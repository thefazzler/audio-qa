# Decision log

Amendments to Audio_QA_Pipeline_Build_Spec_v1.md, agreed during the build.
The spec file is left as written; this file is what the code follows where the
two differ.

## How this file is maintained

**A decision that earns a code comment or a test earns an entry here.**

The reasoning behind a choice must never live only in the code. A comment is
read by whoever happens to open that file; a test states what must stay true
but not why it was ever in doubt. Neither is where someone looks before
changing a threshold, and neither survives the file being refactored.

This rule was written after a real miss. The transcript cache key deliberately
excludes the device and deliberately includes the compute type, which is the
single choice most likely to be undone by a well meaning change to the GPU
path. It had a thorough comment and five tests, and no entry here, so the
handover ended up pointing at a decision that did not exist. It is now D21.

Practically: if you find yourself writing a comment that explains why rather
than what, or a test whose name is an argument, write the entry too. Number it
next in sequence, and cite it from the comment. A test asserts that every D
reference in the documents resolves to a real entry.

## D1. Ingest stage added ahead of config (spec had no stage 0)

Scan the delivery folder, identify each file by sniffing its header rather than
trusting the extension, and demux the audio track out of any video container
into a normalized audio file. Everything downstream is audio only and format
agnostic.

Decision tree: audio soundfile reads natively passes through untouched; video
containers and audio containers soundfile cannot read are demuxed; anything
unrecognized halts the run. A mismatch between the declared project_type and
the delivered formats is a WARNING, not a halt, because VENDOR courses
sometimes arrive as video and CGT courses almost always do.

## D2. ffmpeg is a required documented prerequisite

Used for demux at the ingest stage. Verified on PATH at stage startup, with a
per-platform install hint on failure. The pipeline never installs system
software on its own. ffmpeg is the only sanctioned system binary; every other
dependency is pip installable. Module 5 is built on soundfile plus numpy, not
pydub, to keep it that way.

## D3. ASR tail check

Add last-transcribed-word-end against audio duration. A final word ending more
than about 40 s before the file ends is flagged, and paired with the artifact
module's trailing-silence measurement to separate "narration stopped early"
(a real defect) from "decoder stopped early" (instrument failure).
transcribe.py sets condition_on_previous_text=False to stop hallucination
drift carrying across segments.

## D4. Topic mapper emits evidence and is hard checked

The auto mapper records which marker phrase fired on which slide. The number
of topics it infers must equal the number of delivered audio files or the run
halts with PROBABLE MAPPING ERROR and prints the evidence. checks.py reports
low script coverage as a probable mapping error rather than as a narration
defect.

The spec's marker set was insufficient. "In this video" and "In this
demonstration" alone would have merged topics 08, 09 and 10 into one block on
Course 10, because slide 43 opens "Demonstrate cloud sharing permissions" and
slide 44 opens "In this course, we outlined". Marker set is now:

    demo_intro     ^(in this demonstration|in this demo|demonstrate)
    video_intro    ^in this (video|topic)
    summary_intro  ^in this course,\s*we

Markers are matched against the opening sentence only, so a back reference
later in the notes is not a boundary.

## D5. Course 10 tail assertion (listen item L5)

The first full run produces the answer to whether file 01 ends with the Topic
10 teaser sentence, with timestamp and ASR confidence. Ryan verifies by ear.
Only then is the verified result frozen as the golden value. The test does not
assert the trivial "either way" version.

Status: ANSWER PRODUCED, awaiting confirmation by ear.

First run, large-v3 int8, 2026-08-27. File 01 transcribes to 162 words across
8 segments. The final word ends at 80.67 s of 84.026 s, leaving 3.36 s of
trailing audio. The transcript ends on the last sentence of the topic 01
script, matching it token for token, at word confidences above 0.99.
The Topic 10 teaser sentence does not appear anywhere in the file. Zero words
in the file fall below p 0.6 and the decoder reported no anomalies.

So the pipeline's answer is that L5 is a false alarm: Gemini's extra sentence
was cross-file bleed, and file 01 is clean. Ryan listens to the last ten
seconds to confirm, then this becomes the frozen golden value.

## D6. WPM check is a ratio, not an absolute floor

The spec and the v4 transcriber prompt both flag below 120 words per minute as
POSSIBLE TRUNCATION, on the assumption that professional TTS narration runs
140 to 160 wpm. Course 10 measures 115.6 wpm overall, and nine of its ten
files fall below 120. The absolute floor would flag almost the whole of a
course the manual run rated clean.

checks.py instead compares transcript wpm against the rate the script implies
for that same file, and flags deviation beyond a band. Script coverage percent
and the tail check remain the primary truncation detectors.

Course 10 per file script rate, for reference:

    01 113.5   02 112.2   03 115.8   04 118.7   05 120.3
    06 123.8   07 114.8   08 108.5   10 105.3     all 115.6

This applies to the v4 transcriber prompt as well. Its PACING SELF-CHECK
section needs the same correction if that prompt stays in service.

## D7. Topic ids come from the delivered filenames

The demo file is delivered as `it_spisccc26_10_enus_09.mp4`, so the pipeline
topic id is `09`. The manual findings report calls it `09_01`; that was the
LLM run's numbering and is not carried forward.

## D8. Accepted refinements

- Sentence splitter carries an explicit abbreviation exception set in one
  place, so "e.g." and "U.S." do not split a sentence.
- The packet date is injectable so golden file comparison is reproducible.
- The manifest records a sha256 for every input, and a changed hash forces
  that file's work to rerun.
- Identifiers and URLs are handled in the normalization equivalence table and
  flagged as listen items rather than forced into normalized agreement.
- Discrepancies that are purely normalization equivalent are suppressed from
  the packet. A topic over the diff threshold lists the top N with a
  suppressed count and a mapping error warning, rather than dumping every row.
- Page budget suppression applies to scripted topics only. An unscripted
  topic's transcript runs its natural length in the packet, because that
  transcript is the only evidence a judge has for that file. Course 10's
  topic 09 is 9.1 minutes, roughly 1050 words, so the demo alone can occupy
  a large share of the packet. That is accepted.
- Skillsoft source material is gitignored: storyboards, narration audio, and
  findings reports, which quote storyboard script text verbatim. The three
  prompt and spec documents stay in version control.

## D9. Build environment

Python 3.12, not the machine default 3.14, because ctranslate2 does not
publish 3.14 wheels and faster-whisper would fall back to a source build.
pyproject keeps requires-python at >=3.11.

A small qa/util.py holds the error types, JSON IO, hashing and the sentence
splitter. It is not in the spec's module list, but four stages need those
helpers and duplicating them would be worse.

