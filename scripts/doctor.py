#!/usr/bin/env python3
"""
Setup check for the e-conomic MCP server.

    python scripts/doctor.py                 # check .env / environment and e-conomic access
    python scripts/doctor.py --public-url https://my-app.up.railway.app   # also check a deployment

Prints one line per check. Secrets are never printed. Exit code 1 if something must be fixed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

OK, WARN, FAIL = "OK  ", "WARN", "FAIL"
_failures = 0


def report(status: str, title: str, detail: str = "") -> None:
    global _failures
    if status == FAIL:
        _failures += 1
    line = f"[{status}] {title}"
    if detail:
        line += f"\n       {detail}"
    print(line)


def masked(secret: str) -> str:
    if not secret:
        return "(empty)"
    if secret == "demo":
        return "demo"
    return f"{secret[:4]}… ({len(secret)} characters)"


def check_python() -> None:
    if sys.version_info >= (3, 10):
        report(OK, f"Python {sys.version.split()[0]}")
    else:
        report(FAIL, f"Python {sys.version.split()[0]} is too old", "Install Python 3.10 or newer.")


def check_dependencies() -> bool:
    try:
        import fastmcp  # noqa: F401
        import httpx  # noqa: F401
        from dotenv import load_dotenv  # noqa: F401
    except ImportError as exc:
        report(FAIL, "Dependencies are missing", f"Run: pip install -r requirements.txt ({exc})")
        return False
    import fastmcp as _fastmcp

    report(OK, f"Dependencies installed (fastmcp {_fastmcp.__version__})")
    return True


def check_economic_tokens() -> None:
    import httpx

    app_secret = os.environ.get("ECONOMIC_APP_SECRET_TOKEN", "demo").strip()
    grant = os.environ.get("ECONOMIC_AGREEMENT_GRANT_TOKEN", "demo").strip()
    base_url = os.environ.get("ECONOMIC_BASE_URL", "https://restapi.e-conomic.com").rstrip("/")
    if app_secret == "demo" or grant == "demo":
        report(
            WARN,
            "e-conomic tokens are 'demo'",
            "You are connected to e-conomic's read-only demo agreement. Fine for testing; set both tokens for real data.",
        )
    else:
        report(OK, f"e-conomic tokens set (app secret {masked(app_secret)}, grant {masked(grant)})")

    try:
        response = httpx.get(
            f"{base_url}/self",
            headers={"X-AppSecretToken": app_secret, "X-AgreementGrantToken": grant, "Content-Type": "application/json"},
            timeout=20.0,
        )
    except httpx.HTTPError as exc:
        report(FAIL, "Could not reach the e-conomic API", f"{type(exc).__name__}: check your internet connection or ECONOMIC_BASE_URL.")
        return
    if response.status_code == 200:
        data = response.json()
        company = (data.get("company") or {}).get("name") or "(unknown company)"
        report(OK, f"e-conomic API answers: agreement {data.get('agreementNumber')} – {company}")
    elif response.status_code in (401, 403):
        report(
            FAIL,
            f"e-conomic rejected the tokens (HTTP {response.status_code})",
            "Check ECONOMIC_APP_SECRET_TOKEN and ECONOMIC_AGREEMENT_GRANT_TOKEN, and that the grant has not been revoked.",
        )
    else:
        report(FAIL, f"Unexpected answer from e-conomic (HTTP {response.status_code})", response.text[:200])


def check_auth(public_url_override: str | None):
    import auth

    env = dict(os.environ)
    if public_url_override:
        env["MCP_PUBLIC_URL"] = public_url_override
    try:
        settings = auth.resolve_auth_settings(env)
    except auth.AuthConfigError as exc:
        report(FAIL, "Authentication configuration is invalid", str(exc))
        return None

    if settings.mode == "none":
        if env.get("MCP_ALLOW_UNAUTHENTICATED", "").strip().lower() in {"1", "true", "yes", "on"}:
            report(WARN, "No authentication (MCP_ALLOW_UNAUTHENTICATED=true)", "Only acceptable on your own machine. Never deploy like this.")
        else:
            report(
                FAIL,
                "No authentication configured – the server will refuse to start",
                "Choose Google login, Microsoft login or an access key (see GUIDE.md / README.md).",
            )
        return settings

    report(OK, f"Authentication: {settings.summary()}")
    if settings.uses_oauth:
        report(OK, f"Public URL: {settings.public_url}")
        report(
            OK,
            f"OAuth redirect URI to register at your identity provider: {settings.oauth_callback_url}",
        )
        if not env.get("MCP_JWT_SIGNING_KEY", "").strip():
            report(
                WARN,
                "MCP_JWT_SIGNING_KEY not set",
                "Login sessions are then keyed to the OAuth client secret; rotating that secret logs everyone out. "
                "Optional: set a random value (openssl rand -hex 32).",
            )
    elif settings.public_url:
        report(OK, f"Public URL: {settings.public_url}")

    read_only = env.get("MCP_READ_ONLY", "").strip().lower() in {"1", "true", "yes", "on"}
    report(OK if read_only else WARN, "Read-only mode " + ("ON (write tools hidden)" if read_only else "OFF (write tools available)"),
           "" if read_only else "Recommended for the first weeks: MCP_READ_ONLY=true. Booking invoices is irreversible.")
    return settings


def check_deployment(public_url: str, settings) -> None:
    import httpx

    public_url = public_url.rstrip("/")
    # A fresh Railway domain can answer 404 "Application not found" for a minute or two
    # while the edge network catches up, so retry before calling it a failure.
    health = None
    last_error = ""
    for attempt in range(6):
        try:
            health = httpx.get(f"{public_url}/health", timeout=20.0)
            if health.status_code == 200:
                break
            last_error = f"HTTP {health.status_code}: {health.text[:120]}"
        except httpx.HTTPError as exc:
            last_error = type(exc).__name__
        if attempt < 5:
            print(f"       ... deployment not ready yet ({last_error}), retrying in 10 s")
            time.sleep(10)
    if health is None or health.status_code != 200:
        report(
            FAIL,
            f"Deployment not reachable at {public_url}/health",
            f"{last_error}. Has the deploy finished (railway logs) and a public domain been generated (railway domain)?",
        )
        return
    data = health.json()
    report(OK, f"Deployment healthy: auth={data.get('auth')} readOnly={data.get('readOnly')}")
    if settings is not None and settings.mode != "none" and data.get("auth") != settings.mode:
        report(WARN, "Deployed auth mode differs from your local configuration", f"deployed={data.get('auth')} local={settings.mode}")

    unauthenticated = httpx.post(
        f"{public_url}/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        headers={"Accept": "application/json, text/event-stream"},
        timeout=20.0,
    )
    if unauthenticated.status_code == 401:
        report(OK, "/mcp rejects unauthenticated requests (HTTP 401)")
    else:
        report(FAIL, f"/mcp answered HTTP {unauthenticated.status_code} without credentials", "The endpoint must return 401. Check the auth variables on the server.")

    if data.get("auth") in {"google", "microsoft"}:
        metadata = httpx.get(f"{public_url}/.well-known/oauth-protected-resource/mcp", timeout=20.0)
        if metadata.status_code == 200:
            report(OK, "OAuth metadata published (clients can discover the login)")
        else:
            report(FAIL, f"OAuth metadata missing (HTTP {metadata.status_code})", "MCP_PUBLIC_URL must match the URL you are testing.")


def print_client_snippets(public_url: str | None, settings) -> None:
    url = (public_url or (settings.public_url if settings else None) or "https://<your-app>.up.railway.app").rstrip("/") + "/mcp"
    uses_oauth = bool(settings and settings.uses_oauth)
    print("\nConnect a client (replace the URL if needed):")
    print(f"  Claude Code:   claude mcp add --transport http economic {url}" + ("   then run /mcp to log in" if uses_oauth else ' --header "Authorization: Bearer <MCP_AUTH_TOKEN>"'))
    print(f"  Codex CLI:     codex mcp add economic --url {url}" + ("   then: codex mcp login economic" if uses_oauth else '   then add bearer_token_env_var = "ECONOMIC_MCP_TOKEN" under [mcp_servers.economic] in ~/.codex/config.toml'))
    print(f"  claude.ai:     Settings → Connectors → Add custom connector → {url}")
    snippet = {"mcpServers": {"economic": {"type": "http", "url": url}}}
    if not uses_oauth:
        snippet["mcpServers"]["economic"]["headers"] = {"Authorization": "Bearer ${ECONOMIC_MCP_TOKEN}"}
    print("  .mcp.json:     " + json.dumps(snippet))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--public-url", help="Public https URL of a deployment to check (e.g. https://my-app.up.railway.app)")
    parser.add_argument("--no-network", action="store_true", help="Skip calls to e-conomic and the deployment")
    args = parser.parse_args()

    print(f"e-conomic MCP doctor – {REPO_ROOT}\n")
    check_python()
    if not check_dependencies():
        return 1
    from dotenv import load_dotenv

    env_file = REPO_ROOT / ".env"
    load_dotenv(env_file)
    report(OK if env_file.exists() else WARN, f".env {'loaded' if env_file.exists() else 'not found (using the process environment only)'}")

    if not args.no_network:
        check_economic_tokens()
    settings = check_auth(args.public_url)
    if args.public_url and not args.no_network:
        check_deployment(args.public_url, settings)
    print_client_snippets(args.public_url, settings)

    print()
    if _failures:
        print(f"{_failures} problem(s) must be fixed. See GUIDE.md for step-by-step help.")
        return 1
    print("Everything looks good.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
