# RUNBOOK: scheduled runs

This file is the full instruction set for the scheduled Claude Code cloud session. The scheduled
task's prompt says which mode to run and points here.

| Task | When (Europe/London) | Model | Email |
|---|---|---|---|
| Weekly report | Mon 10:05 | Opus 5.5 | Always |
| Daily red-alert check | Tue–Sat 07:07 | Sonnet 5.5 | Only on a new red signal or a composite rise |

**Rules for every run**
- Never invent numbers. Every manual or judgement value you add needs a source (URL or filing) in its `note` / `source` field.
- Do not change thresholds in `config/signals.yaml` or `config/composite.yaml`. Threshold tuning is the owner's decision.
- Report outcomes honestly. If a step fails, say so in the email and in your final reply.
- This is a monitoring tool. Write nothing that reads as investment advice.
- Push to `main` only, and end your final reply with the status line (step 7).
- Never work around a safety or privacy guard that refuses a tool call. Use the fallback this runbook gives and report it.

---

## 0. Setup (both modes)

```bash
cd /home/user/credit-stress-tracker 2>/dev/null || true
```

If the repo is not on disk, attach `augustasskiba/credit-stress-tracker` with push access (add_repo tool), clone it to `/home/user/credit-stress-tracker`, and `cd` there.

The session usually starts on an auto-named `claude/*` branch. Work on `main` instead, so the commit in step 6 lands there:

```bash
git fetch origin main && git checkout -B main origin/main
python -m pip install -q -r requirements.txt   # not bare `pip`: it can belong to a different Python than `python`
python -m pip install -q --ignore-installed pillow   # the cloud image's system Pillow is broken; without this the charts silently drop out
```

## 1. Score

```bash
python -m tracker run --mode <weekly|daily>
```

- Exit code `2` means more than 25% of signals are stale. Any other non-zero exit is a crash. In either case, send the **failure email** (step 5) with the error output, commit nothing, and stop.
- Read `out/run.json`. If `run`/`finalize` printed `warning: chart rendering failed`, the email will go out with text sparklines only; mention it in the final reply. Look at `composite`, `alerts`, `fetch_errors`, and the `results` with status `red`, `amber` or `stale`.

## 2. Judgement and news checks (**weekly only**; skip for daily)

Edit `config/manual_inputs.yaml`. Set `as_of` to today's date (YYYY-MM-DD) for each judgement you review.

**a. `judgements.bank_disclosures`.** Read `out/edgar_scan.json`, and in `out/run.json` look at `edgar_scan` → `new_items` (filings not seen in any earlier scan) first. Open the most relevant hits for "fund finance", "NAV loan", "nondepository financial" and "reserve build" (at most about 6 filings). Ignore boilerplate "fraud" and "charge-off" language unless it is tied to lending to non-bank financials or private credit.
  - `green`: nothing new beyond routine disclosure.
  - `amber`: new or expanded discussion of NBFI, fund-finance or private-credit exposure, or a reserve build attributed to it.
  - `red`: losses, charge-offs or fraud disclosed on NBFI or private-credit exposures.
  - `note`: one line, plus the filing URLs.

**b. `judgements.insurer_ratings`.** Run a web search covering the last 7 days for AM Best, Moody's, S&P and Fitch downgrades or negative outlooks on US life and annuity insurers. Examples: Athene, Corebridge, F&G, Brighthouse, Jackson, Lincoln, Global Atlantic, Security Benefit, and private-equity-owned insurers.
  - `green`: none.
  - `amber`: 1 downgrade.
  - `red`: multiple downgrades.
  - `note`: list each action with its date and source.
  - Count only actions dated in the last 7 days. An older action that no earlier weekly note recorded may be counted once; say so in the note. Do not count an action already recorded in an earlier week.

**c. `fed_actions`.** Search for Fed actions in the last 7 days: a new facility, an emergency or intermeeting cut, an SRF or discount-window change, or a coordinated liquidity action. Add each one as `{date, action, source}`. Do not remove older entries.

