"""PEFT LoRA SFT of Qwen2.5-1.5B-Instruct on the synthetic set (CPU). Loss on assistant tokens only."""
import json, math, random, sys, time
from pathlib import Path
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import LoraConfig, get_peft_model

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from extractor import SYSTEM_PROMPT  # same prompt the production extractor uses

C = json.loads((ROOT / "finetune/config.json").read_text())
torch.manual_seed(C["seed"]); random.seed(C["seed"]); torch.set_num_threads(8)
tok = AutoTokenizer.from_pretrained(C["local_model_dir"])
model = AutoModelForCausalLM.from_pretrained(C["local_model_dir"], torch_dtype=torch.float32)  # fp32 master weights; bf16 only via autocast (pure-bf16 run went NaN)
model.gradient_checkpointing_enable(); model.enable_input_require_grads()
L = C["lora"]
model = get_peft_model(model, LoraConfig(r=L["r"], lora_alpha=L["alpha"], lora_dropout=L["dropout"],
                                         target_modules=L["target_modules"], task_type="CAUSAL_LM"))
for n, p in model.named_parameters():  # trainable LoRA weights in fp32 (bf16 Adam updates went NaN at step 13)
    if p.requires_grad: p.data = p.data.float()
model.print_trainable_parameters()

def encode(row):
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": f"MESSAGE TO EXTRACT:\n\n{row['text']}"}]
    prompt = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    ans = json.dumps(row["target"], ensure_ascii=False) + "<|im_end|>"
    p, a = tok(prompt)["input_ids"], tok(ans)["input_ids"]
    ids = (p + a)[: C["max_len"]]
    return torch.tensor([ids]), torch.tensor([([-100] * len(p) + a)[: C["max_len"]]])

rows = [json.loads(l) for l in (ROOT / C["train_file"]).read_text().splitlines() if l.strip()]
random.shuffle(rows)
out = ROOT / C["output_dir"]; out.mkdir(parents=True, exist_ok=True)
opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=C["lr"])
total = math.ceil(len(rows) * C["epochs"] / C["grad_accum"])
sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / 5) * max(0.0, 1 - s / total))
start = 0
ck = sorted(out.glob("ckpt-*"), key=lambda p: int(p.name.split("-")[1]))
if ck:  # resume
    st = torch.load(ck[-1] / "state.pt"); start = st["step"]
    from peft import set_peft_model_state_dict; from safetensors.torch import load_file
    set_peft_model_state_dict(model, load_file(ck[-1] / "adapter_model.safetensors"))
    opt.load_state_dict(st["opt"]); sched.load_state_dict(st["sched"]); print("resumed at step", start)
model.train(); t0 = time.time(); log = open(out / "train_log.jsonl", "a")
for step in range(start, total):
    acc = 0.0
    for k in range(C["grad_accum"]):
        ids, lab = encode(rows[(step * C["grad_accum"] + k) % len(rows)])
        with torch.autocast("cpu", dtype=getattr(torch, C["dtype"])):
            loss = model(input_ids=ids, labels=lab).loss / C["grad_accum"]
        if not torch.isfinite(loss): print("non-finite loss, skipping micro-batch", flush=True); continue
        loss.backward(); acc += loss.item()
    gn = torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 1.0)
    if not torch.isfinite(gn): print("non-finite grad norm, skipping step", flush=True); opt.zero_grad(); sched.step(); continue
    opt.step(); sched.step(); opt.zero_grad()
    rec = {"step": step + 1, "of": total, "loss": round(acc, 4), "lr": sched.get_last_lr()[0], "elapsed_s": round(time.time() - t0, 1)}
    print(json.dumps(rec), flush=True); log.write(json.dumps(rec) + "\n"); log.flush()
    if (step + 1) % C["checkpoint_every_steps"] == 0 or step + 1 == total:
        d = out / f"ckpt-{step + 1}"; model.save_pretrained(d)
        torch.save({"step": step + 1, "opt": opt.state_dict(), "sched": sched.state_dict()}, d / "state.pt")
model.save_pretrained(out / "final"); print("done")
