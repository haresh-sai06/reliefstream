"""ReliefStream offline evaluation harness.

Measures, on the hand-labelled set in ``eval/labeled_messages.jsonl``:

* extraction field-level precision / recall / F1 (location, urgency,
  request_type, people_count, contact) on messages whose gold label is
  "actionable";
* actionable-vs-not classification (``parseable``) precision / recall / F1;
* deduplication pairwise precision / recall / F1, using the production
  fingerprint from ``backend/storage.py`` on the extracted fields;
* per-message extraction latency (mean / p50 / p95).

Usage (from repo root)::

    # against whatever OpenAI-compatible endpoint backend/.env points to
    python eval/run_eval.py --out eval/results/latest.json

    # deterministic offline smoke test (no LLM; used by CI)
    python eval/run_eval.py --mode gold

Gold labels may be a single value or a list of acceptable values (used for
genuinely ambiguous cases, e.g. "immediate" vs "high"). See eval/README.md.
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from models import ExtractedFields  # noqa: E402

FIELDS = ["location", "urgency", "request_type", "people_count", "contact"]
STOP = {"near", "opposite", "opp", "the", "at", "in", "of", "area", "road", "street", "st"}


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _as_list(v):
    return v if isinstance(v, list) else [v]


def _norm_enum(v):
    return None if v in (None, "unknown") else v


def _norm_contact(v):
    if v is None:
        return None
    s = re.sub(r"[^0-9x]", "", str(v).lower())
    return s or None


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", s.lower()) if t not in STOP}


def location_match(pred: str | None, gold: str | None) -> bool:
    """Gold location is a short key phrase; match if >=50% of its tokens appear in the prediction."""
    if pred is None or gold is None:
        return pred is None and gold is None
    g = _tokens(gold)
    if not g:
        return False
    return len(g & _tokens(pred)) / len(g) >= 0.5


def field_match(field: str, pred, gold) -> bool:
    if field == "location":
        return location_match(pred, gold)
    if field == "contact":
        return _norm_contact(pred) == _norm_contact(gold)
    if field in ("urgency", "request_type"):
        return _norm_enum(pred) == _norm_enum(gold)
    return pred == gold


def score_field(field: str, pred, gold_spec) -> tuple[int, int, int]:
    """Return (tp, fp, fn) for one field of one message."""
    if field in ("urgency", "request_type"):
        pred = _norm_enum(pred)
    golds = _as_list(gold_spec)
    null_ok = any((_norm_enum(g) if field in ("urgency", "request_type") else g) is None for g in golds)
    non_null = [g for g in golds if g is not None]
    if pred is None:
        return (0, 0, 0) if null_ok else (0, 0, 1)
    if any(field_match(field, pred, g) for g in non_null):
        return (1, 0, 0)
    # wrong non-null prediction: a false positive, and a miss if a value was required
    return (0, 1, 0 if null_ok else 1)


def prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(f, 4), "tp": tp, "fp": fp, "fn": fn}


def gold_extractor(row: dict) -> ExtractedFields:
    """Deterministic 'oracle' extractor: returns the first acceptable gold value. Used for CI smoke tests."""
    g = row["gold"]
    first = lambda v: _as_list(v)[0]  # noqa: E731
    p = bool(first(g["parseable"]))
    return ExtractedFields(
        location=first(g["location"]), urgency=first(g["urgency"]) or "unknown",
        request_type=first(g["request_type"]) or "unknown", people_count=first(g["people_count"]),
        contact=first(g["contact"]), confidence=0.9 if p else 0.1, parseable=p,
    )


def evaluate(rows: list[dict], extract_fn) -> dict:
    import storage  # imported lazily so DATABASE_PATH env is irrelevant here

    preds, latencies = [], []
    for row in rows:
        t0 = time.perf_counter()
        ext = extract_fn(row)
        latencies.append(time.perf_counter() - t0)
        preds.append(ext)

    # 1) field extraction on unambiguously actionable messages
    per_field = {f: [0, 0, 0] for f in FIELDS}
    for row, ext in zip(rows, preds):
        if row["gold"]["parseable"] is not True:
            continue
        for f in FIELDS:
            tp, fp, fn = score_field(f, getattr(ext, f), row["gold"][f])
            per_field[f][0] += tp
            per_field[f][1] += fp
            per_field[f][2] += fn
    micro = [sum(v[i] for v in per_field.values()) for i in range(3)]

    # 2) actionable classification (skip rows labelled ambiguous, i.e. list gold)
    ctp = cfp = cfn = ctn = 0
    for row, ext in zip(rows, preds):
        g = row["gold"]["parseable"]
        if isinstance(g, list):
            continue
        if ext.parseable and g:
            ctp += 1
        elif ext.parseable and not g:
            cfp += 1
        elif not ext.parseable and g:
            cfn += 1
        else:
            ctn += 1

    # 3) dedup: pairwise using production fuzzy matcher (location norm + Jaccard)
    fps = [storage._fingerprint(r["text"], e) for r, e in zip(rows, preds)]
    dtp = dfp = dfn = 0
    for i, j in itertools.combinations(range(len(rows)), 2):
        same_gold = rows[i]["cluster"] == rows[j]["cluster"]
        same_pred = storage.is_duplicate_extracted(
            preds[i], preds[j], rows[i]["text"], rows[j]["text"]
        )
        dtp += same_gold and same_pred
        dfp += (not same_gold) and same_pred
        dfn += same_gold and (not same_pred)

    lat_sorted = sorted(latencies)
    p95_idx = max(0, int(round(0.95 * len(lat_sorted))) - 1)
    return {
        "n_messages": len(rows),
        "extraction_micro": prf(*micro),
        "extraction_per_field": {f: prf(*v) for f, v in per_field.items()},
        "actionable_classification": {**prf(ctp, cfp, cfn), "tn": ctn,
                                      "accuracy": round((ctp + ctn) / max(1, ctp + cfp + cfn + ctn), 4)},
        "dedup_pairwise": prf(dtp, dfp, dfn),
        "latency_s": {"mean": round(statistics.mean(latencies), 3),
                      "p50": round(statistics.median(latencies), 3),
                      "p95": round(lat_sorted[p95_idx], 3)},
        "predictions": [{"id": r["id"], "fingerprint": f, **e.model_dump()} for r, e, f in zip(rows, preds, fps)],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "eval" / "labeled_messages.jsonl"))
    ap.add_argument("--mode", choices=["llm", "gold"], default="llm")
    ap.add_argument("--out", default=None, help="write full JSON results here")
    ap.add_argument("--holdout", choices=["none", "dev", "test"], default="none",
                    help="cluster-level split: tune on dev, report test (no cross-pair leakage)")
    args = ap.parse_args()

    rows = load(Path(args.data))
    holdout = getattr(args, "holdout", "none")
    if holdout != "none":
        # Split by cluster id so duplicate pairs never cross the cut.
        clusters = sorted({r["cluster"] for r in rows})
        mid = len(clusters) // 2
        # even index = tune/dev, odd = hold-out test (or vice versa)
        if holdout == "dev":
            keep = set(clusters[:mid])
        else:  # test
            keep = set(clusters[mid:])
        rows = [r for r in rows if r["cluster"] in keep]
    if args.mode == "gold":
        fn = gold_extractor
        meta = {"mode": "gold (oracle extractor, harness smoke test only)", "holdout": holdout, "n_after_split": len(rows)}
    else:
        try:
            from dotenv import load_dotenv
            load_dotenv(ROOT / "backend" / ".env")
        except ImportError:
            pass
        import extractor
        fn = lambda row: extractor.extract(row["text"])  # noqa: E731
        meta = {"mode": "llm", "model": extractor.LLM_MODEL, "base_url": extractor.LLM_BASE_URL, "holdout": holdout, "n_after_split": len(rows)}

    res = {"meta": meta, **evaluate(rows, fn)}
    summary = {k: v for k, v in res.items() if k != "predictions"}
    print(json.dumps(summary, indent=2))
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
