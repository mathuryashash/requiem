"""Delete a retired flag from Python source with LibCST.

Ported from the Day-1 prototype (if/else on `is_feature_enabled`) and extended to the shape the
demo shop actually uses for experiments:

    variant, value = _variant("buy_button", user)       # the flag lookup
    span.set_attribute("flag.key", "buy_button")        # span tags that exist only for the flag
    span.set_attribute("flag.variant", variant)
    if variant == "green":                              # literal comparisons, with elif / else
        ...
    else:
        ...

`retire_flag(source, flag, keep_variant=..., keep_value=...)` rewrites that so only the winning
branch is left. Rules, so nothing happens silently:

* The lookup line and the two span tags are removed.
* An `if/elif/else` chain whose tests are all `variant == "lit"` / `!=` (or the same on `value`)
  is replaced by the body of the branch the kept variant would take.
* Any other use of `variant` / `value` after the lookup is replaced by the kept literal
  (everyone is on that variant after the rollout, so the value cannot differ).
* A literal-vs-literal comparison created that way is folded to True/False.
* Anything else (a complex `if` condition, `match`, the names being rebound, a one-line `if x: y`,
  or the flag key still appearing as a string somewhere) goes in `Report.unsupported`. When the
  block around a lookup holds such a pattern, that lookup is left exactly as it was.

Boolean flags are supported in the prototype's shape: `if flags.is_feature_enabled("flag"):`,
`if not ...`, with `enabled=True/False` saying which side wins.

Running it twice changes nothing the second time: there is no lookup left to find.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Sequence

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider

LOOKUP_FUNCS = ("_variant",)  # helpers shaped like `variant, value = helper("<flag>", user)`


@dataclass
class Report:
    flag: str
    rewrites: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    changed: bool = False

    def text(self) -> str:
        lines = [f"Codemod report for flag `{self.flag}`: {'changed' if self.changed else 'no change'}"]
        lines += [f"  rewrote: {r}" for r in self.rewrites]
        lines += [f"  UNSUPPORTED (left alone, needs a human): {u}" for u in self.unsupported]
        return "\n".join(lines)


# ---------------------------------------------------------------- small CST helpers

def _lit(node: cst.BaseExpression) -> str | None:
    if isinstance(node, cst.SimpleString) and "f" not in node.prefix.lower() and "b" not in node.prefix.lower():
        try:
            return node.evaluated_value  # type: ignore[return-value]
        except Exception:  # noqa: BLE001
            return None
    return None


def _single_expr(stmt: cst.CSTNode) -> cst.BaseExpression | None:
    if isinstance(stmt, cst.SimpleStatementLine) and len(stmt.body) == 1 and isinstance(stmt.body[0], cst.Expr):
        return stmt.body[0].value
    return None


def _is_lookup(stmt: cst.CSTNode, flag: str, funcs: Sequence[str]) -> tuple[str, str] | None:
    """`a, b = helper("<flag>", ...)` -> (a, b)."""
    if not (isinstance(stmt, cst.SimpleStatementLine) and len(stmt.body) == 1 and isinstance(stmt.body[0], cst.Assign)):
        return None
    a = stmt.body[0]
    if len(a.targets) != 1 or not isinstance(a.targets[0].target, cst.Tuple):
        return None
    elts = a.targets[0].target.elements
    if len(elts) != 2 or not all(isinstance(e.value, cst.Name) for e in elts):
        return None
    c = a.value
    if not (isinstance(c, cst.Call) and isinstance(c.func, cst.Name) and c.func.value in funcs and c.args):
        return None
    if _lit(c.args[0].value) != flag:
        return None
    return elts[0].value.value, elts[1].value.value  # type: ignore[union-attr]


def _set_attribute(stmt: cst.CSTNode) -> tuple[str | None, cst.BaseExpression | None]:
    e = _single_expr(stmt)
    if isinstance(e, cst.Call) and isinstance(e.func, cst.Attribute) and e.func.attr.value == "set_attribute" \
            and len(e.args) == 2:
        return _lit(e.args[0].value), e.args[1].value
    return None, None


def _flag_check(test: cst.BaseExpression, flag: str) -> bool | None:
    """`flags.is_feature_enabled("flag")` -> False (not negated), `not ...` -> True (negated); else None."""
    neg = False
    if isinstance(test, cst.UnaryOperation) and isinstance(test.operator, cst.Not):
        neg, test = True, test.expression
    if isinstance(test, cst.Call) and isinstance(test.func, cst.Attribute) \
            and test.func.attr.value == "is_feature_enabled" and test.args and _lit(test.args[0].value) == flag:
        return neg
    return None


def _simple_compare(test: cst.BaseExpression, names: dict[str, str]) -> tuple[str, bool] | None:
    """`name == "lit"` / `"lit" == name` / `!=`  ->  (the kept value for `name`, is_equal)."""
    if not (isinstance(test, cst.Comparison) and len(test.comparisons) == 1):
        return None
    op = test.comparisons[0].operator
    if not isinstance(op, (cst.Equal, cst.NotEqual)):
        return None
    l, r = test.left, test.comparisons[0].comparator
    for name_node, lit_node in ((l, r), (r, l)):
        if isinstance(name_node, cst.Name) and name_node.value in names and _lit(lit_node) is not None:
            return (names[name_node.value] == _lit(lit_node)) and "T" or "F", isinstance(op, cst.Equal)  # type: ignore[return-value]
    return None


class _Mentions(cst.CSTVisitor):
    def __init__(self, names: set[str]) -> None:
        self.names, self.hit = names, False

    def visit_Name(self, node: cst.Name) -> None:
        if node.value in self.names:
            self.hit = True


def _mentions(node: cst.CSTNode, names: set[str]) -> bool:
    v = _Mentions(names)
    node.visit(v)
    return v.hit


# ---------------------------------------------------------------- pre-scan: is this lookup safe to rewrite?

class _Scan(cst.CSTVisitor):
    def __init__(self, names: dict[str, str]) -> None:
        self.names, self.problems = names, []
        self._elif: set[int] = set()

    def visit_If(self, node: cst.If) -> None:
        if id(node) in self._elif:
            return
        chain, n = [], node
        while isinstance(n, cst.If):
            chain.append(n)
            if isinstance(n.orelse, cst.If):
                self._elif.add(id(n.orelse))
            n = n.orelse  # type: ignore[assignment]
        mention = [_mentions(c.test, set(self.names)) for c in chain]
        if not any(mention):
            return
        if not all(mention):
            self.problems.append("if/elif chain mixes tests on the flag with other tests")
        for c, m in zip(chain, mention):
            if m and _simple_compare(c.test, self.names) is None:
                self.problems.append("an if condition uses the flag variable in something other than ==/!= against a string")
            if m and not isinstance(c.body, cst.IndentedBlock):
                self.problems.append("one-line `if x: y` on the flag variable")
        if isinstance(n, cst.Else) and not isinstance(n.body, cst.IndentedBlock):
            self.problems.append("one-line `else: y` on the flag variable")

    def visit_Match(self, node: cst.Match) -> None:
        if _mentions(node.subject, set(self.names)):
            self.problems.append("`match` on the flag variable")

    def _rebind(self, target: cst.CSTNode) -> None:
        if _mentions(target, set(self.names)):
            self.problems.append("the flag variable is assigned again")

    def visit_AssignTarget(self, node: cst.AssignTarget) -> None:
        self._rebind(node.target)

    def visit_AugAssign(self, node: cst.AugAssign) -> None:
        self._rebind(node.target)

    def visit_AnnAssign(self, node: cst.AnnAssign) -> None:
        self._rebind(node.target)

    def visit_NamedExpr(self, node: cst.NamedExpr) -> None:
        self._rebind(node.target)

    def visit_For(self, node: cst.For) -> None:
        self._rebind(node.target)

    def visit_Param(self, node: cst.Param) -> None:
        if node.name.value in self.names:
            self.problems.append("a nested function reuses the flag variable name as a parameter")


# ---------------------------------------------------------------- the transformer

class _Retire(cst.CSTTransformer):
    def __init__(self, flag: str, keep_variant: str, keep_value: str, enabled: bool | None,
                 funcs: Sequence[str], report: Report) -> None:
        super().__init__()
        self.flag, self.keep_variant, self.keep_value = flag, keep_variant, keep_value
        self.enabled, self.funcs, self.report = enabled, funcs, report
        self.active: list[dict[str, str]] = []  # name -> literal it is replaced by, one entry per rewritten block
        self.remove: set[int] = set()
        self.skip_names: set[int] = set()
        self.made: set[int] = set()
        self._elif: set[int] = set()

    # --- blocks that hold a lookup
    def _enter_block(self, body: Sequence[cst.CSTNode]) -> None:
        for i, stmt in enumerate(body):
            names = _is_lookup(stmt, self.flag, self.funcs)
            if not names:
                continue
            var, val = names
            rest = body[i + 1:]
            mapping = {var: self.keep_variant, val: self.keep_value}
            scan = _Scan(mapping)
            for s in rest:
                s.visit(scan)
            if scan.problems:
                for p in sorted(set(scan.problems)):
                    self.report.unsupported.append(f"lookup `{var}, {val} = ...(\"{self.flag}\")` left as is: {p}")
                continue
            self.remove.add(id(stmt))
            for e in stmt.body[0].targets[0].target.elements:  # type: ignore[attr-defined]
                self.skip_names.add(id(e.value))
            self.report.rewrites.append(f"removed the lookup of `{self.flag}` (`{var}, {val}`)")
            for s in rest:
                key, arg = _set_attribute(s)
                if key == "flag.key" and arg is not None and _lit(arg) == self.flag:
                    self.remove.add(id(s))
                    self.report.rewrites.append("removed span tag flag.key")
                elif key == "flag.variant" and isinstance(arg, cst.Name) and arg.value == var:
                    self.remove.add(id(s))
                    self.skip_names.add(id(arg))
                    self.report.rewrites.append("removed span tag flag.variant")
            self.active.append(mapping)
            self._pushed.append(id(body))  # type: ignore[attr-defined]
            return  # one lookup per block; a second would be reported by the leftover scan

    _pushed: list[int]

    def visit_Module(self, node: cst.Module) -> None:
        self._pushed = []
        self._enter_block(node.body)

    def visit_IndentedBlock(self, node: cst.IndentedBlock) -> None:
        self._enter_block(node.body)

    def _leave_block(self, original_body: Sequence[cst.CSTNode]) -> None:
        if self._pushed and self._pushed[-1] == id(original_body):
            self._pushed.pop()
            self.active.pop()

    def leave_IndentedBlock(self, original_node: cst.IndentedBlock, updated_node: cst.IndentedBlock) -> cst.IndentedBlock:
        self._leave_block(original_node.body)
        if not updated_node.body:
            return updated_node.with_changes(body=[cst.SimpleStatementLine([cst.Pass()])])
        return updated_node

    def leave_Module(self, original_node: cst.Module, updated_node: cst.Module) -> cst.Module:
        self._leave_block(original_node.body)
        return updated_node

    def leave_SimpleStatementLine(self, original_node, updated_node):
        if id(original_node) in self.remove:
            return cst.RemovalSentinel.REMOVE
        return updated_node

    # --- names
    def visit_Attribute(self, node: cst.Attribute) -> None:
        self.skip_names.add(id(node.attr))

    def visit_Arg(self, node: cst.Arg) -> None:
        if node.keyword is not None:
            self.skip_names.add(id(node.keyword))

    def leave_Name(self, original_node: cst.Name, updated_node: cst.Name) -> cst.BaseExpression:
        if id(original_node) in self.skip_names or not self.active:
            return updated_node
        lit = self.active[-1].get(original_node.value)
        if lit is None:
            return updated_node
        new = cst.SimpleString(json.dumps(lit))
        self.made.add(id(new))
        self.report.rewrites.append(f"replaced `{original_node.value}` with \"{lit}\"")
        return new

    def leave_Comparison(self, original_node, updated_node):
        c = updated_node
        if len(c.comparisons) == 1 and isinstance(c.comparisons[0].operator, (cst.Equal, cst.NotEqual)) \
                and (id(c.left) in self.made or id(c.comparisons[0].comparator) in self.made):
            a, b = _lit(c.left), _lit(c.comparisons[0].comparator)
            if a is not None and b is not None:
                res = (a == b) == isinstance(c.comparisons[0].operator, cst.Equal)
                self.report.rewrites.append(f"folded a comparison of two literals to {res}")
                return cst.Name("True" if res else "False")
        return updated_node

    # --- if / elif / else
    def visit_If(self, node: cst.If) -> None:
        if isinstance(node.orelse, cst.If):
            self._elif.add(id(node.orelse))

    def _truth(self, test: cst.BaseExpression) -> bool | None:
        if self.active:
            sc = _simple_compare(test, self.active[-1])
            if sc is not None:
                matched, is_eq = sc
                return (matched == "T") == is_eq
        neg = _flag_check(test, self.flag)
        if neg is not None and self.enabled is not None:
            return self.enabled != neg
        return None

    def leave_If(self, original_node: cst.If, updated_node: cst.If):
        if id(original_node) in self._elif:
            return updated_node  # decided by the head of its chain
        o: cst.If | cst.Else | None = original_node
        u: cst.If | cst.Else | None = updated_node
        while isinstance(o, cst.If) and isinstance(u, cst.If):
            t = self._truth(o.test)
            if t is None:  # not ours; if earlier branches were dropped, the rest of the chain becomes the if
                return updated_node if o is original_node else u
            if t:
                self.report.rewrites.append(f"kept the `{_short(o.test)}` branch of an if on `{self.flag}`")
                return self._body(u.body)
            o, u = o.orelse, u.orelse  # type: ignore[assignment]
        if isinstance(u, cst.Else):
            self.report.rewrites.append("kept the else branch of an if on the flag")
            return self._body(u.body)
        self.report.rewrites.append("removed an if on the flag with no branch left")
        return cst.RemovalSentinel.REMOVE

    @staticmethod
    def _body(b: cst.BaseSuite):
        return cst.FlattenSentinel(list(b.body))  # type: ignore[arg-type]


def _short(node: cst.CSTNode) -> str:
    return cst.Module([]).code_for_node(node)


# ---------------------------------------------------------------- public API

def retire_flag(
    source: str,
    flag: str,
    *,
    keep_variant: str,
    keep_value: str | None = None,
    enabled: bool | None = None,
    lookup_funcs: Sequence[str] = LOOKUP_FUNCS,
) -> tuple[str, Report]:
    """Return `(new_source, report)`. `keep_variant` is the variant key that won (`"control"` if the
    control won); `keep_value` is the flag value that variant serves; `enabled` is for boolean flags."""
    report = Report(flag=flag)
    try:
        module = cst.parse_module(source)
    except cst.ParserSyntaxError as e:
        raise ValueError(f"cannot parse source: {e}") from e
    t = _Retire(flag, keep_variant, keep_value if keep_value is not None else keep_variant, enabled,
                lookup_funcs, report)
    new = module.visit(t)
    code = new.code
    report.changed = code != source
    # Anything still holding the flag key as a string was not understood: say so.
    wrapper = MetadataWrapper(cst.parse_module(code))
    pos = wrapper.resolve(PositionProvider)
    for node in _walk_strings(wrapper.module):
        if _lit(node) == flag:
            report.unsupported.append(f"line {pos[node].start.line} of the rewritten file: the string \"{flag}\" is still used here")
    if compile_error(code):
        raise ValueError(f"codemod produced invalid Python: {compile_error(code)}")
    # de-duplicate the chatty per-name notes
    seen: set[str] = set()
    report.rewrites = [r for r in report.rewrites if not (r in seen or seen.add(r))]
    return code, report


def _walk_strings(module: cst.Module) -> list[cst.SimpleString]:
    out: list[cst.SimpleString] = []

    class V(cst.CSTVisitor):
        def visit_SimpleString(self, node: cst.SimpleString) -> None:
            out.append(node)

    module.visit(V())
    return out


def compile_error(code: str) -> str | None:
    try:
        compile(code, "<codemod>", "exec")
    except SyntaxError as e:
        return f"{e.msg} (line {e.lineno})"
    return None


def remove_contract_entry(yaml_text: str, flag: str) -> tuple[str, bool]:
    """Drop `  <flag>:` and its indented block from requiem.yaml text, keeping every other line and comment."""
    lines = yaml_text.splitlines(keepends=True)
    out: list[str] = []
    i, removed = 0, False
    head = re.compile(rf"^(\s+){re.escape(flag)}:\s*(#.*)?$")
    while i < len(lines):
        m = head.match(lines[i].rstrip("\r\n"))
        if m:
            indent = len(m.group(1))
            i += 1
            while i < len(lines) and (not lines[i].strip() or len(lines[i]) - len(lines[i].lstrip()) > indent):
                if not lines[i].strip():
                    break
                i += 1
            removed = True
            continue
        out.append(lines[i])
        i += 1
    return "".join(out), removed
