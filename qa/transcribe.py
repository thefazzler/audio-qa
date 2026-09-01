"""Module 4: transcription.

faster-whisper on CPU, one file at a time, no state shared between files.
Emits word level timestamps with per word confidence, and records any decode
anomaly it can see so that checks.py can audit the instrument rather than
trusting it.

The engine sits behind a small interface, transcribe(path, topic) -> Transcript,
so a second ASR engine can be added later as a genuine second instrument in the
way two LLM listeners were meant to be and were not.
"""

from __future__ import annotations

import re
import time
from collections import Counter
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Protocol, Sequence

from .device import (
    AUTO,
    CPU,
    CPU_COMPUTE,
    GPU,
    effective_device,
    enable_bundled_cuda,
    gpu_compute_type,
    resolve_device,
)
from .util import QAError, read_json, rel, write_json

DEFAULT_MODEL = "large-v3"

# Whisper's own repetition and confidence signals. A segment past either of
# these thresholds is the decoder telling on itself.
COMPRESSION_RATIO_LIMIT = 2.4
AVG_LOGPROB_FLOOR = -1.0

# A word this unsure is a listen item at a discrepancy site, never a defect.
LOW_CONFIDENCE = 0.6

# Share of a file's words below that floor which makes the decode itself
# suspect. Every file contains a few unsure words, so a bare count fires on
# everything and says nothing. The raw count is reported unconditionally as
# data; only the share crossing this line is an anomaly.
LOW_CONFIDENCE_SHARE = 0.01

# Repeated n-gram loop detection, for hallucination that stays inside one
# segment and so escapes the compression ratio check.
NGRAM = 4
NGRAM_REPEAT_LIMIT = 3


# Segment boundary duplication. faster-whisper re-emits the tail of one
# segment at the head of the next, either as the whole word ("provides."
# twice) or as a suffix fragment ("smartphones" then "phones"). The artifact
# signature is a suffix or repeat relationship, zero gap, and the second token
# starting a new segment. Seen on 7 of the 9 scripted Course 10 files.
DUPLICATE_GAP_S = 0.001
MIN_DUPLICATE_LEN = 2


class TranscribeError(QAError):
    pass


def _bare(token: str) -> str:
    return re.sub(r"[^\w]", "", token).lower()


def _machine_name() -> str:
    """This machine, for the packet's durable record of where a run happened."""
    import platform

    name = platform.node() or ""
    return f"{name} ({platform.system()})" if name else platform.system() or "unknown"


def boundary_duplicate_indices(
    words: Sequence[dict], segments: Sequence[dict]
) -> set[int]:
    """Word indices that look like segment boundary duplication artifacts.

    This identifies candidates only. Callers must confirm a candidate is also
    unmatched against the script before dropping it, because a word can
    legitimately be a suffix of the word before it ("demand," then "and") and
    dropping that would invent a deletion where none exists.
    """
    starts = {round(s["start"], 2) for s in segments}
    flagged: set[int] = set()
    for i in range(1, len(words)):
        current, previous = _bare(words[i]["w"]), _bare(words[i - 1]["w"])
        if len(current) < MIN_DUPLICATE_LEN or not previous:
            continue
        if current != previous and not previous.endswith(current):
            continue
        if words[i]["start"] - words[i - 1]["end"] > DUPLICATE_GAP_S:
            continue
        if round(words[i]["start"], 2) in starts:
            flagged.add(i)
    return flagged


