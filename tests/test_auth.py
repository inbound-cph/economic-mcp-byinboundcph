import asyncio
import logging
import os
import pathlib
import subprocess
import sys

import httpx
import pytest
from fastmcp import Client
from fastmcp.server.auth import AccessToken, MultiAuth
from mcp.server.auth.provider import TokenError

import auth
import server

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
TOKEN = "k" * 40
BASE_ENV = {"MCP_PUBLIC_URL": "https://economic.example.com"}
GOOGLE_ENV = {
    **BASE_ENV,
    "GOOGLE_OAUTH_CLIENT_ID": "123.apps.googleusercontent.com",
    "GOOGLE_OAUTH_CLIENT_SECRET": "GOCSPX-test-secret",
    "MCP_ALLOWED_DOMAINS": "example.com",
}
AZURE_ENV = {
    **BASE_ENV,
    "AZURE_CLIENT_ID": "11111111-1111-1111-1111-111111111111",
    "AZURE_CLIENT_SECRET": "azure-test-secret",
    "AZURE_TENANT_ID": "22222222-2222-2222-2222-222222222222",
}


def run(coro):
    return asyncio.run(coro)


class FakeVerifier:
    """Stands in for Google's tokeninfo / Microsoft's JWKS verification."""

    required_scopes = ["openid"]

    def __init__(self, claims):
        self.claims = claims

    async def verify_token(self, token):
        if self.claims is None:
            return None
        return AccessToken(token=token, client_id="upstream-user", scopes=["openid"], claims=self.claims)


# ---------------------------------------------------------------------------
# Allowlist
# ---------------------------------------------------------------------------


def test_allowlist_matches_emails_and_domains_case_insensitively():
    allowlist = auth.Allowlist.from_env(
        {"MCP_ALLOWED_EMAILS": "Anna@Example.com, bo@firma.dk", "MCP_ALLOWED_DOMAINS": "@Firma.dk eksempel.dk"}
    )
    assert allowlist.allows("anna@example.com")
    assert allowlist.allows("ANNA@EXAMPLE.COM")
    assert allowlist.allows("carl@firma.dk")
    assert allowlist.allows("dorte@eksempel.dk")
    assert not allowlist.allows("eve@example.com")
    assert not allowlist.allows("eve@example.com.evil.dk")
    assert not allowlist.allows("firma.dk")
    assert not allowlist.allows(None)
    assert not allowlist.is_empty
    assert auth.Allowlist.from_env({}).is_empty


@pytest.mark.parametrize(
    "env",
    [
        {"MCP_ALLOWED_EMAILS": "not-an-email"},
        {"MCP_ALLOWED_DOMAINS": "@"},
        {"MCP_ALLOWED_DOMAINS": "user@firma.dk"},
    ],
)
def test_allowlist_rejects_invalid_entries(env):
    with pytest.raises(auth.AuthConfigError):
        auth.Allowlist.from_env(env)


def test_identity_and_verification_claims():
    assert auth.identity_from_claims({"email": " Anna@Example.com "}) == "anna@example.com"
    assert auth.identity_from_claims({"preferred_username": "bo@firma.dk"}) == "bo@firma.dk"
    assert auth.identity_from_claims({"upn": "carl@firma.dk"}) == "carl@firma.dk"
    assert auth.identity_from_claims({"sub": "123", "name": "No Email"}) is None
    assert auth.identity_from_claims(None) is None
    assert auth.email_is_verified({"email_verified": "true"})
    assert auth.email_is_verified({"email_verified": True})
    assert not auth.email_is_verified({"email_verified": "false"})
    assert not auth.email_is_verified({})


# ---------------------------------------------------------------------------
# Settings resolution
# ---------------------------------------------------------------------------


