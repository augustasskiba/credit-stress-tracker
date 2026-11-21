# Credit Stress Tracker: Architecture

Status: **v1, live.** Built and tested end to end on 2026-11-20 and 2026-11-21 (manual weekly runs on Opus 5.5 and daily runs on Sonnet 5.5, email received). The first scheduled daily check ran on 2026-11-21 at 07:07. Last doc update: 2026-11-21.
Source spec: `credit-stress-tracker-spec.md` (the original brief). Operating instructions for scheduled runs: `RUNBOOK.md`.

> Monitoring tool only, not investment advice or a timing signal. Thresholds are rules of thumb.

---

## 1. What runs where

The tracker runs as **Claude Code cloud scheduled tasks**. Every run starts a fresh, temporary container, so nothing stays on disk between runs. Code, config and history all live in this GitHub repo. Each run clones it, scores the signals, emails the report and commits the new history back to `main`.

```
 ┌────────── Scheduled task (fresh cloud session, env "credit-stress-tracker") ──────────┐
 │ repo attached to the task  ·  Gmail connector attached  ·  setup script installs deps │
 │                                                                                        │
 │ 0. git checkout -B main origin/main · pip install -r requirements.txt · Pillow         │
 │ 1. python -m tracker run --mode weekly|daily     (deterministic Python core)           │
 │      fetch → validate/staleness → score → composite → alerts → out/run.json            │
 │ 2. Claude judgement (weekly only, per RUNBOOK.md)                                      │
 │      • read the EDGAR hits (new filings first) → bank_disclosures                      │
 │      • web search: insurer downgrades, Fed actions, fund gates, BDC Q figures          │
 │      • record everything with sources in config/manual_inputs.yaml                     │
 │ 3. out/summary.md: 3 plain-English lines (daily: only if there is an alert)            │
 │ 4. python -m tracker finalize                                                          │
 │      re-score with manual inputs → render HTML/text/markdown + 4 chart PNGs            │
 │      → append data/*.csv → reports/<date>.md (weekly)                                  │
 │ 5. Gmail send_message (weekly always; daily only on a new red / composite rise)        │
 │      fallback: GitHub issue on this repo (GitHub emails the owner)                     │
 │ 6. git commit data/ reports/ config/{manual_inputs,calendar}.yaml → push to main only  │
 │ 7. final reply ends with the status line (see below)                                   │
 └────────────────────────────────────────────────────────────────────────────────────────┘
```

**Status line.** Every run's final reply must end with one line in a fixed format, with any notes above it. This is required by RUNBOOK step 7 and by both task prompts:

```
<weekly|daily> · <composite> · <n> red / <n> amber · email <sent|not sent (no alerts)|FAILED: reason> · commit <hash>
```

If the run replies again (for example after a git hook nudges it to push its session branch, which it must decline), that reply ends with the same line.

**Working on `main`.** Sessions start on an auto-named `claude/*` branch. The runbook's first step switches to `main` (`git fetch origin main && git checkout -B main origin/main`), so commits land on `main` directly. Since this change, the git hook no longer asks to push a session branch.

