# 90-day learning plan: High-Level System Design + ML/AI + Generative AI

Goal: go from basics to advanced (senior / "pro" interview level) in **3 months**, with **2 hours every day**.

Every day has the same shape:

| Block | Time | What |
|-------|------|------|
| 1. System Design (HLD) | 55 min | read the day's notes, draw the diagram yourself, do the estimation |
| 2. ML / GenAI | 55 min | read the notes, run or write the small code exercise |
| 3. Recall | 10 min | answer the self-check questions without looking, write 3 lines in your notes |

Day 7 of every week is a **revision + mini project** day instead of new material.

## How to use it

- Today's file: `python3 -m pipeline learn` writes `daily/<date>.md` and `today.md` here, cut from the week files below.
  The day number counts from the start date in `progress.json` (created on the first run).
- Read the whole plan: `weeks/week-01.md` ... `weeks/week-13.md`.
- Mark a day finished: `python3 -m pipeline learn --done` (the next run moves on even if you skip a calendar day).
- Deeper material already in this repository: the `course/` site (`cd course && python3 serve.py 8000`).
  The week files link to its chapters wherever one covers the topic.

## Syllabus

| Week | Days | System Design (HLD) | ML / AI / GenAI |
|------|------|---------------------|-----------------|
| 1 | 1-7 | Foundations: client-server, DNS, HTTP/TLS, latency numbers, back-of-envelope estimation, vertical vs horizontal scaling, load balancers | Python for ML: NumPy, pandas, linear algebra, probability and statistics essentials |
| 2 | 8-14 | Storage: SQL vs NoSQL, indexes (B-tree, LSM), replication, partitioning/sharding, consistent hashing, transactions and isolation levels | ML fundamentals: supervised vs unsupervised, linear and logistic regression, gradient descent, loss functions, bias-variance, metrics (precision/recall/F1/AUC) |
| 3 | 15-21 | Caching (strategies, eviction, invalidation), CDN, message queues, Kafka, pub/sub, async jobs, rate limiting | Classic ML: decision trees, random forest, gradient boosting/XGBoost, SVM, k-means, PCA, feature engineering, cross-validation |
| 4 | 22-28 | API design (REST, gRPC, GraphQL), idempotency, pagination, API gateway, microservices, service discovery. Cases: URL shortener, pastebin | Deep learning: perceptron, backprop, PyTorch basics, optimizers (SGD/Adam), regularization, CNN basics |
| 5 | 29-35 | Distributed systems: consensus (Raft), leader election, quorum, 2PC vs saga, clocks (Lamport/vector), gossip, CAP/PACELC in depth | Sequences and NLP: tokenization (BPE), embeddings, word2vec, RNN/LSTM, the attention idea |
| 6 | 36-42 | Reliability and observability: SLI/SLO/error budgets, retries with backoff, circuit breakers, backpressure, metrics/logs/traces, deploy strategies. Cases: rate limiter, notification system | Transformers: self-attention math, multi-head, positional encodings, encoder/decoder, build a mini GPT (nanoGPT style) |
| 7 | 43-49 | Case studies 1: news feed, chat system (WhatsApp), typeahead/autocomplete, web crawler, distributed key-value store | LLMs: pretraining, scaling laws, decoding (greedy, top-k, top-p, temperature), KV cache, context windows, MoE, reasoning models |
| 8 | 50-56 | Case studies 2: video streaming (YouTube), ride matching (Uber, geospatial indexes), file sync (Google Drive), payment system | Prompt engineering, structured outputs, function/tool calling, LLM APIs; RAG basics: chunking, embeddings, vector search (HNSW, IVF) |
| 9 | 57-63 | Search and data: inverted index and search engine, analytics pipelines, stream processing (Flink/Kafka Streams), data lake/warehouse, ad-click aggregation | Advanced RAG: hybrid search, reranking, query rewriting, GraphRAG, RAG evaluation (RAGAS); agents: ReAct, tool use, MCP, multi-agent patterns |
| 10 | 64-70 | AI system design 1: LLM serving at scale, inference gateway (LiteLLM-style routing, prompt caching, cost tracking), RAG platform, vector database design | Evaluation: LLM-as-judge and its biases, judge councils, benchmarks, eval harnesses, red teaming, safety and guardrails |
| 11 | 71-77 | AI/ML system design 2: recommendation system, feature store, training pipeline, online evaluation and A/B testing, agent evaluation platform | Fine-tuning: SFT, LoRA/QLoRA, RLHF, DPO, GRPO, distillation, quantization; LLMOps: vLLM serving, monitoring, drift |
| 12 | 78-84 | Interview mastery: the HLD framework drilled on 6 timed problems, trade-off vocabulary, how to lead the interview | Production GenAI and the frontier: multimodal, long context, agentic coding, guardrails, cost/latency optimisation, reading papers |
| 13 | 85-90 | Capstone: design an end-to-end AI product (spec, HLD, deep dives) + 2 full mock HLD interviews | Capstone: build and evaluate a small RAG + agent app, write it up; final mock ML/GenAI interview |

## Format of a day (the week files follow this exactly)

```
## Day N: <short title>

**System Design: <topic>** (55 min)
...notes, diagram (mermaid), estimation...

**ML / GenAI: <topic>** (55 min)
...notes, small code exercise...

**Recall** (10 min)
- question
- question

**Go deeper**
- links
```
