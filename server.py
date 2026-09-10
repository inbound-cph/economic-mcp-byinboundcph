"""
e-conomic MCP Server
--------------------
A FastMCP server exposing the Visma e-conomic REST API (https://restapi.e-conomic.com)
as MCP tools. Designed for HTTP (Streamable HTTP) transport, deployable on Railway.

e-conomic API tokens:
  - ECONOMIC_APP_SECRET_TOKEN       -> X-AppSecretToken header
  - ECONOMIC_AGREEMENT_GRANT_TOKEN  -> X-AgreementGrantToken header

Both default to "demo" which gives read-only access to the e-conomic demo agreement.

Protecting the MCP endpoint (see auth.py): Google login, Microsoft login or an access
key. The server refuses to start without one of them unless MCP_ALLOW_UNAUTHENTICATED=true.
MCP_READ_ONLY=true hides every write tool.
"""

import asyncio
import base64
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Literal, Optional
from urllib.parse import quote, urlsplit
from uuid import uuid4

import httpx
from dotenv import load_dotenv

load_dotenv()

# On Railway, keep OAuth client registrations and encrypted login sessions on the
# attached volume (if any) so users stay logged in across deploys.
if os.environ.get("RAILWAY_VOLUME_MOUNT_PATH") and not os.environ.get("FASTMCP_HOME"):
    os.environ["FASTMCP_HOME"] = os.path.join(os.environ["RAILWAY_VOLUME_MOUNT_PATH"], "fastmcp")
# No outbound calls that are not needed: FastMCP otherwise asks pypi.org for updates at startup.
os.environ.setdefault("FASTMCP_CHECK_FOR_UPDATES", "off")

from fastmcp import FastMCP  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402

from auth import AuditMiddleware, AuthConfigError, build_auth_provider, resolve_auth_settings  # noqa: E402

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("economic-mcp")


def _read_float_setting(name: str, default: float, minimum: float) -> float:
    raw_value = os.environ.get(name, str(default))
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number") from exc
    if value < minimum:
        raise RuntimeError(f"{name} must be at least {minimum}")
    return value


def _read_int_setting(name: str, default: int, minimum: int, maximum: int) -> int:
    raw_value = os.environ.get(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


def _read_bool_setting(name: str, default: bool) -> bool:
    raw_value = os.environ.get(name)
    if raw_value is None or not raw_value.strip():
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be true or false")


def _validated_base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    is_local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not is_local_http:
        raise RuntimeError("ECONOMIC_BASE_URL must use HTTPS, except for localhost testing")
    if not parsed.netloc or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise RuntimeError("ECONOMIC_BASE_URL must be an absolute URL without credentials, query parameters, or fragments")
    if parsed.path not in {"", "/"}:
        raise RuntimeError("ECONOMIC_BASE_URL cannot contain a path")
    return normalized


BASE_URL = _validated_base_url(os.environ.get("ECONOMIC_BASE_URL", "https://restapi.e-conomic.com"))
APP_SECRET_TOKEN = os.environ.get("ECONOMIC_APP_SECRET_TOKEN", "demo").strip()
AGREEMENT_GRANT_TOKEN = os.environ.get("ECONOMIC_AGREEMENT_GRANT_TOKEN", "demo").strip()
REQUEST_TIMEOUT_SECONDS = _read_float_setting("ECONOMIC_REQUEST_TIMEOUT_SECONDS", 30.0, 1.0)
MAX_RETRIES = _read_int_setting("ECONOMIC_MAX_RETRIES", 2, 0, 5)
READ_ONLY = _read_bool_setting("MCP_READ_ONLY", False)
ALLOW_UNAUTHENTICATED = _read_bool_setting("MCP_ALLOW_UNAUTHENTICATED", False)

if not APP_SECRET_TOKEN or not AGREEMENT_GRANT_TOKEN:
    raise RuntimeError("Both e-conomic API tokens must be non-empty")

HEADERS = {
    "X-AppSecretToken": APP_SECRET_TOKEN,
    "X-AgreementGrantToken": AGREEMENT_GRANT_TOKEN,
    "Content-Type": "application/json",
}

_http_client: Optional[httpx.AsyncClient] = None


class EconomicAPIError(RuntimeError):
    def __init__(self, status_code: int, method: str, path: str, detail: Any) -> None:
        self.status_code = status_code
        self.method = method
        self.path = path
        self.detail = detail
        if isinstance(detail, dict):
            message = detail.get("message") or detail.get("developerHint") or str(detail)
            log_id = detail.get("logId")
        else:
            message = str(detail)
            log_id = None
        suffix = f" (logId: {log_id})" if log_id else ""
        super().__init__(f"e-conomic API error {status_code} on {method} {path}: {message}{suffix}")


def _build_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{BASE_URL}/",
        headers=HEADERS,
        timeout=httpx.Timeout(REQUEST_TIMEOUT_SECONDS, connect=min(10.0, REQUEST_TIMEOUT_SECONDS)),
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        follow_redirects=False,
    )


@asynccontextmanager
async def _server_lifespan(server):
    global _http_client
    client = _build_http_client()
    _http_client = client
    try:
        yield {}
    finally:
        await client.aclose()
        if _http_client is client:
            _http_client = None


