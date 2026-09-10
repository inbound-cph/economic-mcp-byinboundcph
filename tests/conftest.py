"""Test environment: the server refuses to start without authentication, so the suite
opts into unauthenticated mode explicitly and keeps FastMCP state out of the home dir."""

import os
import tempfile

os.environ.setdefault("MCP_ALLOW_UNAUTHENTICATED", "true")
os.environ.setdefault("FASTMCP_HOME", tempfile.mkdtemp(prefix="economic-mcp-tests-"))
# Never let a developer's real credentials leak into the test run.
for _key in (
    "MCP_AUTH_TOKEN",
    "GOOGLE_OAUTH_CLIENT_ID",
    "GOOGLE_OAUTH_CLIENT_SECRET",
    "AZURE_CLIENT_ID",
    "AZURE_CLIENT_SECRET",
    "AZURE_TENANT_ID",
    "MCP_ALLOWED_EMAILS",
    "MCP_ALLOWED_DOMAINS",
    "MCP_PUBLIC_URL",
    "MCP_READ_ONLY",
    "RAILWAY_PUBLIC_DOMAIN",
    "RAILWAY_VOLUME_MOUNT_PATH",
):
    os.environ.pop(_key, None)
for _key in [k for k in os.environ if k.startswith(("MCP_AUTH_TOKEN_", "MCP_USER_"))]:
    os.environ.pop(_key, None)
os.environ.setdefault("ECONOMIC_APP_SECRET_TOKEN", "demo")
os.environ.setdefault("ECONOMIC_AGREEMENT_GRANT_TOKEN", "demo")