## D10. Artifact detection compares against the course's own conventions

Absolute silence thresholds reported 49 findings on Course 10, which the
manual review passed with zero artifact flags. Every one was a production
convention: each file opens and closes with 3.00 s of pad, and slides are
separated by about 3.36 s.

So absolute thresholds only nominate candidates. A candidate within tolerance
of what the course does everywhere is recorded as a measured convention and
reported once in the packet header, not listed as a finding on every file
that follows house style. A file with at least five gaps of its own uses its
own median as the norm, because Course 10's demo pauses about 1.35 s between
steps where the decks pause 3.36 s, and judging the demo by the deck's habit
reported twelve findings on a file that is simply paced differently.

Both norms are printed in the packet so that a file which is uniformly wrong
stays visible to a human. Clipping, abrupt ends, silent files, gaps that
break the local norm, and edge padding deviations still fire; tests assert
each of those.

## D11. Packet length

The 2 to 6 page target in the spec holds for the scripted part of a course.
Course 10's packet is about 7.0 pages, of which the nine scripted topics plus
header, topic map and checks table are 2.5 pages. Topic 09's transcript is
the remaining 4.5. That follows from letting unscripted transcripts run their
natural length, which is deliberate: for a demo the transcript is the only
evidence a judge has. Length discipline is applied to scripted topics only,
capped at 25 listed differences with a suppressed count and a mapping error
warning beyond that.

## D12. Whisper segments are not sentences

The sentence count check joins all segment text before splitting, because a
Whisper segment is a decode window and one sentence routinely spans two.
Counting per segment nearly doubled the transcript total and read as invented
content sitting next to the script count.

## D13. Courses are filed under their learning path

Course folders were flat under `tests/`. They now sit one level deeper:

    tests/<learning_path>/<course>/

so `tests/course10/` became `tests/spisccc26/course10/`. Both levels are
already in the delivered filenames and neither needed inventing: in
`it_spisccc26_10_enus_01.mp3` the second segment is the learning path and the
third is the course number.

Course folders are zero padded, `course01` through `course10`, so a directory
listing sorts in course order rather than putting course10 ahead of course02.
`course_number` and `course_code` in course.yaml stay verbatim from the
filenames, because course_code has to match the files for topic parsing to
work; only the folder name is padded.

No pipeline code changed. Every stage already took a course folder as its
argument and wrote relative paths inside it, so the move touched only
`tests/test_course10.py`, the README and the `audio/` line in `.gitignore`,
which is now `tests/*/*/audio/` and covers every learning path. The gitignored
`qa_work/ingest.json` and `qa_out/packet_index.json` still record the old
absolute paths; nothing reads those fields, and the next `--force` run rewrites
them.

## D14. qa-new-course scaffolds from the delivered filenames

New command, `qa/new_course.py`, entry point `qa-new-course`. It takes the
delivery folder (or one delivered filename), and derives:

    learning path   second filename segment      spisccc26
    course number   third segment                11
    course_code     prefix through the locale    it_spisccc26_11_enus

then creates `tests/<path>/course<NN>/`, its `audio/` subfolder, and a
course.yaml with the same key set as Course 10's.

Only `project_type` is prompted for, because it is the only fact the filenames
do not carry. It re-asks on an unrecognized answer, and `--project-type` skips
the prompt for scripted use.

Nothing is asked about file formats. Per D1, ingest sniffs each delivered file
and demuxes anything that is not already readable audio, so mp3 against mp4 is
not a course level setting and putting it in course.yaml would create a second
source of truth that could disagree with the bytes.

`unscripted_topics` is written empty with a TODO comment. Which topics are
outline-only is only answerable from the storyboard, and per D4 a wrong value
here shows up as a mapping halt rather than as silent damage. Guessing it
would be worse than leaving it blank.

The command creates structure only. Copying the narration and the storyboard
into place stays a human step: that material is Skillsoft source, gitignored
per D8, and a scaffolder has no business moving it. A delivery folder holding
two different courses is a hard stop rather than a guess.

## D15. Pronunciation watchlist, level 1: detect and route, never certify

Course 11 produced the evidence for this. The ASR failed to write SIEM at
three of its sites, at p 0.474, 0.282 and 0.533, producing two different wrong
tokens rather than the term. General alignment did surface all
three, but incidentally, mixed into 29 other differences, and it said nothing
at all about the eleven sites where SIEM was heard correctly. Alignment reports
differences; it cannot answer "was this term checked everywhere". That question
is what this layer answers.

New module `qa/watchlist.py`, plus `qa/terms.py` behind the entry point
`qa-terms`. Every change is additive: no existing stage's behavior, output
fields or thresholds changed.

**The line this layer must not cross.** ASR emits orthography, not
pronunciation. It writes "IaaS" whether the voice said "eye-as", "ee-ay-ay-ess"
or something wrong. So a MATCH here means the expected spelling appeared with
reasonable confidence, and nothing more. This layer detects likely
mispronunciation and routes it to a human; it never certifies pronunciation as
correct or wrong. That sentence is in the module docstring, in the packet's
WATCHLIST header, and in the v2 reconciliation prompt's "what the instrument
is" section, so the judgment stage cannot read a clean table as a pass. The
prompt is now v2.1.

**One watchlist per learning path**, at `tests/<learning_path>/watchlist.yaml`,
not per course, because acronyms belong to a certification journey rather than
to any one course in it. Absence is not an error: the check is skipped and the
packet says so in one line.

**Matching reuses normalize.py.** A second normalizer would drift from the one
alignment uses, and then a term could be a match on one page and a miss on the
next. Terms are normalized with the same `build_sequence` the aligner runs, so
`IaaS`, `iaas` and a spelled out `I a a S` are one key, via the equivalence
table that already existed. Sites are located by projecting the script token
range through the same `SequenceMatcher` opcodes alignment uses, so a site
reported here is the site alignment put opposite the term.

**Three classifications, no fourth.** MATCH, LOW CONFIDENCE (expected form
present but below the existing 0.6 floor, reused from align.py rather than
redefined), MISHEARD (something else there). None of them is a defect verdict.
Every LOW CONFIDENCE and MISHEARD occurrence becomes a listen item tagged
"pronunciation candidate" carrying topic, timestamp, term and what was heard.

**Watchlist listen items are counted separately** from the existing per topic
`listen_items` field rather than added into it. Folding them in would change a
number every earlier run and the Course 10 golden test already depend on, which
is exactly the non-additive change this work was supposed to avoid. The packet
reports both, under their own headings.

