# Command reference

Three commands ship with this package, declared as console scripts in
`pyproject.toml`. They are available after an editable install
(`pip install -e ".[asr,dev]"`); each can also be run as a module
(`python -m qa.cli`, `python -m qa.new_course`, `python -m qa.terms`) without
one.

All three print `FAILED: <message>` to stderr and exit `2` on a handled error,
`130` on Ctrl-C, and `0` on success.

---

## `qa-new-course` — scaffold a course folder

    qa-new-course <delivery>

Reads the course out of the delivered filenames
(`<domain>_<learning_path>_<course>_<locale>_<topic>`, e.g.
`it_spisccc26_11_enus_01.mp3`) and creates
`tests/<learning_path>/course<NN>/` with an `audio/` subfolder and a
`course.yaml`. The only thing filenames cannot answer — VENDOR or CGT — is
prompted for.

Copying the media and the storyboard `.pptx` into the new folder stays a human
step, as does listing any outline-only topics under `unscripted_topics`.

| Argument / flag | Description |
| --- | --- |
| `<delivery>` | A delivery folder, or one delivered filename to read the course from. A folder holding two different courses is a hard stop. |
| `--root PATH` | Where learning paths live. Default `tests`. |
| `--project-type {VENDOR,CGT}` | Answer the prompt up front, for scripted use. |
| `--force` | Overwrite an existing `course.yaml`. |

---

## `qa-run` — run the QA pipeline

    qa-run <course_dir>

Runs eight stages in order over a course folder. Intermediates land in
`<course_dir>/qa_work/`, the deliverable packet in `<course_dir>/qa_out/`. A
stage whose output already exists is skipped unless `--force` is given, so a
rerun after a tuning change redoes only the stale work. Each stage prints a
one-line summary, and a table of stage/status/time follows at the end.

| Argument / flag | Description |
| --- | --- |
| `<course_dir>` | The course folder to process — one holding `course.yaml`, a `.pptx` and `audio/`. |
| `--stage NAME` | Run only this stage. Implies no skipping: the named stage always runs. |
| `--force` | Rebuild outputs even when they already exist. |
| `--model NAME` | ASR model, overriding `course.yaml` (`large-v3`, `medium`, …). |
| `--threads N` | CPU threads for the ASR decode, overriding `course.yaml`. |
| `--date YYYY-MM-DD` | Packet date, overriding today. Keeps golden tests reproducible. |
| `--topic ID` | Restrict per-topic work to this topic. Repeatable. |

### The stages

| Stage | Output | What it does |
| --- | --- | --- |
| `ingest` | `qa_work/ingest.json` | Sniffs each delivered file's header, passes readable audio through and demuxes the rest. |
| `config` | `qa_work/manifest.json` | Reads `course.yaml` and builds the topic manifest with durations. |
| `script` | `qa_work/script.json` | Pulls the narration script out of the storyboard `.pptx` and maps topics to slides. |
| `transcribe` | `qa_work/transcripts.json` | ASR over each topic's audio, with per-segment confidences and anomaly counts. |
| `align` | `qa_work/discrepancies.json` | Word-level alignment of script against transcript; produces discrepancies and listen items. |
| `artifacts` | `qa_work/artifacts.json` | Signal-level audio findings (clipping, silence, level problems) with severity. |
| `checks` | `qa_work/checks.json` | Course-level rollups and coverage thresholds; flags topics needing attention. |
| `packet` | `qa_out/packet_index.json` | Writes the reconciliation packet (`.md` and `.json`) for review. |

The packet is the end of phase 1: paste
`qa_out/reconciliation_packet_<course>_<date>.md` into a Claude chat alongside
`prompts/reconciliation_v2.md`. Automating that call is phase 2 and is
currently a documented stub in [render.py](qa/render.py) — it raises
`NotImplementedError` and has no command.

---

## `qa-terms` — propose watchlist candidates

    qa-terms <target>

Reads the `script` stage's output and proposes pronunciation-watchlist
candidates: all-caps tokens (`SIEM`, `NIST`, `CISO`) and mixed-case tokens with
an inner capital (`IaaS`, `DevSecOps`). Writes
`<learning_path>/watchlist.candidates.yaml` and prints the top candidates with
their occurrence counts.

It never writes `watchlist.yaml`. Promotion is a human act — the `say` field is
written as `TODO` on purpose, because how a term should be pronounced is not
derivable from a storyboard.

Requires the `script` stage to have run: `qa-run <course_dir> --stage script`.

| Argument / flag | Description |
| --- | --- |
| `<target>` | A course folder, or a learning path folder to union candidates across every course in it. |
| `--neighbors` | Also propose tokens sharing a sentence with a term already on the watchlist — catches jargon that travels with an acronym but isn't shaped like one. |
| `--top N` | How many candidates to print. Default `25`; all are written to the file regardless. |

---

## Not commands

`qa/watchlist.py` and the other modules under `qa/` are libraries with no CLI of
their own. Tests run under `pytest` from the repo root.
