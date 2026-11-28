"""RETIRE decision rules and the memo's hash binding. Pure code, no Flagsmith needed."""

import json
from pathlib import Path

import pytest

from requiem import retire as R
from requiem import retire_flow as rf
from requiem.decide import Contract

ROOT = Path(__file__).resolve().parent.parent


def results_body(variants, inference, srm=None, metric_id=1):
    """Same shape as Flagsmith's GET .../results/ (see fixtures/spike1/15_results.json)."""
    return {"results": {"as_of": "2026-11-28T10:00:00Z", "payload": {
        "metrics": [{"metric_id": metric_id, "variants": variants, "inference": inference}],
        "srm_p_value": srm}, "is_final": False}}


def v(n, conv):
    return {"n": n, "sum": float(conv), "sum_squares": float(conv)}


def inf(chance, lift=0.5):
    return {"lift": lift, "ci_low": lift - 0.4, "ci_high": lift + 0.4, "chance_to_win": chance}


def snap(control=(100, 20), green=(100, 40), chance=0.99, srm=0.5, excluded=0, extra=None):
    variants = {"control": v(*control), "green": v(*green), **(extra or {})}
    body = results_body(variants, {"green": inf(chance)}, srm=srm)
    exposures = {"exposures": {"payload": {"excluded_identities": excluded}}}
    return R.parse_results(body, exposures, metric_id=1, metric_name="purchase", declared_variants=["green"])


def test_real_spike_payload_is_a_win_and_the_stray_row_is_ignored():
    body = json.loads((ROOT / "fixtures/spike1/15_results.json").read_text())["body"]
    s = R.parse_results(body, None, metric_id=1, metric_name="purchase", declared_variants=["green"])
    assert s.ignored_variants == ("grey",)  # the spike's mislabelled batch
    d = R.decide(s)
    assert d.outcome == R.WIN and d.keep_variant == "green"
    assert d.chance_to_win == pytest.approx(0.99364731845178)
    srm = next(c for c in d.checks if c.name == "srm")
    assert srm.passed and "not checked" in srm.detail  # Flagsmith sent srm_p_value null


def test_win():
    d = R.decide(snap(chance=0.97))
    assert (d.outcome, d.keep_variant) == (R.WIN, "green")


def test_win_bar_is_inclusive():
    assert R.decide(snap(chance=0.95)).outcome == R.WIN
    assert R.decide(snap(chance=0.9499)).outcome == R.INCONCLUSIVE


def test_lose_keeps_control():
    d = R.decide(snap(chance=0.02))
    assert (d.outcome, d.keep_variant) == (R.LOSE, "control")
    assert R.decide(snap(chance=0.05)).outcome == R.LOSE  # bar is inclusive
    assert R.decide(snap(chance=0.0501)).outcome == R.INCONCLUSIVE


def test_middle_is_inconclusive():
    d = R.decide(snap(chance=0.7))
    assert d.outcome == R.INCONCLUSIVE and "0.7000" in d.reason and not d.actionable


def test_too_few_identities_is_inconclusive_even_with_a_great_chance():
    d = R.decide(snap(green=(49, 30), chance=0.999))
    assert d.outcome == R.INCONCLUSIVE and "green has 49 identities" in d.reason
    assert R.decide(snap(green=(50, 30), chance=0.999)).outcome == R.WIN  # 50 is enough


def test_too_few_conversions_is_inconclusive():
    d = R.decide(snap(control=(100, 4), chance=0.999))
    assert d.outcome == R.INCONCLUSIVE and "control has 100 identities / 4 conversions" in d.reason
    assert R.decide(snap(control=(100, 5), chance=0.999)).outcome == R.WIN


def test_srm_below_flagsmiths_line_blocks_even_a_perfect_result():
    d = R.decide(snap(chance=0.999, srm=0.0004))
    assert d.outcome == R.SRM_BLOCK and "0.0004" in d.reason and not d.actionable


def test_srm_exactly_at_the_line_passes():
    assert R.decide(snap(chance=0.999, srm=0.001)).outcome == R.WIN


def test_srm_is_flagsmiths_number_not_recomputed():
    # A split that looks lopsided (150 v 50) but with Flagsmith's srm_p_value healthy is not blocked by us.
    assert R.decide(snap(control=(150, 40), green=(50, 20), chance=0.99, srm=0.4)).outcome == R.WIN


def test_many_excluded_identities_block():
    d = R.decide(snap(chance=0.999, excluded=30))  # 30 of 230 = 13%
    assert d.outcome == R.SRM_BLOCK and "excluded" in d.reason
    assert R.decide(snap(chance=0.999, excluded=10)).outcome == R.WIN  # 10 of 210 = 4.8%


def test_no_results_yet():
    assert R.decide(None).outcome == R.INCONCLUSIVE
    assert R.parse_results({"results": None}, None, metric_id=1, metric_name="p", declared_variants=["green"]) is None
    assert R.parse_results(results_body({}, {}, metric_id=9), None, metric_id=1, metric_name="p", declared_variants=["green"]) is None


def test_missing_inference_is_inconclusive():
    body = results_body({"control": v(100, 20), "green": v(100, 40)}, {})
    s = R.parse_results(body, None, metric_id=1, metric_name="purchase", declared_variants=["green"])
    assert R.decide(s).outcome == R.INCONCLUSIVE