try:
    AUTH_SETTINGS = resolve_auth_settings(os.environ)
except AuthConfigError as exc:
    raise RuntimeError(f"Invalid authentication configuration: {exc}") from exc

if AUTH_SETTINGS.mode == "none" and not ALLOW_UNAUTHENTICATED:
    raise RuntimeError(
        "No authentication is configured, so the server refuses to start. Configure Google login "
        "(GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET plus MCP_ALLOWED_EMAILS or MCP_ALLOWED_DOMAINS), "
        "Microsoft login (AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID) or an access key "
        "(MCP_AUTH_TOKEN). For local testing only, set MCP_ALLOW_UNAUTHENTICATED=true."
    )

_auth = build_auth_provider(AUTH_SETTINGS)

if _auth is None:
    logger.warning("MCP_ALLOW_UNAUTHENTICATED=true - the server is UNPROTECTED. Never expose it publicly.")
else:
    logger.info("Authentication: %s", AUTH_SETTINGS.summary())
if READ_ONLY:
    logger.info("Read-only mode ENABLED: write tools are hidden and economic_api_request accepts GET only")

mcp = FastMCP(
    name="e-conomic MCP",
    instructions=(
        "Tools for the Visma e-conomic accounting platform (e-conomic.dk). "
        "Query customers, products, invoices, accounts, journal entries and more. "
        "List endpoints support pagination via skip_pages/page_size and e-conomic "
        "filter syntax, e.g. name$like:acme or balance$gt:1000."
    ),
    lifespan=_server_lifespan,
    auth=_auth,
    middleware=[AuditMiddleware()],
)

# Tool annotations tell MCP clients which tools are safe and which change the books.
_READ = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True}
_CREATE = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False}
_MODIFY = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False}


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

_CUSTOM_IDENTIFIER_REPLACEMENTS = {
    "<": "0",
    ">": "1",
    "*": "2",
    "%": "3",
    ":": "4",
    "&": "5",
    "/": "6",
    "\\": "7",
    "_": "8",
    " ": "9",
    "?": "10",
    ".": "11",
    "#": "12",
    "+": "13",
}
_RETRYABLE_STATUS_CODES = {429, 502, 503, 504}


def _encode_identifier(value: Any) -> str:
    text = str(value)
    if not text:
        raise ValueError("Resource identifier cannot be empty")
    return "".join(
        f"_{_CUSTOM_IDENTIFIER_REPLACEMENTS[character]}_"
        if character in _CUSTOM_IDENTIFIER_REPLACEMENTS
        else quote(character, safe="-")
        for character in text
    )


def _validate_api_path(path: str) -> str:
    if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
        raise ValueError("API path must start with exactly one '/'")
    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("API path cannot contain a host, query string, or fragment; use params instead")
    if any(segment in {".", ".."} for segment in parsed.path.split("/")):
        raise ValueError("API path cannot contain relative path segments")
    return parsed.path


def _response_error_detail(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text[:2000] or response.reason_phrase


def _retry_delay(response: Optional[httpx.Response], attempt: int) -> float:
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(max(float(retry_after), 0.0), 30.0)
            except ValueError:
                pass
    return min(0.5 * (2 ** attempt), 4.0)


async def _send_request(
    method: str,
    path: str,
    params: Optional[dict] = None,
    json: Any = None,
    idempotency_key: Optional[str] = None,
    accept: str = "application/json",
) -> httpx.Response:
    method = method.upper()
    path = _validate_api_path(path)
    request_headers = {"Accept": accept}
    if json is not None:
        request_headers["Content-Type"] = "application/json"
    if method != "GET":
        request_headers["Idempotency-Key"] = idempotency_key or str(uuid4())

    owned_client = _http_client is None
    client = _build_http_client() if owned_client else _http_client
    assert client is not None
    try:
        for attempt in range(MAX_RETRIES + 1):
            response: Optional[httpx.Response] = None
            try:
                response = await client.request(
                    method,
                    path,
                    headers=request_headers,
                    params=params,
                    json=json,
                )
            except httpx.RequestError as exc:
                if attempt >= MAX_RETRIES:
                    raise RuntimeError(
                        f"Could not reach e-conomic API for {method} {path}: {type(exc).__name__}"
                    ) from exc
                logger.warning("Retrying %s %s after transport error (%s)", method, path, type(exc).__name__)
                await asyncio.sleep(_retry_delay(None, attempt))
                continue

            if response.status_code not in _RETRYABLE_STATUS_CODES or attempt >= MAX_RETRIES:
                return response
            logger.warning("Retrying %s %s after HTTP %s", method, path, response.status_code)
            await asyncio.sleep(_retry_delay(response, attempt))
        raise RuntimeError(f"Request retry loop ended unexpectedly for {method} {path}")
    finally:
        if owned_client:
            await client.aclose()


async def _request(
    method: str,
    path: str,
    params: Optional[dict] = None,
    json: Any = None,
    idempotency_key: Optional[str] = None,
) -> Any:
    response = await _send_request(method, path, params, json, idempotency_key)
    if response.status_code >= 400:
        raise EconomicAPIError(response.status_code, method.upper(), path, _response_error_detail(response))
    if response.status_code == 204 or not response.content:
        return {"status": "success", "httpStatus": response.status_code}
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"e-conomic API returned invalid JSON for {method.upper()} {path}"
        ) from exc


