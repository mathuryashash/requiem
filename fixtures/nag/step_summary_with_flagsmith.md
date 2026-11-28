## Requiem NAG: 1 overdue of 2 flag(s)

Checked on 2026-11-28 (warning window: 14 days).

| Flag | Owner | Dies on | Status | References | Flagsmith |
|---|---|---|---|---|---|
| `new_checkout` | @mathuryashash | 2026-11-20 (8d late) | 🔴 overdue | 31 | flag exists; in experiment 'New checkout' (paused) |
| `buy_button` | @mathuryashash | 2026-12-05 (in 7d) | 🟡 due soon | 15 | flag exists; in experiment 'Green buy button' (running) |

<details><summary>References to <code>new_checkout</code> (31)</summary>

- `README.md:14`: `| Demo shop with two experiments ('buy_button', 'new_checkout') and a fault switch | Works | 'shop/app.py' |`
- `README.md:17`: `| Undo | Works | 'python -m requiem.service undo new_checkout' |`
- `demo/setup_demo.py:7`: `new_checkout  control "old",  variant key "new"`
- `demo/setup_demo.py:25`: `{"name": "new_checkout", "control": "old", "variant": "new",`
- `deploy/spike1_bootstrap.py:55`: `"name": "new_checkout",`
- `deploy/spike1_bootstrap.py:136`: `"flag_key": "new_checkout",`
- `deploy/spike1_bootstrap.py:180`: `"flag_name": "new_checkout",`
- `deploy/spike1_bootstrap.sh:41`: `echo -e "\n--- Creating multivariate feature flag 'new_checkout' ---"`
- `deploy/spike1_bootstrap.sh:43`: `"name": "new_checkout",`
- `deploy/spike1_bootstrap.sh:112`: `"flag_name": "new_checkout",`
- `deploy/spike1_bootstrap.sh:123`: `echo "✓ Multivariate flag 'new_checkout' created"`
- `deploy/grafana-provisioning/dashboards/requiem.json:39`: `"title": "new_checkout: error rate per variant (contract ceiling 5%)",`
- `deploy/grafana-provisioning/dashboards/requiem.json:72`: `"expr": "sum by (flag_variant) (rate(traces_span_metrics_calls_total{flag_key=\"new_checkout\",status_code=\"STATUS_CODE_ERROR\"}[30s])) / sum by (flag_variant)`
- `deploy/grafana-provisioning/dashboards/requiem.json:84`: `"title": "new_checkout: requests per second per variant",`
- `deploy/grafana-provisioning/dashboards/requiem.json:117`: `"expr": "sum by (flag_variant) (rate(traces_span_metrics_calls_total{flag_key=\"new_checkout\"}[30s]))",`
- `deploy/grafana-provisioning/dashboards/requiem.json:129`: `"title": "new_checkout: p95 latency per variant",`
- `deploy/grafana-provisioning/dashboards/requiem.json:162`: `"expr": "histogram_quantile(0.95, sum by (le, flag_variant) (rate(traces_span_metrics_duration_milliseconds_bucket{flag_key=\"new_checkout\"}[1m])))",`
- `loadgen/run.py:79`: `def measure(trials: int, flag: str = "new_checkout") -> None:`
- `loadgen/run.py:121`: `"contract": "requiem.yaml new_checkout", "trials": results,`
- `requiem/service.py:4`: `python -m requiem.service undo new_checkout  # put the experiment back as it was`
- `shop/app.py:4`: `- 'new_checkout' (control old, variant new) on POST /api/checkout. A fault switch makes the new`
- `shop/app.py:87`: `variant, value = _variant("new_checkout", user)`
- `shop/app.py:88`: `span.set_attribute("flag.key", "new_checkout")`
- `tests/test_decide.py:5`: `C = Contract(flag="new_checkout", experiment="New checkout", max_error_rate=0.05, min_requests=20,`
- `tests/test_flagsmith_api.py:37`: `"id": 2, "name": "new_checkout", "type": "MULTIVARIATE", "initial_value": "old",`
- `tests/test_flagsmith_api.py:40`: `assert (e.feature_id, e.feature_name, e.control_value) == (2, "new_checkout", "old")`
- `tests/test_flagsmith_api.py:92`: `post_feature_health("http://fs.local/hook", "new_checkout", "Production", unhealthy=True,`
- `tests/test_flagsmith_api.py:94`: `assert sent == {"feature": "new_checkout", "environment": "Production", "status": "unhealthy",`
- `tests/test_watch.py:13`: `q_all, q_err = window_queries("new_checkout", 30)`
- `tests/test_watch.py:14`: `assert 'flag_key="new_checkout"' in q_all and "[30s]" in q_all`
- `tests/test_watch.py:30`: `w = read_window("http://prom", "new_checkout", 30, client=c)`

</details>

<details><summary>References to <code>buy_button</code> (15)</summary>

- `README.md:14`: `| Demo shop with two experiments ('buy_button', 'new_checkout') and a fault switch | Works | 'shop/app.py' |`
- `SPIKE_RESULTS.md:17`: `| Multivariate flag 'buy_button' (grey control, green variant) | Created | '04_feature.json' |`
- `demo/setup_demo.py:6`: `buy_button    control "grey", variant key "green"`
- `demo/setup_demo.py:23`: `{"name": "buy_button", "control": "grey", "variant": "green",`
- `deploy/grafana-provisioning/dashboards/requiem.json:174`: `"title": "buy_button: requests per second per variant",`
- `deploy/grafana-provisioning/dashboards/requiem.json:207`: `"expr": "sum by (flag_variant) (rate(traces_span_metrics_calls_total{flag_key=\"buy_button\"}[30s]))",`
- `shop/app.py:3`: `- 'buy_button' (control grey, variant green) on GET /api/product`
- `shop/app.py:77`: `variant, value = _variant("buy_button", user)`
- `shop/app.py:78`: `span.set_attribute("flag.key", "buy_button")`
- `spikes/experiment_e2e.py:102`: `feature = find(f"/projects/{proj['id']}/features/", "buy_button") or must(`
- `spikes/experiment_e2e.py:104`: `"name": "buy_button",`
- `spikes/experiment_e2e.py:164`: `flag = next((f for f in body.get("flags", []) if f["feature"]["name"] == "buy_button"), None)`
- `spikes/experiment_e2e.py:177`: `events.append({"event": "$flag_exposure", "feature_name": "buy_button", "identifier": ident,`
- `spikes/kill_latency.py:39`: `flag = next(f for f in body["flags"] if f["feature"]["name"] == "buy_button")`
- `spikes/kill_latency.py:62`: `feature = next(f for f in feats if f["name"] == "buy_button")`

</details>
