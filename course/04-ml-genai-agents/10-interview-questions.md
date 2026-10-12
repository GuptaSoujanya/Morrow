# 10. Interview Question Drill — 60+ Q&A

This file is pure revision: short, direct, senior-level answers across every topic in this
track. Use it the night before an interview. If any answer feels unfamiliar, go back to the
corresponding file for the full explanation.

---

## Section A: ML Fundamentals (15 questions)

**A1. What's the difference between bias and variance?**
Bias is error from a model being too simple to capture the true pattern (underfitting).
Variance is error from a model being too sensitive to the specific training data, capturing
noise rather than signal (overfitting). Total error = bias² + variance + irreducible noise.

**A2. Why is accuracy a bad metric for imbalanced classification?**
A model that always predicts the majority class can score very high accuracy while being
useless — e.g., 99% accuracy on a dataset that's 99% negative by always predicting negative.
Use precision, recall, F1, or PR-AUC instead, and inspect the confusion matrix directly.

**A3. Define precision and recall, and give a scenario where you'd prioritize each.**
Precision = TP/(TP+FP): of what you flagged positive, how much was correct. Recall =
TP/(TP+FN): of all actual positives, how much did you catch. Prioritize precision when false
positives are costly (spam filter blocking important email). Prioritize recall when false
negatives are costly (missing a fraud case or a cancer diagnosis).

**A4. What is k-fold cross-validation and why use it over a single train/test split?**
Split training data into k folds, train on k-1 and validate on the remaining fold, rotate
which fold is held out, and average the validation metric across all k rounds. This gives a
more robust performance estimate than one fixed split, which can be lucky or unlucky
depending on how the data happened to split.

**A5. What is regularization and name two common types.**
A penalty added to the loss function to discourage overly complex models and reduce
overfitting. L1 (Lasso) drives weights to exactly zero (sparse, built-in feature selection).
L2 (Ridge) shrinks weights smoothly toward zero without eliminating them.

**A6. Why must you fit feature scaling only on the training set, not the full dataset?**
Fitting scaling (or any transformation) on the full dataset including test data leaks
information about the test distribution into training, making validation metrics overly
optimistic and unrepresentative of real-world performance (data leakage).

**A7. Explain the difference between bagging and boosting.**
Bagging (Random Forest) trains many trees independently and in parallel on bootstrapped
samples, then averages predictions — reduces variance. Boosting (XGBoost/LightGBM) trains
trees sequentially, each correcting the previous ones' errors — reduces bias, but is more
prone to overfitting and needs more careful tuning.

**A8. What is the elbow method used for?**
Choosing k in k-means clustering: plot within-cluster sum of squares against k and look for
the point where improvement sharply flattens.

**A9. What's the difference between L1 and L2 regularization in terms of the resulting
model?**
L1 produces sparse models (many weights exactly zero) — effectively feature selection. L2
shrinks all weights smoothly but keeps them nonzero — keeps all features with reduced
influence.

**A10. How do you handle missing data in a feature column?**
Mean/median/mode imputation, model-based imputation, or adding a "was missing" indicator
flag so the model can learn from missingness itself. Choice depends on how much data is
missing and whether missingness itself is informative.

**A11. Why don't tree-based models need feature scaling?**
Trees split on thresholds (e.g., "is x > 5?"), not on distances or dot products, so the
absolute scale of a feature doesn't affect how splits are chosen. Models using distance or
gradients (k-means, linear regression, neural nets) do need scaling.

**A12. What's the difference between validation set and test set?**
Validation set is used repeatedly during development to tune hyperparameters and select
models — you make decisions based on it, so it's not fully "unseen." Test set is touched
only once at the very end to report final unbiased performance; using it to make any
decisions invalidates it as a fair test.

**A13. What is overfitting and name three ways to fix it.**
The model performs well on training data but poorly on new data because it memorized noise
rather than general patterns. Fixes: get more data, simplify the model/add regularization,
use cross-validation for hyperparameter tuning, use early stopping, or use ensembling.

**A14. When would you choose logistic regression over a more complex model?**
When you need interpretability (weights map to log-odds/feature importance), a fast and
simple baseline, limited training data, or when the relationship between features and the
target is genuinely close to linear/log-linear — also useful as a sanity-check baseline
before trying more complex models.

