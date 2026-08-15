# Build Prompt for Claude Code — OmniCreator AI (Hackathon Project, Module 3 Comment Triage Only)

> **How to use this file:** Paste this entire document as your first message to Claude Code in your VS Code terminal, inside an empty project folder. It contains full context, all decisions made so far, and the exact feature list to build. Build the whole thing autonomously from this — don't wait for further clarification unless something here is genuinely ambiguous.

---

## 1. Context — what this is and why

I'm building **OmniCreator AI** for the "Social Media Automation Hackathon" on Devpost. Deadline is Aug 17, 2026 @ 4:30am GMT+5:30 — very little time left, so scope is intentionally narrow. Judging: Functionality 30%, Real-world usefulness 30%, Creativity 20%, Technical execution 20%.

**The problem this solves:** creators lose hours replying to comments manually, and real business opportunities (brand deals/sponsorships) get buried under generic comments and spam. OmniCreator AI reads incoming Instagram comments, classifies what kind of comment each one is, drafts a reply, and — critically — never posts anything without the creator's explicit one-click approval. The moment a comment looks like a real sponsorship/collab opportunity, the creator gets an instant phone push notification so it's never missed, even before they've approved a reply.

**Full product vision (context only — NOT being built right now):** Module 1 (content repurposing — image+text in, 4 platform-tailored captions out, one-click publish), Module 2 (broadcast engine across Telegram/WhatsApp/Instagram), and the DM-triage half of Module 3. **None of these are in scope for this build.** Only build what Section 4 below describes.

---

## 2. Scope for THIS build — read carefully

**Build ONLY: Instagram comment triage with human-approved auto-reply.**

Explicitly OUT of scope right now (do not build):
- Instagram DM/message triage (only comments, not direct messages)
- Content repurposing (Module 1)
- Broadcast engine (Module 2)
- YouTube, LinkedIn, X/Twitter, Telegram, WhatsApp integrations
- Auto-publishing new posts/images

**In scope:**
- Pull real comments from my real Instagram account's posts (I already have API access set up — see Section 3)
- Classify each comment via Gemini into: `FAN_PRAISE`, `BUSINESS_COLLABORATION`, `RESOURCE_REQUEST`, `SPAM`
- Generate a suggested reply for each comment (except SPAM)
- Show every comment + suggested reply in a dashboard, PENDING until I approve it
- One-click "Approve" button per comment → posts that reply for real to the actual Instagram comment, using the real Graph API
- `BUSINESS_COLLABORATION` comments additionally trigger an immediate phone push notification (via ntfy.sh) the moment they're detected — independent of whether I've approved a reply yet
- `SPAM` comments are logged but get no generated reply and no approval prompt — just shown de-emphasized in the feed

---

## 3. Real Instagram API access — already set up, use it for real

I already have a working Meta Developer app with Instagram Graph API access, set up via the newer "API setup with Instagram login" flow (not the older Facebook Page + Graph API Explorer flow). I have:
- A real Instagram Business Account ID
- A real, valid long-lived access token
- Permissions granted: `instagram_business_basic`, `instagram_business_manage_comments`, `instagram_business_manage_messages`

I will provide these as environment variables:
- `IG_ACCESS_TOKEN`
- `IG_BUSINESS_ACCOUNT_ID`

**Do not build a simulated/mocked ingestion layer for this module.** Use the real Instagram Graph API for both reading comments and posting replies. Specifically:
- To fetch my recent media (posts): `GET https://graph.instagram.com/v21.0/{IG_BUSINESS_ACCOUNT_ID}/media?fields=id,caption,timestamp&access_token={token}`
- To fetch comments on a given media: `GET https://graph.instagram.com/v21.0/{media-id}/comments?fields=id,text,username,timestamp&access_token={token}`
- To post a reply to a specific comment: `POST https://graph.instagram.com/v21.0/{comment-id}/replies` with `message` and `access_token` params

**Comment ingestion should use polling, not webhooks.** Webhooks require a public HTTPS callback URL (via ngrok or deployment), which adds unnecessary complexity for a local hackathon build. Instead, run a background polling loop (every 30–60 seconds is fine) that: fetches my recent media, fetches comments on each, and diffs against what's already in the local database to find new comments only. Process only new ones through the classification pipeline (don't reprocess already-seen comments).

