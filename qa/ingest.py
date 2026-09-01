"""Stage 0: ingest.

Scan the delivery folder, identify what each file actually is, and demux the
audio track out of any video container into a normalized audio file. Every
stage after this one consumes audio only and never has to know whether the
course arrived as mp3s, mp4s, or a mix.

Decision tree:
  audio soundfile can read directly ....... pass through untouched
  video container, or audio in a container
  soundfile cannot read .................. demux to normalized audio
  anything unrecognized .................. halt the run

A mismatch between the declared project_type and the delivered formats is a
warning, never a halt. VENDOR courses usually arrive as audio and CGT courses
almost always as video, but neither is a rule worth stopping a run over.
"""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from .util import IngestError, rel, sha256_file, write_json

MEDIA_SUFFIXES = {
    ".mp3", ".mp4", ".m4a", ".wav", ".flac", ".ogg", ".oga", ".opus",
    ".aac", ".mov", ".mkv", ".webm", ".avi", ".wma", ".asf", ".wmv",
}

# Containers soundfile reads natively, so downstream needs no conversion.
PASSTHROUGH = {"mp3", "wav", "flac", "ogg"}

# Containers ffmpeg can demux or decode for us.
DEMUXABLE = {"mp4", "mov", "mkv", "webm", "avi", "m4a", "aac", "wma", "asf"}

FFMPEG_INSTALL_HINT = {
    "Windows": "winget install --id Gyan.FFmpeg -e   (then reopen the shell)",
    "Linux": "sudo apt-get install ffmpeg   (Debian or Ubuntu)",
    "Darwin": "brew install ffmpeg",
}


@dataclass(frozen=True)
class ToolInfo:
    ffmpeg: str
    ffprobe: str
    version: str


def require_ffmpeg() -> ToolInfo:
    """Verify ffmpeg and ffprobe are on PATH. Never install them from code."""
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg and ffprobe:
        version = "unknown"
        try:
            out = subprocess.run(
                [ffmpeg, "-version"], capture_output=True, text=True, timeout=30
            ).stdout
            if out:
                version = out.splitlines()[0].strip()
        except (OSError, subprocess.SubprocessError):
            pass
        return ToolInfo(ffmpeg=ffmpeg, ffprobe=ffprobe, version=version)

    missing = [n for n, p in (("ffmpeg", ffmpeg), ("ffprobe", ffprobe)) if not p]
    system = platform.system()
    hint = FFMPEG_INSTALL_HINT.get(
        system, "install ffmpeg from https://ffmpeg.org/download.html"
    )
    raise IngestError(
        "Required tool not found on PATH: "
        + ", ".join(missing)
        + "\n  The ingest stage uses ffmpeg to demux audio out of video containers."
        + f"\n  Install it, then rerun. On {system}:"
        + f"\n    {hint}"
        + "\n  This pipeline never installs system software on your behalf."
    )


# ---------------------------------------------------------------------------
# Type detection. Sniff the bytes: a delivery folder is not a place to trust
# file extensions.
# ---------------------------------------------------------------------------

