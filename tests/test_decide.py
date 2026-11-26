import pytest

from requiem.decide import Contract, Tracker, VariantWindow, judge_window

C = Contract(flag="new_checkout", experiment="New checkout", max_error_rate=0.05, min_requests=20,
             min_gap=0.02, breach_windows=3)


def w(requests, errors):
    return VariantWindow(requests=requests, errors=errors)


def test_breach_when_treatment_is_over_ceiling_and_worse_than_control():
    v = judge_window(C, {"control": w(100, 1), "new": w(100, 30)})
    assert v.breached and v.variant == "new"
    assert "30.0%" in v.reason and "control 1.0%" in v.reason


def test_no_breach_under_ceiling():
    assert not judge_window(C, {"control": w(100, 0), "new": w(100, 5)}).breached  # exactly 5% is allowed


def test_no_breach_without_enough_treatment_traffic():
    v = judge_window(C, {"control": w(100, 0), "new": w(19, 19)})
    assert not v.breached and "not enough treatment traffic" in v.reason


def test_outage_hitting_everyone_is_not_blamed_on_the_variant():
    # Both sides failing at ~30%: the new code isn't the cause, so don't kill it.
    assert not judge_window(C, {"control": w(100, 29), "new": w(100, 30)}).breached


def test_breach_with_no_control_traffic_still_counts():
    v = judge_window(C, {"new": w(50, 25)})
    assert v.breached and "no control traffic" in v.reason


def test_worst_of_several_variants_is_reported():
    v = judge_window(C, {"control": w(100, 0), "a": w(50, 10), "b": w(50, 40)})
    assert v.variant == "b"


def test_streak_needs_consecutive_breaches_and_resets():
    tr = Tracker(C)
    bad = {"control": w(100, 0), "new": w(100, 50)}
    good = {"control": w(100, 0), "new": w(100, 0)}
    tr.observe(bad)
    tr.observe(bad)
    assert not tr.should_act
    tr.observe(good)
    assert tr.streak == 0
    for _ in range(3):
        tr.observe(bad)
    assert tr.should_act


def test_empty_window_never_acts():
    tr = Tracker(C)
    for _ in range(5):
        tr.observe({})
    assert not tr.should_act


@pytest.mark.parametrize("kwargs", [{"max_error_rate": 0}, {"max_error_rate": 1.5}, {"breach_windows": 0},
                                    {"min_requests": 0}, {"on_breach": "maybe"}])
def test_bad_contracts_are_rejected(kwargs):
    with pytest.raises(ValueError):
        Contract(flag="f", experiment="e", **kwargs)
