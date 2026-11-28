"""The RETIRE decision and the decision memo, as plain code (no LLM, no I/O).

Flagsmith computes the statistics: per-variant chance_to_win, lift and interval, a sample ratio
mismatch p-value (`srm_p_value`) and the number of identities it quarantined because they saw
two variants (`excluded_identities`). Requiem does not recompute any of that (D-010). It only
reads those numbers, applies the thresholds in `Rules`, and says WIN, LOSE, INCONCLUSIVE or
SRM_BLOCK. A human approves; nothing here touches Flagsmith or the repo.

Order of the checks matters: a broken split makes every later number meaningless, so SRM and
quarantine come first, then "is there enough data", then the win/lose call.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

CONTROL = "control"
WIN, LOSE, INCONCLUSIVE, SRM_BLOCK = "WIN", "LOSE", "INCONCLUSIVE", "SRM_BLOCK"


@dataclass(frozen=True)
class Rules:
    # Flagsmith's experimentation docs: its results page suggests rolling out at a 95% chance of
    # beating control. Same bar here, so Requiem never calls a win Flagsmith itself would not suggest.
    win_chance: float = 0.95
    # Mirror image: a variant with <= 5% chance of beating control is a clear loser, keep control.
    lose_chance: float = 0.05
    # Flagsmith shows "collecting data" (no inference) below 50 identities per variant
    # (RESULTS_MIN_IDENTITIES_PER_VARIANT in experimentation/constants.py), so we cannot decide below it.
    min_identities: int = 50
    # ...and below 5 converting identities per variant (RESULTS_MIN_CONVERSIONS_PER_VARIANT).
    min_conversions: int = 5
    # Flagsmith's own docstring on srm_p_value: "A tiny value (< 0.001 by convention) means the
    # split is broken and the results can't be trusted." We use the same line.
    srm_block_p: float = 0.001
    # Our own policy, not Flagsmith's: if more than 5% of everyone exposed saw two variants and was
    # dropped from the results, the people left may not represent the audience. Block and look.
    max_excluded_share: float = 0.05

    @staticmethod
    def from_contract(retire: dict | None) -> "Rules":
        """`retire:` block in requiem.yaml may set `win_probability` (the PLAN's name for win_chance)."""
        r = Rules()
        if retire and "win_probability" in retire:
            wp = float(retire["win_probability"])
            if not 0.5 < wp < 1:
                raise ValueError("retire.win_probability must be between 0.5 and 1")
            r = Rules(win_chance=wp)
        return r


@dataclass(frozen=True)
class VariantNumbers:
    key: str
    identities: int
    conversions: float
    conversion_rate: float | None
    lift: float | None = None  # vs control; None for control and while Flagsmith is still collecting
    ci_low: float | None = None
    ci_high: float | None = None
    chance_to_win: float | None = None


@dataclass(frozen=True)
class Snapshot:
    """The numbers Flagsmith returned, picked out of its payloads."""

    as_of: str | None
    metric: str
    srm_p_value: float | None
    excluded_identities: int
    variants: tuple[VariantNumbers, ...]  # control first, then the declared variants
    ignored_variants: tuple[str, ...] = ()  # rows in the results that no option of the flag declares


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    keep_variant: str | None  # variant key whose code survives: the winner, or "control"
    chance_to_win: float | None
    lift: float | None
    checks: tuple[Check, ...] = field(default_factory=tuple)

    @property
    def actionable(self) -> bool:
        return self.outcome in (WIN, LOSE)


def parse_results(
    results_body: dict | None,
    exposures_body: dict | None,
    *,
    metric_id: int,
    metric_name: str,
    declared_variants: list[str],
) -> Snapshot | None:
    """Pick the numbers for one metric out of Flagsmith's `/results/` and `/exposures/` bodies.

    `declared_variants` are the keys of the flag's options. Rows for any other key (the spike's
    stray `grey` row is the example) are not part of this experiment's decision and are listed.
    Returns None when Flagsmith has not produced a results payload yet.
    """
    res = (results_body or {}).get("results")
    payload = (res or {}).get("payload") if res else None
    if not payload:
        return None
    metric = next((m for m in payload.get("metrics", []) if m.get("metric_id") == metric_id), None)
    if metric is None:
        return None
    stats, inference = metric.get("variants", {}), metric.get("inference", {})
    ordered = [CONTROL] + [v for v in declared_variants if v != CONTROL]
    rows = []
    for key in ordered:
        s = stats.get(key)
        if s is None:
            rows.append(VariantNumbers(key, 0, 0.0, None))
            continue
        n, conv = int(s["n"]), float(s["sum"])  # occurrence metric: sum = identities that converted
        inf = inference.get(key) or {}
        rows.append(VariantNumbers(key, n, conv, conv / n if n else None, inf.get("lift"), inf.get("ci_low"),
                                   inf.get("ci_high"), inf.get("chance_to_win")))
    excluded = ((exposures_body or {}).get("exposures") or {}).get("payload", {}).get("excluded_identities", 0)
    return Snapshot(
        as_of=res.get("as_of"), metric=metric_name, srm_p_value=payload.get("srm_p_value"),
        excluded_identities=int(excluded or 0), variants=tuple(rows),
        ignored_variants=tuple(sorted(k for k in stats if k not in ordered)),
    )


def decide(snap: Snapshot | None, rules: Rules = Rules()) -> Decision:
    checks: list[Check] = []
    if snap is None:
        return Decision(INCONCLUSIVE, "Flagsmith has no results for this experiment yet.", None, None, None)

    # 1. Is the split trustworthy? Flagsmith's number, Flagsmith's convention.
    if snap.srm_p_value is None:
        checks.append(Check("srm", True, "Flagsmith reported no srm_p_value (fewer than 100 identities, or the "
                                        "environment default split is not set); not checked"))
    else:
        ok = snap.srm_p_value >= rules.srm_block_p
        checks.append(Check("srm", ok, f"srm_p_value {snap.srm_p_value:.4g} (block below {rules.srm_block_p})"))
        if not ok:
            return Decision(SRM_BLOCK, f"Sample ratio mismatch: srm_p_value {snap.srm_p_value:.4g} is below "
                            f"{rules.srm_block_p}, so traffic was not split as configured and the results "
                            "cannot be trusted.", None, None, None, tuple(checks))
    exposed = sum(v.identities for v in snap.variants)
    share = snap.excluded_identities / (exposed + snap.excluded_identities) if exposed + snap.excluded_identities else 0
    ok = share <= rules.max_excluded_share
    checks.append(Check("excluded", ok, f"{snap.excluded_identities} identities saw two variants and were dropped "
                                        f"({share:.1%} of those exposed; block above {rules.max_excluded_share:.0%})"))
    if not ok:
        return Decision(SRM_BLOCK, f"{share:.1%} of exposed identities saw more than one variant and were "
                        f"excluded (limit {rules.max_excluded_share:.0%}); look at how the flag is evaluated "
                        "before trusting this.", None, None, None, tuple(checks))

    # 2. Enough data in every arm?
    short = [v for v in snap.variants if v.identities < rules.min_identities or v.conversions < rules.min_conversions]
    checks.append(Check("samples", not short,
                        "; ".join(f"{v.key}: {v.identities} identities, {v.conversions:.0f} conversions" for v in snap.variants)
                        + f" (need {rules.min_identities} identities and {rules.min_conversions} conversions each)"))
    if short:
        return Decision(INCONCLUSIVE, "Not enough data yet: " + ", ".join(
            f"{v.key} has {v.identities} identities / {v.conversions:.0f} conversions" for v in short)
            + f" (Flagsmith needs {rules.min_identities} / {rules.min_conversions} per variant).",
            None, None, None, tuple(checks))

    # 3. The call.
    cand = [v for v in snap.variants if v.key != CONTROL]
    if any(v.chance_to_win is None for v in cand):
        return Decision(INCONCLUSIVE, "Flagsmith returned no inference for a variant.", None, None, None, tuple(checks))
    best = max(cand, key=lambda v: v.chance_to_win)  # type: ignore[arg-type,return-value]
    if best.chance_to_win >= rules.win_chance:  # type: ignore[operator]
        checks.append(Check("win", True, f"{best.key} chance_to_win {best.chance_to_win:.4f} >= {rules.win_chance}"))
        return Decision(WIN, f"`{best.key}` beats control with chance_to_win {best.chance_to_win:.4f} "
                        f"(bar {rules.win_chance}) and lift {best.lift:+.1%}.", best.key, best.chance_to_win,
                        best.lift, tuple(checks))
    if all(v.chance_to_win <= rules.lose_chance for v in cand):  # type: ignore[operator]
        checks.append(Check("lose", True, f"every variant chance_to_win <= {rules.lose_chance}"))
        return Decision(LOSE, f"Control beats every variant: best chance_to_win is {best.chance_to_win:.4f} "
                        f"(at or under {rules.lose_chance}). Keep control.", CONTROL, best.chance_to_win,
                        best.lift, tuple(checks))
    checks.append(Check("call", False, f"best chance_to_win {best.chance_to_win:.4f} is between "
                                       f"{rules.lose_chance} and {rules.win_chance}"))
    return Decision(INCONCLUSIVE, f"Enough data but no clear result: best variant `{best.key}` has chance_to_win "
                    f"{best.chance_to_win:.4f}, between {rules.lose_chance} and {rules.win_chance}.",
                    None, best.chance_to_win, best.lift, tuple(checks))


# ----------------------------------------------------------------- the memo

def build_memo(
    *,
    flag: str,
    experiment: dict,
    snap: Snapshot | None,
    decision: Decision,
    rules: Rules,
    created_at: str,
    refresh_note: str,
    plan: dict | None,
    traffic: str,
    results_sha256: str | None,
) -> dict[str, Any]:
    """Everything the human is asked to approve, as one JSON-able dict. `plan` is None unless
    the decision is WIN or LOSE: INCONCLUSIVE and SRM_BLOCK approve nothing."""
    return {
        "schema": 1,
        "flag": flag,
        "created_at_utc": created_at,
        "experiment": experiment,  # id, name, status as seen when the memo was written
        "traffic": traffic,
        "results_refresh": refresh_note,
        "results_response_sha256": results_sha256,
        "rules": asdict(rules),
        "snapshot": asdict(snap) if snap else None,
        "decision": {**{k: v for k, v in asdict(decision).items() if k != "checks"},
                     "checks": [asdict(c) for c in decision.checks]},
        "plan_on_approval": plan,
    }


def memo_bytes(memo: dict) -> bytes:
    """The exact bytes written to the .json file, and the ones that get hashed."""
    return (json.dumps(memo, indent=2, sort_keys=True) + "\n").encode("utf-8")


def memo_sha256(memo: dict) -> str:
    return hashlib.sha256(memo_bytes(memo)).hexdigest()


def sha_matches(memo_file_bytes: bytes, prefix: str) -> bool:
    """Approval binding: the prefix given on the command line must start the sha256 of the file."""
    prefix = prefix.strip().lower()
    return len(prefix) >= 8 and hashlib.sha256(memo_file_bytes).hexdigest().startswith(prefix)


def render_markdown(memo: dict, sha: str) -> str:
    d, s, e = memo["decision"], memo["snapshot"], memo["experiment"]
    L = [f"# Retire `{memo['flag']}`: {d['outcome']}", "",
         f"- Experiment: **{e['name']}** (id {e['id']}, status when written: {e['status']})",
         f"- Written (UTC): {memo['created_at_utc']}",
         f"- Decision memo sha256: `{sha}`",
         f"- Traffic: {memo['traffic']}", "",
         "## Decision", "", d["reason"], ""]
    if s:
        L += [f"## Numbers from Flagsmith (metric `{s['metric']}`, results as of {s['as_of']})", "",
              "| variant | identities | conversions | rate | lift vs control | 95% interval | chance to win |",
              "|---|---|---|---|---|---|---|"]
        for v in s["variants"]:
            f = lambda x, p=False: "n/a" if x is None else (f"{x:+.1%}" if p else f"{x:.4f}")  # noqa: E731
            rate = "n/a" if v["conversion_rate"] is None else f"{v['conversion_rate']:.1%}"
            ci = "n/a" if v["ci_low"] is None else f"{v['ci_low']:+.1%} to {v['ci_high']:+.1%}"
            L.append(f"| {v['key']} | {v['identities']} | {v['conversions']:.0f} | {rate} | {f(v['lift'], True)} | {ci} | {f(v['chance_to_win'])} |")
        srm = "not reported by Flagsmith" if s["srm_p_value"] is None else f"{s['srm_p_value']:.4g}"
        L += ["", f"- `srm_p_value` (Flagsmith's): {srm}",
              f"- Identities Flagsmith excluded for seeing two variants: {s['excluded_identities']}"]
        if s["ignored_variants"]:
            L.append(f"- Rows in the results that this flag has no option for, ignored: {', '.join(s['ignored_variants'])}")
        L.append(f"- Results refresh: {memo['results_refresh']}")
    L += ["", "## Checks", ""] + [f"- {'pass' if c['passed'] else 'FAIL'} `{c['name']}`: {c['detail']}" for c in d["checks"]]
    r = memo["rules"]
    L += ["", "## Thresholds used (requiem/retire.py `Rules`)", "",
          f"- win at chance_to_win >= {r['win_chance']}; lose at <= {r['lose_chance']}",
          f"- at least {r['min_identities']} identities and {r['min_conversions']} conversions per variant (Flagsmith's own minimums)",
          f"- block if srm_p_value < {r['srm_block_p']}, or if more than {r['max_excluded_share']:.0%} of exposed identities were excluded", ""]
    p = memo["plan_on_approval"]
    L += ["## What happens on approval", ""]
    if not p:
        L += [f"Nothing. A decision of {d['outcome']} cannot be approved; `approve` refuses it.", ""]
    else:
        L += [f"1. Flagsmith: `POST .../experiments/{e['id']}/complete/` with `{json.dumps(p['flagsmith']['complete'])}`. "
              "The experiment is completed (final), the flag serves the kept variant to everyone, and the rollout override is removed.",
              f"2. Code: remove the `{memo['flag']}` lookup, its span tags and the losing branch from `{p['code']['file']}`, "
              f"keeping variant `{p['code']['keep_variant']}` (value `{p['code']['keep_value']}`). "
              "Patterns the codemod does not understand are listed and block the approval.",
              f"3. Contract: remove the `{memo['flag']}` entry from `requiem.yaml`.",
              f"4. Git: create branch `retire/{memo['flag']}-<timestamp>` with that diff, after compile and the test suite pass. "
              "Nothing is pushed; opening the PR is a separate `--open-pr` step.", "",
              f"Approve with: `python -m requiem.service approve {memo['flag']} --memo {sha[:12]}`", ""]
    L += ["The numbers above were produced by code from Flagsmith's responses. No model wrote or changed them."]
    return "\n".join(L) + "\n"
