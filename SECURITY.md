# Security

This server gives an AI assistant access to accounting data. Treat it like any other
system that holds financial records.

## How the server protects the data

- **Authentication is mandatory.** The server refuses to start unless Google login,
  Microsoft login or an access key is configured. Unauthenticated mode exists only for
  local testing, listens on `127.0.0.1` and logs a warning.
- **Personal logins with an allowlist.** Google and Microsoft login use OAuth 2.1 with
  PKCE through FastMCP's OAuth proxy. Only e-mail addresses or domains on the allowlist
  (or members of your own Microsoft tenant) are accepted, both when logging in and on
  every request. Rejected accounts get an `access_denied` error.
- **E-mail + password login** (optional, `MCP_USER_*`) is hosted by the server: PBKDF2-SHA256
  hashes with 600 000 rounds and constant-time comparison, lockout after five failures per
  e-mail or IP, single-use short-lived login transactions, PKCE-protected single-use codes,
  one-hour access tokens, 30-day rotating refresh tokens stored only as hashes. No MFA;
  prefer Google/Microsoft login when available.
- **Access keys are personal.** One `MCP_AUTH_TOKEN_<NAME>` per person (32+ characters),
  compared as bearer tokens; the audit log records the name and deleting the variable
  revokes that person. `MCP_AUTH_TOKEN` without a name serves automations. Keys can coexist
  with a login.
- **Read-only mode** (`MCP_READ_ONLY=true`) hides every tool that creates, changes, books
  or deletes anything and limits the generic API tool to `GET`.
- **Audit log.** Every tool call is logged with the caller's identity, the tool name,
  the outcome and the duration. Tool arguments and e-conomic data are never logged.
- **Tool annotations** mark write tools as non-read-only and destructive so MCP clients
  can ask the user before running them.
- **Hardened e-conomic client.** HTTPS only, path validation against traversal and
  query injection, bounded retries, idempotency keys on every write, no token logging.
- **Login sessions** (OAuth client registrations, encrypted upstream tokens) are stored
  encrypted on disk under `FASTMCP_HOME`, which is placed on the Railway volume
  automatically when one is attached.

## What you are responsible for

- Keep the e-conomic tokens, OAuth client secret and access key out of git, chat logs
  and screenshots. Rotate them if they leak (e-conomic: revoke the app's grant;
  Google/Microsoft: create a new client secret; access key: generate a new one).
- Give the e-conomic app the least role it needs. Start with read access and
  read-only mode; enable writes only when you have tested the workflow.
- Keep the allowlist short and remove people who leave.
- Update the server when dependencies are updated (`git pull`, redeploy).

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting on this repository
(Security → Report a vulnerability) rather than opening a public issue.
