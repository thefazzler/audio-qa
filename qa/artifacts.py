"""Module 5: audio artifact detection.

Signal only. This module never sees the script and never sees the transcript,
which is what makes it a genuinely independent second track of evidence: a
finding here is about the recording, not about the words.

Built on soundfile and numpy so the whole install stays pip only. ffmpeg has
already normalized anything that needed it at the ingest stage, so every file
reaching here is readable PCM or mp3.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from .util import QAError, read_json, write_json

# Envelope resolution. 20 ms frames at 10 ms hop is fine enough to place a
# silence to within a syllable and coarse enough to stay cheap on a laptop.
FRAME_S = 0.020
HOP_S = 0.010

# A frame quieter than this counts as silence. Narration beds sit near the
# noise floor between phrases, so this is deliberately well below speech.
SILENCE_DBFS = -45.0

# Gaps worth measuring. Everything above this is a candidate; whether a
# candidate is a finding is decided later, against the course's own habits.
INTERNAL_SILENCE_S = 1.0

# Courses pad their narration and pause between slides, and every course does
# it differently. Course 10 opens and closes every file with 3.00 s of silence
# and separates slides with about 3.36 s. Measuring those as defects would
# report 49 findings on a course the manual review passed with none.
#
# So the absolute thresholds only nominate candidates. A candidate within this
# tolerance of what the course does everywhere else is a convention, recorded
# in the packet header as a measured fact, not listed as a finding. Deviation
# from the course's own norm is what gets reported.
CONVENTION_RELATIVE = 0.40
CONVENTION_ABSOLUTE_S = 1.0

# Below this many samples there is no convention to infer, so candidates fall
# back to being reported on their own.
CONVENTION_MIN_SAMPLES = 5

# Clipping. Peaks this close to full scale, in runs this long, are flat tops
# rather than a loud vowel.
CLIP_LEVEL = 0.999
CLIP_RUN = 3

# Abrupt end. If the file stops while the signal is still at speech level and
# there is essentially no trailing silence, the tail was cut rather than faded.
ABRUPT_TAIL_S = 0.200
ABRUPT_TRAILING_SILENCE_S = 0.050
ABRUPT_LEVEL_DBFS = -40.0


class ArtifactError(QAError):
    pass


@dataclass(frozen=True)
class Finding:
    type: str
    start_s: float | None
    end_s: float | None
    detail: str
    severity: str

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "start_s": self.start_s,
            "end_s": self.end_s,
            "detail": self.detail,
            "severity": self.severity,
        }


def _dbfs(values: np.ndarray) -> np.ndarray:
    return 20.0 * np.log10(np.maximum(values, 1e-10))


def frame_rms(samples: np.ndarray, rate: int) -> tuple[np.ndarray, np.ndarray]:
    """RMS envelope in dBFS, with the start time of each frame."""
    frame = max(1, int(round(FRAME_S * rate)))
    hop = max(1, int(round(HOP_S * rate)))
    if len(samples) < frame:
        return np.array([_dbfs(np.sqrt(np.mean(samples**2)))]), np.array([0.0])
    count = 1 + (len(samples) - frame) // hop
    windows = np.lib.stride_tricks.as_strided(
        samples,
        shape=(count, frame),
        strides=(samples.strides[0] * hop, samples.strides[0]),
    )
    rms = np.sqrt(np.mean(windows.astype(np.float64) ** 2, axis=1))
    times = np.arange(count) * (hop / rate)
    return _dbfs(rms), times


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Start and end indices of each run of True, end exclusive."""
    if not mask.any():
        return []
    padded = np.concatenate(([False], mask, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return list(zip(edges[0::2], edges[1::2]))


def find_clipping(samples: np.ndarray, rate: int) -> list[Finding]:
    """Runs of samples pinned at or near full scale."""
    findings: list[Finding] = []
    hot = np.abs(samples) >= CLIP_LEVEL
    for start, end in _runs(hot):
        if end - start < CLIP_RUN:
            continue
        findings.append(
            Finding(
                type="clipping",
                start_s=round(start / rate, 2),
                end_s=round(end / rate, 2),
                detail=f"{end - start} consecutive samples at or above {CLIP_LEVEL} full scale",
                severity="high",
            )
        )
    return findings


def find_silences(
    levels: np.ndarray, times: np.ndarray, duration: float
) -> tuple[list[Finding], float, float]:
    """Leading, trailing and internal silence. Returns findings and edge lengths."""
    findings: list[Finding] = []
    quiet = levels < SILENCE_DBFS
    voiced = np.flatnonzero(~quiet)

    if voiced.size == 0:
        return (
            [
                Finding(
                    type="silent_file",
                    start_s=0.0,
                    end_s=round(duration, 2),
                    detail="no frame in the file rises above the silence threshold",
                    severity="high",
                )
            ],
            duration,
            duration,
        )

    first, last = int(voiced[0]), int(voiced[-1])
    leading = float(times[first])
    trailing = max(0.0, duration - float(times[last]) - FRAME_S)

    inner = quiet.copy()
    inner[:first] = False
    inner[last + 1 :] = False
    for start, end in _runs(inner):
        length = (end - start) * HOP_S
        if length <= INTERNAL_SILENCE_S:
            continue
        findings.append(
            Finding(
                type="internal_silence",
                start_s=round(float(times[start]), 2),
                end_s=round(float(times[min(end, len(times) - 1)]), 2),
                detail=f"{length:.2f} s gap inside the narration",
                severity="candidate",
            )
        )
    return findings, leading, trailing


# ---------------------------------------------------------------------------
# Course conventions
# ---------------------------------------------------------------------------

def _consistent(value: float, norm: float) -> bool:
    """True when a measurement matches the course habit closely enough."""
    tolerance = max(CONVENTION_ABSOLUTE_S, CONVENTION_RELATIVE * norm)
    return abs(value - norm) <= tolerance


def measure_conventions(results: list[dict]) -> dict:
    """What this course does everywhere, so deviations can be found."""
    import statistics

    leading = [r["leading_silence_s"] for r in results]
    trailing = [r["trailing_silence_s"] for r in results]
    gaps = [
        f["end_s"] - f["start_s"]
        for r in results
        for f in r["findings"]
        if f["type"] == "internal_silence"
    ]
    return {
        "leading_pad_s": round(statistics.median(leading), 2) if leading else None,
        "trailing_pad_s": round(statistics.median(trailing), 2) if trailing else None,
        "slide_gap_s": (
            round(statistics.median(gaps), 2)
            if len(gaps) >= CONVENTION_MIN_SAMPLES
            else None
        ),
        "slide_gap_count": len(gaps),
        "files": len(results),
    }


def apply_conventions(result: dict, conventions: dict) -> dict:
    """Reclassify candidates that match the course habit.

    A gap the course takes everywhere is a production convention. It stays in
    the record as a measurement and is reported once in the packet header,
    rather than as a finding on every file that follows the house style.
    """
    import statistics

    own_gaps = [
        f["end_s"] - f["start_s"]
        for f in result["findings"]
        if f["type"] == "internal_silence"
    ]
    # A file with enough gaps of its own defines its own rhythm. Course 10's
    # demo pauses about 1.35 s between steps where the slide decks pause about
    # 3.36 s; judging the demo by the deck's habit reports twelve findings on
    # a file that is simply paced differently. Both norms are reported in the
    # packet, so a file that is uniformly wrong is still visible as such.
    if len(own_gaps) >= CONVENTION_MIN_SAMPLES:
        norm_gap = round(statistics.median(own_gaps), 2)
        norm_source = "file"
    else:
        norm_gap = conventions.get("slide_gap_s")
        norm_source = "course"

    kept: list[dict] = []
    conventional = 0

    for finding in result["findings"]:
        if finding["type"] == "internal_silence":
            length = finding["end_s"] - finding["start_s"]
            if norm_gap is not None and _consistent(length, norm_gap):
                conventional += 1
                continue
            finding = {
                **finding,
                "severity": "review",
                "detail": (
                    f"{length:.2f} s gap, against a course norm of {norm_gap:.2f} s"
                    if norm_gap is not None
                    else finding["detail"]
                ),
            }
        kept.append(finding)

    for edge, key in (("leading", "leading_pad_s"), ("trailing", "trailing_pad_s")):
        value = result[f"{edge}_silence_s"]
        norm = conventions.get(key)
        if norm is None or _consistent(value, norm):
            continue
        kept.append(
            Finding(
                type=f"{edge}_silence_deviation",
                start_s=0.0 if edge == "leading" else round(result["duration_s"] - value, 2),
                end_s=round(value, 2) if edge == "leading" else round(result["duration_s"], 2),
                detail=(
                    f"{value:.2f} s of {edge} silence, against a course norm of "
                    f"{norm:.2f} s"
                ),
                severity="review",
            ).to_dict()
        )

    kept.sort(key=lambda f: (f["start_s"] if f["start_s"] is not None else 0.0))
    return {
        **result,
        "findings": kept,
        "conventional_gaps": conventional,
        "gap_norm_s": norm_gap,
        "gap_norm_source": norm_source,
        "conventions": conventions,
    }


def find_abrupt_end(
    levels: np.ndarray, times: np.ndarray, duration: float, trailing: float
) -> list[Finding]:
    """A file that stops at speech level, with no decay and no trailing room."""
    if trailing > ABRUPT_TRAILING_SILENCE_S:
        return []
    tail = levels[times >= max(0.0, duration - ABRUPT_TAIL_S)]
    if tail.size == 0:
        return []
    level = float(np.max(tail))
    if level < ABRUPT_LEVEL_DBFS:
        return []
    return [
        Finding(
            type="abrupt_end",
            start_s=round(max(0.0, duration - ABRUPT_TAIL_S), 2),
            end_s=round(duration, 2),
            detail=(
                f"file ends at {level:.1f} dBFS with {trailing:.3f} s of trailing "
                "silence, so the tail shows no decay"
            ),
            severity="high",
        )
    ]


def analyze(path: Path) -> dict:
    """Every acoustic finding for one file. Pure with respect to the script."""
    try:
        data, rate = sf.read(str(path), dtype="float32", always_2d=True)
    except (RuntimeError, sf.LibsndfileError) as exc:
        raise ArtifactError(f"Could not read {path.name}:\n  {exc}") from exc

    samples = np.ascontiguousarray(data.mean(axis=1))
    duration = len(samples) / rate
    levels, times = frame_rms(samples, rate)

    findings: list[Finding] = []
    silence_findings, leading, trailing = find_silences(levels, times, duration)
    findings.extend(silence_findings)
    findings.extend(find_clipping(samples, rate))
    findings.extend(find_abrupt_end(levels, times, duration, trailing))
    findings.sort(key=lambda f: (f.start_s if f.start_s is not None else 0.0))

    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2))) if samples.size else 0.0

    return {
        "file": path.name,
        "duration_s": round(duration, 3),
        "sample_rate": rate,
        "peak_dbfs": round(float(_dbfs(np.array([peak]))[0]), 2),
        "rms_dbfs": round(float(_dbfs(np.array([rms]))[0]), 2),
        "leading_silence_s": round(leading, 3),
        "trailing_silence_s": round(trailing, 3),
        "findings": [f.to_dict() for f in findings],
    }


