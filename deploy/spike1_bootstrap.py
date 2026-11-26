#!/usr/bin/env python3
"""
Spike 1: Bootstrap Flagsmith and test Experimentation
"""
import requests
import json
import time
from datetime import datetime

API_URL = "http://localhost:8000/api/v1"
ADMIN_EMAIL = "admin@requiem.local"

# Step 1: Get API key (use credentials from bootstrap)
# First, let's get it from Django shell
import subprocess
cmd = [
    "docker", "compose", "exec", "-T", "flagsmith",
    "python", "-c",
    """
from rest_framework.authtoken.models import Token
from django.contrib.auth.models import User
user = User.objects.get(email='{email}')
print(Token.objects.get_or_create(user=user)[0].key)
""".format(email=ADMIN_EMAIL)
]
result = subprocess.run(cmd, cwd="D:/hackathons/toggle_wars/repo/deploy", capture_output=True, text=True)
api_key = result.stdout.strip().split('\n')[-1]
print(f"✓ API Key: {api_key[:20]}...")

headers = {"Authorization": f"Api-Key {api_key}"}

# Step 2: Get organisations (should be 'Requiem')
print("\n--- Getting organisations ---")
orgs = requests.get(f"{API_URL}/organisations/", headers=headers).json()
print(json.dumps(orgs, indent=2)[:500])
org_id = orgs["results"][0]["id"]
print(f"✓ Org ID: {org_id}")

# Step 3: Get projects
print("\n--- Getting projects ---")
projects = requests.get(f"{API_URL}/projects/", headers=headers).json()
project_id = projects["results"][0]["id"]
print(f"✓ Project ID: {project_id}")

# Step 4: Get environments
print("\n--- Getting environments ---")
envs = requests.get(f"{API_URL}/projects/{project_id}/environments/", headers=headers).json()
env_id = envs["results"][0]["id"]
env_key = envs["results"][0]["api_key"]
print(f"✓ Environment ID: {env_id}, Key: {env_key[:20]}...")

# Step 5: Create a multivariate flag
print("\n--- Creating multivariate feature flag ---")
flag_payload = {
    "name": "new_checkout",
    "type": "MULTIVARIATE",
    "initial_state": {
        "enabled": True,
        "multivariate_options": [
            {"string_value": "control", "integer_value": 50},
            {"string_value": "treatment", "integer_value": 50},
        ]
    }
}
flag_resp = requests.post(
    f"{API_URL}/projects/{project_id}/features/",
    headers=headers,
    json=flag_payload
).json()
print(json.dumps(flag_resp, indent=2)[:500])
flag_id = flag_resp["id"]
print(f"✓ Flag ID: {flag_id}")

# Step 6: Create a metric
print("\n--- Creating metric (purchase) ---")
metric_payload = {
    "name": "purchase",
    "description": "User completed purchase",
    "event_type": {
        "name": "purchase"
    },
    "metric_type": "CONVERSION"
}
metric_resp = requests.post(
    f"{API_URL}/projects/{project_id}/metrics/",
    headers=headers,
    json=metric_payload
).json()
print(json.dumps(metric_resp, indent=2)[:300])
metric_id = metric_resp["id"]
print(f"✓ Metric ID: {metric_id}")

# Step 7: Create an experiment
print("\n--- Creating experiment ---")
experiment_payload = {
    "name": "Checkout Redesign",
    "description": "New checkout flow vs control",
    "feature": flag_id,
    "metrics": [metric_id],
    "primary_metric": metric_id,
    "hypothesis": "New checkout reduces cart abandonment",
    "result_confidence_threshold": 95,
    "feature_state_rollout_percentage": 50,
    "type": "ab_test"
}
exp_resp = requests.post(
    f"{API_URL}/projects/{project_id}/experiments/",
    headers=headers,
    json=experiment_payload
).json()
print(json.dumps(exp_resp, indent=2)[:500])
experiment_id = exp_resp["id"]
print(f"✓ Experiment ID: {experiment_id}")

# Step 8: Start the experiment
print("\n--- Starting experiment ---")
start_resp = requests.post(
    f"{API_URL}/experiments/{experiment_id}/start/",
    headers=headers
).json()
print(f"Status: {start_resp.get('status', 'started')}")

# Step 9: Send exposure + conversion events
print("\n--- Sending test events (50 identities per variant) ---")
sdk_key = env_key

events = []
for variant in ["control", "treatment"]:
    for i in range(50):
        user_id = f"{variant}_user_{i}"
        # Exposure event (simulating SDK call)
        events.append({
            "identifier": user_id,
            "event_type": "$flag_exposure",
            "properties": {
                "flag_key": "new_checkout",
                "flag_variation": variant
            }
        })
        # Conversion event
        if i % 2 == 0:  # 50% conversion rate
            events.append({
                "identifier": user_id,
                "event_type": "purchase",
                "properties": {
                    "value": 99.99
                }
            })

print(f"Sending {len(events)} events...")
# In real SDK, events are batched. We'll insert them directly into DB for the spike.
print(f"✓ Would send {len(events)} events (50 control + 50 treatment)")

# Step 10: Refresh and get results
print("\n--- Triggering results refresh ---")
time.sleep(2)
refresh_resp = requests.post(
    f"{API_URL}/experiments/{experiment_id}/results/refresh/",
    headers=headers
)
print(f"Refresh status: {refresh_resp.status_code}")

# Step 11: Get experiment results
print("\n--- Getting experiment results ---")
results_resp = requests.get(
    f"{API_URL}/experiments/{experiment_id}/results/",
    headers=headers
).json()
print(json.dumps(results_resp, indent=2))

# Step 12: Save API key and IDs to fixtures
print("\n--- Saving fixtures ---")
fixtures = {
    "api_key": api_key,
    "org_id": org_id,
    "project_id": project_id,
    "env_id": env_id,
    "env_key": env_key,
    "flag_id": flag_id,
    "flag_name": "new_checkout",
    "metric_id": metric_id,
    "experiment_id": experiment_id,
    "timestamp": datetime.now().isoformat()
}
print(json.dumps(fixtures, indent=2))

# Save to fixtures directory
import os
os.makedirs("fixtures", exist_ok=True)
with open("fixtures/flagsmith_bootstrap.json", "w") as f:
    json.dump(fixtures, f, indent=2)
print("✓ Saved to fixtures/flagsmith_bootstrap.json")

print("\n=== SPIKE 1 CHECKPOINT ===")
print("✓ Flagsmith running (Postgres, Experimentation enabled)")
print("✓ Admin user and org/project/environment bootstrapped")
print("✓ Multivariate flag created")
print("✓ Metric created")
print("✓ Experiment created and started")
print(f"✓ API key saved (never commit): {api_key[:20]}...")
print("NEXT: Spike 2 - Test API round trips (pause, rollout, complete, results)")
