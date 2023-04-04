# EXPERT: EXtremely Parameter Efficient loRa Tuning. 

TL;DR: It's possible to train your own **expert** model with a single 24G GPU in a few hours.

About: Generalist models (pre-trained or instruction-tuned) are great, but most of them are closed, requiring access to your data and difficult to tweak with limited resources. In this project, we focus on a specialist model and show that it is possible to train it with affordable resources in terms of compute and time, while achieving expert-level performance on a specific task. Simply speaking, we directly tune the quantized strong LLM on task data in a parameter-efficient manner. As a concrete example, tuning LLaMA-33B-4bit with LoRA on PubMedQA training data leads to 75.6% accuracy on test data, which is better than GPT-4 to some extent, while only a single 24G GPU and 3 hours are needed.

Notes: LLaMA-33B is leveraged in this project, which is not fully open-sourced yet.

Special Thanks: this document is generated with the help of ChatGPT.

## Table of Contents

- [Roadmap](#roadmap)
- [Preparation](#preparation)
- [PubMedQA](#pubmedqa)
- [MMLU](#mmlu)

## Roadmap

## Preparation
Experiments are based on the code from [alpaca_lora_4bit](https://github.com/johnsmith0031/alpaca_lora_4bit), with modifications for specific tasks.

## PubMedQA

- [ ] Add more details: how to prepare prompt (and response)

### Single 24G GPU: 500 samples 10 epochs in 3 hours
```
CUDA_VISIBLE_DEVICES=0 python finetune.py pubmedqa_train.json \ 
    --ds_type gpt4all --lora_out_dir PATH_TO_SAVE_LORA \
    --llama_q4_config_dir PATH_TO_LLAMA_DIR \ 
    --llama_q4_model PATH_TO_LLAMA_WEIGHT \
    --val_set_size 0.0 --grad_chckpt --mbatch_size 2 --cutoff_len 512 \ 
    --warmup_steps 10 --save_steps 10 --save_total_limit 10 --epochs 10 \ 
    --batch_size 50 --lr 1e-4 
```

### Comparisons: reasoning-required setting
| Model                                | Accuracy (%) | F1 (%) | Size      |
| -------------------------------------|--------------| -------|-----------|
| GPT-3.5 + Z-Code++                   | 79.6         | 55.8   | 175B      |
| Flan-PALM (3-shot)                   | 79.0         | ----   | 540B      |
| Codex (5-shot)                       | 78.2         | ----   | 175B      |
| Human Performance                    | 78.0         | 72.2   | ----      |
| Galactica (0-shot)                   | 77.6         | ----   | 120B      |
| **LLaMA-33B-4bit (tuned with LoRA)** | 75.6         | 54.1   | 33B + 20M |
| GPT-4 (0-shot)                       | 75.2         | ----   | ----      |
| GPT-4 (5-shot)                       | 74.4         | ----   | ----      |
| PubMedGPT                            | 74.4         | ----   | 2.7B      |
| DRAGON                               | 73.4         | ----   | 360M      |

Notes: 
1. There are some advanced techniques used in GPT-3.5 + Z-Code++ and Codex (5-shot) like CoT and Voting.
2. It's interesting to see Galactica (0-shot) perform so well, and GPT-4 (0-shot) is better than GPT-4 (5-shot).
3. There's some problem with F1 score, as it's averaged over three classes 'yes', 'no' and 'maybe'. As we can see from pubmedqa_preds.json, LLM only get 1 of 55 samples in "maybe" right. 
4. PubMedGPT and DRAGON respresent full-training of small specialist models. 
5. LLaMA-33B-4bit (tuned with LoRA) requires fewer resources while achieving higher accuracy than small specialist models and large generalist models.

## MMLU

### Comparisons: 5-shot test accuracy (%)
| Model              | Humanities  | STEM        | Social Sciences | Other        | Average     |
|--------------------|-------------|-------------|-----------------|--------------|-------------|
| GPT-NeoX           | 29.8        | 34.9        | 33.7            | 37.7         | 33.6        |
| LLaMA-13B          | 45.0        | 35.8        | 53.8            | 53.3         | 46.9        |
| LLaMA-33B          | 55.8        | 46.0        | 66.7            | 63.4         | 57.8        |
| **LLaMA-33B-4bit** | 62.0 (+6.2) | 44.9 (-1.1) | 64.1 (-2.6)     | 58.6 (-4.8)  | 56.2 (-1.6) |
| LLaMA-65B          | 61.8        | 51.7        | 72.9            | 67.4         | 63.4        |
| LLaMA-I-65B        | 67.4        | 56.6        | 79.2            | 72.6         | 68.9 (+5.5) |

Notes: 
1. Since LLaMA-33B-4bit is quantized (by open-source implementation of GPTQ) and the generation setting is far from optimal, the performance drop from LLaMA-33B reported is reasonable.
2. LLaMA-I-65B is the instruction-tuned version of LLaMA-65B, which is not available to the community.
3. Attempts have been made to evaluate Alpaca-33B-4bit (tuned with LoRA then quantized by GPTQ) under the same setting, but the average accuracy drops to 53.5%. Possible reasons are: not doing the evaluation right, LoRA or PEFT in general is not as good as full tuning, etc. Also, instrunction tuning is not trivial.
4. Fully open-sourced pre-trained models (like GPT-NeoX-20B) are still far behind in terms of performance, scale is not the only issue (as LLaMA-13B performs better). Despite recent efforts in instruction tuning, it seems no quantitative evaluation is available. Curious about how these generalist models perform.
5. To put this into context, GPT-3.5 achieves 70.0% (LLaMA-I-65B is close) and GPT-4 achieves 86.4%. 

### Detailed results: LLaMA-33B-4bit model
![detailed results of llama-33b-4bit](mmlu.png)
