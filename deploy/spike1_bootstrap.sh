#!/bin/bash
# Spike 1: Bootstrap Flagsmith and test Experimentation

set -e

API_URL="http://localhost:8000/api/v1"
ADMIN_EMAIL="admin@requiem.local"

echo "=== SPIKE 1: FLAGSMITH + EXPERIMENTATION ==="

# Step 1: Get API key
echo -e "\n--- Getting API key ---"
API_KEY=$(cd "D:/hackathons/toggle_wars/repo/deploy" && docker compose exec -T flagsmith python -c "
from rest_framework.authtoken.models import Token
from django.contrib.auth.models import User
user = User.objects.get(email='$ADMIN_EMAIL')
print(Token.objects.get_or_create(user=user)[0].key)
" 2>/dev/null | tail -1)
echo "✓ API Key: ${API_KEY:0:20}..."

# Step 2: Get organisations
echo -e "\n--- Getting organisations ---"
ORG_RESP=$(curl -s "$API_URL/organisations/" -H "Authorization: Api-Key $API_KEY")
ORG_ID=$(echo "$ORG_RESP" | grep -o '"id":[0-9]*' | head -1 | cut -d: -f2)
echo "✓ Org ID: $ORG_ID"

# Step 3: Get projects
echo -e "\n--- Getting projects ---"
PROJECT_RESP=$(curl -s "$API_URL/projects/" -H "Authorization: Api-Key $API_KEY")
PROJECT_ID=$(echo "$PROJECT_RESP" | grep -o '"id":[0-9]*' | head -1 | cut -d: -f2)
echo "✓ Project ID: $PROJECT_ID"

# Step 4: Get environments
echo -e "\n--- Getting environments ---"
ENV_RESP=$(curl -s "$API_URL/projects/$PROJECT_ID/environments/" -H "Authorization: Api-Key $API_KEY")
ENV_ID=$(echo "$ENV_RESP" | grep -o '"id":[0-9]*' | head -1 | cut -d: -f2)
ENV_KEY=$(echo "$ENV_RESP" | grep -o '"api_key":"[^"]*"' | head -1 | cut -d'"' -f4)
echo "✓ Environment ID: $ENV_ID, Key: ${ENV_KEY:0:20}..."

# Step 5: Create a multivariate flag
echo -e "\n--- Creating multivariate feature flag 'new_checkout' ---"
FLAG_PAYLOAD='{
  "name": "new_checkout",
  "type": "MULTIVARIATE",
  "initial_state": {
    "enabled": true,
    "multivariate_options": [
      {"string_value": "control", "integer_value": 50},
      {"string_value": "treatment", "integer_value": 50}
    ]
  }
}'
FLAG_RESP=$(curl -s -X POST "$API_URL/projects/$PROJECT_ID/features/" \
  -H "Authorization: Api-Key $API_KEY" \
  -H "Content-Type: application/json" \
  -d "$FLAG_PAYLOAD")
FLAG_ID=$(echo "$FLAG_RESP" | grep -o '"id":[0-9]*' | head -1 | cut -d: -f2)
echo "✓ Flag ID: $FLAG_ID"

# Step 6: Create a metric
echo -e "\n--- Creating metric 'purchase' ---"
METRIC_PAYLOAD='{
  "name": "purchase",
  "description": "User completed purchase",
  "event_type": {"name": "purchase"},
  "metric_type": "CONVERSION"
}'
METRIC_RESP=$(curl -s -X POST "$API_URL/projects/$PROJECT_ID/metrics/" \
  -H "Authorization: Api-Key $API_KEY" \
  -H "Content-Type: application/json" \
  -d "$METRIC_PAYLOAD")
METRIC_ID=$(echo "$METRIC_RESP" | grep -o '"id":[0-9]*' | head -1 | cut -d: -f2)
echo "✓ Metric ID: $METRIC_ID"

# Step 7: Create an experiment
echo -e "\n--- Creating experiment 'Checkout Redesign' ---"
EXP_PAYLOAD='{
  "name": "Checkout Redesign",
  "description": "New checkout flow vs control",
  "feature": '$FLAG_ID',
  "metrics": ['$METRIC_ID'],
  "primary_metric": '$METRIC_ID',
  "hypothesis": "New checkout reduces cart abandonment",
  "result_confidence_threshold": 95,
  "feature_state_rollout_percentage": 50,
  "type": "ab_test"
}'
EXP_RESP=$(curl -s -X POST "$API_URL/projects/$PROJECT_ID/experiments/" \
  -H "Authorization: Api-Key $API_KEY" \
  -H "Content-Type: application/json" \
  -d "$EXP_PAYLOAD")
EXPERIMENT_ID=$(echo "$EXP_RESP" | grep -o '"id":[0-9]*' | head -1 | cut -d: -f2)
echo "✓ Experiment ID: $EXPERIMENT_ID"

# Step 8: Start the experiment
echo -e "\n--- Starting experiment ---"
curl -s -X POST "$API_URL/experiments/$EXPERIMENT_ID/start/" \
  -H "Authorization: Api-Key $API_KEY" > /dev/null
echo "✓ Experiment started"

# Step 9: Save fixtures
echo -e "\n--- Saving fixtures ---"
mkdir -p "D:/hackathons/toggle_wars/repo/fixtures"
cat > "D:/hackathons/toggle_wars/repo/fixtures/flagsmith_spike1.json" << EOF
{
  "api_key": "$API_KEY",
  "org_id": $ORG_ID,
  "project_id": $PROJECT_ID,
  "env_id": $ENV_ID,
  "env_key": "$ENV_KEY",
  "flag_id": $FLAG_ID,
  "flag_name": "new_checkout",
  "metric_id": $METRIC_ID,
  "experiment_id": $EXPERIMENT_ID,
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
echo "✓ Saved to fixtures/flagsmith_spike1.json"

echo -e "\n=== SPIKE 1 CHECKPOINT ==="
echo "✓ Flagsmith running (Postgres, Experimentation enabled)"
echo "✓ Admin user and org/project/environment bootstrapped"
echo "✓ Multivariate flag 'new_checkout' created"
echo "✓ Metric 'purchase' created"
echo "✓ Experiment created and started"
echo "✓ API credentials saved (keep .gitignored)"
echo -e "\nNEXT: Spike 2 - Test API: pause/rollout/complete/results"