def test_resolve_settings_selects_mode_from_environment():
    assert auth.resolve_auth_settings({}).mode == "none"
    assert auth.resolve_auth_settings({"MCP_AUTH_TOKEN": TOKEN}).mode == "token"

    google = auth.resolve_auth_settings(GOOGLE_ENV)
    assert google.mode == "google"
    assert google.uses_oauth
    assert google.oauth_callback_url == "https://economic.example.com/auth/callback"
    assert "Google login" in google.summary()

    azure = auth.resolve_auth_settings({**AZURE_ENV, "AZURE_API_SCOPE": "economic.read"})
    assert azure.mode == "microsoft"
    assert azure.azure_scope == "economic.read"
    assert auth.resolve_auth_settings(AZURE_ENV).azure_scope == "access_as_user"

    combined = auth.resolve_auth_settings({**GOOGLE_ENV, "MCP_AUTH_TOKEN": TOKEN})
    assert combined.mode == "google"
    assert combined.service_token == TOKEN
    assert "access key" in combined.summary()


def test_public_url_defaults_to_railway_domain_and_strips_trailing_slash():
    settings = auth.resolve_auth_settings(
        {**GOOGLE_ENV, "MCP_PUBLIC_URL": "", "RAILWAY_PUBLIC_DOMAIN": "economic-mcp.up.railway.app"}
    )
    assert settings.public_url == "https://economic-mcp.up.railway.app"
    explicit = auth.resolve_auth_settings({**GOOGLE_ENV, "MCP_PUBLIC_URL": "https://mcp.firma.dk/"})
    assert explicit.public_url == "https://mcp.firma.dk"
    local = auth.resolve_auth_settings({**GOOGLE_ENV, "MCP_PUBLIC_URL": "http://localhost:8000"})
    assert local.public_url == "http://localhost:8000"


@pytest.mark.parametrize(
    "env, message",
    [
        ({"MCP_AUTH_TOKEN": "short"}, "at least 32"),
        ({**GOOGLE_ENV, "GOOGLE_OAUTH_CLIENT_SECRET": ""}, "missing GOOGLE_OAUTH_CLIENT_SECRET"),
        ({**GOOGLE_ENV, "MCP_PUBLIC_URL": ""}, "MCP_PUBLIC_URL"),
        ({**GOOGLE_ENV, "MCP_ALLOWED_DOMAINS": ""}, "MCP_ALLOWED_EMAILS"),
        ({**GOOGLE_ENV, "MCP_PUBLIC_URL": "http://economic.example.com"}, "https"),
        ({**GOOGLE_ENV, "MCP_PUBLIC_URL": "https://economic.example.com/?x=1"}, "plain absolute URL"),
        ({**GOOGLE_ENV, "AZURE_CLIENT_ID": "abc"}, "not both"),
        ({**AZURE_ENV, "AZURE_CLIENT_SECRET": ""}, "missing AZURE_CLIENT_SECRET"),
        ({**AZURE_ENV, "AZURE_TENANT_ID": "organizations"}, "any organisation"),
        ({"MCP_ALLOWED_DOMAINS": "example.com"}, "only take effect"),
        ({**GOOGLE_ENV, "MCP_JWT_SIGNING_KEY": "short"}, "MCP_JWT_SIGNING_KEY"),
    ],
)
def test_resolve_settings_rejects_unsafe_configuration(env, message):
    with pytest.raises(auth.AuthConfigError, match=message):
        auth.resolve_auth_settings(env)


def test_generic_azure_tenant_is_allowed_with_an_allowlist():
    settings = auth.resolve_auth_settings(
        {**AZURE_ENV, "AZURE_TENANT_ID": "organizations", "MCP_ALLOWED_DOMAINS": "firma.dk"}
    )
    assert settings.mode == "microsoft"


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------


def test_token_provider_accepts_only_the_configured_key():
    provider = auth.build_auth_provider(auth.resolve_auth_settings({"MCP_AUTH_TOKEN": TOKEN}))
    accepted = run(provider.verify_token(TOKEN))
    assert accepted is not None
    assert accepted.client_id == auth.SERVICE_TOKEN_CLIENT_ID
    assert run(provider.verify_token("z" * 40)) is None
    assert auth.build_auth_provider(auth.resolve_auth_settings({})) is None


