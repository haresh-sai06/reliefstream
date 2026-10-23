"""Score base prompt-only vs base+LoRA with the SAME harness (eval/run_eval.py) on the 41-message test set.

Both variants run in the same runtime (HF transformers, bf16, CPU, greedy decoding, same SYSTEM_PROMPT, same
post-validation in backend/extractor.py). Only the LoRA adapter differs. The test set is read-only here.
Usage: python finetune/eval_hf.py --variant base|lora [--adapter DIR] --out finetune/results/X.json
"""
import argparse, json, sys, time
from pathlib import Path
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend")); sys.path.insert(0, str(ROOT / "eval"))
import extractor, run_eval  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--variant", choices=["base", "lora"], required=True)
ap.add_argument("--adapter", default=str(ROOT / "finetune/out/lora-qwen2.5-1.5b/final"))
ap.add_argument("--out", required=True)
a = ap.parse_args()
C = json.loads((ROOT / "finetune/config.json").read_text())
torch.set_num_threads(8)
tok = AutoTokenizer.from_pretrained(C["local_model_dir"])
model = AutoModelForCausalLM.from_pretrained(C["local_model_dir"], torch_dtype=torch.bfloat16)
if a.variant == "lora":
    from peft import PeftModel
    model = PeftModel.from_pretrained(model, a.adapter).merge_and_unload()
model.eval()
raw_outputs = []

class _Msg:  # mimic the OpenAI response object extractor.extract() expects
    def __init__(s, c): s.message = type("M", (), {"content": c})()

class _Completions:
    def create(self, model=None, messages=None, max_tokens=400, **_):
        ids = tok.apply_chat_template(messages, add_generation_prompt=True, return_tensors="pt")
        with torch.no_grad():
            out = globals()["model"].generate(ids, max_new_tokens=max_tokens, do_sample=False)
        text = tok.decode(out[0, ids.shape[1]:], skip_special_tokens=True)
        raw_outputs.append(text)
        return type("R", (), {"choices": [_Msg(text)]})()

extractor._client = type("C", (), {"chat": type("Ch", (), {"completions": _Completions()})()})()
rows = run_eval.load(ROOT / "eval/labeled_messages.jsonl")
extractor.extract("warmup message: 2 people stuck at Tambaram")  # not scored
raw_outputs.clear()
res = run_eval.evaluate(rows, lambda r: extractor.extract(r["text"]))
valid = 0
for t in raw_outputs:
    try: json.loads(extractor._clean_json(t)); valid += 1
    except Exception: pass
res = {"meta": {"variant": a.variant, "model": C["base_model"], "runtime": "transformers bf16 CPU greedy",
                "adapter": a.adapter if a.variant == "lora" else None}, "json_validity_rate": round(valid / len(raw_outputs), 4), **res,
       "raw_outputs": raw_outputs}
Path(a.out).parent.mkdir(parents=True, exist_ok=True)
Path(a.out).write_text(json.dumps(res, indent=2, ensure_ascii=False))
print(json.dumps({k: v for k, v in res.items() if k not in ("predictions", "raw_outputs")}, indent=2))
