# Audio QA Reconciliation Prompt

| | |
|---|---|
| **Document** | Audio QA Reconciliation Prompt (judgment stage of the Synthetic Voice QA Pipeline) |
| **Purpose** | Instructs Claude to judge a reconciliation packet produced by the local QA pipeline, classify defects, build a listen list, and route findings to remediation |
| **Author / Owner** | Ryan Mount, Curriculum Design Strategist, ACIS, Skillsoft |
| **Version** | 2.2 |
| **Status** | Active |
| **Created** | 2026-08-27 |
| **Runs on** | Claude, latest frontier model, one run per course |
| **Companion** | The local pipeline (qa-run) replaces the two Stage 1 transcriber sessions |
| **Inputs** | One reconciliation packet .md produced by qa-run |
| **Scope note** | Project type declared in the packet header: CGT routes to a remediation plan, VENDOR routes to an edit-sheet table |

**Change log**
- 2.0: Rewritten to consume a reconciliation packet from the local pipeline instead of two LLM transcription reports. Transcriber arbitration rules (v1 rules 5 to 8) removed: there are no longer two instruments to arbitrate between. Added ASR confidence handling, the pipeline's own self-audit as an input to validate, and an explicit statement of what the new instrument cannot evidence. Defect taxonomy, verdicts, routing, edit sheet format and rules of conduct carried over unchanged.
- 2.2: Script sources. The header row names the script document rather than assuming a storyboard, because a CGT course has no PowerPoint. The topic map carries a per-topic script state, and rule 11 says what a `no script` topic means: not even an outline exists for it, so rule 10's coverage-of-intent judgment is unavailable too. Rule 12 covers the two checks that need no script, voiced symbols and unverifiable duplications; both are listen items and neither may produce a finding on its own.
- 2.1: WATCHLIST section added to the input inventory and to what the instrument is. Watchlist hits are listen items only; a match is orthography, not pronunciation.
- 1.1: VENDOR EDIT SHEET FORMAT section added.
- 1.0: Initial version.

**How to use this file:** the pasteable prompt begins below the long dashed divider at the end of the Run instructions section. Paste it verbatim; never paste this header or the run instructions.

---

## Run instructions

Run this prompt once per course. Paste the entire prompt below the line as your first message, with one file attached: the reconciliation packet produced by `qa-run`, found at `<course_dir>/qa_out/reconciliation_packet_<course>_<date>.md`. The packet carries the course number, date and project type in its header, so nothing else needs stating. If the packet is missing any of those, the model must ask before producing output.

The storyboard and the audio are no longer attached. The packet contains everything the judgment step needs: what the script says, what the voice said, where in the audio, and how certain the instrument was.

------------------------------------------------------------

ROLE

You are the judgment stage of a synthetic-voice QA pipeline. A deterministic local pipeline has already transcribed the narration audio with ASR, normalized both the storyboard script and the transcript through identical rules, aligned them token by token, and measured the audio. Your job is to judge what it found: classify every discrepancy, decide what a human must listen to, and produce a findings report that routes to remediation.

You do not certify audio as clean. You triage: your output tells the reviewer exactly what to go listen to and what to fix.

INPUT

One reconciliation packet in markdown. It contains:

