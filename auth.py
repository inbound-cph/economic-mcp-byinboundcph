"""
Authentication, authorization and audit logging for the e-conomic MCP server.

The server picks its protection automatically from environment variables:

  Google login      GOOGLE_OAUTH_CLIENT_ID + GOOGLE_OAUTH_CLIENT_SECRET
                    + MCP_ALLOWED_EMAILS and/or MCP_ALLOWED_DOMAINS (required)
  Microsoft login   AZURE_CLIENT_ID + AZURE_CLIENT_SECRET + AZURE_TENANT_ID
                    (+ allowlist, required when the tenant is not your own)
  Access key        MCP_AUTH_TOKEN (static bearer token, at least 32 characters)

Google and Microsoft login give every user a personal browser login (OAuth 2.1 with
PKCE) through FastMCP's OAuth proxy. Only accounts on the allowlist (or inside the
Microsoft tenant) are accepted, both when logging in and on every request. An access
key can be combined with either login so automations keep a fixed credential while
people sign in with their work account.

Every tool call is written to the audit log with the identity of the caller.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional
from urllib.parse import urlsplit

from fastmcp.server.auth import AccessToken, AuthProvider, MultiAuth, TokenVerifier
from fastmcp.server.auth.providers.azure import AzureProvider
from fastmcp.server.auth.providers.google import GoogleProvider
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import Middleware, MiddlewareContext
from mcp.server.auth.provider import TokenError

logger = logging.getLogger("economic-mcp.auth")
audit_logger = logging.getLogger("economic-mcp.audit")

MIN_SECRET_LENGTH = 32
SERVICE_SCOPE = "economic:access"
SERVICE_TOKEN_CLIENT_ID = "service-token"
GOOGLE_SCOPES = ["openid", "email"]
DEFAULT_AZURE_SCOPE = "access_as_user"
ACCESS_DENIED_MESSAGE = (
    "This account is not allowed to use this e-conomic MCP server. "
    "Ask the administrator to add your e-mail address or domain to the allowlist."
)

_GENERIC_AZURE_TENANTS = {"common", "organizations", "consumers"}
_IDENTITY_CLAIMS = ("email", "preferred_username", "upn")
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class AuthConfigError(ValueError):
    """The authentication environment variables are missing, inconsistent or unsafe."""


# ---------------------------------------------------------------------------
# Allowlist
# ---------------------------------------------------------------------------


def _split_list(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in re.split(r"[,\s]+", value) if item.strip()]


@dataclass(frozen=True)
class Allowlist:
    """E-mail addresses and domains that may log in. Matching is case-insensitive."""

    emails: frozenset[str] = frozenset()
    domains: frozenset[str] = frozenset()

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Allowlist":
        emails = [item.lower() for item in _split_list(env.get("MCP_ALLOWED_EMAILS"))]
        domains = [item.lower().lstrip("@") for item in _split_list(env.get("MCP_ALLOWED_DOMAINS"))]
        for email in emails:
            if not _EMAIL_PATTERN.match(email):
                raise AuthConfigError(f"MCP_ALLOWED_EMAILS contains an invalid e-mail address: {email!r}")
        for domain in domains:
            if "@" in domain or "." not in domain:
                raise AuthConfigError(f"MCP_ALLOWED_DOMAINS contains an invalid domain: {domain!r}")
        return cls(frozenset(emails), frozenset(domains))

    @property
    def is_empty(self) -> bool:
        return not self.emails and not self.domains

    def allows(self, identity: Optional[str]) -> bool:
        if not identity:
            return False
        identity = identity.strip().lower()
        if "@" not in identity:
            return False
        if identity in self.emails:
            return True
        _, _, domain = identity.rpartition("@")
        return bool(domain) and domain in self.domains

    def summary(self) -> str:
        parts = []
        if self.emails:
            parts.append(f"{len(self.emails)} e-mail address(es)")
        if self.domains:
            parts.append("domain(s) " + ", ".join(sorted(self.domains)))
        return " and ".join(parts) if parts else "none"


def identity_from_claims(claims: Optional[Mapping[str, Any]]) -> Optional[str]:
    """Return the e-mail-like identity of a token (Google: email, Microsoft: preferred_username/upn)."""
    if not claims:
        return None
    for key in _IDENTITY_CLAIMS:
        value = claims.get(key)
        if isinstance(value, str) and "@" in value:
            return value.strip().lower()
    return None


def email_is_verified(claims: Optional[Mapping[str, Any]]) -> bool:
    """Google reports email_verified as a boolean or the string 'true'."""
    if not claims:
        return False
    value = claims.get("email_verified")
    if isinstance(value, bool):
        return value
    return isinstance(value, str) and value.strip().lower() == "true"


class AllowlistTokenVerifier(TokenVerifier):
    """Wraps the identity provider's verifier and rejects identities outside the allowlist."""

    def __init__(self, inner: TokenVerifier, allowlist: Allowlist, *, require_verified_email: bool) -> None:
        super().__init__(required_scopes=inner.required_scopes)
        self._inner = inner
        self._allowlist = allowlist
        self._require_verified_email = require_verified_email

    async def verify_token(self, token: str) -> Optional[AccessToken]:
        access = await self._inner.verify_token(token)
        if access is None:
            return None
        if self._allowlist.is_empty:
            return access
        identity = identity_from_claims(access.claims)
        if identity is None:
            logger.warning("Rejected token without an e-mail identity claim")
            return None
        if self._require_verified_email and not email_is_verified(access.claims):
            logger.warning("Rejected %s: the identity provider has not verified the e-mail address", identity)
            return None
        if not self._allowlist.allows(identity):
            logger.warning("Rejected %s: not on the allowlist", identity)
            return None
        return access