**qa-terms proposes, humans promote.** It reads script.json, extracts all-caps
tokens of two or more letters and inner-capital tokens, counts occurrences per
term and records which course and topic each came from, and writes
`watchlist.candidates.yaml`. It never writes `watchlist.yaml`. The candidates
file carries `occurrences` and `seen_in` keys, and the watchlist parser ignores
exactly those two so that promoting a candidate is a copy rather than a retype;
any other unrecognized key is a typo and halts.

`say` is written as TODO and is never guessed. How a term should be pronounced
is not derivable from a storyboard, and a wrong pronunciation note in a file
whose whole purpose is pronunciation would be worse than an empty one.

Two parser details worth stating because both would fail silently. YAML reads a
bare `NO`, `ON` or `YES` as a boolean, which would rename a term to `False`, so
terms are quoted on write and a boolean term is a hard error on read. And a
term that normalizes to nothing can never match anything, so that is an error
rather than a permanently silent entry.

**spisccc26 seed.** `qa-terms` proposed ten candidates across Courses 10 and 11:
AI 56, SIEM 14, SaaS 8, CTI 6, IaaS 6, PaaS 6, ID 2, IP 1, MITRE 1, and one
more with a single occurrence. Only two were seeded into the watchlist, on the
evidence rule that a term goes on the list when a completed run already
flagged it: SIEM, misheard at three sites in Course 11, and SaaS, decoded at
p 0.415 in Course 10 topic 04. The rest wait in the candidates file.

That tenth proposal was a doubled-letter typo in a storyboard, which the
mixed-case rule read as jargon. It is a proofreading error rather than a term,
so it is not watchlist material and has been removed from the candidates file
as well: it named the exact course and topic where a customer's typo lives.

Course 11 measured, first run: SIEM occurs 14 times, 11 matched, 3 misheard.
Frozen as the golden value in `tests/test_course11.py`, pending confirmation by
ear in the same way D5's tail assertion is. The layer is allowed to route a
false alarm to a human. It is not allowed to miss one.

## D16. Test fixtures assert on structure and digests, never on narration

The repository is public. Skillsoft storyboard narration, and the transcripts
made from it, are customer material and must not appear in it verbatim. The
known answer tests originally quoted script and transcript sentences directly,
because that was the clearest way to pin a result while the repo was private.

Those assertions are now structural. Three mechanisms, in order of preference:

1. **Derive the expected text from pipeline output at run time.** The L5 tail
   assertion reads topic 10's closing sentence and topic 01's closing sentence
   out of script.json, normalizes both through qa/normalize.py, and compares
   token sequences against the transcript. Nothing is quoted, and the
   assertion is stronger than the substring check it replaced: it holds
   against whatever the storyboard actually says rather than against a copy
   frozen in a test file, and it compares through the same normalizer the
   pipeline uses, so hyphenation and number spelling cannot cause a false
   pass or a false failure.
2. **Pin identity by digest.** tests/textdigest.py takes a short sha256 over a
   canonical form of a string. Expected sentences and the tokens the ASR heard
   at a watchlist site are compared by digest. A digest fails on exactly the
   regressions the literal string caught.
3. **Assert the surrounding structure.** Token and word counts, topic ids,
   slide numbers, timestamps, confidences, status values, and relationships
   between sites, for example that two of the three misheard SIEM sites
   produced the same wrong token and the third produced a different one.

Verified by mutation rather than by inspection. Six mutations were applied to
the pipeline outputs and each was confirmed to fail the test that covers it:
the teaser sentence planted into file 01, file 01's tail truncated, the L7 site
absorbed, the L7 transcript text changed, a watchlist site's heard token
changed, and one misheard site silently dropped. All six fail. The suite is
110 tests before and after the scrub.

Honest limitation, stated in tests/textdigest.py as well: a digest of a short
common token is not secrecy, since anyone can hash a wordlist. The goal is that
the repository does not quote course narration, not that the digests are
irreversible. Long sentences are effectively opaque; single words are not.

Applies to tests/test_course10.py and tests/test_course11.py. tests/
test_watchlist.py and tests/test_align.py use invented sentences and needed no
change.

### D16 addendum: two documents paraphrased for publication

Reaching zero occurrences of course narration in the published repository
needed two edits beyond the test fixtures.

`DECISIONS.md` D5 quoted the closing fragment of topic 01's script as evidence
for the L5 answer. It now states that the transcript matches that sentence
token for token, which is the same evidence without the words.

`Audio_QA_Pipeline_Build_Spec_v1.md` quoted the topic 10 teaser sentence in
full when setting the L5 acceptance criterion. It now refers to that sentence
by where the storyboard puts it.

The second one is an exception to the rule stated at the top of this file, that
the spec is left as written. The exception is narrow and recorded here: one
quoted sentence paraphrased, no requirement changed. Everything else in the
spec stands as authored.

### D16 addendum: the unit test fixture was not as synthetic as it looked

`tests/test_align.py` carried a four sentence SCRIPT fixture written in the
reference course's own vocabulary, and one of its sentences overlapped that
course's narration almost word for word. It was written while the manual
findings report was open, and reading it as synthetic was wrong. The fixture is
now about potting plants, which no course this pipeline runs will ever cover.

Found by scanning every tracked file for four word overlaps against the
narration in every course's script.json and transcripts, rather than by
grepping for remembered phrases. That scan is the check worth repeating before
any future publication: spot checks find what you already suspect, and this one
found what nobody suspected.

Tracked files now show zero four gram overlaps outside D4's marker phrases,
which are load bearing because they are the literal strings TOPIC_MARKERS
matches on, and a handful of ordinary English collocations.

## D17. Every stage runs every time, except transcribe

**The defect.** The stage runner skipped a stage when its output file already
existed. Underneath that, the pipeline carries a hash per delivered file and
uses it correctly. The skip short circuited it. A vendor returned a corrected
mp3, the operator re-ran, and `ingest` was skipped because ingest.json existed,
so the file was never re-hashed, so the manifest kept the old hash, so
transcribe's per-topic staleness check never saw a change. Nothing re-ran. The
same held for a corrected storyboard: script.json existed, the script stage was
skipped, and alignment ran against the previous script silently.

It was masked because `--force` was the habit during the build. For a web UI
where re-submission is a button, it would have been a silent wrong answer, and
the wrong answer is the expensive kind: a packet that looks complete and is
aligned against superseded material.

**The fix.** Every stage runs every time. Transcribe still skips per topic on
its own hashes, and does not load the model when every topic is current, so an
unchanged course still costs seconds. Measured on Course 10: ingest 1.2s,
config 0.0s, script 0.5s, align 0.3s, artifacts 3.0s, checks 0.2s, packet 0.2s,
about six seconds together against a 23 minute decode.

Verified rather than assumed. One file of ten was replaced with different bytes
and the course re-run: that topic re-transcribed in 35.5 seconds, the other
nine reported `current`, and exactly one hash changed in the manifest.

