# audio-qa

Local synthetic-voice QA for Skillsoft course narration. Drop a course folder
in, get a reconciliation packet out, paste the packet into Claude, receive a
findings report.

Everything runs on your own machine. Audio never leaves it. The only external
step is pasting the finished packet into a Claude chat, which is what the
manual workflow already did.

There are two front doors to one engine. `qa-run` is the command line; `qa-web`
is a local web interface for people who would rather not open a terminal. They
call the same functions and neither knows anything the other does not.

    qa-web            hand it the downloaded files, it does the organizing
    qa-run <course>   run a course folder directly

## Where courses live

Courses live in a library outside this repository:

    %LOCALAPPDATA% then audio-qa\library      Windows
    $XDG_DATA_HOME/audio-qa/library           Linux
    ~/Library/Application Support/...         macOS

Outside, deliberately. Script documents and narration are customer material,
and a library inside the repository would be one bad ignore rule away from
being published. Override the location with the `AUDIO_QA_LIBRARY` environment
variable, or from the web interface, which remembers the choice.

The courses under `tests/` are known-answer fixtures and stay where they are.

## What it replaces

The previous process asked two LLM chat sessions to transcribe narration audio
and a third to reconcile them. It worked, and it exposed its own instruments:
on Course 10 one transcriber silently skipped a file, and the other truncated
four of nine file tails and paraphrased heavily, both without saying so.

This pipeline replaces the LLM listeners with deterministic ASR and code, and
keeps the LLM for judgment only. It also computes the completeness attestations
the transcribers used to self-report, because an instrument that stopped early
cannot honestly certify that it did not.

## Install

**On Windows, double-click `qa-setup.cmd`, then double-click `qa-web.cmd`.**
That is the whole of it. The first checks what this machine needs, installs
what is safe to install, prints the exact command for anything system wide it
will not install for you, and finishes by running the whole pipeline on a
generated fixture to prove the result works. The second opens the interface.

Nobody reviewing narration should have to learn what a virtual environment is,
and "activate the venv, then type qa-web" is where those instructions used to
lose people.

From a terminal, or on macOS and Linux, it is the same command underneath:

    git clone https://github.com/thefazzler/audio-qa.git
    cd audio-qa
    python -m qa.setup

Anything it reports as MISSING or VERSION MISMATCH in Python, git, ffmpeg or
ffprobe is system software: run the command it prints, then run setup again.
It will not install those for you.

Once the virtual environment exists, `qa-setup` is on the path:

    qa-setup --check     re-diagnose at any time, changing nothing

Use `qa-setup --check` later as the troubleshooting tool, too. When something
breaks after a Python or driver upgrade, it shows what changed.

## Requirements

- **Python 3.11 or newer.** 3.12 is what this is developed against. Avoid 3.14
  for now: ctranslate2 does not publish wheels for it and faster-whisper falls
  back to a source build.
- **ffmpeg**, on PATH. Used to demux audio out of video containers at the
  ingest stage. The pipeline checks for it at startup and stops with an
  actionable message if it is missing. It never installs system software for
  you.
- About 3 GB of disk for the ASR model, downloaded once on first run.
- **A GPU is optional.** Everything works on CPU, and the interface says so
  rather than greying out a choice with no explanation. An NVIDIA card with the
  CUDA runtime libraries decodes about 4x faster at float16. Device affects
  decode precision; findings are re-verified rather than assumed identical. See
  DECISIONS.md D23.

### Installing ffmpeg

    Windows      winget install --id Gyan.FFmpeg -e
                 then reopen the shell so PATH refreshes

    Debian/Ubuntu    sudo apt-get update && sudo apt-get install -y ffmpeg
    RHEL/Rocky       sudo dnf install -y ffmpeg-free
    macOS            brew install ffmpeg

Verify with `ffmpeg -version` and `ffprobe -version`. Both are needed.

On the future Linux server this is a deployment-time package for ops, not
something this repo installs.

## Installing by hand

`qa-setup` does all of this for you. These are here for anyone who would rather
do it themselves, or who is packaging this elsewhere.

With uv:

    uv venv --python 3.12
    uv pip install -e ".[asr,dev]"

With pip:

    py -3.12 -m venv .venv
    .venv/Scripts/python -m pip install -e ".[asr,dev]"     # Windows
    .venv/bin/python -m pip install -e ".[asr,dev]"         # Linux, macOS