class _AllowlistGuard:
    """Mixin for FastMCP OAuth proxies. Enforces the allowlist at login and on every request."""

    def install_allowlist(self, allowlist: Allowlist, *, require_verified_email: bool) -> None:
        self._token_validator = AllowlistTokenVerifier(  # type: ignore[attr-defined]
            self._token_validator,  # type: ignore[attr-defined]
            allowlist,
            require_verified_email=require_verified_email,
        )

    async def _extract_upstream_claims(self, idp_tokens: dict[str, Any]) -> Optional[dict[str, Any]]:
        # Runs while the login is being completed: a rejected account gets an OAuth
        # "access_denied" error instead of a token that fails on the first request.
        upstream = await super()._extract_upstream_claims(idp_tokens)  # type: ignore[misc]
        access_token = idp_tokens.get("access_token") if isinstance(idp_tokens, dict) else None
        access = await self._token_validator.verify_token(access_token) if access_token else None  # type: ignore[attr-defined]
        if access is None:
            raise TokenError("access_denied", ACCESS_DENIED_MESSAGE)
        claims = dict(upstream or {})
        identity = identity_from_claims(access.claims)
        if identity:
            claims.setdefault("email", identity)
            logger.info("Login accepted for %s", identity)
        return claims or None


class GuardedGoogleProvider(_AllowlistGuard, GoogleProvider):
    """Google login restricted to the configured allowlist."""


class GuardedAzureProvider(_AllowlistGuard, AzureProvider):
    """Microsoft Entra login restricted to the tenant and the optional allowlist."""


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def _public_url_from_env(env: Mapping[str, str]) -> Optional[str]:
    raw = (env.get("MCP_PUBLIC_URL") or "").strip()
    if not raw and (env.get("RAILWAY_PUBLIC_DOMAIN") or "").strip():
        raw = f"https://{env['RAILWAY_PUBLIC_DOMAIN'].strip()}"
    if not raw:
        return None
    raw = raw.rstrip("/")
    parsed = urlsplit(raw)
    is_local_http = parsed.scheme == "http" and parsed.hostname in _LOCAL_HOSTS
    if parsed.scheme != "https" and not is_local_http:
        raise AuthConfigError("MCP_PUBLIC_URL must use https:// (http:// is only allowed for localhost)")
    if not parsed.netloc or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise AuthConfigError("MCP_PUBLIC_URL must be a plain absolute URL such as https://my-app.up.railway.app")
    return raw


