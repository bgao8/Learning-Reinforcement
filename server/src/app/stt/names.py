"""Whisper prompt: steers how Whisper spells names.

Each 7 s window is transcribed on its own, so Whisper re-guesses every name from sound alone
("GR Corolla" in one window, "Carola" in the next). Whisper's initial_prompt is read as text
that came before the audio, and Whisper copies spellings it sees there. The prompt holds:
  1. the session title (typed by the user, so the most trusted spelling)
  2. names Whisper has already written this session, misspellings folded into the usual spelling
  3. the text just before the window, so sentences and spellings carry across windows
"""
from collections import Counter
from difflib import SequenceMatcher

SIMILAR = 0.75          # "Carola"/"Corolla" is 0.77, "Markov"/"Markoff" 0.77; "Newton"/"Norton" is 0.67
MIN_FUZZY_LEN = 4       # shorter words ("GR", "AI") only match when identical
MAX_NAMES = 12
MAX_TITLE_CHARS = 150
MAX_NAMES_CHARS = 250
MAX_RECENT_CHARS = 250  # all three together stay well under Whisper's 223-token prompt limit

NOT_NAMES = {"I", "I'm", "I've", "I'll", "I'd", "OK", "Okay"}
STRIP = "\"'“”‘’()[]{},.;:!?…"
CLOSERS = "\"'”’)]}"
SENTENCE_END = (".", "?", "!", "…")
PHRASE_END = (",", ";", ":") + SENTENCE_END


def near_miss(a: str, b: str) -> bool:
    """Two different spellings of what is probably one word."""
    a, b = a.lower(), b.lower()
    if a == b or min(len(a), len(b)) < MIN_FUZZY_LEN:
        return False
    return SequenceMatcher(None, a, b).ratio() >= SIMILAR


def shares_near_miss(a: str, b: str) -> bool:
    """Some word of a is a near miss of some word of b ("Toyota Carola" vs "GR Corolla")."""
    return any(near_miss(x, y) for x in a.split() for y in b.split())


class NameGlossary:
    """Names Whisper has written this session, with misspellings grouped together.

    A name is a capitalized word that doesn't start a sentence (capitals there say nothing),
    or an acronym anywhere. Neighboring names join into one ("GR Corolla"). A name whose word
    is a near miss of a known name's word counts toward that name, and each group is shown
    with its most common spelling, so "GR Corolla" x3 beats "Carola" x2.
    """

    def __init__(self):
        self._groups: list[Counter[str]] = []
        self._sentence_start = True

    def add(self, words: list[str]) -> None:
        for phrase in self._phrases(words):
            self._count(phrase)

    def terms(self, limit: int = MAX_NAMES) -> list[str]:
        """The best spelling of each name, most heard first."""
        ranked = sorted(self._groups, key=lambda g: g.total(), reverse=True)
        return [best_spelling(g) for g in ranked[:limit]]

    def _phrases(self, words: list[str]) -> list[str]:
        phrases, current = [], []
        for raw in words:
            core = raw.strip(STRIP).removesuffix("'s").removesuffix("’s")
            if core and self._is_name(core):
                current.append(core)
            elif current:
                phrases.append(" ".join(current))
                current = []

            tail = raw.rstrip(CLOSERS)
            if current and tail.endswith(PHRASE_END):
                phrases.append(" ".join(current))
                current = []
            self._sentence_start = tail.endswith(SENTENCE_END)

        if current:
            phrases.append(" ".join(current))
        return phrases

    def _is_name(self, word: str) -> bool:
        if word in NOT_NAMES or not word[0].isupper():
            return False
        acronym = len(word) >= 2 and word.isupper()
        return acronym or not self._sentence_start

    def _count(self, phrase: str) -> None:
        for group in self._groups:
            if phrase in group or shares_near_miss(phrase, best_spelling(group)):
                group[phrase] += 1
                return
        self._groups.append(Counter({phrase: 1}))


def best_spelling(group: Counter[str]) -> str:
    """Most heard; on a tie the longer one, which says more ("GR Corolla" over "Corolla")."""
    return max(group, key=lambda spelling: (group[spelling], len(spelling)))


def clip_left(text: str, limit: int) -> str:
    """The end of text, at most limit chars, starting on a whole word."""
    if len(text) <= limit:
        return text
    cut = text[-limit:]
    return cut[cut.find(" ") + 1:] if " " in cut else cut


def whisper_prompt(title: str | None, names: list[str], recent: str) -> str | None:
    """The prompt for one window, or None when there is nothing to say yet."""
    parts = []
    title = (title or "").strip()[:MAX_TITLE_CHARS]
    if title:
        parts.append(title if title.endswith(SENTENCE_END) else f"{title}.")

    # the title is typed by the user: a name that is a near miss of it is a misspelling
    kept, used = [], 0
    for name in names:
        if title and shares_near_miss(name, title):
            continue
        if used + len(name) + 2 > MAX_NAMES_CHARS:
            break
        kept.append(name)
        used += len(name) + 2
    if kept:
        parts.append(", ".join(kept) + ".")

    # last, because Whisper reads the prompt as the text right before the audio
    recent = clip_left(recent.strip(), MAX_RECENT_CHARS)
    if recent:
        parts.append(recent)

    return " ".join(parts) or None
