import asyncio
import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastmcp import FastMCP

import auth
import local_users

PASSWORD = "korrekt-hest-batteri-1234"
EMAIL = "anna@firma.dk"
PUBLIC_URL = "https://economic.example.com"


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def users():
    return {EMAIL: local_users.hash_password(PASSWORD, rounds=1000)}


@pytest.fixture
def provider(tmp_path, users):
    return local_users.LocalUsersProvider(users, base_url=PUBLIC_URL, state_dir=tmp_path / "state")


def pkce_pair():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


# ---------------------------------------------------------------------------
# Passwords and configuration
# ---------------------------------------------------------------------------


def test_password_hashing_round_trip():
    stored = local_users.hash_password(PASSWORD, rounds=1000)
    assert stored.startswith("pbkdf2_sha256$1000$")
    assert local_users.verify_password(PASSWORD, stored)
    assert not local_users.verify_password(PASSWORD + "x", stored)
    assert not local_users.verify_password(PASSWORD, "garbage")
    assert local_users.hash_password(PASSWORD, rounds=1000) != stored  # random salt
    with pytest.raises(ValueError):
        local_users.hash_password("short")


def test_parse_users_reads_variables(users):
    env = {"MCP_USER_ANNA": f"{EMAIL}:{users[EMAIL]}", "MCP_USER_EMPTY": "", "OTHER": "x"}
    assert local_users.parse_users(env) == {EMAIL: users[EMAIL]}


@pytest.mark.parametrize(
    "value",
    ["anna@firma.dk", "anna@firma.dk:plain-password", "not-an-email:pbkdf2_sha256$1$a$b", "anna@firma.dk:md5$1$a$b"],
)
def test_parse_users_rejects_bad_values(value):
    with pytest.raises(local_users.UserConfigError):
        local_users.parse_users({"MCP_USER_ANNA": value})


def test_parse_users_rejects_bad_names_and_duplicates(users):
    with pytest.raises(local_users.UserConfigError, match="may only contain"):
        local_users.parse_users({"MCP_USER_Bad Name": f"{EMAIL}:{users[EMAIL]}"})
    with pytest.raises(local_users.UserConfigError, match="defined twice"):
        local_users.parse_users({"MCP_USER_A": f"{EMAIL}:{users[EMAIL]}", "MCP_USER_B": f"{EMAIL.upper()}:{users[EMAIL]}"})


def test_auth_settings_select_users_mode(users):
    env = {"MCP_PUBLIC_URL": PUBLIC_URL, "MCP_USER_ANNA": f"{EMAIL}:{users[EMAIL]}", "MCP_AUTH_TOKEN_CFO": "c" * 40}
    settings = auth.resolve_auth_settings(env)
    assert settings.mode == "users"
    assert settings.uses_oauth
    assert settings.oauth_callback_url is None
    assert "e-mail login for 1 user(s): anna@firma.dk" in settings.summary()
    assert "access keys for cfo" in settings.summary()

    assert settings.login_access_token_minutes == 60 and settings.login_session_days == 30
    tuned = auth.resolve_auth_settings({**env, "MCP_LOGIN_ACCESS_TOKEN_MINUTES": "480", "MCP_LOGIN_SESSION_DAYS": "90"})
    assert tuned.login_access_token_minutes == 480 and tuned.login_session_days == 90
    assert "sessions 90 days" in tuned.summary()
    with pytest.raises(auth.AuthConfigError, match="between 1 and 365"):
        auth.resolve_auth_settings({**env, "MCP_LOGIN_SESSION_DAYS": "0"})
    with pytest.raises(auth.AuthConfigError, match="whole number"):
        auth.resolve_auth_settings({**env, "MCP_LOGIN_ACCESS_TOKEN_MINUTES": "an hour"})

    with pytest.raises(auth.AuthConfigError, match="MCP_PUBLIC_URL"):
        auth.resolve_auth_settings({"MCP_USER_ANNA": f"{EMAIL}:{users[EMAIL]}"})
    with pytest.raises(auth.AuthConfigError, match="cannot be combined"):
        auth.resolve_auth_settings({**env, "GOOGLE_OAUTH_CLIENT_ID": "x", "GOOGLE_OAUTH_CLIENT_SECRET": "y"})
    with pytest.raises(auth.AuthConfigError, match="not used with e-mail login"):
        auth.resolve_auth_settings({**env, "MCP_ALLOWED_DOMAINS": "firma.dk"})


