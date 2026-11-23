from pathlib import Path

import build_site as b
import pull_corrections as p


def make(folder, *names):
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_text(f"# {name}\n")
    return folder


CHARACTERS = {"characters": [
    {"name": "Aria Vale", "player": "Jordan", "source_files": {"portrait": "aria portrait.png"}},
    {"name": "Brunn", "player": "Alex", "nicknames": ["Red"], "source_files": {"portrait": "missing.png"}},
]}


def test_collect_orders_sessions_by_number_and_outputs_by_kind(tmp_path):
    make(tmp_path / "Session 10", "Session 10 - summary.md")
    make(tmp_path / "Session 2", "Session 2 - transcript.md", "Session 2 - summary.md", "Session 2 - laughs.md", "notes.md")
    make(tmp_path / "portraits", "x.md")

    result = b.collect(tmp_path)

    assert [(s, list(o)) for s, o in result.items()] == [
        ("Session 2", ["summary", "laughs", "transcript"]),
        ("Session 10", ["summary"]),
    ]


def test_with_images_puts_numbered_images_under_their_scene_and_the_rest_in_a_gallery():
    page = "# S1 - image prompts\n\n## 1. Arrival\nPrompt one.\n\n## 2. Stairs\nPrompt two.\n"

    result = b.with_images(page, ["1.png", "1 alt.png", "cover art.jpg"])

    assert result == (
        "# S1 - image prompts\n\n## 1. Arrival\nPrompt one.\n\n![](images/1.png)\n\n![](images/1%20alt.png)\n\n"
        "## 2. Stairs\nPrompt two.\n\n## Gallery\n\n![](images/cover%20art.jpg)\n"
    )


def test_with_images_matches_an_image_named_after_its_scene_title():
    page = "## 1. Arrival\nOne.\n\n## 2. The Armor Awakens\nTwo.\n"

    result = b.with_images(page, ["The Armor Awakens.jpeg"])

    assert result == "## 1. Arrival\nOne.\n\n## 2. The Armor Awakens\nTwo.\n\n![](images/The%20Armor%20Awakens.jpeg)\n"


def test_with_portraits_adds_each_portrait_under_the_heading_that_names_the_character():
    page = "# Characters\n\n## Aria\nVain bard.\n\n## Brunn (Red)\nStitched man.\n"

    result = b.with_portraits(page, CHARACTERS, {"Aria Vale": "assets/portraits/aria-vale.png"})

    assert result == (
        "# Characters\n\n## Aria\n\n![Aria Vale](assets/portraits/aria-vale.png){ align=right width=\"220\" }\n\n"
        "Vain bard.\n\n## Brunn (Red)\nStitched man.\n"
    )


def test_tidy_markdown_separates_lists_and_deepens_two_space_nesting():
    page = "## Aria\n- **Player:** Jordan\n- **Relationships:**\n  - **Kael:** just my type\n    - deeper\n"

    result = b.tidy_markdown(page)

    assert result == "## Aria\n\n- **Player:** Jordan\n- **Relationships:**\n    - **Kael:** just my type\n        - deeper\n"


def test_build_publishes_outputs_overview_portraits_and_images_but_not_work(tmp_path, monkeypatch):
    campaign = tmp_path / "Camp"
    make(campaign / "Session 1", "Session 1 - summary.md", "Session 1 - image prompts.md")
    make(campaign / "Session 1" / "work", "Session 1 (window 1).clean.md")
    (campaign / "Session 1" / "images").mkdir()
    (campaign / "Session 1" / "images" / "1.png").write_bytes(b"png")
    (campaign / "characters.md").write_text("# Characters\n\n## Aria\nVain.\n")
    (campaign / "aria portrait.png").write_bytes(b"png")
    chars = campaign / "characters.json"
    chars.write_text(__import__("json").dumps(CHARACTERS))
    wiki = tmp_path / "wiki"
    monkeypatch.setattr(b.subprocess, "run", lambda *a, **k: None)

    b.build(campaign, chars, "Test Campaign", wiki)

    docs = wiki / "docs"
    assert sorted(str(p.relative_to(docs)) for p in docs.rglob("*") if p.is_file()) == [
        "assets/portraits/aria-vale.png",
        "characters.md",
        "index.md",
        "sessions/session-1/image-prompts.md",
        "sessions/session-1/images/1.png",
        "sessions/session-1/summary.md",
    ]


def test_mkdocs_config_lists_newest_session_first():
    sessions = {"Session 1": {"summary": Path("a")}, "Session 2": {"summary": Path("b"), "transcript": Path("c")}}

    result = b.mkdocs_config("Camp", sessions, has_characters=True)

    assert result.index("'Session 2'") < result.index("'Session 1'")
    assert "  - Characters: characters.md" in result
    assert "      - 'Transcript': 'sessions/session-2/transcript.md'" in result


def test_mkdocs_config_adds_the_world_page_when_there_is_one():
    result = b.mkdocs_config("Camp", {"Session 1": {"summary": Path("a")}}, has_characters=True, has_world=True)

    assert "  - Characters: characters.md\n  - World: world.md\n" in result


def test_corrections_markdown_groups_rows_by_page():
    rows = [
        {"page": "/sessions/session-1/summary/", "text": "Sam took the oil,\nnot Jordan.", "email": "w@x.com", "created_at": "2026-11-24T10:00:00Z"},
        {"page": "/sessions/session-1/summary/", "text": "Pebble is pink.", "email": "s@x.com", "created_at": "2026-11-25T09:00:00Z"},
        {"page": "/characters/", "text": "Red is Brunn.", "email": "c@x.com", "created_at": "2026-11-25T11:00:00Z"},
    ]

    result = p.to_markdown(rows)

    assert result == (
        "# Corrections from the wiki\n\nFriends sent these from the wiki pages. Each names the page it is about.\n\n"
        "## /sessions/session-1/summary/\n\n"
        "- 2026-11-24, w@x.com: Sam took the oil, not Jordan.\n"
        "- 2026-11-25, s@x.com: Pebble is pink.\n\n"
        "## /characters/\n\n"
        "- 2026-11-25, c@x.com: Red is Brunn.\n"
    )


def test_with_entry_images_matches_file_names_to_headings_loosely():
    page = "## NPCs\n\n### Rolf\nTaskmaster.\n\n### The woman in the mirror\nA ghost.\n\n### Rose (Rosavalda Durst [sp?])\nA child.\n"
    urls = {b.entry_key("rolf"): "assets/world/rolf.jpeg", b.entry_key("woman_in_the_mirror"): "assets/world/w.jpeg"}

    result = b.with_entry_images(page, urls)

    assert result == (
        "## NPCs\n\n### Rolf\n\n![Rolf](assets/world/rolf.jpeg){ align=right width=\"260\" }\n\nTaskmaster.\n\n"
        "### The woman in the mirror\n\n![The woman in the mirror](assets/world/w.jpeg){ align=right width=\"260\" }\n\n"
        "A ghost.\n\n### Rose (Rosavalda Durst [sp?])\nA child.\n"
    )