MP3_FRAME_SYNC = (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2", b"\xff\xfa")
AAC_FRAME_SYNC = (b"\xff\xf1", b"\xff\xf9")
MKV_MAGIC = b"\x1a\x45\xdf\xa3"
ASF_MAGIC = b"\x30\x26\xb2\x75"


def sniff_container(path: Path) -> str:
    """Identify the container from its header. Returns "unknown" if unsure."""
    with path.open("rb") as fh:
        head = fh.read(16)
    if len(head) < 12:
        return "unknown"

    if head[:3] == b"ID3" or head[:2] in MP3_FRAME_SYNC:
        return "mp3"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head[:4] == b"fLaC":
        return "flac"
    if head[:4] == b"OggS":
        return "ogg"
    if head[:4] == MKV_MAGIC:
        return "mkv"
    if head[:4] == ASF_MAGIC:
        return "asf"
    if head[4:8] == b"ftyp":
        brand = head[8:12].decode("ascii", "replace")
        if brand.upper().startswith("M4A"):
            return "m4a"
        if brand.lower().startswith("qt"):
            return "mov"
        return "mp4"
    if head[:2] in AAC_FRAME_SYNC:
        return "aac"
    return "unknown"


def probe_streams(path: Path, tools: ToolInfo) -> dict:
    """Ask ffprobe what streams the file really holds."""
    cmd = [
        tools.ffprobe, "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise IngestError(
            f"ffprobe could not read {path.name}:\n  {proc.stderr.strip()}"
        )
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams", [])
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    video = [
        s
        for s in streams
        if s.get("codec_type") == "video"
        and s.get("disposition", {}).get("attached_pic", 0) != 1
    ]
    duration = data.get("format", {}).get("duration")
    first = audio[0] if audio else {}
    return {
        "audio_streams": len(audio),
        "video_streams": len(video),
        "codec": first.get("codec_name"),
        "sample_rate": int(first["sample_rate"]) if first.get("sample_rate") else None,
        "channels": first.get("channels"),
        "duration_s": round(float(duration), 3) if duration else None,
    }


def demux(src: Path, dst: Path, tools: ToolInfo) -> None:
    """Decode the first audio stream to mono 16-bit PCM at its native rate.

    Mono because narration is a single voice. PCM because soundfile has to read
    it for the artifact checks. Native sample rate because clipping and silence
    detection should see the delivered signal, not a resampled approximation.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".part")
    cmd = [
        tools.ffmpeg, "-nostdin", "-v", "error", "-y",
        "-i", str(src),
        "-vn", "-sn", "-dn",
        "-map", "0:a:0",
        "-ac", "1",
        "-c:a", "pcm_s16le",
        # State the muxer: the atomic .part suffix defeats format inference.
        "-f", "wav",
        str(tmp),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        raise IngestError(
            f"ffmpeg failed to demux {src.name}:\n  {proc.stderr.strip()}"
        )
    tmp.replace(dst)


# ---------------------------------------------------------------------------
# Stage entry point
# ---------------------------------------------------------------------------

def expected_kind(project_type: str) -> str:
    return "video" if project_type.upper() == "CGT" else "audio"


def _load_previous(ingest_path: Path) -> dict[str, dict]:
    if not ingest_path.exists():
        return {}
    try:
        data = json.loads(ingest_path.read_text(encoding="utf-8"))
        return {f["source"]: f for f in data.get("files", [])}
    except (OSError, ValueError, KeyError):
        return {}


def run_ingest(course_dir: Path, project_type: str, force: bool = False) -> dict:
    """Classify every delivered file and normalize it to readable audio."""
    course_dir = course_dir.resolve()
    src_dir = course_dir / "audio"
    if not src_dir.is_dir():
        raise IngestError(
            f"No audio folder at {src_dir}.\n"
            "  Expected layout: <course_dir>/audio/ holding the delivered media."
        )

    tools = require_ffmpeg()
    out_dir = course_dir / "qa_work" / "audio"
    ingest_path = course_dir / "qa_work" / "ingest.json"
    previous = {} if force else _load_previous(ingest_path)

    candidates = sorted(
        p for p in src_dir.iterdir() if p.is_file() and not p.name.startswith(".")
    )
    if not candidates:
        raise IngestError(f"No files found in {src_dir}.")

    files: list[dict] = []
    warnings: list[str] = []
    unknown: list[str] = []

    for src in candidates:
        container = sniff_container(src)
        if container == "unknown":
            suffix = src.suffix or "none"
            unknown.append(f"{src.name} (unrecognized header, suffix {suffix})")
            continue

        digest = sha256_file(src)
        streams = probe_streams(src, tools)

        if streams["audio_streams"] == 0:
            unknown.append(f"{src.name} (no audio stream)")
            continue
        if streams["audio_streams"] > 1:
            warnings.append(
                f"{src.name} carries {streams['audio_streams']} audio streams; "
                "using the first."
            )

        kind = "video" if streams["video_streams"] else "audio"

        if container in PASSTHROUGH and streams["video_streams"] == 0:
            action = "passthrough"
            audio_path = src
            status = "passthrough"
        elif container in DEMUXABLE or streams["video_streams"]:
            action = "demux"
            audio_path = out_dir / f"{src.stem}.wav"
            prior = previous.get(rel(src, course_dir))
            reusable = (
                prior is not None
                and prior.get("source_sha256") == digest
                and prior.get("action") == "demux"
                and (course_dir / prior.get("audio_path", "")).exists()
            )
            if reusable:
                status = "reused"
            else:
                demux(src, audio_path, tools)
                status = "demuxed"
        else:
            unknown.append(f"{src.name} (container {container} has no handler)")
            continue

        files.append(
            {
                "source": rel(src, course_dir),
                "container": container,
                "kind": kind,
                "action": action,
                "status": status,
                "audio_path": rel(audio_path, course_dir),
                "source_sha256": digest,
                "source_bytes": src.stat().st_size,
                "streams": streams,
            }
        )

    if unknown:
        raise IngestError(
            "Unrecognized files in the delivery folder:\n  "
            + "\n  ".join(unknown)
            + "\n  Ingest will not guess at a format. Remove these files, or "
            "extend qa/ingest.py with explicit handling for them."
        )

    wanted = expected_kind(project_type)
    off = [f for f in files if f["kind"] != wanted]
    if off:
        other = sorted({f["kind"] for f in off})
        warnings.append(
            f"project_type {project_type.upper()} expects {wanted} deliveries, but "
            f"{len(off)} of {len(files)} files are {'/'.join(other)}: "
            + ", ".join(Path(f["source"]).name for f in off)
        )

    result = {
        "course_dir": course_dir.as_posix(),
        "project_type": project_type.upper(),
        "expected_kind": wanted,
        "tools": asdict(tools),
        "counts": {
            "total": len(files),
            "passthrough": sum(1 for f in files if f["action"] == "passthrough"),
            "demuxed": sum(1 for f in files if f["status"] == "demuxed"),
            "reused": sum(1 for f in files if f["status"] == "reused"),
        },
        "warnings": warnings,
        "files": files,
    }
    write_json(ingest_path, result)
    return result
