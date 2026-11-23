import json
import subprocess
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import transcribe as t
from transcribe import names, present_header, stamp, to_text

CHARACTERS = {
    "dm": "Pat",
    "characters": [{"player": "Jordan", "name": "Aria"}, {"player": "Sam", "name": "Kael"}],
}


def test_to_text_formats_one_line_per_segment():
    segments = [
        {"start": 3725.9, "speaker": "SPEAKER_00", "text": " The fog rolls in. "},
        {"start": 5.0, "text": "Who said that?"},
    ]
    expected = "[01:02:05] SPEAKER_00: The fog rolls in.\n[00:00:05] UNKNOWN: Who said that?\n"

    result = to_text(segments)

    assert result == expected


def test_to_text_of_no_segments_is_empty():
    result = to_text([])

    assert result == ""


def test_to_text_folds_line_breaks_inside_a_segment():
    segments = [{"start": 1.0, "speaker": "SPEAKER_01", "text": "Roll\ninitiative."}]

    result = to_text(segments)

    assert result == "[00:00:01] SPEAKER_01: Roll initiative.\n"


@pytest.mark.parametrize(
    "seconds, expected",
    [(59.9, "00:00:59"), (3599.9, "00:59:59"), (3600.0, "01:00:00")],
)
def test_stamp_truncates_to_whole_seconds(seconds, expected):
    result = stamp(seconds)

    assert result == expected


def test_names_lists_dm_then_each_player_and_character():
    characters = {"dm": "Pat", "characters": [{"player": "Jordan", "name": "Aria Vale"}]}

    result = names(characters)

    assert result == ["Pat", "Jordan", "Aria Vale"]


def test_present_header_lists_dm_and_present_players_only():
    result = present_header(CHARACTERS, ["Sam"])

    assert result == "# Present: Pat (DM), Sam (Kael)\n"


def test_present_header_follows_the_characters_file_order():
    result = present_header(CHARACTERS, ["Sam", "Jordan"])

    assert result == "# Present: Pat (DM), Jordan (Aria), Sam (Kael)\n"


@pytest.mark.parametrize(
    "characters",
    [
        {"characters": [{"player": "Jordan", "name": "Aria"}]},
        {"dm": "Pat", "characters": []},
        {"dm": "Pat", "characters": [{"name": "Aria"}]},
    ],
)
def test_check_characters_rejects_incomplete_files(characters):
    with pytest.raises(SystemExit):
        t.check_characters(characters)


def test_write_atomic_leaves_only_the_final_file(tmp_path):
    path = tmp_path / "a.transcript.txt"

    t.write_atomic(path, "hello\n")

    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.transcript.txt"]
    assert path.read_text() == "hello\n"


def test_load_audio_scales_16_bit_samples_to_floats(monkeypatch):
    pcm = np.array([16384, -32768], np.int16).tobytes()
    monkeypatch.setattr(t.subprocess, "run", lambda *a, **k: types.SimpleNamespace(stdout=pcm))

    result = t.load_audio(Path("x.m4a"))

    assert result.tolist() == [0.5, -1.0]


def test_ffmpeg_failure_exits_with_its_error_text(monkeypatch):
    def fail(*a, **k):
        raise subprocess.CalledProcessError(1, "ffmpeg", stderr=b"x.m4a: No such file")

    monkeypatch.setattr(t.subprocess, "run", fail)

    with pytest.raises(SystemExit) as exc:
        t.ffmpeg(["-i", "x.m4a"])

    assert exc.value.code == "ffmpeg failed: x.m4a: No such file"


def test_missing_ffmpeg_exits_with_install_hint(monkeypatch):
    def missing(*a, **k):
        raise FileNotFoundError("ffmpeg")

    monkeypatch.setattr(t.subprocess, "run", missing)

    with pytest.raises(SystemExit) as exc:
        t.ffmpeg(["-i", "x.m4a"])

    assert exc.value.code == "ffmpeg is not installed (brew install ffmpeg)"


def test_speaker_turns_reuses_the_saved_file(tmp_path):
    turns_path = tmp_path / "a.speakers.csv"
    turns_path.write_text("start,end,speaker\n0.0,1.5,SPEAKER_00\n")

    result = t.speaker_turns(tmp_path / "a.m4a", {"num_speakers": 2}, turns_path, tmp_path / "a.voices.json")

    assert result.to_dict("records") == [{"start": 0.0, "end": 1.5, "speaker": "SPEAKER_00"}]


