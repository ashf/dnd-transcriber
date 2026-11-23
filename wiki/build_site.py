"""Build the private campaign wiki from a campaign folder.

    uv run --group wiki python wiki/build_site.py "My Campaign" --characters "My Campaign/characters.json" --title "My Campaign"

Reads the campaign's characters overview (characters.md), its world notes (world.md) with pictures from its world/
folder (each named after the entry it shows, like "the_larder_creature.webp"), and every session folder ("Session 1/") with its
"<session> - <output>.md" files and its images (in the session folder or its images/ folder), and builds the
site into wiki/site. The Characters page shows each character's portrait from the characters file. On an image
prompts page, an image whose file name starts with a scene's title or number ("The Armor Awakens.jpeg",
"3 alt.png") appears under that scene; any other image goes in a gallery at the end. Nothing from a work/
folder is published.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

WIKI = Path(__file__).parent
OUTPUT_ORDER = ["summary", "character developments", "laughs", "image prompts", "transcript"]
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def natural_key(text: str) -> tuple:
    return tuple(int(p) if p.isdigit() else p for p in re.split(r"(\d+)", text))


def output_key(output: str) -> tuple:
    return (OUTPUT_ORDER.index(output) if output in OUTPUT_ORDER else len(OUTPUT_ORDER), output)


def collect(campaign: Path) -> dict[str, dict[str, Path]]:
    """Each session folder's outputs, sessions in number order and outputs in reading order."""
    sessions = {}
    for folder in sorted((p for p in campaign.iterdir() if p.is_dir()), key=lambda p: natural_key(p.name)):
        prefix = f"{folder.name} - "
        outputs = {p.name[len(prefix) : -3]: p for p in folder.glob("*.md") if p.name.startswith(prefix)}
        if outputs:
            sessions[folder.name] = dict(sorted(outputs.items(), key=lambda kv: output_key(kv[0])))
    return sessions


def images(session_folder: Path) -> list[Path]:
    found = [p for d in (session_folder, session_folder / "images") for p in d.glob("*") if p.suffix.lower() in IMAGE_TYPES]
    return sorted(found, key=lambda p: natural_key(p.name))


def with_images(page: str, files: list[str]) -> str:
    """Put each image under the '## N. Title' scene whose number or title its file name starts with."""
    titles = {m[1]: m[2].strip().lower() for m in re.finditer(r"(?m)^## (\d+)\.\s*(.+)$", page)}
    numbered: dict[str, list[str]] = {}
    loose = []
    for name in files:
        m = re.match(r"(\d+)\b", name)
        scene = m[1] if m else next((n for n, t in titles.items() if name.lower().startswith(t)), None)
        (numbered.setdefault(scene, []) if scene else loose).append(name)
    sections = [s for s in re.split(r"(?m)^(?=## )", page) if s]
    out = []
    for section in sections:
        m = re.match(r"## (\d+)\.", section)
        shown = numbered.pop(m[1], []) if m else []
        out.append(section.rstrip("\n") + "\n" + "".join(f"\n![]({quote('images/' + n)})\n" for n in shown) + ("\n" if shown else ""))
    loose += [n for names in numbered.values() for n in names]
    if loose:
        out.append("## Gallery\n" + "".join(f"\n![]({quote('images/' + n)})\n" for n in loose))
    return "\n".join(s.rstrip("\n") + "\n" for s in out)


def tidy_markdown(text: str) -> str:
    """Make lists render in MkDocs: a blank line before a list, and 4-space indents for nested items."""
    lines = text.splitlines()
    item = re.compile(r"^( *)([-*+] |\d+\. )")
    two_space = any((m := item.match(line)) and len(m[1]) % 4 for line in lines)
    out: list[str] = []
    for line in lines:
        m = item.match(line)
        if m:
            if two_space and m[1]:
                line = " " * (len(m[1]) * 2) + line.lstrip(" ")
            if out and out[-1].strip() and not re.match(r"^ *([-*+] |\d+\. )", out[-1]):
                out.append("")
        out.append(line)
    return "\n".join(out) + "\n"


def with_portraits(page: str, characters: dict, portrait_urls: dict[str, str]) -> str:
    """Put each character's portrait under the first '## ' heading that names them."""
    lines, done = [], set()
    for line in page.splitlines():
        lines.append(line)
        if line.startswith("## "):
            heading = line[3:].lower()
            for c in characters["characters"]:
                names = [c["name"], c["name"].split()[0], *c.get("nicknames", [])]
                if c["name"] not in done and c["name"] in portrait_urls and any(n.lower() in heading for n in names):
                    lines += ["", f"![{c['name']}]({portrait_urls[c['name']]}){{ align=right width=\"220\" }}", ""]
                    done.add(c["name"])
                    break
    return "\n".join(lines) + "\n"


