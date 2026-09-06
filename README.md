# Morning Brief

A daily stock-watchlist news brief. Runs on GitHub Actions every weekday at
7:00am Europe/Prague time, researches overnight news for the tracked tickers
in [`tickers.json`](tickers.json) using the Gemini API (Google Search
grounding + structured output), publishes the result to GitHub Pages (with
an in-page watchlist editor), and emails the same brief.

Full design/build spec: [`CLAUDE.md`](CLAUDE.md).

## One-time setup

1. **Secrets** — repo Settings → Secrets and variables → Actions:
   - `GEMINI_API_KEY`
   - `GMAIL_ADDRESS` — the Gmail address the brief is sent from
   - `GMAIL_APP_PASSWORD` — a 16-character App Password for that account
     (Google Account → Security → 2-Step Verification → App passwords; a
     regular Gmail password will not work here, and 2-Step Verification must
     be enabled first to see the App passwords option)
2. **GitHub Pages** — repo Settings → Pages → Source: **GitHub Actions**.
3. **First run** — Actions tab → Morning Brief → Run workflow
   (`workflow_dispatch`) to test without waiting for the schedule. This sets
   `FORCE_RUN=1` and bypasses the 7am-Prague gate.

## Local development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in GEMINI_API_KEY, GMAIL_ADDRESS, GMAIL_APP_PASSWORD
FORCE_RUN=1 python scripts/generate_brief.py
```

Trim `tickers.json` down to 2-3 entries while iterating on prompts/schema to
avoid burning API quota.

## Editing the watchlist

Open the published Pages site → **Watchlist** tab. The first add/remove
prompts for a GitHub fine-grained Personal Access Token (scope it to just
this repo, `Contents: read/write` only) — it's stored in your browser's
`localStorage` and used to commit directly to `tickers.json` via the GitHub
API. Nothing else can read it. Changes apply from the next scheduled run.

## Known limitations (v1)

- Prior-trading-day window skips weekends only, not market holidays.
- Reconciliation quality (dedup, "material despite being outside the window"
  judgment calls) depends on the `gemini-3.1-pro-preview` call in
  [`scripts/reconcile.py`](scripts/reconcile.py) — spot-check real runs
  against what you'd have flagged manually. It's a preview model; if it
  ever 404s as deprecated, the fix is the same as last time — check
  Google's error message for the model it now recommends, swap
  `RECONCILE_MODEL`.
- Repo is public by default for free Pages hosting; nothing secret lives in
  code, but the ticker list and briefs are visible to anyone with the link.
- Model IDs and quota/billing requirements on the Gemini API side move
  fast — if a run 404s on a model name or 429s with a billing message, see
  the model-swap note above and check aistudio.google.com / your Cloud
  project's billing.
