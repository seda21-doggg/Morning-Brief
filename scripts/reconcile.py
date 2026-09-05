"""Single reconciliation pass over all batch research results.

Runs once per morning regardless of ticker count, on a stronger model —
this is where the judgment calls happen (dedup vs. yesterday, dropping
stale analyst-reiteration filler, deciding whether an item just outside the
research window is material enough to keep anyway).
"""
import json

from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential

from gemini_research import BriefItem, MOVE_THRESHOLD_PCT, _ITEM_SCHEMA

# gemini-2.5-pro returned 404 "no longer available to new users" on this
# account as of 2026-09 — Google's own error pointed at this replacement.
# It's a preview model, so re-check availability if it ever 404s again.
RECONCILE_MODEL = "gemini-3.1-pro-preview"


class DailyBrief(BaseModel):
    date: str
    items: list[BriefItem]


# Hand-written flat schema (no $defs/$ref) — see gemini_research.py for why.
DAILY_BRIEF_SCHEMA = {
    "type": "object",
    "properties": {
        "date": {"type": "string"},
        "items": {"type": "array", "items": _ITEM_SCHEMA},
    },
    "required": ["date", "items"],
}


def _build_prompt(date_iso, all_items, yesterday_items):
    return "\n".join([
        "You are reconciling several batches of stock news research into one final daily brief.",
        "",
        f"Date: {date_iso}",
        "",
        "Reconciliation rules:",
        "- Drop any item that duplicates something already reported yesterday (see below).",
        "- Drop stale analyst-reiteration filler dressed up with a fresh publish timestamp — keep "
        "only genuinely new information.",
        "- Keep an item dated just outside the research window if it is clearly new and material "
        "(e.g. regulatory action, M&A, a major guidance change), even though a mechanical date "
        "filter would have excluded it.",
        "- Drop a modest price reaction driven by news that is itself old.",
        f"- Final flags: HIGH/MEDIUM requires either a price reaction of at least "
        f"{MOVE_THRESHOLD_PCT}%, or news that is itself clearly material (confirmed contract/deal, "
        "regulatory action, notable analyst rating/price-target change, verified real-world "
        "product use, a large disclosed financial figure) regardless of price move.",
        "- If two batches returned conflicting information for the same ticker, prefer the more "
        "specific, more recently dated, better-sourced item.",
        "- Preserve the substantive detail in `impact` for every HIGH/MEDIUM item — concrete "
        "figures, confirmed facts, analyst/firm names, deal values. Do not compress a detailed "
        "batch result down into a vague one-liner; if anything, add specifics you can infer from "
        "the raw results below rather than trim them.",
        "",
        "Yesterday's published items (for dedup):",
        json.dumps([i.model_dump() for i in yesterday_items], indent=2),
        "",
        "Today's raw batch research results to reconcile:",
        json.dumps([i.model_dump() for i in all_items], indent=2),
        "",
        "Return the final reconciled list — exactly one item per ticker that appeared in the raw "
        "results above — matching the required JSON schema.",
    ])


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=30))
async def reconcile(client, date_iso, all_items, yesterday_items):
    prompt = _build_prompt(date_iso, all_items, yesterday_items)

    interaction = await client.aio.interactions.create(
        model=RECONCILE_MODEL,
        input=prompt,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": DAILY_BRIEF_SCHEMA,
        },
    )

    data = json.loads(interaction.output_text)
    return DailyBrief.model_validate(data)
