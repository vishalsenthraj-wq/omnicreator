"""Comment classification: Gemini-powered with a rule-based fallback.

Categories: FAN_PRAISE, BUSINESS_COLLABORATION, RESOURCE_REQUEST, SPAM.
Falls back automatically (no crash, no key required) whenever GEMINI_API_KEY
is unset or any Gemini call/parse fails.
"""
import json
import logging
import os
import re

logger = logging.getLogger("omnicreator.classifier")

CATEGORIES = {"FAN_PRAISE", "BUSINESS_COLLABORATION", "RESOURCE_REQUEST", "SPAM"}

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
        logger.warning("Gemini init failed, using rule-based classifier: %s", exc)
        _gemini_model = None
    return _gemini_model


PROMPT_TEMPLATE = """You are triaging Instagram comments for a content creator. Classify the comment into
EXACTLY ONE of these categories:

- FAN_PRAISE: positive/supportive comments, compliments, thanks, general engagement.
- BUSINESS_COLLABORATION: sponsorship offers, brand deals, partnership/collab proposals,
  paid promotion inquiries, "we'd love to work with you" type messages.
- RESOURCE_REQUEST: asking for a link, guide, PDF, template, free resource, "can you share...".
- SPAM: bot-like, irrelevant, scammy, engagement-farming, unrelated promotional junk.

Respond with STRICT JSON only, no markdown, no extra text, in this exact shape:
{{"category": "<one of the four categories>", "confidence": <float 0.0-1.0>, "summary": <string or null>}}

"summary" must be null UNLESS category is BUSINESS_COLLABORATION, in which case give a 1-2 sentence
summary of the opportunity (who, what, any brand/product mentioned).

Examples:
Comment: "omg this changed my life, thank you so much!!"
{{"category": "FAN_PRAISE", "confidence": 0.97, "summary": null}}

Comment: "Hi! We're a skincare brand and would love to send you products for a paid collab, check your DMs"
{{"category": "BUSINESS_COLLABORATION", "confidence": 0.95, "summary": "A skincare brand is offering a paid collaboration and wants to send products, requesting a DM follow-up."}}

Comment: "can you share the link to that planner template you used?"
{{"category": "RESOURCE_REQUEST", "confidence": 0.9, "summary": null}}

Comment: "Make $5000/week from home!! Click my bio NOW"
{{"category": "SPAM", "confidence": 0.98, "summary": null}}

Now classify this comment:
Comment: "{comment_text}"
"""


def _classify_with_gemini(comment_text: str) -> dict | None:
    model = _get_gemini_model()
    if model is None:
        return None
    try:
        prompt = PROMPT_TEMPLATE.format(comment_text=comment_text.replace('"', "'"))
        response = model.generate_content(prompt)
        raw = response.text.strip()
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
        data = json.loads(raw)

        category = data.get("category")
        if category not in CATEGORIES:
            raise ValueError(f"invalid category from Gemini: {category}")
        confidence = float(data.get("confidence", 0.7))
        confidence = max(0.0, min(1.0, confidence))
        summary = data.get("summary") if category == "BUSINESS_COLLABORATION" else None
        return {"category": category, "confidence": confidence, "summary": summary}
    except Exception as exc:
        logger.warning("Gemini classification failed, falling back to rules: %s", exc)
        return None


_COLLAB_KEYWORDS = [
    "sponsorship", "sponsor", "collab", "collaboration", "brand deal", "brand ambassador",
    "partnership", "partner with", "paid promotion", "work with you", "work together",
    "affiliate", "product placement", "influencer marketing",
]
_RESOURCE_KEYWORDS = [
    "send me", "send the link", "share the link", "link please", "pdf", "guide",
    "free resource", "template", "can you share", "where can i get", "drop the link",
]
_PRAISE_KEYWORDS = [
    "love this", "love it", "amazing", "helped me", "thank you", "thanks", "awesome",
    "inspiring", "so good", "great content", "life changing", "changed my life", "beautiful",
]
_SPAM_PATTERNS = [
    r"\$\d+[kK]?/?\s*(week|day|month)",
    r"click (my|the) (bio|link)",
    r"make money from home",
    r"dm me for",
    r"check my profile",
    r"free followers",
    r"crypto|forex|binary options",
]


def _classify_rule_based(comment_text: str) -> dict:
    text_lower = comment_text.lower()

    for pattern in _SPAM_PATTERNS:
        if re.search(pattern, text_lower):
            return {"category": "SPAM", "confidence": 0.6, "summary": None}

    for kw in _COLLAB_KEYWORDS:
        if kw in text_lower:
            return {
                "category": "BUSINESS_COLLABORATION",
                "confidence": 0.6,
                "summary": f"Comment mentions '{kw}' — possible collaboration/sponsorship opportunity, review manually.",
            }

    for kw in _RESOURCE_KEYWORDS:
        if kw in text_lower:
            return {"category": "RESOURCE_REQUEST", "confidence": 0.55, "summary": None}

    for kw in _PRAISE_KEYWORDS:
        if kw in text_lower:
            return {"category": "FAN_PRAISE", "confidence": 0.6, "summary": None}

    # Ambiguous defaults to FAN_PRAISE — never silently spam-filter something real.
    return {"category": "FAN_PRAISE", "confidence": 0.3, "summary": None}


def classify_comment(comment_text: str) -> dict:
    """Returns {"category", "confidence", "summary"}. Tries Gemini, falls back to rules."""
    result = _classify_with_gemini(comment_text)
    if result is not None:
        return result
    return _classify_rule_based(comment_text)
