"""NAG: fail the build when a feature flag is past its `dies_on` date.

  python -m requiem.nag [--config requiem.yaml] [--root .] [--warn-days 14]
                        [--no-fail-on-overdue] [--open-issue] [--today YYYY-MM-DD] [--include-docs]

Reads `owner:` and `dies_on: YYYY-MM-DD` per flag from requiem.yaml, scans the repo for every
reference to each flag key (file:line; prose files only with --include-docs; in a git work tree,
only files git tracks or would track), and reports:
  - GitHub workflow annotations (`::error file=..,line=..::msg`, `::warning ...`) on stdout,
  - a markdown job summary appended to $GITHUB_STEP_SUMMARY when that variable is set,
  - exit code 1 if any flag is overdue (or has a malformed date) and fail-on-overdue is on.
A flag with no `dies_on` gets a warning, never a failure.

Optional, read-only: with FLAGSMITH_URL, FLAGSMITH_ADMIN_TOKEN and FLAGSMITH_ENVIRONMENT_KEY set,
NAG also asks Flagsmith (GET requests only) whether the flag still exists and whether it is still
in an experiment. `--open-issue` creates or updates one GitHub issue per overdue flag through the
`gh` CLI; it is off by default and is the only thing here that writes anywhere.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import yaml

SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache",
             ".ruff_cache", "fixtures", "incidents", "retirements", "dist", "build", ".idea", ".vscode"}
DOC_SUFFIXES = {".md", ".rst", ".txt"}
MAX_FILE_BYTES = 1_000_000
MAX_REF_ANNOTATIONS = 10  # per flag; GitHub shows only the first few per step anyway

OVERDUE, DUE_SOON, OK, NO_DATE, BAD_DATE = "overdue", "due_soon", "ok", "no_date", "bad_date"


@dataclass
class Ref:
    path: str  # posix path relative to the scan root
    line: int
    text: str


@dataclass
class FlagStatus:
    flag: str
    state: str
    owner: str = ""
    dies_on: date | None = None
    raw_dies_on: str = ""
    days_left: int | None = None  # negative when overdue
    config_line: int = 1
    refs: list[Ref] = field(default_factory=list)
    flagsmith: str = ""  # one-line read-only Flagsmith status, empty when not checked


# ---------------------------------------------------------------- config and dates

def parse_date(value: object) -> date | None:
    """YAML turns an unquoted 2026-11-20 into a date; a quoted one stays a string."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def _key_lines(text: str, flags: list[str]) -> dict[str, tuple[int, int]]:
    """For each flag: (line of the flag key, line of its dies_on) in the yaml text, 1-based."""
    out: dict[str, tuple[int, int]] = {}
    lines = text.splitlines()
    for flag in flags:
        start = next((i for i, ln in enumerate(lines) if re.match(rf"^\s+{re.escape(flag)}\s*:", ln)), None)
        if start is None:
            out[flag] = (1, 1)
            continue
        indent = len(lines[start]) - len(lines[start].lstrip())
        dies = start
        for j in range(start + 1, len(lines)):
            ln = lines[j]
            if ln.strip() and not ln.lstrip().startswith("#") and len(ln) - len(ln.lstrip()) <= indent:
                break
            if re.match(r"^\s+dies_on\s*:", ln):
                dies = j
                break
        out[flag] = (start + 1, dies + 1)
    return out


def classify(raw: object, today: date, warn_days: int) -> tuple[str, date | None, int | None]:
    if raw is None or raw == "":
        return NO_DATE, None, None
    d = parse_date(raw)
    if d is None:
        return BAD_DATE, None, None
    left = (d - today).days
    if left < 0:
        return OVERDUE, d, left
    if left <= warn_days:
        return DUE_SOON, d, left
    return OK, d, left


def load_flags(config: Path, today: date, warn_days: int) -> list[FlagStatus]:
    text = config.read_text(encoding="utf-8")
    cfg = yaml.safe_load(text) or {}
    flags = cfg.get("flags") or {}
    lines = _key_lines(text, list(flags))
    out = []
    for name, spec in flags.items():
        spec = spec or {}
        raw = spec.get("dies_on")
        state, d, left = classify(raw, today, warn_days)
        key_line, dies_line = lines[name]
        out.append(FlagStatus(
            flag=name, state=state, owner=str(spec.get("owner") or ""), dies_on=d,
            raw_dies_on="" if raw is None else str(raw), days_left=left,
            config_line=dies_line if state != NO_DATE else key_line,
        ))
    return out