**A15. What does R² measure in regression, and what does an R² of 0 mean?**
R² is the proportion of variance in the target explained by the model. An R² of 0 means the
model performs no better than simply predicting the mean of the target for every example; an
R² of 1 means a perfect fit.

---

## Section B: Deep Learning (10 questions)

**B1. Why do neural networks need non-linear activation functions?**
Stacking linear layers without non-linearity collapses into a single linear transformation
regardless of depth — no extra expressive power is gained. Non-linear activations (ReLU,
GELU) let the network model complex, non-linear relationships.

**B2. Explain backpropagation in one sentence.**
It computes the gradient of the loss with respect to every weight using the chain rule,
propagating backward from the output layer to the input layer, so an optimizer can update
weights to reduce the loss.

**B3. What's the vanishing gradient problem and how is it addressed?**
In deep networks, gradients can shrink toward zero as they're multiplied backward through
many layers, stalling learning in early layers. Addressed with better weight initialization,
batch/layer normalization, residual/skip connections, and non-saturating activations like
ReLU/GELU.

**B4. What is dropout and why does it help generalization?**
Randomly deactivating a fraction of neurons during each training step, preventing the
network from over-relying on specific neurons — approximates training an ensemble of
sub-networks. Disabled at inference time.

**B5. Compare SGD and Adam as optimizers.**
SGD updates weights using the gradient (optionally with momentum) at a given learning rate
applied uniformly. Adam adapts the effective learning rate per parameter using running
averages of gradients and squared gradients, converging faster and being less sensitive to
the initial learning rate — the default choice for training transformers (as AdamW).

**B6. Why were RNNs/LSTMs largely replaced by transformers?**
RNNs process sequences step by step (no parallelism across time) and struggle with
long-range dependencies despite LSTM gating. Transformers process all positions in parallel
via self-attention and handle long-range dependencies much better, making them faster to
train and more accurate on long sequences.

**B7. What problem do LSTM gates solve?**
They control what information is kept, forgotten, or output at each time step, letting
useful information persist over long sequences — solving the vanishing-gradient-driven
"forgetting" problem of vanilla RNNs.

**B8. What is an embedding?**
A dense vector representation of a discrete object (word, token, user, item) learned so that
semantically similar objects end up close together in vector space, replacing sparse
one-hot representations.

**B9. What is batch normalization and what does it do?**
Normalizes layer activations within each mini-batch during training, stabilizing and
speeding up training and providing a mild regularizing effect.

**B10. What is the universal approximation theorem, in plain terms?**
A large enough neural network with non-linear activations can approximate essentially any
function mapping inputs to outputs, given enough data and training — the theoretical basis
for why deep learning can model such a wide variety of complex problems.

---

## Section C: LLMs and Transformers (15 questions)

