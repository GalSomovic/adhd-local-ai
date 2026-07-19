# adhd-local-ai

A self-hosted, local-LLM personal assistant focused on executive function: it nags, escalates,
and refuses to be ignored. Runs entirely on the `alongames` homelab cluster (node `gals-beefy`,
i5-10th gen / 16GB, Talos) next to the media stack.

## Architecture

```
Element X (iPhone)                    Pushover (iPhone, critical alerts)
      │  E2E-ish chat, dedicated app        ▲  full volume, bypasses mute,
      │                                     │  repeats until acknowledged
      ▼                                     │
Tuwunel (Matrix homeserver, ~150Mi) ────────┤
      ▲                                     │
      │ matrix-nio                          │ REST + receipt polling
      ▼                                     │
assistant bot (Python, ~128Mi) ─────────────┘
      │  deterministic engine: scheduler, check-ins, escalation state machine
      │  skills registry: each capability is a self-contained module
      ▼
Ollama / Qwen3-4B-Instruct (CPU, ≤6Gi, unloads when idle)
      LLM = parser + voice only. Never the engine.
```

Design rule that makes this trustworthy with medication reminders: **every
reliability-critical behavior (timers, escalation, receipts) is plain Python.**
The 4B model only parses requests into structured tasks and phrases replies
(Hebrew/English). If the model is down or dumb, the alarms still fire.

## Escalation flow (the heart)

1. Check-in fires (e.g. daily 08:00 "לקחת תרופה?") → message in Matrix.
2. No reply within the configured window → **Pushover emergency alert**:
   full volume, ignores mute/Focus, re-alerts every 30s until acknowledged.
3. Bot polls the Pushover receipt — it *knows* whether you acknowledged.
   Answering in Matrix cancels a live alarm.
4. Acknowledged → follow-up question in chat. Expired unacknowledged → one
   re-alarm, then marked missed.
5. (Google layer) before escalating, check free/busy on both calendars —
   hold the siren while you're in a meeting, re-check when it ends.

## Roadmap

| Layer | What | Status |
|---|---|---|
| Core loop | Tuwunel + Element X, Ollama + Qwen3-4B, bot, check-ins + Pushover escalation | **this repo, phase 1** |
| Google layer | Gmail read **+ send (always confirm-before-send)**, Google Calendar, Google Tasks, meeting-aware alarms, morning brief, appointment harvesting from email | next |
| Motion layer | Israel Rail next-train + delay alerts (Hof HaCarmel↔TLV), free-slot finder with travel time (Distance Matrix), iOS Shortcuts geofence ("left home" webhook) | after |
| Deep layer | Outlook work calendar (Graph API if Nexxen IT allows; ICS publish fallback), WhatsApp read via mautrix-whatsapp bridge | opt-in |
| Parked | Bank Leumi / Max digests, Maccabi | explicitly out for now |

