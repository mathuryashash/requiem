"""The retire codemod: golden cases, the shop's own pattern, refusals, idempotency, compile check."""

from pathlib import Path

import pytest

from requiem.codemod import remove_contract_entry, retire_flag

ROOT = Path(__file__).resolve().parent.parent

SHOP_BEFORE = '''\
def product(user):
    with tracer.start_as_current_span("view_product") as span:
        variant, value = _variant("buy_button", user)
        span.set_attribute("flag.key", "buy_button")
        span.set_attribute("flag.variant", variant)
        span.set_attribute("http.route", "/api/product")
        if variant == "green":
            button = {"colour": "green"}
        else:
            button = {"colour": "grey"}
        return {"user": user, "button_colour": button["colour"], "variant": variant}
'''

SHOP_KEEP_GREEN = '''\
def product(user):
    with tracer.start_as_current_span("view_product") as span:
        span.set_attribute("http.route", "/api/product")
        button = {"colour": "green"}
        return {"user": user, "button_colour": button["colour"], "variant": "green"}
'''

SHOP_KEEP_CONTROL = SHOP_KEEP_GREEN.replace('{"colour": "green"}', '{"colour": "grey"}').replace('"variant": "green"', '"variant": "control"')


def run(src, flag="buy_button", **kw):
    kw.setdefault("keep_variant", "green")
    kw.setdefault("keep_value", "green")
    out, rep = retire_flag(src, flag, **kw)
    compile(out, "<out>", "exec")
    return out, rep


def test_shop_pattern_keep_winner():
    out, rep = run(SHOP_BEFORE)
    assert out == SHOP_KEEP_GREEN
    assert rep.changed and not rep.unsupported


def test_shop_pattern_keep_control():
    out, rep = run(SHOP_BEFORE, keep_variant="control", keep_value="grey")
    assert out == SHOP_KEEP_CONTROL and not rep.unsupported


def test_idempotent():
    once, _ = run(SHOP_BEFORE)
    twice, rep = run(once)
    assert twice == once and not rep.changed and not rep.unsupported


def test_elif_chain_and_value_comparison():
    src = '''\
def f(user):
    variant, value = _variant("buy_button", user)
    if variant == "blue":
        x = 1
    elif value == "green":
        x = 2
    else:
        x = 3
    return x
'''
    out, rep = run(src)
    assert out == "def f(user):\n    x = 2\n    return x\n"
    out, _ = run(src, keep_variant="control", keep_value="grey")
    assert out == "def f(user):\n    x = 3\n    return x\n"


def test_not_equal_and_reversed_operands():
    src = '''\
def f(user):
    variant, value = _variant("buy_button", user)
    if "green" != variant:
        a = 1
    else:
        a = 2
    return a
'''
    assert run(src)[0].endswith("    a = 2\n    return a\n")


def test_if_without_else_and_losing_branch_is_dropped():
    src = '''\
def f(user):
    variant, value = _variant("buy_button", user)
    if variant == "green":
        log("green")
    return 1
'''
    assert run(src)[0] == "def f(user):\n    log(\"green\")\n    return 1\n"
    assert run(src, keep_variant="control", keep_value="grey")[0] == "def f(user):\n    return 1\n"


def test_block_left_empty_gets_pass():
    src = '''\
def f(user):
    variant, value = _variant("buy_button", user)
    if variant == "green":
        x = 1
'''
    out, _ = run(src, keep_variant="control", keep_value="grey")
    assert out == "def f(user):\n    pass\n"


def test_other_flags_and_attributes_named_variant_are_untouched():
    src = '''\
def f(user, obj):
    variant, value = _variant("buy_button", user)
    other, v2 = _variant("new_checkout", user)
    span.set_attribute("flag.key", "new_checkout")
    span.set_attribute("flag.variant", other)
    y = obj.variant
    z = g(variant=1)
    return other, y, z, variant
'''
    out, rep = run(src)
    assert '_variant("new_checkout", user)' in out and "span.set_attribute(\"flag.key\", \"new_checkout\")" in out
    assert "obj.variant" in out and "g(variant=1)" in out
    assert out.endswith('return other, y, z, "green"\n')
    assert not rep.unsupported


def test_unrelated_source_is_byte_identical():
    src = "import os\n\n\ndef f():\n    return os.name  # keep me\n"
    out, rep = retire_flag(src, "buy_button", keep_variant="green")
    assert out == src and not rep.changed