@dataclass(frozen=True)
class AuthSettings:
    mode: str  # "google" | "microsoft" | "token" | "none"
    public_url: Optional[str] = None
    allowlist: Allowlist = field(default_factory=Allowlist)
    service_token: Optional[str] = None
    jwt_signing_key: Optional[str] = None
    allowed_client_redirect_uris: Optional[tuple[str, ...]] = None
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None
    azure_client_id: Optional[str] = None
    azure_client_secret: Optional[str] = None
    azure_tenant_id: Optional[str] = None
    azure_scope: str = DEFAULT_AZURE_SCOPE
    azure_identifier_uri: Optional[str] = None

    @property
    def uses_oauth(self) -> bool:
        return self.mode in {"google", "microsoft"}

    @property
    def oauth_callback_url(self) -> Optional[str]:
        return f"{self.public_url}/auth/callback" if self.uses_oauth and self.public_url else None

    def summary(self) -> str:
        if self.mode == "none":
            return "NONE (unprotected)"
        if self.mode == "token":
            return "access key (MCP_AUTH_TOKEN)"
        label = "Google login" if self.mode == "google" else f"Microsoft login (tenant {self.azure_tenant_id})"
        text = f"{label}, allowlist: {self.allowlist.summary()}"
        if self.service_token:
            text += ", plus access key for automations"
        return text


