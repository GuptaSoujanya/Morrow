"""The voice (edge-tts/Kokoro) and the mix (ffmpeg) of a reel, with the speech engines replaced by a tone."""
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VOICE = ROOT / "studio" / "reels" / "voice.py"
MIX = ROOT / "studio" / "reels" / "mix.py"

pytestmark = pytest.mark.skipif(not (VOICE.exists() and MIX.exists()), reason="the private studio folder is not checked out")
needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg is not installed")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def voice():
    return _load("studio_reels_voice_test", VOICE)


@pytest.fixture
def mix(tmp_path, monkeypatch):
    module = _load("studio_reels_mix_test", MIX)
    monkeypatch.setattr(module, "ASSETS", tmp_path / "assets")
    monkeypatch.setattr(module, "BUNDLED_SFX", tmp_path / "no-bundled-sfx")
    return module


def _tone(path: Path, seconds: float, freq: int = 440) -> Path:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}",
                    "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(path)], check=True)
    return path


# --- voice ---------------------------------------------------------------------------------------

def test_pace_flags_speech_a_first_time_listener_cannot_follow(voice):
    easy = voice.pace(60, 30)
    assert easy["wps"] == 2.0 and easy["wpm"] == 120 and easy["ok"]
    rushed = voice.pace(61, 20)
    assert rushed["wps"] > voice.MAX_WPS and not rushed["ok"]
    assert not voice.pace(10, 0)["ok"]
    assert voice.word_budget(30) == 66


def test_default_voice_follows_language_engine_and_wish(voice):
    assert voice.default_voice("English", "edge") == "en-US-AndrewMultilingualNeural"
    assert voice.default_voice("Hindi", "edge").startswith("hi-IN-")
    assert voice.default_voice("Hinglish", "edge").startswith("en-IN-")
    assert voice.default_voice("English", "edge", "en-GB-RyanNeural") == "en-GB-RyanNeural"
    assert voice.default_voice("Klingon", "kokoro") == voice.VOICES["English"]["kokoro"][0]
    hindi = voice.voices("Hindi")
    assert hindi and all(v["language"] == "Hindi" for v in hindi)
    assert {v["engine"] for v in voice.voices()} == set(voice.ENGINES)


@needs_ffmpeg
def test_make_joins_the_lines_with_pauses_and_writes_timings(voice, tmp_path, monkeypatch):
    monkeypatch.setattr(voice, "edge_available", lambda: True)
    spoken = []

    def fake_edge(text, chosen, rate, out_wav):
        spoken.append((text, chosen, rate))
        _tone(out_wav, 1.0)
        words = text.split()
        step = 1.0 / len(words)
        return [{"w": w, "start": round(i * step, 3), "end": round((i + 1) * step, 3)} for i, w in enumerate(words)]
    monkeypatch.setattr(voice, "synth_edge", fake_edge)

    record = voice.make(tmp_path, ["  Stop  doing this ", "Do this instead", ""], "English", rate="+5%")
    assert [s[0] for s in spoken] == ["Stop doing this", "Do this instead"]
    assert spoken[0][1] == "en-US-AndrewMultilingualNeural" and spoken[0][2] == "+5%"
    assert (tmp_path / "voice.wav").is_file()
    saved = json.loads((tmp_path / "words.json").read_text())
    assert saved["engine"] == "edge" and saved["pace"]["words"] == 6 and not saved["estimated_words"]
    assert [l["text"] for l in saved["lines"]] == ["Stop doing this", "Do this instead"]
    assert saved["lines"][0]["start"] == voice.LEAD_IN_S
    gap = saved["lines"][1]["start"] - saved["lines"][0]["end"]
    assert abs(gap - voice.LINE_GAP_S) < 0.05
    assert [w["w"] for w in saved["words"]] == ["Stop", "doing", "this", "Do", "this", "instead"]
    assert saved["words"][3]["line"] == 1 and saved["words"][3]["start"] >= saved["lines"][1]["start"]
    expected = voice.LEAD_IN_S + 2.0 + voice.LINE_GAP_S
    assert abs(saved["duration_s"] - expected) < 0.4
    assert json.loads((tmp_path / "script.json").read_text())["lines"] == ["Stop doing this", "Do this instead"]
    assert voice.load(tmp_path)["voice"] == saved["voice"]


