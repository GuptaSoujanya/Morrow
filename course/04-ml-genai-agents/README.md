# Track 4: ML + Generative AI — Interview Track

This track takes you from core machine learning foundations to the latest generative AI
engineering practices used in 2025-2026: large language models, retrieval-augmented
generation, autonomous agents, evaluation harnesses, and fine-tuning/LLMOps. It is written
for an experienced engineer (10-12 years) who already knows software systems well but needs
senior-level depth in ML/GenAI for interviews.

Each file is self-contained, uses plain language, includes diagrams (Mermaid) and tables
where they help, and ends with practice questions and answers.

## How to use this track

- Read files in order if you are starting from zero. If you already know classic ML, jump
  straight to file 03 and onward.
- Every file ends with a "Practice Questions" section. Try to answer before reading the given
  answer.
- File 10 is a pure interview drill: 60+ question/answer pairs across all topics, meant for
  final revision the night before an interview.

## Roadmap and file index

| # | File | What it covers | Level |
|---|------|-----------------|-------|
| 01 | [01-ml-fundamentals.md](01-ml-fundamentals.md) | Supervised/unsupervised learning, bias-variance tradeoff, regularization, evaluation metrics (precision/recall/F1/AUC), feature engineering, classic algorithms (linear/logistic regression, decision trees, ensembles, k-means), train/val/test splits, cross-validation | Basic |
| 02 | [02-deep-learning.md](02-deep-learning.md) | Neural networks, backpropagation intuition, CNNs, RNNs/LSTMs, optimizers (SGD, Adam), overfitting remedies, embeddings | Basic → Intermediate |
| 03 | [03-transformers-and-llms.md](03-transformers-and-llms.md) | Self-attention, transformer architecture, tokenization, pretraining vs instruction tuning vs RLHF/DPO, scaling laws, context windows, KV cache, inference optimization (quantization, speculative decoding) | Intermediate → Advanced |
| 04 | [04-prompt-engineering.md](04-prompt-engineering.md) | Zero/few-shot prompting, chain-of-thought, structured outputs/JSON mode, function calling, system prompts, prompt injection and defenses | Intermediate |
| 05 | [05-rag.md](05-rag.md) | Full RAG pipeline: chunking, embeddings, vector databases, hybrid search, reranking; advanced RAG: query rewriting, HyDE, graph RAG, agentic RAG; evaluation (faithfulness, recall) | Advanced |
| 06 | [06-agents-and-tool-use.md](06-agents-and-tool-use.md) | ReAct loop, tool/function calling, planning, short/long-term memory, multi-agent patterns, Model Context Protocol (MCP), agent framework comparison (LangGraph, CrewAI, OpenAI Agents SDK), failure modes and guardrails | Advanced |
| 07 | [07-evaluation-and-harness.md](07-evaluation-and-harness.md) | Eval harnesses (LLM-as-judge, golden datasets, regression evals), benchmarks, A/B testing, observability/tracing, red-teaming, hallucination measurement | Advanced |
| 08 | [08-fine-tuning-and-llmops.md](08-fine-tuning-and-llmops.md) | Full fine-tune vs LoRA/QLoRA vs PEFT, dataset prep, when to fine-tune vs RAG vs prompt, serving (vLLM), cost optimization, LLMOps lifecycle, safety/alignment basics | Advanced |
| 09 | [09-ml-system-design.md](09-ml-system-design.md) | System design: recommendation system, fraud detection, search ranking, production RAG chatbot, AI agent platform — each with architecture diagram and trade-offs | Advanced |
| 10 | [10-interview-questions.md](10-interview-questions.md) | 60+ Q&A across ML fundamentals (15), deep learning (10), LLM/transformers (15), RAG/agents (15), scenario/system design (10) | All levels |

## Suggested study path

```mermaid
flowchart LR
    A[01 ML Fundamentals] --> B[02 Deep Learning]
    B --> C[03 Transformers & LLMs]
    C --> D[04 Prompt Engineering]
    D --> E[05 RAG]
    E --> F[06 Agents & Tool Use]
    F --> G[07 Evaluation & Harness]
    G --> H[08 Fine-Tuning & LLMOps]
    H --> I[09 ML System Design]
    I --> J[10 Interview Drill: 60+ Q&A]
```

## What "2025-2026 current" means in this track

Model families referenced generically throughout (not tied to one vendor): GPT-4/5-class
models, Claude, Llama, Gemini, Mistral. Techniques treated as current practice: Direct
Preference Optimization (DPO) alongside RLHF, Mixture-of-Experts (MoE) architectures,
native multimodal models (text + image + audio), long context windows (100K-1M+ tokens),
agentic RAG, and the Model Context Protocol (MCP) for standardizing tool access across
agent frameworks.

## A note on depth

This is an interview prep track, not a research paper. Explanations favor intuition and
"what would you say in an interview" framing over exhaustive math. Where math matters
(e.g., attention formula, precision/recall), it is given exactly, but always followed by a
plain-English explanation.
