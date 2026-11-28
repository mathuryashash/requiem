## Requiem NAG: 1 overdue of 2 flag(s)

Checked on 2026-11-28 (warning window: 14 days).

| Flag | Owner | Dies on | Status | References | Flagsmith |
|---|---|---|---|---|---|
| `new_checkout` | @mathuryashash | 2026-11-20 (8d late) | 🔴 overdue | 40 | flag exists; in experiment 'New checkout' (paused) |
| `buy_button` | @mathuryashash | 2026-12-05 (in 7d) | 🟡 due soon | 52 | flag exists; in experiment 'Green buy button' (running) |

<details><summary>References to <code>new_checkout</code> (40)</summary>

- `demo/reset_demo.py:32`: `names = {"buy_button": "Green buy button", "new_checkout": "New checkout"}  # demo/setup_demo.py FLAGS`
- `demo/setup_demo.py:7`: `new_checkout  control "old",  variant key "new"`
- `demo/setup_demo.py:25`: `{"name": "new_checkout", "control": "old", "variant": "new",`
- `deploy/grafana-provisioning/dashboards/requiem.json:39`: `"title": "new_checkout: error rate per variant (contract ceiling 5%)",`
- `deploy/grafana-provisioning/dashboards/requiem.json:72`: `"expr": "sum by (flag_variant) (rate(traces_span_metrics_calls_total{flag_key=\"new_checkout\",status_code=\"STATUS_CODE_ERROR\"}[30s])) / sum by (flag_variant)`
- `deploy/grafana-provisioning/dashboards/requiem.json:84`: `"title": "new_checkout: requests per second per variant",`
- `deploy/grafana-provisioning/dashboards/requiem.json:117`: `"expr": "sum by (flag_variant) (rate(traces_span_metrics_calls_total{flag_key=\"new_checkout\"}[30s]))",`
- `deploy/grafana-provisioning/dashboards/requiem.json:129`: `"title": "new_checkout: p95 latency per variant",`
- `deploy/grafana-provisioning/dashboards/requiem.json:162`: `"expr": "histogram_quantile(0.95, sum by (le, flag_variant) (rate(traces_span_metrics_duration_milliseconds_bucket{flag_key=\"new_checkout\"}[1m])))",`
- `deploy/spike1_bootstrap.py:55`: `"name": "new_checkout",`
- `deploy/spike1_bootstrap.py:136`: `"flag_key": "new_checkout",`
- `deploy/spike1_bootstrap.py:180`: `"flag_name": "new_checkout",`
- `deploy/spike1_bootstrap.sh:41`: `echo -e "\n--- Creating multivariate feature flag 'new_checkout' ---"`
- `deploy/spike1_bootstrap.sh:43`: `"name": "new_checkout",`
- `deploy/spike1_bootstrap.sh:112`: `"flag_name": "new_checkout",`
- `deploy/spike1_bootstrap.sh:123`: `echo "✓ Multivariate flag 'new_checkout' created"`
- `loadgen/run.py:90`: `def measure(trials: int, flag: str = "new_checkout") -> None:`
- `loadgen/run.py:132`: `"contract": "requiem.yaml new_checkout", "trials": results,`
- `requiem/service.py:4`: `python -m requiem.service undo new_checkout  # put the experiment back as it was`
- `shop/app.py:4`: `- 'new_checkout' (control old, variant new) on POST /api/checkout. A fault switch makes the new`
- `shop/app.py:94`: `variant, value = _variant("new_checkout", user)`
- `shop/app.py:95`: `span.set_attribute("flag.key", "new_checkout")`
- `tests/test_codemod.py:119`: `other, v2 = _variant("new_checkout", user)`
- `tests/test_codemod.py:120`: `span.set_attribute("flag.key", "new_checkout")`
- `tests/test_codemod.py:127`: `assert '_variant("new_checkout", user)' in out and "span.set_attribute(\"flag.key\", \"new_checkout\")" in out`
- `tests/test_codemod.py:181`: `variant, value = _variant("new_checkout", user)`
- `tests/test_codemod.py:185`: `out, _ = run(src, flag="new_checkout", keep_variant="new", keep_value="new")`
- `tests/test_codemod.py:218`: `("new_checkout", "new", "new"), ("new_checkout", "control", "old")])`
- `tests/test_codemod.py:227`: `other = "new_checkout" if flag == "buy_button" else "buy_button"`
- `tests/test_decide.py:5`: `C = Contract(flag="new_checkout", experiment="New checkout", max_error_rate=0.05, min_requests=20,`
- `tests/test_flagsmith_api.py:37`: `"id": 2, "name": "new_checkout", "type": "MULTIVARIATE", "initial_value": "old",`
- `tests/test_flagsmith_api.py:40`: `assert (e.feature_id, e.feature_name, e.control_value) == (2, "new_checkout", "old")`
- `tests/test_flagsmith_api.py:92`: `post_feature_health("http://fs.local/hook", "new_checkout", "Production", unhealthy=True,`
- `tests/test_flagsmith_api.py:94`: `assert sent == {"feature": "new_checkout", "environment": "Production", "status": "unhealthy",`
- `tests/test_shop_flags.py:2`: `buy_button / new_checkout flags are retired, which is what lets the retire branch run the suite."""`
- `tests/test_shop_flags.py:43`: `if has_lookup(shop, "new_checkout"):`
- `tests/test_shop_flags.py:55`: `if has_lookup(shop, "new_checkout"):`
- `tests/test_watch.py:13`: `q_all, q_err = window_queries("new_checkout", 30)`
- `tests/test_watch.py:14`: `assert 'flag_key="new_checkout"' in q_all and "[30s]" in q_all`
- `tests/test_watch.py:30`: `w = read_window("http://prom", "new_checkout", 30, client=c)`

