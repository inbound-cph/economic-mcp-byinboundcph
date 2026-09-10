import asyncio
import json

import httpx
import pytest
from fastmcp import Client

import server


def run(coro):
    return asyncio.run(coro)


def test_validated_base_url():
    assert server._validated_base_url("https://example.com/") == "https://example.com"
    assert server._validated_base_url("http://localhost:9000") == "http://localhost:9000"


@pytest.mark.parametrize(
    "value",
    [
        "http://example.com",
        "ftp://example.com",
        "https://user:pass@example.com",
        "https://example.com/api",
        "https://example.com?x=1",
        "not-a-url",
    ],
)
def test_validated_base_url_rejects_unsafe_values(value):
    with pytest.raises(RuntimeError):
        server._validated_base_url(value)


def test_settings_validation(monkeypatch):
    monkeypatch.setenv("FLOAT_SETTING", "2.5")
    monkeypatch.setenv("INT_SETTING", "3")
    assert server._read_float_setting("FLOAT_SETTING", 1.0, 1.0) == 2.5
    assert server._read_int_setting("INT_SETTING", 1, 0, 5) == 3

    monkeypatch.setenv("FLOAT_SETTING", "invalid")
    monkeypatch.setenv("INT_SETTING", "6")
    with pytest.raises(RuntimeError, match="must be a number"):
        server._read_float_setting("FLOAT_SETTING", 1.0, 1.0)
    with pytest.raises(RuntimeError, match="must be between"):
        server._read_int_setting("INT_SETTING", 1, 0, 5)


def test_encode_identifier_uses_economic_scheme():
    assert server._encode_identifier("My Product_5%") == "My_9_Product_8_5_3_"
    assert server._encode_identifier("2025/2026") == "2025_6_2026"
    assert server._encode_identifier("æøå") == "%C3%A6%C3%B8%C3%A5"
    with pytest.raises(ValueError, match="cannot be empty"):
        server._encode_identifier("")


@pytest.mark.parametrize(
    "path",
    [
        "customers",
        "//example.com/customers",
        "/../customers",
        "/customers?pagesize=1",
        "/customers#fragment",
        "https://example.com/customers",
    ],
)
def test_validate_api_path_rejects_unsafe_paths(path):
    with pytest.raises(ValueError):
        server._validate_api_path(path)


def test_validate_api_path_accepts_resource_path():
    assert server._validate_api_path("/customers/1/contacts") == "/customers/1/contacts"


def test_get_collection_validates_pagination(monkeypatch):
    calls = []

    async def fake_request(method, path, params=None, json=None, idempotency_key=None):
        calls.append((method, path, params))
        return {"collection": []}

    monkeypatch.setattr(server, "_request", fake_request)
    result = run(server._get_collection("/customers", 2, 50, "name$like:acme"))
    assert result == {"collection": []}
    assert calls == [("GET", "/customers", {"skippages": 2, "pagesize": 50, "filter": "name$like:acme"})]

    with pytest.raises(ValueError, match="zero or greater"):
        run(server._get_collection("/customers", -1, 20))
    with pytest.raises(ValueError, match="between 1 and 1000"):
        run(server._get_collection("/customers", 0, 1001))


