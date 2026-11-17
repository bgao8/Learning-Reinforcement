"""NameGlossary and whisper_prompt: steering Whisper's spelling of names."""
from app.stt.names import NameGlossary, whisper_prompt


def heard(*sentences: str) -> NameGlossary:
    names = NameGlossary()
    for sentence in sentences:
        names.add(sentence.split())
    return names


def test_mid_sentence_capitals_are_names():
    assert heard("we drove the Corolla to Fuji today.").terms() == ["Corolla", "Fuji"]


def test_neighboring_names_join():
    assert heard("compared to a regular GR Corolla and I drove it").terms() == ["GR Corolla"]


def test_sentence_start_is_not_a_name_but_acronyms_are():
    assert heard("So we start. Then NASA tested it.").terms() == ["NASA"]


def test_punctuation_splits_names_and_is_stripped():
    assert heard("parts from Toyota, Subaru and Honda's team.").terms() == ["Toyota", "Subaru", "Honda"]


def test_sentence_start_carries_across_windows():
    names = NameGlossary()
    names.add("it was fast.".split())
    names.add("Anyway the Supra".split())   # new window, new sentence: "Anyway" is not a name
    assert names.terms() == ["Supra"]


def test_misspelling_counts_toward_the_usual_spelling():
    names = heard(
        "a regular GR Corolla here", "the GR Corolla again", "this GR Corolla now",
        "to improve GR of Carola so", "and Carola but",
    )
    assert "GR Corolla" in names.terms()
    assert "Carola" not in names.terms()


def test_different_names_stay_apart():
    assert sorted(heard("by Newton and by Norton").terms()) == ["Newton", "Norton"]


def test_most_heard_first_and_limited():
    names = heard("see Euler then Gauss and Gauss and Gauss with Euler")
    assert names.terms() == ["Gauss", "Euler"]
    assert names.terms(limit=1) == ["Gauss"]


def test_prompt_puts_title_then_names_then_recent_text():
    prompt = whisper_prompt("GR Corolla aero", ["Toyota", "Fuji"], "so the wing adds downforce")
    assert prompt == "GR Corolla aero. Toyota, Fuji. so the wing adds downforce"


def test_title_overrules_a_misspelled_name():
    assert whisper_prompt("GR Corolla aero", ["Carola", "Fuji"], "") == "GR Corolla aero. Fuji."


def test_prompt_is_none_with_nothing_to_say():
    assert whisper_prompt(None, [], "  ") is None


def test_recent_text_keeps_the_end_on_a_word_boundary():
    prompt = whisper_prompt(None, [], "alpha " * 100 + "omega")
    assert prompt.endswith("alpha omega") and len(prompt) <= 250
    assert not prompt.startswith("lpha")
