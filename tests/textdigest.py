"""Digest helper for known answer tests.

This repository is public. Skillsoft storyboard narration and the transcripts
made from it are customer material and must not appear in it verbatim, so the
known answer tests assert on the digest of an expected string rather than on
the string.

What the tests lose is nothing: a digest comparison fails on exactly the same
regressions a literal comparison would. What they gain is that the assertion
no longer publishes the sentence.

Where a test can derive the expected text from pipeline output at run time, it
does that instead and compares structure directly. That is stronger than either
approach, because the assertion then holds against whatever the storyboard
actually says rather than against a copy of it frozen in a test file.

Honest limitation: a digest of a short common token is not secrecy. Anyone can
hash a wordlist and recover a single word from its digest. The purpose here is
that the repository does not quote course narration, not that the digests are
irreversible. Long sentences are effectively opaque; single words are not, and
no test should be written as though they were.
"""

from __future__ import annotations

import hashlib
import re

DIGEST_CHARS = 16

_STRIP = re.compile(r"[^a-z0-9 ]+")
_SPACES = re.compile(r"\s+")


def canonical(text: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace.

    Digests are taken over this form so that a rendering change in punctuation
    or casing does not fail a test for the wrong reason. It matches the spirit
    of qa/normalize.py without importing its equivalence table, which would
    make the digests depend on a tuning file.
    """
    return _SPACES.sub(" ", _STRIP.sub(" ", text.lower())).strip()


def digest(text: str) -> str:
    """Short stable digest of a string's canonical form."""
    return hashlib.sha256(canonical(text).encode("utf-8")).hexdigest()[:DIGEST_CHARS]