**Verify the actual current Graph API version and endpoint paths before hardcoding them** — Meta updates API versions periodically (currently on v21.x-ish as of writing, but confirm via their developer docs) — and confirm the exact JSON response shape for comments and the reply-posting endpoint against Meta's current Instagram Platform documentation before writing the integration code, since endpoint field names/response shapes can differ slightly by API version. Handle API errors gracefully (expired token, rate limits, permission errors) with clear logged messages rather than silent failures or crashes.

If, when actually testing this, calls to `graph.instagram.com` fail with a permissions or endpoint-not-found error, also try the equivalent Facebook Graph API host (`graph.facebook.com`) with the same access token, since Meta has historically supported Instagram Business accounts through both hosts depending on API version/setup path — pick whichever one actually works during testing and document it in the README.

---

## 4. Tech stack (decided — do not change without asking)

- **Backend:** Python, FastAPI, single app (`main.py` + a few modules). Run via `uvicorn`.
- **Frontend:** ONE single-page dashboard, plain HTML/CSS/JS, Tailwind CSS via CDN (`<script src="https://cdn.tailwindcss.com">`). Served as a static file by FastAPI. No Node.js, no npm, no build step.
- **Database:** SQLite, single file, created automatically on first run.
- **LLM:** Google Gemini API via `google-generativeai` Python SDK. Read `GEMINI_API_KEY` from `.env` (via `python-dotenv`). **App must run even with no Gemini key set** — fall back to a rule-based/keyword classifier (see Section 5) so it's demoable immediately; upgrades automatically once a key is added, no code changes needed.
- **Phone notifications:** ntfy.sh — plain HTTP POST to `https://ntfy.sh/<topic>` via `requests`. Read `NTFY_TOPIC` from env; skip (log only) if unset, never error out.
- **Instagram:** `requests` library calling the Graph API directly (no need for a heavy SDK) using `IG_ACCESS_TOKEN` and `IG_BUSINESS_ACCOUNT_ID` from `.env`.
- **Background polling:** use FastAPI's startup event + a simple `asyncio` background task loop, or APScheduler if that's cleaner — your call, keep it simple.
- **Config:** `.env` (gitignored) + `.env.example` committed, showing: `GEMINI_API_KEY`, `NTFY_TOPIC`, `IG_ACCESS_TOKEN`, `IG_BUSINESS_ACCOUNT_ID`, `CREATOR_NAME` (used to personalize generated replies).

---

## 5. Feature detail

### 5.1 Comment ingestion (real, polling-based)
Background loop, every 30–60s: fetch recent media → fetch comments per media → filter to comments not already in the DB (by Instagram comment ID) → insert new ones with status `PENDING_CLASSIFICATION` → immediately classify each new one (see 5.2) → move to `PENDING_APPROVAL` (or `SPAM_LOGGED` if classified as spam).

Also provide `POST /api/poll-now` as a manual trigger — useful for demoing live without waiting for the next scheduled poll cycle.

### 5.2 Classification (Gemini + rule-based fallback)
Categories: `FAN_PRAISE`, `BUSINESS_COLLABORATION`, `RESOURCE_REQUEST`, `SPAM`. Gemini prompt: clear category definitions + few-shot examples, strict JSON response `{"category": "...", "confidence": 0.0-1.0, "summary": "..." or null}` (summary only for BUSINESS_COLLABORATION — a 1-2 sentence description of the opportunity). Parse defensively; fall back to rule-based keyword classifier on any Gemini error or missing key. Rule-based fallback: sponsorship/collab/brand-deal/partnership keywords → BUSINESS_COLLABORATION; "send/link/pdf/guide/free resource" → RESOURCE_REQUEST; praise words (love/amazing/helped me/thank you) → FAN_PRAISE; obvious spam patterns → SPAM; ambiguous defaults to FAN_PRAISE (never silently spam-filter something real).

### 5.3 Reply generation
For FAN_PRAISE and RESOURCE_REQUEST: Gemini-generated (or templated fallback) warm/appropriate reply text, personalized with the commenter's username and `CREATOR_NAME`. For BUSINESS_COLLABORATION: also generate a reply (something like acknowledging interest and saying you'll follow up), plus the separate AI summary of the opportunity for the VIP panel. For SPAM: no reply generated.

