# AURA — Finetuning Guide: Elite Fashion Designer Persona

## Overview

This guide covers how to finetune the LLM that powers AURA's "elite fashion designer" stylist persona.  
The goal is to replace the current Groq-hosted base model with a finetuned model that has deep knowledge of:
- Indian ethnic/contemporary fashion
- Indic multilingual conversation (Telugu/Hindi/English code-mixed)
- Body type → silhouette recommendations
- Fabric expertise (40+ Indian fabrics)
- Regional wedding traditions
- Budget-conscious styling

**Current architecture ensures post-finetune deployment is a one-line config change.**

---

## 1. Model Config Swap

The stylist LLM call reads its model ID from a single config variable:

```python
# services/api/core/config.py
llm_stylist_model: str = "groq/llama-3.3-70b-versatile"
```

**Post-finetune deployment**:
1. Upload your finetuned model to Hugging Face Hub (e.g., `your-org/aura-stylist-v1`)
2. Deploy via vLLM/TGI/Groq custom models
3. Change the env var on Render:
   ```
   LLM_STYLIST_MODEL=groq/your-finetuned-model-id
   ```
4. No code changes needed. The `complete()` function in `services/agent/llm.py` routes based on the model prefix (`groq/`, `ollama/`, etc.).

---

## 2. Dataset Plan

### Structure
Reuse the existing `training/configs/fashion_vlm.yaml` structure. Dataset format: ShareGPT conversations.

### Dataset Composition (recommended mix)

| Category | % of Dataset | Source | Count (target) |
|----------|-------------|--------|----------------|
| Fashion VLM instruction pairs | 30% | `data/processed/fashion_vlm_sharegpt.json` (existing) | ~300 |
| Indic conversational stylist dialogues | 30% | Synthetic generation (GPT-4/Claude → Te/Hi/En code-mixed styling convos) | ~300 |
| Tailoring instruction data | 15% | Manual curation from tailoring guides, measurement tables | ~150 |
| Body type × outfit reasoning | 15% | Synthetic: given measurements → recommend silhouette chains | ~150 |
| Negotiation/argumentation dialogues | 10% | Synthetic: multi-turn back-and-forth where stylist pushes back | ~100 |

### Dataset Format (ShareGPT)

```json
{
  "conversations": [
    {"from": "human", "value": "Naaku wedding ki red lehenga kavali, budget 5000. Naa measurements: chest 90, waist 72, hip 95."},
    {"from": "gpt", "value": "Darling, 5000 budget lo red lehenga dorikindi — kani mee 90cm chest ki A-line silhouette baguntundi..."},
    {"from": "human", "value": "But I want a fitted look..."},
    {"from": "gpt", "value": "Fitted look kosam mermaid cut try cheyandi — kani mee hip:waist ratio ki princess cut more flattering..."}
  ]
}
```

### Data Quality Requirements
- Each conversation must be 3-8 turns (to teach negotiation)
- Responses must reference specific measurements when discussing fit
- Must include at least one "push back" from the stylist per conversation
- Telugu conversations should be natural code-mixed (not formal Telugu)

---

## 3. Training Method: QLoRA via Unsloth

### Base Model
- **Model**: `Qwen/Qwen2.5-VL-7B-Instruct` (or text-only variant for non-vision stylist)
- **Alternative**: `meta-llama/Llama-3.3-8B-Instruct` (lighter, faster training)

### QLoRA Configuration

```yaml
# Matches training/configs/fashion_vlm.yaml
lora:
  rank: 64          # Good balance of capacity vs. training speed
  alpha: 128        # 2x rank is standard
  target_modules:
    - q_proj
    - k_proj
    - v_proj
    - o_proj
    - gate_proj
    - up_proj
    - down_proj
  dropout: 0.05
  bias: none

training:
  learning_rate: 2.0e-4      # Standard for QLoRA
  warmup_ratio: 0.1
  epochs: 3                  # 3 epochs sufficient for ~1000 examples
  per_device_batch_size: 2   # Fits in Colab T4 16GB
  gradient_accumulation_steps: 4  # Effective batch size = 8
  weight_decay: 0.01
  max_grad_norm: 1.0
  fp16: true
  optim: adamw_8bit          # Unsloth-optimized
  lr_scheduler_type: cosine
  max_seq_length: 2048       # Sufficient for multi-turn styling convos
```

