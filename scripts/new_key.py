#!/usr/bin/env python3
"""
Create a personal access key for one person and show how to store it.

    python scripts/new_key.py anna                      # key for Anna
    python scripts/new_key.py cfo --service economic-mcp

Each person gets their own variable, MCP_AUTH_TOKEN_<NAME>. The audit log then shows the
name, and deleting the variable removes that person's access. The key is printed once;
hand it to the person through a secure channel (password manager, not e-mail).
"""

from __future__ import annotations

import argparse
import re
import secrets
import sys

NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("name", help="short name of the person, e.g. anna or cfo (letters, digits, - and _)")
    parser.add_argument("--service", default="economic-mcp", help="Railway service name (default: economic-mcp)")
    args = parser.parse_args()

    name = args.name.strip().lower()
    if not NAME_PATTERN.match(name):
        print("The name may only contain lowercase letters, digits, '-' and '_' (max 32 characters).")
        return 1

    key = secrets.token_hex(32)
    variable = f"MCP_AUTH_TOKEN_{name.upper()}"
    print(f"Access key for '{name}' (shown once):\n\n  {key}\n")
    print("Store it on the server, one of:")
    print(f"  Railway dashboard: service -> Variables -> New variable -> {variable}")
    print(f"  Railway CLI:       echo \"{key}\" | railway variable set {variable} --stdin --service {args.service}")
    print(f"  Local .env:        {variable}={key}\n")
    print(f"Give '{name}' the key and this client setup (replace <domain>):")
    print(f"  Claude Code:  claude mcp add --transport http economic https://<domain>/mcp --header \"Authorization: Bearer {key}\"")
    print("  Codex:        codex mcp add economic --url https://<domain>/mcp, then bearer_token_env_var in ~/.codex/config.toml")
    print("  Claude Desktop: mcp-remote entry in claude_desktop_config.json with the same Authorization header (see README)")
    print(f"\nTo revoke: delete the variable {variable}. Railway redeploys automatically.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
