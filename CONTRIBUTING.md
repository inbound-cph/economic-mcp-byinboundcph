# Contributing

Thanks for helping improve the e-conomic MCP server. It is used by real companies on
real accounting data, so small, well-tested changes are preferred.

## Before you open a pull request

1. Fork the repository and create a branch.
2. Install: `pip install -r requirements-dev.txt`.
3. Run the tests: `python -m pytest -q`. They need no network and no e-conomic tokens.
4. Add tests for anything you change in `server.py` or `auth.py`.

## Ground rules

- **Security first.** Never weaken the fail-closed startup, the allowlist or the
  read-only mode. Never log tokens, tool arguments or accounting data.
- **Write tools** must be declared with `tags={"write"}` and a non-read-only annotation so
  `MCP_READ_ONLY` hides them. Update the tool counts in `tests/test_auth.py` (currently 73
  total, 58 in read-only mode) when adding tools.
- **Skills** live in `skills/<name>/SKILL.md` (Agent Skills format, Danish body). Write
  skills show a proposal and wait for an explicit yes. Bump `version` in
  `.claude-plugin/plugin.json` when skills change.
- **Documentation** is in two languages on purpose: `GUIDE.md` (Danish, for users) and
  `README.md` (English, reference). Keep both in sync when behaviour changes.
- Never commit `.env`, tokens or client secrets. `.gitignore` already excludes `.env`.

## License of contributions

By opening a pull request you agree that your contribution is licensed under the same
terms as the project (PolyForm Shield 1.0.0, see LICENSE) with INBOUND CPH A/S as licensor.

## Reporting problems

Bugs and ideas: open an issue. Security problems: use GitHub's private vulnerability
reporting (Security → Report a vulnerability) instead of a public issue.