`--force` now means "also re-transcribe everything", which is the only thing
left for it to mean.

The script stage also records the storyboard hash it extracted from and warns
when it differs from the previous run, so its dependence on the storyboard is
explicit rather than incidental.

**Scope.** This is a pipeline change made during the web build, which the rule
"the web layer must not modify the pipeline" would otherwise forbid. It is a
correctness fix the investigation surfaced, not web logic leaking into the
engine, and it was approved as an exception on that basis.

## D18. The course library, and two front doors to one engine

**Where courses live.** Outside the repository, at the platform data directory:
`%LOCALAPPDATA%\audio-qa\library` on Windows, `$XDG_DATA_HOME/audio-qa/library`
on Linux, `~/Library/Application Support/audio-qa/library` on macOS.

The reason is not tidiness. Storyboards and narration are customer material,
and a library inside the repository would sit one bad ignore rule away from a
public GitHub repo. Two rounds of this build were spent removing narration from
that repo. Keeping courses out of the tree means no edit to `.gitignore` can
publish one.

Configured in four layers, first match wins: an explicit argument, the
`AUDIO_QA_LIBRARY` environment variable, a `library` key in the user config
file, then the platform default. Both the variable and the file exist on
purpose: the variable is how a scripted or containerised run is configured, and
the file is how someone who never opens a terminal points the app elsewhere
once, from the UI.

Settings are JSON, not TOML. The standard library reads both and writes
neither, and JSON escapes Windows paths correctly without any quoting decisions
of ours.

Platform directories are hand rolled, about twenty lines, rather than adding
platformdirs. The rules are stable and getting them wrong fails visibly.

**Paths are normalized without following links.** `Path.resolve()` was the
obvious choice and was wrong. It follows junctions and reparse points, and it
answers differently depending on whether the path exists yet, so the library
location shown in the UI before the first course was ingested did not match the
one shown afterwards. On Windows it also resolved through packaged-app
redirection and reported a path inside another application's private cache. An
app that names one location and writes to another is not trustworthy, whatever
the reason. The library path is now made absolute and tidy without resolution,
so the location a person configured is the location they are shown.

Found by driving the UI rather than by reading the code; the unit tests all
passed either way. There is now a regression test for both halves.

**Fixtures stay in `tests/`.** Courses 10 and 11 remain known-answer fixtures.
Tests must not depend on where a person pointed their library. The UI starts
empty; nothing is copied into the library to populate it.

**Two front doors, one engine.** Three layers, kept apart:

    qa/            the pipeline. Untouched by the web work except for D17.
    qa/intake.py   the service layer: derive, verify, copy, write course.yaml.
    qa/library.py  where things live.
    qa/device.py   what this machine can do.
    qa/web/        Streamlit pages. No pipeline logic.

The test of the layering is that moving to a server would change only
`qa/web/`. Intake reuses the scaffolder's own filename parser, so intake and
`qa-new-course` cannot drift apart.

**Intake decisions.** Copy, never move: the delivery is the only copy of
customer material until intake succeeds, and removing it is a separate explicit
act offered afterwards. Every copy is verified by hashing the source before and
the destination after, because a short write that nobody noticed surfaces much
later as a transcript that disagrees with the storyboard, and the hours between
those two events are what make it expensive.

Being a video and being outline-only are independent facts. The form suggests a
video topic as a candidate and the user confirms, because a video is often a
demo but a demo is not always a video and a video is not always outline-only.

The device selector is wired to a real probe of what CTranslate2 can actually
use, and reports a readable reason when a GPU is unavailable rather than a
stack trace. Transcription is CPU only in this build; the selector exists so
the GPU path can be added without touching the UI. The UI states that device
affects speed and not results, in three places, because a person who believes
otherwise will re-run a course hoping for a different answer.

The browser's own file uploader is not used. It hands over bytes rather than
paths, and this intake needs paths: to verify a copy against its source, and to
offer to clean up the originals. A 128 MB demo video also has no business
travelling through an upload on a machine that already holds the file. The
Browse button opens the operating system's dialog in a short lived subprocess,
because a Tk main loop inside a web server's worker thread hangs on some
platforms. Pasting paths is always available as a fallback.

## D19. Detached runs, and progress that tells the truth

**A run is a separate process.** Not a thread. A thread inside the web server
dies when the server restarts and is awkward to survive a tab closing; a
subprocess survives both. Its status is a JSON record any process can read, so
a second person can watch a run they did not start, and the CLI is unaffected.

**Progress is read out of the pipeline's own outputs.** A watcher polls
`qa_work/transcript_<topic>.json`, each of which already carries its decode
time and audio duration. Nothing in the pipeline was instrumented to make this
work, so the engine stays free of reporting code.

**The primary bar is per topic, not per stage.** Eight stage ticks sit frozen
for the twenty minutes transcription takes, which is the only part anyone is
waiting for.

**The ETA is measured on this machine, on this run.** Rate is total audio over
total decode time across topics finished this run; the estimate is remaining
audio divided by that rate, refined as each topic lands. A hardcoded rate would
be wrong on a slower laptop today and wrong again when the GPU path arrives. A
test asserts no invented multiplier appears in the module.

**Results stream per topic.** As each transcript lands, the watcher aligns it
by calling `qa.align.align_topic`, the same function the align stage calls, on
the same inputs. It is a preview in timing only: the align stage still writes
the authoritative files, and the two cannot disagree because they are one
implementation with two callers. Without it a person waits out the whole decode
before learning anything about topic one. A test asserts the streamed numbers
equal the stage's.

### Three bugs found by running it, not by reading it

**Old transcripts counted as progress.** The first real run showed ten of ten
topics complete before decoding started, and an estimate of zero seconds while
twenty minutes of work remained, because transcripts from a previous run were
on disk. That is precisely the false comfort per topic progress exists to
prevent. File age against the job's start now separates work this run did from
work it is reusing, and the two are counted and displayed separately: "10 of 10
transcribed" on a run that decoded nothing is true and useless.

**A re-decoded topic was invisible.** Once a topic was marked cached and
aligned, the watcher never looked at its file again, so a forced run that spent
74 seconds decoding reported that it had decoded nothing. The watcher now
re-reads whenever a file's mtime changes.

**Two runs on one course destroyed each other.** Starting a second run while
one was in progress had both writing the same `qa_work` intermediates, each
invalidating the other's hashes, so both re-transcribed the entire course and
neither finished. Submission now refuses a course that already has an active
run. A record still claiming to be running after two minutes of silence is
treated as abandoned rather than blocking forever, since its process is gone.