async def _get_collection(path: str, skip_pages: int = 0, page_size: int = 20, filter: Optional[str] = None) -> Any:
    if skip_pages < 0:
        raise ValueError("skip_pages must be zero or greater")
    if not 1 <= page_size <= 1000:
        raise ValueError("page_size must be between 1 and 1000")
    params: dict[str, Any] = {"skippages": skip_pages, "pagesize": page_size}
    if filter:
        params["filter"] = filter
    return await _request("GET", path, params=params)


async def _request_pdf(path: str) -> Any:
    """Fetch a PDF from the e-conomic REST API and return it base64-encoded."""
    response = await _send_request("GET", path, accept="application/pdf")
    if response.status_code >= 400:
        raise EconomicAPIError(response.status_code, "GET", path, _response_error_detail(response))
    content_type = response.headers.get("Content-Type", "application/pdf").split(";", 1)[0]
    if content_type != "application/pdf":
        raise RuntimeError(f"e-conomic API returned {content_type}, expected application/pdf")
    return {
        "contentType": content_type,
        "sizeBytes": len(response.content),
        "base64": base64.b64encode(response.content).decode("ascii"),
    }


# ---------------------------------------------------------------------------
# Company / agreement
# ---------------------------------------------------------------------------

@mcp.tool(annotations=_READ)
async def get_company_info() -> Any:
    """Get information about the connected e-conomic agreement (company name, address,
    agreement number, modules, user info, etc.)."""
    return await _request("GET", "/self")


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------

@mcp.tool(annotations=_READ)
async def list_customers(skip_pages: int = 0, page_size: int = 20, filter: Optional[str] = None) -> Any:
    """List customers. Optional e-conomic filter, e.g. 'name$like:acme' or 'balance$gt:0'."""
    return await _get_collection("/customers", skip_pages, page_size, filter)


@mcp.tool(annotations=_READ)
async def get_customer(customer_number: int) -> Any:
    """Get a single customer by its customer number."""
    return await _request("GET", f"/customers/{customer_number}")


@mcp.tool(tags={"write"}, annotations=_CREATE)
async def create_customer(
    name: str,
    currency: str,
    customer_group_number: int,
    payment_terms_number: int,
    vat_zone_number: int,
    email: Optional[str] = None,
    address: Optional[str] = None,
    zip: Optional[str] = None,
    city: Optional[str] = None,
    country: Optional[str] = None,
    corporate_identification_number: Optional[str] = None,
) -> Any:
    """Create a new customer. Requires name, currency (e.g. 'DKK'), customer group number,
    payment terms number and VAT zone number. Use list_customer_groups, list_payment_terms
    and list_vat_zones to find valid values."""
    body: dict[str, Any] = {
        "name": name,
        "currency": currency,
        "customerGroup": {"customerGroupNumber": customer_group_number},
        "paymentTerms": {"paymentTermsNumber": payment_terms_number},
        "vatZone": {"vatZoneNumber": vat_zone_number},
    }
    if email:
        body["email"] = email
    if address:
        body["address"] = address
    if zip:
        body["zip"] = zip
    if city:
        body["city"] = city
    if country:
        body["country"] = country
    if corporate_identification_number:
        body["corporateIdentificationNumber"] = corporate_identification_number
    return await _request("POST", "/customers", json=body)


@mcp.tool(tags={"write"}, annotations=_MODIFY)
async def update_customer(customer_number: int, updates: dict) -> Any:
    """Update fields on an existing customer. Fetches the current customer, merges the
    given updates (e-conomic field names, e.g. {"name": "New Name", "email": "a@b.dk"})
    and PUTs the result back."""
    current = await _request("GET", f"/customers/{customer_number}")
    current.update(updates)
    return await _request("PUT", f"/customers/{customer_number}", json=current)


@mcp.tool(tags={"write"}, annotations=_MODIFY)
async def delete_customer(customer_number: int) -> Any:
    """Delete a customer. Only possible if the customer has no booked entries."""
    return await _request("DELETE", f"/customers/{customer_number}")


@mcp.tool(annotations=_READ)
async def list_customer_contacts(customer_number: int, skip_pages: int = 0, page_size: int = 20) -> Any:
    """List contact persons for a specific customer."""
    return await _get_collection(f"/customers/{customer_number}/contacts", skip_pages, page_size)


@mcp.tool(annotations=_READ)
async def list_customer_delivery_locations(customer_number: int, skip_pages: int = 0, page_size: int = 20) -> Any:
    """List delivery locations for a specific customer."""
    return await _get_collection(f"/customers/{customer_number}/delivery-locations", skip_pages, page_size)


@mcp.tool(annotations=_READ)
async def get_customer_draft_invoices(customer_number: int, skip_pages: int = 0, page_size: int = 20) -> Any:
    """List draft invoices belonging to a specific customer."""
    return await _get_collection(f"/customers/{customer_number}/invoices/drafts", skip_pages, page_size)