def test_hear_sends_whisper_models_their_repo(monkeypatch):
    calls = []
    fake = types.SimpleNamespace(transcribe=lambda wav, **kw: calls.append((wav, kw["path_or_hf_repo"])) or {"segments": []})
    monkeypatch.setitem(sys.modules, "mlx_whisper", fake)

    t.hear("v2", Path("/tmp/leveled.wav"), "Names")

    assert calls == [("/tmp/leveled.wav", "mlx-community/whisper-large-v2-mlx")]


def test_hear_turns_parakeet_sentences_into_segments_with_words(monkeypatch):
    token = types.SimpleNamespace(text=" Hi", start=1.0, end=1.2)
    sentence = types.SimpleNamespace(start=1.0, end=1.2, text="Hi", tokens=[token])
    model = types.SimpleNamespace(transcribe=lambda wav, **kw: types.SimpleNamespace(sentences=[sentence]))
    fake = types.SimpleNamespace(
        from_pretrained=lambda repo: model, DecodingConfig=lambda **kw: None, SentenceConfig=lambda **kw: None
    )
    monkeypatch.setitem(sys.modules, "parakeet_mlx", fake)

    result = t.hear("parakeet", Path("/tmp/leveled.wav"), "Names")

    assert result == {
        "segments": [{"start": 1.0, "end": 1.2, "text": "Hi", "words": [{"word": " Hi", "start": 1.0, "end": 1.2}]}]
    }


def test_transcribe_separates_speakers_once_and_shares_the_turns(monkeypatch, tmp_path):
    turns = pd.DataFrame([{"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"}])
    separations, heard, assigned = [], [], []
    monkeypatch.setitem(sys.modules, "mlx", types.ModuleType("mlx"))
    monkeypatch.setitem(sys.modules, "mlx.core", types.SimpleNamespace(set_cache_limit=lambda n: None, clear_cache=lambda: None))
    monkeypatch.setitem(
        sys.modules,
        "whisperx",
        types.SimpleNamespace(assign_word_speakers=lambda tr, r: assigned.append(tr) or {"segments": [r["model"]]}),
    )
    monkeypatch.setattr(t, "speaker_turns", lambda audio, speakers, path, voices: separations.append(path) or turns)
    monkeypatch.setattr(t, "hear", lambda name, wav, prompt: heard.append((name, wav.name)) or {"model": name})
    monkeypatch.setattr(t, "ffmpeg", lambda args, stdin=None: b"")

    result = t.transcribe(
        np.zeros(10, np.float32), "Names", {"num_speakers": 2}, ["v2", "parakeet"], tmp_path / "a.speakers.csv", tmp_path / "a.voices.json"
    )

    assert separations == [tmp_path / "a.speakers.csv"]
    assert heard == [("v2", "leveled.wav"), ("parakeet", "leveled.wav")]
    assert all(a is turns for a in assigned) and len(assigned) == 2
    assert result == {"v2": ["v2"], "parakeet": ["parakeet"]}


@pytest.fixture
def run_main(monkeypatch, tmp_path):
    chars = tmp_path / "characters.json"
    chars.write_text(json.dumps(CHARACTERS))
    calls = []

    def fake_transcribe(audio, prompt, speakers, models, turns_path, voices_path):
        calls.append({"speakers": speakers, "models": models, "samples": len(audio)})
        return {m: [{"start": 0.0, "speaker": "SPEAKER_00", "text": "Hi"}] for m in models}

    monkeypatch.setattr(t, "transcribe", fake_transcribe)
    monkeypatch.setattr(t, "load_audio", lambda path: np.zeros(16000, np.float32))
    monkeypatch.setattr(t, "recording_start", lambda path: None)

    def run(*extra):
        t.main([str(tmp_path / "a.m4a"), "--characters", str(chars), "--out-dir", str(tmp_path / "work"), *extra])
        return calls

    return run


def test_main_rejects_unknown_players(run_main):
    with pytest.raises(SystemExit):
        run_main("--present", "Zed")


def test_main_counts_each_present_player_once_plus_the_dm_and_spare_slots(run_main):
    calls = run_main("--present", "Sam", "Sam", "Jordan")

    assert calls[0]["speakers"] == {"num_speakers": 6}


