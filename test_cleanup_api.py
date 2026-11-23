import contextlib
import types

import pytest

import cleanup_api as c


@pytest.mark.parametrize(
    "file_name, expected",
    [
        ("Session 1 (part 1).v2.transcript.txt", "Session 1 (part 1)"),
        ("Session 1 (part 1).parakeet.transcript.txt", "Session 1 (part 1)"),
        ("Session.01.transcript.txt", "Session.01"),
        ("a.transcript.txt", "a"),
    ],
)
def test_recording_name_strips_only_known_model_names(tmp_path, file_name, expected):
    result = c.recording_name(tmp_path / file_name)

    assert result == expected


class FakeClient:
    def __init__(self, calls, stop_reason="end_turn", text="# Clean\n"):
        message = types.SimpleNamespace(stop_reason=stop_reason, content=[types.SimpleNamespace(type="text", text=text)])
        stream = types.SimpleNamespace(get_final_message=lambda: message)
        self.beta = types.SimpleNamespace(
            messages=types.SimpleNamespace(stream=lambda **kw: calls.append(kw) or contextlib.nullcontext(stream))
        )


@pytest.fixture
def files(tmp_path):
    chars = tmp_path / "characters.json"
    chars.write_text("{}")
    v2 = tmp_path / "S1.v2.transcript.txt"
    v2.write_text("[00:00:00] SPEAKER_00: Hi\n")
    parakeet = tmp_path / "S1.parakeet.transcript.txt"
    parakeet.write_text("[00:00:00] SPEAKER_00: Hi\n")
    return types.SimpleNamespace(chars=chars, v2=v2, parakeet=parakeet, dir=tmp_path)


def install_client(monkeypatch, **kwargs):
    calls = []
    monkeypatch.setattr(c.anthropic, "Anthropic", lambda: FakeClient(calls, **kwargs))
    return calls


def test_main_writes_the_clean_transcript(monkeypatch, files):
    install_client(monkeypatch)

    c.main([str(files.v2), str(files.parakeet), "--context", str(files.chars)])

    assert (files.dir / "S1.clean.md").read_text() == "# Clean\n"


def test_main_rejects_transcripts_from_different_recordings(monkeypatch, files):
    calls = install_client(monkeypatch)
    other = files.dir / "S2.v2.transcript.txt"
    other.write_text("x\n")

    with pytest.raises(SystemExit):
        c.main([str(files.v2), str(other), "--context", str(files.chars)])

    assert calls == []


def test_main_will_not_overwrite_without_force(monkeypatch, files):
    calls = install_client(monkeypatch)
    (files.dir / "S1.clean.md").write_text("hand edited\n")

    with pytest.raises(SystemExit):
        c.main([str(files.v2), "--context", str(files.chars)])

    assert calls == []
    assert (files.dir / "S1.clean.md").read_text() == "hand edited\n"


def test_main_saves_partial_output_when_stopped_early(monkeypatch, files):
    install_client(monkeypatch, stop_reason="max_tokens", text="# Half\n")

    with pytest.raises(SystemExit):
        c.main([str(files.v2), "--context", str(files.chars)])

    assert (files.dir / "S1.clean.md.partial").read_text() == "# Half\n"
    assert not (files.dir / "S1.clean.md").exists()


def test_main_refuses_requests_over_the_size_limit(monkeypatch, files):
    calls = install_client(monkeypatch)
    monkeypatch.setattr(c, "MAX_REQUEST_BYTES", 10)

    with pytest.raises(SystemExit):
        c.main([str(files.v2), "--context", str(files.chars)])

    assert calls == []
