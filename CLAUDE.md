# Morning Brief — build instructions

A daily stock-watchlist news brief. Runs unattended on GitHub Actions every
weekday at 7:00am Europe/Prague time, researches overnight news for a tracked
ticker list using the Gemini API, publishes the result as a GitHub Pages site
(with an in-page watchlist editor), and emails the same brief to two
addresses.

This file is the spec. Implement it in order — repo scaffold, then the
orchestrator script, then the page/template, then the workflow, then wire up
secrets and do a manual test run before trusting the schedule.

## Origin note

This replaces an earlier Cowork-based version that used a scheduled-tasks MCP
trigger + Claude Code subagents (one per ticker batch) + a live HTML artifact
as both the UI and the state store. None of that infra is available here —
GitHub Actions is the trigger, plain async Gemini calls replace the subagent
fan-out, and git-committed JSON files replace the live artifact as state.

## Architecture

```
GitHub Actions cron (weekdays, 7am Prague)
  -> generate_brief.py
       -> load tickers.json (watchlist) + most recent history/*.json (yesterday, for dedup)
       -> chunk tickers into batches of 5
       -> N parallel Gemini calls (gemini-2.5-flash + google_search grounding + structured output)
       -> 1 reconciliation Gemini call (gemini-2.5-pro) — dedup, apply 5% threshold, assign HIGH/MEDIUM/QUIET
       -> write history/<date>.json
       -> render site/index.html from templates/brief_template.html
       -> send email via Resend (to both addresses)
  -> commit tickers.json / history/ / site/index.html back to main
  -> deploy site/ to GitHub Pages
```

The published page shows today's brief AND a watchlist editor. Editing the
watchlist commits directly to `tickers.json` via the GitHub Contents API,
called from the page's own JS — no second workflow needed. Tomorrow's run
just reads whatever is in `tickers.json` at trigger time.

## Repo layout

```
Morning-Brief/
  tickers.json
  history/
    2026-09-04.json
  site/
    index.html                 # generated — do not hand-edit, edit the template
  templates/
    brief_template.html        # Jinja2 template: brief + watchlist editor
  scripts/
    generate_brief.py          # orchestrator (entry point)
    gemini_research.py         # batch research calls
    reconcile.py                # reconciliation call
    render.py                  # renders site/index.html from history + tickers
    email_send.py               # Resend send
  .github/workflows/
    morning-brief.yml
  requirements.txt
  .env.example
  README.md
```

## Watchlist state — `tickers.json`

Seed it with the current list:

```json
[
  {"tk": "APR.WA", "co": "Auto Partner SA", "ex": "WSE"},
  {"tk": "PCO.WA", "co": "Pepco Group", "ex": "WSE"},
  {"tk": "LPP.WA", "co": "LPP SA", "ex": "WSE"},
  {"tk": "GRPN", "co": "Groupon", "ex": "NASDAQ"},
  {"tk": "NU", "co": "Nu Holdings (Nubank)", "ex": "NYSE"},
  {"tk": "EWG.L", "co": "Eurowag (W.A.G Payment Solutions)", "ex": "LSE"},
  {"tk": "VTY.L", "co": "Vistry Group", "ex": "LSE"},
  {"tk": "PAGS", "co": "PagSeguro Digital", "ex": "NYSE"},
  {"tk": "SEE.L", "co": "Seeing Machines", "ex": "LSE"},
  {"tk": "NVO", "co": "Novo Nordisk", "ex": "NYSE"},
  {"tk": "ARA.MX", "co": "Consorcio ARA", "ex": "BMV"},
  {"tk": "KSPI", "co": "Kaspi.kz", "ex": "NASDAQ"},
  {"tk": "VME.DE", "co": "Viromed Medical AG", "ex": "XETRA"},
  {"tk": "KEOC.ST", "co": "Keo Capital", "ex": "Nasdaq Stockholm"},
  {"tk": "GRBK", "co": "Green Brick Partners", "ex": "NYSE"},
  {"tk": "XPF.L", "co": "XP Factory", "ex": "LSE"},
  {"tk": "GOOG", "co": "Alphabet", "ex": "NASDAQ"},
  {"tk": "NVDA", "co": "Nvidia", "ex": "NASDAQ"},
  {"tk": "NOW", "co": "ServiceNow", "ex": "NYSE"},
  {"tk": "EVC", "co": "Entravision Communications", "ex": "NYSE"},
  {"tk": "UBER", "co": "Uber Technologies", "ex": "NYSE"},
  {"tk": "BA", "co": "Boeing", "ex": "NYSE"},
  {"tk": "EVO.ST", "co": "Evolution AB", "ex": "Nasdaq Stockholm"}
]
```

