# Credit Stress Tracker: Architecture & Plan

Status: **v1.0, built and verified against live data** · 2026-11-20
Source spec: `credit-stress-tracker-spec.md`

## Decisions (confirmed)
- **Code and history:** a new private GitHub repo, `credit-stress-tracker`, that you create.
- **Schedule:** a weekly report every Monday, arriving by 10:30 UK time, plus a daily red-alert check Tue–Sat at about 07:30 UK.
- **Delivery:** HTML email through your connected Gmail account, sent to your own address.
- **SEC EDGAR User-Agent:** your account email. It is sent only to sec.gov and read from the environment variable `SEC_CONTACT_EMAIL`, so it is never committed to the repo.

---

## 1. What runs where

The tracker runs as a **Claude Code cloud scheduled task**. Every run starts a fresh, temporary container, so nothing stays on disk between runs. The code, the config and the history all live in a **GitHub repo**. Each run clones the repo, computes the signals, sends the report and commits the new history rows back.

```
 ┌──────────── Scheduled task (Mon 10:05 Europe/London) ─────────────┐
 │  fresh cloud session  →  clone repo  →  pip install (setup script) │
 │                                                                    │
 │  1. python -m tracker run --mode weekly      (deterministic core)  │
 │       fetch → validate/staleness → score → composite → render      │
 │       writes: out/report.html, out/report.md, out/run.json         │
 │                                                                    │
 │  2. Claude layer (judgement, per RUNBOOK.md)                       │
 │       • write the 3-line plain-English summary from run.json       │
 │       • web search: insurer downgrades, Fed facilities/cuts,       │
 │         non-traded BDC/private credit fund gates                   │
 │       • quarterly weeks: review EDGAR keyword-scan hits            │
 │                                                                    │
 │  3. Deliver: Gmail connector → email to you (HTML body)            │
 │  4. git commit data/*.csv + reports/YYYY-MM-DD.md → push           │
 └────────────────────────────────────────────────────────────────────┘
```

**Why this split:** the numbers, thresholds and status colours come from plain Python, so they can be tested and repeated, and a run gives the same result whether or not Claude is involved. Claude handles the parts the spec leaves to judgement or news: the summary, insurer downgrades, Fed actions, fund gates, and reading filing snippets. Those parts would be fragile as code.

---

## 2. Schedule

| Job | When | Cron (stored with `CRON_TZ=Europe/London`) | Notes |
|---|---|---|---|
| **Weekly full report** | Mon, starts 10:05, in your inbox by about 10:30 | `5 10 * * 1` | Covers Friday's H.8 (released Fri 16:15 ET) and Friday's market close. Uses the London zone, so BST/GMT changes are handled. |
| Daily red-alert check *(optional, decision needed)* | Tue–Sat 07:xx London (after the US close) | `xx 7 * * 2-6` | Stage 2 and 4 only. Emails only when a signal turns red or the composite moves up a level; otherwise it stays silent. |
| Quarterly items | inside the weekly report | n/a | An "Upcoming in the next 14 days" block lists SLOOS, bank/BDC earnings, the IMF GFSR and the Fed FSR, from `config/calendar.yaml`. |

> The spec puts the weekly run on Friday evening. A Monday 10:30 UK report still has all of Friday's data, so nothing is lost. Its "1-week change" means Fri→Fri closes.

---

## 3. Data sources & network

The data hosts must be allowed in the cloud environment. **All of them are currently blocked** in your Default environment (checked: proxy 403 for every host below).

| Source | Hosts | Auth | Used for |
|---|---|---|---|
| FRED (keyless CSV) | `fred.stlouisfed.org` | none | All FRED series via `fredgraph.csv?id=…` |
| NY Fed Markets API | `markets.newyorkfed.org` | none | SOFR, TGCR, Standing Repo Facility results |
| Yahoo (yfinance) | `query1.finance.yahoo.com`, `query2.finance.yahoo.com`, `fc.yahoo.com` | none | BIZD, BDC stocks, BKLN, KRE/KBE/XLF/SPY, TLT, GLD, ^VIX, ^MOVE |
| SEC EDGAR | `data.sec.gov`, `www.sec.gov`, `efts.sec.gov` | none, but a User-Agent with contact info is **required** | BDC NAV/share via XBRL `companyconcept`, 10-Q full-text keyword scan |
| Gmail | MCP connector | your connected account | Delivery |

**FRED key decision:** use the keyless `fredgraph.csv` endpoint instead of the JSON API. The JSON API takes the key as a URL query parameter. The environment's secret store can only inject headers, so the key would have to sit in plain text in the environment. Keyless CSV avoids that. Staleness is checked from the date of the last observation, which is the check that matters. The JSON API can be added later if needed.

**BDC NAV:** take it from EDGAR XBRL (`us-gaap:NetAssetValuePerShare`) rather than scanning 10-Q text for keywords. It is structured data, so it is reliable. Keyword scanning is kept for the Stage 3 disclosure terms only.

