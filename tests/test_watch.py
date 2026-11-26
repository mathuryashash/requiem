import httpx
import pytest

from requiem.watch import parse_vector, read_window, window_queries


def vec(pairs):
    return {"status": "success", "data": {"resultType": "vector", "result": [
        {"metric": {"flag_variant": v}, "value": [0, str(n)]} for v, n in pairs]}}


def test_queries_filter_on_flag_and_error_status():
    q_all, q_err = window_queries("new_checkout", 30)
    assert 'flag_key="new_checkout"' in q_all and "[30s]" in q_all
    assert 'status_code="STATUS_CODE_ERROR"' in q_err


def test_parse_vector_and_failure():
    assert parse_vector(vec([("control", 10), ("new", 4.5)])) == {"control": 10.0, "new": 4.5}
    with pytest.raises(RuntimeError):
        parse_vector({"status": "error", "error": "bad query"})


def test_read_window_joins_calls_and_errors():
    def handler(req: httpx.Request):
        q = req.url.params["query"]
        return httpx.Response(200, json=vec([("new", 6)]) if "STATUS_CODE_ERROR" in q else vec([("control", 40), ("new", 20)]))

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        w = read_window("http://prom", "new_checkout", 30, client=c)
    assert w["new"].requests == 20 and w["new"].error_rate == pytest.approx(0.3)
    assert w["control"].errors == 0
