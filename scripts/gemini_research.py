"""Per-batch ticker research via Gemini, grounded with Google Search.

Runs once per batch of ~5 tickers (cheap Flash-tier model, several of these
run concurrently per morning — see generate_brief.py).
"""
import json
from typing import Optional

from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential

RESEARCH_MODEL = "gemini-3.5-flash"
MOVE_THRESHOLD_PCT = 5.0


class BriefItem(BaseModel):
    tk: str
    co: str
    flag: str  # HIGH | MEDIUM | QUIET
    headline: str = ""
    impact: str = ""
    move_pct: Optional[float] = None
    url: str = ""
    published_at: str = ""


class BatchResult(BaseModel):
    items: list[BriefItem]


# Hand-written flat schema (no $defs/$ref) for the structured-output request —
# more broadly compatible than Pydantic's auto-generated nested schema.
# BriefItem/BatchResult above are still used to validate/parse the response.
_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "tk": {"type": "string"},
        "co": {"type": "string"},
        "flag": {"type": "string", "enum": ["HIGH", "MEDIUM", "QUIET"]},
        "headline": {"type": "string"},
        "impact": {"type": "string"},
        "move_pct": {"type": "number", "nullable": True},
        "url": {"type": "string"},
        "published_at": {"type": "string"},
    },
    "required": ["tk", "co", "flag"],
}

BATCH_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {"type": "array", "items": _ITEM_SCHEMA},
    },
    "required": ["items"],
}


def _build_prompt(batch, window_start_iso, window_end_iso, today_iso, exclude_by_ticker):
    lines = [
        "You are researching overnight stock news for a personal watchlist brief.",
        "",
        f"Today's date: {today_iso}",
        f"Research window: news dated between {window_start_iso} and {window_end_iso} (UTC). "
        "An item dated just outside this window may still be kept if it is clearly new and "
        "material (e.g. a regulatory decision, M&A, a major guidance change) rather than routine "
        "commentary — otherwise, stick to the window.",
        "",
        f"Move threshold: only flag HIGH or MEDIUM if the price reaction is at least "
        f"{MOVE_THRESHOLD_PCT}%. Smaller moves without a clearly material driver are QUIET.",
        "",
        "Hard rules:",
        "- Never fabricate a story, date, or URL — only report items with a real, dated source "
        "you actually found.",
        "- QUIET is a normal, expected outcome for most tickers on most days. Do not manufacture "
        "content to avoid returning QUIET.",
        "- Do not re-report a story already listed below as covered yesterday for that ticker.",
        "",
        "Tickers to research in this batch:",
    ]
    for t in batch:
        lines.append(f"- {t['tk']} ({t['co']}, {t['ex']})")
        excl = exclude_by_ticker.get(t["tk"], [])
        if excl:
            lines.append(f"  Already covered yesterday, do not repeat: {excl}")
    lines.append("")
    lines.append(
        "Return exactly one item per ticker listed above (QUIET items included), matching the "
        "required JSON schema."
    )
    return "\n".join(lines)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=30))
async def research_batch(client, batch, window_start_iso, window_end_iso, today_iso, exclude_by_ticker):
    prompt = _build_prompt(batch, window_start_iso, window_end_iso, today_iso, exclude_by_ticker)

    interaction = await client.aio.interactions.create(
        model=RESEARCH_MODEL,
        input=prompt,
        tools=[{"type": "google_search"}],
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": BATCH_RESULT_SCHEMA,
        },
    )

    data = json.loads(interaction.output_text)
    return BatchResult.model_validate(data).items
