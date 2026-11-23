"""Join a session's cleaned windows into one transcript, without retyping a line.

    uv run python join_windows.py "My Campaign/Session 1/work" "Session 1"

Reads "<session> (window N).clean.md" in window order and writes "<session> - transcript.md" one folder up:
one speaker map (each voice's row from the first window it appears in), then every line in order. A paragraph
that a window cut split in two, the same speaker on both sides of the cut, becomes one paragraph again.
"""

import argparse
import re
import sys
from pathlib import Path

PARAGRAPH = re.compile(r"^\*\*\[(\d\d:\d\d:\d\d)\] (.+?):\*\* (.*)$", re.S)


def window_number(path: Path) -> int:
    m = re.search(r"\(window (\d+)\)", path.name)
    return int(m[1]) if m else 0


def sections(text: str) -> tuple[list[str], list[str]]:
    """Speaker map table rows (header excluded) and transcript paragraphs of one cleaned window."""
    _, _, rest = text.partition("## Speaker map")
    table, _, body = rest.partition("## Transcript")
    rows = [line for line in table.strip().splitlines() if line.startswith("|")][2:]
    paragraphs = [p.strip() for p in body.strip().split("\n\n") if p.strip()]
    return rows, paragraphs


def join(session: str, windows: list[str]) -> str:
    rows: dict[str, str] = {}
    paragraphs: list[str] = []
    for text in windows:
        window_rows, window_paragraphs = sections(text)
        for row in window_rows:
            rows.setdefault(row.split("|")[1].strip(), row)
        if paragraphs and window_paragraphs:
            last, first = PARAGRAPH.match(paragraphs[-1]), PARAGRAPH.match(window_paragraphs[0])
            if last and first and last[2] == first[2]:
                paragraphs[-1] = f"{paragraphs[-1]} {first[3]}"
                window_paragraphs = window_paragraphs[1:]
        paragraphs += window_paragraphs
    header = "| Label | Person | Confidence | Evidence |\n|---|---|---|---|\n"
    return f"# {session}\n\n## Speaker map\n{header}" + "\n".join(rows.values()) + "\n\n## Transcript\n\n" + "\n\n".join(paragraphs) + "\n"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("work_dir", type=Path)
    ap.add_argument("session")
    ap.add_argument("--force", action="store_true", help="overwrite an existing transcript")
    args = ap.parse_args(argv)

    files = sorted(args.work_dir.glob(f"{args.session} (window *).clean.md"), key=window_number)
    if not files:
        sys.exit(f"No cleaned windows for {args.session} in {args.work_dir}")
    out = args.work_dir.parent / f"{args.session} - transcript.md"
    if out.exists() and not args.force:
        sys.exit(f"{out} exists; pass --force to overwrite it")
    out.write_text(join(args.session, [f.read_text() for f in files]))
    print(f"Joined {len(files)} windows into {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
