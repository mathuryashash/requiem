"""FlagsmithAPI against recorded shapes from the live instance (fixtures/spike1), no network."""

import json
from pathlib import Path

import httpx
import pytest

from requiem.flagsmith_api import FlagsmithAPI, FlagsmithError, post_feature_health

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "spike1"


def recorded(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))["body"]


def make(handler):
    return FlagsmithAPI("http://fs.local", "tok", "ENVKEY", 2, transport=httpx.MockTransport(handler))


def test_experiment_lookup_uses_environment_path_and_token():
    exp = recorded("07_experiment.json")
    seen = {}

    def handler(req: httpx.Request):
        seen["path"], seen["auth"] = req.url.path, req.headers["authorization"]
        return httpx.Response(200, json=[exp])

    e = make(handler).experiment_by_name(exp["name"])
    assert seen == {"path": "/api/v1/environments/ENVKEY/experiments/", "auth": "Token tok"}
    assert (e.id, e.feature_id) == (exp["id"], exp["feature"])


def test_list_endpoint_nests_the_feature_with_its_options():
    listed = {"id": 2, "name": "New checkout", "status": "running", "feature": {
        "id": 2, "name": "new_checkout", "type": "MULTIVARIATE", "initial_value": "old",
        "multivariate_options": [{"id": 2, "string_value": "new", "key": "new"}]}}
    e = make(lambda req: httpx.Response(200, json=[listed])).experiment_by_name("New checkout")
    assert (e.feature_id, e.feature_name, e.control_value) == (2, "new_checkout", "old")
    assert [(v.option_id, v.key) for v in e.variants] == [(2, "new")]


def test_unknown_experiment_raises_lookup_error():
    with pytest.raises(LookupError):
        make(lambda req: httpx.Response(200, json={"results": []})).experiment_by_name("nope")


def test_kill_rollout_body_matches_what_the_live_api_accepted():
    sent = {}

    def handler(req: httpx.Request):
        sent["method"], sent["path"], sent["body"] = req.method, req.url.path, json.loads(req.content)
        return httpx.Response(200, json={"id": 1})

    make(handler).set_rollout(1, 0, "old", {7: 50.0})
    assert sent["method"] == "PATCH"
    assert sent["path"] == "/api/v1/environments/ENVKEY/experiments/1/rollout/"
    assert sent["body"] == {
        "enabled": True, "rollout_percentage": 0,
        "feature_state_value": {"type": "string", "value": "old"},
        "multivariate_feature_state_values": [{"multivariate_feature_option": 7, "percentage_allocation": 50.0}],
    }


def test_variants_read_option_keys():
    feat = recorded("04_feature.json")
    feat["multivariate_options"][0]["key"] = "green"
    vs = make(lambda req: httpx.Response(200, json=feat)).variants(feat["id"])
    assert [(v.key, v.value) for v in vs] == [("green", "green")]


def test_http_errors_raise_with_status():
    with pytest.raises(FlagsmithError) as e:
        make(lambda req: httpx.Response(400, json={"experiment_rollout": ["This field is required."]})).pause(1)
    assert e.value.status == 400


def test_results_unwraps_payload():
    body = recorded("15_results.json")
    res = make(lambda req: httpx.Response(200, json=body)).results(1)
    assert "green" in res["payload"]["metrics"][0]["inference"]


def test_feature_health_body():
    sent = {}

    def handler(req: httpx.Request):
        sent.update(json.loads(req.content))
        return httpx.Response(200)

    post_feature_health("http://fs.local/hook", "new_checkout", "Production", unhealthy=True,
                        title="Requiem kill", text="30% errors", transport=httpx.MockTransport(handler))
    assert sent == {"feature": "new_checkout", "environment": "Production", "status": "unhealthy",
                    "reason": {"text_blocks": [{"title": "Requiem kill", "text": "30% errors"}], "url_blocks": []}}