None of the three would have been caught by the unit tests as written. All
three have regression tests now.

### A note on writing these

Three separate edits to this codebase silently did nothing this session,
because a string replace whose pattern did not match is a no-op. One of them
looked like a logic bug for several minutes. Bulk edits now assert that the
pattern was found before writing.

## D20. Results, the listen list, and one home for telemetry

**The page is ordered by what happens next, not by what was computed.** The
listen list comes before the checks table, because it is the only part that
requires a person and the whole pipeline exists to produce it. Burying it under
an expander would make the deliverable look like a footnote to the diagnostics.

**This layer does not assign verdicts.** CLEAN, FIX RECOMMENDED and SHOWSTOPPER
belong to the judgment step along with the Class 1 to 4 taxonomy. Putting them
in the app would quietly move judgment out of the reconciliation prompt into
software that has no basis for it, and the packet's whole claim is that it is
evidence rather than analysis.

What a topic gets instead is a measured state: no differences, differences
found, listen items, check flag, outline only. A flag outranks a difference,
because a flagged topic is a validation problem before it is a narration
question. A test asserts no verdict vocabulary appears in qa/results.py.

**Judgment stays manual.** The page hands over the packet and names the prompt
to use with it. Automating that is render.py, deliberately a separate task.

**Two detectors on one site are marked, not deduplicated.** Alignment and the
watchlist are independent, so when both land on the same timestamp that is a
reason to listen there first. On Course 11, six of eleven listen items are
corroborated that way. Collapsing them into one row would throw away the
strongest signal in the list.

**One home for telemetry.** Device, model, quantization, thread count, measured
decode rate and per topic decode times were showing in the live run view and
would have appeared again in the stats panel. The same numbers in two places
drift, and a progress view is not where anyone reads telemetry. The live view
now shows only what a person waiting needs: topics decoded of total, time
remaining, and results as they arrive. Everything else lives in the stats
panel, off by default, one click away on the Results tab.

**Memory is reported as machine information and labelled as such.** Total and
available system RAM, probed at display time, because the question people
actually ask is whether large-v3 will fit. Peak memory during a decode is not
measured anywhere, and the panel says so rather than letting these numbers be
read as describing the run.

Everything else in the panel was already recorded by a stage. Nothing is
computed for the display.

## D21. Device is excluded from the transcript cache key, precision is not

`ASRSettings.fingerprint` decides when a cached transcript is stale. It carries
the model, the compute type, the beam size, the VAD setting and the language.
It deliberately does not carry the device.

**Correction, added after D23 measured this.** The premise below is false. A
GPU decode and a CPU decode at the same precision agree on about 99.4 percent
of tokens, not all of them, and produce different discrepancy counts. The rule
that device stays out of the fingerprint still stands, but for a different and
weaker reason: re-decoding a whole course because someone changed machines
costs half an hour and buys a sub-one-percent difference that the listen list
and the judgment step already handle. It is a cost decision now, not an
identity claim. Anyone comparing two runs across devices should expect small
differences and should not read them as a change in the audio.

**Why device is out.** The same audio through the same engine at the same
precision produces the same transcript on CPU or GPU. Device affects speed, not
results. Someone who runs a course on CPU and later re-runs it on a machine
with a graphics card should get their cached transcripts back, not thirty
minutes of decoding they have already paid for. Adding device to the key
because "the GPU path is new and we should be safe" would throw away every
cached transcript on a machine that merely gained hardware, which is the exact
mistake the comment on that method exists to prevent.

**Why compute type is in.** A float16 run is a different numerical path from an
int8 run and can legitimately differ in what it hears, so changing precision
does invalidate a transcript, correctly. Device alone never does. The two look
similar from the UI, where both are "how it runs", and they are not the same
kind of change.

`ASRSettings` still carries `device`, so a run records what it used, and
`settings_from_course` coerces it through `effective_device` first. Recording a
requested `cuda` on a build that decodes on CPU would put a false claim in
every transcript's settings block.

The staleness rule itself is `transcript_is_current`, extracted from inside the
transcribe loop so it can be tested on its own. Five tests cover this: device
changes leave a transcript current; compute type, model, beam, VAD and language
changes do not; and a changed audio hash never does.

This is the decision `HANDOVER.md` points at when it says the GPU path is wired
but not enabled.

## D22. qa-setup: what it installs, what it only explains

Until now the install worked because the prerequisites had been put on two
machines by hand with the owner present. That is not a distribution.
`qa-setup` replaces the owner standing next to you.

**The line down the middle, and why it is where it is.** System software is
checked, explained and never installed: Python, git, ffmpeg, ffprobe and the
CUDA runtime. Local things are installed: the project's own virtual
environment, its Python packages, and the ASR model. The test is not how hard
the install is, it is whose machine changes. A venv and a model cache are this
project's business; anything that lands in Program Files or on the system PATH
is the user's. This extends D2 from ffmpeg to every prerequisite, and puts the
gates that were scattered through the pipeline in one place.

**Four states, kept distinct.** OK, MISSING, VERSION MISMATCH, NOT USABLE.
Collapsing them into "unavailable" would be the single worst thing this command
could do, because "not installed" and "installed but the wrong version" have
different fixes and a user told the wrong one will install something they
already have.

**The Python row catches the newer-is-worse trap.** A machine with 3.14 has a
newer Python and a broken install, because ctranslate2 publishes no wheels for
it. The row says so and points at D9, rather than reporting a version that
looks fine.

**The model download is deliberate.** Today the first transcription silently
fetches about three gigabytes, which is a poor thing to discover on a metered
connection. Setup states the size and asks. Declining is fine and says plainly
what will happen later.

**It ends with a smoke test, not a summary.** The whole pipeline runs on a
generated fixture with the tiny model, about two seconds, and reports pass or
fail. Installed and works are different claims and only the second one matters.
The fixture is generated rather than committed: it keeps binary media out of a
repository that must stay free of customer material, it satisfies D16 by
containing no course narration at all, and the generator works on any machine.

### The CUDA row, and a correction to the task that specified it

The row is built as specified: it asks ctranslate2 what it can actually use
rather than whether a card exists, reports VERSION MISMATCH separately from no
CUDA at all, and offers an additive remediation, the pip `nvidia-*-cu12`
packages that land in the virtual environment and change nothing system wide.
It never recommends uninstalling the old toolkit, because CUDA versions coexist
and something else on the machine may depend on it; removing an orphan is noted
as the user's own call. GPU is optional in every state and never blocks setup.

**Superseded in part by D23.** The reading below was itself too optimistic. The
probe asked ctranslate2 to enumerate devices and to list compute types, both of
which succeed on a machine with no cuBLAS and no cuDNN, so this row reported OK
on a laptop where a real decode then failed on the first kernel. The probe now
also checks that the CUDA support libraries can actually be loaded. What
follows was true about the toolkit and wrong about usability.

