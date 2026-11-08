"""Speech to text with mlx-whisper, which runs Whisper on the Mac's GPU. Same return shape as fast_speech, so the bench does not care which ran.
mlx-whisper has no voice-activity filter, so segments Whisper itself marks as silence or looping are dropped here."""
import threading

REPO = "mlx-community/whisper-small-mlx"
NO_SPEECH_PROB, LOW_LOGPROB, LOOPING_RATIO = 0.6, -1.0, 2.4
_state = {"failed": False}
_lock = threading.Lock()


def available():
    try:
        import mlx_whisper  # noqa: F401
    except ImportError:
        return False
    return not _state["failed"]


def keep(seg):
    """Whether a segment is speech: not Whisper's own silence guess and not a repeating loop."""
    if seg.get("compression_ratio", 0) > LOOPING_RATIO:
        return False
    return not (seg.get("no_speech_prob", 0) > NO_SPEECH_PROB and seg.get("avg_logprob", 0) < LOW_LOGPROB)


def transcribe(wav, task, timed):
    """{"language", "text", "segments": [{"text", "start", "end", "words": [{"word", "start", "end"}]}]} for a wav file."""
    import mlx_whisper
    with _lock:
        try:
            raw = mlx_whisper.transcribe(str(wav), path_or_hf_repo=REPO, task=task, word_timestamps=timed, condition_on_previous_text=False)
        except Exception:
            _state["failed"] = True
            raise
    out = [{"text": seg["text"], "start": float(seg["start"]), "end": float(seg["end"]),
            "words": [{"word": w["word"], "start": float(w["start"]), "end": float(w["end"])} for w in seg.get("words", [])]}
           for seg in raw["segments"] if keep(seg)]
    return {"language": raw.get("language"), "text": "".join(seg["text"] for seg in out).strip(), "segments": out}