**Proposed environment:** a new personal environment, `credit-stress-tracker`, with the hosts above, package managers on, and a setup script that runs `pip install -r requirements.txt`. It needs no secrets.

---

## 4. Repo layout

```
credit-stress-tracker/
├── RUNBOOK.md                 # what the scheduled Claude session does, step by step
├── config/
│   ├── signals.yaml           # every signal: id, source, series, transform, amber/red rule, max_age
│   ├── composite.yaml         # composite-level rules (contained / spreading / systemic)
│   ├── calendar.yaml          # quarterly reminder dates
│   └── manual_inputs.yaml     # you edit by hand: non-accruals, PIK %, redemptions/gates, Fed actions
├── tracker/
│   ├── sources/  fred.py  nyfed.py  yahoo.py  edgar.py   # one fetcher each, all return tidy pandas Series
│   ├── calendar_utils.py      # US business days, month-end/quarter-end windows
│   ├── transforms.py          # pct_from_52w_high, rel_perf_3m, growth_3m, spread_vs, persist_n_days …
│   ├── rules.py               # generic threshold evaluator (gt/lt/persist/rising_n/count_in_window)
│   ├── composite.py
│   ├── history.py             # append + read data/*.csv
│   ├── alerts.py              # diff vs. previous run → red transitions, composite escalation
│   ├── render.py              # HTML email + markdown report (Jinja2)
│   └── cli.py                 # verify | backfill | run --mode weekly|daily
├── data/
│   ├── observations.csv       # long format: date, signal_id, value, status, run_id
│   └── runs.csv               # run_id, ts, mode, composite, stale_series, errors
├── reports/2026-11-23.md      # archived weekly reports (readable on GitHub)
└── tests/                     # rule-evaluator tests on fixture data
```

**Storage decision:** append-only CSV committed to git, not SQLite. It is about 50 signals × 1 row per day, which comes to well under 1 MB a year. CSV diffs show on GitHub and stay readable there, while a binary SQLite file rewritten in git on every run would not. `history.py` can load it into SQLite or pandas when you want to query it.

---

## 5. Signal engine

The engine is driven by config, so thresholds never appear in code. Example `signals.yaml` entries:

```yaml
- id: hy_oas
  stage: 2
  source: {type: fred, series: BAMLH0A0HYM2}
  unit: bp            # FRED gives %, transform ×100
  transform: {fn: scale, factor: 100}
  rule: {op: gt, amber: 400, red: 500}
  max_age_bdays: 3

- id: sofr_iorb
  stage: 4
  source: {type: spread, a: {type: nyfed, rate: sofr}, b: {type: fred, series: IORB}}
  unit: bp
  rule: {op: gt_persist, amber: 5, red: 15, days: 3, exclude: month_end_window}

- id: kre_vs_spy_3m
  stage: 3
  source: {type: rel_perf, a: KRE, b: SPY, window: 63}
  rule: {op: lt, amber: -10, red: -20}
```

Rule types cover the whole spec: `gt`/`lt`, `gt_persist` (N days), `rising_n_periods`, `change_over_window`, `count_in_window` (forced-selling days), `manual` (taken straight from the YAML).

**Month-end and quarter-end repo spikes:** the last business day of a month or quarter and the first 2 business days after it are tagged `window=true`. A breach inside that window shows as amber with a "MEQ" flag and never triggers an alert. It counts toward red only if it lasts past the second business day after the window.

**Freshness ("fail loudly"):** each signal has `max_age_bdays`. A stale or missing series is marked `STALE` in grey, listed at the top of the report, and the email subject gets `⚠ DATA ISSUE`. A run where more than 25% of series are stale exits non-zero, and Claude then emails a failure notice instead of a misleading report.

**First run:** `tracker verify` fetches every series ID once and prints the last date and value for each. It exits non-zero on a 404 or an empty series. Several IDs in the spec need checking before anything is built on them (see §8).

---

## 6. Report & alerts

