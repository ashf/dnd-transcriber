"""Step 1: turn a D&D session's recordings into speaker-labeled base transcripts.

The recordings of one session ("Session 1 (part 1).m4a", "Session 1 (part 2).m4a", ...) are joined in part
order into one recording, with silence for any gap between their recorded start times. Speakers are separated
once over the whole session, so VOICE_NN is the same person everywhere in it. The transcript is written as
windows of about 45 minutes, cut at pauses, into --out-dir (default: a work folder next to the audio):
    <session> (window N).<model>.transcript.txt
one line per segment, stamped with local clock time when the recordings carry their start time:
    [14:12:34] VOICE_03: I want to check the door for traps.
The whole session's uncleaned transcript is also kept in the session folder as "<session> - raw transcript.txt".
Speaker turns are saved in <session>.speakers.csv and reused, so models added later get the same labels.
Existing transcripts are never overwritten; delete a session's transcripts and .speakers.csv to regenerate them.
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

# Lifts quiet voices far from the mic and cuts hum. Speech models only: evened levels hurt speaker separation.
LEVEL_FILTER = "highpass=f=80,dynaudnorm=f=150:g=15:p=0.9"

MODELS = {
    "v2": ("whisper", "mlx-community/whisper-large-v2-mlx"),
    "parakeet": ("parakeet", "mlx-community/parakeet-tdt-0.6b-v2"),
    "turbo": ("whisper", "mlx-community/whisper-large-v3-turbo"),
}
DEFAULT_MODELS = ["parakeet"]
# Across Session 1's parts the same person scored 0.84 to 0.97 and different people at most 0.68.
VOICE_MATCH = 0.75
SPARE_VOICES = 3
# A model writing a whole session in one cleanup pass starts condensing, so sessions are cut into windows.
WINDOW = 45 * 60
SAMPLE_RATE = 16000
WINDOW_SLACK = 3 * 60


def stamp(seconds: float, start: datetime | None = None) -> str:
    if start:
        return (start + timedelta(seconds=int(seconds))).strftime("%H:%M:%S")
    t = int(seconds)
    return f"{t // 3600:02}:{t % 3600 // 60:02}:{t % 60:02}"


def to_text(segments: list[dict], start: datetime | None = None) -> str:
    return "".join(
        f"[{stamp(s['start'], start)}] {s.get('speaker', 'UNKNOWN')}: {' '.join(s['text'].split())}\n" for s in segments
    )


def recording_start(path: Path) -> datetime | None:
    """Local time the recording began, from the file's creation_time tag; None when the file has none."""
    try:
        tag = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format_tags=creation_time", "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True,
            text=True,
        ).stdout.strip()
        return datetime.fromisoformat(tag.replace("Z", "+00:00")).astimezone()
    except (FileNotFoundError, ValueError):
        return None


def recorded_header(start: datetime | None) -> str:
    return f"# Recorded: {start:%Y-%m-%d}, times are local clock time\n" if start else ""


def names(characters: dict) -> list[str]:
    return [characters["dm"], *(n for c in characters["characters"] for n in (c["player"], c["name"]))]


def present_header(characters: dict, present: list[str]) -> str:
    who = [f"{c['player']} ({c['name']})" for c in characters["characters"] if c["player"] in present]
    return f"# Present: {characters['dm']} (DM), " + ", ".join(who) + "\n"


def check_characters(characters: dict) -> None:
    if "dm" not in characters or not characters.get("characters"):
        sys.exit("Characters file needs a 'dm' name and a non-empty 'characters' list")
    for i, c in enumerate(characters["characters"]):
        if "player" not in c or "name" not in c:
            sys.exit(f"Character {i} in the characters file needs both 'player' and 'name'")


def write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)


def ffmpeg(args: list[str], stdin: bytes | None = None) -> bytes:
    try:
        cmd = ["ffmpeg", "-v", "error", *args] if stdin is not None else ["ffmpeg", "-nostdin", "-v", "error", *args]
        return subprocess.run(cmd, input=stdin, capture_output=True, check=True).stdout
    except FileNotFoundError:
        sys.exit("ffmpeg is not installed (brew install ffmpeg)")
    except subprocess.CalledProcessError as e:
        sys.exit(f"ffmpeg failed: {e.stderr.decode(errors='replace').strip()}")


def load_audio(path: Path) -> np.ndarray:
    pcm = ffmpeg(["-i", str(path), "-f", "s16le", "-ac", "1", "-ar", "16000", "-"])
    return np.frombuffer(pcm, np.int16).astype(np.float32) / 32768.0


def session_name(stem: str) -> str:
    m = re.match(r"^(.*?)(?:\s*\((?:part|window) \d+\))+$", stem)
    return m[1] if m else stem


