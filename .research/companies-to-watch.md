# Companies to watch

As of 2026-10 (researched 2026-10-22). For a software engineer in India (GenAI/agent evaluation, LLM harnesses, Python/FastAPI, Next.js) applying through Naukri, Hirist, Instahyre, Cutshort and Wellfound, and directly via company career pages.

Verification tags used below:
- [V] confirmed in a web search or page fetch on 2026-10-22 (source linked).
- [K] from general background knowledge, not re-verified this session. Confirm on the careers page before investing prep time.

Careers links were checked with an HTTP request on 2026-10-22. Where a site blocks scripted requests (403/406) I say "bot-blocked, link is the standard one"; open it in a browser.

---

## Market context (why now)

- [GCCs (global capability centres) out-hired IT services for a third year: about 200,000 net adds vs 110,000 in FY26; about 2,117 centres, 2.36 million people (Recruise, citing industry data). Source](https://recruiseglobal.com/intelligence/hiring-pulse/02/)
- [About 65% of new GCC roles created in 2026 require AI skills; median experience of GCC hires is six years and 62% of hiring is in the 3-8 year band; forward-deployed and AI-engineering postings are reported up roughly 1,000% in twelve months (ANSR, 24 Sep 2026). Source](https://www.globenewswire.com/news-release/2026/09/24/3368576/0/en/new-ansr-report-finds-ai-skills-driving-gcc-hiring-in-india.html)
- [Shortages cited by Quess include GenAI engineering, AI observability, MLOps and LLM fine-tuning, with a 38-42% AI/data talent gap (Apr 2026). Source](https://economictimes.indiatimes.com/tech/startups/ai-talent-gap-of-nearly-40-emerges-as-biggest-bottleneck-for-gcc-growth-quess-report/articleshow/130396111.cms)
- [Zinnov reports an average GCC salary increase of 9.8% in 2026 but 21.1% for AI/ML. Source](https://zinnov.com/global-talent/salary-increase-attrition-and-hiring-trends-an-india-gcc-view-2026-report/)
- [Indian AI-agent startups announced 45 disclosed rounds worth $632.2M in 2026 through 4 Oct; Bengaluru is the base for 47% of rounds. Source](https://gravity.fast/data/india-ai-agent-funding-tracker/)
- [Frontier labs are building India teams: Anthropic and OpenAI both announced offices (Bengaluru; OpenAI also Delhi, with Mumbai/Bengaluru planned). As of June 2026 OpenAI directly employed fewer than 30 people in India. Source](https://www.livemint.com/ai/artificial-intelligence/openai-india-team-artificial-general-intelligence-personlised-voice-ai-assistant-chatgpt-anthropic-google-11781766302966.html)

Implication: your profile (agent evals + harnesses + production backend) maps to the roles titled AI Engineer, Forward Deployed Engineer, Applied AI Engineer, Agent Engineer, LLM Platform Engineer and GenAI Evaluation. Search those exact titles on every portal, not only "ML Engineer".

Seniority warning. Several lab roles in India are senior: Anthropic's Applied AI Architect (Bangalore, posted 2026-10-08) asks for 10+ years in customer-facing technical roles; its Applied AI Engineer, Beneficial Deployments asks for 8+ years. Treat those as stretch targets and prioritise the mid-level roles below.

---

## Group 1: AI labs and AI infrastructure

### Anthropic [V]
- What: builds Claude; Claude Agent SDK, MCP, Claude Code.
- Why relevant: your exact domain (evals, harnesses, agents). Bengaluru office announced Oct 2025 for early 2026; India roles are currently customer-facing Applied AI.
- Typical India roles: Applied AI Engineer / Architect, Beneficial Deployments engineer; engineering roles in Bengaluru are few.
- Careers: [https://www.anthropic.com/careers](https://www.anthropic.com/careers) (live listings at [https://job-boards.greenhouse.io/anthropic](https://job-boards.greenhouse.io/anthropic))
- Prepare: read "Demystifying evals for AI agents", "Effective harnesses for long-running agents", "Effective context engineering for AI agents" (all at [https://www.anthropic.com/engineering](https://www.anthropic.com/engineering)). Ship a public MCP server and a small eval harness repo. Roles ask for evals advice, context engineering, agent architecture and MCP/Agent Skills. Evidence: [https://job-boards.greenhouse.io/anthropic/jobs/5443882008](https://job-boards.greenhouse.io/anthropic/jobs/5443882008) and [https://www.productbased.in/jobs/3653/applied-ai-engineer-beneficial-deployments](https://www.productbased.in/jobs/3653/applied-ai-engineer-beneficial-deployments)

### OpenAI [V]
- What: GPT-6 family, Agents SDK, Codex.
- Why relevant: building an India engineering team for multilingual voice/personalised assistant; first office New Delhi (Aug 2025).
- Typical roles: Applied AI Engineer, a small number of engineering roles; counts are low.
- Careers: [https://jobs.ashbyhq.com/openai](https://jobs.ashbyhq.com/openai) (https://openai.com/careers is bot-blocked)
- Prepare: OpenAI Agents SDK (handoffs, guardrails, tracing), Responses API, prompt caching; multilingual/voice evaluation angle for Indian languages.

### Google DeepMind (Bangalore) [V]
- What: Gemini, Veo; ML and Optimization team in India does efficiency and foundational-model research.
- Why relevant: research-engineer track; also Google India product teams use Gemini/ADK/A2A.
- Typical roles: Research Scientist, Research Engineer, Software Engineer (PhD or strong publication record expected for research roles).
- [Careers: [https://deepmind.google/careers/](https://deepmind.google/careers/) ; Google-wide](https://careers.google.com)
- Prepare: JAX familiarity, efficient-inference concepts, Google ADK + A2A quickstart for the product-engineering side.

### Sarvam AI (Bengaluru, Delhi) [V]
- What: India's full-stack sovereign AI: foundation models, ASR, TTS, Translate, Vision, Model API platform. Unicorn at about $1.5B per Inc42. Customers listed include Tata Capital, SBI Life, CRED, IDFC, LIC.
- Why relevant: 42 open positions on the careers page; includes Agent Engineer, Data Scientist (Evaluations), MLOps Engineer, Software Engineer for the Model API Platform (Python/Go, FastAPI listed as a plus), Inference Performance Engineer, Platform Engineer for AI Infrastructure.
- Typical roles: as above; most are on-site in Bengaluru or Delhi.
- Careers: [https://www.sarvam.ai/careers](https://www.sarvam.ai/careers) and [https://jobs.ashbyhq.com/sarvam](https://jobs.ashbyhq.com/sarvam)
- [Prepare: low-latency backend design (p95/p99, WebSockets, metering, rate limiting), streaming ASR/TTS basics, vLLM/SGLang internals if you target inference roles. Their JDs expect daily AI-tool use and written RFCs. Evidence](https://jobs.ashbyhq.com/sarvam/0371342b-5cb8-487b-9310-4d0eb5b37f47)

### Gnani.ai (Bengaluru) [V]
- What: voice AI agents and speech models (ASR/TTS) for BFSI, telecom, e-commerce; Series B ($10M, Mar 2026 per the funding tracker).
- Why relevant: agentic voice products at enterprise scale; hiring at 3+ years across ASR/TTS and ML engineering.
- Typical roles: ML Engineer/Scientist, Senior Staff Engineer (ASR/TTS), backend.
- [Careers](https://www.gnani.ai/careers)
- Prepare: speech-LLM basics, code-switching across Indian languages, streaming latency, evaluation of voice agents (task completion, WER).

### Databricks (Bengaluru) [K]
- What: data/AI platform with its own LLM inference platform (125T tokens/month per its May 2026 post), agent tooling, Lakebase Postgres.
- Why relevant: published inference-platform and agent-reference architecture you can study; Bengaluru R&D presence is long-standing (confirm current openings).
- Typical roles: Software Engineer (backend/infra), Solutions/Field Engineering, ML platform.
- [Careers](https://www.databricks.com/company/careers)
- Prepare: [https://www.databricks.com/blog/reliable-llm-inference-scale](https://www.databricks.com/blog/reliable-llm-inference-scale) and [https://www.databricks.com/blog/build-durable-agents-temporal-and-lakebase](https://www.databricks.com/blog/build-durable-agents-temporal-and-lakebase) ; distributed systems and Spark/Delta basics.

### NVIDIA (India) [K]
- What: GPUs, CUDA, NeMo, Dynamo and TensorRT-LLM inference stack, Nemotron open models.
- Why relevant: inference/serving and applied-AI roles in India sites; RadixArk and Inferact cite NVIDIA as investor/partner.
- Typical roles: Deep Learning Software Engineer, Solutions Architect, Systems Software.
- [Careers](https://www.nvidia.com/en-in/about-nvidia/careers/)
- Prepare: CUDA/Triton basics, TensorRT-LLM and Dynamo docs, KV cache and batching.

### Microsoft India (IDC Hyderabad/Bengaluru) [K]
- What: Azure AI Foundry, Copilot, Microsoft Agent Framework 1.x; A2A integrated into Foundry and Copilot Studio (per Linux Foundation, Apr 2026).
- Why relevant: large GenAI engineering orgs in India; Microsoft India's president publicly cites AI-skill scarcity (Reuters, May 2026).
- Typical roles: Software Engineer / SDE II, Applied Scientist, AI Engineer.
- [Careers](https://careers.microsoft.com)
- Prepare: Microsoft Agent Framework quickstart, OpenTelemetry GenAI (a Microsoft author wrote the OTel GenAI post), Azure OpenAI/Foundry basics.

### Amazon / AWS (India) [K]
- What: Bedrock, AgentCore (Runtime, Gateway, Memory, Evaluation), Strands Agents SDK.
- Why relevant: AgentCore bundles agent hosting, identity and evaluation, a direct fit for eval-minded engineers; large India engineering presence.
- Typical roles: SDE II, Applied Scientist, Solutions Architect (GenAI).
- [Careers](https://www.amazon.jobs)
- Prepare: Strands Agents + AgentCore tutorials, leadership-principle stories, HLD.

### Inference and eval infrastructure startups with open-source projects (remote or contribution route)
These are US-based and I did not verify India hiring, so treat them as open-source contribution targets and remote-role watchlist items.
- Inferact (vLLM creators; $150M seed, Jan 2026) [V]: [https://inferact.ai](https://inferact.ai) , careers [https://jobs.ashbyhq.com/inferact](https://jobs.ashbyhq.com/inferact)
- [RadixArk (SGLang and Miles; $100M seed, May 2026) [V]](https://radixark.com)
- [Braintrust (eval platform; $80M Series B, Feb 2026) [V]](https://www.braintrust.dev/careers)
- [LangChain (LangGraph, LangSmith) [K]](https://langchain.com/careers)
- [Temporal (durable execution; agent harness) [K]](https://temporal.io/careers)
- [Modal (sandboxes and serverless GPUs) [K]](https://modal.com/careers)
- ClickHouse (owns Langfuse since Jan 2026) [V]: [https://clickhouse.com](https://clickhouse.com) (careers page not checked)
- Prepare: pick one issue in vLLM, SGLang, Langfuse, Inspect AI or an MCP SDK and land a merged PR; it is the strongest signal for these teams.

---

## Group 2: Product companies and GCCs with large India engineering

### Atlassian (Bengaluru) [K]
- What: Jira/Confluence with Rovo AI agents.
- Why relevant: agentic features inside products used by millions; MCP/agent-integration surface.
- Typical roles: Software Engineer (backend/full-stack), ML Engineer.
- [Careers](https://www.atlassian.com/company/careers/all-jobs)
- Prepare: strong HLD (multi-tenant SaaS), Java/Kotlin or Python backend, evals for agent features.

### Uber (Bengaluru, Hyderabad) [K]
- What: runs a generative AI gateway with an OpenAI-compatible interface, centralised auth, caching and routing (mentioned by InfoQ, Jul 2026).
- Why relevant: gateway and platform patterns match your harness work.
- Typical roles: Software Engineer II/III, ML Engineer, Platform.
- Careers: [https://www.uber.com/in/en/careers/](https://www.uber.com/in/en/careers/) (bot-blocked, standard link)
- Prepare: gateway/rate-limiting/caching HLD; read [https://www.infoq.com/news/2026/07/netflix-llm-platform/](https://www.infoq.com/news/2026/07/netflix-llm-platform/) for the pattern.

### Salesforce (Hyderabad, Bengaluru) [K]
- What: Agentforce; member of the A2A Technical Steering Committee.
- Why relevant: enterprise agent platform with a big India engineering base.
- Typical roles: MTS/SMTS, AI engineer.
- [Careers](https://careers.salesforce.com)
- Prepare: A2A basics, Java/Apex-adjacent platform thinking, eval/guardrails for enterprise agents.

### Adobe (Noida, Bengaluru) [K]
- What: Firefly and GenAI features across Creative Cloud and Acrobat.
- Why relevant: GenAI product engineering with a large India site.
- Typical roles: Computer Scientist, ML Engineer, Software Engineer.
- Careers: [https://www.adobe.com/careers.html](https://www.adobe.com/careers.html) (bot-blocked, standard link)
- Prepare: retrieval over documents, latency-sensitive inference APIs.

### Intuit (Bengaluru) [K]
- What: GenAI assistants across QuickBooks/TurboTax/Credit Karma.
- Why relevant: production LLM apps in regulated finance, strong eval and guardrail focus.
- Typical roles: Software Engineer 2/3, Staff Engineer, ML engineer.
- [Careers](https://www.intuit.com/careers/)
- Prepare: RAG evaluation, safety/guardrails, Java/Python services.

### Walmart Global Tech (Bengaluru, Chennai) [K]
- What: retail tech with GenAI search and associate assistants.
- Typical roles: SDE III, Data/ML Engineer.
- [Careers](https://careers.walmart.com)
- Prepare: large-scale HLD, Kafka, retrieval.

### ThoughtSpot (Bengaluru) [K]
- What: AI-driven analytics with an agent interface.
- Typical roles: Software Engineer, MTS.
- [Careers](https://www.thoughtspot.com/careers)
- Prepare: text-to-SQL evaluation, semantic layers.

### Observe.AI (Bengaluru) [V]
- What: contact-centre AI: voice and chat AI agents, real-time copilots, conversation intelligence; processes millions of call recordings a day; offices in Redwood City and Bengaluru.
- Why relevant: published interview guide, multi-tenant scale problems, agent QA.
- Typical roles: SDE (backend), ML Engineer.
- [Careers](https://www.observe.ai/careers)
- [Prepare: Java/Python at scale, queues, multi-tenancy, evaluation of conversations. Evidence](https://getmereferred.com/job-listing/software-development-engineer-iv-backend-observeai-bengaluru-2-to-5-years-experience-4da48984-baa8-43ea-a62c-2e3010b0ef2e)

### Sprinklr (Gurugram, Bengaluru) [K]
- What: unified CXM platform with AI agents.
- Typical roles: Software Engineer, AI/ML Engineer.
- [Careers](https://www.sprinklr.com/careers/)
- Prepare: LLM routing across providers, multi-tenant search.

### Freshworks (Chennai, Bengaluru) [K]
- What: Freddy AI agents in support/ITSM products.
- Typical roles: Software Engineer, ML Engineer.
- [Careers](https://www.freshworks.com/company/careers/)
- Prepare: RAG over knowledge bases, evaluation of resolution rate, Ruby/Java/Python services.

### Zoho (Chennai) [K]
- What: Zia and own LLM efforts across a large product suite.
- Typical roles: Member Technical Staff.
- [Careers](https://www.zoho.com/careers/)
- Prepare: Java fundamentals, DSA; process is campus-style.

### Postman (Bengaluru) [K]
- What: API platform with AI agent builder and MCP support.
- Why relevant: API-first, MCP-adjacent tooling.
- Typical roles: Software Engineer, AI engineer.
- [Careers](https://www.postman.com/company/careers/)
- Prepare: API design, MCP servers, Node/TypeScript.

### BrowserStack (Mumbai) [K]
- What: testing platform with AI agents for QA.
- Why relevant: testing and evaluation mindset.
- Typical roles: Software Engineer, SDET.
- [Careers](https://www.browserstack.com/careers)
- Prepare: test automation, agentic QA.

### Razorpay (Bengaluru) [K]
- What: payments with AI-driven agents and agentic payments work.
- Typical roles: SDE 2/3, ML Engineer.
- [Careers](https://razorpay.com/jobs/)
- Prepare: payments system design, idempotency, Go/Java/Python.

### PhonePe (Bengaluru) [K]
- [Careers](https://www.phonepe.com/careers/)
- What: fintech at UPI scale with GenAI assistants and fraud ML.
- Typical roles: SDE, ML Engineer.
- Prepare: high-throughput HLD, Kafka, consistency.

### CRED (Bengaluru) [V for Claude usage]
- What: fintech; named by Anthropic as a large Indian enterprise relying on Claude for critical coding work; also a Sarvam customer.
- Typical roles: Backend, ML, full-stack.
- [Careers](https://jobs.lever.co/cred)
- [Prepare: Kotlin/Java/Python backend, product-level design questions. Evidence](https://www.anthropic.com/news/expanding-global-operations-to-india)

### Swiggy (Bengaluru) [K]
- What: food and quick commerce with GenAI search/assistant work.
- Typical roles: SDE, ML Engineer.
- [Careers](https://careers.swiggy.com)
- Prepare: recommender and search HLD, geospatial systems.

### Flipkart (Bengaluru) [K]
- [Careers](https://www.flipkartcareers.com)
- What: e-commerce with large GenAI shopping-assistant effort.
- Typical roles: SDE 2/3, Data Scientist.
- Prepare: DSA plus HLD (high-scale commerce), retrieval and ranking.

### Meesho (Bengaluru) [K]
- Careers: [https://jobs.lever.co/meesho](https://jobs.lever.co/meesho) (careers.meesho.com is bot-blocked)
- What: social commerce with GenAI for seller tooling and search.
- Typical roles: SDE, ML Engineer.
- Prepare: ML systems, cost-sensitive inference design.

### Zepto (Mumbai, Bengaluru) [K]
- [Careers](https://www.zepto.com/careers)
- What: quick commerce.
- Typical roles: backend, ML.
- Prepare: real-time inventory and routing HLD.

### Pocket FM (Gurugram, Bengaluru) [K]
- [Careers](https://www.pocketfm.com/careers)
- What: audio-series platform using GenAI for content and voice.
- Typical roles: ML Engineer, backend.
- Prepare: TTS/LLM pipeline cost and quality.

---

## Group 3: Startups (Wellfound, Cutshort and Instahyre are the best channels here)

All in this group are confirmed in the 2026 funding tracker unless tagged [K]. Source for rounds: [https://gravity.fast/data/india-ai-agent-funding-tracker/](https://gravity.fast/data/india-ai-agent-funding-tracker/) (data through 4 Oct 2026).

### Emergent (Bengaluru / San Francisco) [V]
- What: builds production-ready web and mobile apps from prompts using multi-agent systems; $130M Series C on 15 Jul 2026 (reported valuation $1.5B), after $70M Series B in Jan.
- Why relevant: agent harness and evaluation of generated apps at scale; fast growth.
- Typical roles: Software Engineer, AI/Agent Engineer, full-stack (Next.js plus Python).
- [Careers](https://emergent.sh/careers)
- Prepare: sandboxed code execution, evals for code agents, build one agent that produces a working app and measure pass rate.

### Ema (San Francisco HQ, Bengaluru office) [V]
- What: "universal AI employees" for HR, IT and finance workflows; $77M Series B on 24 Sep 2026.
- Typical roles: AI engineer, backend, platform.
- [Careers](https://ema.co/careers)
- Prepare: enterprise connectors (MCP-style), workflow reliability, human-in-the-loop.

### Vorflux (SF HQ, most employees in Bengaluru) [V]
- What: teams of specialised AI agents running the software lifecycle from planning to code review; $15M seed (YC, Peak XV), Jul 2026.
- Why relevant: coding-agent evals and harnesses.
- Careers: search [https://www.ycombinator.com/companies/industry/ai/india/hiring](https://www.ycombinator.com/companies/industry/ai/india/hiring)
- Prepare: code-review agents, multi-agent coordination, evals.

### Ringg AI (Bengaluru) [V]
- What: enterprise voice, WhatsApp and browser agents; Series A extended to $15.5M (Peak XV), Aug 2026.
- Careers: [https://ringg.ai](https://ringg.ai) (site check only; find the careers link on the page)
- Prepare: voice-agent latency, telephony, evaluation of call outcomes.

### Bolna (Bengaluru) [V]
- What: platform for building human-like voice AI agents; $6.3M seed (General Catalyst), Jan 2026.
- Careers: [https://bolna.ai](https://bolna.ai) (site check only)
- Prepare: real-time streaming stacks (WebSockets, WebRTC), ASR/TTS integration.

### Navana.ai (Bengaluru) [V]
- What: full-stack voice AI in 12 Indian languages; Series A $4.2M, Sep 2026.
- Prepare: Indic voice evaluation.

### Pinegap (Bengaluru / New York) [V]
- What: agentic platform for institutional equity analysts; $8M Series A (Stellaris), Aug 2026.
- Prepare: financial-document RAG, eval of research agents.

### Kapture CX (Bengaluru) [V]
- What: verticalised agentic platform for customer support; $10M pre-Series B, Jun 2026.
- Prepare: support-resolution evals.

### NudgeBee (Pune) [V]
- What: agentic AI for enterprise cloud operations and Kubernetes troubleshooting; $3M seed, Apr 2026.
- Why relevant: infra plus agents, matches your system-design learning.
- Prepare: Kubernetes basics, tool-using SRE agents.

### Composio [K]
- What: tooling layer that gives agents authenticated access to hundreds of apps; Indian-founded.
- [Careers](https://composio.dev/careers)
- Prepare: tool-calling reliability, auth (OAuth), MCP.

### Maxim AI (Bengaluru / San Francisco) [K, listed in a 2026 eval-tool comparison]
- What: agent simulation and evaluation platform (multi-turn simulation, trajectory evals).
- Why relevant: the company whose product is your specialty.
- Careers: search [https://www.maxim.ai](https://www.maxim.ai) ; confirm the careers page
- Prepare: build a multi-turn simulation eval for a voice or chat agent.

### Yellow.ai [K]
- What: enterprise conversational and agentic automation.
- [Careers](https://www.yellow.ai/careers)
- Prepare: multi-channel bots, evaluation of dialogue flows.

### Other lists to mine
- [Tracxn, 70 agentic AI startups in Bengaluru (updated 30 Sep 2026)](https://tracxn.com/d/explore/agentic-ai-startups-in-bengaluru-india/__-ZE2EEWJnKCUvN904fKz_Na-AKnnk_pX9rx1GE9FRSM)
- [Inc42 top 30 funded AI startups in Bengaluru](https://inc42.com/lists/top-30-funded-ai-startups-in-bengaluru-2026/)
- [Inc42 Indian AI startup tracker (170+)](https://inc42.com/startups/indian-ai-startup-tracker/)
- [YC India AI companies currently hiring](https://www.ycombinator.com/companies/industry/ai/india/hiring)

Not listed because career pages did not resolve in my checks: Krutrim (site unreachable by script), Atomicwork (404). Search them manually if interested.

---

## How to use this list

1. Shortlist 8-10: for your profile, the strongest fits are Sarvam, Emergent, Ema, Vorflux, Observe.AI, Gnani, Maxim AI, Microsoft/AWS GenAI teams, Intuit, Atlassian, and Anthropic/OpenAI for mid-level roles when they appear.
2. For each, reuse this pre-application checklist:
   - Read the company's latest engineering post or product announcement and one JD end to end.
   - Prepare one project that mirrors the JD: for example an eval harness with trial isolation and graders, an MCP server, a low-latency streaming API in FastAPI, or a durable agent workflow.
   - Prepare two HLD designs: an LLM gateway and a durable agent runtime. See the system-design section in tech-radar.md.
   - Prepare numbers: latency, cost per task, pass rate before/after your change.
3. Portal tips:
   - Naukri and Hirist: search "GenAI engineer", "LLM engineer", "agentic AI", "AI platform engineer", "MLOps", "forward deployed engineer". Keep headline and key skills aligned to those titles.
   - Instahyre and Cutshort: set role preference to AI/ML plus backend and keep notice-period and expected-CTC fields current; recruiters filter on them.
   - Wellfound: filter by Bengaluru and Series A/B AI startups listed above; apply with a short note linking a relevant repo.
   - Direct careers pages (Ashby, Greenhouse, Lever) are faster than portals for Sarvam, Anthropic, OpenAI and Emergent.

---

## Notes on method

Searches and link checks run on 2026-10-22. Facts tagged [V] come from the cited pages: Anthropic and Sarvam job posts, Anthropic India announcement, Mint on OpenAI India, DeepMind careers page, Observe.AI and Gnani pages, Inc42 and Gravity funding data, TechCrunch/Business Wire on Inferact and RadixArk, Quess/ANSR/Zinnov/Recruise reports. Facts tagged [K] are background knowledge; company careers pages and current openings change weekly, so confirm location, level and openings before applying. Funding-tracker figures are secondary and some HQ attributions differ between sources.
