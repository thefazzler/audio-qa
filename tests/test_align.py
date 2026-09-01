"""Known answer tests for normalization and alignment.

The synthetic fixture plants exactly one substitution, one deletion and one
inserted sentence, and asserts the aligner finds exactly those and nothing
else. Audio is not involved: the fixture supplies the word list a transcriber
would have produced, which is what the aligner actually consumes.
"""

from __future__ import annotations

import pytest

from qa.align import align_topic
from qa.normalize import build_sequence, normalize_token, script_tokens


def words(text: str, start: float = 0.0, step: float = 0.4, p: float = 0.99):
    """Fake transcript words with plausible timestamps."""
    out = []
    clock = start
    for token in text.split():
        out.append(
            {"w": token, "start": round(clock, 2), "end": round(clock + step, 2), "p": p}
        )
        clock += step
    return out


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def test_case_and_punctuation_fold():
    assert normalize_token("Cloud,") == ["cloud"]
    assert normalize_token("(IaaS,") == ["iaas"]
    assert normalize_token("Model.") == ["model"]


def test_hyphenated_compound_splits_like_whisper_does():
    # Whisper's word timestamps emit "cloud" then "-based". The script writes
    # one token. Splitting both sides makes them agree.
    assert normalize_token("cloud-based") == ["cloud", "based"]
    assert normalize_token("-based") == ["based"]


def test_curly_apostrophe_matches_straight():
    assert normalize_token("we’ll") == normalize_token("we'll")


def test_numbers_become_words():
    assert normalize_token("24") == ["twenty", "four"]
    assert normalize_token("50%") == ["fifty", "percent"]


def test_equivalence_table_collapses_compounds():
    def norms(text: str) -> list[str]:
        return [t.norm for t in build_sequence(script_tokens([text]))]

    assert norms("life cycle") == norms("lifecycle")
    assert norms("data set") == norms("dataset")
    assert norms("A-I") == norms("AI")


# ---------------------------------------------------------------------------
# Alignment, planted defects
# ---------------------------------------------------------------------------

# Deliberately about nothing this pipeline will ever be pointed at. An earlier
# version of this fixture was written in the vocabulary of the reference course
# and overlapped its narration almost word for word, which is exactly what the
# repository must not carry. See D16.
SCRIPT = [
    "The gardener waters the seedlings each morning.",
    "Volunteers repot the tallest cuttings before the weekend arrives.",
    "Labels stay attached to every tray on every shelf.",
    "Compost warms the raised beds through the coldest months.",
]


def test_clean_alignment_is_silent():
    spoken = " ".join(SCRIPT)
    result = align_topic(SCRIPT, words(spoken))
    assert result["discrepancies"] == []
    assert result["coverage"] == 1.0


def test_notation_differences_do_not_register():
    spoken = (
        "the gardener waters the seedlings each morning "
        "volunteers repot the tallest cuttings before the weekend arrives "
        "labels stay attached to every tray on every shelf "
        "compost warms the raised beds through the coldest months"
    )
    result = align_topic(SCRIPT, words(spoken))
    assert result["discrepancies"] == []


def test_finds_exactly_the_planted_defects():
    """One substitution, one deletion, one inserted sentence, and nothing else.

    The three plants are kept apart in the sequence on purpose. Adjacent plants
    merge into a single substitution, which is correct reporting but a different
    assertion; see the merge test below.
    """
    spoken = (
        # substitution: one verb becomes another
        "The gardener soaks the seedlings each morning. "
        # deletion: the closing phrase of the second sentence is dropped
        "Volunteers repot the tallest cuttings. "
        "Labels stay attached to every tray on every shelf. "
        # insertion: a sentence that is not in the script at all
        "That finishes the walkthrough. "
        "Compost warms the raised beds through the coldest months."
    )
    result = align_topic(SCRIPT, words(spoken))
    found = result["discrepancies"]

    assert result["counts"] == {"substitution": 1, "deletion": 1, "insertion": 1}
    assert len(found) == 3

    sub = next(d for d in found if d["type"] == "substitution")
    assert sub["script_says"] == "waters"
    assert sub["voice_said"] == "soaks"
    assert sub["start_s"] is not None

    dele = next(d for d in found if d["type"] == "deletion")
    assert "the weekend arrives" in dele["script_says"]
    assert dele["voice_said"] == ""
    assert dele["start_s"] is not None  # points at the seam

    ins = next(d for d in found if d["type"] == "insertion")
    assert "finishes" in ins["voice_said"]
    assert ins["script_says"] == ""


def test_adjacent_deletion_and_insertion_merge_into_one_substitution():
    """A dropped tail replaced by other speech reads as one substitution.

    This is deliberate. "script says X, voice said Y" at one location is more
    useful to a judge than two separate findings that have to be re-joined by
    hand.
    """
    spoken = (
        "The gardener waters the seedlings each morning. "
        "Volunteers repot the tallest cuttings before the weekend arrives. "
        "Labels stay attached to every tray on every shelf. "
        "Something else entirely was said here."
    )
    result = align_topic(SCRIPT, words(spoken))
    assert result["counts"]["substitution"] == 1
    assert result["counts"]["deletion"] == 0
    assert result["counts"]["insertion"] == 0
    sub = result["discrepancies"][0]
    assert "Compost" in sub["script_says"]
    assert "Something else" in sub["voice_said"]