def split_windows(segments: list[dict]) -> list[list[dict]]:
    """Cut a long recording into windows of about WINDOW seconds, each cut at the longest pause near the mark."""
    end = lambda s: s.get("end", s["start"])
    if not segments:
        return [segments]
    cuts, target = [], WINDOW
    while end(segments[-1]) - target > WINDOW / 2:
        after = cuts[-1] if cuts else 0
        near = [i for i in range(max(after, 1), len(segments)) if abs(segments[i]["start"] - target) <= WINDOW_SLACK]
        if near:
            cut = max(near, key=lambda i: segments[i]["start"] - end(segments[i - 1]))
        else:
            cut = next((i for i in range(max(after, 1), len(segments)) if segments[i]["start"] >= target), None)
        if cut is None:
            break
        cuts.append(cut)
        target += WINDOW
    bounds = [0, *cuts, len(segments)]
    return [segments[a:b] for a, b in zip(bounds, bounds[1:])]


def existing_transcripts(out_dir: Path, stem: str, model: str) -> list[Path]:
    whole = out_dir / f"{stem}.{model}.transcript.txt"
    windows = sorted(out_dir.glob(f"{glob.escape(stem)} (window *).{model}.transcript.txt"))
    return [whole] if whole.exists() else windows


def window_files(out_dir: Path, stem: str, model: str, windows: list[list[dict]]) -> list[tuple[Path, list[dict]]]:
    if len(windows) == 1:
        return [(out_dir / f"{stem}.{model}.transcript.txt", windows[0])]
    return [(out_dir / f"{stem} (window {k}).{model}.transcript.txt", w) for k, w in enumerate(windows, 1)]


def match_voices(embeddings: dict, talk_time: dict, voices: dict) -> tuple[dict, dict]:
    """Map each cluster to a session voice, biggest talker first. Several clusters may map to one voice
    (the DM's NPC voices); a cluster unlike every known voice becomes a new one."""
    voices = {name: np.asarray(v, float) for name, v in voices.items()}
    mapping = {}
    for label in sorted(embeddings, key=lambda lbl: -talk_time.get(lbl, 0.0)):
        v = np.asarray(embeddings[label], float)
        if not np.isfinite(v).all() or not np.linalg.norm(v):
            continue
        v = v / np.linalg.norm(v)
        best = max(voices, key=lambda n: float(v @ voices[n]), default=None)
        if best is not None and float(v @ voices[best]) >= VOICE_MATCH:
            mapping[label] = best
        else:
            mapping[label] = f"VOICE_{len(voices) + 1:02}"
            voices[mapping[label]] = v
    return mapping, voices


def part_number(path: Path) -> int:
    m = re.search(r"\(part (\d+)\)", path.stem)
    return int(m[1]) if m else 0


def group_sessions(paths: list[Path]) -> dict[str, list[Path]]:
    sessions: dict[str, list[Path]] = {}
    for p in sorted(paths, key=part_number):
        sessions.setdefault(session_name(p.stem), []).append(p)
    return sessions


def join(clips: list[np.ndarray], starts: list[datetime | None]) -> np.ndarray:
    """Join a session's parts in order, padding with silence up to each part's recorded start time."""
    pieces, length = [], 0
    for clip, start in zip(clips, starts):
        if all(starts) and pieces:
            gap = round((start - starts[0]).total_seconds() * SAMPLE_RATE) - length
            if gap > 0:
                pieces.append(np.zeros(gap, np.float32))
                length += gap
        pieces.append(clip)
        length += len(clip)
    return np.concatenate(pieces) if pieces else np.zeros(0, np.float32)


def speaker_turns(audio: np.ndarray, speakers: dict, turns_path: Path, voices_path: Path):
    import pandas as pd

    if turns_path.exists():
        print(f"Reusing speaker turns from {turns_path.name}", file=sys.stderr)
        return pd.read_csv(turns_path)
    import torch
    from whisperx.diarize import DiarizationPipeline

    # token=None falls back to the token saved by `hf auth login`
    diarize = DiarizationPipeline(token=os.environ.get("HF_TOKEN"), device="mps")
    turns, embeddings = diarize(audio, return_embeddings=True, **speakers)
    del diarize
    torch.mps.empty_cache()
    turns = turns[["start", "end", "speaker"]]
    talk_time = turns.assign(d=turns.end - turns.start).groupby("speaker").d.sum().to_dict()
    known = json.loads(voices_path.read_text()) if voices_path.exists() else {}
    mapping, voices = match_voices(embeddings or {}, talk_time, known)
    turns = turns.assign(speaker=turns.speaker.map(lambda s: mapping.get(s, s)))
    write_atomic(voices_path, json.dumps({n: v.tolist() for n, v in voices.items()}))
    write_atomic(turns_path, turns.to_csv(index=False))
    return turns


