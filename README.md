# e-conomic MCP Server by InboundCPH

A [FastMCP](https://gofastmcp.com) server that exposes the [Visma e-conomic](https://www.e-conomic.dk/)
REST API as 73 MCP tools over Streamable HTTP. The server is the gate in front of your
e-conomic tokens: **one access key per person**, **e-mail + password login hosted by the
server**, or **Google/Microsoft login** with an **allowlist**, plus **read-only mode** and an
**audit log**. Runs on Railway in minutes.

Built by Ian Rosenfeldt, founder of [INBOUND CPH A/S](https://inboundcph.dk).

**Dansk guide:** [GUIDE.md](GUIDE.md) tager dig trin for trin gennem e-conomic-tokens,
Railway, login og klienter. **AI agents:** [AGENTS.md](AGENTS.md) tells Claude Code /
Codex how to set the server up for you.

```
Claude / Codex / Cursor  ──login──▶  your MCP server (Railway)  ──API tokens──▶  e-conomic
```

## Quick start

**Let an AI coding agent do it** (recommended):

```bash
git clone https://github.com/inbound-cph/economic-mcp-byinboundcph.git
cd economic-mcp-byinboundcph
claude    # or: codex
```

Ask: *"Help me set up the e-conomic MCP server on Railway."* The agent follows
`AGENTS.md`, runs the Railway CLI for you and tells you what to click in e-conomic,
Google/Microsoft and Railway.

**Manual, with the Railway CLI** from your clone:

```bash
railway login
railway init --name economic-mcp
railway add --service economic-mcp --variables "MCP_READ_ONLY=true" \
  --variables "ECONOMIC_APP_SECRET_TOKEN=demo" --variables "ECONOMIC_AGREEMENT_GRANT_TOKEN=demo"
railway volume add --mount-path /data --service economic-mcp   # login sessions survive deploys
python scripts/new_key.py cfo --service economic-mcp   # prints a key once + the command to store it
railway domain --service economic-mcp
railway up --detach --service economic-mcp
python scripts/doctor.py --public-url https://<your-domain>
```

Then replace the `demo` tokens with your own (GUIDE.md step 1), add one key per person or
personal login (step 3) and connect your client (step 4).

## Features (73 tools)

- **Company**: `get_company_info` (agreement/company details via `/self`)
- **Customers**: list/get/create/update/delete customers, contacts, delivery locations, per-customer draft/booked invoices, totals, customer groups
- **Suppliers**: list/get/create suppliers, supplier groups
- **Products**: list/get/create/update/delete products, product groups
- **Invoices**: draft/booked/sent/paid/unpaid/overdue/not-due invoices, invoice totals, `create_draft_invoice`, `update_draft_invoice`, `book_draft_invoice`, `register_invoice_as_sent`, `delete_draft_invoice`, PDF download (draft + booked, base64)
- **Quotes**: draft/sent/archived quotes, `register_quote_as_sent`
- **Orders**: draft/sent/archived orders
- **Accounting**: chart of accounts, account entries by accounting year, accounting years, periods, year/period totals, journals, journal entries and vouchers, `create_finance_voucher`, `create_journal_voucher` (raw)
- **Reference data**: payment terms, payment types, VAT zones/accounts/types, currencies, layouts, units, departments, departmental distributions, employees
- **Escape hatch**: `economic_api_request` — call any e-conomic REST endpoint (method, path, params, body) not covered by a dedicated tool

All list tools support pagination (`skip_pages`, `page_size`, maximum 1000). Filter-capable
list tools accept e-conomic filter syntax, e.g. `name$like:acme`, `date$gte:2026-01-01`,
`customer.customerNumber$eq:123`. Every tool carries MCP annotations (`readOnlyHint`,
`destructiveHint`) so clients can ask before changing the books.

## Authentication

The server **refuses to start without authentication**. Pick a method by setting its
variables; the mode is detected automatically.

| Mode | Variables | Who gets in |
|---|---|---|
| **Access keys** (simplest) | `MCP_AUTH_TOKEN_<NAME>` per person, e.g. `MCP_AUTH_TOKEN_CFO`, `MCP_AUTH_TOKEN_ANNA`; `MCP_AUTH_TOKEN` for automations. 32+ characters each, `python scripts/new_key.py <name>` generates one | Whoever holds a key; the audit log shows the name; delete the variable to revoke |
| **E-mail + password login** | `MCP_USER_<NAME>=email:hash` per person; `python scripts/new_user.py <name> <email>` creates the line and shows the password once | The people listed, via the server's own login page. Works in claude.ai / Claude Desktop connectors without Google or Microsoft |
| **Google login** | `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, plus `MCP_ALLOWED_DOMAINS` and/or `MCP_ALLOWED_EMAILS` (required) | Google accounts on the allowlist with a verified e-mail |
| **Microsoft login** | `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID` (optional `AZURE_API_SCOPE`, default `access_as_user`) | Members of your Entra tenant, further narrowed by the optional allowlist |

**Which one?** A small group (the CFO, a finance person, someone in management) using
Claude Code, Codex, Cursor or Claude Desktop: access keys, one per person, no identity
provider needed. Sharing the server with a whole organisation through claude.ai / Claude
Desktop *connectors* (Team and Enterprise plans): those connectors require an OAuth login.
Use Google or Microsoft login if you have Workspace or Microsoft 365 (everybody can see the
connector, but only the e-mails on the allowlist or in your tenant get in), or **e-mail +
password login** hosted by the server if you have neither. Keys can be combined with any
login; the three login methods are mutually exclusive.

E-mail + password login in detail: the server hosts a small login page. Passwords are stored
only as PBKDF2-SHA256 hashes (600 000 rounds) in the `MCP_USER_*` variables, compared in
constant time; five failed attempts per e-mail or IP lock login for 15 minutes; each login
page belongs to a single short-lived OAuth transaction; authorization codes are single-use
with PKCE; access tokens live one hour, refresh tokens 30 days with rotation, stored as
hashes under `FASTMCP_HOME` so logins survive deploys. Clients refresh silently, so a user
who uses the server at least once every 30 days never logs in again; tune with
`MCP_LOGIN_SESSION_DAYS` (1–365) and `MCP_LOGIN_ACCESS_TOKEN_MINUTES` (5–1440). There is no
MFA and no self-service password reset: the admin runs `new_user.py` again. Prefer
Google/Microsoft when you have them.

Google and Microsoft login use OAuth 2.1 with PKCE through FastMCP's OAuth proxy: MCP
clients discover the server's OAuth metadata, register dynamically, the user sees a short
consent page and then the Google/Microsoft login. The allowlist is enforced **when the
login completes** (rejected accounts receive `access_denied`) **and on every request**.

Access keys can be combined with either login, for example keys for automations and a
few power users while everyone else signs in personally. `MCP_ALLOWED_*` without a login
mode is rejected as a misconfiguration.

Login needs the server's public URL: set `MCP_PUBLIC_URL=https://…`. On Railway it is
derived from `RAILWAY_PUBLIC_DOMAIN` automatically. Register
`https://<domain>/auth/callback` as the redirect URI at Google/Microsoft (exact console
steps in GUIDE.md step 3).

Login state (OAuth client registrations, encrypted upstream tokens) is stored under
`FASTMCP_HOME`. When a Railway volume is attached the server uses it automatically, so
users stay logged in across deploys. Optional hardening: `MCP_JWT_SIGNING_KEY` (keeps
sessions valid when you rotate the OAuth client secret) and
`MCP_ALLOWED_CLIENT_REDIRECT_URIS` (restrict which MCP clients may complete a login,
e.g. `http://localhost:*,https://claude.ai/*`).

`MCP_ALLOW_UNAUTHENTICATED=true` disables all of this for local testing only; the server
then listens on `127.0.0.1` and logs a warning.

## Read-only mode and audit log

- `MCP_READ_ONLY=true` hides every tool that creates, changes, books or deletes anything
  (15 tools) and limits `economic_api_request` to `GET`. Start with it on.
- Every tool call is logged as `tool=… user=… status=… duration_ms=…` on the
  `economic-mcp.audit` logger. `user` is the e-mail of the logged-in person, the key name
  (`cfo`, `anna`) for personal access keys, or `service-token`. Arguments and data are never logged.

## Configuration reference

| Variable | Default | Purpose |
|---|---|---|
| `ECONOMIC_APP_SECRET_TOKEN` | `demo` | e-conomic `X-AppSecretToken` |
| `ECONOMIC_AGREEMENT_GRANT_TOKEN` | `demo` | e-conomic `X-AgreementGrantToken` |
| `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` | | Google login |
| `AZURE_CLIENT_ID` / `AZURE_CLIENT_SECRET` / `AZURE_TENANT_ID` | | Microsoft login |
| `AZURE_API_SCOPE` / `AZURE_IDENTIFIER_URI` | `access_as_user` / `api://<client-id>` | Scope exposed by your Entra app |
| `MCP_ALLOWED_EMAILS` / `MCP_ALLOWED_DOMAINS` | | Comma-separated allowlist |
| `MCP_AUTH_TOKEN_<NAME>` | | One access key per person (32+ chars); `<NAME>` becomes the identity in the audit log |
| `MCP_AUTH_TOKEN` | | Access key for automations (identity `service-token`) |
| `MCP_USER_<NAME>` | | `email:pbkdf2_sha256$…` for e-mail + password login (create with `scripts/new_user.py`) |
| `MCP_LOGIN_SESSION_DAYS` / `MCP_LOGIN_ACCESS_TOKEN_MINUTES` | `30` / `60` | Lifetimes for e-mail login sessions and access tokens |
| `MCP_PUBLIC_URL` | from `RAILWAY_PUBLIC_DOMAIN` | Public https URL, needed for login |
| `MCP_READ_ONLY` | `false` | Hide write tools |
| `MCP_ALLOW_UNAUTHENTICATED` | `false` | Local testing only |
| `MCP_JWT_SIGNING_KEY` | derived from client secret | Signing key for issued tokens |
| `MCP_ALLOWED_CLIENT_REDIRECT_URIS` | all | Redirect URI patterns for MCP clients |
| `MCP_HOST` | `0.0.0.0` (with auth) / `127.0.0.1` | Bind address |
| `PORT` | `8000` | Injected by Railway |
| `FASTMCP_HOME` | platform data dir / Railway volume | Login state storage |
| `ECONOMIC_BASE_URL` | `https://restapi.e-conomic.com` | HTTPS only (http for localhost) |
| `ECONOMIC_REQUEST_TIMEOUT_SECONDS` / `ECONOMIC_MAX_RETRIES` | `30` / `2` | HTTP client tuning |
| `LOG_LEVEL` | `INFO` | Logging |

`.env.example` documents the same variables with comments.

## e-conomic tokens

e-conomic uses two token headers (see [developer docs](https://www.e-conomic.com/developer/connect)):
`X-AppSecretToken` identifies your app, `X-AgreementGrantToken` grants it access to one
agreement. Both default to `demo`, e-conomic's read-only demo agreement.

1. Sign up for a free developer agreement at e-conomic.com/developer.
2. In the developer agreement: **Apps → New app**, choose the least role you need, save the **AppSecretToken**.
3. Click **Tokens** on the app, open the installation URL while logged into the target agreement, approve, and save the **AgreementGrantToken**.
4. Verify with `GET https://restapi.e-conomic.com/self` or `python scripts/doctor.py`.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # set MCP_AUTH_TOKEN_<NAME>, or MCP_ALLOW_UNAUTHENTICATED=true for local play
python server.py
python scripts/doctor.py
```

The MCP endpoint is `http://127.0.0.1:8000/mcp`, health at `/health`.

## Deploy on Railway

Two ways; both use `railway.json` (start command `python server.py`, health check `/health`).

- **From your clone with the CLI** (see Quick start). Update with `git pull && railway up --detach`.
- **From a GitHub fork**: New Project → Deploy from GitHub repo → set variables →
  Settings → Networking → Generate Domain. Railway redeploys when the fork changes.

The volume (`railway volume add --mount-path /data`, part of the quick start) is where login
state lives; the server detects `RAILWAY_VOLUME_MOUNT_PATH` automatically. Without it every
deploy logs all users out.

## Connect an MCP client

Endpoint: `https://<your-domain>/mcp`.

**Claude Code**
```bash
claude mcp add --transport http --scope user economic https://<your-domain>/mcp
# then /mcp inside Claude Code to log in; or, with an access key:
claude mcp add --transport http economic https://<your-domain>/mcp --header "Authorization: Bearer <your key>"
```

**claude.ai / Claude Desktop**: Settings → Connectors → Add custom connector → paste the
URL → Connect (personal login). For access-key-only servers use `mcp-remote`:

```json
{
  "mcpServers": {
    "economic": {
      "command": "npx",
      "args": ["-y", "mcp-remote@latest", "https://<your-domain>/mcp", "--header", "Authorization:${AUTH_HEADER}"],
      "env": {"AUTH_HEADER": "Bearer <your-access-key>"}
    }
  }
}
```

**Codex**
```bash
codex mcp add economic --url https://<your-domain>/mcp
codex mcp login economic
```
Access key instead: `bearer_token_env_var = "ECONOMIC_MCP_TOKEN"` under `[mcp_servers.economic]` in `~/.codex/config.toml`.

**Clients with native Streamable HTTP** (`.mcp.json`, Cursor, Windsurf):
```json
{
  "mcpServers": {
    "economic": {
      "type": "http",
      "url": "https://<your-domain>/mcp",
      "headers": {"Authorization": "Bearer ${ECONOMIC_MCP_TOKEN}"}
    }
  }
}
```
Omit `headers` when using personal login.

## Skills (ready-made workflows)

The `skills/` folder ships seven Danish skills for Claude Code, Codex and any client
that follows the Agent Skills standard: debtor follow-up, monthly report, customer 360,
account statements and reconciliation, precise data answers, draft invoices and journal
vouchers. Write skills always show a proposal and wait for a yes; booking is only done on
explicit request. See [skills/README.md](skills/README.md).

Install in Claude Code as a plugin:

```
/plugin marketplace add inbound-cph/economic-mcp-byinboundcph
/plugin install economic@economic-mcp
```

Or copy them as personal skills for Claude Code and Codex:

```bash
python scripts/install_skills.py
```

## Test

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

The suite uses FastMCP's in-memory client and HTTPX mock transport; it never touches
e-conomic. It covers the e-conomic client, all auth modes and the allowlist, read-only
mode, tool annotations, the audit log and the fail-closed startup.

## Reliability and security

- Mandatory authentication: per-person access keys or personal login with an allowlist enforced at login and per request; optional read-only mode; audit log with the caller's name.
- Pooled HTTP client for the server lifespan; transport failures and HTTP `429`, `502`, `503`, `504` retried with bounded backoff.
- Every non-GET operation carries one e-conomic `Idempotency-Key`, reused across retries.
- API paths reject absolute URLs, query strings, fragments and relative traversal; product numbers and fiscal years use e-conomic's custom resource encoding.
- API errors keep HTTP status, structured body, developer hint and `logId` without logging tokens.
- HTTPS-only base URL (http allowed for localhost only); no outbound calls other than e-conomic and the identity provider.
- See [SECURITY.md](SECURITY.md) for the security model and how to report issues.

## Notes / gotchas

- Stateless Streamable HTTP with FastMCP's host/origin protection defaults.
- e-conomic paginates with `skippages`/`pagesize` (max 1000); exposed as `skip_pages`/`page_size`.
- `register_invoice_as_sent` books and sends the draft through `/invoices/booked`; like `book_draft_invoice` this is **irreversible**.
- `register_quote_as_sent` fetches and reposts the complete unchanged quote, as e-conomic requires.
- `create_draft_invoice` lines need a `productNumber` that exists on the agreement (`list_products`).
- `demo` tokens are read-only; write tools fail with them.
- The e-conomic API has no versioned URL; runtime dependencies are pinned for reproducible deployments.

## Troubleshooting

- **Server exits with "refuses to start"**: no auth configured. Set a personal key (`MCP_AUTH_TOKEN_<NAME>`) or the Google/Microsoft variables.
- **"Invalid authentication configuration: …"**: the message names the missing or invalid variable.
- **`access_denied` at login**: the account is not on the allowlist (Google also requires a verified e-mail).
- **E-mail login says "For mange forsøg"**: five wrong passwords locked that e-mail/IP for 15 minutes.
- **E-mail login page says the page expired**: the login link is valid for 10 minutes and once; reconnect from the client.
- **Google `redirect_uri_mismatch`**: the redirect URI must be exactly `https://<domain>/auth/callback`.
- **Microsoft `AADSTS65001` / `AADSTS650057`**: add the scope under API permissions and set `requestedAccessTokenVersion` to 2.
- **Clients keep asking to log in after deploys**: attach a Railway volume.
- **`401` from e-conomic**: verify both tokens and that the grant has not been revoked.
- **Write tools missing**: `MCP_READ_ONLY=true`; set it to `false` when you are ready.
- **`429` or temporary `5xx`**: retried automatically; adjust `ECONOMIC_MAX_RETRIES` only if necessary.
- **Invalid fiscal-year path**: pass the exact `year` from `list_accounting_years`; split years such as `2025/2026` are encoded automatically.

## API reference

- REST docs: https://restdocs.e-conomic.com/
- Auth: https://www.e-conomic.com/developer/authentication
- FastMCP auth: https://gofastmcp.com/servers/auth

## Contributing

This is a public, source-available project by [InboundCPH](https://inboundcph.dk). Improvements are welcome:
open an issue or a pull request. Run `python -m pytest -q` before submitting, keep write
tools tagged `write`, and never commit tokens or `.env` files. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[PolyForm Shield 1.0.0](https://polyformproject.org/licenses/shield/1.0.0), see [LICENSE](LICENSE).
Copyright INBOUND CPH A/S. In short: you may use, change and share the software freely,
including inside your own business and to help your own clients, but you may not sell it or
offer it as a product or service that competes with it or with what INBOUND CPH offers using it.