@mcp.tool(annotations=_READ)
async def get_customer_booked_invoices(customer_number: int, skip_pages: int = 0, page_size: int = 20) -> Any:
    """List booked invoices belonging to a specific customer."""
    return await _get_collection(f"/customers/{customer_number}/invoices/booked", skip_pages, page_size)


@mcp.tool(annotations=_READ)
async def get_customer_totals(customer_number: int) -> Any:
    """Get invoice totals (booked and drafts) for a specific customer."""
    return await _request("GET", f"/customers/{customer_number}/totals")


@mcp.tool(annotations=_READ)
async def list_customer_groups(skip_pages: int = 0, page_size: int = 20) -> Any:
    """List customer groups on the agreement."""
    return await _get_collection("/customer-groups", skip_pages, page_size)


# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------

@mcp.tool(annotations=_READ)
async def list_suppliers(skip_pages: int = 0, page_size: int = 20, filter: Optional[str] = None) -> Any:
    """List suppliers. Optional e-conomic filter, e.g. 'name$like:acme'."""
    return await _get_collection("/suppliers", skip_pages, page_size, filter)


@mcp.tool(annotations=_READ)
async def get_supplier(supplier_number: int) -> Any:
    """Get a single supplier by its supplier number."""
    return await _request("GET", f"/suppliers/{supplier_number}")


@mcp.tool(tags={"write"}, annotations=_CREATE)
async def create_supplier(
    name: str,
    currency: str,
    supplier_group_number: int,
    payment_terms_number: int,
    vat_zone_number: int,
    email: Optional[str] = None,
    address: Optional[str] = None,
    zip: Optional[str] = None,
    city: Optional[str] = None,
    country: Optional[str] = None,
    corporate_identification_number: Optional[str] = None,
) -> Any:
    """Create a new supplier. Use list_supplier_groups, list_payment_terms and
    list_vat_zones to find valid reference numbers."""
    body: dict[str, Any] = {
        "name": name,
        "currency": currency,
        "supplierGroup": {"supplierGroupNumber": supplier_group_number},
        "paymentTerms": {"paymentTermsNumber": payment_terms_number},
        "vatZone": {"vatZoneNumber": vat_zone_number},
    }
    if email:
        body["email"] = email
    if address:
        body["address"] = address
    if zip:
        body["zip"] = zip
    if city:
        body["city"] = city
    if country:
        body["country"] = country
    if corporate_identification_number:
        body["corporateIdentificationNumber"] = corporate_identification_number
    return await _request("POST", "/suppliers", json=body)


@mcp.tool(annotations=_READ)
async def list_supplier_groups(skip_pages: int = 0, page_size: int = 20) -> Any:
    """List supplier groups on the agreement."""
    return await _get_collection("/supplier-groups", skip_pages, page_size)


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

@mcp.tool(annotations=_READ)
async def list_products(skip_pages: int = 0, page_size: int = 20, filter: Optional[str] = None) -> Any:
    """List products. Optional e-conomic filter, e.g. 'name$like:widget'."""
    return await _get_collection("/products", skip_pages, page_size, filter)


@mcp.tool(annotations=_READ)
async def get_product(product_number: str) -> Any:
    """Get a single product by its product number."""
    return await _request("GET", f"/products/{_encode_identifier(product_number)}")


@mcp.tool(annotations=_READ)
async def list_product_groups(skip_pages: int = 0, page_size: int = 20) -> Any:
    """List product groups on the agreement."""
    return await _get_collection("/product-groups", skip_pages, page_size)


@mcp.tool(tags={"write"}, annotations=_CREATE)
async def create_product(
    product_number: str,
    name: str,
    product_group_number: int,
    sales_price: Optional[float] = None,
    cost_price: Optional[float] = None,
    description: Optional[str] = None,
    unit_number: Optional[int] = None,
    barred: bool = False,
) -> Any:
    """Create a new product. Use list_product_groups and list_units for valid reference numbers."""
    body: dict[str, Any] = {
        "productNumber": product_number,
        "name": name,
        "productGroup": {"productGroupNumber": product_group_number},
        "barred": barred,
    }
    if sales_price is not None:
        body["salesPrice"] = sales_price
    if cost_price is not None:
        body["costPrice"] = cost_price
    if description:
        body["description"] = description
    if unit_number is not None:
        body["unit"] = {"unitNumber": unit_number}
    return await _request("POST", "/products", json=body)


@mcp.tool(tags={"write"}, annotations=_MODIFY)
async def update_product(product_number: str, updates: dict) -> Any:
    """Update fields on an existing product. Fetches the current product, merges the given
    updates (e-conomic field names, e.g. {"salesPrice": 995, "name": "New name"}) and PUTs it back."""
    encoded_product_number = _encode_identifier(product_number)
    current = await _request("GET", f"/products/{encoded_product_number}")
    current.update(updates)
    return await _request("PUT", f"/products/{encoded_product_number}", json=current)


@mcp.tool(tags={"write"}, annotations=_MODIFY)
async def delete_product(product_number: str) -> Any:
    """Delete a product. Only possible if the product is not used on any documents."""
    return await _request("DELETE", f"/products/{_encode_identifier(product_number)}")


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

