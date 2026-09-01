"""What compute this machine can actually offer the transcriber.

The web UI offers a device choice, so it needs an answer that is true on this
machine rather than a hopeful one. A probe that raises, or that reports a GPU
the runtime cannot actually use, would put a stack trace in front of a content
contributor.

Two rules here:

Device choice affects speed, not results. The same audio decodes to the same
transcript on CPU or GPU. Anything in the UI implying otherwise would invite
someone to re-run a course on a different device hoping for a different
answer.

The probe is honest about not knowing. Where CUDA is missing, too old, or
present but unusable, the reason is reported in words a person can act on.
"unavailable" with no reason is what sends someone to a support channel.

Transcription runs CPU only in this build. The probe and the selector exist so
the GPU path can be added later without touching the UI.
"""

from __future__ import annotations

from dataclasses import dataclass

CPU = "cpu"
GPU = "cuda"


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

    return Device(
        key=GPU,
        label="GPU",
        available=True,
        detail=f"{count} CUDA device{'s' if count > 1 else ''}, "
        f"compute types {', '.join(sorted(names))}",
    )


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


# Transcription is CPU only in this build. The selector is wired and the probe
# is real, so enabling the GPU path later is a change in transcribe.py alone.
TRANSCRIBE_SUPPORTS_GPU = False


def effective_device(requested: str) -> tuple[str, str]:
    """What will really be used, and a note when that differs from the ask."""
    if requested == GPU and not TRANSCRIBE_SUPPORTS_GPU:
        return CPU, (
            "GPU was selected, but transcription runs on CPU in this build. "
            "The run will use CPU. Results are identical either way; only "
            "speed differs."
        )
    return requested, ""