**The premise about this machine was wrong, and the correction matters.** The
task described a desktop with a stale CUDA 11.0 toolkit on PATH that
ctranslate2 4.x cannot use, and set that up as the live fixture for this row.
This machine is not that. It is a laptop with an RTX 3060, driver 616.56, and:

    no CUDA toolkit installed, no CUDA_PATH, nothing CUDA on PATH,
    no nvidia-* packages in the venv

and a real `WhisperModel(device="cuda", compute_type="float16")` load
**succeeds**. The driver supplies what ctranslate2 4.8.1 needs. The correct
reading of this machine is CUDA OK, which is what the check reports, and it
agrees with the ground truth load.

So the mismatch path could not be validated against this hardware without
inventing a fault. It is validated by injection instead: the tests drive the
row with a broken probe plus an old toolkit and assert VERSION MISMATCH, an
additive pip remediation, and that every mention of uninstalling is a
prohibition rather than advice. That is a weaker proof than a live failure
would have been, and it is the strongest available here. If a machine with the
CUDA 11 situation turns up, run `qa-setup --check` on it: that is the
confirmation still outstanding.

## D23. The device selector, and what measuring it actually showed

The web interface had a device selector that probed honestly and then did
nothing: transcription ran on CPU whatever was chosen. It now decodes where it
was told to, on the CLI as `--device {cpu,cuda,auto}` and in the interface,
built from the same settings so the two front doors stay one engine. Precision
follows the device, float16 on a card that supports it and int8 on CPU, and the
precision that actually ran is recorded because per D21 it is in the cache key.

### Falling back without losing the run

The probe catches a GPU that cannot work. It cannot catch one that works until
it is asked to do something, and that case turned up live during this work: on
this laptop the model loaded on CUDA and the first kernel failed with
`cublas64_12.dll is not found`.

So a GPU failure during a topic falls back to CPU, finishes that topic, and
finishes the course on CPU. It does not retry the GPU: thrashing between
devices is how a run ends up slower than either device alone. The GPU model is
released first, because the usual reason for the failure is that the card has
just run out of memory.

The fallback is recorded in the transcripts index, the job status, the stats
panel and the packet header, which reads "requested cuda, decoded on cpu from
topic 03 after: <reason>". A silent fallback would be a lie about what produced
the findings, which is worse than the failure it hides.

### The equivalence claim was wrong, and the measurement says so

The interface and D21 both claimed device affects speed and not results. That
had never been measured. It has now, on Course 11, from a forced clean state
each time.

    run                     decode      rate     discrepancies  coverage
    CPU int8               32.9 min    2.30x          29         99.50%
    GPU float16             7.8 min    9.67x          33         99.35%
    GPU int8                9.9 min    7.67x          32         99.48%

    CPU int8 vs GPU float16:  99.328% token agreement, 6 of 13 topics identical
    CPU int8 vs GPU int8:     99.418% token agreement, 4 of 13 topics identical

**The claim does not hold.** Nor is it only a precision effect: the control run,
GPU at int8, holds precision constant and still disagrees with CPU int8 on nine
of thirteen topics. The device itself changes the output.

What changed, concretely. GPU float16 found a whole-sentence deletion in topic
02 that CPU did not, and two extra substitutions in topic 08. CPU found four
differences in topic 09 that GPU did not. The watchlist saw SIEM misheard at
three sites on CPU and four on GPU, with topic 11 reading "some" at p 0.282 on
CPU and "SIM" at p 0.163 plus another "SIM." at p 0.994 on GPU. Check flags were
identical: topic 01 only, on every run.

Two notes on reading those numbers honestly. The differences are small in
aggregate, about half a percent of tokens, and they are real rather than noise
in the metric: they change the discrepancy count and the listen list. And the
first metric I wrote, a positional word-by-word overlap, reported 74 percent
and was wrong; one inserted word shifts every later position. The alignment
based figure above is the honest one.

So the wording everywhere is now "device may affect decode precision; findings
are re-verified", carried in one constant, `qa.device.DEVICE_NOTE`, so it
cannot drift between pages. The stronger sentence is not recoverable by
argument; it was tested and it failed.

### Addendum: the counterexample, and why the wording says "may"

D25 concluded that findings are robust to the device. That is true in
aggregate and it is not a guarantee, and the difference matters enough to name
the case that shows it.

**In Course 11, GPU float16 caught a whole-sentence deletion in topic 02 that
CPU int8 missed.** Not a confidence that moved, not a token spelt differently:
a sentence the script contains, reported absent by one device and matched by the
other. If a course had been run on CPU alone, that finding would not exist.

This is why the wording is "device may affect decode precision; findings are
re-verified" rather than anything stronger in either direction. Findings are
usually stable; they are not guaranteed to be. Anyone who reads D25 as
permission to treat the two devices as interchangeable should read this
paragraph first.

The Course 10 pair measured on 2026-09-01 says the same thing more quietly. Same
audio, same model, same day: CPU int8 found 3 discrepancies and GPU float16
found 4. The two the devices share are at high confidence and are the real
defects; the rest is decode noise. That pair is the evidence behind D27, which
proposes using the disagreement rather than merely tolerating it.

**The speedup is 4.2x at float16 and 3.3x at int8** on this laptop, an RTX
3060. A 75.7 minute course decodes in 7.8 minutes rather than 32.9. That is the
first real number behind any "handful of minutes" expectation.

### The pip remediation did not work until it was made to

D22 promised that `nvidia-cublas-cu12` and `nvidia-cudnn-cu12` land in the
virtual environment and are "found ahead of the older libraries". Installing
them did not fix the decode. The wheels put their libraries inside
site-packages, and `os.add_dll_directory` only helps loaders that pass the
search flags; ctranslate2 loads cuBLAS by bare name, which resolves against
PATH. Both are needed. `enable_bundled_cuda` now does both and is called before
any CUDA model is loaded. Without it the remediation installs exactly the right
files and the run still dies on the first kernel, which is the most
frustrating possible outcome for the person following the instructions.

## D24. The four CUDA states, and which have been seen live

The selector is only proven "for anyone" when each state has been seen on real
hardware rather than constructed in a test. Tracking that honestly, because an
injected pass is weaker evidence than a live one and the difference is easy to
forget.