@mcp.tool(annotations=_READ)
async def list_draft_invoices(skip_pages: int = 0, page_size: int = 20, filter: Optional[str] = None) -> Any:
    """List draft (unbooked) invoices. Optional filter, e.g. 'customer.customerNumber$eq:123'."""
    return await _get_collection("/invoices/drafts", skip_pages, page_size, filter)


@mcp.tool(annotations=_READ)
async def get_draft_invoice(draft_invoice_number: int) -> Any:
    """Get a single draft invoice, including its lines."""
    return await _request("GET", f"/invoices/drafts/{draft_invoice_number}")


@mcp.tool(annotations=_READ)
async def list_booked_invoices(skip_pages: int = 0, page_size: int = 20, filter: Optional[str] = None) -> Any:
    """List booked invoices. Optional filter, e.g. 'date$gte:2026-01-01' or 'customer.customerNumber$eq:123'."""
    return await _get_collection("/invoices/booked", skip_pages, page_size, filter)


@mcp.tool(annotations=_READ)
async def get_booked_invoice(booked_invoice_number: int) -> Any:
    """Get a single booked invoice, including its lines."""
    return await _request("GET", f"/invoices/booked/{booked_invoice_number}")


@mcp.tool(annotations=_READ)
async def list_paid_invoices(skip_pages: int = 0, page_size: int = 20) -> Any:
    """List booked invoices that have been fully paid."""
    return await _get_collection("/invoices/paid", skip_pages, page_size)


@mcp.tool(annotations=_READ)
async def list_unpaid_invoices(skip_pages: int = 0, page_size: int = 20) -> Any:
    """List booked invoices that have not yet been fully paid."""
    return await _get_collection("/invoices/unpaid", skip_pages, page_size)


@mcp.tool(annotations=_READ)
async def list_overdue_invoices(skip_pages: int = 0, page_size: int = 20) -> Any:
    """List booked invoices that are past their due date and not fully paid."""
    return await _get_collection("/invoices/overdue", skip_pages, page_size)


@mcp.tool(annotations=_READ)
async def list_not_due_invoices(skip_pages: int = 0, page_size: int = 20) -> Any:
    """List booked invoices that are unpaid but not yet past their due date."""
    return await _get_collection("/invoices/not-due", skip_pages, page_size)


@mcp.tool(annotations=_READ)
async def list_sent_invoices(skip_pages: int = 0, page_size: int = 20) -> Any:
    """List draft invoices that have been registered as sent to the customer."""
    return await _get_collection("/invoices/sent", skip_pages, page_size)


@mcp.tool(annotations=_READ)
async def get_invoice_totals() -> Any:
    """Get aggregate invoice totals for the agreement (booked, drafts, paid, unpaid, overdue)."""
    return await _request("GET", "/invoices/totals")


@mcp.tool(annotations=_READ)
async def get_draft_invoice_pdf(draft_invoice_number: int) -> Any:
    """Download a draft invoice as PDF (returned base64-encoded)."""
    return await _request_pdf(f"/invoices/drafts/{draft_invoice_number}/pdf")


@mcp.tool(annotations=_READ)
async def get_booked_invoice_pdf(booked_invoice_number: int) -> Any:
    """Download a booked invoice as PDF (returned base64-encoded)."""
    return await _request_pdf(f"/invoices/booked/{booked_invoice_number}/pdf")


@mcp.tool(tags={"write"}, annotations=_MODIFY)
async def register_invoice_as_sent(
    draft_invoice_number: int,
    send_by: Literal["ean", "Email"] = "ean",
) -> Any:
    """Book a draft invoice and send it through e-conomic. This is irreversible. Use
    send_by='ean' for e-invoicing or send_by='Email' for configured invoice recipients."""
    body = {
        "draftInvoice": {"draftInvoiceNumber": draft_invoice_number},
        "sendBy": send_by,
    }
    return await _request("POST", "/invoices/booked", json=body)


@mcp.tool(tags={"write"}, annotations=_MODIFY)
async def update_draft_invoice(draft_invoice_number: int, updates: dict) -> Any:
    """Update a draft invoice. Fetches the current draft, merges the given updates
    (e-conomic field names, e.g. {"notes": {"heading": "..."}, "lines": [...]}) and PUTs it back.
    Note: to change lines you must supply the complete 'lines' array."""
    current = await _request("GET", f"/invoices/drafts/{draft_invoice_number}")
    current.update(updates)
    return await _request("PUT", f"/invoices/drafts/{draft_invoice_number}", json=current)