**Runbook rules added 2026-11-21:**
- Never work around a safety or privacy guard; use the documented fallback and report it.
- Insurer actions count only if dated in the last 7 days. An older action no earlier week recorded may be counted once, with a note.
- Coming-up items that have already happened are removed from `config/calendar.yaml`.
- `finalize` may be re-run (it replaces that day's rows). The run checks the subject and summary before sending.

**Why this split:** numbers, thresholds, colours, charts and alerts come from plain, tested Python, so the same data always gives the same result. Claude handles the judgement parts: the summary, reading filings, news on insurers, the Fed and fund gates, and sourcing quarterly BDC figures. Every value Claude adds must cite a source.

---

## 2. Schedule

| Scheduled task | When (Europe/London) | Scope | Email |
|---|---|---|---|
| **Credit Stress Weekly Report** | Mon 10:05, in the inbox by about 10:30 | All 4 stages, judgement and news checks, EDGAR scan | Always |
| **Credit Stress Daily Check** | Tue–Sat 07:07, after the US close | Stages 2 and 4 only | Only on a new red signal or a composite rise |

- Both tasks start a new session per run in environment `credit-stress-tracker`, on a split model setup (2026-11-20): the **weekly report on Claude Opus 5.5** for its judgement work (reading filings, dating news, sourcing BDC figures), and the **daily check on Claude Sonnet 5.5**, which is mostly mechanical and costs half as much per token. Each has the repo `augustasskiba/credit-stress-tracker` and the Gmail connector attached.
- The cron uses the London zone, so BST and GMT changes are handled automatically.
- Monday's report includes Friday's H.8 release (Fri 16:15 ET) and the Friday close. "1-week change" means Fri→Fri.
- Quarterly reminders (SLOOS, bank and BDC earnings, IMF GFSR, Fed FSR) appear in the weekly email under "Coming up", from `config/calendar.yaml`.

---

## 3. Cloud environment `credit-stress-tracker`

| Setting | Value |
|---|---|
| Network | Unrestricted (set by the owner) |
| Variables | `SEC_CONTACT_EMAIL`, read by the code for the SEC User-Agent. The address is never committed. |
| Setup script | For both `python` and `python3`: `-m pip install` pandas, requests, yfinance, PyYAML, matplotlib, pytest, then `--ignore-installed pillow` |
| Repositories | `augustasskiba/credit-stress-tracker` |
| Pre-approved commands | `.claude/settings.json`: tracker, pytest, pip, git add/commit/pull/fetch/checkout and push to main, the GitHub-issue fallback, web search and fetch, Gmail send |

---

## 4. Data sources

| Source | Access | Used for |
|---|---|---|
| FRED `fredgraph.csv` | Keyless CSV. **Standard client User-Agent only:** FRED drops custom ones | OAS spreads, H.8 NBFI loans, NBFI growth, SLOOS, IORB, NFCI/ANFCI, STLFSI |
| NY Fed Markets API | No key | SOFR, TGCR, Standing Repo Facility results (daily accepted, $bn) |
| Yahoo Finance (yfinance) | Unofficial; retried | BIZD, ARCC, OBDC, FSK, BXSL, BKLN, KRE, KBE, SPY, TLT, GLD, ^VIX, ^MOVE |
| SEC EDGAR | User-Agent with `SEC_CONTACT_EMAIL` | XBRL `NetAssetValuePerShare` (BDC NAV, indexed by filing date); full-text keyword scan |
| Web search (Claude) | Weekly runs | Insurer ratings, Fed actions, fund gates and redemptions, BDC quarterly figures |

**Price conventions.** Price levels (P/NAV, VIX, MOVE) use **raw** closes. Dividend-adjusted closes would understate past BDC prices by every later dividend (about 10% a year). BIZD drawdown, BKLN 1-month, KRE/KBE vs SPY and forced selling use **total-return** (adjusted) closes, so distributions don't count as losses.

---

## 5. Repo layout

```
credit-stress-tracker/
├── RUNBOOK.md                 # step-by-step instructions for the scheduled session
├── ARCHITECTURE.md · README.md · CLAUDE.md
├── .claude/settings.json      # pre-approved commands for unattended runs
├── requirements.txt           # pandas, requests, yfinance, PyYAML, matplotlib, pytest
├── config/
│   ├── signals.yaml           # 29 signals: source, transform, amber/red rule, max_age_days
│   ├── composite.yaml         # composite levels 0–3
│   ├── calendar.yaml          # quarterly reminder dates
│   ├── manual_inputs.yaml     # quarterly BDC/fund figures, judgements, Fed actions (all sourced)
│   └── settings.yaml          # history length, stale limit, EDGAR banks/insurers/keywords, repo_url
├── tracker/
│   ├── sources/  http.py fred.py nyfed.py yahoo.py edgar.py
│   ├── data.py               # DataStore: fetch once, record errors, cache to out/cache.pkl
│   ├── signals.py            # build value series, score, staleness, changes, low-coverage warning
│   ├── rules.py · composite.py · calendar_utils.py
│   ├── history.py            # CSV history, alerts, EDGAR scan history and comparison
│   ├── charts.py             # one small-multiples PNG per stage (matplotlib)
│   ├── render.py             # e-mail HTML, plain text, markdown
│   └── cli.py                # verify | run | finalize | replay
├── data/
│   ├── observations.csv       # one row per signal per run
│   ├── runs.csv               # one row per run (composite, counts, fetch errors)
│   ├── edgar_scan.csv         # keyword × group totals per weekly scan
│   ├── edgar_hits.csv         # filings returned per scan (to find new ones)
│   └── replay.csv             # threshold replay, weekly since Jan 2024
├── reports/<date>.md          # weekly reports with full source links
└── tests/test_rules.py        # 13 tests: rules, transforms, composite, EDGAR history, coverage
```

**History rules.** History is append-only across dates. Re-running `finalize` for the **same as-of date and mode** replaces that run's rows (and that day's EDGAR scan), so a repeated run never duplicates history. Earlier dates are never touched.

