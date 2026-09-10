# Security

This server gives an AI assistant access to accounting data. Treat it like any other
system that holds financial records. This document describes the threat model: what the
server protects against, what it does not, and what you as operator must do.

## What we protect

- **The e-conomic tokens** (`ECONOMIC_APP_SECRET_TOKEN`, `ECONOMIC_AGREEMENT_GRANT_TOKEN`).
  They never leave the server; clients only ever talk to the MCP endpoint.
- **The accounting data** reachable through those tokens: customers, invoices, entries,
  and the ability to create, book and delete.
- **Who did what**: an audit trail with a real identity per call.

## Trust boundaries

```
 user's device            Anthropic / OpenAI cloud        your Railway project        e-conomic
 ┌──────────────┐  login   ┌────────────────────┐  MCP   ┌──────────────────────┐  API  ┌────────┐
 │ Claude Code, │ ───────▶ │ claude.ai connector│ ─────▶ │ this server          │ ────▶ │ REST   │
 │ Desktop,     │  or key  │ (or none: direct)  │        │ auth · read-only ·   │ tokens│ API    │
 │ Codex        │ ───────────────────────────────────▶   │ audit log            │       └────────┘
 └──────────────┘                                        └──────────────────────┘
```

The server is the gate. Everything left of it is untrusted until a request carries a valid
credential; everything right of it is trusted with the operator's e-conomic role.

## How the server protects the data

- **Authentication is mandatory.** The server refuses to start unless a login method is
  configured. Unauthenticated mode exists only for local testing, listens on `127.0.0.1`
  and logs a warning.
- **Three login methods, one identity per person.**
  - *Personal access keys* (`MCP_AUTH_TOKEN_<NAME>`): 32+ character bearer tokens, one per
    person. The name is the identity; deleting the variable revokes.
  - *Google / Microsoft login*: OAuth 2.1 with PKCE through FastMCP's OAuth proxy. Only
    e-mail addresses or domains on the allowlist (or members of your own Microsoft tenant)
    are accepted, both when logging in and on every request.
  - *E-mail + password login hosted by the server* (`MCP_USER_*`): PBKDF2-SHA256 hashes
    (600 000 rounds) compared in constant time, lockout after five failures per e-mail or IP,
    single-use short-lived login transactions, PKCE-protected single-use codes, one-hour
    access tokens, 30-day rotating refresh tokens stored only as hashes. The login page shows
    the redirect destination; `MCP_ALLOWED_CLIENT_REDIRECT_URIS` can restrict it.
- **Least privilege.** `MCP_READ_ONLY=true` hides every write tool for everyone;
  `MCP_WRITE_USERS` limits write tools to named people. Write tools are hidden *and*
  blocked for everyone else, and the generic API tool is limited to `GET` for them.
- **Audit log.** Every tool call is logged with identity, tool name, outcome and duration.
  Tool arguments and e-conomic data are never logged.
- **Tool annotations** mark write tools as non-read-only and destructive so MCP clients
  can ask the user before running them.
- **Hardened e-conomic client.** HTTPS only, path validation against traversal and query
  injection, bounded retries, idempotency keys on every write, no token logging.
- **Login state** lives encrypted or hashed under `FASTMCP_HOME`, placed on the Railway
  volume automatically.

## Known limitations (read these before you rely on the server)

1. **Railway holds the keys.** e-conomic tokens, access keys and password hashes are
   Railway variables. Anyone with access to the Railway project has everything. Keep
   project membership minimal and enable two-factor authentication on Railway.
2. **Access keys do not expire.** A leaked key (chat log, screenshot, stolen laptop) works
   until you delete its variable. Clients store keys in plain text in their configuration.
   Prefer a login method for larger groups and rotate keys when someone leaves.
3. **E-mail login has no MFA** and no self-service reset. Its lockout is per e-mail and per
   IP and lives in memory, so it resets on deploy, and five wrong attempts against a
   colleague's address lock her out for 15 minutes. Google or Microsoft login is stronger.
4. **Prompt injection through accounting data.** Text stored in e-conomic (a customer
   name, an invoice line from a supplier) reaches the AI assistant and could try to make it
   book, change or delete something. Read-only mode, `MCP_WRITE_USERS`, tool annotations and
   the skills' confirm-before-writing rules reduce this; a user who auto-approves write
   tools in their client removes that protection. Keep writes with as few people as possible
   and never auto-approve write tools.
5. **The login page costs CPU** by design (slow hashing). Many concurrent attempts from many
   addresses can slow the server down. Fine for a company server; a public product would
   need rate limiting in front.
6. **Audit logs live in Railway's logs** with limited retention and no tamper protection.
   Export them if you need compliance-grade records.
7. **Dependencies are pinned** for reproducibility, which means someone must update them.
   Watch FastMCP and httpx advisories; enable Dependabot on your fork.
8. **The e-conomic role is the ceiling.** The server can never do more than the app's role
   in e-conomic allows, but also never less. Give the app the smallest role that covers the
   job, and use a separate app per company.

## What you are responsible for

- Keep tokens, client secrets, access keys and passwords out of git, chat logs and
  screenshots. Rotate them if they leak (e-conomic: revoke the app's grant; Google/Microsoft:
  new client secret; keys/users: delete the variable and create a new one).
- Start with `MCP_READ_ONLY=true`; when you enable writes, list the people in
  `MCP_WRITE_USERS`.
- Keep the allowlist, key and user lists short, and remove people who leave.
- Attach a volume so sessions survive deploys, and update the server when dependencies
  are updated (`git pull`, redeploy).
- Have a person with security experience review `auth.py` and `local_users.py` before
  you expose the server to more than a handful of trusted users.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting on this repository
(Security → Report a vulnerability) rather than opening a public issue.