@mcp.tool(tags={"write"}, annotations=_CREATE)
async def create_draft_invoice(
    customer_number: int,
    currency: str,
    date: str,
    layout_number: int,
    payment_terms_number: int,
    recipient_name: str,
    recipient_vat_zone_number: int,
    lines: list[dict],
    notes_heading: Optional[str] = None,
) -> Any:
    """Create a draft invoice.

    Args:
        customer_number: The e-conomic customer number.
        currency: Currency code, e.g. 'DKK'.
        date: Invoice date in YYYY-MM-DD format.
        layout_number: Invoice layout number (see list_layouts).
        payment_terms_number: Payment terms number (see list_payment_terms).
        recipient_name: Name printed on the invoice recipient block.
        recipient_vat_zone_number: VAT zone number of the recipient (see list_vat_zones).
        lines: Invoice lines, each a dict like:
            {"description": "Consulting", "quantity": 2, "unitNetPrice": 500,
             "productNumber": "1"}  (productNumber is required by e-conomic).
        notes_heading: Optional heading shown on the invoice.
    """
    api_lines = []
    for line in lines:
        api_line: dict[str, Any] = {
            "description": line.get("description", ""),
            "quantity": line.get("quantity", 1),
            "unitNetPrice": line.get("unitNetPrice", 0),
        }
        if "productNumber" in line:
            api_line["product"] = {"productNumber": str(line["productNumber"])}
        if "discountPercentage" in line:
            api_line["discountPercentage"] = line["discountPercentage"]
        api_lines.append(api_line)

    body: dict[str, Any] = {
        "date": date,
        "currency": currency,
        "customer": {"customerNumber": customer_number},
        "layout": {"layoutNumber": layout_number},
        "paymentTerms": {"paymentTermsNumber": payment_terms_number},
        "recipient": {
            "name": recipient_name,
            "vatZone": {"vatZoneNumber": recipient_vat_zone_number},
        },
        "lines": api_lines,
    }
    if notes_heading:
        body["notes"] = {"heading": notes_heading}
    return await _request("POST", "/invoices/drafts", json=body)


@mcp.tool(tags={"write"}, annotations=_MODIFY)
async def book_draft_invoice(
    draft_invoice_number: int,
    send_by: Literal["none", "ean", "Email"] = "none",
    book_with_number: Optional[int] = None,
) -> Any:
    """Book (finalize) a draft invoice. This is irreversible. Optionally select e-invoicing
    or email delivery and a specific booked invoice number."""
    body: dict[str, Any] = {
        "draftInvoice": {"draftInvoiceNumber": draft_invoice_number},
        "sendBy": send_by,
    }
    if book_with_number is not None:
        body["bookWithNumber"] = book_with_number
    return await _request("POST", "/invoices/booked", json=body)


@mcp.tool(tags={"write"}, annotations=_MODIFY)
async def delete_draft_invoice(draft_invoice_number: int) -> Any:
    """Delete a draft invoice."""
    return await _request("DELETE", f"/invoices/drafts/{draft_invoice_number}")


# ---------------------------------------------------------------------------
# Quotes
# ---------------------------------------------------------------------------

@mcp.tool(annotations=_READ)
async def list_draft_quotes(skip_pages: int = 0, page_size: int = 20, filter: Optional[str] = None) -> Any:
    """List draft quotes. Optional filter, e.g. 'customer.customerNumber$eq:123'."""
    return await _get_collection("/quotes/drafts", skip_pages, page_size, filter)


@mcp.tool(annotations=_READ)
async def get_draft_quote(quote_number: int) -> Any:
    """Get a single draft quote, including its lines."""
    return await _request("GET", f"/quotes/drafts/{quote_number}")


@mcp.tool(annotations=_READ)
async def list_sent_quotes(skip_pages: int = 0, page_size: int = 20) -> Any:
    """List quotes that have been sent to customers."""
    return await _get_collection("/quotes/sent", skip_pages, page_size)


@mcp.tool(annotations=_READ)
async def list_archived_quotes(skip_pages: int = 0, page_size: int = 20) -> Any:
    """List archived quotes (e.g. quotes upgraded to orders/invoices)."""
    return await _get_collection("/quotes/archived", skip_pages, page_size)


@mcp.tool(tags={"write"}, annotations=_MODIFY)
async def register_quote_as_sent(quote_number: int) -> Any:
    """Register a draft quote as sent. e-conomic requires the complete unchanged quote document."""
    quote_document = await _request("GET", f"/quotes/drafts/{quote_number}")
    return await _request("POST", "/quotes/sent", json=quote_document)


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

@mcp.tool(annotations=_READ)
async def list_draft_orders(skip_pages: int = 0, page_size: int = 20, filter: Optional[str] = None) -> Any:
    """List draft orders. Optional filter, e.g. 'customer.customerNumber$eq:123'."""
    return await _get_collection("/orders/drafts", skip_pages, page_size, filter)


@mcp.tool(annotations=_READ)
async def get_draft_order(order_number: int) -> Any:
    """Get a single draft order, including its lines."""
    return await _request("GET", f"/orders/drafts/{order_number}")


@mcp.tool(annotations=_READ)
async def list_sent_orders(skip_pages: int = 0, page_size: int = 20) -> Any:
    """List orders that have been sent to customers."""
    return await _get_collection("/orders/sent", skip_pages, page_size)


@mcp.tool(annotations=_READ)
async def list_archived_orders(skip_pages: int = 0, page_size: int = 20) -> Any:
    """List archived orders (e.g. orders upgraded to invoices)."""
    return await _get_collection("/orders/archived", skip_pages, page_size)


# ---------------------------------------------------------------------------
# Accounting
# ---------------------------------------------------------------------------

