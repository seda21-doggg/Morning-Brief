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
   - `RESEND_API_KEY`
   - `RESEND_FROM` (optional — a verified sender, e.g. `"Morning Brief <brief@yourdomain.com>"`;
     falls back to Resend's sandbox sender otherwise)
2. **Resend** — sign up at resend.com and verify a sending domain (or rely on
   the sandbox sender for initial testing — it has recipient restrictions).
3. **GitHub Pages** — repo Settings → Pages → Source: **GitHub Actions**.
4. **First run** — Actions tab → Morning Brief → Run workflow
   (`workflow_dispatch`) to test without waiting for the schedule. This sets
   `FORCE_RUN=1` and bypasses the 7am-Prague gate.

## Local development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in GEMINI_API_KEY, RESEND_API_KEY
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
  judgment calls) depends on the `gemini-2.5-pro` call in
  [`scripts/reconcile.py`](scripts/reconcile.py) — spot-check the first
  week of real runs.
- Repo is public by default for free Pages hosting; nothing secret lives in
  code, but the ticker list and briefs are visible to anyone with the link.
- The Gemini structured-output schemas in `gemini_research.py` /
  `reconcile.py` were hand-verified against docs but not yet run against a
  live API key from this session — run the first `workflow_dispatch` test
  and check the Action log / `history/<date>.json` before trusting the
  schedule.
