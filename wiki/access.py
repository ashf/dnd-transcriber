"""Manage who can read the wiki.

    uv run python wiki/access.py requests                 # pending requests
    uv run python wiki/access.py approve friend@gmail.com # let them in and email them
    uv run python wiki/access.py welcome friend@gmail.com # email a member the welcome again
    uv run python wiki/access.py add me@gmail.com "Riley" # add someone directly
    uv run python wiki/access.py deny friend@gmail.com    # decline a request
    uv run python wiki/access.py revoke friend@gmail.com  # take access away
    uv run python wiki/access.py members                  # who is in

Talks to the wiki's D1 database with `wrangler d1 execute` (run `npx wrangler login` first). The welcome
email goes through Resend with the API key kept in the macOS Keychain (service "dnd-wiki-resend"); add
--quiet to approve without emailing.
"""

import argparse
import json
import tomllib
import urllib.error
import urllib.request
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

WIKI = Path(__file__).parent
DATABASE = "campaign-corrections"
KEYCHAIN_SERVICE = "dnd-wiki-resend"
EMAIL = re.compile(r"^[^@\s'\"]+@[^@\s'\"]+\.[^@\s'\"]+$")


def sql_text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def checked_email(value: str) -> str:
    email = value.strip().lower()
    if not EMAIL.match(email):
        sys.exit(f"Not an email address: {value}")
    return email


def run(sql: str) -> list[dict]:
    try:
        out = subprocess.run(
            ["npx", "wrangler", "d1", "execute", DATABASE, "--remote", "--json", "--command", sql],
            cwd=WIKI, capture_output=True, text=True, check=True,
        ).stdout
    except subprocess.CalledProcessError as e:
        sys.exit(f"wrangler failed: {e.stderr.strip() or e.stdout.strip()}")
    return json.loads(out)[-1]["results"]


def approve_sql(email: str, name: str | None = None) -> str:
    now = sql_text(datetime.now(timezone.utc).isoformat(timespec="seconds"))
    name_sql = sql_text(name) if name else f"COALESCE((SELECT name FROM access_requests WHERE email = {sql_text(email)}), {sql_text(email)})"
    return (
        f"INSERT INTO members (email, name, added_at) VALUES ({sql_text(email)}, {name_sql}, {now}) "
        f"ON CONFLICT(email) DO UPDATE SET name = excluded.name; "
        f"DELETE FROM access_requests WHERE email = {sql_text(email)};"
    )


def site_settings() -> dict:
    """SITE_NAME, SITE_URL and MAIL_FROM from the wiki's wrangler.toml, which stays out of git."""
    path = WIKI / "wrangler.toml"
    if not path.exists():
        sys.exit("Copy wiki/wrangler.example.toml to wiki/wrangler.toml and fill it in")
    return tomllib.loads(path.read_text())["vars"]


def welcome_email(name: str, email: str, site: dict) -> dict:
    return {
        "from": f"{site['SITE_NAME']} wiki <{site['MAIL_FROM']}>",
        "to": [email],
        "subject": f"You're in: {site['SITE_NAME']} wiki",
        "text": (
            f"Hi {name},\n\n"
            f"Your access to the {site['SITE_NAME']} wiki is approved. Open {site['SITE_URL']} and sign in with this "
            f"address ({email}).\n\n"
            "Spot a mistake? Every page has a corrections box at the bottom.\n"
        ),
    }


def resend_key() -> str | None:
    found = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"], capture_output=True, text=True)
    return found.stdout.strip() or None


def send_welcome(email: str) -> None:
    rows = run(f"SELECT name FROM members WHERE email = {sql_text(email)}")
    if not rows:
        sys.exit(f"{email} is not a member")
    key = resend_key()
    if not key:
        print(f"No Resend key in the Keychain ({KEYCHAIN_SERVICE}); no email sent to {email}", file=sys.stderr)
        return
    request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(welcome_email(rows[0]["name"], email, site_settings())).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "dnd-transcriber"},
    )
    try:
        urllib.request.urlopen(request, timeout=30)
        print(f"Emailed {email}", file=sys.stderr)
    except urllib.error.HTTPError as e:
        print(f"Approved, but the email to {email} failed: {e.code} {e.read().decode(errors='replace')}", file=sys.stderr)
    except urllib.error.URLError as e:
        print(f"Approved, but the email to {email} failed: {e.reason}", file=sys.stderr)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("requests")
    sub.add_parser("members")
    approve = sub.add_parser("approve")
    approve.add_argument("email")
    approve.add_argument("--quiet", action="store_true", help="do not email them")
    sub.add_parser("welcome").add_argument("email")
    add = sub.add_parser("add")
    add.add_argument("email")
    add.add_argument("name")
    sub.add_parser("revoke").add_argument("email")
    sub.add_parser("deny").add_argument("email")
    args = ap.parse_args(argv)

    if args.command == "requests":
        rows = run("SELECT email, name, note, requested_at FROM access_requests ORDER BY requested_at")
        for r in rows:
            print(f"{r['requested_at'][:10]}  {r['email']}  {r['name']}" + (f"  ({r['note']})" if r["note"] else ""))
        print(f"{len(rows)} pending", file=sys.stderr)
    elif args.command == "members":
        rows = run("SELECT email, name, added_at FROM members ORDER BY name")
        for r in rows:
            print(f"{r['name']}  {r['email']}  since {r['added_at'][:10]}")
    elif args.command == "approve":
        email = checked_email(args.email)
        if run(f"SELECT 1 FROM members WHERE email = {sql_text(email)}"):
            print(f"{email} is already a member; nothing changed (use `welcome` to resend the email)", file=sys.stderr)
            return
        run(approve_sql(email))
        print(f"Approved {email}", file=sys.stderr)
        if not args.quiet:
            send_welcome(email)
    elif args.command == "welcome":
        send_welcome(checked_email(args.email))
    elif args.command == "add":
        run(approve_sql(checked_email(args.email), args.name.strip()[:100]))
        print(f"Added {args.email}", file=sys.stderr)
    elif args.command == "deny":
        run(f"DELETE FROM access_requests WHERE email = {sql_text(checked_email(args.email))};")
        print(f"Denied {args.email}", file=sys.stderr)
    elif args.command == "revoke":
        run(f"DELETE FROM members WHERE email = {sql_text(checked_email(args.email))};")
        print(f"Revoked {args.email}", file=sys.stderr)


if __name__ == "__main__":
    main()