### Unsloth Training Script (outline)

```python
from unsloth import FastLanguageModel

model, tokenizer = FastLanguageModel.from_pretrained(
    "Qwen/Qwen2.5-7B-Instruct",
    max_seq_length=2048,
    load_in_4bit=True,
)

model = FastLanguageModel.get_peft_model(
    model,
    r=64, lora_alpha=128,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj", 
                     "gate_proj", "up_proj", "down_proj"],
    lora_dropout=0.05,
)

# Load dataset
from datasets import load_dataset
dataset = load_dataset("json", data_files="data/processed/fashion_vlm_sharegpt.json")

# Train
from trl import SFTTrainer, SFTConfig
trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=dataset["train"],
    args=SFTConfig(
        per_device_train_batch_size=2,
        gradient_accumulation_steps=4,
        num_train_epochs=3,
        learning_rate=2e-4,
        fp16=True,
        output_dir="models/checkpoints/aura-stylist",
    ),
)
trainer.train()

# Save and push
model.save_pretrained_merged("models/aura-stylist-merged", tokenizer)
model.push_to_hub_merged("your-org/aura-stylist-v1", tokenizer)
```

### Hardware Requirements
- **Minimum**: Google Colab T4 Free (16GB VRAM) — ~2 hours for 1000 examples
- **Recommended**: A100 40GB — ~30 minutes for 1000 examples
- **Cost estimate**: Free (Colab) or ~$2 (Lambda/RunPod spot A100)

---

## 4. Evaluation Strategy

### Hold-out Set
- Reserve 10% of dataset as evaluation set (configured in `fashion_vlm.yaml`)
- Track loss convergence per epoch

### Automated Metrics
| Metric | Target | How |
|--------|--------|-----|
| ROUGE-L | > 0.35 | Overlap with reference styling responses |
| BLEU | > 0.20 | N-gram precision for Telugu/Hindi responses |
| Response length | 50-200 words | Ensure concise, actionable advice |

### G-EVAL Fashion Accuracy Check
Use GPT-4 as a judge to score responses on:
1. **Fashion accuracy** (0-5): Are fabric/silhouette/color recommendations correct?
2. **Body type awareness** (0-5): Does response reference measurements and suggest appropriate fits?
3. **Cultural accuracy** (0-5): Are regional traditions and occasions correctly handled?
4. **Negotiation quality** (0-5): Does the model push back intelligently, or just agree?
5. **Language naturalness** (0-5): Is code-mixed Telugu/Hindi natural, not formal?

### Before/After Comparison
```
Test prompt: "Naaku wedding ki outfit kavali, naa height 165cm, chest 90, waist 72, hip 95. Budget 8000. Hyderabad wedding."

Baseline (Groq llama-3.3-70b):     [score responses]
Finetuned (aura-stylist-v1):        [score responses]
```

Run 50 test prompts, compare aggregate scores.

---

## 5. Deployment Checklist

1. [ ] Curate and validate training dataset (1000+ examples)
2. [ ] Run training via Unsloth on Colab/cloud GPU
3. [ ] Evaluate on hold-out set — confirm metrics meet targets
4. [ ] Run G-EVAL comparison against baseline
5. [ ] Push model to HF Hub
6. [ ] Deploy model via Groq Custom Models / vLLM endpoint
7. [ ] Update `LLM_STYLIST_MODEL` env var on Render
8. [ ] Verify: hit `/api/v1/voice/converse` — confirm finetuned responses
9. [ ] Monitor: check Langfuse traces for quality regression

---

## 6. Notes

- The `training/configs/fashion_vlm.yaml` file already has the correct QLoRA config — reuse as-is.
- Existing `data/processed/fashion_vlm_sharegpt.json` has initial training data — expand it.
- The `services/agent/stylist.py` system prompt serves as the "pre-finetune" quality baseline.
- Post-finetune, you can simplify the system prompt since knowledge will be in weights.