## `history/<date>.json` schema

This is both the published day's data and tomorrow's dedup input.

```json
{
  "date": "2026-09-04",
  "prior_trading_day_window": {"start": "2026-09-03T00:00:00Z", "end": "2026-09-04T06:00:00Z"},
  "items": [
    {
      "tk": "UBER",
      "co": "Uber Technologies",
      "flag": "HIGH",
      "headline": "...",
      "impact": "...",
      "move_pct": 6.2,
      "url": "https://...",
      "published_at": "2026-09-03T21:10:00Z"
    }
  ]
}
```

`flag` is `HIGH` / `MEDIUM` / `QUIET`. QUIET tickers still get an entry (empty
or minimal) so the dedup/history trail is complete, even though most small
caps will be QUIET most days — that's expected, not a failure.

## `scripts/generate_brief.py` — orchestrator

1. **DST/schedule gate first.** The workflow triggers at both 05:00 and
   06:00 UTC (see workflow below) because Prague shifts between UTC+1 and
   UTC+2. Only actually run the brief if it's currently 7am in
   `Europe/Prague`:

   ```python
   from zoneinfo import ZoneInfo
   from datetime import datetime
   import os, sys

   now = datetime.now(ZoneInfo("Europe/Prague"))
   if now.hour != 7 and not os.environ.get("FORCE_RUN"):
       print(f"Not 7am Prague yet ({now.isoformat()}), skipping this trigger.")
       sys.exit(0)
   ```

   `workflow_dispatch` (manual runs) should set `FORCE_RUN=1` to bypass this.

2. **Compute the prior trading day window**, skipping weekends. Holidays are
   a known gap for v1 — not handled, note it in the README as a limitation.

3. **Load state**: `tickers.json` (current watchlist — always read fresh,
   never hardcode tickers anywhere else) and the most recent file in
   `history/` (for the dedup/exclude list per ticker).

4. **Batch and fan out.** Chunk tickers into groups of 5. For each batch,
   call Gemini concurrently — see `gemini_research.py` below. Cap concurrency
   with a semaphore (default 5 concurrent requests; adjust down if you hit
   rate limits on your Gemini tier) and wrap each batch call in retry with
   exponential backoff (3 attempts) so a transient failure doesn't require
   manual relaunching, unlike the old Cowork version.

5. **Reconcile** — see `reconcile.py` below.

6. **Write** `history/<date>.json`.

7. **Render** `site/index.html` via `render.py`.

8. **Email** via `email_send.py`.

9. Print a short stdout summary (HIGH items first, one line each) for the
   Action log.

## `gemini_research.py` — per-batch research call

- Model: `gemini-2.5-flash` (cheap; this runs once per batch, ~5 times per
  morning — no reason to pay Pro pricing here).
- Tool: Google Search grounding — `tools=[{"google_search": {}}]`. This
  replaces WebSearch-then-summarize as a single call.
- Structured output: pass a `response_schema` (JSON mode) matching the
  `items` array shape above, so you get parsed JSON back directly instead of
  parsing a fixed text format.
