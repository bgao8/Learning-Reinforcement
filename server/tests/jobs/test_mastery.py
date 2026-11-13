"""Spec for the mastery rating rules (#25). Pure functions: no DB, no model.

- Ratings and questions start at 1000.
- The first 3 answers on a concept move it by fixed steps: +30 right, 0 partial, −30 wrong.
- From the 4th answer on: weighted Elo, K = 42 × (score − expected).
- SCALE 900: a 900-point gap is 10-to-1 odds, so 1500 ≈ 78% and 2000 ≈ 93% sustained accuracy.
- All right answers: 1500 after 35, 2000 after 133.
- Ratings are clamped to 0..2000.
- Overall = attempt-weighted average of concepts with 3+ answers; None until one exists.
"""
import pytest

from app.jobs.mastery import (
    CALIBRATION_ATTEMPTS, MAX_RATING, MIN_RATING, START_RATING, apply_change, expected, is_calibrating,
    overall_rating, rating_change,
)


# --- expected ---

def test_equal_ratings_are_a_coin_flip():
    assert expected(1000) == pytest.approx(0.5)


@pytest.mark.parametrize("rating, chance", [(100, 0.0909), (550, 0.2403), (1450, 0.7597), (1900, 0.9091)])
def test_rating_gap_sets_the_odds(rating, chance):
    # SCALE 900: 450 points ≈ 76%, 900 points = 10-to-1
    assert expected(rating) == pytest.approx(chance, abs=1e-4)


def test_stronger_is_always_more_likely():
    assert expected(900) < expected(1000) < expected(1100)


# --- calibration: fixed steps for the first 3 answers ---

@pytest.mark.parametrize("attempts_before", [0, 1, 2])
@pytest.mark.parametrize("rating", [700, 1000, 1400])
def test_calibrating_steps_are_fixed_at_any_rating(rating, attempts_before):
    assert rating_change(rating, 1.0, attempts_before) == pytest.approx(30)
    assert rating_change(rating, 0.5, attempts_before) == pytest.approx(0)
    assert rating_change(rating, 0.0, attempts_before) == pytest.approx(-30)


def test_weighted_model_starts_at_the_fourth_answer():
    # at 1200 the weighted model differs from the fixed step, so the switch is visible
    assert rating_change(1200, 1.0, attempts_before=2) == pytest.approx(30)
    assert rating_change(1200, 1.0, attempts_before=3) == pytest.approx(15.74, abs=0.01)


def test_is_calibrating_matches_the_threshold():
    assert [is_calibrating(n) for n in range(5)] == [True, True, True, False, False]
    assert CALIBRATION_ATTEMPTS == 3


# --- weighted Elo after calibration ---

def test_at_the_start_rating_it_is_plus_minus_twenty_one():
    assert rating_change(START_RATING, 1.0, 3) == pytest.approx(21)
    assert rating_change(START_RATING, 0.0, 3) == pytest.approx(-21)


def test_strong_concept_gains_little_and_loses_a_lot():
    assert rating_change(1200, 1.0, 5) == pytest.approx(15.74, abs=0.01)
    assert rating_change(1200, 0.0, 5) == pytest.approx(-26.26, abs=0.01)


def test_weak_concept_gains_a_lot_and_loses_little():
    assert rating_change(800, 1.0, 5) == pytest.approx(26.26, abs=0.01)
    assert rating_change(800, 0.0, 5) == pytest.approx(-15.74, abs=0.01)


def test_partial_credit_depends_on_what_was_expected():
    assert rating_change(1000, 0.5, 5) == pytest.approx(0)
    assert rating_change(1200, 0.5, 5) < 0   # expected to get it fully right
    assert rating_change(800, 0.5, 5) > 0    # expected to miss it


def test_repeated_right_answers_level_off():
    rating, steps = START_RATING, []
    for attempts_before in range(30):
        step = rating_change(rating, 1.0, attempts_before)
        steps.append(step)
        rating = apply_change(rating, 1.0, attempts_before)
    after_calibration = steps[CALIBRATION_ATTEMPTS:]
    assert all(a > b for a, b in zip(after_calibration, after_calibration[1:]))   # each gain smaller
    # 4th answer +18.59 → 30th answer +10.09 (rating 1460): shrinking steadily
    assert after_calibration[-1] < after_calibration[0] * 0.6


@pytest.mark.parametrize("score", [-0.1, 1.5])
def test_score_outside_zero_to_one_is_rejected(score):
    with pytest.raises(ValueError):
        rating_change(1000, score, 0)


# --- clamping ---

def test_apply_change_adds_the_step():
    assert apply_change(1000, 1.0, 0) == pytest.approx(1030)
    assert apply_change(1000, 0.0, 5) == pytest.approx(979)


def test_rating_never_goes_above_2000():
    assert MAX_RATING == 2000
    assert apply_change(1990, 1.0, 0) == 2000      # +30 would overshoot
    assert apply_change(2000, 1.0, 10) == 2000


def test_rating_never_goes_below_0():
    assert MIN_RATING == 0
    assert apply_change(10, 0.0, 0) == 0           # −30 would undershoot
    assert apply_change(0, 0.0, 10) == 0


def test_a_capped_rating_still_drops_on_a_wrong_answer():
    assert apply_change(2000, 0.0, 10) < 2000


# --- overall rating ---

def test_no_concepts_means_no_overall():
    assert overall_rating([]) is None


def test_only_calibrating_concepts_means_no_overall():
    assert overall_rating([(1040, 2), (980, 1)]) is None


def test_overall_is_weighted_by_attempts():
    # (1300 × 6 + 1000 × 3) / 9 = 1200
    assert overall_rating([(1300, 6), (1000, 3)]) == pytest.approx(1200)


def test_calibrating_concepts_are_left_out():
    assert overall_rating([(1100, 4), (900, 2)]) == pytest.approx(1100)


def test_weak_concepts_count_once_calibrated():
    # gating on attempts, not on rating: a weak concept still pulls the overall down
    assert overall_rating([(1200, 3), (850, 3)]) == pytest.approx(1025)


def test_a_wrong_answer_never_raises_the_overall():
    # the case that ruled out "only count concepts above 1100": with that rule, missing a
    # question on the 1110 concept dropped it below the cutoff and the overall went UP
    strong, weak = (1300.0, 5), (1110.0, 3)
    before = overall_rating([strong, weak])
    weak_after = (weak[0] + rating_change(weak[0], 0.0, weak[1]), weak[1] + 1)
    after = overall_rating([strong, weak_after])
    assert after < before


@pytest.mark.parametrize("rating, accuracy", [(1500, 0.782), (2000, 0.928)])
def test_rating_levels_mean_sustained_accuracy(rating, accuracy):
    # a rating settles where predicted accuracy = real accuracy: 2000 needs ~93%, expert level
    assert expected(rating) == pytest.approx(accuracy, abs=0.001)


def test_all_right_answers_reach_1500_after_35_and_2000_after_133():
    # the pacing agreed for #25: 1500 is solid, 2000 is hard but reachable
    rating, reached = START_RATING, {}
    for answers in range(1, 400):
        rating = apply_change(rating, 1.0, answers - 1)
        for target in (1500, 2000):
            if target not in reached and rating >= target:
                reached[target] = answers
    assert reached == {1500: 35, 2000: 133}