# ---------------------------------------------------------------------------
# Full OAuth flow over HTTP (client registration -> login page -> code -> token)
# ---------------------------------------------------------------------------


def _client(provider):
    app = FastMCP("test", auth=provider).http_app(path="/mcp")
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=PUBLIC_URL)


async def _register_and_start(http, redirect_uri="http://localhost:6274/callback"):
    registration = await http.post(
        "/register",
        json={"redirect_uris": [redirect_uri], "client_name": "Claude test", "token_endpoint_auth_method": "none",
              "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"]},
    )
    assert registration.status_code == 201, registration.text
    client_id = registration.json()["client_id"]
    verifier, challenge = pkce_pair()
    authorize = await http.get(
        "/authorize",
        params={"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri, "state": "xyz",
                "code_challenge": challenge, "code_challenge_method": "S256", "scope": local_users.SCOPE},
    )
    assert authorize.status_code == 302, authorize.text
    login_url = authorize.headers["location"]
    assert login_url.startswith(f"{PUBLIC_URL}/login?txn=")
    txn = parse_qs(urlparse(login_url).query)["txn"][0]
    return client_id, verifier, txn, redirect_uri


def test_login_flow_issues_tokens_and_refreshes(provider):
    async def flow():
        async with _client(provider) as http:
            client_id, verifier, txn, redirect_uri = await _register_and_start(http)

            page = await http.get("/login", params={"txn": txn})
            assert page.status_code == 200
            assert "Kodeord" in page.text and 'name="txn"' in page.text
            assert "http://localhost:6274" in page.text  # destination is always shown
            assert page.headers["cache-control"] == "no-store"
            assert "frame-ancestors 'none'" in page.headers["content-security-policy"]

            wrong = await http.post("/login", data={"txn": txn, "email": EMAIL, "password": "nope-nope-nope"})
            assert wrong.status_code == 401 and "Forkert" in wrong.text

            ok = await http.post("/login", data={"txn": txn, "email": EMAIL.upper(), "password": PASSWORD})
            assert ok.status_code == 302, ok.text
            location = urlparse(ok.headers["location"])
            assert location.netloc == "localhost:6274"
            query = parse_qs(location.query)
            assert query["state"] == ["xyz"]
            code = query["code"][0]

            reused = await http.post("/login", data={"txn": txn, "email": EMAIL, "password": PASSWORD})
            assert reused.status_code == 400  # transaction is single-use

            token = await http.post(
                "/token",
                data={"grant_type": "authorization_code", "code": code, "code_verifier": verifier,
                      "client_id": client_id, "redirect_uri": redirect_uri},
            )
            assert token.status_code == 200, token.text
            body = token.json()
            access = await provider.verify_token(body["access_token"])
            assert access is not None and access.claims["email"] == EMAIL
            assert local_users.SCOPE in access.scopes
            assert auth.identity_from_claims(access.claims) == EMAIL

            replay = await http.post(
                "/token",
                data={"grant_type": "authorization_code", "code": code, "code_verifier": verifier,
                      "client_id": client_id, "redirect_uri": redirect_uri},
            )
            assert replay.status_code in (400, 401)

            refreshed = await http.post(
                "/token", data={"grant_type": "refresh_token", "refresh_token": body["refresh_token"], "client_id": client_id}
            )
            assert refreshed.status_code == 200, refreshed.text
            new_body = refreshed.json()
            assert new_body["refresh_token"] != body["refresh_token"]
            assert (await provider.verify_token(new_body["access_token"])).claims["email"] == EMAIL

            rotated = await http.post(
                "/token", data={"grant_type": "refresh_token", "refresh_token": body["refresh_token"], "client_id": client_id}
            )
            assert rotated.status_code in (400, 401)  # old refresh token is dead
            return client_id, new_body["refresh_token"]

    client_id, refresh_token = run(flow())

    # Client registrations and refresh tokens survive a restart; access tokens do not.
    restarted = local_users.LocalUsersProvider(provider._users, base_url=PUBLIC_URL, state_dir=provider._state_dir)
    assert run(restarted.get_client(client_id)) is not None
    client = run(restarted.get_client(client_id))
    assert run(restarted.load_refresh_token(client, refresh_token)) is not None
    state = provider._state_file.read_text()
    assert refresh_token not in state  # only hashes are stored

    # Removing the user invalidates their refresh token.
    without_user = local_users.LocalUsersProvider({"bo@firma.dk": provider._users[EMAIL]}, base_url=PUBLIC_URL, state_dir=provider._state_dir)
    assert run(without_user.load_refresh_token(client, refresh_token)) is None


