"""Put the demo back so the RETIRE run can be repeated from the start.

  python demo/reset_demo.py buy_button           # Flagsmith side
  git restore shop/app.py requiem.yaml           # code side, if you merged or kept a retire branch's changes

A completed experiment is final in Flagsmith, so "reset" means: pause it if it is running, delete
it, put the flag's environment default back to control with a 50/50 split, then run
demo/setup_demo.py, which creates and starts a fresh experiment with the same name. The new
experiment's results window starts now, so earlier exposures do not count. Needs the same .env
as Requiem (FLAGSMITH_URL, FLAGSMITH_ADMIN_TOKEN, FLAGSMITH_ENVIRONMENT_KEY, FLAGSMITH_PROJECT_ID).
Only touches the experiments you name; never the other flags.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from requiem.flagsmith_api import FlagsmithAPI  # noqa: E402
from requiem.service import api_from_env, load_contracts, load_env  # noqa: E402


def main(flags: list[str]) -> int:
    load_env()
    api: FlagsmithAPI = api_from_env()
    contracts = {c.flag: c for c in load_contracts()[0]}
    names = {"buy_button": "Green buy button", "new_checkout": "New checkout"}  # demo/setup_demo.py FLAGS
    for flag in flags:
        name = contracts[flag].experiment if flag in contracts else names[flag]
        try:
            exp = api.experiment_by_name(name)
        except LookupError:
            print(f"{flag}: no experiment named {name!r}, nothing to delete")
            continue
        if exp.status == "running":
            api.pause(exp.id)
        api._call("DELETE", f"/environments/{api.env}/experiments/{exp.id}/")
        print(f"{flag}: deleted experiment {exp.id} (was {exp.status})")
    cmd = [sys.executable, str(ROOT / "demo" / "setup_demo.py"), "--token", os.environ["FLAGSMITH_ADMIN_TOKEN"],
           "--url", os.environ.get("FLAGSMITH_URL", "http://localhost:8000")]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    print("setup_demo ran (environment key / project id / webhook lines not shown)" if out else "setup_demo: no output")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1:]))
