"""Deterministic expansion of qualifying phrases into spoken-form match variants.

VENDORED verbatim (pun intended) from the standalone Verbatim project,
`backend/verbatim/watchlist/variants.py`. Pure stdlib, no behavioural changes —
kept byte-compatible so patterns generated here match what the GPU-side matcher
scans for. If the upstream expansion logic changes, this must change with it.


The matcher only ever scans *stored* variants, so every transformation here is
deterministic, auditable, and visible in the console. Given a canonical phrase we
produce a small set of normalized variants:

* ``normalized`` — lower-cased, punctuation-stripped, whitespace-collapsed.
* ``numbers_to_words`` — digits and currency amounts spoken out
  (``"$5"`` → ``"five dollars"``, ``"2024"`` → ``"twenty twenty four"`` style
  handled by a compact number speller).
* ``homophones`` — swaps from a small curated table (``"buy"`` ↔ ``"by"``).

Each variant is emitted as a :class:`Variant` carrying its ``kind`` so the
console can label how it was derived.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Curated homophone groups. Each inner tuple is a set of mutually swappable
# spoken forms; expansion substitutes any occurrence with the others.
HOMOPHONES: tuple[tuple[str, ...], ...] = (
    ("buy", "by", "bye"),
    ("to", "too", "two"),
    ("for", "four"),
    ("their", "there", "they're"),
    ("your", "you're"),
    ("no", "know"),
    ("here", "hear"),
    ("won", "one"),
    ("great", "grate"),
    ("peace", "piece"),
)

_ONES = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen",
]
_TENS = [
    "", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
    "eighty", "ninety",
]


@dataclass(frozen=True)
class Variant:
    """A single derived match variant.

    Attributes:
        text: The normalized variant string the matcher scans for.
        kind: How it was derived (``normalized``/``numbers_to_words``/``homophones``).
    """

    text: str
    kind: str


def normalize(text: str) -> str:
    """Lower-case, strip punctuation to spaces, and collapse whitespace."""
    lowered = text.lower()
    stripped = re.sub(r"[^\w\s]", " ", lowered)
    return re.sub(r"\s+", " ", stripped).strip()


def _spell_under_1000(n: int) -> str:
    """Spell an integer in [0, 999] as words."""
    if n < 20:
        return _ONES[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        return _TENS[tens] + ("" if ones == 0 else " " + _ONES[ones])
    hundreds, rest = divmod(n, 100)
    head = _ONES[hundreds] + " hundred"
    return head if rest == 0 else head + " " + _spell_under_1000(rest)


def spell_number(n: int) -> str:
    """Spell a non-negative integer as words (supports up to the billions)."""
    if n == 0:
        return "zero"
    parts: list[str] = []
    for scale, name in ((1_000_000_000, "billion"), (1_000_000, "million"), (1_000, "thousand")):
        if n >= scale:
            count, n = divmod(n, scale)
            parts.append(_spell_under_1000(count) + " " + name)
    if n > 0:
        parts.append(_spell_under_1000(n))
    return " ".join(parts)


def _spell_year(n: int) -> str:
    """Spell a 4-digit year in the natural 'nineteen eighty four' pairing."""
    hi, lo = divmod(n, 100)
    if lo == 0:
        return _spell_under_1000(hi) + " hundred"
    lo_words = _ONES[lo] if lo < 20 else _spell_under_1000(lo)
    if lo < 10:
        lo_words = "oh " + _ONES[lo]
    return f"{_spell_under_1000(hi)} {lo_words}"


def numbers_to_words(text: str) -> str:
    """Replace currency amounts and bare numbers with spoken forms.

    ``"$5"`` → ``"five dollars"``, ``"$1.50"`` → ``"one dollar and fifty cents"``,
    four-digit numbers spelled year-style, others spelled plainly.
    """

    def money(match: re.Match[str]) -> str:
        whole = int(match.group(1))
        cents = match.group(2)
        dollars = f"{spell_number(whole)} {'dollar' if whole == 1 else 'dollars'}"
        if cents:
            c = int(cents.ljust(2, "0")[:2])
            if c:
                return f"{dollars} and {spell_number(c)} {'cent' if c == 1 else 'cents'}"
        return dollars

    text = re.sub(r"\$(\d+)(?:\.(\d{1,2}))?", money, text)

    def plain(match: re.Match[str]) -> str:
        n = int(match.group(0))
        if 1000 <= n <= 9999:
            return _spell_year(n)
        return spell_number(n)

    return re.sub(r"\d+", plain, text)


def _homophone_variants(normalized: str) -> list[str]:
    """Return normalized strings with one homophone token swapped, if any."""
    tokens = normalized.split()
    out: list[str] = []
    for i, tok in enumerate(tokens):
        for group in HOMOPHONES:
            if tok in group:
                for alt in group:
                    if alt != tok:
                        swapped = tokens.copy()
                        swapped[i] = alt
                        out.append(" ".join(swapped))
    return out


def expand_phrase(phrase: str) -> list[Variant]:
    """Expand a canonical phrase into a de-duplicated list of match variants.

    The canonical normalized form is always first. Number-spelling and
    homophone variants are added when they differ from it.
    """
    seen: set[str] = set()
    variants: list[Variant] = []

    def add(text: str, kind: str) -> None:
        norm = normalize(text)
        if norm and norm not in seen:
            seen.add(norm)
            variants.append(Variant(norm, kind))

    add(phrase, "normalized")

    spoken = numbers_to_words(phrase)
    add(spoken, "numbers_to_words")

    base_norm = normalize(phrase)
    for hv in _homophone_variants(base_norm):
        add(hv, "homophones")
    # also homophones over the number-spelled form
    for hv in _homophone_variants(normalize(spoken)):
        add(hv, "homophones")

    return variants
