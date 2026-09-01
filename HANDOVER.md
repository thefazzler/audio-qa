# Handover

For whoever picks this up next. Written so that if the person who built it is
unavailable, you can run a course end to end, understand why it is built the
way it is, and know what is unfinished.

**Step one on a new machine: run `qa-setup`.** It checks every prerequisite,
tells you the exact command for anything missing, installs the things that are
safe to install, and finishes by running the whole pipeline on a generated
fixture to prove it works. `qa-setup --check` is also the troubleshooting tool
later, when something breaks after a Python or driver upgrade. See D22.

Read this first, then `README.md` for how to install and run, then
`DECISIONS.md` when you want to know why something is the way it is. Do not
change a threshold before reading its decision entry; nearly every one was set
against a measurement rather than picked.

Gaps only the owner can fill are marked **TODO** rather than guessed at. A
visible hole is safer than a plausible invention.

## What this is for

Skillsoft courses ship with synthetic voice narration read from a storyboard
script. Sometimes the voice does not say what the script says: a dropped
sentence, a substituted word, a mispronounced acronym, a truncated file. This
finds those, and produces a packet of evidence for a human to judge.

It replaces a manual process in which two LLM chat sessions transcribed the
audio and a third reconciled them. That process worked once and exposed its own
instruments: on the reference course one transcriber silently skipped a file,
and the other truncated four of nine file tails and paraphrased heavily,
neither of them saying so. The design lesson is the reason this codebase is
shaped the way it is: **an instrument that can fail silently is worse than no
instrument.** Almost everything here is either a measurement or a check on a
measurement.

## The loop, end to end

1. **Material arrives on SharePoint** and is downloaded by hand to wherever the
   browser puts it, usually Downloads. It is never a synced folder, so there is
   no automatic pickup and nothing watches a directory. A course is a
   storyboard `.pptx` plus one narration file per topic, mp3 or mp4 or a mix.
2. **Intake** takes those files, derives the course from their names, copies
   them into the library and verifies every copy by hash. Either the web
   interface or `qa-new-course` plus a manual copy.
3. **The run** transcribes, aligns against the script, measures the audio and
   builds a packet. Tens of minutes the first time, seconds afterwards.
4. **Judgment** is manual and stays manual. Open a Claude chat, paste
   `prompts/reconciliation_v2.md`, attach the packet from `qa_out/`. It returns
   a findings report with verdicts, a listen list and remediation routing.
5. **The listen list** is worked through by a person with headphones. Nothing
   in the pipeline can settle these; that is the point of them.
6. **Remediation.** For VENDOR courses the judgment step emits an edit sheet
   block to paste into the vendor tracking spreadsheet. For CGT it emits a
   remediation plan.

   **TODO: what happens to the edit sheet after that.** Where the tracking
   spreadsheet lives, who owns it, how the vendor is notified, and what the
   expected turnaround is. The format is specified in exhaustive detail in
   `prompts/reconciliation_v2.md`; what happens to it afterwards is written
   down nowhere.

   **TODO: who acts on a SHOWSTOPPER**, and whether it changes the release
   path for a course.

## What it measures, and what it does not

This matters more than any implementation detail, because a report that is
silent about something is easily read as clearing it.

**Measured well:** word level fidelity against the script, script coverage,
truncation, audio artifacts that deviate from the course's own conventions.

**Not measured at all:** pronunciation. ASR emits orthography. It writes
"IaaS" whether the voice said "eye-as" or something wrong. The old LLM
transcribers emitted `[as:]` tags and this has no equivalent. The watchlist
detects likely mispronunciation and routes it to a human; it never certifies
one. A clean watchlist clears nothing.

**Barely measured:** delivery. There is no equivalent of odd stress or robotic
cadence. Long pauses are covered by the audio stage; nothing else is.

The judgment prompt requires every report to say this. Do not remove that
requirement.

## Two front doors, one engine

`qa-run` is the command line. `qa-web` is a local Streamlit interface for
people who would rather not open a terminal. They call the same functions.

    qa/            the pipeline: eight stages, each rerunnable alone
    qa/intake.py   derive, verify, copy, write course.yaml
    qa/jobs.py     detached runs and progress
    qa/results.py  composing a finished run for reading
    qa/library.py  where courses live
    qa/web/        Streamlit pages, no pipeline logic

The test of the layering: moving this to a server should change only `qa/web/`.
If you find yourself writing "run a course" logic in the web layer, stop.

Courses live in a library **outside this repository**, at
`%LOCALAPPDATA%\audio-qa\library` by default. That is deliberate: storyboards
and narration are customer material, and a library inside the tree would be one
bad ignore rule away from a public GitHub repo. Do not move courses into
`tests/`.

## What will bite you

