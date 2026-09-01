# Build Spec: Synthetic Voice QA Pipeline (v1)

Owner: Ryan Mount, ACIS, Skillsoft. Purpose: replace the manual two-LLM transcription QA workflow with a local pipeline. Drop a course folder in, get a reconciliation packet out, feed the packet to Claude for judgment, receive a findings report. Constraints: zero budget, everything runs locally on a standard work laptop (CPU only), all dependencies free open source, audio never leaves the machine. The only external step is pasting the final packet into Claude chat, which mirrors the current manual workflow.

## Background

Current process: two LLM chat sessions (ChatGPT, Gemini) transcribe TTS narration audio; a Claude session reconciles both transcripts against the storyboard script and produces a findings report. A completed run (Course 10, it_spisccc26_10_enus_, 2026-08-25) proved the design works but exposed the instruments: one LLM silently skipped a file, the other truncated 4 of 9 file tails and paraphrased heavily. This pipeline replaces LLM listeners with deterministic ASR and code, reserving the LLM for judgment only.

## Repo layout

    audio-qa/
      pyproject.toml            (uv-managed; pipx-installable entry point: qa-run)
      qa/
        cli.py                  Module 1
        config.py               Module 2
        extract_script.py       Module 3
        transcribe.py           Module 4
        artifacts.py            Module 5
        normalize.py            Module 6
        align.py                Module 7
        checks.py               Module 8
        packet.py               Module 9
        render.py               Module 10 (phase 2, stub for now)
      prompts/
        reconciliation_v2.md    (judgment prompt template, packet-aware)
      tests/
        course10/               (known-answer test data, see Testing)