@dataclass(frozen=True)
class ASRSettings:
    model: str = DEFAULT_MODEL
    compute_type: str = "int8"
    cpu_threads: int = 8
    beam_size: int = 5
    language: str | None = "en"
    vad: bool = True
    # Carried so a run records what it was asked for, and excluded from the
    # fingerprint on purpose; see fingerprint() below.
    device: str = "cpu"
    # What the operator asked for, kept for the record. Never in the
    # fingerprint; see below.
    requested_device: str = AUTO

    def fingerprint(self) -> str:
        """Settings identity, so a changed model invalidates old transcripts.

        Device is deliberately absent from this string. The same audio through
        the same engine at the same precision produces the same transcript on
        CPU or GPU, so switching device must never force a re-decode. Someone
        who runs a course on CPU and later re-runs it on a machine with a GPU
        should get their cached transcripts back, not thirty minutes of work
        they have already paid for.

        The nuance worth keeping straight: compute_type IS in the fingerprint.
        A GPU run at float16 is a different numerical path from an int8 run and
        can legitimately differ in what it hears, so changing precision does
        re-decode, correctly. Device alone never does.

        If anyone is ever tempted to add device here because "the GPU path is
        new and we should be safe", that is the mistake this comment exists to
        prevent: it would throw away every cached transcript on a machine that
        merely gained a graphics card.
        """
        return (
            f"{self.model}/{self.compute_type}/beam{self.beam_size}/"
            f"vad{int(self.vad)}/lang{self.language or 'auto'}"
        )


@dataclass(frozen=True)
class Word:
    w: str
    start: float
    end: float
    p: float


@dataclass(frozen=True)
class Segment:
    text: str
    start: float
    end: float


@dataclass
class Transcript:
    topic: str
    duration_s: float
    engine: str
    model: str
    settings: dict[str, Any]
    language: str | None
    language_probability: float | None
    words: list[Word]
    segments: list[Segment]
    anomalies: list[dict] = field(default_factory=list)
    decode_seconds: float = 0.0

    @property
    def last_word_end(self) -> float | None:
        return self.words[-1].end if self.words else None

    @property
    def low_confidence(self) -> tuple[int, float]:
        """Count and share of words below the confidence floor, always data."""
        low = sum(1 for w in self.words if w.p < LOW_CONFIDENCE)
        return low, round(low / len(self.words), 4) if self.words else 0.0

    def to_dict(self) -> dict:
        low_count, low_share = self.low_confidence
        return {
            "topic": self.topic,
            "duration_s": self.duration_s,
            "engine": self.engine,
            "model": self.model,
            "settings": self.settings,
            "language": self.language,
            "language_probability": self.language_probability,
            "word_count": len(self.words),
            "segment_count": len(self.segments),
            "last_word_end": self.last_word_end,
            "low_confidence_words": low_count,
            "low_confidence_share": low_share,
            "decode_seconds": round(self.decode_seconds, 2),
            "anomalies": self.anomalies,
            "words": [asdict(w) for w in self.words],
            "segments": [asdict(s) for s in self.segments],
        }


class Engine(Protocol):
    name: str

    def transcribe(self, path: Path, topic: str) -> Transcript: ...


# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------

def _repeated_ngrams(tokens: list[str]) -> tuple[str, int] | None:
    """Most repeated n-gram in a token list, when it repeats suspiciously."""
    if len(tokens) < NGRAM * NGRAM_REPEAT_LIMIT:
        return None
    grams = Counter(
        " ".join(tokens[i : i + NGRAM]) for i in range(len(tokens) - NGRAM + 1)
    )
    gram, count = grams.most_common(1)[0]
    if count >= NGRAM_REPEAT_LIMIT:
        return gram, count
    return None