As a tool, once published internally:

    pipx install --python 3.12 audio-qa

The `asr` extra pulls faster-whisper and ctranslate2. Without it every stage
except transcription still runs.

## Course folder layout

Courses are grouped by learning path, one level above the course:

    tests/
      <learning_path>/          e.g. spisccc26
        watchlist.yaml          optional, shared by every course in the path
        course10/               zero padded, so course01 sorts before course10
          course.yaml           required
          *.pptx or *.docx      exactly one script document, see below
          audio/                the delivered media, mp3 or mp4 or a mix

Both levels come straight out of the delivered filenames: in
`it_spisccc26_10_enus_01.mp3` the learning path is `spisccc26` and the course
number is `10`. `qa-new-course` builds this skeleton for you; see
[Scaffolding a new course](#scaffolding-a-new-course).

A course folder on its own is all any stage needs:

    <course_dir>/
      course.yaml               required
      *.pptx or *.docx          exactly one script document
      audio/                    the delivered media, mp3 or mp4 or a mix

The script document depends on the project type and on nothing else. A VENDOR
course's script is the speaker notes of a PowerPoint storyboard. A CGT course
has no PowerPoint at all; its script is a Word document in the BUS Writing
Template. Container format says nothing about either: topics normally arrive
as mp4 and need demux on both project types. See DECISIONS.md D26.

`course.yaml`:

    course_number: "10"
    project_type: VENDOR          # or CGT
    course_code: it_spisccc26_10_enus

    # optional
    script_source: pptx           # or docx_bus; defaults from project_type
    unscripted_topics: ["09"]     # topics whose script is an outline, not narration
    topics:                       # per-topic states unscripted_topics cannot say
      "09": {script: none}                          # no script at all
      "12": {script: freeform, file: demo.docx}     # a script of its own
    slide_map:                    # only when the auto mapper cannot do it
      "01": [2, 3]
      "02": [4, 8]
    asr:
      model: large-v3             # or medium, for faster iteration
      cpu_threads: 14

Every topic is verbatim unless something here says otherwise. The four states
are `verbatim`, `outline` (the storyboard describes the topic rather than
scripting it), `freeform` (the narration is a separate document) and `none`
(there is no script anywhere). A `none` topic is still transcribed, measured
and reported; what it cannot have is word-level alignment.

Audio files are named `<course_code>_<topic>.<ext>`. Topic ids are numeric and
may be compound, so both `_01.mp3` and `_09_01.mp4` parse.

The pipeline writes intermediates to `<course_dir>/qa_work/`. Finished
packets go somewhere else: an output folder, `Documents\audio-qa` by default and
settable in the web interface or with `--output`. They are named by course,
timestamp and device and are never overwritten, so that folder is the run
history. See DECISIONS.md D28.

## Scaffolding a new course

    qa-new-course <delivery_folder>       derive the course from what was delivered
    qa-new-course <a_delivered_file>      derive it from one filename

Point it at the delivery folder. It reads the learning path, the course number
and the `course_code` out of the filenames, asks the one question the filenames
cannot answer, and writes the skeleton:

    audio-qa: scaffolding from D:/deliveries/spisccc26-11

      learning path   spisccc26
      course number   11
      course_code     it_spisccc26_11_enus
      topics seen     3  (01, 02, 03)

      project_type [VENDOR/CGT]: VENDOR

      created tests/spisccc26/course11/
              course.yaml
              audio/

`--project-type VENDOR|CGT` answers the prompt up front for scripted use, and
`--root` puts the learning path somewhere other than `tests/`.

Copying the delivered media and the script document in stays a human step, and
so do the per-topic script states: the scaffolder writes `unscripted_topics`
and `topics` empty with a reminder, because which topics are outline-only, or
unscripted, or scripted in a document of their own, is a question only the
script answers. `script_source` is filled in from `project_type`, since that is
what decides it.

Nothing is asked about file formats, and nothing is inferred from them. Ingest
sniffs each delivered file and demuxes whatever is not already readable audio,
so an mp3 and an mp4 in the same folder need no configuration, and neither one
tells you anything about the project type or about whether a topic is a demo.

## Pronunciation watchlist

A mispronounced acronym does not arrive as silence. It arrives as a low
confidence mishearing at exactly that term: in Course 11 the ASR failed to
write SIEM in three of its thirteen topics, at low confidence, producing more
than one wrong token. General alignment surfaces those
incidentally, mixed in with everything else. The watchlist finds them
deliberately, and checks every site of every listed term whether or not
alignment had anything to say about it.

One watchlist per learning path, because acronyms are shared across a
certification journey:

    tests/<learning_path>/watchlist.yaml

    - term: "SIEM"              # canonical form, as the storyboard writes it
      expect: "SIEM"            # or a list, when more than one rendering is fine
      say: TODO                 # a note for humans; never used for matching

`expect` defaults to the term. Matching runs through `qa/normalize.py`, the same
normalizer both sides of the alignment use, so case, hyphenation and a spelled
out `I a a S` are not misses. `say` is the seed of a pronunciation guide and the
pipeline never reads it.

Each site is classified `MATCH`, `LOW CONFIDENCE` or `MISHEARD`, and every low
confidence and misheard site becomes a listen item tagged "pronunciation
candidate", with topic, timestamp, term and what was heard. The packet carries a
WATCHLIST table.

**This layer detects; it does not certify.** A match means the ASR wrote the
expected spelling, which is orthography, not pronunciation: ASR writes "IaaS"
whether the voice said "eye-as" or something wrong. Nothing here is a defect and
nothing here clears a term. If a learning path has no watchlist the check is
skipped, the packet says so in one line, and that is not an error.

### Seeding one

    qa-terms <course_dir>            candidates from one course
    qa-terms <learning_path_dir>     union across every course in the path
    qa-terms <dir> --neighbors       also propose tokens sharing a sentence
                                     with a term already on the watchlist

`qa-terms` reads the script stage's output, proposes all-caps tokens (SIEM,
NIST, CISO) and inner-capital tokens (IaaS, DevSecOps), counts occurrences and
records which topics they came from, and writes
`tests/<learning_path>/watchlist.candidates.yaml`. It never touches
`watchlist.yaml`. Promotion is a human act, and `say` is written as TODO
because how a term should be pronounced is not derivable from a storyboard.