# ---------------------------------------------------------------- scanning

def _git_files(root: Path) -> list[Path] | None:
    """Tracked + untracked-but-not-ignored files when `root` is a git work tree's top, else None.

    Using git's own view keeps ignored scratch files and build output out of the report.
    """
    try:
        top = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=30)
        if top.returncode != 0 or Path(top.stdout.strip()).resolve() != root.resolve():
            return None
        ls = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if ls.returncode != 0:
        return None
    return sorted({root / rel for rel in ls.stdout.split("\0") if rel})


def _walk_files(root: Path, skip_dirs: set[str]) -> list[Path]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in skip_dirs)
        out.extend(Path(dirpath) / fn for fn in sorted(filenames))
    return out


def scan_references(root: Path, flags: list[str], skip: set[str] | None = None,
                    skip_files: set[str] | None = None, include_docs: bool = False) -> dict[str, list[Ref]]:
    """Every line under `root` that mentions a flag key as a whole word. Text files only.

    Prose files (.md/.rst/.txt) are skipped unless `include_docs`: a README that names a flag is
    not code anyone has to delete, and listing it buries the lines that matter.
    """
    skip_dirs = SKIP_DIRS | (skip or set())
    pats = {f: re.compile(rf"(?<![A-Za-z0-9_]){re.escape(f)}(?![A-Za-z0-9_])") for f in flags}
    found: dict[str, list[Ref]] = {f: [] for f in flags}
    files = _git_files(root)
    if files is None:
        files = _walk_files(root, skip_dirs)
    for p in files:
        rel_parts = p.relative_to(root).parts
        if any(part in skip_dirs for part in rel_parts[:-1]):
            continue
        if not include_docs and p.suffix.lower() in DOC_SUFFIXES:
            continue
        rel = p.relative_to(root).as_posix()
        if skip_files and rel in skip_files:
            continue
        try:
            if p.stat().st_size > MAX_FILE_BYTES:
                continue
            data = p.read_bytes()
        except OSError:
            continue  # listed by git but deleted in the work tree, or unreadable
        if b"\0" in data[:4096]:
            continue  # binary
        for n, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
            for f, pat in pats.items():
                if pat.search(line):
                    found[f].append(Ref(rel, n, line.strip()[:160]))
    return found


# ---------------------------------------------------------------- output

def _esc_data(s: str) -> str:
    return s.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _esc_prop(s: str) -> str:
    return _esc_data(s).replace(":", "%3A").replace(",", "%2C")


def annotation(level: str, message: str, file: str | None = None, line: int | None = None,
               title: str | None = None) -> str:
    """One GitHub workflow command, e.g. `::error file=a.py,line=3,title=T::message`."""
    props = []
    if file:
        props.append(f"file={_esc_prop(file)}")
    if line:
        props.append(f"line={line}")
    if title:
        props.append(f"title={_esc_prop(title)}")
    return f"::{level} {','.join(props)}::{_esc_data(message)}" if props else f"::{level}::{_esc_data(message)}"


def describe(s: FlagStatus) -> str:
    who = f" (owner {s.owner})" if s.owner else ""
    if s.state == OVERDUE:
        return f"Flag `{s.flag}`{who} was due to die on {s.dies_on} and is {-s.days_left} day(s) overdue. Retire it or move dies_on."
    if s.state == DUE_SOON:
        return f"Flag `{s.flag}`{who} dies on {s.dies_on}, in {s.days_left} day(s)."
    if s.state == NO_DATE:
        return f"Flag `{s.flag}`{who} has no dies_on date. Every flag should have one."
    if s.state == BAD_DATE:
        return f"Flag `{s.flag}`{who} has a dies_on that is not a YYYY-MM-DD date: {s.raw_dies_on!r}."
    return f"Flag `{s.flag}` dies on {s.dies_on} ({s.days_left} days left)."


