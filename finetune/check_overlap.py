"""Near-duplicate / leakage check: synthetic TRAIN set vs the 41-message TEST set."""
import json, re, sys
from pathlib import Path
from rapidfuzz import fuzz

ROOT = Path(__file__).resolve().parents[1]
test = [json.loads(l) for l in (ROOT / "eval/labeled_messages.jsonl").read_text().splitlines() if l.strip()]
train = [json.loads(l) for l in (ROOT / "finetune/data/train_synth.jsonl").read_text().splitlines() if l.strip()]
tok = lambda s: set(re.findall(r"\w+", s.lower()))
ng = lambda s, n=5: {s.lower()[i:i + n] for i in range(len(s) - n + 1)}

best = []
for t in train:
    m = max(test, key=lambda x: fuzz.token_set_ratio(t["text"], x["text"]))
    j = max(len(tok(t["text"]) & tok(x["text"])) / len(tok(t["text"]) | tok(x["text"])) for x in test)
    best.append((fuzz.token_set_ratio(t["text"], m["text"]), j, t["id"], m["id"]))
best.sort(reverse=True)
exact = sum(t["text"].strip().lower() in {x["text"].strip().lower() for x in test} for t in train)
near = [b for b in best if b[0] >= 80 or b[1] >= 0.5]
# place-name / contact leakage: test locations & phone numbers appearing in train
test_locs = {str(v).lower() for x in test for v in (x["gold"]["location"] if isinstance(x["gold"]["location"], list) else [x["gold"]["location"]]) if v}
test_phones = {re.sub(r"\D", "", p) for x in test for p in re.findall(r"[\d\-X]{10,}", x["text"]) if len(re.sub(r"\D", "", p)) >= 5}
STOP = {"street", "road", "main", "cross", "near", "opposite", "nagar", "colony", "4th", "2nd", "3rd", "8th", "1st", "6th", "temple", "college", "community", "hall", "bus", "stand", "last", "stop", "house", "ward", "school"}
test_place_tokens = {w for l in test_locs for w in re.findall(r"[a-z]+", l) if w not in STOP and len(w) > 3}
loc_leak = [(t["id"], w) for t in train for w in tok(t["text"]) if w in test_place_tokens]
phone_leak = [t["id"] for t in train if t["target"]["contact"] and re.sub(r"\D", "", t["target"]["contact"]) in test_phones]
rep = {"n_train": len(train), "n_test": len(test), "exact_duplicates": exact,
       "near_duplicates(token_set_ratio>=80 or jaccard>=0.5)": len(near),
       "max_token_set_ratio": best[0][0], "max_jaccard": round(max(b[1] for b in best), 3),
       "closest_pair": {"train": best[0][2], "test": best[0][3]},
       "test_place_tokens_checked": sorted(test_place_tokens), "train_rows_with_test_place_token": len(loc_leak),
       "train_rows_with_test_phone": len(phone_leak)}
print(json.dumps(rep, indent=2))
(ROOT / "finetune/results").mkdir(exist_ok=True)
(ROOT / "finetune/results/overlap_check.json").write_text(json.dumps(rep, indent=2))
sys.exit(1 if exact or near or loc_leak or phone_leak else 0)
