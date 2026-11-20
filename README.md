# Credit Stress Tracker

This tracker watches whether private-credit ("shadow debt") stress is spreading into banks (Stage 3) and funding markets (Stage 4). It scores 29 signals green, amber or red from free data: FRED, the NY Fed Markets API, Yahoo Finance and SEC EDGAR. It then emails a weekly report, plus an alert when something turns red.

> This is a monitoring tool, not investment advice or a timing signal. Thresholds are rules of thumb. Tune them in `config/signals.yaml`.

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

Re-score with the manual inputs, render the email, and append to `data/`:

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
| `config/manual_inputs.yaml` | Non-accruals, PIK, redemptions and gates, judgement signals, Fed actions |
| `config/calendar.yaml` | SLOOS, earnings, GFSR and FSR reminders |

## How it runs

Claude Code cloud scheduled tasks run the tracker by following `RUNBOOK.md`:
- **Weekly:** Monday 10:05 Europe/London.
- **Daily red-alert check:** Tuesday to Saturday, 07:07 Europe/London (after the US close).

`ARCHITECTURE.md` covers the design.
