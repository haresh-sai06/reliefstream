# LoRA fine-tune for extraction (Qwen2.5-0.5B-Instruct)

## Method
- **Test set (never trained or tuned on):** `eval/labeled_messages.jsonl`, 41 messages, scored with the unchanged `evaluate()` from `eval/run_eval.py`.
- **Training set:** `data/train_synth.jsonl`: 600 synthetic messages from `gen_synthetic.py` (templates plus random slots; English and Tamil-English mix; forwards, RTs, lowercase and other noise; 20% non-actionable negatives). Places are Chennai, Madurai, Tirunelveli, Kerala and Assam localities, never the Coimbatore areas in the test set. **Labels come from the template slots** that generated each message, not from the test set.
- **Leakage check** (`check_overlap.py`, output in `results/overlap_check.json`): 0 exact duplicates and **0 near-duplicates** (rapidfuzz token-set ≥80 or Jaccard ≥0.5; max token-set 77, max Jaccard 0.44). 0 training rows contain a test-set place token, and 0 contain a test-set phone number.
- **Training** (`train_lora.py`, `config.json`): PEFT LoRA with r=16, α=32 and dropout 0.05 on q/k/v/o. 1 epoch, lr 2e-4, effective batch 8 (75 steps), loss computed only on the assistant JSON, same system prompt as `backend/extractor.py`. Weights in fp32 with bf16 autocast, on an 8-core CPU, about 22 minutes, with a checkpoint every 15 steps. 3 of the 75 steps were skipped by a non-finite-gradient guard. The adapter (8.3 MB) is in `adapter/`.
- **Eval** (`eval_hf.py`): the base model and base+LoRA run in the same runtime (transformers, CPU, greedy decoding) with the same prompt and the same post-validation from `extractor.py`. The only difference is the adapter.

## Results (41-message test set)
| | Qwen2.5-0.5B prompt-only | Qwen2.5-0.5B + LoRA |
|---|---|---|
| Extraction micro-F1 | 0.703 (P 0.877 / R 0.587) | **0.921** (P 0.961 / R 0.884) |
| location F1 | 0.711 | 0.875 |
| urgency F1 | 0.773 | 0.958 |
| request_type F1 | 0.844 | 0.958 |
| people_count F1 | 0.261 | 0.872 |
| contact F1 | 0.720 | 0.938 |
| JSON validity | 97.6% | 100% |
| Actionable-classification F1 | 0.766 | 0.939 |
| Dedup pairwise F1 | 0.842 | 0.952 |
| Latency mean / p50 / p95 (s) | 4.89 / 3.88 / 8.24 | 2.95 / 2.76 / 3.98 |

For reference only, since it ran in a different runtime: Qwen2.5-1.5B Q4_K_M prompt-only via llama.cpp scores micro-F1 0.901 (`eval/results/summary.json`). That number is not directly comparable to the table.

## Limitations
- The test set is small (41 messages, labelled by the author), so a single message moves F1 by about 1 point. No confidence intervals are reported.
- The synthetic templates follow the label guide in the system prompt, so part of the gain comes from learning the output conventions (people_count, how much of the location to keep). The test set was not used for this.
- LoRA latency is lower mostly because its outputs are shorter and more consistent. Latency was measured on a shared CPU box with transformers, not llama.cpp.
- I tried 1.5B first. Pure-bf16 LoRA went to NaN in two runs, and the fp32 1.5B run was OOM-killed on this 15 GB box. So I used 0.5B and measured its own prompt-only baseline. A 1.5B LoRA (on a GPU) is still to do.
- The adapter hasn't been converted to GGUF or wired into the llama.cpp serving path.

## Reproduce
```bash
python finetune/gen_synthetic.py 600 13 && python finetune/check_overlap.py
python finetune/train_lora.py            # resumes from the latest checkpoint
python finetune/eval_hf.py --variant base --out finetune/results/qwen0.5b_base.json
python finetune/eval_hf.py --variant lora --adapter finetune/adapter --out finetune/results/qwen0.5b_lora.json
```