def resolve_auth_settings(env: Mapping[str, str]) -> AuthSettings:
    """Validate the authentication environment variables and decide the mode. Pure function."""

    def get(key: str) -> str:
        return (env.get(key) or "").strip()

    public_url = _public_url_from_env(env)
    allowlist = Allowlist.from_env(env)

    service_token = get("MCP_AUTH_TOKEN") or None
    if service_token and len(service_token) < MIN_SECRET_LENGTH:
        raise AuthConfigError(
            f"MCP_AUTH_TOKEN must be at least {MIN_SECRET_LENGTH} characters (generate one with: openssl rand -hex 32)"
        )
    jwt_signing_key = get("MCP_JWT_SIGNING_KEY") or None
    if jwt_signing_key and len(jwt_signing_key) < MIN_SECRET_LENGTH:
        raise AuthConfigError(f"MCP_JWT_SIGNING_KEY must be at least {MIN_SECRET_LENGTH} characters")
    redirect_uris = tuple(_split_list(get("MCP_ALLOWED_CLIENT_REDIRECT_URIS"))) or None

    google = {key: get(key) for key in ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET")}
    azure = {key: get(key) for key in ("AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET", "AZURE_TENANT_ID")}
    if any(google.values()) and any(azure.values()):
        raise AuthConfigError("Configure either Google login or Microsoft login, not both")

    common = dict(
        public_url=public_url,
        allowlist=allowlist,
        service_token=service_token,
        jwt_signing_key=jwt_signing_key,
        allowed_client_redirect_uris=redirect_uris,
    )

    if any(google.values()):
        missing = [key for key, value in google.items() if not value]
        if missing:
            raise AuthConfigError(f"Google login is missing {', '.join(missing)}")
        if not public_url:
            raise AuthConfigError(
                "Google login requires MCP_PUBLIC_URL (the server's public https URL). "
                "On Railway it is derived automatically from RAILWAY_PUBLIC_DOMAIN once a domain has been generated."
            )
        if allowlist.is_empty:
            raise AuthConfigError(
                "Google login requires MCP_ALLOWED_EMAILS and/or MCP_ALLOWED_DOMAINS, "
                "otherwise anyone with a Google account could reach the accounting data"
            )
        return AuthSettings(
            mode="google",
            google_client_id=google["GOOGLE_OAUTH_CLIENT_ID"],
            google_client_secret=google["GOOGLE_OAUTH_CLIENT_SECRET"],
            **common,
        )

    if any(azure.values()):
        missing = [key for key, value in azure.items() if not value]
        if missing:
            raise AuthConfigError(f"Microsoft login is missing {', '.join(missing)}")
        if not public_url:
            raise AuthConfigError(
                "Microsoft login requires MCP_PUBLIC_URL (the server's public https URL). "
                "On Railway it is derived automatically from RAILWAY_PUBLIC_DOMAIN once a domain has been generated."
            )
        tenant_id = azure["AZURE_TENANT_ID"]
        if tenant_id.lower() in _GENERIC_AZURE_TENANTS and allowlist.is_empty:
            raise AuthConfigError(
                f"AZURE_TENANT_ID={tenant_id} accepts accounts from any organisation. "
                "Use your own tenant ID, or set MCP_ALLOWED_EMAILS/MCP_ALLOWED_DOMAINS."
            )
        return AuthSettings(
            mode="microsoft",
            azure_client_id=azure["AZURE_CLIENT_ID"],
            azure_client_secret=azure["AZURE_CLIENT_SECRET"],
            azure_tenant_id=tenant_id,
            azure_scope=get("AZURE_API_SCOPE") or DEFAULT_AZURE_SCOPE,
            azure_identifier_uri=get("AZURE_IDENTIFIER_URI") or None,
            **common,
        )

    if service_token:
        return AuthSettings(mode="token", **common)

    if not allowlist.is_empty:
        raise AuthConfigError(
            "MCP_ALLOWED_EMAILS/MCP_ALLOWED_DOMAINS only take effect together with Google or Microsoft login"
        )
    return AuthSettings(mode="none", public_url=public_url)


# ---------------------------------------------------------------------------
# Provider construction
# ---------------------------------------------------------------------------


def _service_token_verifier(token: str, scopes: list[str], required_scopes: Optional[list[str]]) -> StaticTokenVerifier:
    return StaticTokenVerifier(
        tokens={token: {"client_id": SERVICE_TOKEN_CLIENT_ID, "scopes": scopes}},
        required_scopes=required_scopes,
    )


def build_auth_provider(settings: AuthSettings) -> Optional[AuthProvider]:
    """Create the FastMCP auth provider for the resolved settings (None when unprotected)."""
    if settings.mode == "none":
        return None
    if settings.mode == "token":
        assert settings.service_token
        return _service_token_verifier(settings.service_token, [SERVICE_SCOPE], required_scopes=[SERVICE_SCOPE])

    redirect_uris = list(settings.allowed_client_redirect_uris) if settings.allowed_client_redirect_uris else None
    if settings.mode == "google":
        provider: _AllowlistGuard = GuardedGoogleProvider(
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            base_url=settings.public_url,
            required_scopes=GOOGLE_SCOPES,
            jwt_signing_key=settings.jwt_signing_key,
            allowed_client_redirect_uris=redirect_uris,
        )
        provider.install_allowlist(settings.allowlist, require_verified_email=True)
    elif settings.mode == "microsoft":
        provider = GuardedAzureProvider(
            client_id=settings.azure_client_id,
            client_secret=settings.azure_client_secret,
            tenant_id=settings.azure_tenant_id,
            required_scopes=[settings.azure_scope],
            identifier_uri=settings.azure_identifier_uri,
            base_url=settings.public_url,
            jwt_signing_key=settings.jwt_signing_key,
            allowed_client_redirect_uris=redirect_uris,
        )
        provider.install_allowlist(settings.allowlist, require_verified_email=False)
    else:
        raise AuthConfigError(f"Unknown authentication mode: {settings.mode}")

    oauth_provider: AuthProvider = provider  # type: ignore[assignment]
    if settings.service_token:
        # The access key must carry the same scopes the OAuth login grants, so the
        # server-wide scope check accepts it as well.
        verifier = _service_token_verifier(
            settings.service_token,
            [*(oauth_provider.required_scopes or []), SERVICE_SCOPE],
            required_scopes=None,
        )
        return MultiAuth(server=oauth_provider, verifiers=[verifier])
    return oauth_provider


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------


def current_identity() -> str:
    """Who is calling: e-mail for logged-in users, 'service-token' for the access key."""
    try:
        token = get_access_token()
    except Exception:  # pragma: no cover - defensive, depends on transport internals
        return "unknown"
    if token is None:
        return "anonymous"
    claims = getattr(token, "claims", None) or {}
    return identity_from_claims(claims) or str(claims.get("sub") or token.client_id or "unknown")


class AuditMiddleware(Middleware):
    """Logs every tool call with caller identity, outcome and duration. Arguments are never logged."""

    async def on_call_tool(self, context: MiddlewareContext, call_next):  # type: ignore[override]
        tool_name = getattr(context.message, "name", "?")
        user = current_identity()
        started = time.monotonic()
        try:
            result = await call_next(context)
        except Exception as exc:
            audit_logger.warning(
                "tool=%s user=%s status=error error=%s duration_ms=%d",
                tool_name,
                user,
                type(exc).__name__,
                (time.monotonic() - started) * 1000,
            )
            raise
        audit_logger.info(
            "tool=%s user=%s status=ok duration_ms=%d",
            tool_name,
            user,
            (time.monotonic() - started) * 1000,
        )
        return result