def entry_key(text: str) -> str:
    """Compare an image file name with a heading: lowercase, words only, no '[sp?]' and no leading 'the'."""
    words = re.sub(r"[^a-z0-9]+", " ", text.lower().replace("[sp?]", "")).split()
    return " ".join(words[1:] if words[:1] == ["the"] else words)


def with_entry_images(page: str, image_urls: dict[str, str]) -> str:
    """Put each image under the heading its file name matches, floated beside the entry's text."""
    lines = []
    for line in page.splitlines():
        lines.append(line)
        m = re.match(r"^#{2,6} (.+)$", line)
        if m and (url := image_urls.pop(entry_key(m[1]), None)):
            lines += ["", f"![{m[1]}]({url}){{ align=right width=\"260\" }}", ""]
    return "\n".join(lines) + "\n"


def page_path(session: str, output: str) -> str:
    return f"sessions/{slug(session)}/{slug(output)}.md"


def mkdocs_config(title: str, sessions: dict[str, dict[str, Path]], has_characters: bool, has_world: bool = False) -> str:
    lines = [
        f"site_name: {title!r}",
        "theme:",
        "  name: material",
        "  custom_dir: overrides",
        "  features: [navigation.sections, navigation.top, search.highlight]",
        "  palette:",
        "    - scheme: slate",
        "      primary: deep purple",
        "plugins:",
        "  - search",
        "  # Click any image to see it full size.",
        "  - glightbox",
        "markdown_extensions:",
        "  - tables",
        "  - attr_list",
        "  - md_in_html",
        "  - toc:",
        "      toc_depth: 2",
        "nav:",
        "  - Home: index.md",
    ]
    if has_characters:
        lines.append("  - Characters: characters.md")
    if has_world:
        lines.append("  - World: world.md")
    lines.append("  - Sessions:")
    for session, outputs in reversed(sessions.items()):
        lines.append(f"    - {session!r}:")
        lines += [f"      - {output.title()!r}: {page_path(session, output)!r}" for output in outputs]
    return "\n".join(lines) + "\n"


def home_page(title: str, sessions: dict[str, dict[str, Path]]) -> str:
    rows = [f"# {title}", "", "## Sessions", ""]
    for session, outputs in reversed(sessions.items()):
        links = ", ".join(f"[{o}]({page_path(session, o)})" for o in outputs)
        rows.append(f"- **{session}**: {links}")
    return "\n".join(rows) + "\n"


def build(campaign: Path, characters_file: Path, title: str, wiki: Path = WIKI) -> None:
    sessions = collect(campaign)
    if not sessions:
        sys.exit(f"No session folders with '<session> - <output>.md' files in {campaign}")
    characters = json.loads(characters_file.read_text())
    docs = wiki / "docs"
    shutil.rmtree(docs, ignore_errors=True)

    for session, outputs in sessions.items():
        folder = docs / f"sessions/{slug(session)}"
        folder.mkdir(parents=True, exist_ok=True)
        pictures = images(campaign / session)
        for picture in pictures:
            (folder / "images").mkdir(exist_ok=True)
            shutil.copyfile(picture, folder / "images" / picture.name)
        for output, path in outputs.items():
            text = path.read_text()
            if output == "image prompts":
                text = with_images(text, [p.name for p in pictures])
            (docs / page_path(session, output)).write_text(tidy_markdown(text))

    overview = campaign / "characters.md"
    if overview.exists():
        portrait_urls = {}
        for c in characters["characters"]:
            portrait = campaign / c.get("source_files", {}).get("portrait", "")
            if portrait.is_file():
                target = docs / "assets" / "portraits" / f"{slug(c['name'])}{portrait.suffix.lower()}"
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(portrait, target)
                portrait_urls[c["name"]] = f"assets/portraits/{target.name}"
        (docs / "characters.md").write_text(tidy_markdown(with_portraits(overview.read_text(), characters, portrait_urls)))

    world = campaign / "world.md"
    if world.exists():
        image_urls = {}
        for picture in images(campaign / "world"):
            target = docs / "assets" / "world" / picture.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(picture, target)
            image_urls[entry_key(picture.stem)] = quote(f"assets/world/{picture.name}")
        page = with_entry_images(world.read_text(), image_urls)
        for leftover in image_urls:
            print(f"No world entry matches the image {leftover!r}", file=sys.stderr)
        (docs / "world.md").write_text(tidy_markdown(page))

    (docs / "index.md").write_text(home_page(title, sessions))
    (wiki / "mkdocs.yml").write_text(mkdocs_config(title, sessions, overview.exists(), world.exists()))
    subprocess.run(["mkdocs", "build", "--clean", "--quiet"], cwd=wiki, check=True)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("campaign", type=Path, help="the campaign folder, holding one folder per session")
    ap.add_argument("--characters", type=Path, required=True, help="the characters JSON (for portraits)")
    ap.add_argument("--title", required=True)
    args = ap.parse_args(argv)
    build(args.campaign, args.characters, args.title)
    print(f"Built {WIKI / 'site'}", file=sys.stderr)


if __name__ == "__main__":
    main()
