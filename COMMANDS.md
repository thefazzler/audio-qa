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

## `qa-web` — the web interface

    qa-web                      start the local interface on port 8501
    qa-web --port 8600          serve somewhere else
    qa-web --no-browser         do not open a browser window

The web interface and `qa-run` are two front doors to the same engine. Anything
one can do the other can; neither knows anything the other does not.

What it is for: handing the app a storyboard and a pile of narration files from
wherever they were downloaded, and having it do the organizing. It derives the
learning path, course number, course code and topic list from the filenames,
asks only the questions a filename cannot answer, copies everything into the
course library, and verifies every copy by hash before declaring the course
ingested.

Requires the web extra:

    pip install -e ".[web]"

Courses go to the library, which lives outside this repository so that no
ignore rule can ever publish customer material. Its location, in order of
precedence: an explicit setting in the app, the `AUDIO_QA_LIBRARY` environment
variable, the saved setting, then the platform default
(`%LOCALAPPDATA%` then `audio-qa\library`, on Windows).

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

## Runs

Starting a course from the web interface runs it as a separate process with an
id. Closing the tab, or the whole app, does not stop it. Come back to the Runs
tab and the run is still there; so is anyone else who opens the app.

While it runs you see the topic being transcribed, this machine's measured
decode rate, and an estimate of the time left computed from that rate rather
than from any assumption. Each topic's coverage and difference count appear as
that topic finishes, so early topics can be read while later ones are still
decoding.

Only one run per course at a time. Two would overwrite each other's
intermediates.

## Re-running a course

Every stage runs every time. The cheap stages cost about six seconds together;
transcribe skips per topic on each file's hash and does not load the model when
nothing changed. So a course whose vendor returned one corrected file
re-transcribes that topic and nothing else, and a course with no changes at all
finishes in seconds.

`--force` additionally re-transcribes every topic.

## Not commands

`qa/watchlist.py` and the other modules under `qa/` are libraries with no CLI of
their own. Tests run under `pytest` from the repo root.
