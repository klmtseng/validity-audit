# Domain pack: quantitative research

This is the original pack — the full checklist (leakage / universe bias / arithmetic &
protocol bugs / statistical power / backtest realism) lives in the main
[`../README.md`](../README.md) Stage 1, with
[`../protocol/leak_audit_template.py`](../protocol/leak_audit_template.py) as a runnable
starting point.

Defaults unless specified otherwise:
- Null = label-shuffled empirical score, not 1/n (class imbalance pushes null above 1/n).
- Headline numbers need a pure-OOS (lockbox) segment; no train+OOS blends.
- Returns: confirm log vs. simple before compounding; never mix.
- CI: ddof=1; small n uses t; multi-seed on one return path is pseudo-replication —
  block-bootstrap the return series instead.
- When builder and reviewer disagree, truth = what the code outputs, not seniority.
- Retraction is the default outcome, not the exception.