- System instructions must state explicitly, verbatim, every run — this is
  the actual IP of the whole system, carry it over unchanged in spirit from
  the old task file:
  - Exact date window (today's date + the prior-trading-day window).
  - Per-ticker company/exchange context (from `tickers.json`).
  - The exclude list: headlines/URLs already reported for that ticker
    yesterday (from the loaded history file) — don't re-report them.
  - **Move threshold: 5%** (updated from the original 10%) — price moves
    under 5% don't qualify as HIGH/MEDIUM on their own.
  - No fabrication — only items with a real, dated, in-window source.
  - QUIET is an expected, acceptable outcome for most tickers most days —
    do not manufacture content to avoid returning QUIET.

## `reconcile.py` — single reconciliation call

- Model: `gemini-2.5-pro` — this runs once per morning regardless of ticker
  count, so the better reasoning is cheap here even though Flash was right
  for the batches. This is where the judgment calls happen: an item dated
  just outside the window but clearly new and material should be kept (e.g.
  a regulatory fine announced late the prior session); a fresh publish
  timestamp wrapped around a stale analyst reiteration should be dropped;
  a small reaction to old news should be dropped.
- Input: the concatenated batch results + yesterday's `history` file.
- Output: same `items` schema, finalized — this is what gets written to
  `history/<date>.json`.
- Do this reconciliation in one real Gemini call, not pure string-matching
  Python logic — the materiality judgment calls are the part that needs a
  model, not a diff.

## `templates/brief_template.html` + `render.py`

Single self-contained HTML page (inline CSS/JS is fine, matches the old
artifact's approach) with two sections:

1. **Today's brief** — HIGH items first, then MEDIUM, QUIET tickers listed
   compactly or collapsed (nobody needs to read 15 "no news" lines by
   default).
2. **Watchlist editor** — list of tracked tickers with a remove control and
   an add-ticker input. On save, it:
   - Prompts once for a GitHub fine-grained Personal Access Token (repo
     scoped to `Morning-Brief` only, `Contents: read/write` permission —
     nothing broader). Stores it in `localStorage`, never anywhere else.
   - `GET`s `tickers.json` via the GitHub Contents API to obtain its current
     `sha`, edits the array client-side, `PUT`s it back with the same API —
     a real commit. Tomorrow's run picks it up automatically.
   - Note in the UI, in small text: the token stays in your browser only;
     use a token scoped to this one repo, not a broad classic PAT.

`render.py` just fills the template from `history/<date>.json` +
`tickers.json` via Jinja2 — no logic beyond templating.

## `email_send.py`

- Provider: **Resend** (`RESEND_API_KEY` secret). One-time manual setup
  outside this repo: sign up, verify a sending domain or use the sandbox
  sender for testing — Resend restricts unverified senders to limited
  recipients, so verify before relying on the two real addresses below.
- Recipients: `seda.21@seznam.cz`, `martin.sedivy@jtfg.com`.
- Send the same HIGH-first content as the page, as a plain HTML email (reuse
  the rendered brief section, not the watchlist editor part).

## `.github/workflows/morning-brief.yml`

```yaml
name: Morning Brief

on:
  schedule:
    - cron: '0 5 * * 1-5'   # 7am Prague when CEST (UTC+2, summer)
    - cron: '0 6 * * 1-5'   # 7am Prague when CET  (UTC+1, winter)
  workflow_dispatch: {}

permissions:
  contents: write
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: false

jobs:
  build-and-publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt
      - name: Generate brief
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          RESEND_API_KEY: ${{ secrets.RESEND_API_KEY }}
          FORCE_RUN: ${{ github.event_name == 'workflow_dispatch' && '1' || '' }}
        run: python scripts/generate_brief.py
      - name: Commit updated data
        run: |
          git config user.name "morning-brief-bot"
          git config user.email "actions@github.com"
          git add tickers.json history/ site/index.html
          git diff --cached --quiet || git commit -m "Morning brief $(date -u +%F)"
          git push
      - uses: actions/upload-pages-artifact@v3
        with:
          path: site
      - uses: actions/deploy-pages@v4
```

Both cron lines fire every weekday; the script's Prague-hour gate makes only
one of them actually produce output, so DST is handled without any manual
schedule updates twice a year.

## Secrets to set in the repo (Settings → Secrets and variables → Actions)

- `GEMINI_API_KEY`
- `RESEND_API_KEY`

The watchlist-editor PAT is **not** a repo secret — the user enters it once
in their own browser, stored in `localStorage` only.

## Local dev

- `.env.example` listing `GEMINI_API_KEY`, `RESEND_API_KEY`.
- `python scripts/generate_brief.py` with `FORCE_RUN=1` in the environment
  to bypass the time gate for local testing.
- Test with a 2-3 ticker subset of `tickers.json` first to avoid burning
  quota while iterating on prompts/schema.

## Known limitations (v1, intentional — not bugs to silently fix)

- Prior-trading-day logic skips weekends only, not market holidays.
- Reconciliation quality depends on `gemini-2.5-pro` judgment for the
  "outside window but material" / "stale reiteration" calls — spot-check the
  first week of real runs against what you'd have flagged manually.
- Repo is public by default (simplifies free GitHub Pages hosting); nothing
  secret lives in code, but the ticker watchlist and briefs are visible to
  anyone with the link. Switch to private only if you also have GitHub
  Pro/Team (required for private-repo Pages).