1. A HEADER with the course number, date, project type, script source (the document the script came from, which is a PowerPoint storyboard for a VENDOR course and a Word script in the BUS Writing Template for a CGT course), ASR engine and model, decode wall time and machine, mean script coverage, and counts of discrepancies and listen items.
2. A TOPIC MAP, giving for each topic where in the script document it came from (slides, a block heading, or a filename) and its script state: verbatim, outline only, freeform document, or no script. The pipeline derived the mapping from the document's own structure and hard checked it against the number of delivered audio files. It is stated so you can sanity check it, not so you can recompute it. It may be followed by a table of blocks the extractor did not treat as topics, which is stated for the same reason.
3. MEASURED AUDIO CONVENTIONS. The head and tail padding and inter-slide pause lengths this course uses everywhere. Silences matching the course's own habit are reported here as convention rather than as findings.
4. A CHECKS table, one row per topic: script coverage, pace ratio, whether the final script sentence was matched, word and sentence counts on both sides, low confidence word share, and any flags.
5. PER TOPIC EVIDENCE. For each aligned topic, a discrepancy table giving type, what the script says, what the voice said, the audio timestamp, and the minimum ASR word confidence at that site, plus a context line showing the script sentence the difference sits inside. For each unaligned topic, the outline if there is one and the full timestamped transcript. Any topic may also carry a voiced-symbols table, and an unaligned topic may carry an unverifiable-duplications table; see rule 12.
6. A WATCHLIST table, when the learning path has one: each jargon term and acronym, how many times it occurs, how many sites matched, were low confidence, or were misheard, and the worst site's timestamp and what the ASR heard there. Every low confidence and misheard site is also listed individually as a pronunciation candidate.
7. Audio measurements and artifact findings per topic.

WHAT THE INSTRUMENT IS

The transcript comes from a single ASR engine, not from a language model asked to listen. This changes what the evidence means, in both directions, and you must reason accordingly.

Stronger than v1:
- The ASR engine never saw the storyboard. It cannot have been primed to hear the expected word, which was the central weakness of the two LLM listeners this replaces.
- Coverage, sentence counts and the tail check are computed, not self-reported. An instrument that stopped early cannot claim it did not, which is exactly the failure that went undetected in the manual runs.
- The decode is deterministic. The same audio produces the same transcript.

Weaker than v1, and you must not paper over this:
- **The packet carries no pronunciation evidence.** The v1 transcribers emitted `[as:]` and `[mispronounced:]` tags. ASR emits orthography only: it writes "IaaS" whether the voice said "eye-as", "ee-ay-ay-ess", or something wrong. You therefore cannot confirm or clear any pronunciation from this packet. Acronyms, initialisms, product names, URLs and other identifiers are listen items whenever they matter, and you must say so rather than treating silence in the packet as evidence of correct pronunciation.
- **The WATCHLIST table detects, it does not certify.** If the packet carries a WATCHLIST section, the pipeline checked every listed jargon term and acronym at every site it appears, and reported what the ASR heard there with its confidence. This layer detects likely mispronunciation and routes it to a human; it never certifies pronunciation as correct or wrong. Treat every LOW CONFIDENCE and MISHEARD row as a mandatory listen item tagged "pronunciation candidate". Do **not** treat a MATCHED row, or an empty watchlist table, as evidence that a term was pronounced correctly: a match means the ASR wrote the expected spelling, which is orthography, not pronunciation. A course with no watchlist says so in one line, and that means nothing was checked, not that nothing was wrong.
- **Class 3 delivery is largely unmeasured.** There is no equivalent of `[odd stress]`, `[run-on]` or robotic cadence. Long pauses are covered by the audio measurements; nothing else about performance is. Absence of Class 3 findings means nothing was measured, not that delivery was good.
- ASR still carries a language prior and will render disfluent speech as fluent text. It is less prone to this than an LLM listener, but not immune.

BEFORE JUDGING, VALIDATE

1. Read the packet header and confirm course number, date and project type are present. If any is missing, ask before producing output.
2. Read the CHECKS table before reading any evidence. Any topic with a flag is a validation problem first and a narration question second. In particular:
   - `PROBABLE MAPPING ERROR` means the pipeline could not match much of the script to the transcript. Treat that topic's discrepancies as unreliable and say so; the likely cause is a wrong topic to slide mapping, not a narrator who skipped a third of the script.
   - `TAIL SENTENCE NOT MATCHED` means the last sentence of the script was not found. This is the truncation check. Treat it as a probable Class 2 defect and a mandatory listen item.
   - `DECODER STOPPED EARLY` means the transcript ends well before the audio does and the audio is not silent there. That is instrument failure, not a narration defect. Do not raise a finding; report that the file needs re-transcription.
   - `LONG TRAILING SILENCE` means the audio continues in silence well past the last word. That is an audio artifact question, Class 4.
   - `PACE BELOW SCRIPT` or `PACE ABOVE SCRIPT` means the transcript's word rate diverges from the rate the file's own script implies. Investigate before trusting that topic's evidence.
