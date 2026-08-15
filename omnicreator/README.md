# OmniCreator AI — Comment Triage (Module 3, Instagram Comments)

Built for the Social Media Automation Hackathon. Reads Instagram comments on your posts,
classifies each one (fan praise / business collaboration / resource request / spam), drafts
a reply, and **never posts anything without your explicit one-click approval**. The moment a
comment looks like a real sponsorship/collab lead, you get an instant phone push notification —
before you've even reviewed the reply.

## What it does

- Polls your real Instagram Business Account for new comments (every 45s, or on-demand via "Poll Now")
- Classifies each new comment with Gemini (or a rule-based fallback if no API key is set)
- Drafts a suggested reply for everything except spam
- Shows every comment in a live dashboard, `PENDING_APPROVAL` until you approve or reject it
- **Approve** → posts the (optionally edited) reply for real via the Instagram Graph API
- **Reject** → dismisses the suggestion, nothing is posted
- `BUSINESS_COLLABORATION` comments trigger an immediate ntfy.sh push notification the moment
  they're detected, independent of approval status
- Spam is logged and shown de-emphasized in the feed, with no generated reply

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # then fill in the values you have
python main.py
```

The app runs at `http://localhost:8000`.

**The app works with zero configured env vars.** With nothing set, it starts cleanly, the
dashboard loads with all-zero stats, and classification/replies use a built-in rule-based
fallback so you can see the UI immediately. Clicking "Poll Now" without Instagram credentials
returns a clear "Instagram not configured" message instead of crashing.

### Environment variables (`.env`)

| Variable | Required? | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | No | Enables Gemini-powered classification + reply drafting. Without it, a rule-based keyword classifier and templated replies are used instead — same app, same flow, no code changes needed once you add a key. |
| `NTFY_TOPIC` | No | ntfy.sh topic for VIP push notifications. Without it, VIP alerts are logged only, never sent. Pick a unique/hard-to-guess topic name and subscribe to it in the [ntfy app](https://ntfy.sh/app) or via `https://ntfy.sh/<topic>` in a browser. |
| `IG_ACCESS_TOKEN` | For real polling/posting | Long-lived access token from the Meta "API setup with Instagram login" flow, with `instagram_business_basic` and `instagram_business_manage_comments` permissions. |
| `IG_BUSINESS_ACCOUNT_ID` | For real polling/posting | Your Instagram Business Account ID. |
| `CREATOR_NAME` | No (defaults to "the creator") | Used to personalize generated replies. |

## How to demo

1. Start the app (`python main.py`) with your `.env` filled in.
2. Open `http://localhost:8000` — dashboard loads, stats at zero.
3. Click **Poll Now** — this immediately fetches your recent posts' comments from real
   Instagram, classifies them, generates suggested replies, and updates the feed and stat tiles.
4. Point out the **VIP Leads panel** — any `BUSINESS_COLLABORATION` comment shows up there with
   an AI-generated summary of the opportunity, and (if `NTFY_TOPIC` is set) triggers a real
   phone push notification the instant it's classified — before anyone approves anything.
5. Edit a suggested reply's text if you like, then click **Approve** — this posts the reply for
   real to the actual comment on Instagram. Verify by opening the post on Instagram directly.
6. Click **Reject** on another comment to show the dismiss path — nothing gets posted.
7. Point out the de-emphasized spam entries — no reply, no approval prompt, just logged.

## Instagram Graph API notes

- Uses the newer **API setup with Instagram login** flow (not the classic Facebook Page +
  Graph API Explorer flow), calling `graph.instagram.com` at API version `v21.0`.
- Comment ingestion is **polling-based, not webhook-based** — no public HTTPS callback URL
  (ngrok, deployment) is needed, which keeps local hackathon setup simple.
- If a call to `graph.instagram.com` fails with what looks like a permissions/host mismatch
  error (404/400/403), the client automatically retries the same call against
  `graph.facebook.com` with the same access token, since Meta has historically supported
  Instagram Business accounts through both hosts depending on API version/setup path.
  **Document here which host actually worked for you during testing** — update this section
  once you've run a real poll cycle.
- All Graph API errors (expired token, rate limits, permission errors) are caught and logged
  with a clear message; the app never crashes on an Instagram API failure. `Poll Now` in the
  UI will surface the exact error message returned by the API.

## Project structure

```
omnicreator/
  main.py               # FastAPI app, routes, startup, background polling loop
  instagram_client.py   # Graph API calls: fetch media, fetch comments, post reply
  classifier.py         # Gemini classification + rule-based fallback
  actions.py             # generates suggested reply text per category
  notifier.py             # ntfy.sh dispatcher
  db.py                     # SQLite setup + CRUD helpers
  static/
    index.html               # the whole dashboard
  requirements.txt
  .env.example
  .gitignore
```

## Known assumptions / hackathon-pragmatic choices

- No auth/login — single-user demo app, as specified.
- Poll interval is 45 seconds; "Poll Now" bypasses this for live demos.
- Ambiguous comments default to `FAN_PRAISE` rather than being silently spam-filtered, since
  missing a real opportunity is worse than an occasional over-friendly reply suggestion.
- The reply textarea in the UI lets you edit suggested replies before approving (nice-to-have
  from the spec, implemented).