**C1. Explain self-attention in plain English.**
Every token creates a Query (what it's looking for), a Key (what it offers), and a Value
(the content it carries). Attention scores come from comparing each token's Query against
every other token's Key; softmax turns these into weights summing to 1, which are then used
to blend all tokens' Values — giving each token an updated representation informed by
relevant context anywhere in the sequence.

**C2. Why scale attention scores by √d_k?**
Without scaling, dot products grow large as the key dimension increases, pushing softmax
into a very peaked regime with tiny gradients. Dividing by √d_k keeps scores in a stable
range for better gradient flow.

**C3. What is multi-head attention and why use multiple heads?**
Running attention several times in parallel with separately learned Q/K/V projections, so
different heads can specialize in different relationship types (e.g., syntax, coreference,
local order). Outputs are concatenated and projected back to the model dimension.

**C4. What do residual connections do in a transformer block?**
Add the input of a sub-layer back to its output, letting gradients flow directly through the
network during backprop — enabling very deep stacks of layers without vanishing gradients.

**C5. Why do transformers need positional encoding?**
Self-attention treats input as an unordered set — it has no inherent sense of sequence
order. Positional encodings (absolute embeddings, RoPE, ALiBi) inject order information so
the model knows which token came first.

**C6. Compare encoder-only, decoder-only, and encoder-decoder architectures.**
Encoder-only (BERT): bidirectional attention, good for classification/embeddings. Decoder-
only (GPT, Llama, Claude-style chat models): causal/masked attention, generates text one
token at a time — the dominant architecture for modern general-purpose LLMs. Encoder-decoder
(T5, original Transformer): bidirectional encoder plus causal decoder with cross-attention,
good for translation/summarization.

**C7. What is causal masking and why is it needed in decoder-only models?**
It prevents a token from attending to future tokens during training, so the model can't
"cheat" by peeking ahead when learning to predict the next token — essential for the
next-token-prediction training objective to be meaningful.

**C8. Describe the three-stage LLM training pipeline.**
(1) Pretraining: self-supervised next-token prediction on massive text corpora — teaches
grammar, facts, reasoning. (2) Supervised fine-tuning/instruction tuning: train on curated
(instruction, response) pairs to produce assistant-like behavior. (3) Preference alignment
(RLHF or DPO): align outputs to human preferences for helpfulness and safety.

**C9. Compare RLHF and DPO.**
RLHF trains a separate reward model from human preference rankings, then uses RL (typically
PPO) to optimize the LLM against it, with a KL penalty to limit drift. DPO skips the reward
model and RL loop, directly optimizing the LLM on (chosen, rejected) pairs with a
classification-style loss. DPO is simpler and more stable to train, which is why it's widely
adopted as a cheaper alternative or complement to RLHF.

**C10. What do scaling laws tell us about model size vs. data size?**
For a fixed compute budget, there's an optimal balance between model size and training data
size — many earlier large models were undertrained relative to their parameter count, so
more training tokens often help more than just adding parameters ("Chinchilla-optimal").

**C11. What is the KV cache and why is it important for inference?**
During generation, each new token's attention needs the Key/Value vectors of all previous
tokens. The KV cache stores these once computed, avoiding recomputation — the dominant
reason autoregressive generation can be fast, though cache memory is often the real
bottleneck limiting concurrent requests on a server.

**C12. What is Mixture-of-Experts (MoE) and why use it?**
Instead of one dense feed-forward network per layer, MoE uses multiple expert sub-networks
with a router selecting only a few per token. This increases total model capacity/parameters
without proportionally increasing per-token compute, at the cost of more complex training
and higher total memory requirements.

**C13. What is quantization and what's the tradeoff?**
Reducing weight/activation precision (e.g., from 16-bit to 4-bit) to shrink memory footprint
and speed up inference, at a small, usually acceptable, accuracy cost. Techniques include
GPTQ, AWQ, and bitsandbytes.

**C14. Explain speculative decoding.**
A small draft model quickly proposes several candidate next tokens; the large target model
verifies all of them in one parallel pass, accepting matches and rejecting the rest. Since
verifying several tokens in parallel is nearly as cheap as generating one, this speeds up
generation (often 2-3x) with identical output quality to normal decoding.

**C15. Why doesn't a huge context window eliminate the need for RAG?**
Cost and latency still scale with token count even with large windows; models can suffer
"lost in the middle" effects where relevant info gets less attention than content near the
start/end; and retrieving only relevant chunks is typically cheaper and often more accurate
than processing an entire corpus in context on every request.

---

## Section D: RAG and Agents (15 questions)

**D1. Walk through the full RAG pipeline end to end.**
Offline: chunk documents, embed each chunk, store in a vector database. Online: embed the
user query, retrieve candidates via hybrid (dense + sparse) search, rerank with a
cross-encoder, build a prompt from the top chunks plus the query, and generate a grounded
answer with citations.

**D2. Why use hybrid search instead of pure vector search?**
Pure vector/semantic search can miss exact keyword matches (SKUs, names, rare terms) that
don't embed distinctly. Hybrid search combines dense (semantic) and sparse (keyword/BM25)
retrieval, typically merged via reciprocal rank fusion, to catch both match types.

**D3. Why rerank after initial retrieval instead of just retrieving fewer, more precise
results directly?**
Cross-encoder rerankers are far more accurate (they process query and document jointly) but
too slow to run against an entire corpus since they can't be precomputed/indexed. Fast
approximate retrieval narrows the field first; the expensive reranker then gets precision
only on a small final shortlist.

**D4. What is HyDE and why can it improve retrieval?**
Hypothetical Document Embeddings: instead of embedding the raw question, the LLM first
generates a plausible hypothetical answer, and that is embedded for retrieval. This helps
when the question and real documents use different vocabulary/style — the hypothetical
answer tends to be phrased more like the actual source documents.

**D5. When would you use Graph RAG over standard vector RAG?**
When answering requires multi-hop reasoning connecting facts across different documents via
explicit relationships (e.g., "which vendors of Company A were also flagged in an audit?"),
which pure semantic chunk retrieval struggles with since no single chunk contains the full
answer.

**D6. What's the difference between faithfulness and answer relevance in RAG evaluation?**
Faithfulness checks whether every claim in the answer is supported by the retrieved context
(no hallucination beyond it). Answer relevance checks whether the answer actually addresses
the user's question, independent of faithfulness — an answer can be faithful to irrelevant
context while failing to address the actual question.

**D7. Explain the ReAct loop.**
The model alternates: Thought (reason about what to do), Action (call a tool), Observation
(see the result), repeating until it has enough information to give a Final Answer. This
grounds the model in real information and lets it course-correct based on observations
rather than committing to assumptions upfront.

**D8. What's the difference between short-term and long-term agent memory?**
Short-term memory is the current session's context window — thoughts/actions/observations
within the active task, lost when the session ends. Long-term memory persists across
sessions (user preferences, past facts) and is typically stored externally (vector DB or
structured DB) and explicitly read/written by the agent.

**D9. Describe the orchestrator-worker multi-agent pattern and when to use it.**
A central orchestrator decomposes a task into subtasks and dispatches them to specialized
worker agents, then combines results — useful for tasks that decompose into independent or
parallelizable pieces. Only worth the added coordination complexity and multiplied LLM calls
when the task genuinely benefits from specialization or parallelism.

**D10. What problem does the Model Context Protocol (MCP) solve?**
It standardizes how LLM applications connect to external tools/data sources, so a tool
provider (MCP server) can be built once and used by any MCP-compatible agent framework
(MCP client), decoupling tool implementation from agent framework — similar to how LSP
decoupled editors from language-specific tooling.

**D11. Compare LangGraph, CrewAI, and OpenAI Agents SDK at a high level.**
LangGraph uses an explicit state graph for fine-grained control over complex/cyclic flows —
best for production systems needing precise control. CrewAI uses role-based agent "crews" —
best for quick multi-agent prototyping. OpenAI Agents SDK offers lightweight agent/handoff/
guardrail primitives with built-in tracing — best for teams wanting a minimal, provider-
native framework.

**D12. What's the most reliable guardrail for an agent that can take irreversible actions?**
Human-in-the-loop approval before execution — the agent proposes the action, but a human
must explicitly approve it before it runs, since no current guardrail technique (schema
validation, step limits, least-privilege tools) guarantees the model is correct 100% of the
time.

**D13. What is indirect prompt injection?**
Adversarial instructions embedded in content the model processes as data (a retrieved
document, web page, tool output) rather than typed directly by the user — e.g., hidden text
in a retrieved page saying "ignore previous instructions." Defended against via clear
delimiters marking untrusted content, least-privilege tool access, and output validation.

**D14. Why should multi-agent systems not be the default architecture choice?**
A single well-prompted agent with good tools is simpler to build, debug, and reason about.
Multi-agent systems add real coordination complexity (shared state, failure propagation,
multiplied LLM call cost) that should be justified by a concrete benefit like genuine task
parallelism or adversarial checking, not used by default.

**D15. What's the key tradeoff of agentic RAG versus single-pass RAG?**
Agentic RAG lets the model iteratively retrieve, reformulate queries, and self-critique
before finalizing an answer, handling complex multi-step questions far better. The cost is
more LLM calls and retrieval rounds (latency, cost) plus added engineering complexity to
control the loop and prevent runaway iteration.

---

## Section E: Scenario and System Design (10 questions)

**E1. A stakeholder asks "why not just fine-tune the model on our documents instead of
building RAG?" How do you respond?**
Fine-tuning bakes knowledge into weights at training time — expensive and slow to update
whenever documents change, and doesn't reliably add precise factual recall for data it
wasn't heavily exposed to. RAG retrieves fresh, exact content from a vector database at
query time, which is cheap and fast to update (just re-ingest changed docs), and lets the
model cite its sources. Fine-tuning is better suited for teaching style, behavior, or
response format, not injecting frequently-changing factual knowledge.

**E2. Your RAG chatbot gives a wrong answer. Walk through your debugging process.**
First check whether the relevant chunk was retrieved at all — inspect the top-k results for
that query. If the relevant content is missing from retrieval, no prompting fix will help;
improve chunking, embedding model choice, or hybrid search/reranking. If the relevant chunk
was retrieved but the model ignored it or hallucinated beyond it, that's a
generation/faithfulness issue — improve prompt instructions requiring grounding and
citations, or check for a weaker model struggling to use the context correctly.

**E3. How would you design the candidate generation and ranking stages of a recommendation
system?**
Candidate generation uses cheap approximate methods (embedding similarity/ANN search,
popularity heuristics) to narrow millions of items to a few hundred candidates. Ranking
applies a more expensive, accurate model (gradient boosting or a deep ranking model with
rich features) to precisely score and order just those candidates — this two-stage funnel
is necessary because running an expensive model against the full catalog per request is too
slow.

**E4. Why would a fraud detection system use a three-tier decision (allow/review/block)
instead of a single binary threshold?**
A binary threshold forces ambiguous cases into either a false positive (blocking a
legitimate customer) or false negative (missing fraud). A middle review-queue tier routes
genuinely uncertain cases to human judgment, reserving automatic decisions for
high-confidence cases in either direction — better matching the real business cost asymmetry
between error types.

**E5. How would you evaluate whether a prompt change improved your production LLM
application before fully rolling it out?**
Run the new prompt against a golden dataset with both automated checks and LLM-as-judge
scoring to catch obvious regressions offline. If it passes, do a staged/canary rollout to a
small percentage of real traffic, tracking a primary business metric (task completion,
satisfaction) alongside guardrail metrics (latency, cost, safety violations) with proper
statistical rigor, before expanding to full traffic.

**E6. A user pastes a 50-page document into your chatbot and complains it's slow and
expensive. What do you explain and what do you suggest?**
Cost and latency scale with token count, and most of a 50-page document is likely irrelevant
to the specific question — plus very long contexts can suffer "lost in the middle" effects.
I'd suggest switching to a RAG approach: chunk and embed the document once, then retrieve
only the relevant chunks per question, which is typically cheaper, faster, and often more
accurate than stuffing the whole document into context every time.

**E7. How would you design guardrails for an AI agent platform that can take real-world
actions (sending emails, processing refunds)?**
Enforce least-privilege tool access scoped per task type, require human-in-the-loop approval
for irreversible/high-cost actions before execution, enforce hard platform-level limits on
steps/cost/time (not just prompt suggestions), validate all tool call arguments against
schemas before executing, and maintain full tracing of every thought/action/observation for
debugging and audit.

**E8. When would you choose LoRA/QLoRA fine-tuning over full fine-tuning?**
Almost always, unless you're a large lab building a new foundation model from scratch. LoRA/
QLoRA need far less GPU memory, carry lower catastrophic forgetting risk, and let you cheaply
swap multiple task-specific adapters on top of one shared frozen base model — full
fine-tuning is rarely justified given these advantages for typical customization tasks.

**E9. How would you design a search ranking system differently for news content versus a
static product catalog?**
News needs near-real-time index updates (incremental indexing, minutes-level freshness) and
ranking features that weight recency heavily. A product catalog can use a slower index
rebuild cadence (hourly/daily) and lean more on stable signals like historical engagement,
reviews, and popularity rather than recency.

**E10. What's your framework for deciding between prompt engineering, RAG, and fine-tuning
for a new LLM feature request?**
Start with prompt engineering — cheapest and fastest to iterate, good for formatting/tone/
instruction-following issues. Add RAG when the task needs fresh or private factual knowledge
the model wasn't trained on, since updating a vector DB is far cheaper than retraining.
Reach for fine-tuning only after validating that prompting/RAG genuinely can't achieve the
needed behavior consistently — typically for teaching a new skill, enforcing a very specific
structured output style at scale, or reducing per-request cost/latency by baking behavior
into weights instead of a long prompt. These are often combined, not mutually exclusive.

---

## Final Tips for Interview Day

- Always clarify requirements before diving into a system design answer — scale, latency
  budget, and cost constraints change the right architecture significantly.
- When asked "why" questions (why RAG, why LoRA, why this metric), always name the specific
  tradeoff you're making, not just the benefit — interviewers are testing judgment, not
  memorized facts.
- For any GenAI system, defense-in-depth (multiple guardrail layers, not one magic fix) is
  the expected framing for safety/injection/hallucination questions — no single technique is
  presented as a complete solution in a strong answer.
- Connect concepts across files where relevant: the same "cheap filter, then expensive
  precise step" pattern appears in RAG reranking, recommendation ranking, and search ranking
  — naming this pattern explicitly signals senior-level pattern recognition, not just
  memorized definitions.
