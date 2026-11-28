from __future__ import annotations

import io
import json
from datetime import date
from pathlib import Path

import pytest

from requiem import nag

TODAY = date(2026, 11, 28)

CONFIG = """\
flags:
  old_flag:
    experiment: Old
    owner: "@alice"
    dies_on: 2026-11-20
  soon_flag:
    experiment: Soon
    dies_on: 2026-12-05
  fine_flag:
    experiment: Fine
    dies_on: 2027-06-01
  undated_flag:
    experiment: Undated
  broken_flag:
    experiment: Broken
    dies_on: next tuesday
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "requiem.yaml").write_text(CONFIG, encoding="utf-8")
    (tmp_path / "app.py").write_text("x = 1\nif flags.is_on('old_flag'):\n    pass\nold_flag_extra = 2\n", encoding="utf-8")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "b.py").write_text("# soon_flag here\nold_flag, soon_flag = 1, 2\n", encoding="utf-8")
    for skipped in (".git", ".venv", "fixtures", "node_modules"):
        (tmp_path / skipped).mkdir()
        (tmp_path / skipped / "x.txt").write_text("old_flag\n", encoding="utf-8")
    (tmp_path / "blob.bin").write_bytes(b"\0\0old_flag\0")
    return tmp_path


def states(repo: Path, today: date = TODAY, warn: int = 14) -> dict[str, nag.FlagStatus]:
    return {s.flag: s for s in nag.load_flags(repo / "requiem.yaml", today, warn)}


# ---- dates

def test_overdue_due_soon_ok_missing_malformed(repo):
    s = states(repo)
    assert (s["old_flag"].state, s["old_flag"].days_left) == (nag.OVERDUE, -8)
    assert (s["soon_flag"].state, s["soon_flag"].days_left) == (nag.DUE_SOON, 7)
    assert s["fine_flag"].state == nag.OK
    assert s["undated_flag"].state == nag.NO_DATE
    assert s["broken_flag"].state == nag.BAD_DATE
    assert s["old_flag"].owner == "@alice" and s["soon_flag"].owner == ""


def test_due_today_is_not_overdue_and_boundary_of_warn_window(repo):
    assert states(repo, date(2026, 11, 20))["old_flag"].state == nag.DUE_SOON  # due today: 0 days left
    assert states(repo, date(2026, 11, 21))["old_flag"].state == nag.OVERDUE
    assert states(repo, TODAY, warn=6)["soon_flag"].state == nag.OK
    assert states(repo, TODAY, warn=7)["soon_flag"].state == nag.DUE_SOON


def test_quoted_date_string_is_accepted():
    assert nag.classify("2026-01-02", TODAY, 14)[0] == nag.OVERDUE
    assert nag.classify("2026-13-40", TODAY, 14)[0] == nag.BAD_DATE
    assert nag.classify(20261120, TODAY, 14)[0] == nag.BAD_DATE


def test_config_line_points_at_dies_on(repo):
    s = states(repo)
    lines = CONFIG.splitlines()
    assert "dies_on: 2026-11-20" in lines[s["old_flag"].config_line - 1]
    assert lines[s["undated_flag"].config_line - 1].strip().startswith("undated_flag")


# ---- scanning

def test_scan_finds_whole_word_references_and_skips_dirs(repo):
    refs = nag.scan_references(repo, ["old_flag", "soon_flag"], skip_files={"requiem.yaml"})
    assert ("requiem.yaml", 2) in {(r.path, r.line) for r in nag.scan_references(repo, ["old_flag"])["old_flag"]}
    old = {(r.path, r.line) for r in refs["old_flag"]}
    assert old == {("app.py", 2), ("pkg/b.py", 2)}
    assert ("app.py", 4) not in old  # old_flag_extra is a different name
    assert not any(r.path.startswith((".git", ".venv", "fixtures", "node_modules")) for r in refs["old_flag"])
    assert not any(r.path == "blob.bin" for r in refs["old_flag"])
    assert {(r.path, r.line) for r in refs["soon_flag"]} == {("pkg/b.py", 1), ("pkg/b.py", 2)}


# ---- annotations

def test_annotation_format_and_escaping():
    assert nag.annotation("error", "msg", "a/b.py", 3, "T") == "::error file=a/b.py,line=3,title=T::msg"
    assert nag.annotation("warning", "no file") == "::warning::no file"
    assert nag.annotation("error", "100%\nnext", "dir:x,y.py", 1) == "::error file=dir%3Ax%2Cy.py,line=1::100%25%0Anext"


def test_annotations_for_each_state(repo):
    st = list(states(repo).values())
    refs = nag.scan_references(repo, [s.flag for s in st], skip_files={"requiem.yaml"})
    for s in st:
        s.refs = refs[s.flag]
    out = nag.annotations(st, "requiem.yaml")
    assert any(a.startswith("::error file=requiem.yaml,line=5,title=Overdue flag::") and "8 day(s) overdue" in a for a in out)
    assert "::error file=app.py,line=2,title=Overdue flag::`old_flag` is referenced here and is overdue." in out
    assert any(a.startswith("::warning file=requiem.yaml") and "in 7 day(s)" in a for a in out)
    assert any("no dies_on" in a and a.startswith("::warning") for a in out)
    assert any("not a YYYY-MM-DD" in a and a.startswith("::error") for a in out)
    assert not any("fine_flag" in a for a in out)


def test_reference_annotations_are_capped(tmp_path):
    (tmp_path / "requiem.yaml").write_text("flags:\n  f:\n    dies_on: 2020-01-01\n", encoding="utf-8")
    (tmp_path / "many.py").write_text("f\n" * 40, encoding="utf-8")
    st = nag.load_flags(tmp_path / "requiem.yaml", TODAY, 14)
    st[0].refs = nag.scan_references(tmp_path, ["f"])["f"]
    out = nag.annotations(st, "requiem.yaml")
    assert len(out) == 1 + nag.MAX_REF_ANNOTATIONS


# ---- exit codes and summary

def run(repo, summary=None, fail=True, today=TODAY):
    env = {"GITHUB_STEP_SUMMARY": str(summary)} if summary else {}
    buf = io.StringIO()
    code, st = nag.run_nag(repo / "requiem.yaml", repo, today, 14, fail, env=env, out=buf)
    return code, st, buf.getvalue()


def test_exit_code_is_1_when_overdue_and_0_when_not_failing(repo):
    assert run(repo)[0] == 1
    assert run(repo, fail=False)[0] == 0


def test_exit_code_0_when_nothing_overdue(tmp_path):
    (tmp_path / "requiem.yaml").write_text("flags:\n  a:\n    dies_on: 2027-01-01\n  b: {}\n", encoding="utf-8")
    code, _, out = run(tmp_path)
    assert code == 0 and "::error" not in out and "::warning" in out  # b has no date: warning only


def test_malformed_date_fails_the_check(tmp_path):
    (tmp_path / "requiem.yaml").write_text("flags:\n  a:\n    dies_on: soon\n", encoding="utf-8")
    assert run(tmp_path)[0] == 1


def test_step_summary_written_and_appended(repo, tmp_path):
    summ = tmp_path / "summary.md"
    summ.write_text("earlier step\n", encoding="utf-8")
    run(repo, summary=summ)
    text = summ.read_text(encoding="utf-8")
    assert text.startswith("earlier step\n")  # appended, not overwritten
    assert "## Requiem NAG: 2 overdue of 5 flag(s)" in text  # old_flag + broken_flag
    assert "| `old_flag` | @alice | 2026-11-20 (8d late) | 🔴 overdue |" in text
    assert "`app.py:2`" in text


def test_no_summary_when_env_unset(repo, tmp_path):
    run(repo)
    assert not (tmp_path / "summary.md").exists()


def test_main_cli_exit_codes(repo, capsys, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.delenv("FLAGSMITH_URL", raising=False)
    args = ["--config", str(repo / "requiem.yaml"), "--root", str(repo), "--today", "2026-11-28"]
    assert nag.main(args) == 1
    assert nag.main(args + ["--no-fail-on-overdue"]) == 0
    assert nag.main(args + ["--fail-on-overdue", "false"]) == 0
    assert nag.main(["--config", str(repo / "nope.yaml")]) == 2
    assert nag.main(args[:-1] + ["garbage"]) == 2
    assert "::error" in capsys.readouterr().out


# ---- Flagsmith check (read-only) and issues

def test_flagsmith_check_failure_is_reported_not_raised():
    assert "check failed" in nag.flagsmith_check("f", None, "http://127.0.0.1:9", "t", "k", "1")


def test_flagsmith_check_uses_only_get(monkeypatch):
    import httpx

    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((req.method, req.url.path))
        if "experiments" in req.url.path:
            return httpx.Response(200, json={"results": [{"name": "Old", "status": "running", "feature": {"name": "old_flag"}}]})
        return httpx.Response(200, json={"results": [{"name": "old_flag"}]})

    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    out = nag.flagsmith_check("old_flag", "Old", "http://fs", "tok", "envkey", "7")
    assert out == "flag exists; in experiment 'Old' (running)"
    assert {m for m, _ in seen} == {"GET"}


def test_open_issue_creates_or_comments_via_gh(repo):
    st = [s for s in states(repo).values() if s.state == nag.OVERDUE]
    calls = []
    existing = [True]

    class R:
        def __init__(self, stdout=""):
            self.stdout = stdout

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if cmd[:3] == ["gh", "issue", "list"]:
            return R(json.dumps([{"number": 12, "title": "Flag `old_flag` is overdue (dies_on 2026-11-20)"}]) if existing[0] else "[]")
        return R()

    assert nag.open_issues(st, run=fake_run) == ["commented on #12 for old_flag"]
    assert calls[1][:4] == ["gh", "issue", "comment", "12"]
    calls.clear()
    existing[0] = False
    assert nag.open_issues(st, run=fake_run) == ["created an issue for old_flag"]
    assert calls[1][:3] == ["gh", "issue", "create"]

def test_prose_files_are_skipped_unless_asked(tmp_path):
    (tmp_path / "README.md").write_text("old_flag is on\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("old_flag\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("old_flag\n", encoding="utf-8")
    assert {r.path for r in nag.scan_references(tmp_path, ["old_flag"])["old_flag"]} == {"app.py"}
    with_docs = nag.scan_references(tmp_path, ["old_flag"], include_docs=True)["old_flag"]
    assert {r.path for r in with_docs} == {"README.md", "notes.txt", "app.py"}


def test_git_ignored_files_are_not_references(tmp_path):
    import subprocess
    if subprocess.run(["git", "--version"], capture_output=True).returncode != 0:
        pytest.skip("git not installed")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("scratch/\n", encoding="utf-8")
    (tmp_path / "scratch").mkdir()
    (tmp_path / "scratch" / "t.py").write_text("old_flag\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("old_flag\n", encoding="utf-8")
    assert {r.path for r in nag.scan_references(tmp_path, ["old_flag"])["old_flag"]} == {"app.py"}
