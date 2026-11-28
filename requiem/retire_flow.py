"""RETIRE, the live half: read Flagsmith's results, write the memo, and (on approval) act.

  python -m requiem.service retire <flag>                      writes the memo, changes nothing
  python -m requiem.service approve <flag> --memo <sha prefix> [--open-pr]
  python -m requiem.service open-pr <flag>                     push the retire branch, `gh pr create`

`approve` order, chosen so the one step that cannot be undone comes last:
  1. the memo file must hash to the prefix you typed (approval is bound to the exact bytes shown);
  2. in a temporary git worktree on a new branch, run the codemod on the committed code, drop the
     contract entry, compile, run the whole test suite; any unsupported pattern or failure stops here;
  3. commit on that branch (main is never touched, nothing is pushed);
  4. POST complete to Flagsmith (final: results freeze, the winner is served to everyone);
  5. write the PR body and an approval record under fixtures/retire/.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from requiem import retire as R
from requiem.codemod import remove_contract_entry, retire_flag
from requiem.decide import Contract
from requiem.flagsmith_api import FlagsmithAPI, FlagsmithError

ROOT = Path(__file__).resolve().parent.parent
RETIREMENTS = ROOT / "retirements"
FIXTURES = ROOT / "fixtures" / "retire"
DEFAULT_TRAFFIC = "not stated in requiem.yaml (retire.traffic)"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _parse_ts(s: str | None) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() if s else 0.0


def _refresh(api: FlagsmithAPI, exp_id: int, which: str, wait_s: float = 90) -> str:
    """Ask Flagsmith to recompute; wait until `as_of` catches up with the request. Rate-limited
    refreshes (5 min minimum gap) are not an error: we say so and use what Flagsmith has."""
    refresh = api.refresh_results if which == "results" else api.refresh_exposures
    read = api.results_raw if which == "results" else api.exposures_raw
    try:
        refresh(exp_id)
    except FlagsmithError as e:
        return f"{which}: refresh not accepted ({e.status}: {e.body[:120]}); used the last computed numbers"
    deadline = time.time() + wait_s
    while time.time() < deadline:
        body = (read(exp_id) or {}).get(which) or {}
        if body.get("as_of") and _parse_ts(body["as_of"]) >= _parse_ts(body.get("refresh_requested_at")):
            return f"{which}: refreshed, as_of {body['as_of']}"
        time.sleep(2)
    return f"{which}: refresh requested but not finished after {wait_s:.0f}s; used the last computed numbers"


def _git(*args: str, cwd: Path = ROOT, check: bool = True) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout


# ------------------------------------------------------------------------------- retire (memo only)

def make_memo(api: FlagsmithAPI, c: Contract, *, refresh: bool = True) -> tuple[Path, Path, dict]:
    retire_cfg = c.retire or {}
    exp = api.experiment_by_name(c.experiment)
    detail = api.experiment(exp.id)
    metrics = detail.get("metrics") or []
    want = retire_cfg.get("metric")
    metric = next((m for m in metrics if m["metric_name"] == want), None) if want else (metrics[0] if metrics else None)
    if metric is None:
        raise SystemExit(f"{c.flag}: experiment {exp.name!r} has no metric {want!r}" if want else f"{c.flag}: experiment has no metric")
    notes = []
    if refresh:
        notes = [_refresh(api, exp.id, "results"), _refresh(api, exp.id, "exposures")]
    results = api.results_raw(exp.id)
    exposures = api.exposures_raw(exp.id)
    stamp = _stamp()
    FIXTURES.mkdir(parents=True, exist_ok=True)
    rbytes = json.dumps(results, indent=2, sort_keys=True).encode() + b"\n"
    (FIXTURES / f"results_{stamp}_{c.flag}.json").write_bytes(rbytes)
    (FIXTURES / f"exposures_{stamp}_{c.flag}.json").write_bytes(json.dumps(exposures, indent=2, sort_keys=True).encode() + b"\n")

    declared = [v.key for v in exp.variants]
    snap = R.parse_results(results, exposures, metric_id=metric["metric"], metric_name=metric["metric_name"],
                           declared_variants=declared)
    rules = R.Rules.from_contract(c.retire)
    decision = R.decide(snap, rules)
    plan = None
    if decision.actionable:
        if not retire_cfg.get("code"):
            raise SystemExit(f"{c.flag}: requiem.yaml has no retire.code (the file holding the losing branch)")
        if decision.keep_variant == R.CONTROL:
            complete = {"rollout_decision": "control"}
            keep_value = str(exp.control_value)
        else:
            v = {x.key: x for x in exp.variants}[decision.keep_variant]  # type: ignore[index]
            complete = {"rollout_decision": "variant", "rollout_variant": v.option_id}
            keep_value = v.value
        plan = {"flagsmith": {"complete": complete},
                "code": {"file": retire_cfg["code"], "keep_variant": decision.keep_variant, "keep_value": keep_value},
                "contract": {"remove_entry": c.flag}}
    memo = R.build_memo(
        flag=c.flag, experiment={"id": exp.id, "name": exp.name, "status": detail["status"]},
        snap=snap, decision=decision, rules=rules,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        refresh_note="; ".join(notes) if notes else "not refreshed (--no-refresh)",
        plan=plan, traffic=str(retire_cfg.get("traffic", DEFAULT_TRAFFIC)),
        results_sha256=hashlib.sha256(rbytes).hexdigest(),
    )
    sha = R.memo_sha256(memo)
    RETIREMENTS.mkdir(exist_ok=True)
    jpath = RETIREMENTS / f"{stamp}_{c.flag}.json"
    mpath = RETIREMENTS / f"{stamp}_{c.flag}.md"
    jpath.write_bytes(R.memo_bytes(memo))
    mpath.write_text(R.render_markdown(memo, sha), encoding="utf-8")
    return mpath, jpath, memo


# ------------------------------------------------------------------------------- approve

def find_memo(flag: str, prefix: str) -> tuple[Path, dict, str]:
    hits = []
    for p in sorted(RETIREMENTS.glob(f"*_{flag}.json")):
        b = p.read_bytes()
        if R.sha_matches(b, prefix):
            hits.append((p, json.loads(b), hashlib.sha256(b).hexdigest()))
    if not hits:
        raise SystemExit(f"no memo for {flag} has a sha256 starting with {prefix!r} (need at least 8 hex characters). "
                         "Approval only works on the exact memo you were shown.")
    return hits[-1]


def approve(api: FlagsmithAPI, c: Contract, prefix: str, *, open_pr: bool = False, run_tests: bool = True) -> dict:
    memo_path, memo, sha = find_memo(c.flag, prefix)
    plan = memo.get("plan_on_approval")
    if not plan:
        raise SystemExit(f"memo says {memo['decision']['outcome']}: there is nothing to approve. {memo['decision']['reason']}")
    exp = api.experiment_by_name(c.experiment)
    if exp.id != memo["experiment"]["id"]:
        raise SystemExit("the experiment with that name is not the one in the memo")
    if api.experiment(exp.id)["status"] == "completed":
        raise SystemExit(f"experiment {exp.id} is already completed; nothing to do")

    ts = _stamp()
    branch = f"retire/{c.flag}-{ts}"
    wt = Path(tempfile.mkdtemp(prefix="requiem-retire-"))
    shutil.rmtree(wt)  # git wants to create it
    base = _git("rev-parse", "HEAD").strip()
    _git("worktree", "add", "-b", branch, str(wt), "HEAD")
    try:
        code_file = wt / plan["code"]["file"]
        src = code_file.read_text(encoding="utf-8")
        new, report = retire_flag(src, c.flag, keep_variant=plan["code"]["keep_variant"], keep_value=plan["code"]["keep_value"])
        if report.unsupported:
            raise SystemExit("codemod found patterns it will not rewrite, so nothing was changed in Flagsmith or git:\n" + report.text())
        if not report.changed:
            raise SystemExit("codemod changed nothing: no lookup of the flag found in " + plan["code"]["file"])
        code_file.write_text(new, encoding="utf-8", newline="")
        cfg = wt / "requiem.yaml"
        ytext, removed = remove_contract_entry(cfg.read_text(encoding="utf-8"), c.flag)
        cfg.write_text(ytext, encoding="utf-8", newline="")
        tests: dict = {"ran": False}
        if run_tests:
            r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"], cwd=wt,
                               capture_output=True, text=True, encoding="utf-8")
            out = r.stdout.strip().splitlines()
            tests = {"ran": True, "returncode": r.returncode, "summary": out[-1] if out else r.stderr[-300:]}
            if r.returncode:
                raise SystemExit("the test suite fails with the codemod's output; nothing was changed in Flagsmith:\n" + r.stdout[-1500:])
        _git("add", plan["code"]["file"], "requiem.yaml", cwd=wt)
        msg = (f"Retire flag {c.flag}: {memo['decision']['outcome']}, keep {plan['code']['keep_variant']}\n\n"
               f"{memo['decision']['reason']}\n\nDecision memo sha256: {sha}\nGenerated by Requiem's codemod.")
        _git("commit", "-m", msg, cwd=wt)
        patch = _git("diff", f"{base}..HEAD", cwd=wt)
        stat = _git("diff", "--stat", f"{base}..HEAD", cwd=wt)
        commit = _git("rev-parse", "HEAD", cwd=wt).strip()
    except BaseException:
        _git("worktree", "remove", "--force", str(wt), check=False)
        _git("branch", "-D", branch, check=False)
        raise
    _git("worktree", "remove", "--force", str(wt))

    # The one step that cannot be undone.
    decision = plan["flagsmith"]["complete"]
    try:
        resp = api.complete(exp.id, decision["rollout_decision"], decision.get("rollout_variant"))
    except FlagsmithError:
        _git("branch", "-D", branch, check=False)
        raise
    after = api.experiment(exp.id)

    FIXTURES.mkdir(parents=True, exist_ok=True)
    record = {
        "flag": c.flag, "approved_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "memo_file": memo_path.name, "memo_sha256": sha,
        "flagsmith": {"complete_request": decision, "complete_response": resp,
                      "experiment_after": {k: after.get(k) for k in ("id", "status", "ended_at", "rollout_decision", "rollout_variant")},
                      "served_after_complete": _served_after(c.flag)},
        "codemod": {"file": plan["code"]["file"], "rewrites": report.rewrites, "unsupported": report.unsupported},
        "contract_entry_removed": removed, "tests": tests,
        "git": {"branch": branch, "base_commit": base, "commit": commit, "diff_stat": stat, "patch": patch},
    }
    pr = RETIREMENTS / f"{memo_path.stem}_PR.md"
    pr.write_text(pr_body(memo, sha, record), encoding="utf-8")
    record["pr_body"] = pr.relative_to(ROOT).as_posix()
    if open_pr:
        record["pr_url"] = open_pull_request(branch, pr, c.flag, memo)
    (FIXTURES / f"approve_{ts}_{c.flag}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def _served_after(flag: str, n: int = 12) -> dict:
    """What the flags API serves to 12 of the load generator's identities now (remote evaluation)."""
    key, url = os.environ.get("FLAGSMITH_ENVIRONMENT_KEY"), os.environ.get("FLAGSMITH_URL", "http://localhost:8000")
    if not key:
        return {"checked": False}
    seen: dict[str, int] = {}
    for i in range(n):
        r = httpx.get(f"{url}/api/v1/identities/", params={"identifier": f"lg_{i:03d}"},
                      headers={"X-Environment-Key": key}, timeout=10)
        for f in r.json().get("flags", []):
            if f["feature"]["name"] == flag:
                v = str(f["feature_state_value"])
                seen[v] = seen.get(v, 0) + 1
    return {"checked": True, "identities": n, "values_served": seen}


