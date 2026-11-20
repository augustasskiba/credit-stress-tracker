# RUNBOOK: scheduled runs

This file is the full instruction set for the scheduled Claude Code cloud session. The scheduled
task's prompt only says which mode to run (`weekly` or `daily`) and points here.

**Rules for every run**
- Never invent numbers. Every manual or judgement value you add needs a source (URL or filing) in its `note` / `source` field.
- Do not change thresholds in `config/signals.yaml` or `config/composite.yaml`. Threshold tuning is the owner's decision.
- Report outcomes honestly. If a step fails, say so in the email and in your final reply.
- This is a monitoring tool. Write nothing that reads as investment advice.

---

## 0. Setup (both modes)

```bash
cd /home/user/credit-stress-tracker 2>/dev/null || true
```

If the repo is not on disk, attach `augustasskiba/credit-stress-tracker` with push access (add_repo tool), clone it to `/home/user/credit-stress-tracker`, and `cd` there.

```bash
git pull --ff-only origin main
pip install -q -r requirements.txt
```

## 1. Score

```bash
python -m tracker run --mode <weekly|daily>
```

- Exit code `2` means more than 25% of signals are stale. Any other non-zero exit is a crash. In either case, send the **failure email** (step 5) with the error output, commit nothing, and stop.
- Read `out/run.json`. Look at `composite`, `alerts`, `fetch_errors`, and the `results` with status `red`, `amber` or `stale`.

## 2. Judgement and news checks (**weekly only**; skip for daily)

Edit `config/manual_inputs.yaml`. Set `as_of` to today's date (YYYY-MM-DD) for each judgement you review.

**a. `judgements.bank_disclosures`.** Read `out/edgar_scan.json`. Open the most relevant hits for "fund finance", "NAV loan", "nondepository financial" and "reserve build" (at most about 6 filings). Ignore boilerplate "fraud" and "charge-off" language unless it is tied to lending to non-bank financials or private credit.
  - `green`: nothing new beyond routine disclosure.
  - `amber`: new or expanded discussion of NBFI, fund-finance or private-credit exposure, or a reserve build attributed to it.
  - `red`: losses, charge-offs or fraud disclosed on NBFI or private-credit exposures.
  - `note`: one line, plus the filing URLs.

**b. `judgements.insurer_ratings`.** Run a web search covering the last 7 days for AM Best, Moody's, S&P and Fitch downgrades or negative outlooks on US life and annuity insurers. Examples: Athene, Corebridge, F&G, Brighthouse, Jackson, Lincoln, Global Atlantic, Security Benefit, and private-equity-owned insurers.
  - `green`: none.
  - `amber`: 1 downgrade.
  - `red`: multiple downgrades.
  - `note`: list each action with its source.

**c. `fed_actions`.** Search for Fed actions in the last 7 days: a new facility, an emergency or intermeeting cut, an SRF or discount-window change, or a coordinated liquidity action. Add each one as `{date, action, source}`. Do not remove older entries.

**d. Quarterly series** (`quarterly.*`). Update these only when you find a cited figure for a quarter that is not yet recorded:
  - `redemption_requests_pct` and `gated_quarters`: news on redemption requests and pro-rating at large non-traded BDCs and interval funds.
  - `nonaccrual_pct` and `pik_pct`: only in weeks when `out/run.json → upcoming` mentions BDC earnings, or when the latest quarter is missing. Use the earnings releases and 10-Qs of ARCC, OBDC, FSK and BXSL. Use the simple average of the four, and list each component in `source`.

## 3. Summary

Write `out/summary.md` with **exactly 3 lines**, in plain English and a neutral tone:
1. The composite reading and what is driving it.
2. What changed since last week. Compare with `reports/` (the latest earlier file) or `data/observations.csv`.
3. What to watch next, such as signals near a threshold or upcoming releases.

For **daily** runs, write a summary only if `alerts` is non-empty: 1–3 lines explaining the alert.

## 4. Finalise

```bash
python -m tracker finalize
```

This re-scores with your manual inputs, recomputes alerts, renders `out/email.json`, appends to `data/*.csv` and, for weekly runs, writes `reports/<date>.md`.

## 5. E-mail (Gmail connector)

Read `out/email.json`.
- If `should_send` is true, call **Gmail `send_message`** with:
  - `to`: the owner's own address (the account e-mail in your context)
  - `subject`: `subject`
  - `htmlBody`: `html`
  - `body`: `text`
- Weekly runs always send. Daily runs send only when there is an alert.
- **Failure email**: subject `⚠ Credit Stress Tracker run FAILED · <date>`, with the error output and the list of stale signals in the body.

## 6. Commit history

```bash
git add data/ reports/ config/manual_inputs.yaml
git commit -m "<weekly|daily> run <date>: <composite name>, <n> red / <n> amber"
git push origin main
```

Retry the push up to 4 times with backoff. If it is rejected because main moved, run `git pull --rebase origin main` and push again.

## 7. Final reply

End with one line: mode, composite, red/amber counts, whether the email was sent, and the commit hash.
