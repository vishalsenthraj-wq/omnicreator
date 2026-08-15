"""OmniCreator AI — Instagram comment triage with human-approved auto-reply.

FastAPI app: routes, startup, and the background polling loop.
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

import actions
import classifier
import db
import instagram_client
import notifier

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("omnicreator.main")

POLL_INTERVAL_SECONDS = 45
SPAM_STATUS = "SPAM_LOGGED"
PENDING_APPROVAL_STATUS = "PENDING_APPROVAL"

_poll_lock = asyncio.Lock()


def run_poll_cycle() -> dict:
    """Fetch recent media -> comments -> insert+classify new ones. Returns a summary dict."""
    new_count = 0
    errors: list[str] = []

    try:
        media_list = instagram_client.fetch_recent_media()
    except instagram_client.InstagramConfigError as exc:
        return {"ok": False, "error": str(exc), "new_comments": 0}
    except instagram_client.InstagramAPIError as exc:
        logger.error("Failed to fetch recent media: %s", exc)
        return {"ok": False, "error": str(exc), "new_comments": 0}

    with db.get_conn() as conn:
        for media in media_list:
            media_id = media.get("id")
            if not media_id:
                continue
            try:
                comments = instagram_client.fetch_comments(media_id)
            except instagram_client.InstagramAPIError as exc:
                logger.error("Failed to fetch comments for media %s: %s", media_id, exc)
                errors.append(str(exc))
                continue

            for c in comments:
                ig_comment_id = c.get("id")
                if not ig_comment_id or db.comment_exists(conn, ig_comment_id):
                    continue

                username = c.get("username", "unknown")
                text = c.get("text", "")
                comment_row_id = db.insert_comment(conn, ig_comment_id, media_id, username, text)
                new_count += 1

                _classify_and_store(conn, comment_row_id, username, text)

    return {"ok": True, "new_comments": new_count, "errors": errors}


def _classify_and_store(conn, comment_row_id: int, username: str, text: str):
    """Classify a newly inserted comment, generate a reply, store results, fire VIP alert."""
    try:
        result = classifier.classify_comment(text)
    except Exception as exc:
        logger.error("Classification crashed unexpectedly for comment %s: %s", comment_row_id, exc)
        result = {"category": "FAN_PRAISE", "confidence": 0.0, "summary": None}

    category = result["category"]
    confidence = result["confidence"]
    summary = result.get("summary")
    is_vip = category == "BUSINESS_COLLABORATION"

    if category == "SPAM":
        suggested_reply = None
        status = SPAM_STATUS
    else:
        try:
            suggested_reply = actions.generate_reply(username, text, category)
        except Exception as exc:
            logger.error("Reply generation crashed unexpectedly for comment %s: %s", comment_row_id, exc)
            suggested_reply = None
        status = PENDING_APPROVAL_STATUS

    db.update_classification(
        conn, comment_row_id, category, confidence, summary, suggested_reply, status, is_vip
    )

    if is_vip:
        try:
            notifier.send_vip_notification(username, summary)
        except Exception as exc:
            logger.error("VIP notification crashed unexpectedly for comment %s: %s", comment_row_id, exc)


async def _polling_loop():
    while True:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        try:
            async with _poll_lock:
                result = await asyncio.to_thread(run_poll_cycle)
            if not result["ok"]:
                logger.info("Scheduled poll skipped: %s", result["error"])
            elif result["new_comments"]:
                logger.info("Scheduled poll: %d new comment(s) processed", result["new_comments"])
        except Exception as exc:
            logger.error("Background polling loop error: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    task = asyncio.create_task(_polling_loop())
    logger.info("OmniCreator AI started. Polling every %ds.", POLL_INTERVAL_SECONDS)
    yield
    task.cancel()


app = FastAPI(title="OmniCreator AI — Comment Triage", lifespan=lifespan)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _row_to_dict(row) -> dict:
    return dict(row)


@app.get("/")
async def dashboard():
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/poll-now")
async def poll_now():
    async with _poll_lock:
        result = await asyncio.to_thread(run_poll_cycle)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.get("/api/comments")
async def list_comments():
    with db.get_conn() as conn:
        rows = db.list_comments(conn)
    return [_row_to_dict(r) for r in rows]


@app.get("/api/leads")
async def list_leads():
    with db.get_conn() as conn:
        rows = db.list_leads(conn)
    return [_row_to_dict(r) for r in rows]


@app.get("/api/stats")
async def stats():
    with db.get_conn() as conn:
        return db.get_stats(conn)


class ApproveBody(BaseModel):
    reply_text: str | None = None


@app.post("/api/comments/{comment_id}/approve")
async def approve_comment(comment_id: int, body: ApproveBody | None = None):
    with db.get_conn() as conn:
        comment = db.get_comment(conn, comment_id)
        if comment is None:
            raise HTTPException(status_code=404, detail="Comment not found")
        if comment["status"] != PENDING_APPROVAL_STATUS:
            raise HTTPException(
                status_code=400, detail=f"Comment is not pending approval (status={comment['status']})"
            )

        final_reply = (body.reply_text if body and body.reply_text else comment["suggested_reply"])
        if not final_reply:
            raise HTTPException(status_code=400, detail="No reply text available to post")

        try:
            instagram_client.post_reply(comment["ig_comment_id"], final_reply)
        except instagram_client.InstagramConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except instagram_client.InstagramAPIError as exc:
            raise HTTPException(status_code=502, detail=f"Failed to post reply to Instagram: {exc}")

        db.mark_posted(conn, comment_id, final_reply)
        updated = db.get_comment(conn, comment_id)
        return _row_to_dict(updated)


@app.post("/api/comments/{comment_id}/reject")
async def reject_comment(comment_id: int):
    with db.get_conn() as conn:
        comment = db.get_comment(conn, comment_id)
        if comment is None:
            raise HTTPException(status_code=404, detail="Comment not found")
        db.mark_rejected(conn, comment_id)
        updated = db.get_comment(conn, comment_id)
        return _row_to_dict(updated)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