@mcp.tool(annotations=_READ)
async def list_accounts(skip_pages: int = 0, page_size: int = 50, filter: Optional[str] = None) -> Any:
    """List accounts in the chart of accounts. Optional filter, e.g. 'accountType$eq:profitAndLoss'."""
    return await _get_collection("/accounts", skip_pages, page_size, filter)


@mcp.tool(annotations=_READ)
async def get_account(account_number: int) -> Any:
    """Get a single account by its account number."""
    return await _request("GET", f"/accounts/{account_number}")


@mcp.tool(annotations=_READ)
async def get_account_entries(
    account_number: int,
    accounting_year: str,
    skip_pages: int = 0,
    page_size: int = 50,
    filter: Optional[str] = None,
) -> Any:
    """List entries for an account in a required accounting year, e.g. '2026' or '2025/2026'."""
    encoded_year = _encode_identifier(accounting_year)
    path = f"/accounts/{account_number}/accounting-years/{encoded_year}/entries"
    return await _get_collection(path, skip_pages, page_size, filter)


@mcp.tool(annotations=_READ)
async def list_accounting_years(skip_pages: int = 0, page_size: int = 20) -> Any:
    """List accounting (fiscal) years on the agreement."""
    return await _get_collection("/accounting-years", skip_pages, page_size)


@mcp.tool(annotations=_READ)
async def get_accounting_year_entries(year: str, skip_pages: int = 0, page_size: int = 50, filter: Optional[str] = None) -> Any:
    """List all entries for a given accounting year (e.g. '2026'). Optional filter,
    e.g. 'account.accountNumber$eq:1000'."""
    return await _get_collection(f"/accounting-years/{_encode_identifier(year)}/entries", skip_pages, page_size, filter)


@mcp.tool(annotations=_READ)
async def get_accounting_year_totals(year: str, skip_pages: int = 0, page_size: int = 100) -> Any:
    """Get account totals for a given accounting year (e.g. '2026'). Useful for P&L and balance overviews."""
    return await _get_collection(f"/accounting-years/{_encode_identifier(year)}/totals", skip_pages, page_size)


@mcp.tool(annotations=_READ)
async def list_accounting_year_periods(year: str, skip_pages: int = 0, page_size: int = 20) -> Any:
    """List the periods (typically months) of a given accounting year (e.g. '2026')."""
    return await _get_collection(f"/accounting-years/{_encode_identifier(year)}/periods", skip_pages, page_size)


@mcp.tool(annotations=_READ)
async def get_accounting_period_totals(year: str, period_number: int, skip_pages: int = 0, page_size: int = 100) -> Any:
    """Get account totals for a specific period of an accounting year."""
    encoded_year = _encode_identifier(year)
    return await _get_collection(f"/accounting-years/{encoded_year}/periods/{period_number}/totals", skip_pages, page_size)


@mcp.tool(annotations=_READ)
async def list_journals(skip_pages: int = 0, page_size: int = 20) -> Any:
    """List journals (kassekladder) on the agreement."""
    return await _get_collection("/journals", skip_pages, page_size)


@mcp.tool(annotations=_READ)
async def get_journal_entries(journal_number: int, skip_pages: int = 0, page_size: int = 50) -> Any:
    """List pending (unbooked) entries in a specific journal."""
    return await _get_collection(f"/journals/{journal_number}/entries", skip_pages, page_size)


@mcp.tool(annotations=_READ)
async def get_journal_vouchers(journal_number: int, skip_pages: int = 0, page_size: int = 50) -> Any:
    """List pending (unbooked) vouchers in a specific journal."""
    return await _get_collection(f"/journals/{journal_number}/vouchers", skip_pages, page_size)


@mcp.tool(tags={"write"}, annotations=_CREATE)
async def create_finance_voucher(
    journal_number: int,
    accounting_year: str,
    account_number: int,
    amount: float,
    currency: str,
    date: str,
    text: str,
    contra_account_number: Optional[int] = None,
) -> Any:
    """Create a finance voucher (manual posting) in a journal. The voucher stays in the
    journal until it is booked in the e-conomic UI.

    Args:
        journal_number: Journal to add the voucher to (see list_journals).
        accounting_year: Accounting year string, e.g. '2026'.
        account_number: Account to post to.
        amount: Amount (positive = debit, negative = credit, per e-conomic convention).
        currency: Currency code, e.g. 'DKK'.
        date: Entry date in YYYY-MM-DD format.
        text: Entry text.
        contra_account_number: Optional contra account for a balanced posting.
    """
    entry: dict[str, Any] = {
        "account": {"accountNumber": account_number},
        "amount": amount,
        "currency": {"code": currency},
        "date": date,
        "text": text,
    }
    if contra_account_number is not None:
        entry["contraAccount"] = {"accountNumber": contra_account_number}
    body = {
        "accountingYear": {"year": accounting_year},
        "entries": {"financeVouchers": [entry]},
    }
    return await _request("POST", f"/journals/{journal_number}/vouchers", json=body)


