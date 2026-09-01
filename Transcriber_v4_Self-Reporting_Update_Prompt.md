# Prompt: Upgrade Audio QA Transcriber Prompt to v4 (self-reporting instrumentation)

Paste everything below this line into the session holding the transcriber prompt, with Audio_QA_Transcriber_Prompt_v3.md attached.

------------------------------------------------------------

Revise the attached Audio QA Transcriber Prompt from v3 to v4. The goal of this revision is to make the transcriber self-reporting: when the instrument fails, its own report should expose the failure on paper, without anyone listening to audio.

CONTEXT FOR THE REVISION

A completed reconciliation run (Course 10, 2026-08-25) found two failure modes in LLM transcribers that v3 does not detect:

1. Tail truncation. One transcriber silently stopped transcribing before the audio ended in 4 of 9 files, always at a clean paragraph boundary, so the truncation was invisible in the report itself. It was only caught because a second transcriber covered the missing content.
2. Paraphrase drift. The same transcriber drifted from verbatim transcription into fluent paraphrase over long files, substituting synonyms and restructuring sentences while producing natural-sounding output. The instruction to transcribe verbatim weakened as generation length grew.

A third, unconfirmed failure mode is cross-file contamination: a closing sentence from the final audio file may have bled into the transcript of the first file, consistent with all files being processed in one long context.

REQUIRED CHANGES

Add the following to the prompt. Keep every existing v3 requirement (YAML front matter, one sentence per line, inline flag tags, FLAG SUMMARY table, ascending topic order) unchanged, and make all additions additive so that a Stage 2 reconciliation prompt written against v3 output still parses v4 output without modification.

1. COMPLETION ATTESTATION, per file. At the end of each file section, after the transcript, the transcriber must add an attestation block containing: (a) the approximate timestamp where the audio ends, (b) a verbatim quote of the final sentence it heard, labeled FINAL SENTENCE, and (c) an explicit statement of whether it reached the end of the audio or stopped early for any reason. A transcriber that never processed the tail cannot quote it, so this field turns silent truncation into a visible mismatch.

2. SENTENCE COUNT, per file. Add a per-topic sentence count column to the FLAG SUMMARY table. Downstream reconciliation will diff counts between two instruments before diffing words, so a truncated file surfaces as a count mismatch immediately.

3. PACING SELF-CHECK, per file. Require the transcriber to compute words transcribed divided by audio duration in minutes and report it per file. Professional TTS narration runs roughly 140 to 160 words per minute. If the computed rate falls below 120, the transcriber must flag that file as POSSIBLE TRUNCATION in its own report and say so in the file's attestation block.

4. SEGMENTED TRANSCRIPTION. Instruct the transcriber to work in labeled segments of roughly two minutes of audio, completing each segment verbatim before starting the next. The purpose is to re-anchor the verbatim instruction repeatedly across a long file instead of relying on one instruction issued before a long continuous generation. Segment labels are for the transcriber's discipline; the final output should remain one continuous per-file transcript so the v3 output format is preserved.

5. VERBATIM DISCIPLINE CLAUSE. Add explicit anti-paraphrase language: transcribe exactly what is spoken, including awkward phrasing, redundancy, and grammatical errors; never substitute a synonym, never smooth a sentence, never summarize; if a passage was not clearly heard, use the [unclear:] tag rather than reconstructing plausible wording. State plainly that a fluent paraphrase is a worse failure than a tagged gap, because the paraphrase is invisible and the gap is not.

6. RUN ISOLATION INSTRUCTION. In the run instructions (the header section that is never pasted), add: process one audio file per fresh session or request whenever the platform allows it, and never carry multiple courses in one context. This attacks both instruction decay and cross-file contamination.

7. TRUNCATION HONESTY CLAUSE. Add: if you hit any output limit, are unable to finish a file, or are uncertain you reached the end of the audio, you must say so explicitly in that file's attestation block and in the YAML front matter. Ending a transcript early without declaring it is the single worst failure this prompt can produce.

8. VERSIONING. Update the version to 4.0, update prompt_version in the required YAML output accordingly, and add a change log entry summarizing these additions in one or two lines. Update the document header table if one exists.

CONSTRAINTS

Do not use em dashes anywhere in the revised prompt. Do not remove or weaken any v3 requirement. Do not change the flag tag vocabulary. Keep the additions concise and imperative; this prompt is pasted into transcriber sessions verbatim, so every added sentence costs attention. After revising, output the complete v4 prompt as a single file, then list the changes you made as a short summary.