def test_google_provider_enforces_allowlist_at_login_and_on_requests():
    provider = auth.build_auth_provider(auth.resolve_auth_settings(GOOGLE_ENV))
    assert isinstance(provider, auth.GuardedGoogleProvider)
    wrapper = provider._token_validator
    assert isinstance(wrapper, auth.AllowlistTokenVerifier)

    wrapper._inner = FakeVerifier({"email": "anna@example.com", "email_verified": "true"})
    assert run(wrapper.verify_token("upstream")) is not None
    assert run(provider._extract_upstream_claims({"access_token": "upstream"})) == {"email": "anna@example.com"}

    wrapper._inner = FakeVerifier({"email": "eve@evil.example", "email_verified": "true"})
    assert run(wrapper.verify_token("upstream")) is None
    with pytest.raises(TokenError) as denied:
        run(provider._extract_upstream_claims({"access_token": "upstream"}))
    assert denied.value.error == "access_denied"

    wrapper._inner = FakeVerifier({"email": "anna@example.com", "email_verified": "false"})
    assert run(wrapper.verify_token("upstream")) is None

    wrapper._inner = FakeVerifier({"sub": "no-email-claim"})
    assert run(wrapper.verify_token("upstream")) is None

    wrapper._inner = FakeVerifier(None)
    assert run(wrapper.verify_token("upstream")) is None
    with pytest.raises(TokenError):
        run(provider._extract_upstream_claims({}))


def test_microsoft_provider_trusts_tenant_unless_allowlist_is_set():
    provider = auth.build_auth_provider(auth.resolve_auth_settings(AZURE_ENV))
    assert isinstance(provider, auth.GuardedAzureProvider)
    wrapper = provider._token_validator
    wrapper._inner = FakeVerifier({"preferred_username": "anyone@tenant-member.dk"})
    assert run(wrapper.verify_token("upstream")) is not None

    restricted = auth.build_auth_provider(auth.resolve_auth_settings({**AZURE_ENV, "MCP_ALLOWED_DOMAINS": "firma.dk"}))
    wrapper = restricted._token_validator
    wrapper._inner = FakeVerifier({"preferred_username": "bo@firma.dk"})  # no email_verified claim on Azure
    assert run(wrapper.verify_token("upstream")) is not None
    wrapper._inner = FakeVerifier({"preferred_username": "guest@other.dk"})
    assert run(wrapper.verify_token("upstream")) is None


def test_login_plus_service_token_uses_multi_auth():
    settings = auth.resolve_auth_settings({**AZURE_ENV, "MCP_AUTH_TOKEN": TOKEN})
    provider = auth.build_auth_provider(settings)
    assert isinstance(provider, MultiAuth)
    accepted = run(provider.verify_token(TOKEN))
    assert accepted is not None
    assert accepted.client_id == auth.SERVICE_TOKEN_CLIENT_ID
    assert set(provider.required_scopes or []) <= set(accepted.scopes)
    assert auth.SERVICE_SCOPE in accepted.scopes
    assert run(provider.verify_token("not-a-real-token")) is None


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------


def test_current_identity_prefers_email_then_subject_then_client_id(monkeypatch):
    monkeypatch.setattr(auth, "get_access_token", lambda: None)
    assert auth.current_identity() == "anonymous"
    monkeypatch.setattr(
        auth,
        "get_access_token",
        lambda: AccessToken(token="t", client_id="cid", scopes=[], claims={"email": "Anna@Example.com"}),
    )
    assert auth.current_identity() == "anna@example.com"
    monkeypatch.setattr(auth, "get_access_token", lambda: AccessToken(token="t", client_id="cid", scopes=[], claims={"sub": "42"}))
    assert auth.current_identity() == "42"
    monkeypatch.setattr(auth, "get_access_token", lambda: AccessToken(token="t", client_id="service-token", scopes=[]))
    assert auth.current_identity() == "service-token"