### 5.4 Approval + real posting
Every non-spam comment sits with status `PENDING_APPROVAL` and its generated reply text visible (editable in the UI before approving, if easy to add — nice-to-have, not required). `POST /api/comments/{id}/approve` — takes the (possibly edited) reply text, posts it for real via the Instagram Graph API reply endpoint, updates status to `POSTED`, stores the timestamp. If the API call fails, surface the error clearly in the UI and keep status as `PENDING_APPROVAL` (don't silently mark it posted). Also support `POST /api/comments/{id}/reject` to dismiss a suggestion without posting (status → `REJECTED`).

### 5.5 VIP escalation
The moment a comment is classified `BUSINESS_COLLABORATION`, immediately (before any approval step) trigger an ntfy push notification: `🚨 New Collab Lead Detected! <username>: <summary>`. This happens once per comment, at classification time, not at approval time — the whole point is the creator gets alerted to the opportunity right away even if they're slow to review/approve the reply.

### 5.6 Storage
`comments` table: `id` (internal), `ig_comment_id`, `ig_media_id`, `username`, `text`, `category`, `confidence`, `summary` (nullable), `suggested_reply` (nullable), `status` (`PENDING_APPROVAL` | `POSTED` | `REJECTED` | `SPAM_LOGGED`), `is_vip` (bool), `created_at`, `posted_at` (nullable).

### 5.7 Dashboard (single HTML page, Tailwind CDN)
- Stat tiles: total comments processed, pending approvals, VIP leads count, replies posted, spam filtered
- "Poll Now" button (manual trigger for demoing)
- Live comment feed: newest first, showing username, comment text, category badge (color-coded), confidence, suggested reply (editable text area), and Approve / Reject buttons for anything `PENDING_APPROVAL`
- Dedicated VIP Leads panel: `BUSINESS_COLLABORATION` comments with their AI summaries, visually prominent
- Auto-refresh via simple polling (every few seconds), no websockets needed

### 5.8 API endpoints
- `GET /` — dashboard HTML
- `POST /api/poll-now` — manually trigger a comment-fetch cycle immediately
- `GET /api/comments` — list all comments, newest first
- `GET /api/leads` — list only `BUSINESS_COLLABORATION` comments
- `GET /api/stats` — counts for stat tiles
- `POST /api/comments/{id}/approve` — post the reply for real, body optionally includes edited reply text
- `POST /api/comments/{id}/reject` — dismiss without posting

---

## 6. Project structure

```
omnicreator/
  main.py                  # FastAPI app, routes, startup, background polling loop
  instagram_client.py       # Graph API calls: fetch media, fetch comments, post reply
  classifier.py              # Gemini classification + rule-based fallback
  actions.py                  # generates suggested reply text per category
  notifier.py                  # ntfy.sh dispatcher
  db.py                         # SQLite setup + CRUD helpers
  static/
    index.html                  # the whole dashboard
  requirements.txt
  .env.example
  .gitignore                     # .env, __pycache__, *.db
  README.md
```

---

## 7. Explicit working instructions

1. Build end-to-end without pausing for approval on each file — I want to review a working app.
2. The app must run with **zero required env vars** (rule-based classifier fallback), so I can verify it's alive before plugging in real credentials.
3. Once I provide `IG_ACCESS_TOKEN` and `IG_BUSINESS_ACCOUNT_ID` in `.env`, the real Instagram polling/posting path must work — test this yourself against the real API if I've provided real credentials, and tell me clearly what happened (success, or the exact error) rather than assuming it works.
4. Write a clear `README.md`: what it does, setup (`pip install -r requirements.txt`, configure `.env`), how to run, and a "how to demo" section (use Poll Now + Approve buttons to show the live flow to judges).
5. Init a git repo if none exists; ensure `.env` and `.db` files are gitignored before first commit.
6. No authentication/login — single-user demo app.
7. No Node.js/npm/frontend build tooling.
8. If something here is genuinely ambiguous, make the most reasonable hackathon-pragmatic choice, note the assumption, and keep going — don't block on asking me.

---

## 8. Definition of done

- `pip install -r requirements.txt && python main.py` starts cleanly with no env vars set; dashboard loads with all-zero stats.
- With a Gemini key set but no Instagram credentials, "Poll Now" fails gracefully with a clear error (no Instagram creds configured) rather than crashing.
- With real `IG_ACCESS_TOKEN` + `IG_BUSINESS_ACCOUNT_ID` set, "Poll Now" actually fetches real comments from my real Instagram posts and they appear in the feed with a category, confidence, and suggested reply.
- Clicking "Approve" on a real comment actually posts the reply back to that comment on real Instagram (verify by checking the comment on Instagram directly after approving).
- A `BUSINESS_COLLABORATION`-classified comment triggers a real ntfy push notification (if `NTFY_TOPIC` is set) immediately at classification time.
- README lets me run this from a fresh clone.

Build it now.
