# Listening

Two golden values are waiting on a person with headphones, frozen in a test as
"pending confirmation by ear". This page settles both in five minutes and ends
with the message to paste back. Nothing here quotes narration (D16).
Timestamps are minutes:seconds into the file, from a CPU int8 decode; they can
shift by a second between decodes (D23), so each range carries padding.

## 1. Course 10, file 01: does it end with the next topic's teaser? (D5)

**File:** Course 10 of spisccc26, topic 01, the delivered file whose name ends
`_10_enus_01`, 84 seconds long. If the course has left the library, bring the
delivery back through Intake first.

**Play:** 1:10 to the end.

**Listen for:** the last sentence. The pipeline heard the narration end on
topic 01's own closing sentence at 1:20.7, then three seconds of silence. The
question is whether one more sentence follows: the 14-word sentence the
storyboard places on topic 10's final slide (slide 46), a preview of the topic
to come, which a manual transcriber once reported hearing here.

- **Absent.** The file ends on its own closing sentence and goes quiet. The
  earlier report was cross-file bleed; the golden value freezes as it is.
- **Present.** A sentence is spoken after 1:21. The transcriber missed it,
  which is the more serious finding: D5 is rewritten, the test is inverted to
  assert the sentence is there, and the miss is recorded against the ASR.

## 2. Course 11: three sites where SIEM was not heard (D15)

**Files:** Course 11 of spisccc26, topics 01, 11 and 13: the files whose
names end `_11_enus_01`, `_11_enus_11` and `_11_enus_13`.

| Topic | Play | Site | Confidence |
|---|---|---|---|
| 01 | 1:27 to 1:34 | 1:30 | 0.49 |
| 11 | 1:50 to 1:58 | 1:54, worst of the three | 0.18 |
| 13 | 1:01 to 1:08 | 1:05 | 0.54 |

**Listen for:** the term SIEM, once in each range, where the transcriber
wrote something else at low confidence. Decide one thing per site: voiced
acceptably, or wrongly or garbled? The watchlist's `say` note for SIEM is
still TODO, so there is no house pronunciation to check against; record what
you heard and the note can be written from it.

The golden test does not change either way: the layer may route a false alarm
to a person and may not miss one, and the test asserts the routing.

- **Acceptable.** A false alarm, correctly routed. D15 records that the
  mishearing was the transcriber's, and the site seeds the `say` note.
- **Wrong.** A real pronunciation finding, the first this layer has caught.
  It goes to the course's judgment step, not this repository; D15 records it.

To see the sites in the interface, copy `tests/spisccc26/watchlist.yaml` to
`<library>/spisccc26/watchlist.yaml` and run the course again.

## The message to paste back

Fill in the brackets and paste the whole block. Either outcome for either
item is a complete answer.

    LISTENING.md results, [date], listened by [name]
    Item 1, course 10 file 01 tail: [ABSENT | PRESENT at m:ss]
    Item 2, course 11 SIEM:
      topic 01 at 1:30: [ACCEPTABLE | WRONG], heard as [describe, do not spell the narration]
      topic 11 at 1:54: [ACCEPTABLE | WRONG], heard as [...]
      topic 13 at 1:05: [ACCEPTABLE | WRONG], heard as [...]

Then the "pending confirmation by ear" lines in `tests/test_course10.py` and
`tests/test_course11.py` become "confirmed by ear" with date and name, D5 and
D15 get a closing addendum each, and this page is deleted. Nothing is
confirmed until that message arrives.
