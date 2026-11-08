"""Speech to text with faster-whisper, kept loaded between clips so each one only pays for listening, not for starting up.
Returns the same shape the whisper command line writes as json, so the rest of the bench does not care which ran."""
import threading

MODEL_NAME = "small"
_model = {"value": None, "failed": False}
_lock = threading.Lock()


def available():
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return not _model["failed"]


def _load():
    if _model["value"] is None:
        from faster_whisper import WhisperModel
        _model["value"] = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8")
    return _model["value"]


def transcribe(wav, task, timed):
    """{"language", "text", "segments": [{"text", "start", "end", "words": [{"word", "start", "end"}]}]} for a wav file."""
    with _lock:
        try:
            model = _load()
        except Exception:
            _model["failed"] = True
            raise
        segments, info = model.transcribe(str(wav), task=task, word_timestamps=timed, condition_on_previous_text=False, vad_filter=True)
        out = [{"text": seg.text, "start": seg.start, "end": seg.end, "words": [{"word": w.word, "start": w.start, "end": w.end} for w in (seg.words or [])]} for seg in segments]
    return {"language": info.language, "text": "".join(seg["text"] for seg in out).strip(), "segments": out}