def detect_anomalies(raw_segments: list[dict], words: list[Word]) -> list[dict]:
    """Decode anomalies worth surfacing to checks.py.

    These describe the instrument, not the narration. A hallucination loop or a
    collapsed segment means the transcript cannot be trusted at that spot, which
    is a different statement from "the voice said something wrong".
    """
    anomalies: list[dict] = []

    for seg in raw_segments:
        text = (seg.get("text") or "").strip()
        start = round(float(seg.get("start", 0.0)), 2)
        if not text:
            anomalies.append(
                {"type": "empty_segment", "start": start, "detail": "segment decoded to no text"}
            )
            continue

        ratio = seg.get("compression_ratio")
        if ratio is not None and ratio > COMPRESSION_RATIO_LIMIT:
            anomalies.append(
                {
                    "type": "repetition_suspected",
                    "start": start,
                    "detail": f"compression ratio {ratio:.2f} above {COMPRESSION_RATIO_LIMIT}",
                    "text": text[:120],
                }
            )

        logprob = seg.get("avg_logprob")
        if logprob is not None and logprob < AVG_LOGPROB_FLOOR:
            anomalies.append(
                {
                    "type": "low_confidence_segment",
                    "start": start,
                    "detail": f"average logprob {logprob:.2f} below {AVG_LOGPROB_FLOOR}",
                    "text": text[:120],
                }
            )

        # Whisper flipping script is the visible half of a language flip.
        if any(ord(ch) > 0x2FFF for ch in text):
            anomalies.append(
                {
                    "type": "language_flip_suspected",
                    "start": start,
                    "detail": "segment contains non-Latin script",
                    "text": text[:120],
                }
            )

        repeat = _repeated_ngrams(text.lower().split())
        if repeat:
            gram, count = repeat
            anomalies.append(
                {
                    "type": "repeated_ngram",
                    "start": start,
                    "detail": f"{gram!r} repeats {count} times in one segment",
                }
            )

    low = [w for w in words if w.p < LOW_CONFIDENCE]
    share = (len(low) / len(words)) if words else 0.0
    if share > LOW_CONFIDENCE_SHARE:
        anomalies.append(
            {
                "type": "low_confidence_words",
                "start": round(low[0].start, 2),
                "detail": (
                    f"{len(low)} of {len(words)} words below p {LOW_CONFIDENCE} "
                    f"({100.0 * share:.1f} percent, above the "
                    f"{100.0 * LOW_CONFIDENCE_SHARE:.0f} percent threshold)"
                ),
            }
        )
    return anomalies


# ---------------------------------------------------------------------------
# faster-whisper engine
# ---------------------------------------------------------------------------

class FasterWhisperEngine:
    """CTranslate2 backed Whisper, on whichever device was chosen."""

    name = "faster-whisper"

    def __init__(self, settings: ASRSettings) -> None:
        self.settings = settings
        self._model = None

    def release(self) -> None:
        """Drop the model so a fallback can load another on a different device.

        Without this the GPU model stays resident while the CPU one loads, on
        a card that has just said it is out of memory.
        """
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise TranscribeError(
                    "faster-whisper is not installed.\n"
                    "  Install the ASR extra:  pip install -e .[asr]"
                ) from exc
            if self.settings.device == GPU:
                # Make pip installed CUDA libraries findable before the
                # runtime looks for them. Without this the recommended
                # remediation installs the right files and the decode still
                # fails; see DECISIONS.md D23.
                enable_bundled_cuda()
            self._model = WhisperModel(
                self.settings.model,
                device=self.settings.device,
                compute_type=self.settings.compute_type,
                cpu_threads=self.settings.cpu_threads,
            )
        return self._model

    def transcribe(self, path: Path, topic: str) -> Transcript:
        model = self._load()
        started = time.monotonic()
        segments_iter, info = model.transcribe(
            str(path),
            language=self.settings.language,
            beam_size=self.settings.beam_size,
            word_timestamps=True,
            vad_filter=self.settings.vad,
            # Each segment is decoded without inheriting the previous one, so a
            # hallucination cannot propagate forward through the file.
            condition_on_previous_text=False,
        )

        words: list[Word] = []
        segments: list[Segment] = []
        raw: list[dict] = []

        for seg in segments_iter:
            text = seg.text or ""
            segments.append(
                Segment(
                    text=text.strip(),
                    start=round(float(seg.start), 2),
                    end=round(float(seg.end), 2),
                )
            )
            raw.append(
                {
                    "text": text,
                    "start": seg.start,
                    "compression_ratio": getattr(seg, "compression_ratio", None),
                    "avg_logprob": getattr(seg, "avg_logprob", None),
                    "no_speech_prob": getattr(seg, "no_speech_prob", None),
                }
            )
            for word in seg.words or []:
                token = (word.word or "").strip()
                if not token:
                    continue
                words.append(
                    Word(
                        w=token,
                        start=round(float(word.start), 2),
                        end=round(float(word.end), 2),
                        p=round(float(word.probability), 3),
                    )
                )

        elapsed = time.monotonic() - started
        return Transcript(
            topic=topic,
            duration_s=round(float(info.duration), 3),
            engine=self.name,
            model=self.settings.model,
            settings=asdict(self.settings),
            language=info.language,
            language_probability=round(float(info.language_probability), 3),
            words=words,
            segments=segments,
            anomalies=detect_anomalies(raw, words),
            decode_seconds=elapsed,
        )