def test_audit_middleware_logs_tool_calls_without_arguments(monkeypatch, caplog):
    def handler(request):
        return httpx.Response(200, json={"agreementNumber": 123})

    monkeypatch.setattr(
        server,
        "_build_http_client",
        lambda: httpx.AsyncClient(base_url=f"{server.BASE_URL}/", headers=server.HEADERS, transport=httpx.MockTransport(handler)),
    )

    async def call_tool():
        async with Client(server.mcp) as client:
            await client.call_tool("get_company_info", {})
            await client.call_tool("get_customer", {"customer_number": 987654})

    with caplog.at_level(logging.INFO, logger="economic-mcp.audit"):
        run(call_tool())

    messages = [record.getMessage() for record in caplog.records if record.name == "economic-mcp.audit"]
    assert any("tool=get_company_info" in m and "user=anonymous" in m and "status=ok" in m for m in messages)
    assert any("tool=get_customer" in m and "status=ok" in m for m in messages)
    assert not any("987654" in m for m in messages)


# ---------------------------------------------------------------------------
# Read-only mode
# ---------------------------------------------------------------------------


def test_read_only_mode_hides_every_write_tool():
    async def visible_tools():
        async with Client(server.mcp) as client:
            return {tool.name for tool in await client.list_tools()}

    server.mcp.disable(tags={"write"})
    try:
        visible = run(visible_tools())
        assert len(visible) == 58
        for name in ("create_draft_invoice", "book_draft_invoice", "delete_customer", "create_journal_voucher"):
            assert name not in visible
        assert {"list_customers", "get_account_entries", "economic_api_request"} <= visible
    finally:
        server.mcp.enable(tags={"write"})
    assert len(run(visible_tools())) == 73


def test_generic_request_is_get_only_in_read_only_mode(monkeypatch):
    async def fake_request(method, path, params=None, json=None, idempotency_key=None):
        return {"method": method}

    monkeypatch.setattr(server, "_request", fake_request)
    monkeypatch.setattr(server, "READ_ONLY", True)
    assert run(server.economic_api_request("get", "/self")) == {"method": "GET"}
    with pytest.raises(ValueError, match="read-only"):
        run(server.economic_api_request("POST", "/customers", body={"name": "x"}))


def test_write_tools_are_tagged_and_annotated():
    async def tools():
        async with Client(server.mcp) as client:
            return {tool.name: tool for tool in await client.list_tools()}

    listed = run(tools())
    assert listed["book_draft_invoice"].annotations.destructiveHint is True
    assert listed["book_draft_invoice"].annotations.readOnlyHint is False
    assert listed["create_customer"].annotations.destructiveHint is False
    assert listed["list_customers"].annotations.readOnlyHint is True
    assert listed["economic_api_request"].annotations.openWorldHint is True


# ---------------------------------------------------------------------------
# Startup behaviour
# ---------------------------------------------------------------------------


def _startup_env(tmp_path, **overrides):
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("MCP_", "GOOGLE_", "AZURE_", "RAILWAY_", "FASTMCP_"))
    }
    env["FASTMCP_HOME"] = str(tmp_path)
    env["ECONOMIC_APP_SECRET_TOKEN"] = "demo"
    env["ECONOMIC_AGREEMENT_GRANT_TOKEN"] = "demo"
    env.update(overrides)
    return env


def _import_server(env):
    return subprocess.run(
        [sys.executable, "-c", "import server; print(server.AUTH_SETTINGS.mode, server.READ_ONLY)"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_server_refuses_to_start_without_authentication(tmp_path):
    result = _import_server(_startup_env(tmp_path))
    assert result.returncode != 0
    assert "refuses to start" in result.stderr


def test_server_starts_with_access_key_and_read_only(tmp_path):
    result = _import_server(_startup_env(tmp_path, MCP_AUTH_TOKEN=TOKEN, MCP_READ_ONLY="true"))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "token True"


def test_server_reports_invalid_configuration_clearly(tmp_path):
    result = _import_server(_startup_env(tmp_path, GOOGLE_OAUTH_CLIENT_ID="abc"))
    assert result.returncode != 0
    assert "Invalid authentication configuration" in result.stderr
    assert "GOOGLE_OAUTH_CLIENT_SECRET" in result.stderr
