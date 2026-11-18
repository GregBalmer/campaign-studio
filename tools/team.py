"""Add, list or remove the people who can sign in to Campaign Studio.

    python3 tools/team.py list
    python3 tools/team.py add "Full Name" name@company.com ["Role"]
    python3 tools/team.py remove name@company.com

`add` asks for a password (it isn't shown or stored as typed: only a salted hash
is kept in workspace/team.json). In production this list is the client's single
sign-on directory instead.
"""
from __future__ import annotations

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from studio import auth  # noqa: E402


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "list"
    if cmd == "list":
        for email, p in sorted(auth.team().items()):
            print(f"  {p['name']:<22} {email:<30} {p.get('role', '')}{'  (demo)' if p.get('demo') else ''}")
        return 0
    if cmd == "add" and len(argv) >= 3:
        name, email, role = argv[1], argv[2], argv[3] if len(argv) > 3 else ""
        pw = getpass.getpass(f"Password for {name}: ")
        if getpass.getpass("Again: ") != pw:
            print("The passwords didn't match. Nothing was changed.")
            return 1
        try:
            auth.add_person(name, email, pw, role)
        except auth.AuthError as e:
            print(e)
            return 1
        print(f"Added {name}. They can sign in with {email.lower()}.")
        return 0
    if cmd == "remove" and len(argv) == 2:
        print("Removed." if auth.remove_person(argv[1]) else "No one with that email.")
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