async def request_with_transport(monkeypatch, handler, operation):
    client = httpx.AsyncClient(
        base_url=f"{server.BASE_URL}/",
        headers=server.HEADERS,
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(server, "_http_client", client)
    try:
        return await operation
    finally:
        await client.aclose()
        monkeypatch.setattr(server, "_http_client", None)


def test_request_sends_authentication_and_parses_json(monkeypatch):
    def handler(request):
        assert request.headers["X-AppSecretToken"] == server.APP_SECRET_TOKEN
        assert request.headers["X-AgreementGrantToken"] == server.AGREEMENT_GRANT_TOKEN
        assert request.headers["Accept"] == "application/json"
        assert request.url.params["pagesize"] == "3"
        return httpx.Response(200, json={"collection": [{"customerNumber": 1}]})

    result = run(
        request_with_transport(
            monkeypatch,
            handler,
            server._request("GET", "/customers", params={"pagesize": 3}),
        )
    )
    assert result["collection"][0]["customerNumber"] == 1


def test_request_raises_structured_api_error(monkeypatch):
    def handler(request):
        return httpx.Response(
            400,
            json={"message": "Validation error.", "developerHint": "Correct the request.", "logId": "abc-123"},
        )

    with pytest.raises(server.EconomicAPIError) as error:
        run(request_with_transport(monkeypatch, handler, server._request("POST", "/customers", json={})))

    assert error.value.status_code == 400
    assert error.value.detail["developerHint"] == "Correct the request."
    assert "abc-123" in str(error.value)


def test_request_retries_with_same_idempotency_key(monkeypatch):
    attempts = []

    async def no_sleep(delay):
        return None

    def handler(request):
        attempts.append(request.headers["Idempotency-Key"])
        if len(attempts) == 1:
            return httpx.Response(503, json={"message": "Unavailable"})
        return httpx.Response(201, json={"customerNumber": 42})

    monkeypatch.setattr(server.asyncio, "sleep", no_sleep)
    result = run(
        request_with_transport(
            monkeypatch,
            handler,
            server._request("POST", "/customers", json={"name": "Test"}),
        )
    )
    assert result == {"customerNumber": 42}
    assert len(attempts) == 2
    assert attempts[0] == attempts[1]


def test_request_rejects_invalid_json_success_response(monkeypatch):
    def handler(request):
        return httpx.Response(200, text="not-json")

    with pytest.raises(RuntimeError, match="invalid JSON"):
        run(request_with_transport(monkeypatch, handler, server._request("GET", "/customers")))


def test_request_pdf_validates_content_type(monkeypatch):
    def handler(request):
        assert request.headers["Accept"] == "application/pdf"
        return httpx.Response(200, content=b"%PDF-1.7", headers={"Content-Type": "application/pdf"})

    result = run(
        request_with_transport(
            monkeypatch,
            handler,
            server._request_pdf("/invoices/booked/1/pdf"),
        )
    )
    assert result["contentType"] == "application/pdf"
    assert result["sizeBytes"] == 8
    assert result["base64"] == "JVBERi0xLjc="


def test_corrected_tool_paths_and_payloads(monkeypatch):
    calls = []

    async def fake_request(method, path, params=None, json=None, idempotency_key=None):
        calls.append((method, path, json))
        if method == "GET" and path.startswith("/quotes/drafts/"):
            return {"quoteNumber": 7, "customer": {"customerNumber": 1}}
        return {"ok": True}

    async def fake_collection(path, skip_pages=0, page_size=20, filter=None):
        calls.append(("GET_COLLECTION", path, {"filter": filter}))
        return {"collection": []}

    monkeypatch.setattr(server, "_request", fake_request)
    monkeypatch.setattr(server, "_get_collection", fake_collection)

    run(server.get_product("My Product_5%"))
    run(server.get_account_entries(1010, "2025/2026", filter="date$gte:2026-01-01"))
    run(server.register_quote_as_sent(7))
    run(server.register_invoice_as_sent(11, "Email"))
    run(server.book_draft_invoice(12, "none", 5000))

    assert calls[0][1] == "/products/My_9_Product_8_5_3_"
    assert calls[1][1] == "/accounts/1010/accounting-years/2025_6_2026/entries"
    assert calls[2] == ("GET", "/quotes/drafts/7", None)
    assert calls[3][0:2] == ("POST", "/quotes/sent")
    assert calls[3][2]["quoteNumber"] == 7
    assert calls[4][1] == "/invoices/booked"
    assert calls[4][2]["sendBy"] == "Email"
    assert calls[5][2]["bookWithNumber"] == 5000


def test_generic_request_requires_safe_absolute_path(monkeypatch):
    async def fake_request(method, path, params=None, json=None, idempotency_key=None):
        return {"method": method, "path": path}

    monkeypatch.setattr(server, "_request", fake_request)
    assert run(server.economic_api_request("get", "/self")) == {"method": "GET", "path": "/self"}
    with pytest.raises(ValueError):
        run(server.economic_api_request("get", "self"))
    with pytest.raises(ValueError):
        run(server.economic_api_request("trace", "/self"))


def test_health_response():
    response = run(server.health_check(None))
    assert response.status_code == 200
    assert json.loads(response.body) == {
        "status": "healthy",
        "service": "economic-mcp",
        "auth": "none",
        "readOnly": False,
    }


def test_mcp_lists_all_tools():
    async def check_tools():
        async with Client(server.mcp) as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools}
            assert len(tools) == 73
            assert {"get_company_info", "list_customers", "get_account_entries", "economic_api_request"} <= names

    run(check_tools())


def test_mcp_invokes_tool_with_mocked_api(monkeypatch):
    def handler(request):
        assert request.url.path == "/self"
        return httpx.Response(200, json={"agreementNumber": 123, "company": {"name": "Test"}})

    def build_mock_client():
        return httpx.AsyncClient(
            base_url=f"{server.BASE_URL}/",
            headers=server.HEADERS,
            transport=httpx.MockTransport(handler),
        )

    monkeypatch.setattr(server, "_build_http_client", build_mock_client)

    async def call_tool():
        async with Client(server.mcp) as client:
            result = await client.call_tool("get_company_info", {})
            assert result.data["agreementNumber"] == 123

    run(call_tool())