</details>

<details><summary>References to <code>buy_button</code> (52)</summary>

- `demo/reset_demo.py:3`: `python demo/reset_demo.py buy_button           # Flagsmith side`
- `demo/reset_demo.py:32`: `names = {"buy_button": "Green buy button", "new_checkout": "New checkout"}  # demo/setup_demo.py FLAGS`
- `demo/setup_demo.py:6`: `buy_button    control "grey", variant key "green"`
- `demo/setup_demo.py:12`: `Usage:  python demo/setup_demo.py --token <admin API token> [--url http://localhost:8000] [--only buy_button]`
- `demo/setup_demo.py:23`: `{"name": "buy_button", "control": "grey", "variant": "green",`
- `deploy/grafana-provisioning/dashboards/requiem.json:174`: `"title": "buy_button: requests per second per variant",`
- `deploy/grafana-provisioning/dashboards/requiem.json:207`: `"expr": "sum by (flag_variant) (rate(traces_span_metrics_calls_total{flag_key=\"buy_button\"}[30s]))",`
- `loadgen/run.py:14`: `python loadgen/run.py convert --shoppers 400 --prefix rt1_   # traffic for the buy_button RETIRE run`
- `loadgen/run.py:16`: `'convert' is how the buy_button experiment gets its evidence. Each shopper has a fixed identity,`
- `loadgen/run.py:161`: `out = {"what": "script-generated shoppers for the buy_button experiment", "shoppers": shoppers, "prefix": prefix,`
- `requiem/codemod.py:6`: `variant, value = _variant("buy_button", user)       # the flag lookup`
- `requiem/codemod.py:7`: `span.set_attribute("flag.key", "buy_button")        # span tags that exist only for the flag`
- `requiem/service.py:5`: `python -m requiem.service retire buy_button  # RETIRE: read results, write the decision memo, change nothing`
- `requiem/service.py:6`: `python -m requiem.service approve buy_button --memo <sha256 prefix> [--open-pr]`
- `requiem/service.py:7`: `python -m requiem.service open-pr buy_button # push the retire branch and run 'gh pr create'`
- `shop/app.py:3`: `- 'buy_button' (control grey, variant green) on GET /api/product`
- `shop/app.py:80`: `variant, value = _variant("buy_button", user)`
- `shop/app.py:81`: `span.set_attribute("flag.key", "buy_button")`
- `spikes/experiment_e2e.py:102`: `feature = find(f"/projects/{proj['id']}/features/", "buy_button") or must(`
- `spikes/experiment_e2e.py:104`: `"name": "buy_button",`
- `spikes/experiment_e2e.py:164`: `flag = next((f for f in body.get("flags", []) if f["feature"]["name"] == "buy_button"), None)`
- `spikes/experiment_e2e.py:177`: `events.append({"event": "$flag_exposure", "feature_name": "buy_button", "identifier": ident,`
- `spikes/kill_latency.py:39`: `flag = next(f for f in body["flags"] if f["feature"]["name"] == "buy_button")`
- `spikes/kill_latency.py:62`: `feature = next(f for f in feats if f["name"] == "buy_button")`
- `tests/test_codemod.py:14`: `variant, value = _variant("buy_button", user)`
- `tests/test_codemod.py:15`: `span.set_attribute("flag.key", "buy_button")`
- `tests/test_codemod.py:36`: `def run(src, flag="buy_button", **kw):`
- `tests/test_codemod.py:64`: `variant, value = _variant("buy_button", user)`
- `tests/test_codemod.py:82`: `variant, value = _variant("buy_button", user)`
- `tests/test_codemod.py:95`: `variant, value = _variant("buy_button", user)`
- `tests/test_codemod.py:107`: `variant, value = _variant("buy_button", user)`
- `tests/test_codemod.py:118`: `variant, value = _variant("buy_button", user)`
- `tests/test_codemod.py:135`: `out, rep = retire_flag(src, "buy_button", keep_variant="green")`
- `tests/test_codemod.py:142`: `variant, value = _variant("buy_button", user)`
- `tests/test_codemod.py:152`: `assert any("string \"buy_button\" is still used" in u for u in rep.unsupported)`
- `tests/test_codemod.py:159`: `src = "def f(user):\n    variant, value = _variant(\"buy_button\", user)\n" + body`
- `tests/test_codemod.py:167`: `variant, value = _variant("buy_button", user)`
- `tests/test_codemod.py:171`: `return flagsmith.get_experiment_flag("buy_button", identifier=user)`
- `tests/test_codemod.py:174`: `assert "get_experiment_flag(\"buy_button\"" in out`
- `tests/test_codemod.py:192`: `variant, value = _variant("buy_button", user)`
- `tests/test_codemod.py:217`: `@pytest.mark.parametrize("flag,kv,val", [("buy_button", "green", "green"), ("buy_button", "control", "grey"),`
- `tests/test_codemod.py:227`: `other = "new_checkout" if flag == "buy_button" else "buy_button"`
- `tests/test_codemod.py:245`: `buy_button:`
- `tests/test_codemod.py:258`: `out, removed = remove_contract_entry(YAML, "buy_button")`
- `tests/test_codemod.py:260`: `assert "buy_button" not in out and "shop/app.py" not in out and "purchase" not in out`
- `tests/test_codemod.py:264`: `assert remove_contract_entry(out, "buy_button") == (out, False)`
- `tests/test_retire.py:160`: `"contract": {"remove_entry": "buy_button"}} if d.actionable else None`
- `tests/test_retire.py:161`: `return R.build_memo(flag="buy_button", experiment={"id": 1, "name": "Green buy button", "status": "running"},`
- `tests/test_retire.py:184`: `assert "/complete/" in md and "approve buy_button --memo " + sha[:12] in md and "requiem.yaml" in md`
- `tests/test_retire.py:200`: `c = Contract(flag="buy_button", experiment="Green buy button")`
- `tests/test_shop_flags.py:2`: `buy_button / new_checkout flags are retired, which is what lets the retire branch run the suite."""`
- `tests/test_shop_flags.py:32`: `if has_lookup(shop, "buy_button"):`

</details>
