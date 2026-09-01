# Decision log

Amendments to Audio_QA_Pipeline_Build_Spec_v1.md, agreed during the build.
The spec file is left as written; this file is what the code follows where the
two differ.

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