**The known-answer tests skip on a fresh clone.** Courses 10 and 11 under
`tests/spisccc26/` have their audio and storyboards gitignored, so 25 or so
tests skip silently and you may never know they exist. To run them you need the
course material from SharePoint, dropped into `tests/spisccc26/course10/` and
`course11/`, then `qa-run` on each. Those tests are the real proof the pipeline
works; the rest are unit tests.

**Thresholds are measured, not chosen.** Three separate times a plausible
absolute threshold turned out to flag a course's house style rather than its
defects: a 120 wpm floor on narration that runs 115, silence limits on files
padded with 3 seconds of deliberate lead-in, a demo paced faster than the decks
it ships with. Each is now a comparison against what the course itself does.
See D6, D10. If you find yourself adding an absolute threshold, check first
whether the thing you are measuring is a convention.

**The mapper is the highest risk component.** One slide assigned to the wrong
topic produces a block of false deletions in one topic and false insertions in
the next, which reads exactly like a serious defect. It emits its evidence and
halts rather than guessing when the topic count does not match the delivered
file count. If a new course opens its topics with wording the mapper does not
know, it stops and tells you which phrase fired on which slide. Add to
`TOPIC_MARKERS` in `qa/extract_script.py`; do not paper over it with a
`slide_map`.

**Only one run per course at a time.** Two runs on one course folder overwrite
each other's intermediates and each keeps invalidating the other. The web layer
refuses this; the CLI does not stop you.

**A no-op edit is not an error.** Several bulk edits during the build silently
did nothing because a string replace whose pattern does not match changes
nothing and reports success. Assert before writing.

## Tuning for a new course

Three places absorb house style, and adding to them is normal work:

- `qa/normalize.py`, `EQUIVALENCES`: notation that should not read as a
  difference, such as "life cycle" against "lifecycle".
- `qa/extract_script.py`, `TOPIC_MARKERS`: the phrases a storyboard uses to
  open a topic.
- `qa/checks.py`: the thresholds, all named at the top of the file.

Audio conventions need no configuration; the artifact stage measures what the
course does and reports deviations from it.

A learning path may also have `watchlist.yaml` listing jargon terms to check at
every occurrence. `qa-terms` proposes candidates from the storyboards; a human
promotes them, because which terms matter and how they should be said are
judgments the command cannot make.

## What is unfinished

**`render.py` is a stub.** Phase 2 would call the Claude API with the packet
and write the edit sheet or remediation plan directly, removing the manual
paste. The interface and constraints are documented in the module. It is not
built because the packet format should settle across more courses first.

**Two listens are outstanding**, both recorded in `DECISIONS.md`:

- **D5**: whether Course 10 file 01 ends with the Topic 10 teaser sentence. The
  pipeline says it does not, at above 0.99 confidence, and the golden test
  encodes that answer. It is marked pending confirmation by ear. Ten seconds of
  audio settles it.
- **Course 11's three SIEM sites**, at ASR confidences 0.474, 0.282 and 0.533.
  Whether the term was voiced wrong or the decode merely struggled is something
  only listening can answer. The layer is designed so that a false alarm routed
  to a human is acceptable and a miss is not.

Neither blocks anything. Both stay open forever if nobody knows they were
waiting on a person rather than on code, which is why they are here.

**Two CUDA states have never been seen on real hardware.** D24 tracks all four
and which are live. `VERSION MISMATCH` needs the owner's desktop with its stale
CUDA 11.0 toolkit: run `qa-setup --check` there, follow the check's own
remediation, confirm it goes green. `NO GPU` needs any CPU-only machine, and it
is the state most contributors will be in, so it is the most valuable one left
to confirm: `qa-setup --check` plus one short run, with the selector showing
GPU greyed out and the run finishing on CPU without anyone doing anything.

**The GPU path is wired and enabled.** The device probe is real and the
selector works; transcription still runs CPU only. Enabling it is a change in
Choosing GPU decodes on GPU, about 4x faster here, and a GPU that fails under
load falls back to CPU and says so everywhere. Before you touch the cache key,
read **D21** and its correction: device is excluded from it, and the reason is
now a cost decision rather than the identity claim it started as, because
**D23** measured the two devices and they do not agree exactly.

## Who to ask

**TODO.** Names and roles for: the vendor relationship and the tracking
spreadsheet, the ACIS counterparts who receive findings, whoever owns the
storyboard source on SharePoint, and who to escalate a SHOWSTOPPER to.

Repository: https://github.com/thefazzler/audio-qa. It is public but
proprietary; see `LICENSE`. No course material is in it, in the working tree or
in its history, and it must stay that way. `DECISIONS.md` D16 describes how the
test fixtures avoid quoting narration, and the corpus scan that should be
re-run before any future publication.