def test_two_variants_best_one_wins():
    body = results_body({"control": v(100, 20), "a": v(100, 30), "b": v(100, 45)}, {"a": inf(0.9), "b": inf(0.98)})
    s = R.parse_results(body, None, metric_id=1, metric_name="purchase", declared_variants=["a", "b"])
    d = R.decide(s)
    assert d.outcome == R.WIN and d.keep_variant == "b"


def test_contract_can_raise_the_win_bar():
    rules = R.Rules.from_contract({"win_probability": 0.99})
    assert R.decide(snap(chance=0.97), rules).outcome == R.INCONCLUSIVE
    with pytest.raises(ValueError):
        R.Rules.from_contract({"win_probability": 1.5})


# ---- contract loader accepts the keys other parts of Requiem use

def test_contract_accepts_owner_dies_on_and_retire():
    c = Contract(flag="f", experiment="E", owner="@me", dies_on="2026-12-15", retire={"metric": "purchase"})
    assert c.dies_on == "2026-12-15" and c.retire["metric"] == "purchase"
    import datetime
    assert Contract(flag="f", experiment="E", dies_on=datetime.date(2026, 12, 15)).dies_on == "2026-12-15"
    with pytest.raises(ValueError):
        Contract(flag="f", experiment="E", dies_on="15/12/2026")


def test_repo_requiem_yaml_loads():
    from requiem.service import load_contracts
    contracts, _ = load_contracts(ROOT / "requiem.yaml")  # still loads once a flag's entry is retired
    assert all(c.flag and c.experiment for c in contracts)


def test_loader_reads_the_new_optional_keys(tmp_path):
    from requiem.service import load_contracts
    f = tmp_path / "r.yaml"
    f.write_text("flags:\n  x:\n    experiment: X\n    owner: '@me'\n    dies_on: 2026-12-15\n"
                 "    retire:\n      metric: purchase\n      code: a.py\n", encoding="utf-8")
    (c,), _ = load_contracts(f)
    assert (c.owner, c.dies_on, c.retire["code"]) == ("@me", "2026-12-15", "a.py")


# ---- memo + hash binding

def make_memo(decision_snap):
    d = R.decide(decision_snap)
    plan = {"flagsmith": {"complete": {"rollout_decision": "variant", "rollout_variant": 1}},
            "code": {"file": "shop/app.py", "keep_variant": "green", "keep_value": "green"},
            "contract": {"remove_entry": "buy_button"}} if d.actionable else None
    return R.build_memo(flag="buy_button", experiment={"id": 1, "name": "Green buy button", "status": "running"},
                        snap=decision_snap, decision=d, rules=R.Rules(), created_at="2026-11-28T10:00:00+00:00",
                        refresh_note="test", plan=plan, traffic="load-generated", results_sha256="ab" * 32)


def test_memo_hash_is_over_the_exact_file_bytes():
    memo = make_memo(snap())
    b = R.memo_bytes(memo)
    sha = R.memo_sha256(memo)
    assert R.sha_matches(b, sha[:12]) and R.sha_matches(b, sha) and R.sha_matches(b, sha[:12].upper())
    assert not R.sha_matches(b, "0" * 12)
    assert not R.sha_matches(b, sha[:7])  # too short to bind anything
    assert not R.sha_matches(b + b" ", sha[:12])  # one changed byte breaks approval
    tampered = json.loads(b)
    tampered["plan_on_approval"]["flagsmith"]["complete"]["rollout_variant"] = 2
    assert not R.sha_matches(json.dumps(tampered, indent=2, sort_keys=True).encode() + b"\n", sha[:12])


def test_memo_markdown_shows_numbers_decision_hash_and_plan():
    memo = make_memo(snap(chance=0.97))
    sha = R.memo_sha256(memo)
    md = R.render_markdown(memo, sha)
    assert sha in md and "WIN" in md and "0.9700" in md and "Flagsmith" in md
    assert "/complete/" in md and "approve buy_button --memo " + sha[:12] in md and "requiem.yaml" in md


def test_inconclusive_memo_has_no_plan_and_says_so():
    memo = make_memo(snap(chance=0.6))
    assert memo["plan_on_approval"] is None
    assert "Nothing. A decision of INCONCLUSIVE cannot be approved" in R.render_markdown(memo, "a" * 64)


class NoApi:
    def __getattr__(self, name):  # any Flagsmith call in these tests is a bug
        raise AssertionError(f"approve touched Flagsmith ({name}) before the memo checks passed")


def test_approve_refuses_unknown_hash_and_non_actionable_memos(tmp_path, monkeypatch):
    monkeypatch.setattr(rf, "RETIREMENTS", tmp_path)
    c = Contract(flag="buy_button", experiment="Green buy button")
    win, hold = make_memo(snap(chance=0.99)), make_memo(snap(chance=0.6))
    (tmp_path / "20261128T100000Z_buy_button.json").write_bytes(R.memo_bytes(win))
    (tmp_path / "20261128T110000Z_buy_button.json").write_bytes(R.memo_bytes(hold))
    with pytest.raises(SystemExit, match="no memo"):
        rf.approve(NoApi(), c, "deadbeefdead")
    with pytest.raises(SystemExit, match="no memo"):
        rf.approve(NoApi(), c, R.memo_sha256(win)[:6])
    with pytest.raises(SystemExit, match="nothing to approve"):
        rf.approve(NoApi(), c, R.memo_sha256(hold)[:12])
