# Tech radar

As of 2026-10 (researched 2026-10-22). Written for a software engineer in India working on GenAI/agent evaluation and LLM harnesses (Python/FastAPI, Next.js) who is also learning HLD and ML/GenAI.

How to read this: rings are my judgement for this reader, not a neutral industry ranking.
- Adopt: learn it properly and put it on the resume; interviewers will ask.
- Trial: build one small project with it.
- Assess: read about it, know the trade-off, do not build yet.
- Hold: do not start new work on it, or know why it is on the way out.

Source caveat. Model-release dates and prices come from third-party trackers (linked per item) and several comparison articles are SEO or AI-written pages. Where a claim is vendor-run or tracker-only I say so. Check the vendor page before quoting a number in an interview or resume.

---

## Adopt

### Model Context Protocol (MCP), spec 2026-07-28
- What: the standard for connecting agents to tools and data. The 2026-07-28 revision makes the protocol stateless: no `initialize` handshake, no `Mcp-Session-Id`, every request carries its own version and capabilities, `server/discover` replaces the handshake, `Mcp-Method`/`Mcp-Name` headers allow gateway routing, list results carry `ttlMs`/`cacheScope`, and Tasks moved into an official extension. Roots, Sampling and Logging are deprecated; HTTP+SSE transport and Dynamic Client Registration are deprecated in favour of Streamable HTTP and Client ID Metadata Documents.
- Why it matters to you: it is the default answer to "how does the agent get tools" in 2026. Statelessness also makes it a clean HLD topic: any request can hit any instance behind a round-robin load balancer, so state moves into explicit handles passed as tool arguments. Your harness work should speak MCP on both sides (client and server).
- Governance: MCP sits in the Agentic AI Foundation (Linux Foundation), launched 2025-12-09 with MCP, goose and AGENTS.md.
- [Link](https://blog.modelcontextprotocol.io/posts/2026-07-28/)

### Provider-native agent harnesses: Claude Agent SDK and OpenAI Agents SDK
- What: SDKs that give you the agent loop, tools, MCP, hooks/guardrails, sessions and sub-agents. Per a 16 Oct 2026 comparison, OpenAI Agents SDK was at 0.24.0 and Claude Agent SDK (Python) at 0.2.168. Claude Agent SDK is Claude-only; OpenAI's adapters for other providers are described as best-effort/beta.
- Why it matters: you build and evaluate harnesses. These are the two harnesses your target employers (Anthropic, OpenAI and their customers) run in production, so knowing their hook/permission/handoff models is directly interview-relevant.
- [Link](https://arize.com/ai-agents/agent-frameworks/)

### LangGraph 1.x for durable, stateful workflows
- What: graph orchestration with checkpointing (Postgres/SQLite) and human-in-the-loop interrupts. LangGraph 1.2.x and LangChain 1.4.x as of mid-Oct 2026.
- Why it matters: the most commonly named framework in Indian job descriptions for agentic workflows; it is the provider-agnostic option, so it pairs with a Claude/OpenAI-native harness as a contrast in design discussions.
- Link: [https://dbggr.dev/articles/agent-frameworks-compared/](https://dbggr.dev/articles/agent-frameworks-compared/) (AI-written comparison; versions dated 16 Oct 2026, cross-check on PyPI)

### Agent evaluation fundamentals (Anthropic's vocabulary)
- What: task, trial, grader, transcript, outcome, eval harness vs agent harness; capability evals (start low, a hill to climb) vs regression evals (near 100%); prefer deterministic graders, use LLM judges where needed and calibrate them to humans; grade what the agent produced, not the exact path; isolate each trial in a clean environment.
- Why it matters: this is your core domain. Using the same vocabulary as the labs in interviews is a cheap signal.
- [Link](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)

### vLLM for self-hosted serving
- What: the default open-source inference engine (PagedAttention, continuous batching, prefix caching). Commercialised as Inferact ($150M seed at $800M valuation, Jan 2026). Netflix chose vLLM under Triton for its in-house LLM serving.
- Why it matters: HLD interviews for GenAI platforms ask about KV cache, batching, TTFT vs TPOT, and p95/p99. Be able to explain these without notes.
- Links: [https://techcrunch.com/2026/01/22/inference-startup-inferact-lands-150m-to-commercialize-vllm/](https://techcrunch.com/2026/01/22/inference-startup-inferact-lands-150m-to-commercialize-vllm/) and [https://www.infoq.com/news/2026/07/netflix-llm-platform/](https://www.infoq.com/news/2026/07/netflix-llm-platform/)

### pgvector as the default vector store
- What: Postgres extension (HNSW, `halfvec`). One comparison reports 8-25 ms p95 at 2M vectors and says it tops out around 10M vectors without significant tuning. Single blog benchmarks, so treat as indicative.
- Why it matters: you already run FastAPI + Postgres. Start here; it also gives transactional consistency between rows and embeddings, a good HLD talking point.
- [Link](https://alexcloudstar.com/blog/vector-database-comparison-2026/)

### OpenTelemetry GenAI semantic conventions + tracing
- What: `gen_ai.*` attributes, `invoke_agent` / `chat` / `execute_tool` spans, token and duration metrics. Still marked experimental (opt-in via `OTEL_SEMCONV_STABILITY_OPT_IN`). LiteLLM Proxy's OTel v2 emits these. MCP also documents OTel trace-context propagation in `_meta`.
- Why it matters: eval and observability are the same data. Traces are the input to online evals.
- [Link](https://opentelemetry.io/blog/2026/genai-observability/)

### Prompt caching
- What: provider-side caching of long static prefixes. Anthropic reportedly cut cache-read prices to $0.25/M on Fable 5.1 (tracker, Sep 2026); MCP now requires deterministic `tools/list` ordering to keep cache hits stable.
- Why it matters: cost and latency design for agents (large system prompt + tools + growing history). Expect "how would you cut the bill" questions.
- [Link](https://docs.litellm.ai/docs/completion/prompt_caching)

---

## Trial

### SGLang
- What: inference engine with RadixAttention (prefix reuse), strong on disaggregated prefill/decode. Commercialised as RadixArk ($100M seed, $400M post-money, May 2026). Independent comparisons say vLLM and SGLang are within roughly 10-15% on dense models; the winner depends on prefix sharing and hardware.
- Why it matters: Sarvam's inference-performance job post names SGLang, vLLM, NVIDIA Dynamo and TensorRT-LLM as the engines you must read at source level.
- [Link](https://developers.redhat.com/articles/2026/10/14/vllm-vs-sglang-choosing-the-right-inference-engine-for-your-workload)

### Pydantic AI 2.x
- What: typed Python agent framework with provider swap by string and durable execution via Temporal, DBOS, Prefect and others. Stable V2 since June 2026 per the 16 Oct comparison.
- Why it matters: fits a Python/FastAPI/Pydantic stack naturally. Good for a small portfolio project that is not LangChain.
- [Link](https://dbggr.dev/articles/agent-frameworks-compared/)

### Durable execution for agents (Temporal, DBOS, Restate)
- What: agents as event-sourced workflows that survive crashes, deploys and multi-day human waits. Temporal published an agent harness and a sandbox orchestration harness in 2026; PostHog describes running cloud agents on Temporal with Postgres as the system of record.
- Why it matters: the cleanest "system design for agents" story: retries, idempotency (Activities are at-least-once), human approval via signals, replay for cheap prompt experiments.
- Links: [https://temporal.io/blog/temporal-agent-harness-durable-agent-infrastructure](https://temporal.io/blog/temporal-agent-harness-durable-agent-infrastructure) and [https://posthog.com/blog/cloud-agents-runtime](https://posthog.com/blog/cloud-agents-runtime)

### Eval and observability platforms: Langfuse, Arize Phoenix, Braintrust, LangSmith
- What: Langfuse (MIT core) was acquired by ClickHouse on 2026-01-16 and stays open source; Arize Phoenix is OTel-native (Elastic License 2.0); Braintrust raised an $80M Series B (Feb 2026) and stays independent; LangSmith is the LangChain-ecosystem choice. Helicone moved to maintenance mode after Mintlify acquired it (Mar 2026).
- Why it matters: pick one open-source (Langfuse or Phoenix) and one hosted (Braintrust or LangSmith) and be able to compare them on trajectory-level evals, online scoring and CI gating.
- Links: [https://arize.com/resources/llm-and-agent-evaluation-platforms/](https://arize.com/resources/llm-and-agent-evaluation-platforms/) and [https://clickhouse.com/blog/clickhouse-raises-400-million-series-d-acquires-langfuse-launches-postgres](https://clickhouse.com/blog/clickhouse-raises-400-million-series-d-acquires-langfuse-launches-postgres)

### Inspect AI (UK AISI) for sandboxed agent evals
- What: MIT-licensed framework with 200+ pre-built evals, Docker/Kubernetes/Modal sandboxes, agent bridge for external agents such as Claude Code or Codex CLI. Offline only; pair with a platform for production scoring.
- Why it matters: closest open-source analogue to lab-grade agent eval infrastructure; strong resume project if you contribute or port an eval.
- [Link](https://agentopsguide.com/ai-agent-evaluation-tools/)

### CI eval gates: promptfoo and DeepEval
- What: config-driven (promptfoo, MIT) and pytest-style (DeepEval, Apache 2.0) regression checks with trajectory/tool-correctness metrics.
- Why it matters: shows you can turn evals into a merge gate, which is what "eval-driven development" means in practice.
- [Link](https://aitoolsbakery.com/blog/best-llm-evaluation-tools/)

### Qdrant (hybrid search and filtering)
- What: Rust vector engine; repeatedly ranked best for filtered/hybrid retrieval in 2026 comparisons (one September 2026 benchmark claims it leads at 10M x 1536; treat as one source).
- Why it matters: the step up from pgvector when metadata filtering and sparse+dense fusion matter.
- [Link](https://devrudals.github.io/posts/vector-db-2026-enterprise-guide/)

### A2A protocol v1.0
- What: agent-to-agent protocol, stable 1.0 in March 2026, Signed Agent Cards, SDKs in six languages, accepted as a Growth Stage project at the Agentic AI Foundation on 2026-08-27 (alongside MCP). MCP is agent-to-tool; A2A is agent-to-agent across vendor boundaries.
- Why it matters: shows up in enterprise multi-agent designs (Google ADK, Microsoft Agent Framework, AWS AgentCore). Know the one-line difference from MCP.
- [Link](https://a2a-protocol.org/latest/)

### LiteLLM / AI gateway layer
- What: OpenAI-compatible proxy with virtual keys, budgets, routing/fallbacks and OTel. Production caveat from one review: it is a stateful service with a Postgres dependency; read changelogs before upgrades.
- Why it matters: the gateway pattern recurs in HLD answers (Uber's GenAI gateway, Cloudflare AI Gateway).
- [Link](https://mpiv.ai/blog/litellm-in-production-architecture-tradeoffs-and-operational-reality-2026)

### TypeScript side for your Next.js work: Vercel AI SDK and Mastra
- What: AI SDK 7.x (`ToolLoopAgent`) for agents inside a web app; Mastra 1.x for workflows, memory, evals and an MCP server in one package.
- Why it matters: lets you ship the front end of an eval dashboard without hand-rolling streaming.
- [Link](https://dbggr.dev/articles/agent-frameworks-compared/)

---

## Assess

### Prefill/decode disaggregation and distributed KV transfer
- What: run prefill (compute-bound) and decode (memory-bound) on separate servers, move KV cache between them, route with token-aware load balancing. Cloudflare describes doing this for Kimi K2.5 on Workers AI; Sarvam's job post asks for it on its Hopper/Blackwell fleet.
- Why it matters: the headline concept in modern LLM serving design interviews. Read, do not build.
- [Link](https://blog.cloudflare.com/high-performance-llms/)

### Cost-aware routing and autoscaling for multi-tenant inference
- What: Databricks reports "model units" as a VM-like capacity abstraction, load-aware sticky routing (Dicer), and over 80% GPU cost saving vs static provisioning (vendor-reported).
- Why it matters: a concrete reference architecture for "design an LLM serving platform".
- [Link](https://www.databricks.com/blog/reliable-llm-inference-scale)

### Agent sandboxes (Modal, E2B, Daytona, Cloudflare Sandbox SDK, AgentCore Runtime)
- What: isolated, fast-booting, snapshot-capable environments for untrusted agent-generated code. Orchestrating them durably is called "the missing layer" by Temporal.
- Why it matters: eval harnesses need clean, isolated trials. Anthropic's eval write-up notes shared state between trials inflates scores.
- [Link](https://temporal.io/blog/temporal-sandbox-orchestration-harness-the-missing-layer-for-running-agents)

### MCP extensions: Tasks, MCP Apps, Enterprise Managed Authorization; MRTR
- What: Tasks (polling via `tasks/get`) and Multi Round-Trip Requests replace server-initiated streams. The Aug 2026 roadmap lists agentic messaging, HTTP-native transport hardening, and agent identity as priorities.
- Why it matters: affects how long-running tools are designed. Track, do not implement yet.
- [Link](https://blog.modelcontextprotocol.io/posts/mcp-roadmap/)

### Managed agent runtimes
- What: Claude Managed Agents ($0.08 per running session-hour plus tokens per one comparison), OpenAI's hosted agent API, Amazon Bedrock AgentCore. Neither Anthropic's nor OpenAI's managed loop is zero-data-retention eligible per the same comparison.
- Why it matters: build-vs-buy discussions; many Indian enterprises will ask for ZDR and data residency.
- [Link](https://dbggr.dev/articles/agent-frameworks-compared/)

### Other framework families: Google ADK 2.x, Microsoft Agent Framework 1.x, Strands, CrewAI, Mastra
- What: ADK is multi-language with native A2A; Microsoft Agent Framework targets Azure/.NET; Strands is AWS-flavoured; CrewAI is role-based.
- Why it matters: you will meet them in GCC job descriptions (Microsoft, AWS, Google shops). Read one quickstart each.
- [Link](https://arize.com/ai-agents/agent-frameworks/)

### Turbopuffer and object-storage-backed vector search
- What: storage on object store, compute on demand; cheap at large scale, but one review measured 300-800 ms cold queries.
- Why it matters: cost-architecture trade-off for very large, infrequently queried corpora.
- [Link](https://alexcloudstar.com/blog/vector-database-comparison-2026/)

### Speculative decoding (EAGLE-style speculators)
- What: draft models verified by the target model; senior inference roles now expect you to train your own speculators and tune acceptance rate.
- Why it matters: a differentiator on inference-performance JDs.
- [Link](https://jobs.ashbyhq.com/sarvam/7d2faba2-21a1-4a8a-aff5-f708a6959195)

### Open-weight frontier models for self-hosting
- What: DeepSeek V4.1 Flash (open, MIT per one tracker, 1M context), Meta Muse Spark Open (822B, 15 Oct), NVIDIA Nemotron 3.5 Super VL, Qwen3.6 27B (21 Oct), MiMo-V2.6, Kimi K2.x.
- Why it matters: cheap tool-using agents and the models that vLLM/SGLang jobs actually serve.
- [Link](https://modeldrops.com/releases/2026-10/)

---

## Hold

- [MCP session-dependent designs, `initialize`-handshake assumptions, SSE resumability, and the HTTP+SSE transport. The 2026-07-28 spec removed or deprecated them. New servers should be stateless with explicit handles. Link](https://modelcontextprotocol.io/specification/2026-07-28/changelog)
- MCP Roots, Sampling, Logging features: deprecated with a twelve-month minimum window. Use tool parameters, direct provider APIs and OpenTelemetry instead. Same link.
- Dynamic Client Registration for new MCP auth work: deprecated in favour of Client ID Metadata Documents. Same link.
- [Helicone as a new observability choice: maintenance mode since March 2026 (security fixes and new models only). Link](https://dev.to/jasondevlab/the-llm-observability-tool-you-pick-today-may-not-exist-as-you-know-it-tomorrow-4dl1)
- [Eval graders that assert an exact tool-call sequence: Anthropic reports they are brittle because agents find valid paths designers did not anticipate. Grade the outcome; add partial credit. Link](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- [Hand-built multi-agent swarms without measured benefit: one comparison states no independent evidence shows one multi-agent design beating another on current models (single source, AI-written page; treat as a prompt to measure, not a fact). Link](https://dbggr.dev/articles/agent-frameworks-compared/)
- [Relying on forced `tool_choice` with Anthropic's newest models: a tracker reports Fable 5.1 and Mythos 5.1 removed forced tool choice and changed thinking/history rules (enforced for accounts created on or after 31 Aug 2026). Verify against Anthropic's migration guide before relying on it. Link](https://www.digitalapplied.com/blog/ai-model-releases-september-2026-tracker)
- [Chroma for anything beyond prototypes: positioned by its own docs for lightweight/local use. Link](https://www.developersdigest.tech/blog/vector-database-comparison-rag-agents-2026)

---

## Notable model releases (Sep - Oct 2026)

Dates and licences from tracker pages; prices change often.

| Date (2026) | Model | Notes |
| --- | --- | --- |
| Sep 1 | Claude Fable 5.1 / Mythos 5.1 | Mythos 5.1 gated to trusted-access programmes; $10/$50 per M tokens, 1M context (tracker) |
| Sep 2 | Gemini 3.8 Flash | $0.75/$3.75 per M introductory to Dec 31, 2026 (tracker) |
| Sep 3 | GPT-6 Astra | OpenAI frontier tier, closed |
| Sep 10 | DeepSeek V4.1 Flash | open weights, 1M context |
| Sep 22 | Claude Opus 5.5; GPT-6 Sol and Luna | Opus 5.5 priced $4/$20 per ThursdAI; Luna $0.10/$0.50 |
| Sep 28 | Claude Sonnet 5.5 | mid tier |
| Sep 29 | GPT-6.1 Sol | successor to Sol |
| Sep 30 | Gemini 4 Argon | Google top reasoning model; listed Oct 13 on another tracker, so the date is inconsistent between sources |
| Oct 6 | Mistral Large 4 (preview), EmbeddingGemma 2 | Mistral weights promised for end of October |
| Oct 7 | Claude Haiku 5.5 | low-cost tier |
| Oct 15 | Meta Muse Spark Open (822B), NVIDIA Nemotron 3.5 Super VL | open weights |
| Oct 19-21 | MiniMax M3.1 Flash, Qwen3.6 27B | latest at time of writing |

Links: [https://www.elegantsoftwaresolutions.com/blog/ai-model-releases-september-october-2026](https://www.elegantsoftwaresolutions.com/blog/ai-model-releases-september-october-2026) , [https://modeldrops.com/releases/2026-10/](https://modeldrops.com/releases/2026-10/) , [https://thursdai.news/releases/2026-09](https://thursdai.news/releases/2026-09) , [https://www.scriptbyai.com/ai-model-release-calendar/](https://www.scriptbyai.com/ai-model-release-calendar/)

Why it matters for you: the release cadence (several frontier updates a month) is the argument for model-agnostic harnesses and automated regression evals. Re-run your eval suite on every new model and track cost per task, not only accuracy.

---

## System-design-relevant infrastructure

Map each to an HLD question you can answer on a whiteboard.

- LLM serving platform: router, autoscaler, rate limiter, capacity manager (Databricks); Triton control plane plus vLLM (Netflix); PD disaggregation (Cloudflare).
- AI gateway: single OpenAI-compatible surface with auth, caching, routing, failover, cost tracking (Cloudflare AI Gateway buffers streamed responses so an interrupted agent can reconnect without paying twice; Uber and LiteLLM follow the same pattern).
- Agent runtime: durable workflow + sandbox per run + Postgres system of record + event stream (PostHog, Temporal).
- Stateless protocol servers behind a plain load balancer (MCP 2026-07-28).
- Observability pipeline: OTel GenAI spans into ClickHouse-backed stores (Langfuse v4 moved to a single wide, mostly immutable ClickHouse table).
- Agent-scale developer infrastructure: Anthropic moved from roughly 2,500 merges/day (May 2026) to over 30,000/day (Sep 2026) and replaced git with an in-house system (Scion) built on content-addressed storage and a tiered cache. A good case study for caching tiers and horizontal scalability.
- Retrieval: pgvector first, Qdrant/Milvus when filtering or scale demands it, object-storage-backed when cost dominates.

Link for the first and last: [https://www.anthropic.com/engineering/redesigning-source-control](https://www.anthropic.com/engineering/redesigning-source-control)

---

## What to read this week

1. The 2026-07-28 MCP Specification (stateless core, MRTR, caching) - [https://blog.modelcontextprotocol.io/posts/2026-07-28/](https://blog.modelcontextprotocol.io/posts/2026-07-28/)
2. The New MCP Roadmap (Aug 2026) - [https://blog.modelcontextprotocol.io/posts/mcp-roadmap/](https://blog.modelcontextprotocol.io/posts/mcp-roadmap/)
3. Demystifying evals for AI agents (Anthropic, Jan 2026) - [https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
4. Effective harnesses for long-running agents (Anthropic, Nov 2025) - [https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
5. Harness design for long-running application development (Anthropic, Mar 2026) - [https://www.anthropic.com/engineering/harness-design-long-running-apps](https://www.anthropic.com/engineering/harness-design-long-running-apps)
6. Redesigning source control at Anthropic (13 Oct 2026) - [https://www.anthropic.com/engineering/redesigning-source-control](https://www.anthropic.com/engineering/redesigning-source-control)
7. vLLM vs. SGLang: choosing the right inference engine (Red Hat, 14 Oct 2026) - [https://developers.redhat.com/articles/2026/10/14/vllm-vs-sglang-choosing-the-right-inference-engine-for-your-workload](https://developers.redhat.com/articles/2026/10/14/vllm-vs-sglang-choosing-the-right-inference-engine-for-your-workload)
8. Reliable LLM Inference at Scale (Databricks, May 2026) - [https://www.databricks.com/blog/reliable-llm-inference-scale](https://www.databricks.com/blog/reliable-llm-inference-scale)
9. In-House LLM Serving at Netflix (Jul 2026) - [https://netflixtechblog.com/in-house-llm-serving-at-netflix-a5a8e799ea2c](https://netflixtechblog.com/in-house-llm-serving-at-netflix-a5a8e799ea2c)
10. Temporal Agent Harness: durable agent infrastructure (Aug 2026) - [https://temporal.io/blog/temporal-agent-harness-durable-agent-infrastructure](https://temporal.io/blog/temporal-agent-harness-durable-agent-infrastructure)

Next in the queue: Building the foundation for running extra-large language models (Cloudflare) [https://blog.cloudflare.com/high-performance-llms/](https://blog.cloudflare.com/high-performance-llms/) ; Effective context engineering for AI agents (Anthropic) [https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) ; Inside the LLM Call: GenAI Observability with OpenTelemetry [https://opentelemetry.io/blog/2026/genai-observability/](https://opentelemetry.io/blog/2026/genai-observability/) ; Cutting our inference bill by 68% (Cloudflare, 19 Oct 2026) [https://blog.cloudflare.com/obsessive-inference-optimization/](https://blog.cloudflare.com/obsessive-inference-optimization/) (listed in search results, not read by me).

No academic papers are in this list because I did not verify any 2026 paper this session. For serving fundamentals, read the vLLM and SGLang documentation and project READMEs instead.

---

## Engineering blogs to follow

- Anthropic Engineering: agents, evals, harnesses, context engineering, MCP. [https://www.anthropic.com/engineering](https://www.anthropic.com/engineering)
- [claude.dev blog (practical posts from Anthropic developers, for example "Automating eval design and hillclimbing with Claude", 28 Sep 2026)](https://claude.dev/)
- [MCP blog (spec releases, roadmap)](https://blog.modelcontextprotocol.io/)
- [Cloudflare Blog (inference, Agents SDK, AI Gateway, Workflows)](https://blog.cloudflare.com/)
- [Databricks Blog (inference platform, Temporal + Lakebase agent reference)](https://www.databricks.com/blog)
- [Netflix Tech Blog](https://netflixtechblog.com/)
- [Temporal Blog (durable execution for agents)](https://temporal.io/blog)
- [PostHog engineering (cloud agents runtime, candid write-ups)](https://posthog.com/blog)
- [Meta Engineering (AI infrastructure at scale; dense, for staff-level readers)](https://engineering.fb.com/)
- [OpenTelemetry Blog (GenAI conventions)](https://opentelemetry.io/blog/)
- [Red Hat Developer (vLLM ecosystem explainers)](https://developers.redhat.com/)
- [Langfuse handbook and blog (ClickHouse data-model lessons)](https://langfuse.com/handbook/chapters/story)
- [Sarvam blog (Indic models, voice, inference)](https://www.sarvam.ai/blogs)
- [Curated list: daily.dev "best engineering blogs to follow in 2026"](https://daily.dev/blog/best-engineering-blogs-to-follow/)

---

## Notes on method

Searches run on 2026-10-22 against: agent frameworks, MCP, eval tooling, vLLM/SGLang, vector databases, LLMOps/OTel, model releases, system-design infra. Primary sources (MCP spec, Anthropic, Cloudflare, Databricks, Netflix/InfoQ, TechCrunch, Business Wire, ClickHouse, Temporal, Linux Foundation) were preferred. Items sourced only from tracker or comparison sites are labelled as such. Not verified this session: any specific benchmark number beyond what is attributed to its source, and exact current pricing.