def build_engine(settings: ASRSettings) -> Engine:
    return FasterWhisperEngine(settings)


# ---------------------------------------------------------------------------
# Stage entry point
# ---------------------------------------------------------------------------

def transcript_is_current(
    prior: dict | None, source_sha256: str, fingerprint: str, path: Path
) -> bool:
    """Whether a topic's cached transcript still stands.

    Three conditions, all necessary: a previous run recorded this topic, the
    audio has not changed, and the ASR settings that matter have not changed.
    Device is not among them, by design; see ASRSettings.fingerprint.
    """
    if prior is None or not path.exists():
        return False
    return (
        prior.get("source_sha256") == source_sha256
        and prior.get("fingerprint") == fingerprint
    )


def settings_from_course(cfg, overrides: dict | None = None) -> ASRSettings:
    """ASR settings from course.yaml's optional asr block, then CLI overrides."""
    import os

    raw = dict(getattr(cfg, "asr", {}) or {})
    raw.update({k: v for k, v in (overrides or {}).items() if v is not None})
    # Leave the top quarter of logical threads alone. Measured on an i7-12700H
    # (20 logical): 14 threads decoded at 2.41x realtime, 20 threads at 1.97x,
    # because spilling a latency sensitive decode onto the E-cores costs more
    # than the extra cores return.
    default_threads = min(16, max(4, (os.cpu_count() or 8) * 3 // 4))

    # What will actually run, not what was asked for. Recording a requested
    # "cuda" on a machine that decoded on CPU would put a false claim in every
    # transcript's settings block.
    requested = str(raw.get("device", AUTO))
    device, _ = resolve_device(requested)

    # Precision follows the device unless the caller pinned one. A GPU decode
    # at float16 and a CPU decode at int8 are different numerical paths, and
    # per D21 that difference belongs in the fingerprint while the device
    # itself does not.
    compute = raw.get("compute_type")
    if compute is None:
        compute = gpu_compute_type() if device == GPU else CPU_COMPUTE

    return ASRSettings(
        model=str(raw.get("model", DEFAULT_MODEL)),
        compute_type=str(compute),
        cpu_threads=int(raw.get("cpu_threads", default_threads)),
        beam_size=int(raw.get("beam_size", 5)),
        language=raw.get("language", "en"),
        vad=bool(raw.get("vad", True)),
        device=device,
        requested_device=requested,
    )


def run_transcribe(
    course_dir: Path,
    force: bool = False,
    overrides: dict | None = None,
    only_topics: Iterable[str] | None = None,
) -> dict:
    """Transcribe every topic, skipping files whose transcript is current.

    only_topics restricts the work to named topics; rows for the untouched
    topics are carried forward so the index stays complete.
    """
    from .config import load_course_yaml

    cfg = load_course_yaml(course_dir)
    manifest_path = cfg.qa_work / "manifest.json"
    if not manifest_path.exists():
        raise TranscribeError(f"{manifest_path} not found. Run the config stage first.")
    manifest = read_json(manifest_path)

    settings = settings_from_course(cfg, overrides)
    index_path = cfg.qa_work / "transcripts.json"
    previous: dict[str, dict] = {}
    if index_path.exists():
        try:
            previous = {r["topic"]: r for r in read_json(index_path)["topics"]}
        except (ValueError, KeyError, OSError):
            previous = {}

    selected = set(only_topics) if only_topics else None
    known = {e["topic"] for e in manifest["topics"]}
    if selected is not None:
        unknown = sorted(selected - known)
        if unknown:
            raise TranscribeError(
                "No such topic in this course: " + ", ".join(unknown)
                + "\n  Known topics: " + ", ".join(sorted(known))
            )

    engine = build_engine(settings)
    rows: list[dict] = []
    warnings: list[str] = []
    # Set once if a GPU decode fails; from then on the run is a CPU run and
    # says so everywhere it reports.
    fallback: str | None = None
    fallback_after: str | None = None
    requested_device = settings.requested_device
    started_device = settings.device

    for entry in manifest["topics"]:
        topic = entry["topic"]
        if selected is not None and topic not in selected:
            if topic in previous:
                rows.append({**previous[topic], "status": "untouched"})
            continue
        out_path = cfg.qa_work / f"transcript_{topic}.json"
        prior = previous.get(topic)
        current = transcript_is_current(
            prior, entry["source_sha256"], settings.fingerprint(), out_path
        )
        if current and not force:
            rows.append({**prior, "status": "current"})
            print(f"        {topic}  current  {prior['word_count']} words", flush=True)
            continue

        audio = cfg.course_dir / entry["audio_path"]
        try:
            transcript = engine.transcribe(audio, topic)
        except Exception as exc:
            # The probe catches a GPU that cannot work at all. It cannot catch
            # one that passes and then fails under load: out of memory on a
            # small card, a driver fault mid decode, a library that loads and
            # then errors on the first kernel. A person who picked the fast
            # option must not lose their run for it.
            if settings.device != GPU or fallback is not None:
                raise
            fallback = f"{type(exc).__name__}: {exc}"
            fallback_after = topic
            print(
                f"        {topic}  GPU decode failed, continuing on CPU\n"
                f"          reason: {fallback}",
                flush=True,
            )
            warnings.append(
                f"GPU decode failed on topic {topic} and the run continued on "
                f"CPU: {fallback}"
            )
            release = getattr(engine, "release", None)
            if callable(release):
                release()
            # The rest of the course finishes on CPU. Retrying the GPU per
            # topic is how a run ends up slower than either device alone.
            settings = replace(
                settings, device=CPU, compute_type=CPU_COMPUTE
            )
            engine = build_engine(settings)
            transcript = engine.transcribe(audio, topic)

        write_json(out_path, transcript.to_dict())

        speed = entry["duration_s"] / transcript.decode_seconds if transcript.decode_seconds else 0.0
        wpm = len(transcript.words) / (entry["duration_s"] / 60.0) if entry["duration_s"] else 0.0
        print(
            f"        {topic}  {len(transcript.words):>5} words  {wpm:>5.1f} wpm  "
            f"{transcript.decode_seconds:>6.1f}s decode  {speed:>4.2f}x realtime  "
            f"{len(transcript.anomalies)} anomalies",
            flush=True,
        )
        if transcript.anomalies:
            warnings.append(
                f"topic {topic}: "
                + ", ".join(sorted({a['type'] for a in transcript.anomalies}))
            )
        rows.append(
            {
                "topic": topic,
                "path": rel(out_path, cfg.course_dir),
                "source_sha256": entry["source_sha256"],
                "fingerprint": settings.fingerprint(),
                "word_count": len(transcript.words),
                "segment_count": len(transcript.segments),
                "duration_s": transcript.duration_s,
                "last_word_end": transcript.last_word_end,
                "decode_seconds": round(transcript.decode_seconds, 2),
                "anomaly_count": len(transcript.anomalies),
                "status": "transcribed",
            }
        )

    index = {
        "engine": engine.name,
        "model": settings.model,
        "settings": asdict(settings),
        "fingerprint": settings.fingerprint(),
        # Which machine produced these transcripts. Decode speed is a property
        # of the hardware, so a wall time on the packet means nothing without
        # it, and "which laptop was that run on" is not answerable afterwards
        # from anything else in the record.
        "machine": _machine_name(),
        # What was asked for, what actually ran, and why they differ. A silent
        # fallback would be a lie about what produced these transcripts, which
        # is worse than the failure it papered over.
        "requested_device": requested_device,
        "device_used": settings.device,
        "device_started": started_device,
        "fallback_reason": fallback,
        "fallback_after_topic": fallback_after,
        "warnings": warnings,
        "topics": rows,
    }
    write_json(index_path, index)
    return index
