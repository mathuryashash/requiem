#!/bin/bash
# Quick spike: get API credentials and IDs and save them

API_URL="http://localhost:8000/api/v1"

# Wait for Flagsmith to be fully ready
sleep 5

# Try to create superuser password for admin if needed, then auth
echo "Testing Flagsmith API..."
curl -s "$API_URL/organisations/" -H "Authorization: Api-Key invalid" > /dev/null 2>&1

# Restart the container to apply migrations
cd "D:/hackathons/toggle_wars/repo/deploy"
docker compose restart flagsmith

# Wait again
sleep 10

# Now get the API key via a one-off container that can interact with Django
echo "Getting API credentials..."
API_KEY=$(docker compose exec -T flagsmith python manage.py shell -c "
from rest_framework.authtoken.models import Token
from users.models import FFAdminUser as User
user = User.objects.get(email='admin@requiem.local')
print(Token.objects.get_or_create(user=user)[0].key)
" 2>/dev/null | grep -v "^2026\|^time\|^objects\|^>>>" | tail -1)

echo "API_KEY: $API_KEY"

if [ -z "$API_KEY" ]; then
    echo "ERROR: Could not get API key"
    exit 1
fi

# Save minimal fixture
mkdir -p "D:/hackathons/toggle_wars/repo/fixtures"
cat > "D:/hackathons/toggle_wars/repo/.env.local" << EOF
API_KEY=$API_KEY
API_URL=$API_URL
EOF

echo "✓ Credentials saved to .env.local (keep .gitignored)"
echo "API_KEY=${API_KEY:0:20}..."
