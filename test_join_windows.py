import pytest

import join_windows as j


def window(n, rows, paragraphs):
    table = "| Label | Person | Confidence | Evidence |\n|---|---|---|---|\n" + "\n".join(rows)
    return f"# S1 (window {n})\n\n## Speaker map\n{table}\n\n## Transcript\n\n" + "\n\n".join(paragraphs) + "\n"


W1 = window(
    1,
    ["| VOICE_01 | Pat (DM) | high | narrates |"],
    ["**[14:00:00] DM (Pat):** The fog rolls in.", "**[14:00:05] Aria (Jordan):** I sing"],
)


def test_join_keeps_each_voices_first_row_and_every_line_in_order():
    w2 = window(
        2,
        ["| VOICE_01 | Pat (DM) | high | voices Garrick |", "| VOICE_02 | Jordan (Aria) | high | sings |"],
        ["*[14:45:00] Sam (table talk): Chips?*"],
    )

    result = j.join("S1", [W1, w2])

    assert result == (
        "# S1\n\n## Speaker map\n| Label | Person | Confidence | Evidence |\n|---|---|---|---|\n"
        "| VOICE_01 | Pat (DM) | high | narrates |\n| VOICE_02 | Jordan (Aria) | high | sings |\n\n"
        "## Transcript\n\n**[14:00:00] DM (Pat):** The fog rolls in.\n\n**[14:00:05] Aria (Jordan):** I sing\n\n"
        "*[14:45:00] Sam (table talk): Chips?*\n"
    )


def test_join_rejoins_a_paragraph_split_by_a_window_cut():
    w2 = window(2, [], ["**[14:45:00] Aria (Jordan):** to the moon.", "**[14:45:09] DM (Pat):** Roll."])

    result = j.join("S1", [W1, w2])

    assert "**[14:00:05] Aria (Jordan):** I sing to the moon.\n\n**[14:45:09] DM (Pat):** Roll.\n" in result


def test_join_keeps_different_speakers_apart_at_a_cut():
    w2 = window(2, [], ["**[14:45:00] DM (Pat):** Roll."])

    result = j.join("S1", [W1, w2])

    assert "**[14:00:05] Aria (Jordan):** I sing\n\n**[14:45:00] DM (Pat):** Roll.\n" in result


def test_main_writes_windows_in_number_order_one_folder_up(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "S1 (window 10).clean.md").write_text(window(10, [], ["**[16:00:00] DM (Pat):** Late."]))
    (work / "S1 (window 2).clean.md").write_text(window(2, [], ["**[14:45:00] DM (Pat):** Early."]))

    j.main([str(work), "S1"])

    assert (tmp_path / "S1 - transcript.md").read_text().endswith("**[14:45:00] DM (Pat):** Early. Late.\n")


def test_main_will_not_overwrite_without_force(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "S1 (window 1).clean.md").write_text(W1)
    (tmp_path / "S1 - transcript.md").write_text("hand edited\n")

    with pytest.raises(SystemExit):
        j.main([str(work), "S1"])

    assert (tmp_path / "S1 - transcript.md").read_text() == "hand edited\n"