@mcp.tool(tags={"write"}, annotations=_CREATE)
async def create_journal_voucher(journal_number: int, voucher: dict) -> Any:
    """Create a raw voucher in a journal for advanced cases (customer payments, supplier
    invoices/payments, multi-line finance vouchers). The voucher dict must follow the
    e-conomic voucher schema, e.g.:
    {"accountingYear": {"year": "2026"},
     "entries": {"customerPayments": [...], "supplierInvoices": [...], "financeVouchers": [...]}}"""
    return await _request("POST", f"/journals/{journal_number}/vouchers", json=voucher)


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

@mcp.tool(annotations=_READ)
async def list_payment_terms(skip_pages: int = 0, page_size: int = 20) -> Any:
    """List payment terms defined on the agreement."""
    return await _get_collection("/payment-terms", skip_pages, page_size)


@mcp.tool(annotations=_READ)
async def list_vat_zones(skip_pages: int = 0, page_size: int = 20) -> Any:
    """List VAT zones (domestic, EU, abroad, etc.)."""
    return await _get_collection("/vat-zones", skip_pages, page_size)


@mcp.tool(annotations=_READ)
async def list_vat_accounts(skip_pages: int = 0, page_size: int = 20) -> Any:
    """List VAT accounts and their rates."""
    return await _get_collection("/vat-accounts", skip_pages, page_size)


@mcp.tool(annotations=_READ)
async def list_currencies(skip_pages: int = 0, page_size: int = 50) -> Any:
    """List currencies available on the agreement."""
    return await _get_collection("/currencies", skip_pages, page_size)


@mcp.tool(annotations=_READ)
async def list_layouts(skip_pages: int = 0, page_size: int = 20) -> Any:
    """List invoice layouts (needed to create draft invoices)."""
    return await _get_collection("/layouts", skip_pages, page_size)


@mcp.tool(annotations=_READ)
async def list_units(skip_pages: int = 0, page_size: int = 20) -> Any:
    """List units (e.g. hours, pcs) defined on the agreement."""
    return await _get_collection("/units", skip_pages, page_size)


@mcp.tool(annotations=_READ)
async def list_departments(skip_pages: int = 0, page_size: int = 20) -> Any:
    """List departments (dimension module) if enabled on the agreement."""
    return await _get_collection("/departments", skip_pages, page_size)


@mcp.tool(annotations=_READ)
async def list_employees(skip_pages: int = 0, page_size: int = 20) -> Any:
    """List employees on the agreement."""
    return await _get_collection("/employees", skip_pages, page_size)


@mcp.tool(annotations=_READ)
async def list_vat_types(skip_pages: int = 0, page_size: int = 20) -> Any:
    """List VAT types on the agreement."""
    return await _get_collection("/vat-types", skip_pages, page_size)


@mcp.tool(annotations=_READ)
async def list_payment_types(skip_pages: int = 0, page_size: int = 20) -> Any:
    """List payment types on the agreement."""
    return await _get_collection("/payment-types", skip_pages, page_size)


@mcp.tool(annotations=_READ)
async def list_departmental_distributions(skip_pages: int = 0, page_size: int = 20) -> Any:
    """List departmental distributions (dimension module) if enabled on the agreement."""
    return await _get_collection("/departmental-distributions", skip_pages, page_size)


# ---------------------------------------------------------------------------
# Generic escape hatch
# ---------------------------------------------------------------------------

@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True})
async def economic_api_request(
    method: str,
    path: str,
    params: Optional[dict] = None,
    body: Optional[dict] = None,
) -> Any:
    """Call any e-conomic REST API endpoint directly. Use this for endpoints not covered
    by a dedicated tool. See https://restdocs.e-conomic.com/ for the full API reference.

    Args:
        method: HTTP method (GET, POST, PUT, DELETE, PATCH).
        path: API path starting with '/', e.g. '/customers/1/contacts'.
        params: Optional query parameters, e.g. {"skippages": 0, "pagesize": 20, "filter": "name$like:acme"}.
        body: Optional JSON body for POST/PUT/PATCH.
    """
    method = method.upper()
    if method not in {"GET", "POST", "PUT", "DELETE", "PATCH"}:
        raise ValueError(f"Unsupported HTTP method: {method}")
    if READ_ONLY and method != "GET":
        raise ValueError("This server runs in read-only mode (MCP_READ_ONLY=true); only GET requests are allowed")
    path = _validate_api_path(path)
    return await _request(method, path, params=params, json=body)


if READ_ONLY:
    mcp.disable(tags={"write"})


# ---------------------------------------------------------------------------
# Health check (for Railway)
# ---------------------------------------------------------------------------

@mcp.custom_route("/health", methods=["GET"])
async def health_check(request):
    return JSONResponse(
        {"status": "healthy", "service": "economic-mcp", "auth": AUTH_SETTINGS.mode, "readOnly": READ_ONLY}
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = _read_int_setting("PORT", 8000, 1, 65535)
    # Without authentication, only listen on the local machine.
    host = os.environ.get("MCP_HOST", "0.0.0.0" if _auth is not None else "127.0.0.1").strip()
    logger.info("Starting e-conomic MCP server on %s:%s (e-conomic API: %s)", host, port, BASE_URL)
    mcp.run(
        transport="http",
        host=host,
        port=port,
        path="/mcp",
        stateless_http=True,
    )