def test_token_lifetimes_are_configurable(tmp_path, users):
    provider = local_users.LocalUsersProvider(users, base_url=PUBLIC_URL, state_dir=tmp_path, access_token_ttl=120, refresh_token_ttl=3600)
    from mcp.shared.auth import OAuthClientInformationFull
    client = OAuthClientInformationFull(client_id="c1", redirect_uris=["http://localhost/cb"])
    token = provider._issue_tokens(client, EMAIL, [local_users.SCOPE])
    assert token.expires_in == 120
    record = next(iter(provider._refresh_tokens.values()))
    assert record["expires_at"] - __import__("time").time() <= 3600


def test_lockout_after_repeated_failures(provider):
    async def flow():
        async with _client(provider) as http:
            _, _, txn, _ = await _register_and_start(http)
            statuses = []
            for _ in range(local_users.MAX_FAILED_ATTEMPTS):
                response = await http.post("/login", data={"txn": txn, "email": "nobody@firma.dk", "password": "wrong-wrong-wrong"})
                statuses.append(response.status_code)
            # a fresh transaction for the same IP / e-mail is now locked
            _, _, txn2, _ = await _register_and_start(http)
            locked = await http.post("/login", data={"txn": txn2, "email": EMAIL, "password": PASSWORD})
            return statuses, locked.status_code, locked.text

    statuses, locked_status, text = run(flow())
    assert statuses[:4] == [401, 401, 401, 401]
    assert locked_status == 429 and "For mange" in text


def test_expired_or_unknown_transaction_is_rejected(provider):
    async def flow():
        async with _client(provider) as http:
            page = await http.get("/login", params={"txn": "does-not-exist"})
            post = await http.post("/login", data={"txn": "does-not-exist", "email": EMAIL, "password": PASSWORD})
            return page.status_code, post.status_code

    assert run(flow()) == (400, 400)


def test_redirect_allowlist_blocks_unknown_destinations(tmp_path, users):
    provider = local_users.LocalUsersProvider(
        users, base_url=PUBLIC_URL, state_dir=tmp_path, allowed_client_redirect_uris=["http://localhost:*", "https://claude.ai/*"]
    )

    async def flow():
        async with _client(provider) as http:
            bad = await http.post("/register", json={"redirect_uris": ["https://evil.example/cb"], "client_name": "x", "token_endpoint_auth_method": "none"})
            good = await http.post("/register", json={"redirect_uris": ["https://claude.ai/api/mcp/auth_callback"], "client_name": "claude", "token_endpoint_auth_method": "none"})
            return bad.status_code, good.status_code

    bad, good = run(flow())
    assert bad >= 400 and good == 201


def test_metadata_advertises_login_server(provider):
    async def flow():
        async with _client(provider) as http:
            meta = await http.get("/.well-known/oauth-authorization-server")
            resource = await http.get("/.well-known/oauth-protected-resource/mcp")
            return meta.json(), resource.status_code

    meta, resource_status = run(flow())
    assert meta["authorization_endpoint"] == f"{PUBLIC_URL}/authorize"
    assert meta["token_endpoint"] == f"{PUBLIC_URL}/token"
    assert "S256" in meta["code_challenge_methods_supported"]
    assert resource_status == 200