def hear(model: str, wav: Path, prompt: str) -> dict:
    kind, repo = MODELS[model]
    if kind == "whisper":
        import mlx_whisper

        return mlx_whisper.transcribe(
            str(wav),
            language="en",
            path_or_hf_repo=repo,
            initial_prompt=prompt,
            word_timestamps=True,
            condition_on_previous_text=False,  # otherwise Whisper drifts into unpunctuated fragments
            hallucination_silence_threshold=2.0,  # skip text Whisper invents over long silences
        )
    import parakeet_mlx
    from parakeet_mlx import DecodingConfig, SentenceConfig

    result = parakeet_mlx.from_pretrained(repo).transcribe(
        str(wav),
        chunk_duration=120,
        decoding_config=DecodingConfig(sentence=SentenceConfig(silence_gap=1.0, max_duration=20)),
    )
    return {
        "segments": [
            {
                "start": s.start,
                "end": s.end,
                "text": s.text,
                "words": [{"word": t.text, "start": t.start, "end": t.end} for t in s.tokens],
            }
            for s in result.sentences
        ]
    }


def transcribe(
    audio: np.ndarray, prompt: str, speakers: dict, models: list[str], turns_path: Path, voices_path: Path
) -> dict[str, list[dict]]:
    import mlx.core as mx
    import whisperx

    # Both GPU libraries keep freed memory cached; uncapped, an hour of audio needs over 25 GB.
    mx.set_cache_limit(2**30)
    turns = speaker_turns(audio, speakers, turns_path, voices_path)
    out = {}
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "leveled.wav"
        pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes()
        ffmpeg(["-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", "1", "-i", "-", "-af", LEVEL_FILTER, str(wav)], stdin=pcm)
        for name in models:
            out[name] = whisperx.assign_word_speakers(turns, hear(name, wav, prompt))["segments"]
            mx.clear_cache()
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audio", type=Path, nargs="+")
    ap.add_argument("--characters", type=Path, required=True, help="JSON with 'dm' and characters[].player/.name")
    ap.add_argument("--present", nargs="+", metavar="PLAYER", help="players at the table (the DM is implied)")
    ap.add_argument("--models", nargs="+", choices=MODELS, default=DEFAULT_MODELS)
    ap.add_argument("--out-dir", type=Path, help="where transcripts go (default: a work folder next to the audio)")
    args = ap.parse_args(argv)

    characters = json.loads(args.characters.read_text())
    check_characters(characters)
    # Biases name spelling, but only in Whisper's first 30-second window: prompts reset per window.
    prompt = "A Dungeons & Dragons session. Names: " + ", ".join(names(characters)) + "."
    players = {c["player"] for c in characters["characters"]}
    present = sorted(set(args.present or []))
    if unknown := set(present) - players:
        sys.exit(f"Unknown players {sorted(unknown)}; expected some of {sorted(players)}")
    # Spare slots beyond the people at the table: the DM's NPC voices form clusters of their own (three of them
    # in Session 2), and without room two similar voices get merged for good. match_voices folds extra clusters
    # of one voice back together, so splitting a voice is harmless and merging two is not.
    speakers = {"num_speakers": len(present) + 1 + SPARE_VOICES} if present else {"max_speakers": len(players) + 1 + SPARE_VOICES}
    header = present_header(characters, present) if present else ""

    for session, parts in group_sessions(args.audio).items():
        out_dir = args.out_dir or parts[0].parent / "work"
        out_dir.mkdir(parents=True, exist_ok=True)
        turns_path = out_dir / f"{session}.speakers.csv"
        voices_path = out_dir / f"{session}.voices.json"
        missing = [m for m in args.models if not existing_transcripts(out_dir, session, m)]
        if not missing:
            print(f"Skipping {session}: transcripts exist", file=sys.stderr)
            continue
        if len(missing) < len(args.models) and not turns_path.exists():
            print(f"Skipping {session}: it has transcripts but no {turns_path.name}, so new ones would get "
                  "different speaker labels. Delete its transcripts to regenerate them all.", file=sys.stderr)
            continue
        print(f"Transcribing {session} ({len(parts)} recordings) with {', '.join(missing)}", file=sys.stderr)
        starts = [recording_start(p) for p in parts]
        audio = join([load_audio(p) for p in parts], starts)
        for name, segments in transcribe(audio, prompt, speakers, missing, turns_path, voices_path).items():
            for path, window in window_files(out_dir, session, name, split_windows(segments)):
                write_atomic(path, header + recorded_header(starts[0]) + to_text(window, starts[0]))
                print(f"Wrote {path}", file=sys.stderr)
            raw = out_dir.parent / (f"{session} - raw transcript.txt" if len(missing) == 1 else f"{session} - raw transcript ({name}).txt")
            write_atomic(raw, header + recorded_header(starts[0]) + to_text(segments, starts[0]))
            print(f"Wrote {raw}", file=sys.stderr)

if __name__ == "__main__":
    main()
