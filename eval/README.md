# ReliefStream evaluation harness

## Dataset

`labeled_messages.jsonl` — 41 hand-labelled messages (29 unique incidents + 10 near-duplicate forwards + 2 hard-negative near-misses). Gold fields may be a single value or a list of acceptable alternatives for genuinely ambiguous cases.

## Metrics

| Metric | Definition |
|---|---|
| Extraction micro-F1 | Field-level P/R/F1 over `location`, `urgency`, `request_type`, `people_count`, `contact` on messages whose gold `parseable` is strictly `true`. Location match = ≥50% of gold tokens appear in the prediction. |
| Actionable classification | P/R/F1 of `parseable` (rows with list-valued gold are skipped). |
| Dedup pairwise | Over all message pairs: same `cluster` ⇒ should share fingerprint. Uses production `_fingerprint` from `backend/storage.py`. |
| Latency | Wall-clock seconds per `extractor.extract` call (mean / p50 / p95). |

## Run

```bash
# CI smoke (no LLM) — oracle extractor, checks the scorer
python eval/run_eval.py --mode gold

# Against whatever OpenAI-compatible endpoint backend/.env points at
python eval/run_eval.py --out eval/results/latest.json
```

## Measured (this PR)

See [`results/summary.json`](results/summary.json). Model: **Qwen2.5-1.5B-Instruct Q4_K_M** via `llama-server` (OpenAI-compatible at `localhost:11434`). Hardware: CPU-only box. Larger models (qwen2.5:7b / Groq llama-3.3-70b) are expected to improve location/dedup recall — re-run and replace the summary to update the README table.