def test_main_caps_speakers_at_the_whole_table_plus_spare_slots_without_present(run_main):
    calls = run_main()

    assert calls[0]["speakers"] == {"max_speakers": 6}


def test_main_writes_the_present_header_only_when_given(run_main, tmp_path):
    run_main("--present", "Jordan")

    result = (tmp_path / "work" / "a.parakeet.transcript.txt").read_text()

    assert result == "# Present: Pat (DM), Jordan (Aria)\n[00:00:00] SPEAKER_00: Hi\n"


def test_main_skips_a_recording_whose_transcripts_all_exist(run_main, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    for m in t.DEFAULT_MODELS:
        (work / f"a.{m}.transcript.txt").write_text("kept\n")

    calls = run_main()

    assert calls == []


def test_main_adds_only_missing_models_when_turns_are_saved(run_main, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "a.v2.transcript.txt").write_text("kept\n")
    (work / "a.speakers.csv").write_text("start,end,speaker\n")

    calls = run_main("--models", "v2", "parakeet")

    assert [(c["speakers"], c["models"]) for c in calls] == [({"max_speakers": 6}, ["parakeet"])]
    assert (work / "a.v2.transcript.txt").read_text() == "kept\n"


def test_main_refuses_to_mix_new_transcripts_with_unsaved_turns(run_main, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "a.v2.transcript.txt").write_text("kept\n")

    calls = run_main("--models", "v2", "parakeet")

    assert calls == []


@pytest.mark.parametrize(
    "stem, expected",
    [
        ("Session 1 (part 2)", "Session 1"),
        ("Session 3", "Session 3"),
        ("Finale (part 10)", "Finale"),
        ("Session 3 (window 2)", "Session 3"),
        ("Session 1 (part 2) (window 1)", "Session 1"),
    ],
)
def test_session_name_drops_the_part_number(stem, expected):
    result = t.session_name(stem)

    assert result == expected


def test_match_voices_maps_a_returning_voice_to_its_session_label():
    known = {"VOICE_01": [1.0, 0.0], "VOICE_02": [0.0, 1.0]}
    embeddings = {"SPEAKER_00": [0.1, 0.99], "SPEAKER_01": [0.98, 0.05]}

    mapping, _ = t.match_voices(embeddings, {"SPEAKER_00": 10.0, "SPEAKER_01": 5.0}, known)

    assert mapping == {"SPEAKER_00": "VOICE_02", "SPEAKER_01": "VOICE_01"}


def test_match_voices_gives_an_unfamiliar_voice_a_new_label():
    known = {"VOICE_01": [1.0, 0.0, 0.0]}
    embeddings = {"SPEAKER_00": [0.0, 0.0, 1.0]}

    mapping, voices = t.match_voices(embeddings, {"SPEAKER_00": 3.0}, known)

    assert mapping == {"SPEAKER_00": "VOICE_02"}
    assert sorted(voices) == ["VOICE_01", "VOICE_02"]


def test_match_voices_folds_a_second_cluster_of_one_voice_into_it():
    embeddings = {"SPEAKER_00": [1.0, 0.0], "SPEAKER_01": [0.9, 0.3], "SPEAKER_02": [0.0, 1.0]}
    talk_time = {"SPEAKER_00": 900.0, "SPEAKER_01": 180.0, "SPEAKER_02": 400.0}

    mapping, _ = t.match_voices(embeddings, talk_time, {})

    assert mapping == {"SPEAKER_00": "VOICE_01", "SPEAKER_01": "VOICE_01", "SPEAKER_02": "VOICE_02"}


def test_match_voices_skips_a_cluster_without_a_usable_fingerprint():
    embeddings = {"SPEAKER_00": [float("nan"), 0.0]}

    mapping, voices = t.match_voices(embeddings, {"SPEAKER_00": 1.0}, {})

    assert (mapping, voices) == ({}, {})


START = datetime(2026, 11, 7, 14, 11, 50, tzinfo=timezone(timedelta(hours=-5)))


def test_stamp_with_a_start_time_gives_clock_time():
    result = stamp(2574.9, START)

    assert result == "14:54:44"


def test_to_text_with_a_start_time_stamps_clock_time():
    segments = [{"start": 10.0, "speaker": "VOICE_01", "text": "Welcome."}]

    result = to_text(segments, START)

    assert result == "[14:12:00] VOICE_01: Welcome.\n"


def test_recording_start_reads_the_creation_time_tag(monkeypatch):
    monkeypatch.setattr(t.subprocess, "run", lambda *a, **k: types.SimpleNamespace(stdout="2026-11-07T19:11:50.000000Z\n"))

    result = t.recording_start(Path("x.m4a"))

    assert result == datetime(2026, 11, 7, 19, 11, 50, tzinfo=timezone.utc)


def test_recording_start_is_none_without_a_tag(monkeypatch):
    monkeypatch.setattr(t.subprocess, "run", lambda *a, **k: types.SimpleNamespace(stdout=""))

    result = t.recording_start(Path("x.m4a"))

    assert result is None


def test_recorded_header_names_the_date_and_clock_time():
    result = t.recorded_header(START)

    assert result == "# Recorded: 2026-11-07, times are local clock time\n"



def seg(start, end):
    return {"start": float(start), "end": float(end), "speaker": "VOICE_01", "text": "x"}


def test_split_windows_leaves_a_session_under_67_minutes_whole():
    segments = [seg(0, 10), seg(3000, 3300)]

    result = t.split_windows(segments)

    assert result == [segments]


def test_split_windows_cuts_at_the_longest_pause_near_each_45_minute_mark():
    segments = [seg(0, 2600), seg(2610, 2690), seg(2750, 2800), seg(2805, 5500), seg(5520, 5580), seg(5700, 8200)]

    result = t.split_windows(segments)

    assert [[s["start"] for s in w] for w in result] == [[0, 2610], [2750, 2805], [5520, 5700]]


def test_split_windows_folds_a_short_last_stretch_into_the_previous_window():
    segments = [seg(0, 2600), seg(2750, 5500), seg(5700, 6000)]

    result = t.split_windows(segments)

    assert [[s["start"] for s in w] for w in result] == [[0], [2750, 5700]]


def test_main_writes_windows_for_a_long_recording(monkeypatch, run_main, tmp_path):
    long_segments = [seg(0, 2600), seg(2750, 5500), seg(5700, 8200)]
    monkeypatch.setattr(t, "transcribe", lambda *a: {"parakeet": long_segments})

    run_main()

    assert (tmp_path / "a - raw transcript.txt").read_text().count("VOICE_01") == 3
    assert sorted(p.name for p in (tmp_path / "work").glob("*.transcript.txt")) == [
        "a (window 1).parakeet.transcript.txt",
        "a (window 2).parakeet.transcript.txt",
        "a (window 3).parakeet.transcript.txt",
    ]


def test_main_counts_existing_windows_as_done(run_main, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "a (window 1).parakeet.transcript.txt").write_text("kept\n")

    calls = run_main()

    assert calls == []



def test_group_sessions_orders_parts_by_number():
    paths = [Path("S1 (part 10).m4a"), Path("S2.m4a"), Path("S1 (part 2).m4a")]

    result = t.group_sessions(paths)

    assert result == {"S1": [Path("S1 (part 2).m4a"), Path("S1 (part 10).m4a")], "S2": [Path("S2.m4a")]}


def test_join_pads_the_gap_between_recorded_start_times_with_silence():
    clips = [np.ones(16000, np.float32), np.ones(16000, np.float32)]
    starts = [START, START + timedelta(seconds=3)]

    result = t.join(clips, starts)

    assert (len(result), result[16000:48000].any(), result[48000:].all()) == (64000, False, True)


def test_join_without_start_times_places_parts_back_to_back():
    clips = [np.ones(5, np.float32), np.zeros(3, np.float32)]

    result = t.join(clips, [None, None])

    assert result.tolist() == [1, 1, 1, 1, 1, 0, 0, 0]


def test_main_joins_a_sessions_parts_into_one_transcription(monkeypatch, tmp_path):
    chars = tmp_path / "characters.json"
    chars.write_text(json.dumps(CHARACTERS))
    calls = []
    monkeypatch.setattr(t, "load_audio", lambda path: np.zeros(16000, np.float32))
    monkeypatch.setattr(t, "recording_start", lambda path: None)
    monkeypatch.setattr(t, "transcribe", lambda audio, *a: calls.append(len(audio)) or {"parakeet": []})
    parts = [str(tmp_path / f"S1 (part {n}).m4a") for n in (1, 2)]

    t.main([*parts, "--characters", str(chars), "--out-dir", str(tmp_path / "work")])

    assert calls == [32000]
