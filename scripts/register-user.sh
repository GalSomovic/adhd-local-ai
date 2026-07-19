#!/usr/bin/env bash
# Register a Matrix user on the token-gated homeserver (UIA two-step flow).
# usage: register-user.sh <homeserver-url> <username> <password> <registration-token>
set -euo pipefail
HS=$1 USERNAME=$2 PASSWORD=$3 TOKEN=$4

SESSION=$(curl -fsS -X POST "$HS/_matrix/client/v3/register" \
  -H 'content-type: application/json' -d '{}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["session"])' 2>/dev/null) || {
  SESSION=$(curl -sS -X POST "$HS/_matrix/client/v3/register" \
    -H 'content-type: application/json' -d '{}' \
    | python3 -c 'import sys,json; print(json.load(sys.stdin)["session"])')
}

python3 - "$USERNAME" "$PASSWORD" "$TOKEN" "$SESSION" <<'EOF' > /tmp/register-body.json
import json, sys
u, p, t, s = sys.argv[1:5]
print(json.dumps({
    "username": u,
    "password": p,
    "auth": {"type": "m.login.registration_token", "token": t, "session": s},
}))
EOF

curl -fsS -X POST "$HS/_matrix/client/v3/register" \
  -H 'content-type: application/json' \
  -d @/tmp/register-body.json
rm -f /tmp/register-body.json
echo
echo "registered @$USERNAME"