def annotations(statuses: list[FlagStatus], config_name: str) -> list[str]:
    out = []
    for s in statuses:
        level = {OVERDUE: "error", BAD_DATE: "error", DUE_SOON: "warning", NO_DATE: "warning"}.get(s.state)
        if not level:
            continue
        title = {OVERDUE: "Overdue flag", BAD_DATE: "Bad dies_on", DUE_SOON: "Flag due soon",
                 NO_DATE: "Flag has no dies_on"}[s.state]
        out.append(annotation(level, describe(s), config_name, s.config_line, title))
        if s.state in (OVERDUE, DUE_SOON):
            for r in s.refs[:MAX_REF_ANNOTATIONS]:
                out.append(annotation(level, f"`{s.flag}` is referenced here and {'is overdue' if s.state == OVERDUE else 'dies on ' + str(s.dies_on)}.",
                                      r.path, r.line, title))
    return out


def summary_markdown(statuses: list[FlagStatus], today: date, warn_days: int) -> str:
    n_over = sum(s.state in (OVERDUE, BAD_DATE) for s in statuses)
    icon = {OVERDUE: "🔴 overdue", BAD_DATE: "🔴 bad date", DUE_SOON: "🟡 due soon", NO_DATE: "⚪ no date", OK: "🟢 ok"}
    md = [f"## Requiem NAG: {n_over} overdue of {len(statuses)} flag(s)", "",
          f"Checked on {today} (warning window: {warn_days} days).", "",
          "| Flag | Owner | Dies on | Status | References | Flagsmith |", "|---|---|---|---|---|---|"]
    for s in statuses:
        days = "" if s.days_left is None else (f" ({-s.days_left}d late)" if s.days_left < 0 else f" (in {s.days_left}d)")
        md.append(f"| `{s.flag}` | {s.owner or '-'} | {s.raw_dies_on or '-'}{days} | {icon[s.state]} | {len(s.refs)} | {s.flagsmith or 'not checked'} |")
    for s in statuses:
        if s.state in (OVERDUE, DUE_SOON) and s.refs:
            md += ["", f"<details><summary>References to <code>{s.flag}</code> ({len(s.refs)})</summary>", ""]
            md += [f"- `{r.path}:{r.line}`: `{r.text.replace('`', "'")}`" for r in s.refs]
            md += ["", "</details>"]
    return "\n".join(md) + "\n"


# ---------------------------------------------------------------- Flagsmith (read-only) and issues

def flagsmith_check(flag: str, experiment_name: str | None, base: str, token: str, env_key: str,
                    project_id: str | None) -> str:
    """GET requests only. Returns a short human string; never raises."""
    import httpx

    try:
        with httpx.Client(base_url=base.rstrip("/") + "/api/v1", headers={"Authorization": f"Token {token}"},
                          timeout=10) as c:
            def items(path: str) -> list[dict]:
                r = c.get(path)
                r.raise_for_status()
                b = r.json()
                return b.get("results", []) if isinstance(b, dict) else list(b or [])

            exps = [e for e in items(f"/environments/{env_key}/experiments/")
                    if (e.get("feature") or {}).get("name") == flag
                    or (experiment_name and e.get("name") == experiment_name)]
            exists = None
            if project_id:
                exists = any(f.get("name") == flag for f in items(f"/projects/{project_id}/features/?search={flag}"))
            parts = []
            if exists is not None:
                parts.append("flag exists" if exists else "flag not found")
            parts.append(", ".join(f"in experiment '{e['name']}' ({e['status']})" for e in exps) or "not in an experiment")
            return "; ".join(parts)
    except Exception as e:  # network, auth, shape: report, never fail the nag because of it
        return f"check failed ({type(e).__name__})"


def open_issues(statuses: list[FlagStatus], run=subprocess.run) -> list[str]:
    """One issue per overdue flag, found by its title; created if missing, commented if it exists."""
    done = []
    for s in (x for x in statuses if x.state == OVERDUE):
        title = f"Flag `{s.flag}` is overdue (dies_on {s.dies_on})"
        body = describe(s) + "\n\nReferences:\n" + "\n".join(f"- `{r.path}:{r.line}`" for r in s.refs[:50])
        if s.owner.startswith("@"):
            body += f"\n\nOwner: {s.owner}"
        found = run(["gh", "issue", "list", "--state", "open", "--search", f'"{title}" in:title',
                     "--json", "number,title"], capture_output=True, text=True, check=True)
        match = next((i for i in json.loads(found.stdout or "[]") if i["title"] == title), None)
        if match:
            run(["gh", "issue", "comment", str(match["number"]), "--body", body], check=True)
            done.append(f"commented on #{match['number']} for {s.flag}")
        else:
            run(["gh", "issue", "create", "--title", title, "--body", body], check=True)
            done.append(f"created an issue for {s.flag}")
    return done


# ---------------------------------------------------------------- main

def run_nag(config: Path, root: Path, today: date, warn_days: int, fail_on_overdue: bool,
            env: dict[str, str] | None = None, out=None,
            include_docs: bool = False) -> tuple[int, list[FlagStatus]]:
    env = os.environ if env is None else env
    out = out or sys.stdout
    statuses = load_flags(config, today, warn_days)
    try:
        cfg_name = config.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        cfg_name = config.name
    # The config file defines the flags, so its own mentions are not references to clean up.
    refs = scan_references(root, [s.flag for s in statuses], skip_files={cfg_name}, include_docs=include_docs)
    for s in statuses:
        s.refs = refs[s.flag]

    url, token, ek = env.get("FLAGSMITH_URL"), env.get("FLAGSMITH_ADMIN_TOKEN"), env.get("FLAGSMITH_ENVIRONMENT_KEY")
    if url and token and ek:
        exp_names = {n: (sp or {}).get("experiment")
                     for n, sp in ((yaml.safe_load(config.read_text(encoding="utf-8")) or {}).get("flags") or {}).items()}
        for s in statuses:
            s.flagsmith = flagsmith_check(s.flag, exp_names.get(s.flag), url, token, ek, env.get("FLAGSMITH_PROJECT_ID"))

    for ln in annotations(statuses, cfg_name):
        print(ln, file=out)
    for s in statuses:
        print(f"{s.state:9} {s.flag}  dies_on={s.raw_dies_on or '-'}  owner={s.owner or '-'}  "
              f"refs={len(s.refs)}  flagsmith={s.flagsmith or 'not checked'}", file=out)

    summary = env.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(summary_markdown(statuses, today, warn_days))

    failed = any(s.state in (OVERDUE, BAD_DATE) for s in statuses)
    return (1 if failed and fail_on_overdue else 0), statuses


def _bool(v: str) -> bool:
    return v.strip().lower() not in ("0", "false", "no", "off", "")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m requiem.nag", description=__doc__.split("\n")[0])
    ap.add_argument("--config", default="requiem.yaml")
    ap.add_argument("--root", default=".", help="directory to scan for flag references")
    ap.add_argument("--warn-days", type=int, default=14)
    ap.add_argument("--fail-on-overdue", default="true", help="true/false (default true)")
    ap.add_argument("--no-fail-on-overdue", action="store_true")
    ap.add_argument("--open-issue", action="store_true", help="create/update a GitHub issue per overdue flag via gh")
    ap.add_argument("--today", help="override today's date, YYYY-MM-DD (for tests and demos)")
    ap.add_argument("--include-docs", action="store_true", help="also list mentions in .md/.rst/.txt files")
    a = ap.parse_args(argv)

    today = parse_date(a.today) if a.today else date.today()
    if today is None:
        print("--today must be YYYY-MM-DD", file=sys.stderr)
        return 2
    config = Path(a.config)
    if not config.is_file():
        print(annotation("error", f"config file not found: {a.config}"))
        return 2
    fail = _bool(a.fail_on_overdue) and not a.no_fail_on_overdue
    code, statuses = run_nag(config, Path(a.root), today, a.warn_days, fail, include_docs=a.include_docs)
    if a.open_issue:
        for line in open_issues(statuses):
            print(line)
    return code


if __name__ == "__main__":
    sys.exit(main())
