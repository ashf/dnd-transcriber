"""Step 2 through the Anthropic API: clean up a recording's base transcripts with CLEANUP_PROMPT.md.

Pass every hearing of one recording (<recording>.<model>.transcript.txt). Writes <recording>.clean.md next to them.
Context files can be text (.json, .md, .txt) or images; include the .clean.md files of earlier parts.
"""

import argparse
import base64
import mimetypes
import sys
from pathlib import Path

import anthropic

from transcribe import MODELS

MODEL = "claude-opus-5-5"
PROMPT = Path(__file__).with_name("CLEANUP_PROMPT.md")
IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
MAX_REQUEST_BYTES = 30 * 2**20  # the API rejects requests over 32 MB


def context_block(path: Path) -> list[dict]:
    mime = mimetypes.guess_type(path)[0]
    if mime in IMAGE_TYPES:
        data = base64.standard_b64encode(path.read_bytes()).decode()
        return [
            {"type": "text", "text": f"Image: {path.name}"},
            {"type": "image", "source": {"type": "base64", "media_type": mime, "data": data}},
        ]
    return [{"type": "text", "text": f"<file name=\"{path.name}\">\n{path.read_text()}\n</file>"}]


def recording_name(transcript: Path) -> str:
    name = transcript.name.removesuffix(".transcript.txt")
    stem, _, model = name.rpartition(".")
    return stem if stem and model in MODELS else name


def block_bytes(block: dict) -> int:
    return len(block["text"]) if block["type"] == "text" else len(block["source"]["data"])


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("transcripts", type=Path, nargs="+")
    ap.add_argument("--context", type=Path, nargs="+", required=True, help="characters JSON, notes, images")
    ap.add_argument("--drop-ooc", action="store_true", help="leave table talk out")
    ap.add_argument("--force", action="store_true", help="overwrite an existing .clean.md")
    args = ap.parse_args(argv)

    recordings = {(t.parent, recording_name(t)) for t in args.transcripts}
    if len(recordings) != 1:
        sys.exit(f"All transcripts must be hearings of one recording; got {sorted(n for _, n in recordings)}")
    folder, recording = recordings.pop()
    out = folder / f"{recording}.clean.md"
    if out.exists() and not args.force:
        sys.exit(f"{out} exists; pass --force to overwrite it")

    content = [block for p in args.context for block in context_block(p)]
    content += [block for p in args.transcripts for block in context_block(p)]
    if args.drop_ooc:
        content.append({"type": "text", "text": "Drop table talk from the transcript."})
    if (size := sum(block_bytes(b) for b in content)) > MAX_REQUEST_BYTES:
        sys.exit(f"Request is {size / 2**20:.1f} MB, over the API limit; pass fewer or smaller context files")

    client = anthropic.Anthropic()
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=128000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
        system=PROMPT.read_text(),
        messages=[{"role": "user", "content": content}],
    ) as stream:
        msg = stream.get_final_message()

    text = "".join(b.text for b in msg.content if b.type == "text")
    if msg.stop_reason != "end_turn":
        partial = out.with_name(out.name + ".partial")
        partial.write_text(text)
        sys.exit(f"Claude stopped early ({msg.stop_reason}); the output so far is in {partial}")
    out.write_text(text)
    print(f"Wrote {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