def test_complex_condition_is_refused_and_listed():
    src = '''\
def f(user):
    variant, value = _variant("buy_button", user)
    if variant == "green" and user.vip:
        x = 1
    else:
        x = 2
    return x
'''
    out, rep = run(src)
    assert out == src  # nothing rewritten
    assert any("something other than ==/!=" in u for u in rep.unsupported)
    assert any("string \"buy_button\" is still used" in u for u in rep.unsupported)


def test_rebinding_match_and_one_line_if_are_refused():
    for body in ("    variant = 3\n    return variant\n",
                 "    match variant:\n        case 'a':\n            return 1\n",
                 "    if variant == 'green': return 1\n    return 2\n"):
        src = "def f(user):\n    variant, value = _variant(\"buy_button\", user)\n" + body
        out, rep = run(src)
        assert out == src and rep.unsupported, body


def test_other_use_of_the_flag_key_is_reported_not_rewritten():
    src = '''\
def f(user):
    variant, value = _variant("buy_button", user)
    return variant

def g(user):
    return flagsmith.get_experiment_flag("buy_button", identifier=user)
'''
    out, rep = run(src)
    assert "get_experiment_flag(\"buy_button\"" in out
    assert len(rep.unsupported) == 1 and "line 5 of the rewritten file" in rep.unsupported[0]


def test_literal_comparison_made_by_substitution_is_folded():
    src = '''\
def f(user):
    variant, value = _variant("new_checkout", user)
    broken = on and variant != "control"
    return broken
'''
    out, _ = run(src, flag="new_checkout", keep_variant="new", keep_value="new")
    assert "broken = on and True" in out


def test_comparisons_the_codemod_did_not_create_are_left_alone():
    src = '''\
def f(user):
    variant, value = _variant("buy_button", user)
    return "a" == "b", variant
'''
    assert '"a" == "b"' in run(src)[0]


BOOL = '''\
def f(flags):
    if flags.is_feature_enabled("dark_mode"):
        theme = "dark"
    else:
        theme = "light"
    if not flags.is_feature_enabled("dark_mode"):
        banner = 1
    return theme
'''


def test_boolean_flag_if_else_and_negation():
    out, rep = run(BOOL, flag="dark_mode", enabled=True, keep_variant="enabled")
    assert out == 'def f(flags):\n    theme = "dark"\n    return theme\n'
    out, _ = run(BOOL, flag="dark_mode", enabled=False, keep_variant="disabled")
    assert out == 'def f(flags):\n    theme = "light"\n    banner = 1\n    return theme\n'


@pytest.mark.parametrize("flag,kv,val", [("buy_button", "green", "green"), ("buy_button", "control", "grey"),
                                         ("new_checkout", "new", "new"), ("new_checkout", "control", "old")])
def test_the_real_shop_compiles_and_loses_the_flag(flag, kv, val):
    """shop/app.py as committed (or already retired: then there is nothing to do and nothing breaks)."""
    src = (ROOT / "shop" / "app.py").read_text(encoding="utf-8")
    out, rep = run(src, flag=flag, keep_variant=kv, keep_value=val)
    assert not rep.unsupported, rep.text()
    assert f'_variant("{flag}"' not in out and f'"{flag}"' not in out
    again, rep2 = run(out, flag=flag, keep_variant=kv, keep_value=val)
    assert again == out and not rep2.changed
    other = "new_checkout" if flag == "buy_button" else "buy_button"
    assert (f'_variant("{other}"' in out) == (f'_variant("{other}"' in src)  # the other flag is untouched


def test_invalid_python_raises():
    with pytest.raises(ValueError):
        retire_flag("def (:", "x", keep_variant="a")


YAML = '''\
# header
check_every_seconds: 5

flags:
  a_flag:
    experiment: A
    retire:             # nested
      metric: m
  buy_button:
    experiment: B
    max_error_rate: 0.05
    retire:
      code: shop/app.py
      metric: purchase

  last:
    experiment: C
'''


def test_remove_contract_entry_keeps_everything_else():
    out, removed = remove_contract_entry(YAML, "buy_button")
    assert removed
    assert "buy_button" not in out and "shop/app.py" not in out and "purchase" not in out
    assert "# header" in out and "a_flag:" in out and "metric: m" in out and "  last:\n    experiment: C" in out
    import yaml
    assert set(yaml.safe_load(out)["flags"]) == {"a_flag", "last"}
    assert remove_contract_entry(out, "buy_button") == (out, False)
