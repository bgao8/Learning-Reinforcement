"""Mastery ratings (#25): Elo per (user, concept), as pure functions. No DB, no I/O.

How a rating changes after one graded answer (score 1 / 0.5 / 0 from grading):
- Calibrating (fewer than CALIBRATION_ATTEMPTS answers on this concept before this one):
  fixed steps, K_CALIBRATING × (score − 0.5) = +30 / 0 / −30. With so little data the
  rating can't predict anything yet, so it isn't used to scale the step.
- After that: weighted Elo, K × (score − expected). A result the rating predicted moves it
  a little; a surprising one moves it a lot. Strong concepts gain little from a right
  answer and lose a lot from a wrong one, so ratings level off instead of growing forever.

Every question is rated START_RATING. It must equal the starting rating, or a brand-new
learner would be predicted to fail and ratings would drift upward.

The overall rating is derived, never stored: the attempt-weighted average of the concepts
that finished calibrating. Weighting by attempts lets well-tested concepts count more;
gating on attempts (not on how high a rating is) keeps weak concepts in, so a wrong answer
can never raise the overall rating.

Ratings are clamped to 0..2000 (apply_change), so 1000 is the middle of the range.
A rating settles where predicted accuracy matches real accuracy on the concept. SCALE = 900
makes that 1500 ≈ 78% and 2000 ≈ 93% sustained. With K = 42, all-right answers reach 1500
after ~35 and 2000 after ~133: expert level, hard but reachable. (SCALE 600 meant 2000 ≈ 98%
but took ~265 straight right answers; chess's 400 would need 99.7%, which grader noise
alone makes impossible.)
"""
from collections.abc import Iterable

START_RATING = 1000.0       # new concepts start here; also the fixed rating of every question
CALIBRATION_ATTEMPTS = 3    # answers on a concept before the weighted model takes over
K_CALIBRATING = 60.0        # with expected fixed at 0.5: +30 right / 0 partial / −30 wrong
K = 42.0                    # weighted Elo step once calibrated: ±21 at the start rating
SCALE = 900.0               # a 900-point gap means 10-to-1 odds (chess uses 400; see module docstring)
MIN_RATING = 0.0            # ratings are clamped to [MIN_RATING, MAX_RATING]
MAX_RATING = 2000.0


def expected(rating: float, question_rating: float = START_RATING) -> float:
    """Predicted chance (0..1) of answering a question right, from the rating gap."""
    return 1.0 / (1.0 + 10.0 ** ((question_rating - rating) / SCALE))


def is_calibrating(attempts: int) -> bool:
    """True while a concept has too few answers for its rating to mean much."""
    return attempts < CALIBRATION_ATTEMPTS


def rating_change(rating: float, score: float, attempts_before: int) -> float:
    """How much one graded answer moves a concept's rating.

    attempts_before: graded answers on this concept before this one.
    """
    if not 0.0 <= score <= 1.0:
        raise ValueError(f"score must be in [0, 1], got {score}")
    if is_calibrating(attempts_before):
        return K_CALIBRATING * (score - 0.5)
    return K * (score - expected(rating))


def apply_change(rating: float, score: float, attempts_before: int) -> float:
    """The concept's new rating after one graded answer, clamped to [MIN_RATING, MAX_RATING]."""
    new = rating + rating_change(rating, score, attempts_before)
    return min(MAX_RATING, max(MIN_RATING, new))


def overall_rating(concepts: Iterable[tuple[float, int]]) -> float | None:
    """Attempt-weighted average of (rating, attempts) for concepts past calibration.

    None while no concept qualifies: there's no honest overall number yet.
    """
    rated = [(rating, attempts) for rating, attempts in concepts if not is_calibrating(attempts)]
    total = sum(attempts for _, attempts in rated)
    if total == 0:
        return None
    return sum(rating * attempts for rating, attempts in rated) / total


# mastery_tier's boundaries sit between rating steps, never on one, so a small change to K
# can't flip a concept to the next tier. In answers, starting from START_RATING:
WEAK_BELOW = START_RATING - 45         # 955: two net misses (940); one miss (970) is still "learning"
VERY_WEAK_BELOW = START_RATING - 120   # 880: about five misses in a row (873)
SOLID_FROM = START_RATING + 45         # 1045: two net right (1060); one right (1030) is still "learning"
VERY_SOLID_FROM = START_RATING + 120   # 1120: about five right in a row (1127)


def mastery_tier(elo: float | None) -> str:
    """How well the user knows a concept, as a word the question prompt acts on.

    "new" when there's no rating yet (asked about, never answered). One answer either way
    stays "learning": one right guess shouldn't skip practice, one slip shouldn't drill it.
    """
    if elo is None:
        return "new"
    if elo < VERY_WEAK_BELOW:
        return "very weak"
    if elo < WEAK_BELOW:
        return "weak"
    if elo < SOLID_FROM:
        return "learning"
    if elo < VERY_SOLID_FROM:
        return "solid"
    return "very solid"
