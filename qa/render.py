"""Module 10: findings rendering (phase 2, not implemented).

Phase 1 ends with a packet a human drags into a Claude chat. Phase 2 closes
that loop: call the Claude API with prompts/reconciliation_v2.md plus
packet.json, parse the findings the model returns, and write the deliverable
directly, so the only manual step left is reviewing the result.

Interface, once built:

    render(course_dir, api_key=None, model=None) -> RenderResult

    Reads   qa_out/reconciliation_packet_<course>_<date>.json
            prompts/reconciliation_v2.md
    Calls   the Claude Messages API, one request per course, with the packet
            JSON as the user content and the prompt as the system content.
    Parses  the findings document the model returns. The prompt already fixes
            the output shape: a FINDINGS table, a LISTEN LIST, and for VENDOR
            a tab separated edit sheet block inside one fenced code block.
    Writes  VENDOR: qa_out/edit_sheet_<course>_<date>.csv, built from the
                    paste block, columns in the sheet's exact order, nothing
                    populated past Reviewed By.
            CGT:    qa_out/remediation_plan_<course>_<date>.md, the plan
                    section grouped by fix path.
            Both:   qa_out/findings_<course>_<date>.md, the full document as
                    returned, kept verbatim for the audit trail.

Design constraints carried forward from phase 1:

- The judgment stays in the prompt. This module transports and parses; it
  must not classify, rank or filter findings on its own.
- The model's response is written to disk unmodified before anything is
  parsed out of it, so a parsing change can be re-run against a past response
  and so a human can always read what the model actually said.
- Audio never leaves the machine. Only the packet JSON is sent, which holds
  script text, transcript text, timestamps and confidences.
- Rerunnable in isolation like every other stage, keyed on the packet's hash
  so an unchanged packet does not spend another API call.

Not implemented yet, deliberately. The manual paste step is the current
workflow and it works; this becomes worth building once the packet format has
settled across more than one course.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .util import QAError


class RenderError(QAError):
    pass


@dataclass(frozen=True)
class RenderResult:
    findings_path: Path
    deliverable_path: Path
    model: str
    findings_count: int


def render(
    course_dir: Path, api_key: str | None = None, model: str | None = None
) -> RenderResult:
    """Call Claude with the packet and write the routed deliverable.

    Phase 2. See the module docstring for the intended behavior.
    """
    raise NotImplementedError(
        "render.py is a phase 2 stub. The current workflow is to paste "
        "qa_out/reconciliation_packet_<course>_<date>.md into a Claude chat "
        "along with prompts/reconciliation_v2.md."
    )