---

## 6. Signal engine

Every signal is defined in `config/signals.yaml`. No thresholds appear in code.

- **Rule language:** shorthand `{op, amber, red}`, or full lists of conditions with `gt/lt/ge/le`, `persist: N`, `count: N within: M`, `diff: N`, `rising: N` and `exclude: month_end`.
- **Month-end and quarter-end repo spikes:** the window is the last business day of the month plus the first 2 business days after it. Breaches inside the window are flagged in a note but excluded from the persistence rules. Applies to SOFR–IORB, TGCR–IORB and SRF.
- **Staleness:** each signal has a `max_age_days` (the weekly H.8 series gets 21, the monthly SLOOS 130, and so on). A stale signal shows grey and is excluded from the composite. If more than 25% of signals are stale, `run` exits 2 and the run sends a failure email instead of a misleading report.
- **Stress direction:** each signal knows whether a rise or a fall means more stress, taken from its rule. The email colours change arrows by that direction: ▲▼ red = toward stress, green = away from it.
- **Judgement signals:** `bank_disclosures` and `insurer_ratings` are set weekly by Claude in `manual_inputs.yaml`, with sources. They go stale after 10 days, which forces the weekly review.
- **BDC non-accruals and PIK** (quarterly, `rising` 2 → amber, 3 → red): the value is a simple average of **whichever of ARCC, OBDC, FSK and BXSL have reported**. Each row records `n` and `bdcs`. Fewer than 3 of 4 raises a **low-coverage warning** in the data-issues box, in the plain-text email and in the summary. A quarter's row is updated as more BDCs report.
- **Non-traded funds** are split into two signals: redemption requests above 5% of NAV → amber; gated 1 quarter → amber, 2 or more → red.
- **Composite:** level 3 Systemic funding stress (2+ Stage-4 reds, or VIX, MOVE and HY OAS all red) → level 2 Spreading to banks (2+ Stage-3 reds, or SLOOS red plus a bank-stock red) → level 1 Contained grind (any Stage-1 or Stage-2 amber or worse) → level 0 Calm.
- **Alerts:** a signal turning red (compared with the latest run of any mode) or the composite rising (compared with the last run of the same mode). The daily check sees only Stages 2 and 4, so its composite is compared only with earlier daily runs.

---

## 7. EDGAR keyword scan

- **What it scans:** each weekly run uses EDGAR full-text search over the last 30 days of 10-Q, 10-K and 8-K filings, separately for 18 banks and 9 life/annuity insurers. Keywords: fund finance, NAV loan, nondepository financial, fraud, charge-off, reserve build.
- **What it stores:** keyword totals and the returned filings, saved in `data/edgar_scan.csv` and `data/edgar_hits.csv`.
- **The comparison:** the report shows totals against the **previous scan** (▲▼ change) and lists **new filings**, meaning filings not among the top results of any earlier scan. Claude reads new filings first when it judges `bank_disclosures`.
- **Limitation:** "new" is detected only among the top 10 results per keyword, so it can miss new filings for very common keywords such as "fraud".
- **Baseline and first comparison:** the 2026-11-20 scan is the baseline. The 2026-11-21 test run was the first real comparison: totals vs 20 Nov plus one new filing, a Zions 10-Q exhibit matching only boilerplate "fraud" wording.

---

## 8. Report and email

- **Email body (inline styles only):** Gmail drops `<style>` blocks. The layout is one centred column, 720px wide at most, with fixed table layouts and percentage column widths, so it fits a phone (checked at 390px).
- **Content, top to bottom:**
  - composite level "ladder";
  - "This week" summary;
  - new-red alerts and data issues;
  - four stage tiles with red/amber/green counts;
  - one section per stage: Value, Change (1-week change over 3-month change), Status pill;
  - one chart image per stage: small multiples with shaded amber/red zones, labelled threshold lines, start and end dates, and an end dot in the status colour;
  - Fed actions, the SEC filing keyword scan, coming-up dates, and a "Full report with sources on GitHub" button.