@needs_ffmpeg
def test_a_dropped_edge_line_is_tried_again_before_any_fallback(voice, tmp_path, monkeypatch):
    monkeypatch.setattr(voice, "edge_available", lambda: True)
    monkeypatch.setattr(voice.time, "sleep", lambda s: None)
    attempts = []

    def flaky_edge(text, chosen, rate, out_wav):
        attempts.append(text)
        if len(attempts) < 3:
            raise voice.VoiceError("edge-tts failed: No audio was received.")
        _tone(out_wav, 0.5)
        return [{"w": w, "start": i * 0.1, "end": i * 0.1 + 0.1} for i, w in enumerate(text.split())]
    monkeypatch.setattr(voice, "synth_edge", flaky_edge)
    monkeypatch.setattr(voice, "synth_kokoro", lambda *a, **k: pytest.fail("kokoro must not be used while edge can recover"))

    record = voice.make(tmp_path, ["One line only"], "English")
    assert record["engine"] == "edge" and len(attempts) == 3


@needs_ffmpeg
def test_make_falls_back_to_kokoro_when_edge_fails(voice, tmp_path, monkeypatch):
    monkeypatch.setattr(voice, "edge_available", lambda: True)
    monkeypatch.setattr(voice.time, "sleep", lambda s: None)

    def broken_edge(text, chosen, rate, out_wav):
        raise voice.VoiceError("no network")
    monkeypatch.setattr(voice, "synth_edge", broken_edge)
    used = []

    def fake_kokoro(text, chosen, speed, lang, out_wav):
        used.append((chosen, lang))
        _tone(out_wav, 0.8)
        return [{"w": w, "start": i * 0.2, "end": i * 0.2 + 0.2} for i, w in enumerate(text.split())]
    monkeypatch.setattr(voice, "synth_kokoro", fake_kokoro)

    record = voice.make(tmp_path, ["Namaste doston"], "Hindi")
    assert record["engine"] == "kokoro" and record["estimated_words"]
    assert used[0] == (voice.VOICES["Hindi"]["kokoro"][0], "hi")
    with pytest.raises(voice.VoiceError):
        voice.make(tmp_path, ["again"], "English", allow_fallback=False)


def test_make_refuses_an_empty_script_or_unknown_engine(voice, tmp_path):
    with pytest.raises(voice.VoiceError):
        voice.make(tmp_path, ["", "   "])
    with pytest.raises(voice.VoiceError):
        voice.make(tmp_path, ["hello"], engine="siri")


def test_srt_groups_words_with_timestamps(voice):
    record = {"words": [{"w": "Stop", "start": 0.25, "end": 0.5}, {"w": "doing", "start": 0.5, "end": 0.8},
                        {"w": "this", "start": 0.8, "end": 1.1}, {"w": "now", "start": 1.6, "end": 61.9}]}
    text = voice.srt(record, group=3)
    assert text.startswith("1\n00:00:00,250 --> 00:00:01,100\nStop doing this\n")
    assert "2\n00:00:01,600 --> 00:01:01,900\nnow\n" in text


# --- mix -----------------------------------------------------------------------------------------

def test_loudness_problems_name_what_is_off(mix):
    assert mix.loudness_problems({"has_audio": False}) == ["no measurable audio"]
    assert mix.loudness_problems({"has_audio": True, "lufs": -14.4, "true_peak_db": -1.2}) == []
    quiet = mix.loudness_problems({"has_audio": True, "lufs": -19.1, "true_peak_db": -1.2})
    assert len(quiet) == 1 and "-19.1 LUFS" in quiet[0] and "target -14" in quiet[0]
    hot = mix.loudness_problems({"has_audio": True, "lufs": -14.0, "true_peak_db": 0.2})
    assert len(hot) == 1 and "true peak" in hot[0]