| State | Status | What confirmed it, or what would |
|---|---|---|
| CUDA OK | **Confirmed live** on this laptop, RTX 3060, driver 616.56, after installing `nvidia-cublas-cu12` and `nvidia-cudnn-cu12` into the venv. A full Course 11 decode ran on GPU at 9.67x realtime. | Done. |
| GPU PRESENT BUT NOT USABLE | **Confirmed live** on this same laptop before that install: the card enumerated, compute types listed, and the decode failed with `cublas64_12.dll is not found`. This is what prompted the probe to start checking library loadability. | Done, and it was found by running rather than by reasoning. |
| VERSION MISMATCH | **Injection only.** No machine here has an old CUDA toolkit. | `qa-setup --check` on the owner's desktop with its stale CUDA 11.0, then the check's own remediation, then a green rerun. |
| NO GPU | **Confirmed live** on this laptop 2026-09-01, by running a full Course 10 through `qa-web` with `CUDA_VISIBLE_DEVICES=-1` set in the launching shell. See below for what that does and does not prove. | Done, with one caveat. |

Three of the four are now live, and one of those three was not in the original
plan at all: the "present but not usable" state existed on the development
machine the whole time and was being reported as OK.

### How NO GPU was confirmed, and what the method is worth

`CUDA_VISIBLE_DEVICES=-1` in the shell that launches `qa-web` makes the runtime
enumerate zero devices, which is the same thing the probe sees on a machine with
no card. The whole path was exercised, end to end, with no code changed and no
test double anywhere:

- the probe reported MISSING with the optional wording, naming the reason
- the sidebar and the run form both showed GPU unavailable, with that reason
- the run completed on CPU with no intervention from the operator
- the packet header read "requested cpu, decoded on cpu"
- coverage 99.94 percent, 3 discrepancies, which is the CPU baseline

**What this proves and what it does not.** It proves the probe, the selector,
the fallback and the packet's own account of itself all behave correctly when
the runtime reports no CUDA device. It does not prove the behaviour on a machine
that has never had CUDA installed: there, the failure could be an import error
or a missing driver library rather than a device count of zero, and those take
different branches. A bare CPU-only laptop is still the real test and is
scheduled for the colleague pilot. Recording the method here so that a later
reader does not mistake a simulated state for a bare machine.

VERSION MISMATCH remains injection only.

## D25. What the device change did to the known answer tests

Switching the default to `auto`, which selects GPU on this machine, re-decoded
Course 10 and gave the golden tests their first cross-device workout. Of about
twenty five assertions, **exactly one changed**, and it was not a finding.

Listen item L7 is still reported, at the same timestamp, with the same script
text and the same transcript text, as the same substitution. Its ASR confidence
moved from 0.845 on CPU int8 to 0.923 on GPU float16.

Everything that carries meaning survived: L5 still answers that file 01 does
not end with the Topic 10 teaser, the tail still matches on every scripted
topic, there are still no deletions anywhere, coverage is still above 99
percent on every topic, the auto mapper still reproduces the slide map, and the
audio conventions are unchanged.

The test now asserts what the claim actually is, that the site is well clear of
the listen item floor and therefore a corroborated finding rather than an
unsure decode, rather than pinning a number that depends on which chip ran it.

This is the most useful single result in this whole piece of work. D23 shows
the two devices disagree on about half a percent of tokens; D25 shows what that
does to conclusions, which is almost nothing. Findings are robust to the device;
the numbers underneath them are not, and any future test that pins a confidence,
a word count or a coverage figure to three decimal places will break the first
time someone runs it on other hardware.

## D26. Script sources: what a course's script is, and what a topic's state is

The pipeline assumed one shape of delivery: a PowerPoint storyboard whose
speaker notes are the narration, one topic per delivered audio file, and an mp4
among the mp3s meaning a demo whose storyboard is an outline. Every step of that
chain is now known to be wrong, and each was wrong in a way that produced a
confident false answer rather than an error.

**File type carries no information.** Topics normally arrive as mp4 and need
demux, on both project types. The ingest module warned when a VENDOR course
arrived as video; it fired on every correct delivery. A check that fires on the
correct case is worse than no check, because people learn to scroll past it.
The warning is gone and `expected_kind` now returns "any", kept only so a reader
of an old `ingest.json` can see the claim was withdrawn rather than quietly
changed.

**A CGT course has no PowerPoint at all.** Its script is a Word document in the
BUS Writing Template. The old code would have found no `.pptx`, halted, and told
the operator to go and find a storyboard that does not exist.

**"Demo" and "unscripted" are different facts.** A demo may be fully scripted
(CGT always is), outlined in the deck (usually VENDOR), scripted in a freeform
document of its own (occasionally VENDOR), or not scripted anywhere.

So two separate concepts, deliberately not one:

    source   a property of the course:  pptx | docx_bus
    state    a property of a topic:     verbatim | outline | freeform | none

`course.yaml` gains `script_source`, defaulted from `project_type` and stated
rather than inferred, and a `topics` mapping for per-topic states.
`unscripted_topics` is unchanged and still means outline-only; it is the
shortest way to say the common VENDOR case and nothing here deprecates it.

The script stage became a dispatcher. Every extractor emits the same per-topic
structure, so `align.py`, `checks.py`, `artifacts.py` and `packet.py` are
unchanged by any of this. `freeform` and `none` are applied as an overlay after
the course-level extractor runs, so both extractors get them and neither knows
about the other.

### What the BUS extractor reads, and what it refuses to read

Verified against a real delivery rather than assumed, and the assertions are in
`tests/test_bus_template.py`:

- **The SCRIPT column only.** OST is on-screen bullet text that nobody reads
  aloud. Including it would produce a wall of false deletions in every topic of
  every CGT course. The evidence that none leaks in is that every block's
  extracted word count equals the count the author wrote in its own metadata
  row, on all eleven blocks of the reference document.
- **Scene headers are stripped from the alignment text and kept as tagged
  non-narration spans**, with the position they held. They are not narrated, so
  leaving them in would report each one as a deletion; deleting them outright
  would mean a header the voice did read simply disappeared. Kept as spans, a
  voiced header surfaces as an insertion, which is the correct answer.
- **Interactivity placeholders are dropped and reported.** Two independent
  signals, either sufficient: the template's own placeholder sentence, and a
  block under 20 words whose title says interactivity. Both fire on the
  reference document's topic 9. Dropping one is a silent decision about how many
  topics a course has and shifts every later block onto the wrong audio file, so
  the packet lists what was dropped and why.
- **Blocks map to delivered files by order, never by the number in the TOPIC
  heading**, because the heading numbers include the placeholder and the files
  do not. A count mismatch halts with the same evidence contract as the pptx
  mapper.
- **The COURSE ID cell is cross-checked against the code from the filenames**,
  after dropping the locale segment the filenames carry and the cell does not. A
  mismatch halts: aligning a course against another course's script would report
  every topic as a total narration failure.