- **Attachments:** the 4 stage PNGs go as inline attachments (`cid:att0..3`). The Gmail connector accepts at most 10 file attachments; per-signal charts (25) failed.
- **No SEC links in the email (owner's choice):** the session's privacy guard refuses to send the owner's address alongside sec.gov links. Notes therefore say "[SEC filing links in the full report]", and `reports/<date>.md` keeps every link.
- **Plain-text and markdown versions** keep Unicode sparklines as a fallback.
- **Subject:** `🔴 ALERT · Credit Stress · <composite> · N red, N amber · <date>`, with `· ⚠ DATA ISSUE` added when signals are stale.

---

## 9. Lessons from the build (keep these in mind when changing things)

| Problem | Cause | Fix |
|---|---|---|
| FRED requests hung | FRED drops unknown custom User-Agents | Standard `requests` UA for non-SEC hosts |
| BDC P/NAV red in all of history | Adjusted closes understate past prices | Raw closes for price levels |
| BIZD showed −19.7% | Price drawdown counts distributions as losses | Total-return drawdown (−9 to −10%) |
| Scheduled run couldn't push (403) | Tasks don't inherit the environment's repo | Repo attached to each scheduled task |
| `pandas` missing in scheduled run | `pip` belonged to Python 3.13, `python` was 3.11 | `python -m pip` everywhere |
| Charts silently missing | System Pillow broken in the cloud image | Reinstall Pillow (setup script and runbook) |
| Gmail rejected the send | More than 10 attachments | 4 stage images |
| Gmail send blocked | Privacy guard: owner address plus sec.gov links | SEC links removed from email bodies only |
| Email zoomed out, centred headers | `<style>` dropped; unbreakable URLs widened a table | Inline styles, fixed column, wrapped short links |
| Stray `claude/*` branch | Scheduled sessions start on their own branch; a git hook nudges them to push it | Runbook and prompts: switch to `main` first, push to `main` only, decline the hook |
| Final reply ended without the status line | A hook-reply became the last message | Status line required as the last line of every reply |

---

## 10. Cost and plan usage

Measured on test runs on 2026-11-20 and 2026-11-21, at list prices. The weekly report runs on Opus 5.5. The daily check runs on **Sonnet 5.5**, which is half the per-token price ($2 / $10 per MTok in/out, $0.10 cache reads).

| Run | API-equivalent | Drivers |
|---|---|---|
| Weekly report (Opus 5.5) | ~$1.65–2.30 (last test $2.03) | Loading context (~50%) and writing out the ~53 KB email (~40%); more when sourcing quarterly BDC figures |
| Daily check (Sonnet 5.5) | ~$0.12–0.13 (Opus was ~$0.26); 3 tests, 43–50 s each | Short run, no email unless alerting |
| **Per week** | **~$2.30–2.95** | **≈ 0.8–1.1% of the Pro weekly limit**, up to ~6% of a 5-hour window on Monday morning |

Effort level matters little here, because thinking is under 10% of output. Plan-usage percentages come from a before/after reading of the Pro usage bars on 2026-11-20: about $3.90 of usage moved the weekly bar by about 1 point, so a week ≈ $270–300 API-equivalent. That reading is rough.

---

## 11. Commands

```bash
python -m tracker verify                      # fetch every source once; non-zero exit if any fails
python -m tracker run --mode weekly           # fetch + score → out/ (no history written)
python -m tracker finalize                    # re-score with manual inputs, render, append history
python -m tracker replay --start 2024-01-05   # score past Fridays → data/replay.csv
python -m pytest -q
```

---

## 12. Open items

- **FSK P/NAV:** it has traded below 0.80× NAV for about half of the replay period, so it may stay red on its own. Keeping the spec threshold for now (owner's choice). Revisit with a per-BDC baseline after a few weeks of data.
- **Quarterly inputs:** BDC non-accruals and PIK, plus fund redemptions and gates, are filled by the weekly run around earnings season. ARCC doesn't break out PIK in its press release, so the 10-Q is needed. Two redemption figures are still marked "verify vs SC TO-I/A".
- **Calendar dates** are approximate. Update `config/calendar.yaml` when official schedules are published (the fall 2026 Fed FSR reminder was removed; the report came out 13 Nov).
- **Replay coverage:** ICE BofA OAS history on FRED covers about 3 years, so the 2020 and 2023 stress episodes can't be replayed for spreads.
- **Sonnet 5.5 (daily task):** three test runs and the first scheduled run (2026-11-21) committed correctly and pushed to `main` only. The latest two tests ended with the status line, and the latest one ran on `main` from the start with no hook nudge. Still untested on Sonnet: an alerting day that sends an email. Check the first one, and switch the task back to Opus in its settings if the email is incomplete.
- **Duplicate test reports:** `reports/2026-11-20.md` and `reports/2026-11-21.md` both come from owner-requested test runs. Monday 23 Nov compares against 21 Nov.
- **Optional:** tune thresholds after 4–6 weeks of history.
