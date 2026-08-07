#!/bin/bash
# Simulate manager-response and payment webhooks against a running local server.
# Usage:
#   export BASE_URL="https://abcd1234.ngrok.io"  # or http://localhost:8000
#   ./scripts/simulate_webhooks.sh

set -e
: "${BASE_URL:?Please set BASE_URL env var to your ngrok or local server URL}"

echo "Simulating manager response webhook..."
curl -s -X POST "$BASE_URL/api/webhooks/manager-response/" \
  -H "Content-Type: application/json" \
  -d '{"order_item_id": 1, "manager_bale_id": "897950525", "action": "approve"}' | jq || true

sleep 1

echo "Simulating payment webhook (paid)..."
curl -s -X POST "$BASE_URL/api/webhooks/payment/" \
  -H "Content-Type: application/json" \
  -d '{"order_id": 1, "status": "paid"}' | jq || true

echo "Done. Check your server logs for processing results."
