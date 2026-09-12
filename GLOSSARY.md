# Glossary

The words this tool uses, in alphabetical order, each explained in a few
sentences. The Docs tab renders this file, and the hover marks in the
interface point here when the short answer beside a column is not enough.
Nothing here is a rule; the rules and the measurements behind them are in
`DECISIONS.md`, and the entry that set a threshold is named where one applies.

## Alignment

The align stage. It normalizes the script and the transcript the same way,
then compares them word by word. Every difference the tool reports comes from
here, and so do the listen items it raises for low confidence sites and
identifiers. Only a topic with a verbatim script can be aligned.

## Artifacts

The artifacts stage, and what it finds. It measures the audio signal alone:
clipping, silence inside the narration, a file that is silent throughout, and
an abrupt end. Everything is measured against the course's own conventions,
so a pause the whole course makes between slides is house style rather than
a finding. The "audio" column of the checks table lists what it heard.

## ASR

Automatic speech recognition: the transcriber. Here it is faster-whisper
running the Whisper large-v3 model, or medium when speed matters more than
accuracy. It writes spelling, never pronunciation: it writes "IaaS" whether
the voice said "eye-as" or something wrong. See "What it measures, and what
it does not" in `HANDOVER.md`.

## BUS Writing Template

The Word document format a CGT course's script arrives in. Every topic of a
BUS script is verbatim, so a CGT course has nothing to set per topic at
Intake.

## Cached

A topic state during a run. The audio file has not changed since an earlier
run, so that run's transcript is reused rather than decoded again. Reuse is
keyed on the file's hash and the compute type, not the device, for the
reasons in D21.

## CGT

One of the two project types. A CGT course's script is the Word document in
the BUS Writing Template, and its findings route to a remediation plan.

## Checks

The checks stage. It rolls each topic up into one row: coverage, pace, the
tail sentence, the mapping guard, the audio findings, and the flags. The
checks table on Results is this stage's output read back.

## Class 1 to 4

The defect taxonomy the judgment step applies to a difference. This tool
never assigns a class; the reconciliation prompt does, from the packet.

## Compute type

The numeric precision the transcriber runs at: float16 on a GPU, int8 on a
CPU. Also called quantization. The two do not produce identical transcripts,
which is why the compute type is part of the transcript cache key and the
device is not. D21 and D23 have the measurements.

## Confidence

The transcriber's own estimate, between 0 and 1, that it heard a word
correctly. Every transcribed word carries one, and a listen item shows the
lowest confidence among the words at its site.

**Why it matters.** It is the reason most listen items exist. The floor is
0.6: a site whose least certain word falls below it is listed because the
decode itself is in doubt, and a difference there may be the transcriber's
mistake rather than the narrator's. A difference at high confidence is the
opposite case: the transcriber was sure of what it heard, so the words on the
two sides really do differ. Reading the number tells you which kind of
listening a row needs. A low number asks "did the transcriber mishear?", which
one listen settles. A high number, when it appears on the listen list at all,
is there for another reason, usually an identifier whose voicing cannot be
judged on paper.

**What it does not measure.** Pronunciation. A confident "IaaS" means the
transcriber recognized the word, not that the voice said it correctly. The
watchlist's LOW CONFIDENCE label is this same threshold applied at a watched
term, and MATCH there is spelling, not pronunciation.

## Corroborated

Two independent detectors landed on the same spot: the same topic and the same
timestamp to a tenth of a second, from different kinds of check. Marked "++"
in the "found by" column of the listen list. Alignment and the watchlist do
not consult each other, so their agreement is a reason to listen there first.

## Course code

The identifier derived from the delivered filenames, such as
`it_spisccc26_10_enus`: learning path, course number and language. It names
the course in the library and in every packet filename.

## Coverage

The share of the script's words that the transcript matched. Below 97% the
checks stage raises LOW COVERAGE. Below 85% it raises PROBABLE MAPPING ERROR
instead, because a narrator skipping a third of a script is less likely than
the topic having been mapped to the wrong slides. Unscripted topics have no
coverage.

## Delivery

The files as they arrived: every narration file and the script document.
Intake copies them into the library and verifies each copy by hash. The
originals are left where they were unless you ask to delete them.

## Demux

Pulling the audio track out of a video container. The ingest stage does it,
so everything downstream is audio only and does not care what format the
delivery came in.

