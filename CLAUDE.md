# Credit Stress Tracker

A personal monitor of whether private-credit stress is spreading into banks and funding markets.
It is a monitoring tool, not investment advice.

- **Scheduled runs:** follow `RUNBOOK.md` exactly. A weekly report goes out Mon 10:05 Europe/London; a daily red-alert check runs Tue–Sat.
- **Design:** see `ARCHITECTURE.md`. Thresholds live in `config/*.yaml` and must never be hard-coded.
- **Code:** in `tracker/`. Entry point is `python -m tracker {verify|run|finalize|replay}`.
- **History:** append-only CSVs in `data/`, plus weekly markdown reports in `reports/`. Never rewrite past rows.
- **Tests:** `python -m pytest -q`. Run them after any change to `tracker/`.
- **SEC requests:** the User-Agent contact comes from the `SEC_CONTACT_EMAIL` env var. Never commit an email address.
- **FRED:** rejects custom User-Agents. Keep the requests default for non-SEC hosts.
- **Yahoo:** raw closes are used for price levels (P/NAV, VIX/MOVE). Dividend-adjusted closes are used for BIZD drawdown, returns and relative performance.
