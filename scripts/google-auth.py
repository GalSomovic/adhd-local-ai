#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["google-auth-oauthlib"]
# ///
"""One-time Google OAuth — applies the credentials straight into the cluster.

usage: uv run scripts/google-auth.py ~/Downloads/client_secret.json

Opens a browser for the Google login, then patches the assistant-bot k8s
Secret and restarts the bot. Nothing is printed or written locally.
"""

import json
import subprocess
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

CONTEXT = "admin@alongames-remote"
NAMESPACE = "assistant"
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/tasks",
]

secret_file = sys.argv[1]
flow = InstalledAppFlow.from_client_secrets_file(secret_file, SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
if not creds.refresh_token:
    sys.exit("no refresh token returned — remove the app's access at "
             "https://myaccount.google.com/permissions and run again")
client = json.load(open(secret_file))["installed"]

patch = json.dumps({"stringData": {
    "GOOGLE_CLIENT_ID": client["client_id"],
    "GOOGLE_CLIENT_SECRET": client["client_secret"],
    "GOOGLE_REFRESH_TOKEN": creds.refresh_token,
}})
kubectl = ["kubectl", "--context", CONTEXT, "-n", NAMESPACE]
subprocess.run([*kubectl, "patch", "secret", "assistant-bot", "-p", patch], check=True)
subprocess.run([*kubectl, "rollout", "restart", "deploy/assistant-bot"], check=True)
subprocess.run([*kubectl, "rollout", "status", "deploy/assistant-bot",
                "--timeout=120s"], check=True)
print(f"\ndone — google skills are live. you can now delete {secret_file}")