**d. Quarterly series** (`quarterly.*`). Update these only when you find a cited figure for a quarter that is not yet recorded:
  - `redemption_requests_pct` and `gated_quarters`: news on redemption requests and pro-rating at large non-traded BDCs and interval funds.
  - `nonaccrual_pct` and `pik_pct`: only in weeks when `out/run.json → upcoming` mentions BDC earnings, or when the latest quarter is missing. Use the earnings releases and 10-Qs of ARCC, OBDC, FSK and BXSL. Use the simple average of **whichever of the four have reported** (each value cited), and record `n` (how many) and `bdcs` (which) on the row, e.g. `{date: 2026-09-30, value: 2.4, n: 1, bdcs: [ARCC], source: "..."}`. When more BDCs report later, update that quarter's row instead of adding a new one. If `n` is below 3, the report flags low coverage; also say so in the summary's third line.

**e. Calendar.** If an item in `out/run.json → upcoming` has already happened (for example a report that was already published), remove it from `config/calendar.yaml` and mention that in the final reply.

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

This re-scores with your manual inputs, recomputes alerts, renders `out/email.json` and the 4 chart PNGs, appends to `data/*.csv`, stores the EDGAR scan for next week's comparison, and, for weekly runs, writes `reports/<date>.md`.

You can re-run `finalize` safely, for example after fixing the summary: it replaces that day's rows instead of adding duplicates. Check `out/email.json → subject` and the summary before sending.

## 5. E-mail (Gmail connector)

Read `out/email.json`.
- If `should_send` is true, call **Gmail `send_message`** with:
  - `to`: the owner's own address (the account e-mail in your context)
  - `subject`: `subject`
  - `htmlBody`: `html`
  - `body`: `text`
  - `attachments`: the `attachments` array from `out/email.json`, copied exactly and **in the same order**. These are the inline trend-chart PNGs: the HTML refers to them as `cid:att0`, `cid:att1`, … by position, and each `content` is a file reference the app fills in. If sending with attachments fails, send again without them; the text sparklines in `text` still go out.
- Weekly runs always send. Daily runs send only when there is an alert.
- Send the HTML exactly as rendered. The code has already removed SEC links from the email body (the owner's choice, because a privacy guard refuses Gmail sends with them); do not add filing links to the subject or body. The repo report keeps them.
- **Failure email**: subject `⚠ Credit Stress Tracker run FAILED · <date>`, with the error output and the list of stale signals in the body.

**Fallback if the Gmail tool is not available** (no `mcp__Gmail__send_message` in this session), or if sending fails or is refused by a guard:
open a GitHub issue on the repo, and GitHub will e-mail the owner.

```bash
gh api repos/augustasskiba/credit-stress-tracker/issues -f title="<subject>" -F body=@out/report.md   # REST only; gh GraphQL is blocked here
```

Use `reports/<date>.md` or the failure text as the body. Say in the final reply that the issue fallback was used instead of Gmail.

## 6. Commit history

```bash
git add data/ reports/ config/manual_inputs.yaml config/calendar.yaml
git commit -m "<weekly|daily> run <date>: <composite name>, <n> red / <n> amber"
git push origin main
```

Push to `main` only. Do not create or push any other branch, even if the session started on one. A git hook may say the session branch has no remote copy and suggest pushing it: decline, briefly say why, and end that reply with the status line. Retry the push up to 4 times with backoff. If it is rejected because main moved, run `git pull --rebase origin main` and push again.

## 7. Final reply

The **last line of your final reply** must be this status line, in both modes, every run, in exactly this shape:

```
<weekly|daily> · <composite name> · <n> red / <n> amber · email <sent|not sent (no alerts)|FAILED: reason> · commit <hash>
```

Example: `daily · Contained grind · 1 red / 1 amber · email not sent (no alerts) · commit f89b2ad`

Put any other notes (warnings, skipped steps, a hook or tool message you answered) **above** it. If you reply again after the run, for example to answer a hook, end that reply with the status line too.