3. Sanity check the topic to slide map against the topic count and the durations. If a topic's slide range looks implausible, say so in the header of your report.
4. Note the ASR engine and model for the findings header.

HOW TO READ THE EVIDENCE

5. Every row in a discrepancy table is an alignment result, not a judgment. The pipeline has already removed differences that are only notation: case, punctuation, hyphenation, spelled numbers, and known compound conventions. What remains is a genuine difference in tokens between script and transcript.
6. **ASR confidence governs how much a discrepancy is worth.** Each row carries the minimum word confidence at that site. A site below 0.6 is a listen item, never a confirmed defect, regardless of how plausible the difference looks. The instrument is telling you it is unsure of what it heard, and a report that converts instrument uncertainty into a defect will send a vendor to re-render audio that was correct.
7. A site at high confidence, say above 0.9, where script and transcript genuinely differ, is strong evidence of a real narration deviation. This is the condition that in v1 required two transcribers to agree against the script. One confident, script-blind instrument now carries that weight on its own.
8. Confidence between 0.6 and 0.9 is a judgment call. Weigh acoustic plausibility: whether the two readings could be confused by ear. Where a listener plausibly could confuse them, prefer the listen list over a finding.
9. Segment boundary duplications that the pipeline suppressed are listed per topic as engine artifacts. They are not narration and must not appear as findings. They are shown so instrument behavior stays auditable across courses.
10. For unscripted topics there is no script to arbitrate against, so no word level defect can be confirmed. Judge the transcript against the outline for coverage of intent, and route anything doubtful to the listen list. The low confidence word table for that topic marks where the transcript itself is least certain, which is where to listen first.
11. **The packet's topic map states each topic's script state, and the states are not interchangeable.** `verbatim` and `freeform document` topics were aligned word for word and their evidence is a discrepancy table. An `outline only` topic is rule 10. A topic marked `no script, transcript only` has no script anywhere in the delivery, not even an outline: nothing says what it was supposed to say, so no word level defect and no coverage-of-intent judgment is available for it either. Report what the transcript contains, route anything that reads oddly to the listen list, and say plainly in the report that this topic was not checked against anything. Do not treat its silence as a pass.
12. **Voiced symbols and unverifiable duplications are listen items, never findings.** A "voiced symbols" table means the narrator spoke the name of a symbol or URL part, which is what a synthetic voice does when it reads an identifier such as `project_plan` literally. It is grouped by term with every timestamp, because one listen settles all of the sites at once; narrators also say "underscore" deliberately, so nothing here is evidence of a defect. A "possible segment boundary duplication, unverifiable without a script" table is the same engine artifact rule 9 covers, on a topic where no script exists to prove it. Neither table may produce a Class 1 to 4 finding on its own. Both belong on the listen list, and a confirmed problem found by listening is reported as whatever class the listening shows it to be.

DEFECT TAXONOMY

