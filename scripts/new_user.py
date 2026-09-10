#!/usr/bin/env python3
"""
Create an e-mail + password user for the server's own login page.

    python scripts/new_user.py anna anna@firma.dk                # generates a strong password
    python scripts/new_user.py anna anna@firma.dk --service economic-mcp

The password is shown once. Only its hash goes into the variable MCP_USER_<NAME>, so the
server never stores the password itself. Deleting the variable removes the user; running
the script again gives the user a new password.
"""

from __future__ import annotations

import argparse
import re
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from local_users import MIN_PASSWORD_LENGTH, hash_password  # noqa: E402

NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("name", help="short name, e.g. anna or cfo (letters, digits, - and _)")
    parser.add_argument("email", help="the e-mail address the person logs in with")
    parser.add_argument("--service", default="economic-mcp", help="Railway service name (default: economic-mcp)")
    args = parser.parse_args()

    name = args.name.strip().lower()
    email = args.email.strip().lower()
    if not NAME_PATTERN.match(name):
        print("The name may only contain lowercase letters, digits, '-' and '_' (max 32 characters).")
        return 1
    if not EMAIL_PATTERN.match(email):
        print("That does not look like an e-mail address.")
        return 1

    password = secrets.token_urlsafe(18)  # 24 characters, URL-safe
    assert len(password) >= MIN_PASSWORD_LENGTH
    value = f"{email}:{hash_password(password)}"
    variable = f"MCP_USER_{name.upper()}"

    print(f"User '{name}' ({email}). Password, shown once:\n\n  {password}\n")
    print("Store the user on the server, one of:")
    print(f"  Railway dashboard: service -> Variables -> New variable -> {variable} with the value below")
    print(f"  Railway CLI:       echo '{value}' | railway variable set {variable} --stdin --service {args.service}")
    print(f"  Local .env:        {variable}={value}\n")
    print(f"Give '{name}' the password through a secure channel. They log in with their e-mail on the")
    print("server's login page the first time a client connects (claude.ai connector, Claude Desktop,")
    print("Claude Code /mcp, Codex mcp login).")
    print(f"\nTo remove the user: delete the variable {variable}. To reset the password: run this script again.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