- **Email subject:** `Credit Stress · Contained grind · 2 amber, 0 red · w/e 21 Nov`
- **Top:** the composite level badge plus a 3-line summary that Claude writes from `run.json`.
- **Per stage:** a table with columns Signal | Value | 1w Δ | 3m Δ | Status | Trend.
- **Sparklines** are drawn as **Unicode blocks** (`▁▂▃▅▆▇`, last 13 weeks). Gmail removes inline SVG and often blocks images, while plain text always renders.
- **Context sections:** Fed actions (manual YAML plus Claude's news check), Upcoming dates, Data issues.
- The markdown copy goes into `reports/` in the repo.
- **Alerts** (daily job, or the weekly job if daily is turned off) fire only on `status → red` or a composite escalation. The subject starts with `🔴`, and the body names the signal, its value, the threshold, and how long it has been in breach.
- **Disclaimer footer:** "Monitoring tool, not investment advice."

---

## 7. Build phases

| # | Phase | Output | Done when |
|---|---|---|---|
| 0 | **Setup** | GitHub repo, cloud environment with hosts, Gmail connector check | `curl` reaches every host from a session |
| 1 | **Fetchers + verify** | `sources/*`, `tracker verify` | every spec series resolves, or is replaced with a documented alternative |
| 2 | **Backfill** | `tracker backfill --years 3` | history CSV holds 3 years, so 52w-high, 3m and 8w windows work from day one |
| 3 | **Rules + composite** | `rules.py`, `composite.py`, tests | unit tests pass; a replay of Mar 2020, Sep–Oct 2022 and Mar 2023 (SVB) produces sensible colours |
| 4 | **Render + history + alerts** | HTML/MD report, CSV append, diffing | a local dry run produces the report from live data |
| 5 | **Claude layer** | `RUNBOOK.md` (summary, news checks, send email, commit) | one manual end-to-end run lands in your inbox |
| 6 | **Schedule** | weekly scheduled task (and daily, if chosen) | the first scheduled email arrives Mon 10:30 |
| 7 | **Tune** | adjust thresholds after 4–6 weeks | n/a |

The Phase 3 replay doubles as a threshold sanity check. ICE BofA OAS history on FRED is limited to the most recent years, so the 2020 replay may need to use the spec's levels without a check against data.

---

## 8. Phase 1 pre-check (run 2026-11-20, all sources reachable)

| Check | Result |
|---|---|
| FRED: all 12 spec series IDs | ✅ all resolve. HY OAS 352 bp, CCC 1,353 bp (**red**), IG 94 bp, IORB 3.90, NFCI −0.48, STLFSI4 −0.87, VIXCLS 24.6 |
| H.8 `LNFACBW027SBOG` | ✅ last obs 2026-11-04. The data lags about 2 weeks, so `max_age` must be 18 days or more |
| `B1030NDMCMG` | ✅ 30.3% annualised (Oct) |
| NY Fed SOFR / TGCR / repo ops | ✅ SOFR 3.91 (+1 bp vs IORB), TGCR 3.88. The repo ops endpoint is `/api/rp/repo/all/results/last/N.json` |
| Yahoo: all 14 tickers incl. ^MOVE | ✅ (crumb 429 warning, harmless). ^VIX 29.7 intraday, ^MOVE 102 |
| SEC XBRL NAV/share | ✅ ARCC NAV $19.31 (Q3 10-Q) vs price $18.60, so P/NAV 0.96 |

**SEC contact:** a privacy guard here blocks me from writing your email address into code or commands. Put it in an environment variable `SEC_CONTACT_EMAIL` on the `credit-stress-tracker` environment (Settings → environment → variables). The code reads that variable and falls back to a generic UA.

## 8a. Implementation notes (from the build)

- **FRED User-Agents:** FRED drops requests that carry unknown custom User-Agents. Non-SEC hosts use the `requests` library's default UA.
- **Yahoo prices:** dividend-adjusted closes push historical BDC prices down by every later dividend (about 10% a year). Price-level signals (P/NAV, VIX, MOVE) use **raw** closes. Return-based signals (BIZD drawdown, BKLN 1m, KRE/KBE vs SPY, forced selling) use **adjusted** total-return closes.
- **Non-traded funds:** the redemption signal is split in two. `nontraded_redemptions` (requests > 5% → amber) and `nontraded_gates` (gated 1 qtr → amber, 2+ → red).
- **Judgement signals:** `bank_disclosures` and `insurer_ratings` are set weekly by the Claude run in `manual_inputs.yaml`. They go STALE after 10 days, which forces the weekly review.
- **Replay** (`data/replay.csv`, weekly from Jan 2024): composite was level 0 in 21 weeks and level 1 in 130. The level-1 weeks are driven mainly by FSK/OBDC P/NAV and BIZD, plus CCC OAS in 2026. FSK has traded below 0.90× NAV for most of the period. Consider a per-BDC baseline after a few weeks of data.

## 8b. Remaining open items

- **Series IDs that need checking on first run.** Fall back to the right H.8 / Z.1 series if any are wrong:
  - `LNFACBW027SBOG`, `LNFACBM027SBOG` (H.8 loans to nondepository financial institutions)
  - `B1030NDMCMG` (NBFI loan growth)
- **CCC OAS series:** `BAMLH0A3HYC` is "CCC & lower", which is fine.
- **`^MOVE` on Yahoo:** coverage can have gaps. If needed, fall back to flagging it stale. There is no good free alternative.
- **SRF endpoint:** NY Fed `/api/rp/results/search.json` (operationType=repo). The filter needs confirming once the host is open.
- **NFCI amber rule** ("rises > 0.25 in 8 weeks"): uses an 8-week change of the weekly series.
- **SEC User-Agent:** EDGAR asks every client for a contact string. You decide what goes in it (see the questions).

---

## 9. Cost & limits

- One cloud session per week, about 5–10 minutes. The daily option adds 5 short sessions a week, mostly silent.
- No paid APIs are used. yfinance is unofficial and Yahoo sometimes rate-limits it. Fetches retry 3 times with backoff, and a failure there marks only those signals stale.