## Device

Where the decode runs: CPU, or a CUDA GPU. GPU is roughly four times faster.
A GPU that fails under load falls back to CPU, finishes the course, and says
so in the run record, the stats panel and the packet header.

## Difference

A place where the script and the transcript disagree after both have been
normalized: a substitution, a deletion or an insertion. Also called a
discrepancy in the pipeline's files. A difference is a measurement, not a
verdict; the judgment step decides which ones are defects.

## Flag

A label the checks stage puts on a topic when a validation check fails: PACE
BELOW SCRIPT or PACE ABOVE SCRIPT (outside 0.85 to 1.15 of the rate the
script implies), PACE BELOW COURSE or PACE ABOVE COURSE (an unscripted topic
outside 0.70 to 1.40 of the course median), LOW COVERAGE, PROBABLE MAPPING
ERROR, TAIL SENTENCE NOT MATCHED, LONG TRAILING SILENCE, DECODER STOPPED
EARLY, and AUDIO ARTIFACT for a high severity audio finding. Read a flag
before reading the topic's differences: a mapping error makes every
difference beneath it noise.

## Freeform

A topic scripted in a document of its own, outside the storyboard. The
occasional vendor demo arrives this way. Chosen per topic at Intake.

## Identifier

A URL, a path, an address, or a token that looks like one. Whether it was
voiced correctly cannot be judged on paper, so any difference at an
identifier is a listen item regardless of confidence.

## Ingest

The first stage. It identifies each delivered file by its header rather than
its extension, and demuxes video containers to audio.

## Intake

The tab where a course comes in. It reads the delivered filenames, derives
the course, its topics and its code, and asks only what a filename cannot
answer: VENDOR or CGT, which topics are not verbatim, and who is reviewing.

## Judgment step

The human step after a run. Open a Claude chat, paste
`prompts/reconciliation_v2.md`, attach the packet, and it returns the findings
report with verdicts (CLEAN, FIX RECOMMENDED, SHOWSTOPPER), the Class 1 to 4
taxonomy, and the edit sheet or remediation plan. Nothing in this app judges;
it measures and hands over evidence.

## Learning path

The certification journey a course belongs to, and the first part of the
course code. Watchlists are kept per learning path, because acronyms are
shared across one.

## Library

Where courses live: outside the repository, so nothing customer-owned can be
committed by accident. Its location is shown in the sidebar. Each course is a
folder holding the delivered files, `course.yaml`, the working files under
`qa_work/`, and the packet index under `qa_out/`.

## Listen item

One place a person has to use their ears, because the pipeline has taken it
as far as paper goes. There are five sources: an alignment difference at low
confidence or at an identifier; a voiced symbol; an unverifiable duplication;
a pronunciation candidate from the watchlist; and a whole topic that has no
verbatim script. The listen list on Results is all of them, merged and sorted
by topic and time.

## Listen list

The listen items for a course, and the first thing on the Results tab,
because it is the only part of the output that needs a human. Nothing
downstream settles it.

## MATCH, LOW CONFIDENCE, MISHEARD

The three things the watchlist can say about one site of one watched term.
MATCH: the transcriber wrote the expected spelling. LOW CONFIDENCE: it wrote
the expected spelling but was not sure of it. MISHEARD: it wrote something
else. The last two become listen items. A MATCH is orthography and clears
nothing about pronunciation.

## Model

Which Whisper model the transcriber loads. large-v3 is the default and the
one every measurement in `DECISIONS.md` was made with; medium is faster and
rougher, for tuning.

## No script

A topic state: nothing in the delivery says what this topic should have said.
It is still transcribed and measured for audio, but it cannot be aligned, and
the whole file is a listen item.

## Outline only

A topic state: the storyboard notes for this topic are an outline rather than
word-for-word narration. It is transcribed and measured, but word-level
comparison would report the whole outline as missing, so it is skipped and
the whole file is a listen item instead. Marked at Intake; marking a verbatim
topic as outline only hides real defects. D26 defines the states.

## Pace

Words per minute in the transcript, as a ratio against the rate the script
implies for that topic. A ratio rather than an absolute floor, because a
voice that runs at 115 words per minute is not slow if its script does too.
Flagged outside 0.85 to 1.15; unscripted topics are compared to the course
median instead, with a wider band.