- **The Pronunciation Guide feeds `qa-terms`** with the author's stated
  pronunciation attached, which is the one thing that command otherwise cannot
  know. Empty in the reference document, and the extractor says so rather than
  inventing rows.
- **The author's own word count and estimated duration are carried to the
  packet and are not a threshold.** They are a source-side pacing reference: a
  number a human wrote down before anything was recorded. The pace check stays
  what D6 made it, a ratio against the script the file was actually read from.
  A threshold built from these would be a threshold built from an estimate.
  They also happen to be the cleanest evidence that the SCRIPT-only rule works:
  on the reference document all eleven blocks match exactly, and the packet
  shows the difference where they do not.

### The two checks that need no script

A topic whose state is `none` is not skipped. It runs demux, transcription and
artifacts as normal and the packet carries its full timestamped transcript, but
everything alignment normally catches has to come from somewhere else or not at
all. Two detectors in `qa/transcript_checks.py` are what a transcript alone can
honestly support. Both produce listen items and neither can produce a defect,
because with no script there is nothing to be wrong against.

**Voiced symbols.** A synthetic voice reading `project_plan` literally says
"project underscore plan", and the transcript then contains a perfectly ordinary
word that is not a word. Course 10's topic 09 does this fourteen times and the
packet had nowhere to say so. Reported grouped by term with every timestamp, so
one listen settles all fourteen. Run on scripted topics too: it costs nothing,
and a script containing an identifier says nothing about whether reading it out
that way was intended. Never a defect, because narrators do say "underscore" on
purpose.

**Unverifiable boundary duplications.** The scripted path suppresses ASR
segment-boundary duplications outright, and that is safe only because alignment
has already proved the script has one word there. With no script that proof does
not exist, so the same candidates are listed under their own heading instead of
dropped. Every candidate is listed, not only the ones whose second copy decoded
badly: Course 10's demo has one at p 0.958, and a confidence filter would have
dropped it with nothing left that could find it again. Confidence is reported
per site so a reader can triage by it, which is what it is good for.

### The SaaS family, and the rule an equivalence has to follow

GPU decode wrote "SAS" for "SaaS" at two sites in Course 10 topic 04 and
reported them as substitutions. The narrator said "sass" both times.
`EQUIVALENCES` now folds `SAS`, `IAS` and `PAS` into `SaaS`, `IaaS` and `PaaS`;
casing is already folded before the table is consulted, so one row covers each.

The standing rule this establishes: **an equivalence that absorbs a difference
must be paired with a watchlist entry for the same term.** Absorbing it is
correct, because the difference is orthography rather than speech, but it also
means alignment will never mention that term again. Without the watchlist entry
the pipeline has quietly stopped looking at a term it used to look at. All three
are now on the `spisccc26` watchlist for exactly that reason.

The predicted effect was that Course 10's discrepancy count would fall from 4 to
2. It fell to 3, and the missing one is worth recording. One of the two SAS
sites had been fused into a single substitution row together with a separate
low-confidence insertion beside it. Removing the SaaS half leaves that insertion
standing on its own, correctly, as the listen item it always was. So the
equivalence did not only remove noise; it un-fused a real listen item that the
noise had been hiding. Both SaaS sites are gone from the packet, which was the
substantive claim.

## D27. Two devices as two instruments, not one instrument twice

**Recorded so the idea and its evidence survive. Not built.**

D23 measured CPU and GPU disagreeing on about half a percent of tokens, and D25
showed that almost nothing a person acts on moves as a result. The natural
reading is that the disagreement is a nuisance. There is another reading.

On a GPU machine a second decode costs minutes: Course 10 is 53 minutes of audio
that decodes in about 5.5. Two devices are two independent instruments in
exactly the sense the original two-transcriber design wanted and never got. A
site both report is a defect. A site only one reports is a listen item. That is
the old triangulation rebuilt on instruments that, unlike two LLM listeners,
neither paraphrase nor truncate nor silently skip a file.

The evidence is already in hand, and it got cleaner when it was re-measured.

The first pair, before D26's SaaS equivalence, was CPU int8 at 3 discrepancies
and GPU float16 at 4, sharing 2. Removing the SaaS noise from the GPU side left
this, on the same audio, the same model and the same afternoon:

    site                                          CPU int8   GPU float16
    topic 04  "provides a" heard as "provide the"  p 0.845     p 0.923
    topic 05  "and" heard as "in"                  p 0.959     p 0.959
    topic 04  "element." inserted                     -        p 0.054
    topic 06  "managed" heard as "manage"          p 0.345        -

**Both devices find three. They agree on two, and those two are the only ones
either device is confident about.** Each device also finds one site the other
does not, and both of those are decode noise by the instrument's own account:
p 0.054 and p 0.345, well under the 0.6 floor.

That is the whole argument in four rows. A site both report is a defect. A site
one reports is a listen item, and here the confidence says so independently,
which is the check on the check. The pair separated signal from noise without a
human having to guess which was which.

Course 11 gives the counterexample that makes it worth doing rather than merely
interesting: GPU float16 caught a whole-sentence deletion in topic 02 that CPU
int8 missed, at high confidence on the side that saw it. Agreement is not the
only useful outcome of running two instruments; sometimes one of them is simply
right and the other is not. See the addendum to D23.

Against building it now: it doubles decode time on the only machine where that
is cheap, it needs a second cache slot per topic, and the packet would need a
third column throughout. None of that is hard; it is simply not the next thing.
The reason to write it down is that the evidence for it is scattered across two
runs on one afternoon, and in six months nobody will reconstruct it.

## D28. Where finished packets go, and why they are never overwritten

Working files and finished output had one home between them, inside the course
folder in `%LOCALAPPDATA%`. That is right for the working files and wrong for
the packets.

Working files stay where they are: copied media, demuxed audio, the transcript
cache and every intermediate live in `qa_work/` under the library. They are
large, they are regenerable, and nobody opens them by hand.

Finished packets move to an output folder, defaulting to `Documents\audio-qa`
and settable in the sidebar. Two reasons, and the second is the important one.
A person who has just run a course wants to attach the packet to a chat, and
asking them to navigate into `AppData\Local` to find it is a bad answer.

And packets are named by course, timestamp and device, and **never overwritten**:

    it_spisccc26_10_enus_2026-09-01_1441_gpu-float16.md

so the output folder is the run history. A before-fix packet and an after-fix
packet sit side by side, and a CPU packet sits next to a GPU packet of the same
course, which is what makes a claim like D23's checkable by anyone rather than
only by whoever happened to run both that afternoon. The old naming was course
plus date, so a second run on the same day overwrote the first silently, which
is precisely the case where comparing them matters most.