def test_low_confidence_becomes_a_listen_item():
    spoken = "The gardener soaks the seedlings each morning. " + " ".join(SCRIPT[1:])
    transcript = words(spoken)
    for word in transcript:
        if word["w"] == "soaks":
            word["p"] = 0.31
    result = align_topic(SCRIPT, transcript)
    sub = next(d for d in result["discrepancies"] if d["type"] == "substitution")
    assert sub["listen_item"] is True
    assert "confidence" in sub["reason"]


def test_discrepancy_carries_timestamps_and_context():
    spoken = "The gardener soaks the seedlings each morning. " + " ".join(SCRIPT[1:])
    result = align_topic(SCRIPT, words(spoken))
    sub = next(d for d in result["discrepancies"] if d["type"] == "substitution")
    assert sub["script_sentence"] == 0
    assert sub["context_after"] == SCRIPT[1]
    assert sub["end_s"] >= sub["start_s"]


def test_truncated_tail_shows_as_one_deletion():
    spoken = " ".join(SCRIPT[:2])
    result = align_topic(SCRIPT, words(spoken))
    assert result["counts"]["deletion"] == 1
    assert result["coverage"] < 0.8


@pytest.mark.parametrize(
    "script_word,spoken_word",
    [("life cycle", "lifecycle"), ("data set", "dataset"), ("AI", "A-I")],
)
def test_conventions_never_register_as_defects(script_word, spoken_word):
    script = [f"The {script_word} matters here."]
    result = align_topic(script, words(f"The {spoken_word} matters here."))
    assert result["discrepancies"] == []


# ---------------------------------------------------------------------------
# faster-whisper segment boundary duplication
# ---------------------------------------------------------------------------

def timed(pairs, step=0.4):
    """Words plus segments, where a break marker starts a new segment."""
    out_words, out_segments = [], []
    clock, seg_start, seg_words = 0.0, 0.0, []
    for token, breaks in pairs:
        out_words.append(
            {"w": token, "start": round(clock, 2), "end": round(clock + step, 2),
             "p": 0.9}
        )
        seg_words.append(token)
        clock = round(clock + step, 2)
        if breaks:
            out_segments.append(
                {"start": seg_start, "end": clock, "text": " ".join(seg_words)}
            )
            seg_start, seg_words = clock, []
    if seg_words:
        out_segments.append(
            {"start": seg_start, "end": clock, "text": " ".join(seg_words)}
        )
    return out_words, out_segments


def test_suffix_fragment_at_segment_start_is_suppressed():
    script = ["Organizations use application platforms or managed services."]
    # "platforms," ends a segment; whisper re-emits its tail as "forms,"
    words_, segments = timed([
        ("Organizations", False), ("use", False), ("application", False),
        ("platforms,", True),
        ("forms,", False), ("or", False), ("managed", False), ("services.", False),
    ])
    result = align_topic(script, words_, segments)
    assert result["discrepancies"] == []
    assert len(result["suppressed_asr_duplicates"]) == 1
    assert result["suppressed_asr_duplicates"][0]["voice_said"] == "forms,"


def test_whole_word_repeat_at_segment_start_is_suppressed():
    script = ["Cloud computing provides scale."]
    words_, segments = timed([
        ("Cloud", False), ("computing", False), ("provides.", True),
        ("provides.", False), ("scale.", False),
    ])
    result = align_topic(script, words_, segments)
    assert result["discrepancies"] == []
    assert len(result["suppressed_asr_duplicates"]) == 1


def test_legitimate_suffix_word_survives():
    """"demand," followed by "and" is real English, not an artifact.

    It matches the script, so it is never a candidate for suppression. This
    test fails loudly if suppression is ever moved ahead of alignment.
    """
    script = ["Teams see seasonal demand, and sudden increases in load."]
    words_, segments = timed([
        ("Teams", False), ("see", False), ("seasonal", False), ("demand,", True),
        ("and", False), ("sudden", False), ("increases", False), ("in", False),
        ("load.", False),
    ])
    result = align_topic(script, words_, segments)
    assert result["discrepancies"] == []
    assert result["suppressed_asr_duplicates"] == []
    assert result["coverage"] == 1.0
    assert result["counts"]["deletion"] == 0


def test_genuine_insertion_is_not_suppressed():
    """An added word that is not a boundary duplicate still gets reported."""
    script = ["Cloud security protects data."]
    words_, segments = timed([
        ("Cloud", False), ("security", False), ("carefully", False),
        ("protects", False), ("data.", False),
    ])
    result = align_topic(script, words_, segments)
    assert result["counts"]["insertion"] == 1
    assert result["discrepancies"][0]["voice_said"] == "carefully"
    assert result["suppressed_asr_duplicates"] == []


def test_substitutions_are_never_suppressed():
    """A two token substitution survives the duplicate filter.

    The wording is deliberately unrelated to any real course, so that no
    fixture in this repository echoes customer narration. See D16.
    """
    script = ["The kettle boils a fresh pot."]
    words_, segments = timed([
        ("The", False), ("kettle", False), ("boil", False), ("the", False),
        ("fresh", False), ("pot.", False),
    ])
    result = align_topic(script, words_, segments)
    assert result["counts"]["substitution"] == 1
    assert result["suppressed_asr_duplicates"] == []


def test_healthcare_convention_does_not_register():
    script = ["Customer records and healthcare data are hosted in the cloud."]
    result = align_topic(
        script, words("Customer records and health care data are hosted in the cloud.")
    )
    assert result["discrepancies"] == []