## Course folder convention (input)

    <course_dir>/
      course.yaml               required
      *.pptx                    exactly one storyboard
      audio/*.mp3               narration files, one per topic

course.yaml:

    course_number: "10"
    project_type: VENDOR        # or CGT
    course_code: it_spisccc26_10_enus
    # optional overrides:
    # slide_map: {"01": [2,3], "02": [4,8], ...}   topic -> [first_slide, last_slide]
    # unscripted_topics: ["09_01"]                  demo files with outline-only notes

Pipeline writes all intermediates to <course_dir>/qa_work/ and final outputs to <course_dir>/qa_out/.

## Modules

### 1. cli.py
Entry point. `qa-run <course_dir>` runs stages in order, skipping any stage whose output already exists unless --force. `qa-run --stage align <course_dir>` reruns one stage. Prints a one-line status per stage and a summary table at the end. Fail loudly and specifically: a missing storyboard or an mp3/topic mismatch stops the run with a clear message.

### 2. config.py
Load and validate course.yaml. Discover mp3s, parse topic numbers from filenames (pattern: <course_code>_<topic>.mp3, where topic may be like 01 or 09_01). Validate one storyboard pptx exists. Output: qa_work/manifest.json listing every file, topic id, and audio duration (via soundfile or librosa).

### 3. extract_script.py
python-pptx. Pull speaker notes per slide. Map slides to topics: use slide_map from course.yaml when present; otherwise auto-map by narration continuity (a slide whose notes begin with "In this video" or "In this demonstration" starts a new topic; the course-overview slides before the first such marker are topic 01; trailing summary slides are the final topic). Slides with empty notes or template instructions are excluded. Vertical-tab characters (\x0b) in notes are paragraph breaks, not sentence ends. Output: qa_work/script.json:

    {"topics": [{"topic": "02", "slides": [4,8], "scripted": true,
                 "sentences": ["...", "..."]}]}

Sentence-split with a simple rule set (period/question/exclamation + space + capital), preserving original text exactly. Mark topics listed in unscripted_topics with "scripted": false and keep their notes as outline text.

### 4. transcribe.py
faster-whisper (CTranslate2 backend, CPU, model large-v3 by default, configurable to medium for speed). Enable built-in silero VAD. Emit word-level timestamps. One file at a time, no shared state between files. Output: qa_work/transcript_<topic>.json:

    {"topic": "02", "duration_s": 412.3, "model": "large-v3",
     "words": [{"w": "Cloud", "start": 0.42, "end": 0.68, "p": 0.94}, ...],
     "segments": [{"text": "...", "start": 0.42, "end": 6.10}]}

Record any decode anomalies (empty segments, repeated n-grams, language flips) in an "anomalies" list; these feed checks.py. Design the module behind a small interface (transcribe(path) -> Transcript) so a second engine can be added later as a second instrument.

### 5. artifacts.py
librosa/pydub per file: leading/trailing silence length, internal silences > 1.5 s with timestamps, clipping detection (sample peaks at or near full scale), abrupt-end detection (no energy decay in final 200 ms). Output: qa_work/artifacts_<topic>.json with a findings list, each with type, timestamp, severity hint.

### 6. normalize.py
Shared token normalization used by align.py on BOTH script and transcript tokens: lowercase; strip punctuation; expand common spoken forms (numbers to words via num2words); collapse spelled-out acronym variants ("a i", "a-i" -> "ai"); treat "life cycle"/"lifecycle" and "data set"/"dataset" style compounds as equal via a small equivalence table that lives in one place and is easy to extend. Normalization must be a pure function; keep the original tokens alongside normalized ones so reports always quote originals.

### 7. align.py
Per scripted topic: align normalized script tokens against normalized transcript tokens (rapidfuzz or a plain difflib SequenceMatcher on token lists is sufficient at this scale). Emit each discrepancy with type (insertion, deletion, substitution), the original script text, the original transcript text, and the audio timestamp range from the transcript words. Merge adjacent single-word ops into spans. Attach 1 sentence of script context on each side. For unscripted topics, skip alignment and emit the full transcript with timestamps for the packet. Output: qa_work/discrepancies_<topic>.json.

### 8. checks.py
Per topic, deterministic versions of the self-reporting attestations: words per minute (flag < 120 as POSSIBLE TRUNCATION, though with ASR this should never fire; it guards against decode failures), script coverage percent (share of script tokens matched), transcript tail check (last script sentence matched yes/no), sentence counts both sides, ASR anomaly rollup, artifact rollup. Output: qa_work/checks.json, one row per topic.

### 9. packet.py
Assemble qa_out/reconciliation_packet_<course>_<date>.md. Human-readable markdown a person drags into Claude chat. Contents in order: header (course, date, project type, model versions, topic-to-slide map), checks table, then per topic: the discrepancy list (script says / voice said / timestamp), artifact findings, and for unscripted topics the outline plus full transcript. Also write the same data as packet.json for phase 2. Keep the packet tight; it should typically run 2 to 6 pages, not a transcript dump.

### 10. render.py (phase 2 stub)
Later: call Claude API with prompts/reconciliation_v2.md plus packet.json, parse the findings, and write the VENDOR edit-sheet CSV or CGT remediation plan directly. For now, create the module with a NotImplementedError and a docstring describing the interface.

## Judgment prompt (prompts/reconciliation_v2.md)

Adapt the existing Audio QA Reconciliation Prompt to consume the packet instead of raw transcripts: same defect taxonomy (Class 1 script defect, Class 2 rendering defect, Class 3 delivery flag, Class 4 artifact), same verdicts (CLEAN, FIX RECOMMENDED, SHOWSTOPPER), same VENDOR/CGT routing, same rules of conduct (traceability, no findings on paraphrase, honest open items). Remove the transcriber-arbitration rules (rules 5 to 8 in v1); with ASR plus script alignment there are no dueling instruments to arbitrate. Add: treat low-confidence ASR words (p < 0.6) at a discrepancy site as listen items, not confirmed defects.

## Testing

Course 10 is the known-answer test. Expected results the pipeline must reproduce:
- Zero confirmed word-level defects across topics 01 to 08 and 10.
- Topic 09_01 is unscripted (demo); packet carries outline + transcript.
- The open question from the manual run: whether file 01 ends with an extra sentence, the closing teaser that the storyboard places on the final slide of topic 10. The pipeline settles this definitively; assert that the aligner reports the tail state of file 01 either way.
- checks.json shows full coverage and no truncation flags for all files (ASR should not reproduce the LLM instruments' truncations).
Include a tiny synthetic fixture too: a 30-second TTS clip plus a script with one planted substitution, one deletion, and one inserted sentence, asserting the aligner finds exactly those.

## Build order

1. Modules 2 and 3 (config, extractor), tested against the Course 10 storyboard.
2. Module 4 (transcriber) on one Course 10 mp3; eyeball output quality.
3. Modules 6 and 7 (normalize, align) on that topic; tune the equivalence table until conventions stop registering as diffs.
4. Modules 5, 8, 9; full course run; compare packet to the manual findings report.
5. Module 1 polish (stage skipping, force, errors), README with team setup steps (uv or pipx), phase 2 stub.

## Style constraints

Python 3.11+, type hints, no em dashes in any generated document or report output, small pure functions, every stage rerunnable in isolation, all intermediates human-readable JSON.
