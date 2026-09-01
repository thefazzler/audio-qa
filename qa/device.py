"""What compute this machine can actually offer the transcriber.

The web UI offers a device choice, so it needs an answer that is true on this
machine rather than a hopeful one. A probe that raises, or that reports a GPU
the runtime cannot actually use, would put a stack trace in front of a content
contributor.

Two rules here:

Device choice mainly affects speed, and it was measured rather than assumed.
On Course 11 a GPU decode agreed with a CPU decode on about 99.4 percent of
tokens and produced a different discrepancy count, so the honest claim is that
findings are re-verified rather than identical. See DECISIONS.md D23. The
earlier wording, "device affects speed, not results", was a reasonable
expectation that the measurement did not support.

The probe is honest about not knowing. Where CUDA is missing, too old, or
present but unusable, the reason is reported in words a person can act on.
"unavailable" with no reason is what sends someone to a support channel.

Transcription honours the selection. This module used to end by saying the
opposite, that the GPU path was wired but unused, two paragraphs after the one
above reporting a GPU decode of Course 11; a file that contradicts itself is
read by whichever half the reader reaches first.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

CPU = "cpu"
GPU = "cuda"

# The additive remediation: these land in the virtual environment and change
# nothing system wide.
CUDA_PIP_PACKAGES = (
    'pip install -e ".[gpu]"   (equivalently: '
    "pip install nvidia-cublas-cu12 nvidia-cudnn-cu12)"
)

# One sentence, used everywhere the interface talks about the choice, so the
# claim cannot drift between pages. Measured, not assumed; see D23.
DEVICE_NOTE = (
    "Device may affect decode precision; findings are re-verified. Measured on "
    "Course 11: about 99.4 percent token agreement between devices, and a "
    "different discrepancy count."
)


@dataclass(frozen=True)
class Device:
    """One offerable device, and why it is or is not offerable."""

    key: str
    label: str
    available: bool
    reason: str = ""
    detail: str = ""

    @property
    def display(self) -> str:
        return self.label if self.available else f"{self.label} (unavailable)"


def probe_cpu() -> Device:
    import os

    count = os.cpu_count() or 1
    return Device(
        key=CPU,
        label="CPU",
        available=True,
        detail=f"{count} logical processors",
    )


# The libraries a CUDA decode actually needs, beyond the driver. ctranslate2
# 4.x links cuBLAS 12 and cuDNN 9. Their absence is invisible to
# get_supported_compute_types, which is why the probe used to say a GPU was
# usable on a machine where the first kernel then failed.
CUDA_LIBRARIES = {
    "win32": ("cublas64_12.dll", "cudnn_ops64_9.dll"),
    "linux": ("libcublas.so.12", "libcudnn_ops.so.9"),
}


def enable_bundled_cuda() -> list[str]:
    """Put pip installed CUDA libraries where the loader will find them.

    The nvidia-*-cu12 wheels drop their libraries inside site-packages rather
    than on the system path. On Windows nothing looks there unless it is added
    explicitly, so the remediation this project recommends would install the
    right files and still fail without this. Returns the directories added.
    """
    added: list[str] = []
    try:
        import site
    except ImportError:
        return added

    roots: list[Path] = []
    for base in site.getsitepackages() + [site.getusersitepackages()]:
        candidate = Path(base) / "nvidia"
        if candidate.is_dir():
            roots.append(candidate)

    for root in roots:
        for directory in sorted(root.glob("*/bin")) + sorted(root.glob("*/lib")):
            if not directory.is_dir():
                continue
            added.append(str(directory))
            if sys.platform == "win32":
                # Both are needed, and finding that out cost a live debug.
                # add_dll_directory only helps loaders that pass the search
                # flags; ctranslate2 loads cuBLAS by bare name, which resolves
                # against PATH. With only the first, the libraries install
                # correctly, ctypes can load them, and the decode still dies on
                # the first kernel.
                if hasattr(os, "add_dll_directory"):
                    try:
                        os.add_dll_directory(str(directory))
                    except OSError:
                        pass
                if str(directory) not in os.environ.get("PATH", ""):
                    os.environ["PATH"] = (
                        f"{directory}{os.pathsep}{os.environ.get('PATH', '')}"
                    )
            else:
                existing = os.environ.get("LD_LIBRARY_PATH", "")
                if str(directory) not in existing:
                    os.environ["LD_LIBRARY_PATH"] = (
                        f"{directory}{os.pathsep}{existing}" if existing else str(directory)
                    )
    return added


def missing_cuda_libraries() -> list[str]:
    """Which CUDA support libraries cannot be loaded on this machine.

    Checked by actually trying to load them, because the question is whether
    the loader can find them, not whether a file exists somewhere.
    """
    import ctypes

    names = CUDA_LIBRARIES.get(
        "win32" if sys.platform == "win32" else "linux", ()
    )
    enable_bundled_cuda()
    missing = []
    for name in names:
        try:
            ctypes.CDLL(name)
        except OSError:
            missing.append(name)
    return missing


def probe_gpu() -> Device:
    """Ask CTranslate2 what it can see, and translate the answer into English.

    CTranslate2 is the runtime that would actually do the work, so it is the
    only authority worth asking. torch might report a GPU that CTranslate2 was
    not built to use.
    """
    try:
        import ctranslate2
    except ImportError:
        return Device(
            key=GPU,
            label="GPU",
            available=False,
            reason=(
                "the ASR runtime is not installed, so no GPU can be detected. "
                "Install the asr extra."
            ),
        )

    try:
        count = ctranslate2.get_cuda_device_count()
    except Exception as exc:  # the runtime raises several unrelated types here
        return Device(
            key=GPU,
            label="GPU",
            available=False,
            reason=f"the ASR runtime could not query CUDA: {exc}",
        )

    if count < 1:
        return Device(
            key=GPU,
            label="GPU",
            available=False,
            reason=(
                "no CUDA capable device was found. This machine has no NVIDIA "
                "GPU, or its driver is not installed."
            ),
        )

    try:
        names = ctranslate2.get_supported_compute_types(GPU)
    except Exception as exc:
        return Device(
            key=GPU,
            label="GPU",
            available=False,
            reason=(
                f"a CUDA device was found but the runtime cannot use it: {exc}. "
                "This is usually a driver or CUDA version mismatch."
            ),
        )

    # A card the runtime can enumerate is not yet a card it can decode on.
    # Seen live on this project's own laptop: the model loaded on cuda and the
    # first kernel then failed with cublas64_12.dll not found. Enumeration
    # succeeds without those libraries; decoding does not.
    missing = missing_cuda_libraries()
    if missing:
        return Device(
            key=GPU,
            label="GPU",
            available=False,
            reason=(
                f"a CUDA device is present but {', '.join(missing)} cannot be "
                "loaded, so a decode would fail on the first kernel. Install "
                "the runtime libraries into this environment: "
                f"{CUDA_PIP_PACKAGES}"
            ),
            detail=f"{count} CUDA device{'s' if count > 1 else ''} enumerated",
        )

    return Device(
        key=GPU,
        label="GPU",
        available=True,
        detail=f"{count} CUDA device{'s' if count > 1 else ''}, "
        f"compute types {', '.join(sorted(names))}",
    )


def memory() -> dict:
    """Total and available system memory, in gigabytes.

    Machine information, not a pipeline metric. Peak memory during a decode is
    not measured anywhere, and the stats panel says so rather than implying
    these numbers describe the run. What they do answer is the question people
    actually ask, which is whether large-v3 will fit.
    """
    total = available = None
    try:
        if sys.platform == "win32":
            import ctypes

            class Status(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = Status()
            status.dwLength = ctypes.sizeof(Status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                total = status.ullTotalPhys
                available = status.ullAvailPhys
        else:
            import os as _os

            page = _os.sysconf("SC_PAGE_SIZE")
            total = page * _os.sysconf("SC_PHYS_PAGES")
            if hasattr(_os, "sysconf_names") and "SC_AVPHYS_PAGES" in _os.sysconf_names:
                available = page * _os.sysconf("SC_AVPHYS_PAGES")
    except Exception:
        # Machine trivia must never be the reason a results page fails.
        return {"measured": False}

    gigabyte = 1024 ** 3
    return {
        "measured": total is not None,
        "total_gb": round(total / gigabyte, 1) if total else None,
        "available_gb": round(available / gigabyte, 1) if available else None,
        "note": "system memory now; peak memory during a decode is not measured",
    }


def probe() -> list[Device]:
    """Every device, best first. CPU is always present and always works."""
    gpu = probe_gpu()
    cpu = probe_cpu()
    return [gpu, cpu] if gpu.available else [cpu, gpu]


def default_device(devices: list[Device] | None = None) -> str:
    """The fastest device that actually works."""
    devices = devices if devices is not None else probe()
    for device in devices:
        if device.available:
            return device.key
    return CPU


AUTO = "auto"

# Transcription honours the selection. The probe decides whether a GPU choice
# can be met; a run that cannot use one says so rather than failing.
TRANSCRIBE_SUPPORTS_GPU = True

# Compute types for a GPU decode, best first. float16 is the default wherever
# the card offers it; the int8 mixes are the fallback for a card that cannot
# hold it. The one that is actually used is recorded, because per D21 compute
# type is in the cache fingerprint and device is not.
#
# There is no consistency argument for preferring int8 on GPU so that it
# matches the CPU path. D23 held precision constant, ran GPU at int8, and it
# still disagreed with CPU int8 on nine of thirteen topics: the device changes
# the output on its own. So int8 on a card that can do float16 would buy
# nothing and cost a third of the speed, and float16 was the run that caught a
# whole-sentence deletion CPU missed. See D23 and D27.
GPU_COMPUTE_PREFERENCE = ("float16", "int8_float16", "int8")
CPU_COMPUTE = "int8"


def gpu_compute_type(supported: list[str] | tuple[str, ...] | None = None) -> str:
    """The best precision this card actually offers.

    "Offers" is the runtime's own answer rather than a guess from the card's
    name: a card that cannot hold float16 does not list it, and only that card
    falls through to the int8 mixes.
    """
    if supported is None:
        try:
            import ctranslate2

            supported = list(ctranslate2.get_supported_compute_types(GPU))
        except Exception:
            supported = []
    for candidate in GPU_COMPUTE_PREFERENCE:
        if candidate in supported:
            return candidate
    return CPU_COMPUTE


def resolve_device(requested: str, devices: list[Device] | None = None) -> tuple[str, str]:
    """What will really be used, and a note when that differs from the ask.

    "auto" takes the fastest device that works. An explicit GPU choice that
    cannot be met falls back to CPU with the probe's own reason, because a
    selector that fails a run rather than running it slower is a worse
    selector.
    """
    devices = devices if devices is not None else probe()
    by_key = {d.key: d for d in devices}

    if requested == AUTO:
        return default_device(devices), ""

    if requested == GPU:
        gpu = by_key.get(GPU)
        if gpu is not None and gpu.available:
            return GPU, ""
        reason = getattr(gpu, "reason", "") or "no usable CUDA device"
        return CPU, (
            f"GPU was selected but cannot be used on this machine: {reason} "
            "The run will use CPU."
        )

    return CPU, ""


def effective_device(requested: str, devices: list[Device] | None = None) -> tuple[str, str]:
    """Kept as the name the rest of the code already calls."""
    return resolve_device(requested, devices)
