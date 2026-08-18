"""Supertonic, loaded once in this process, plus the job queue that feeds it.

Everything here is synchronous and thread-bound on purpose. ONNX Runtime
already spreads one inference across cores, so a second concurrent job would
mostly fight the first for CPU. One worker thread, one job at a time.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from .config import Settings, get_settings
from .segmenter import (
    BLOCK,
    BY_PARAGRAPH,
    BY_SENTENCE,
    CHUNK_MAX_CHARS,
    LINE,
    SENTENCE,
    group_spans,
    max_chars_for,
    segment_spans,
)

log = logging.getLogger("oneread.tts")

VOICES: list[dict[str, str]] = [
    {"id": "F1", "label": "Faye", "gender": "female"},
    {"id": "F2", "label": "Iris", "gender": "female"},
    {"id": "F3", "label": "June", "gender": "female"},
    {"id": "F4", "label": "Nora", "gender": "female"},
    {"id": "F5", "label": "Sage", "gender": "female"},
    {"id": "M1", "label": "Abel", "gender": "male"},
    {"id": "M2", "label": "Cole", "gender": "male"},
    {"id": "M3", "label": "Emil", "gender": "male"},
    {"id": "M4", "label": "Otto", "gender": "male"},
    {"id": "M5", "label": "Reid", "gender": "male"},
]
VOICE_IDS = {voice["id"] for voice in VOICES}

MIN_SPEED = 0.7
MAX_SPEED = 2.0

_SPACES = re.compile(r"[ \t]+")


_TRIM_FRAME_S = 0.010  # granularity of the silence hunt
_TRIM_FLOOR = 4e-4  # absolute quiet, so a soft voice isn't shredded
_TRIM_RELATIVE = 0.01  # ...and 40 dB under this clip's own peak
_TRIM_HEAD_S = 0.010  # kept before the first sound
_TRIM_TAIL_S = 0.040  # kept after the last, room for a fricative to die


def trim_silence(wav: np.ndarray, sample_rate: int) -> np.ndarray:
    """Cut a clip's lead-in and tail so the gap we add is the gap heard.

    The model pads its own silence onto every utterance: the latent is rounded
    up to a whole chunk, and the duration predictor writes a pause of its own
    for the full stop. Left in, that stacks on top of the silence between
    pieces and a paragraph reads like a list. Taken off, the pause is exactly
    what `pacing` asked for.
    """
    frame = max(1, int(_TRIM_FRAME_S * sample_rate))
    usable = (wav.shape[0] // frame) * frame
    if usable < frame:
        return wav

    peaks = np.abs(wav[:usable]).reshape(-1, frame).max(axis=1)
    loud = np.flatnonzero(peaks > max(_TRIM_FLOOR, float(peaks.max()) * _TRIM_RELATIVE))
    if loud.size == 0:
        return wav  # nothing but silence; not ours to throw away

    start = max(0, loud[0] * frame - int(_TRIM_HEAD_S * sample_rate))
    end = min(wav.shape[0], (loud[-1] + 1) * frame + int(_TRIM_TAIL_S * sample_rate))
    return wav[start:end]


class SynthesisError(RuntimeError):
    """Raised when a piece of text cannot be spoken."""


class Cancelled(RuntimeError):
    """Raised when a job is thrown away part-way, usually because it was edited."""


# What a stop hook can ask for.
KEEP = "keep"  # finish the file here; the audio so far is worth having
DISCARD = "discard"  # bin it, nobody wants a stale half-reading

# (segments done, segments total, seconds of audio written so far)
ProgressHook = Callable[[int, int, float], None]
StopHook = Callable[[], str | None]


@dataclass(frozen=True)
class Synthesis:
    duration_s: float
    cues: list[dict]
    segments_done: int = 0
    segments_total: int = 0
    spoken_chars: int = 0
    #: Sentences in the whole document, so a reading knows what share it covers.
    document_segments: int = 0
    #: The first sentence, for telling two recordings apart at a glance.
    opening: str = ""
    #: False when a limit was hit or someone pressed stop.
    complete: bool = True
    #: Why it ended: "complete", "limit" (a sample reached its cap), or "stopped".
    reason: str = "complete"


class TTSEngine:
    """Thin wrapper over `supertonic.TTS` with the model held open."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._tts = None
        self._styles: dict[str, object] = {}
        self._lock = threading.Lock()
        # Held for one segment at a time. Two callers (the queue worker and a
        # voice preview) then take turns instead of thrashing every core, and a
        # preview waits one sentence rather than a whole entry.
        self._infer_lock = threading.Lock()

    # --- lifecycle ----------------------------------------------------------

    def load(self) -> None:
        with self._lock:
            if self._tts is not None:
                return
            from supertonic import TTS

            log.info("loading supertonic model")
            self._tts = TTS(auto_download=True)
            log.info("model ready, sample rate %s Hz", self._tts.sample_rate)

    @property
    def tts(self):
        if self._tts is None:
            self.load()
        return self._tts

    def languages(self) -> list[str]:
        from supertonic.config import AVAILABLE_LANGUAGES

        return list(AVAILABLE_LANGUAGES)

    def _style(self, voice: str):
        if voice not in VOICE_IDS:
            raise SynthesisError(f"Unknown voice {voice!r}.")
        with self._lock:
            style = self._styles.get(voice)
            if style is None:
                style = self.tts.get_voice_style(voice)
                self._styles[voice] = style
            return style

    # --- synthesis ----------------------------------------------------------

    def check_text(self, text: str) -> list[str]:
        """Return characters the model has no pronunciation for."""
        ok, unsupported = self.tts.model.text_processor.validate_text(text)
        return [] if ok else list(unsupported)

    def speakable(self, text: str) -> str:
        """Drop what this model can't pronounce instead of refusing the text.

        `markdown_speech` has already taken out the marks no voice could say;
        this is the backstop for whatever is specific to the loaded model, and it
        stays quiet because a reader has no way of acting on it anyway.
        """
        unsupported = self.check_text(text)
        if not unsupported:
            return text
        log.info(
            "dropping %d unspeakable character(s): %s",
            len(unsupported),
            " ".join(repr(char) for char in unsupported[:8]),
        )
        blanked = _SPACES.sub(" ", text.translate({ord(char): " " for char in unsupported}))
        # Line by line, so the gap a dropped character leaves at the end of one
        # doesn't survive as trailing space in a subtitle cue.
        return "\n".join(line.strip() for line in blanked.split("\n")).strip()

    def synthesize_to_file(
        self,
        text: str,
        *,
        voice: str,
        lang: str,
        speed: float,
        out_path: Path,
        limit_s: float | None = None,
        start_segment: int = 0,
        end_segment: int | None = None,
        mode: str = BY_SENTENCE,
        on_progress: ProgressHook | None = None,
        should_stop: StopHook | None = None,
    ) -> Synthesis:
        """Speak `text` into `out_path` and report where each sentence lands.

        `TTS.synthesize` throws away per-chunk timings, so this walks the
        segments and calls the model directly. Cue boundaries come from the
        sample count of the audio written rather than the duration predictor,
        which is what keeps subtitles in step with speech.

        Audio goes to disk a sentence at a time: memory stays flat however long
        the document is, and a reading that stops early leaves a playable file.

        `limit_s` stops once that many seconds exist. `start_segment` and
        `end_segment` read a slice instead, counted in sentences so a range
        begins and ends on a whole one.

        `mode` "paragraph" hands the model several whole sentences per call, so
        it places the pauses between them itself. One cue then covers the whole
        chunk. Everything reported stays counted in sentences either way, so a
        range, the progress bar and the coverage of two readings mean the same
        thing whichever mode made them.
        """
        text = self.speakable(text.strip())
        if not text:
            raise SynthesisError("There is no text to read.")

        tts = self.tts
        effective_lang = lang if tts.is_multilingual else None
        if tts.is_multilingual:
            from supertonic.config import AVAILABLE_LANGUAGES

            if lang not in AVAILABLE_LANGUAGES:
                raise SynthesisError(f"Unknown language {lang!r}.")

        style = self._style(voice)
        steps = self.settings.tts_steps
        pauses = {
            kind: np.zeros(
                int(seconds * tts.sample_rate),
                dtype=np.float32,
            )
            for kind, seconds in (
                (SENTENCE, self.settings.silence_between_sentences_s),
                (LINE, self.settings.silence_between_lines_s),
                (BLOCK, self.settings.silence_between_blocks_s),
            )
        }

        every_segment = segment_spans(text, lang=lang)
        start_segment = max(0, min(start_segment, len(every_segment)))
        sentences = every_segment[start_segment:end_segment]
        if not sentences:
            raise SynthesisError("That range doesn't cover any text.")

        # Grouping happens after the slice, so a range still begins and ends on
        # the sentences the reader picked.
        if mode == BY_PARAGRAPH:
            segments = group_spans(sentences, target=self.settings.paragraph_chunk_chars)
            limit = CHUNK_MAX_CHARS
        else:
            segments = sentences
            limit = max_chars_for(lang)
        total = len(sentences)

        cues: list[dict] = []
        cursor = 0  # samples written so far
        spoken_chars = 0
        sentence = start_segment  # where the next piece starts, in sentences
        done = 0
        complete = True
        reason = "complete"

        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = out_path.with_suffix(".partial.wav")

        try:
            with sf.SoundFile(
                str(tmp_path),
                mode="w",
                samplerate=tts.sample_rate,
                channels=1,
                subtype="PCM_16",
            ) as sink:
                for index, span in enumerate(segments):
                    segment = span.text
                    stop = should_stop() if should_stop is not None else None
                    if stop == DISCARD:
                        raise Cancelled()
                    if stop == KEEP:
                        complete = False
                        reason = "stopped"
                        break

                    if len(segment) > limit:  # the segmenter promises this already
                        segment = segment[:limit]
                    with self._infer_lock:
                        wav, _predicted = tts.model(
                            [segment], style, steps, speed, effective_lang
                        )
                    if wav.shape[0] != 1:
                        raise SynthesisError(f"Model returned an odd shape: {wav.shape}")

                    clip = wav.squeeze(axis=0)
                    if self.settings.trim_segment_silence:
                        clip = trim_silence(clip, tts.sample_rate)

                    start = cursor / tts.sample_rate
                    cursor += clip.shape[0]
                    end = cursor / tts.sample_rate
                    cues.append(
                        {
                            "i": sentence,
                            "start": round(start, 3),
                            "end": round(end, 3),
                            "text": segment,
                        }
                    )
                    sink.write(clip)
                    spoken_chars += len(segment)
                    sentence += span.parts
                    done = sentence - start_segment

                    if limit_s is not None and end >= limit_s:
                        complete = done >= total
                        reason = "complete" if complete else "limit"
                        if on_progress is not None:
                            on_progress(done, total, end)
                        break

                    if index < len(segments) - 1:
                        # A full stop mid-paragraph earns a breath; a line or
                        # a paragraph earns a stop.
                        pause = pauses[span.ends]
                        if pause.size:
                            sink.write(pause)
                            cursor += pause.size

                    if on_progress is not None:
                        on_progress(done, total, end)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise

        if not cues:
            tmp_path.unlink(missing_ok=True)
            raise Cancelled()  # stopped before a single sentence was read

        tmp_path.replace(out_path)

        covers_everything = start_segment == 0 and total == len(every_segment)
        return Synthesis(
            duration_s=round(cursor / tts.sample_rate, 3),
            cues=cues,
            segments_done=done,
            segments_total=total,
            spoken_chars=spoken_chars,
            document_segments=len(every_segment),
            opening=cues[0]["text"][:160] if cues else "",
            complete=complete and covers_everything,
            reason=reason,
        )


_engine: TTSEngine | None = None
_engine_lock = threading.Lock()


def get_engine() -> TTSEngine:
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = TTSEngine()
        return _engine


def set_engine(engine: TTSEngine) -> None:
    """Test hook: swap in a fake so the suite never loads 385 MB of ONNX."""
    global _engine
    with _engine_lock:
        _engine = engine
