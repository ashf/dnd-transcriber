"""Download the corrections friends sent from the wiki into the campaign's work folder.

    uv run python wiki/pull_corrections.py "My Campaign/corrections.md"

Reads every stored correction with `wrangler d1 execute` (you must have run `npx wrangler login`) and rewrites
the file, grouped by page, oldest first. The cleanup reads it as context for the next session.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

WIKI = Path(__file__).parent
DATABASE = "campaign-corrections"
QUERY = "SELECT id, page, text, email, created_at FROM corrections ORDER BY page, id"


def to_markdown(rows: list[dict]) -> str:
    lines = ["# Corrections from the wiki", "", "Friends sent these from the wiki pages. Each names the page it is about."]
    page = None
    for row in rows:
        if row["page"] != page:
            page = row["page"]
            lines += ["", f"## {page}", ""]
        text = " ".join(row["text"].split())
        lines.append(f"- {row['created_at'][:10]}, {row['email']}: {text}")
    return "\n".join(lines) + "\n"


def fetch_rows() -> list[dict]:
    try:
        out = subprocess.run(
            ["npx", "wrangler", "d1", "execute", DATABASE, "--remote", "--json", "--command", QUERY],
            cwd=WIKI,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except subprocess.CalledProcessError as e:
        sys.exit(f"wrangler failed: {e.stderr.strip() or e.stdout.strip()}")
    return json.loads(out)[0]["results"]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", type=Path, help="where to write corrections.md")
    args = ap.parse_args(argv)
    rows = fetch_rows()
    args.out.write_text(to_markdown(rows))
    print(f"Wrote {len(rows)} corrections to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