def run_artifacts(course_dir: Path, force: bool = False) -> dict:
    """Stage entry point: measure every file, write artifacts_<topic>.json."""
    from .config import load_course_yaml

    cfg = load_course_yaml(course_dir)
    manifest_path = cfg.qa_work / "manifest.json"
    if not manifest_path.exists():
        raise ArtifactError(f"{manifest_path} not found. Run the config stage first.")
    manifest = read_json(manifest_path)

    # First pass measures every file, second pass judges each measurement
    # against what the course does everywhere else.
    raw: list[dict] = []
    for entry in manifest["topics"]:
        result = analyze(cfg.course_dir / entry["audio_path"])
        result["topic"] = entry["topic"]
        raw.append(result)

    conventions = measure_conventions(raw)

    rows: list[dict] = []
    warnings: list[str] = []
    for result in raw:
        result = apply_conventions(result, conventions)
        topic = result["topic"]
        write_json(cfg.qa_work / f"artifacts_{topic}.json", result)

        high = [f for f in result["findings"] if f["severity"] == "high"]
        if high:
            warnings.append(
                f"topic {topic}: " + ", ".join(sorted({f["type"] for f in high}))
            )
        rows.append(
            {
                "topic": topic,
                "findings": len(result["findings"]),
                "high": len(high),
                "peak_dbfs": result["peak_dbfs"],
                "leading_silence_s": result["leading_silence_s"],
                "trailing_silence_s": result["trailing_silence_s"],
                "conventional_gaps": result["conventional_gaps"],
                "gap_norm_s": result["gap_norm_s"],
                "gap_norm_source": result["gap_norm_source"],
            }
        )

    index = {
        "total_findings": sum(r["findings"] for r in rows),
        "conventional_gaps": sum(r["conventional_gaps"] for r in rows),
        "conventions": conventions,
        "warnings": warnings,
        "topics": rows,
    }
    write_json(cfg.qa_work / "artifacts.json", index)
    return index
