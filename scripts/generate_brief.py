#!/usr/bin/env python3
"""Morning Brief orchestrator — entry point run by the GitHub Action.

Trigger -> load state -> fan out research per ticker batch -> reconcile ->
write history -> render site + email -> send.
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from google import genai

load_dotenv()  # no-op in CI where there's no .env file

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gemini_research import research_batch, BriefItem  # noqa: E402
from reconcile import reconcile  # noqa: E402
from render import render_site, render_email  # noqa: E402
from email_send import send_brief_email  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TICKERS_FILE = ROOT / "tickers.json"
HISTORY_DIR = ROOT / "history"

BATCH_SIZE = 5
MAX_CONCURRENCY = 5


def gate_on_prague_hour():
    """The workflow fires at both 05:00 and 06:00 UTC to cover both sides of
    Prague's DST shift — only the trigger that lands at 7am local actually
    runs. workflow_dispatch sets FORCE_RUN to bypass this for manual tests.
    """
    now = datetime.now(ZoneInfo("Europe/Prague"))
    if now.hour != 7 and not os.environ.get("FORCE_RUN"):
        print(f"Not 7am Prague yet ({now.isoformat()}), skipping this trigger.")
        sys.exit(0)
    return now


def prior_trading_day_window(now_prague):
    """Heuristic prior-trading-day window: previous calendar day (Friday if
    today is Monday) through this morning. Does not account for market
    holidays — a known v1 limitation.
    """
    today = now_prague.date()
    if today.weekday() == 0:  # Monday -> back to Friday
        start_date = today - timedelta(days=3)
    else:
        start_date = today - timedelta(days=1)
    start = datetime.combine(start_date, dtime(0, 0), tzinfo=ZoneInfo("UTC"))
    end = datetime.combine(today, dtime(6, 0), tzinfo=ZoneInfo("UTC"))
    return start, end


def load_tickers():
    return json.loads(TICKERS_FILE.read_text(encoding="utf-8"))


def load_latest_history():
    if not HISTORY_DIR.exists():
        return None
    files = sorted(p for p in HISTORY_DIR.glob("*.json"))
    if not files:
        return None
    return json.loads(files[-1].read_text(encoding="utf-8"))


def chunk(items, size):
    return [items[i:i + size] for i in range(0, len(items), size)]


async def run():
    now_prague = gate_on_prague_hour()
    today_iso = now_prague.date().isoformat()
    window_start, window_end = prior_trading_day_window(now_prague)

    tickers = load_tickers()
    yesterday = load_latest_history()
    yesterday_items = (
        [BriefItem.model_validate(i) for i in yesterday["items"]] if yesterday else []
    )
    exclude_by_ticker = {}
    for item in yesterday_items:
        if item.headline:
            exclude_by_ticker.setdefault(item.tk, []).append(item.headline)

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    batches = chunk(tickers, BATCH_SIZE)
    sem = asyncio.Semaphore(MAX_CONCURRENCY)

    async def bounded(batch):
        async with sem:
            return await research_batch(
                client, batch,
                window_start.isoformat(), window_end.isoformat(), today_iso,
                exclude_by_ticker,
            )

    print(f"Researching {len(tickers)} tickers in {len(batches)} batches...")
    batch_results = await asyncio.gather(*(bounded(b) for b in batches))
    all_items = [item for batch in batch_results for item in batch]

    print("Reconciling...")
    final_brief = await reconcile(client, today_iso, all_items, yesterday_items)

    HISTORY_DIR.mkdir(exist_ok=True)
    history_payload = {
        "date": today_iso,
        "prior_trading_day_window": {
            "start": window_start.isoformat(),
            "end": window_end.isoformat(),
        },
        "items": [i.model_dump() for i in final_brief.items],
    }
    (HISTORY_DIR / f"{today_iso}.json").write_text(
        json.dumps(history_payload, indent=2), encoding="utf-8"
    )

    render_site(today_iso, history_payload, tickers)
    email_html = render_email(today_iso, history_payload)

    try:
        send_brief_email(today_iso, email_html)
    except Exception as e:  # noqa: BLE001 — never let email failure kill the run
        print(f"WARNING: email send failed: {e}", file=sys.stderr)

    items = history_payload["items"]
    high = [i for i in items if i["flag"] == "HIGH"]
    medium = [i for i in items if i["flag"] == "MEDIUM"]
    print(f"\nMorning Brief {today_iso} — {len(high)} HIGH, {len(medium)} MEDIUM, "
          f"{len(items) - len(high) - len(medium)} QUIET")
    for i in high:
        print(f"  [HIGH]   {i['tk']}: {i['headline']}")
    for i in medium:
        print(f"  [MEDIUM] {i['tk']}: {i['headline']}")


if __name__ == "__main__":
    asyncio.run(run())