## Running

    qa-run <course_dir>                      every stage, in order
    qa-run <course_dir> --force              rebuild everything
    qa-run <course_dir> --stage align        one stage on its own
    qa-run <course_dir> --topic 04           restrict per topic work
    qa-run <course_dir> --model medium       faster ASR while tuning
    qa-run <course_dir> --threads 14         override the thread count
    qa-run <course_dir> --date 2026-08-27    fix the packet date

A stage whose output already exists is skipped, so rerunning after a tuning
change redoes only what is stale. Inputs are hashed, so replacing one mp3
forces that file's work to rerun and leaves the rest alone.

Expect roughly one minute of decode per two minutes of audio on a recent
laptop CPU. Course 10, at 53 minutes of narration, takes about 23 minutes the
first time and seconds thereafter.

## Stages

| Stage | Module | Output | What it does |
|---|---|---|---|
| ingest | `qa/ingest.py` | `ingest.json` | Identify each delivered file by its header, demux video containers to audio |
| config | `qa/config.py` | `manifest.json` | Validate course.yaml, parse topic ids, measure durations, hash inputs |
| script | `qa/extract_script.py` | `script.json` | Pull speaker notes, map slides to topics, split sentences |
| transcribe | `qa/transcribe.py` | `transcript_<topic>.json`, `transcripts.json` | ASR with word timestamps and confidences |
| align | `qa/align.py` | `discrepancies_<topic>.json`, `discrepancies.json` | Normalize both sides identically, align, report differences |
| artifacts | `qa/artifacts.py` | `artifacts_<topic>.json`, `artifacts.json` | Signal only: silence, clipping, abrupt ends |
| checks | `qa/checks.py` | `checks.json` | Coverage, pace, tail, mapping guard, one row per topic |
| packet | `qa/packet.py` | `<output>/<course>_<date>_<time>_<device>.md` and `.json` | Assemble the evidence a judge needs |
| render | `qa/render.py` | phase 2 | Call the API and write the deliverable directly. Not implemented |

Paths are relative to `<course_dir>/qa_work/` unless stated. Stages that write
one file per topic also write a small index, which is what the runner checks to
decide whether the stage is already done.

