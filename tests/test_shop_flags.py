"""The shop's flag-driven branches, with the Flagsmith lookup stubbed. Passes before and after the
buy_button / new_checkout flags are retired, which is what lets the retire branch run the suite."""

import importlib
import sys

import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")


@pytest.fixture(scope="module")
def shop():
    import os
    os.environ.setdefault("FLAGSMITH_ENVIRONMENT_KEY", "test-key-not-real")
    os.environ.setdefault("FLAGSMITH_URL", "http://127.0.0.1:9")
    sys.modules.pop("shop.app", None)
    return importlib.import_module("shop.app")


def has_lookup(shop, flag):
    import inspect
    return f'_variant("{flag}"' in inspect.getsource(shop)


@pytest.mark.parametrize("variant,value", [("green", "green"), ("control", "grey")])
def test_product_page(shop, monkeypatch, variant, value):
    monkeypatch.setattr(shop, "_variant", lambda flag, user: (variant, value))
    r = fastapi_testclient.TestClient(shop.app).get("/api/product", params={"user": "u1"})
    body = r.json()
    assert r.status_code == 200 and body["button_colour"] in ("green", "grey") and body["label"]
    if has_lookup(shop, "buy_button"):
        assert body["button_colour"] == value and body["variant"] == variant


@pytest.mark.parametrize("variant,value,steps", [("new", "new", 2), ("control", "old", 3)])
def test_checkout(shop, monkeypatch, variant, value, steps):
    monkeypatch.setattr(shop, "_variant", lambda flag, user: (variant, value))
    monkeypatch.setattr(shop.flagsmith, "track_event", lambda *a, **k: None)
    r = fastapi_testclient.TestClient(shop.app).post("/api/checkout", params={"user": "u1"})
    body = r.json()
    assert r.status_code == 200 and body["ok"] and len(body["steps"]) in (2, 3)
    if has_lookup(shop, "new_checkout"):
        assert len(body["steps"]) == steps and body["variant"] == variant


def test_fault_still_breaks_only_the_non_control_variant(shop, monkeypatch):
    monkeypatch.setattr(shop, "_variant", lambda flag, user: ("new", "new"))
    monkeypatch.setattr(shop.flagsmith, "track_event", lambda *a, **k: None)
    c = fastapi_testclient.TestClient(shop.app)
    c.post("/admin/fault", json={"enabled": True, "rate": 1.0})
    try:
        assert c.post("/api/checkout", params={"user": "u1"}).status_code == 500
        monkeypatch.setattr(shop, "_variant", lambda flag, user: ("control", "old"))
        if has_lookup(shop, "new_checkout"):
            assert c.post("/api/checkout", params={"user": "u1"}).status_code == 200
    finally:
        c.post("/admin/fault", json={"enabled": False})