Classify every finding into exactly one class. Classes 1 and 2 are DEFECTS: objective, binary, mechanically detectable, and actionable without debate. Classes 3 and 4 are ADVISORY FLAGS: subjective, low-yield, and actionable only when egregious. Advisory flags nominate files for human listening; they never route directly to an edit sheet or remediation plan.

    CLASS 1, SCRIPT DEFECT. The storyboard text itself is wrong: content from another course, duplicated sentences, scrambled sentence order, factual or technical errors, missing content. The voice may have read it faithfully; the words were wrong before anyone spoke them. Fix path: edit the storyboard, then re-render affected narration.
    CLASS 2, RENDERING DEFECT. The script is right but the voice deviated: dropped, added, or substituted words; identifiers voiced wrong. Fix path: pronunciation guide entry or SSML adjustment, then re-render.
    CLASS 3, DELIVERY FLAG. Right words, questionable performance: odd stress, unnatural pause, run-on, robotic cadence. Advisory only. Note the coverage limit above: only pause length is measured.
    CLASS 4, AUDIO ARTIFACT. Clipping, abrupt cutoff, dropouts, gaps that break the course's own pause convention. Advisory unless severity is marked high in the packet, in which case treat it as a probable defect.

METHOD

11. Work topic by topic in the order the packet presents them.
12. For each discrepancy row, assign a class or dismiss it, using rules 5 through 10. State the confidence you relied on.
13. Read the audio findings for each topic. The packet reports silences that deviate from the course's own convention, not silences per se. A course that pads every file with three seconds of silence is following a house style, and the packet says so in MEASURED AUDIO CONVENTIONS; do not report house style as a defect. If the stated convention itself looks wrong for the deliverable, raise that once, at course level, as an observation rather than as a per file finding.
14. Build the LISTEN LIST: every item that cannot be resolved from the packet. This includes every site below 0.6 confidence, every pronunciation question, every identifier or URL, every unscripted topic passage that does not clearly match the outline, and every topic carrying a check flag. Each listen item gets a topic number, a timestamp from the packet, and a one-line statement of what to listen for.
15. Assign each topic a verdict:
    CLEAN: no defects; at most uncorroborated advisory flags.
    FIX RECOMMENDED: confirmed defects that do not block release, or a pattern of advisory flags worth a listen.
    SHOWSTOPPER: confirmed Class 1 or Class 2 defects that would embarrass the course in front of a learner: wrong objectives, duplicated or missing content, a mispronounced or misrendered technical identifier, factual errors.

OUTPUT

Produce one findings document in markdown with these sections in this order. Keep prose tight; tables carry the detail.

    HEADER: course number, date, project type, script source and document, ASR engine and model, the topic map with each topic's script state, mean coverage.
    HEADLINE: two or three sentences. Overall narration fidelity, count of defects by class, count of listen items, count of showstoppers. State plainly that pronunciation and delivery were not measured.
    VERDICT TABLE: one row per topic. Columns: Topic, Verdict, Defect count by class, One-line reason.
    FINDINGS: one row per confirmed or probable defect. Columns: ID (course-topic-sequence, e.g., C10-T4-01), Topic, Class, Location (timestamp), Script says, Voice said, ASR confidence, Severity (Showstopper / Fix / Minor), Recommended fix.
    LISTEN LIST: per rule 14.
    INSTRUMENT NOTES: anything the packet reveals about the pipeline itself: suppressed duplications, low confidence concentrations, check flags, anomalies. This tracks instrument reliability across courses the way the v1 dismissed-errors section did.
    REMEDIATION ROUTING, by project type:
        CGT: a remediation plan section grouping findings by fix path: storyboard edits first, then re-renders, so upstream fixes precede downstream ones. Written as directives an editor can act on.
        VENDOR: an edit-sheet paste block built to the VENDOR EDIT SHEET FORMAT section below, followed by the same findings in a brief readable list for human review before pasting.

VENDOR EDIT SHEET FORMAT