def test_sfx_cues_are_read_capped_and_resolved(mix, tmp_path):
    folder = tmp_path / "day"
    folder.mkdir()
    assert mix.cues_for(folder) == []
    (folder / "sfx.json").write_text(json.dumps({"cues": [
        {"at": 1.5, "name": "pop", "gain_db": -6}, {"at": 3, "name": "Whoosh Short", "gain_db": 4},
        {"at": -1, "name": "pop"}, {"at": "x", "name": "pop"}, {"name": "pop"}, "junk", {"at": 2, "name": ""},
        {"at": 4, "name": "ping", "gain_db": "loud"}]}))
    cues = mix.cues_for(folder)
    assert [c["name"] for c in cues] == ["pop", "Whoosh Short", "ping"]
    assert cues[0]["gain_db"] == -6 and cues[1]["gain_db"] == mix.SFX_MAX_DB and cues[2]["gain_db"] == -8.0
    (folder / "sfx.json").write_text(json.dumps([{"at": i, "name": "pop"} for i in range(12)]))
    assert len(mix.cues_for(folder)) == mix.MAX_CUES
    (folder / "sfx.json").write_text("{not json")
    assert mix.cues_for(folder) == []

    library = {"pop": Path("pop.mp3"), "whoosh-short": Path("ws.mp3"), "whoosh-cinematic": Path("wc.mp3")}
    assert mix.resolve_sfx("pop", library) == Path("pop.mp3")
    assert mix.resolve_sfx("Whoosh Short", library) == Path("ws.mp3")
    assert mix.resolve_sfx("whoosh", library) in (Path("ws.mp3"), Path("wc.mp3"))
    assert mix.resolve_sfx("explosion", library) is None


def test_music_comes_from_the_folder_first_then_the_shared_assets(mix, tmp_path):
    folder = tmp_path / "day-01"
    folder.mkdir()
    assert mix.music_for(folder) is None
    (mix.ASSETS / "music").mkdir(parents=True)
    (mix.ASSETS / "music" / "calm.mp3").write_bytes(b"id3")
    assert mix.music_for(folder) == mix.ASSETS / "music" / "calm.mp3"
    (folder / "music.wav").write_bytes(b"RIFF")
    assert mix.music_for(folder) == folder / "music.wav"


@needs_ffmpeg
def test_build_lands_on_the_loudness_target_and_places_cues(mix, tmp_path):
    folder = tmp_path / "day-01"
    folder.mkdir()
    _tone(folder / "voice.wav", 3.0, 220)
    (mix.ASSETS / "sfx").mkdir(parents=True)
    _tone(mix.ASSETS / "sfx" / "pop.wav", 0.2, 1200)
    (folder / "sfx.json").write_text(json.dumps([{"at": 0.5, "name": "pop", "gain_db": -8}, {"at": 1.0, "name": "nothing-here"}]))

    result = mix.build(folder, duration=4.0)
    assert (folder / "reel-audio.wav").is_file()
    assert [c["name"] for c in result["sfx"]] == ["pop"] and result["sfx_skipped"] == ["nothing-here"]
    assert result["music"] == "generated pad"
    assert abs(result["duration_s"] - 4.0) < 0.3
    measured = mix.measure(folder / "reel-audio.wav")
    assert measured["has_audio"] and abs(measured["lufs"] - mix.TARGET_LUFS) <= mix.LUFS_TOLERANCE
    assert measured["true_peak_db"] <= mix.TRUE_PEAK + 0.3
    assert mix.loudness_problems(measured) == []
    saved = json.loads((folder / "mix.json").read_text())
    assert saved["target_lufs"] == mix.TARGET_LUFS and saved["sfx"][0]["at"] == 0.5


@needs_ffmpeg
def test_build_with_real_music_numbers_the_cue_inputs_right(mix, tmp_path):
    # music arrives as "-stream_loop -1 -i file", so counting pairs shifts every later cue by one input
    folder = tmp_path / "day-01"
    folder.mkdir()
    _tone(folder / "voice.wav", 3.0, 220)
    _tone(folder / "music.wav", 3.0, 110)
    (mix.ASSETS / "sfx").mkdir(parents=True)
    for name, freq in (("pop", 1200), ("ping", 1600), ("whoosh", 400)):
        _tone(mix.ASSETS / "sfx" / f"{name}.wav", 0.2, freq)
    (folder / "sfx.json").write_text(json.dumps([{"at": 0.3, "name": "pop"}, {"at": 1.2, "name": "ping"},
                                                 {"at": 2.1, "name": "whoosh"}]))

    result = mix.build(folder, duration=4.0)
    assert [c["name"] for c in result["sfx"]] == ["pop", "ping", "whoosh"]
    assert result["music"] == str(folder / "music.wav")
    measured = mix.measure(folder / "reel-audio.wav")
    assert measured["has_audio"] and abs(measured["lufs"] - mix.TARGET_LUFS) <= mix.LUFS_TOLERANCE


def test_build_needs_a_voice(mix, tmp_path):
    with pytest.raises(mix.MixError):
        mix.build(tmp_path)
