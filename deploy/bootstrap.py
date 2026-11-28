"""One-shot bootstrap for `docker compose up`.

Waits for Flagsmith, creates (or reuses) an admin user, logs in to get its API token, builds the
org / project / environment / two experiments with demo/setup_demo.py, and writes the values the
shop and Requiem need to /shared/requiem.env. Safe to run on every `up`.

The admin user is made through Flagsmith's own sign-up API and /auth/login/; nothing needs a
shell inside the Flagsmith container. Credentials are a local-demo default; override with
REQUIEM_ADMIN_EMAIL / REQUIEM_ADMIN_PASSWORD.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from demo.setup_demo import setup  # noqa: E402

URL = os.environ.get("FLAGSMITH_URL", "http://flagsmith:8000").rstrip("/")
EMAIL = os.environ.get("REQUIEM_ADMIN_EMAIL", "admin@requiem.local")
PASSWORD = os.environ.get("REQUIEM_ADMIN_PASSWORD", "requiem-demo-password")
OUT = Path(os.environ.get("REQUIEM_ENV_FILE", "/shared/requiem.env"))


def post(path: str, body: dict) -> tuple[int, str]:
    req = urllib.request.Request(f"{URL}/api/v1{path}", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def wait_for_flagsmith(timeout_s: int = 300) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{URL}/health", timeout=5) as r:
                if r.status == 200:
                    print("flagsmith is up", flush=True)
                    return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(3)
    raise SystemExit(f"Flagsmith did not answer {URL}/health within {timeout_s}s")


def admin_token() -> str:
    status, body = post("/auth/users/", {"email": EMAIL, "password": PASSWORD, "re_password": PASSWORD,
                                         "first_name": "Requiem", "last_name": "Admin"})
    print(f"sign-up {EMAIL}: HTTP {status}" + (" (already exists, reusing)" if status == 400 else ""), flush=True)
    if status not in (200, 201, 400):
        raise SystemExit(f"sign-up failed: {status} {body[:300]}")
    status, body = post("/auth/login/", {"email": EMAIL, "password": PASSWORD})
    if status != 200 or "key" not in json.loads(body):
        raise SystemExit(f"login failed: {status} {body[:300]}")
    return json.loads(body)["key"]


def main() -> None:
    wait_for_flagsmith()
    token = admin_token()
    values = setup(URL, token)
    # The webhook URL is built from FLAGSMITH_DOMAIN (a host-side address); containers reach it by service name.
    hook = values["FLAGSMITH_HEALTH_WEBHOOK"]
    values["FLAGSMITH_HEALTH_WEBHOOK"] = URL + urlsplit(hook).path
    values.update(FLAGSMITH_ADMIN_TOKEN=token, FLAGSMITH_URL=URL)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
    OUT.chmod(0o644)
    print(f"wrote {OUT} with: {', '.join(values)}", flush=True)  # keys only, never values


if __name__ == "__main__":
    main()