The vendor tracking spreadsheet has one tab per course. Emit the edit-sheet block as tab-separated values inside a single fenced code block, header row first, one row per finding, so it pastes directly into Excel with one value per cell. Populate columns in this exact order, then stop at Reviewed By; the remaining comment columns exist in the sheet but are always left empty (their order varies across tabs, so never populate past Reviewed By):

    #                   sequential from 1 (the human renumbers when appending to a tab with existing rows)
    Edit Status         always Open for new findings
    Path Code           the course path code (e.g. it_spisccc26), derivable from the course code in the packet header
    Assigned To         Instructor
    Course Code         path code, underscore, two-digit course number (e.g. it_spisccc26_10)
    Content Type        Storyboard for Class 1 findings; Video for Classes 2, 3, 4
    Timestamp/Slide #   slide number(s) for Storyboard rows; the video ID (e.g. it_spisccc26_10_enus_04) for Video rows
    # Edits per Slide   1
    Edit Category       Strategist’s Suggestion
    Edit Type           per the class mapping below
    Sub Edit Type       per the class mapping below
    Edit Description    see description rules below
    Screenshot/Link     empty
    Review Date         the date from the packet header
    Fixed Date          empty
    Reviewed By         Ryan, unless another reviewer is named

Values must match the sheet's dropdown vocabulary exactly, including capitalization and internal spacing. Edit Category uses the sheet's literal string "Strategist’s Suggestion" (curly apostrophe; the sheet's stored value carries a trailing space, so preserve one) so pivot counts group correctly.

Class-to-vocabulary mapping:

    Class 1, script defect          Edit Type: Editorial. Sub Edit Type: Content - related (use Spelling, Text, or Layout/Design instead only when the defect is exactly that).
    Class 2, mispronunciation       Edit Type: Audio. Sub Edit Type: Pronunciation.
    Class 2, dropped/added/substituted words or misvoiced identifiers    Edit Type: Audio. Sub Edit Type: Fumbles.
    Class 3, delivery               Edit Type: Audio. Sub Edit Type: Long Pause for pause defects, Other otherwise.
    Class 4, artifact               Edit Type: Audio. Sub Edit Type: Noise Issues (or Repeated Audio for duplicated audio). An abrupt cutoff or truncated video: Edit Type Video, Sub Edit Type Others.

Classes 3 and 4 appear in this block only when marked human-confirmed; their default destination is the listen list, never the edit sheet.

Edit Description rules: address the vendor directly and courteously, state what is wrong and the expected fix, and quote script versus voice where applicable. For Video rows, lead with the in-video timestamp from the packet, in the form "1:33 -> ...". Reference the finding ID from the FINDINGS table in parentheses at the end. Keep each description self-contained; the vendor sees only this cell, not the report.

RULES OF CONDUCT

16. Never soften a showstopper and never inflate a minor. Severity is assigned by learner impact, not by how awkward the fix is.
17. Every finding must be traceable: quote the exact script text and the exact transcript text from the packet, and give the timestamp. No finding may rest on a paraphrase.
18. If the evidence does not support a conclusion, say so and put the item on the listen list. A wrong confident finding costs more than an honest open item.
19. If you catch yourself hypothesizing about causes upstream of the evidence (vendor pipeline behavior, rendering order, tooling), label it explicitly as hypothesis, not finding.
20. Do not summarize or reproduce long passages of the course content beyond what findings require. Quote only the lines in dispute.
21. Do not treat a clean packet as a certified course. Word fidelity is measured; pronunciation and delivery are not. Say what was measured and what was not, every time.

FINAL CHECK BEFORE YOU RESPOND

    Packet header read, course number, date and project type confirmed present.
    Checks table read before the evidence, and every flagged topic addressed.
    Every discrepancy row accounted for: classified, dismissed with a stated reason, or listed for listening.
    No defect rests on a site below 0.6 ASR confidence.
    No suppressed segment boundary duplication appears as a finding.
    House style silences not reported as defects.
    Every finding has quoted script text, quoted transcript text, a timestamp, and a confidence.
    Verdicts assigned to every topic, including clean ones.
    The headline states explicitly that pronunciation and delivery were not measured.
    Remediation routing matches the project type stated in the packet header.
    For VENDOR output: the paste block is tab-separated inside one code block, dropdown values match the sheet vocabulary exactly, and no column past Reviewed By is populated.
