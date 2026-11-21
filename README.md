# Credit Stress Tracker

This tracker watches whether private-credit ("shadow debt") stress is spreading into banks (Stage 3) and funding markets (Stage 4). It scores 29 signals green, amber or red from free data: FRED, the NY Fed Markets API, Yahoo Finance and SEC EDGAR. It emails a weekly report, plus an alert when something turns red.

> This is a monitoring tool, not investment advice or a timing signal. Thresholds are rules of thumb. Tune them in `config/signals.yaml`.

## How it runs

Two Claude Code cloud scheduled tasks run the tracker. Each follows `RUNBOOK.md`:

| Task | When (Europe/London) | Model | Email |
|---|---|---|---|
| **Weekly report** | Monday 10:05, in the inbox by about 10:30 | Opus 5.5 | Always |
| **Daily red-alert check** | Tuesday to Saturday 07:07, after the US close | Sonnet 5.5 | Only when a signal newly turns red or the composite rises |

- **Repo and connector:** each run starts a fresh cloud session with this repo and the Gmail connector attached.
- **Every run:**
  - scores the signals and commits history to `data/`;
  - pushes to `main` only;
  - ends its final reply with a one-line status, e.g. `daily · Contained grind · 1 red / 1 amber · email not sent (no alerts) · commit ee56dfd`.
- **Weekly run only:**
  - reads new SEC filings and checks the news (insurer ratings, Fed actions, fund gates, BDC quarterly figures);
  - records sources in `config/manual_inputs.yaml`;
  - writes a 3-line summary;
  - saves a report to `reports/<date>.md`.
- **If Gmail fails:** the run opens a GitHub issue on this repo instead, and GitHub emails you.
- **Cost:** about $2.30–2.95 a week in API-equivalent usage, roughly 1% of the Pro plan's weekly limit.

## The weekly email

- **At a glance:** a composite level "ladder" (Calm → Contained grind → Spreading to banks → Systemic funding stress) and a "This week" summary.
- **Stage tiles:** four tiles with red, amber and green counts per stage.
- **Per stage:**
  - a table with value, 1-week and 3-month change, and status;
  - change arrows: red = toward stress, green = away from it;
  - one chart image with 6 months of history, shaded amber/red zones and labelled thresholds.
- **SEC filing keyword scan:** counts compared with the previous scan, plus a list of new filings.
- **Coming up:** dates from `config/calendar.yaml`, then a link to the full report on GitHub.
- **No SEC links in the email:** a privacy guard blocks sending them, so they appear only in `reports/<date>.md`.

## Commands

```bash
python -m pip install -r requirements.txt
```

Fetch every source and fail if any series is missing:

```bash
python -m tracker verify
```

Fetch and score, writing `out/run.json` and `out/report.html` (no history is written):

```bash
python -m tracker run --mode weekly
```

Re-score with the manual inputs, render the email and charts, and append to `data/`:

```bash
python -m tracker finalize
```

Score past Fridays, to tune thresholds:

```bash
python -m tracker replay --start 2024-01-05
```

Run the tests:

```bash
python -m pytest -q
```

## Files you edit by hand

| File | What it holds |
|---|---|
| `config/signals.yaml` | Signals, thresholds and staleness limits |
| `config/composite.yaml` | Composite levels (Contained grind, Spreading to banks, Systemic funding stress) |
| `config/manual_inputs.yaml` | Quarterly BDC non-accruals and PIK (average of whichever BDCs reported; fewer than 3 of 4 is flagged as low coverage), fund redemptions and gates, judgement signals, Fed actions. Every value needs a source |
| `config/calendar.yaml` | SLOOS, earnings, IMF GFSR and Fed FSR reminders |
| `config/settings.yaml` | EDGAR banks, insurers and keywords; history length; repo link used in the email |

## Where things are

| Path | What it holds |
|---|---|
| `RUNBOOK.md` | Step-by-step instructions the scheduled runs follow |
| `ARCHITECTURE.md` | Design, data sources, conventions, lessons from the build, cost, open items |
| `reports/<date>.md` | Weekly reports with full source links |
| `data/` | History: per-signal observations, runs, EDGAR scans, threshold replay |
| `.claude/settings.json` | Commands pre-approved for unattended runs |