### Backlog / proactive ideas
- Morning brief: merged calendars + next train + weather + emails that matter + today's check-ins.
- Geofence-aware "did you leave" (Shortcuts automation POSTs location events; alarm only if you *haven't* left by leave-by time).
- "Catch the 17:49" — evening train suggestion based on last meeting's end.
- Prescription/errand recurrence learned from confirmations (~every 25 days: "לקנות תרופות").
- Weekly review (Sunday): done / ignored / upcoming.
- Quiet-hours & Shabbat awareness for non-critical nagging.
- Voice notes: Element X voice message → local Hebrew STT (ivrit.ai whisper models, CPU).
- Package tracking from delivery emails.
- Shopping-list skill ("תוסיף חלב").
- Meta-loop: a `suggest_feature` skill drafts a Claude Code prompt for the next module.

## Repo layout

```
deploy/           kustomize manifests (namespace `assistant`)
  tuwunel/        Matrix homeserver (server name matrix.galsgames.dpdns.org)
  ollama/         LLM runtime, hard resource caps
  bot/            the assistant (image ghcr.io/galsomovic/adhd-local-ai-bot)
  cloudflared/    dedicated "assistant-tunnel" — the media tunnel is untouched
bot/              Python source + Dockerfile
scripts/          register-user.sh (Matrix UIA registration)
.github/          CI: pushes the bot image to ghcr.io on every bot/ change
```

CI: pushing to `main` with changes under `bot/` builds and pushes
`ghcr.io/galsomovic/adhd-local-ai-bot:latest` (+ `:<sha>`) via GitHub Actions —
no local docker builds needed. The GHCR package must be **public** (or the
cluster needs a pull secret); check package settings after the first push.

## Setup

### On the phone (one-time)
1. Buy **Pushover** ($5 one-time), open it, enable **critical alerts** when prompted
   (Settings → Notifications inside the app if you missed it). Note your **user key**;
   create an **application** on pushover.net → note its **API token**.
2. Install **Element X**.

### Expose the homeserver
The assistant has its own Cloudflare tunnel (`assistant-tunnel`, remotely
managed), so the media tunnel stays untouched. One-time creation via CF API
(token in `~/.cfcli.yml`, account `b2a61b...`, zone `galsgames.dpdns.org`):
tunnel create → DNS CNAME `matrix` → `<tunnel-id>.cfargotunnel.com` (proxied)
→ tunnel ingress `matrix.galsgames.dpdns.org` →
`http://tuwunel.assistant.svc.cluster.local:8008` + `http_status:404` catch-all.
The tunnel token lives in the `assistant-tunnel` Secret.

### Deploy
Secrets first (never in git), then the manifests:
```bash
CTX=admin@alongames-remote
kubectl --context $CTX create ns assistant
kubectl --context $CTX -n assistant create secret generic tuwunel \
  --from-literal=REGISTRATION_TOKEN='<random>'
kubectl --context $CTX -n assistant create secret generic assistant-tunnel \
  --from-literal=TUNNEL_TOKEN='<from CF API>'
kubectl --context $CTX -n assistant create secret generic assistant-bot \
  --from-literal=MATRIX_PASSWORD='<bot password>' \
  --from-literal=PUSHOVER_TOKEN='<app token>' \
  --from-literal=PUSHOVER_USER='<user key>'
kubectl --context $CTX apply -k deploy/
```

Pull the model (~2.5GB, one-time; survives restarts on hostPath):
```bash
kubectl --context admin@alongames-remote -n assistant exec deploy/ollama -- \
  ollama pull qwen3:4b-instruct-2507-q4_K_M
```

### Create the two Matrix users
Registration is token-gated. Register your user and the bot user, then set
`TUWUNEL_ALLOW_REGISTRATION` to `false` and re-apply:
```bash
./scripts/register-user.sh https://matrix.galsgames.dpdns.org gal '<your password>' '<the-token>'
./scripts/register-user.sh https://matrix.galsgames.dpdns.org bot '<bot password>' '<the-token>'
```
Log in to Element X as `@gal:matrix.galsgames.dpdns.org`
(server address: `matrix.galsgames.dpdns.org`).

### First contact
The bot creates a private room and invites you on first start. Accept the invite, then:
- `תזכיר לי לקחת תרופה כל בוקר ב-8:00, ואם אני לא עונה תוך 20 דקות — אזעקה`
- Test the siren end-to-end: `!testalarm` (ignore the chat message and let it escalate).

## Google layer setup (one-time)

1. In [Google Cloud Console](https://console.cloud.google.com): create a project →
   **APIs & Services → Library** → enable **Gmail API**, **Google Calendar API**,
   **Google Tasks API**.
2. **APIs & Services → OAuth consent screen**: External, fill the two required
   fields, add your Gmail as a test user — then set **Publishing status: In
   production** (otherwise the refresh token dies every 7 days; the "unverified
   app" warning during login is fine, it's your own app).
3. **Credentials → Create credentials → OAuth client ID → Desktop app** →
   download the JSON as `client_secret.json`.
4. On the Mac (uv manages the dependency, nothing installed globally):
   ```bash
   uv run scripts/google-auth.py ~/Downloads/client_secret.json
   ```
   A browser opens; log in with the Gmail account, click through the
   unverified-app warning, approve the scopes. The script then patches the
   `assistant-bot` Secret on the cluster and restarts the bot itself —
   no secrets printed or copy-pasted. Delete `client_secret.json` after.

What it unlocks: Gmail search/read + staged send (`!send` / `!discard`),
Calendar list/create, Google Tasks (every fired שעון מעורר mirrors into an
"ADHD Assistant" list and completes when answered), the `!brief` morning brief
(also auto-sent daily at `BRIEF_TIME`, default 07:00), and meeting-aware
escalation (check-in alarms hold while the calendar says you're busy;
explicit שעון מעורר alarms ring regardless).

## Security notes
- Nothing leaves the cluster except: Pushover API calls, Apple/Matrix push wake-ups,
  and (later) Google/Graph API calls. Chat content lives on your node.
- Federation is disabled; registration is token-gated then disabled outright.
- All credentials are k8s Secrets; the bot room is invite-only between the two local users.
- Gmail send is gated: the bot always shows the draft in chat and sends only after explicit ✅.