Every intermediate is human-readable JSON. Every stage is rerunnable alone.

## Judgment step

Open a Claude chat, paste `prompts/reconciliation_v2.md`, and attach the packet
from the output folder. The prompt carries the defect taxonomy, the verdict
definitions, the VENDOR edit-sheet format and the CGT remediation plan format.

Two limits the prompt states and you should know before reading any report:

- **Pronunciation is not measured.** ASR emits orthography. It writes "IaaS"
  whether the voice said "eye-as" or something wrong. The old LLM transcribers
  emitted `[as:]` tags; this pipeline has no equivalent. Acronyms, identifiers
  and URLs are listen items, and a clean packet is not evidence they were
  voiced correctly.
- **Delivery is mostly not measured.** There is no equivalent of odd stress or
  robotic cadence. Long pauses are covered by the audio stage; nothing else is.

Word-level fidelity, coverage and truncation are measured well. Say what was
measured and what was not.

## Tuning for a new course

Three places absorb house style, and adding to them is normal work rather than
a workaround:

- `qa/normalize.py`, `EQUIVALENCES`: notation conventions that should not read
  as differences, such as "life cycle" against "lifecycle" or an acronym
  spelled out letter by letter. **Add the term to the learning path's
  `watchlist.yaml` at the same time.** Absorbing the difference is right when
  it is orthography rather than speech, and it also means alignment will never
  mention that term again; without the watchlist entry the pipeline has quietly
  stopped looking at it. See DECISIONS.md D26.
- `qa/extract_script.py`, `TOPIC_MARKERS`: the phrases a storyboard uses to
  open a topic. If a course opens topics differently the mapper halts with
  `PROBABLE MAPPING ERROR` and prints which phrase fired on which slide, so
  you can see what to add. The BUS extractor has no equivalent: a Word script
  is structured by tables rather than by wording, so it maps blocks to files by
  document order and halts the same way if the counts disagree.
- `qa/checks.py`: the thresholds, all named at the top of the file.

Audio conventions need no configuration. The artifact stage measures what the
course does everywhere and reports deviations from it, so a course that pads
three seconds of silence around every file is not reported as having 20 defects.

## Tests

    pytest

The suite covers normalization, alignment against planted defects, artifact
detection against synthetic signals, the BUS Writing Template extractor against
a document the tests generate, and Courses 10 and 11 as known-answer cases.

The known-answer tests skip automatically when the pipeline outputs are absent,
which they are on a fresh clone, because narration audio and script documents
are Skillsoft source material and are not in version control. To produce them,
drop the course material into `tests/spisccc26/course10/` and `course11/` and
run:

    qa-run tests/spisccc26/course10 --date 2026-08-27
    qa-run tests/spisccc26/course11 --date 2026-08-30

The BUS extractor's golden assertions want a real CGT script in
`tests/spcrisc26/course02/`, and skip without one. Its structural tests build a
document from nothing and always run, so a fresh clone still exercises the
rules: SCRIPT column only, scene headers stripped but kept, placeholders
dropped, blocks matched to delivered files by order, a wrong `COURSE ID`
halted.

Nothing in the suite quotes narration. Where a test has to pin what the ASR
heard, it pins a digest of it; see `tests/textdigest.py` and DECISIONS.md D16.
And nothing pins a confidence, a word count or a coverage figure to three
decimal places, because those move between CPU and GPU and a test that pins
them breaks the first time someone runs it on other hardware. See D23 and D25.

## If you are taking this over

Read `HANDOVER.md` first. It covers what the tool is for, where course material
comes from, the whole loop from delivery through judgment to remediation, what
is deliberately not automated, what is unfinished, and the things that will
bite you. Gaps that only the owner can fill are marked TODO there rather than
guessed at.

## Notes

`DECISIONS.md` records where the build departs from
`Audio_QA_Pipeline_Build_Spec_v1.md` and why. Read it before changing a
threshold; most of them were set against a measured result rather than picked.

## License

Copyright (c) 2026 Skillsoft. All rights reserved. Proprietary; see LICENSE.
The repository is readable publicly, which is not the same as a grant of rights
in it. No permission to use, copy, modify or redistribute is given to anyone
outside Skillsoft.