def pr_body(memo: dict, sha: str, rec: dict) -> str:
    d = memo["decision"]
    head = [f"## Retire `{memo['flag']}`: {d['outcome']}", "",
            f"Approved against decision memo sha256 `{sha}`. Flagsmith experiment {memo['experiment']['id']} is completed "
            f"with `{json.dumps(rec['flagsmith']['complete_request'])}`.", "",
            f"This PR deletes the `{memo['flag']}` lookup, its span tags and the losing branch from `{rec['codemod']['file']}`, "
            "and removes the flag's entry from `requiem.yaml`. Generated by Requiem's LibCST codemod; "
            f"compile and the test suite passed on this branch (`{rec['tests'].get('summary', 'tests not run')}`).", "",
            "Codemod report:", ""] + [f"- {r}" for r in rec["codemod"]["rewrites"]] + ["", "---", ""]
    body = "\n".join(l for l in R.render_markdown(memo, sha).splitlines() if not l.startswith("Approve with:"))
    return "\n".join(head) + body + "\n"


def open_pull_request(branch: str, body_file: Path, flag: str, memo: dict) -> str:
    """Push the branch and open the PR with gh. Only ever called behind --open-pr / `open-pr`."""
    _git("push", "-u", "origin", branch)
    r = subprocess.run(["gh", "pr", "create", "--base", "main", "--head", branch,
                        "--title", f"Retire flag {flag}: {memo['decision']['outcome']}",
                        "--body-file", str(body_file)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if r.returncode:
        raise RuntimeError(f"gh pr create failed: {r.stderr.strip()}")
    return r.stdout.strip()
