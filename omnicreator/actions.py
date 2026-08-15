"""Generates suggested reply text per comment category.

Uses Gemini when available (same lazy-init pattern as classifier.py), falling
back to simple templated replies personalized with username + CREATOR_NAME.
"""
import logging
import os

logger = logging.getLogger("omnicreator.actions")

_gemini_model = None
_gemini_init_attempted = False


def _get_gemini_model():
    global _gemini_model, _gemini_init_attempted
    if _gemini_init_attempted:
        return _gemini_model
    _gemini_init_attempted = True

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        _gemini_model = genai.GenerativeModel("gemini-1.5-flash")
    except Exception as exc:
        logger.warning("Gemini init failed for reply generation, using templates: %s", exc)
        _gemini_model = None
    return _gemini_model


REPLY_PROMPT_TEMPLATE = """You are {creator_name}, an Instagram content creator, replying to a comment on your post.
The comment is from @{username} and has been classified as {category}.
Comment: "{comment_text}"

Write a short (1-2 sentence), warm, authentic, in-character reply as {creator_name} would post it
as a public Instagram comment reply. {extra_instruction}
Respond with ONLY the reply text, no quotes, no markdown, no explanation.
"""

_EXTRA_INSTRUCTIONS = {
    "FAN_PRAISE": "Be genuinely appreciative and personable.",
    "RESOURCE_REQUEST": "Acknowledge the request warmly and let them know you'll follow up "
                         "with the resource (don't invent a link or promise specifics you don't have).",
    "BUSINESS_COLLABORATION": "Acknowledge their interest positively and say you'll follow up "
                               "via DM to discuss further — keep it professional but friendly.",
}


def _generate_with_gemini(username: str, comment_text: str, category: str, creator_name: str) -> str | None:
    model = _get_gemini_model()
    if model is None:
        return None
    try:
        prompt = REPLY_PROMPT_TEMPLATE.format(
            creator_name=creator_name,
            username=username,
            category=category,
            comment_text=comment_text.replace('"', "'"),
            extra_instruction=_EXTRA_INSTRUCTIONS.get(category, ""),
        )
        response = model.generate_content(prompt)
        text = response.text.strip().strip('"')
        if not text:
            raise ValueError("empty reply from Gemini")
        return text
    except Exception as exc:
        logger.warning("Gemini reply generation failed, falling back to template: %s", exc)
        return None


_TEMPLATES = {
    "FAN_PRAISE": "Thank you so much, @{username}! Comments like this genuinely make my day 💛 — {creator_name}",
    "RESOURCE_REQUEST": "Thanks for asking, @{username}! I'll follow up with that shortly 🙌 — {creator_name}",
    "BUSINESS_COLLABORATION": "Thanks so much for reaching out, @{username}! Really appreciate the interest — "
                               "I'll follow up via DM to chat further. — {creator_name}",
}


def _generate_template(username: str, category: str, creator_name: str) -> str:
    template = _TEMPLATES.get(category, _TEMPLATES["FAN_PRAISE"])
    return template.format(username=username, creator_name=creator_name)


def generate_reply(username: str, comment_text: str, category: str) -> str | None:
    """Returns suggested reply text, or None for SPAM (no reply generated)."""
    if category == "SPAM":
        return None

    creator_name = os.getenv("CREATOR_NAME", "the creator")
    reply = _generate_with_gemini(username, comment_text, category, creator_name)
    if reply is not None:
        return reply
    return _generate_template(username, category, creator_name)