## Packet

The evidence file a run writes for the judgment step: one Markdown file and a
JSON twin, named `<course code>_<date>_<time>_<device>` and never overwritten,
so the packet folder is the run history. D28 says why.

## Packet folder

Where packets land. Separate from the library, because a packet is a thing a
person opens five minutes later rather than a working file. Shown in the
sidebar; `Documents\audio-qa` by default.

## Pronunciation candidate

A listen item raised by the watchlist: a watched term whose site came back
LOW CONFIDENCE or MISHEARD. It is a reason to listen, not a defect, and the
watchlist never certifies a pronunciation.

## Realtime factor

Minutes of audio decoded per minute of decoding. Shown in the stats panel
and used to estimate the time a run has left, from this machine's own
measured rate rather than an assumption.

## Reclaim

Freeing disk space from the Storage tab. Scratch audio rebuilds in seconds
and costs nothing to remove. Delivered media frees most of a course and costs
the ability to run it until the delivery is downloaded again. Findings and
packets are never removed there; D31 says why.

## Reviewer

The name entered at Intake. It is recorded in the course's `course.yaml`,
carried into every run, and printed in the packet header, so a finding can be
traced to whoever ran it.

## Run

One execution of the pipeline on one course, started from Runs or from
`qa-run`. It is a separate process with its own id, so closing the app does
not stop it, and only one run per course can be in progress at a time.

## Scratch audio

The wav the ingest stage demuxes from each delivered file, under
`qa_work/audio/`. A working copy: it rebuilds in seconds, and the course
stays runnable without it.

## Script source

Which document is read as the script. A VENDOR course's script is the speaker
notes of the PowerPoint storyboard; a CGT course's is the Word document in the
BUS Writing Template; a freeform topic's is a document of its own. The
project type decides, so a wrong project type aligns the course against the
wrong text.

## Stage

One of the eight steps a run takes, in order: ingest, config, script,
transcribe, align, artifacts, checks, packet. A stage whose output already
exists is skipped, so a rerun redoes only what went stale. Transcribe is the
only slow one.

## Storyboard

The PowerPoint deck a VENDOR course arrives with. Its speaker notes are the
script, and the "from" column of the checks table gives the slides each topic
was read from.

## Suppressed duplication

The transcriber decodes in segments, and a phrase that straddles a segment
seam is sometimes written twice. When the script shows it was said once, the
second copy is removed as an engine artifact and counted in the "suppressed"
column rather than as a difference.

## Telemetry

What a run recorded about itself and this machine: engine, model, compute
type, device, thread count, decode rate, per topic decode times, quality
signals and the course's measured audio conventions. All of it lives in the
"Stats for nerds" panel on Results, and nowhere else.

## Topic

One narration file, numbered from its filename. A course is a set of topics;
every table in the interface has one row per topic.

## Tour

The six-step walkthrough offered on the first launch on a machine, and
reachable afterwards from the "Tour" link in the sidebar.

## Transcript

The transcriber's output for one topic: the words it heard, each with a
timestamp and a confidence. Kept under `qa_work/` as JSON and reused on the
next run if the audio has not changed.

## Unverifiable duplication

A phrase heard twice across a segment seam in a topic that has no script to
check it against. With no proof that it is an engine artifact, it is listed
for a listen rather than suppressed.

## VENDOR

One of the two project types. A VENDOR course's script is the storyboard, and
its findings route to a vendor edit sheet.

## Verbatim

A topic whose script is word-for-word narration. Only verbatim topics are
aligned; every topic of a CGT course is verbatim, and every topic of a VENDOR
course is unless marked otherwise at Intake.

## Voiced symbol

A symbol or URL part read aloud as a word: underscore, hyphen, dash, slash,
backslash, colon, asterisk, http, https, www. A synthetic voice does this
with an identifier; a narrator sometimes does it on purpose. One row per term
per topic, with every timestamp, so one listen settles all of them.

## Watchlist

A list of terms, one per learning path, whose every site is checked whether
or not alignment had anything to say about it. Each site comes back MATCH,
LOW CONFIDENCE or MISHEARD. The watchlist detects likely mispronunciation and
routes it to a person; it never certifies one, and a clean watchlist clears
nothing. See "Pronunciation watchlist" in `README.md`.
