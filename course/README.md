# PrepForge — Senior Engineer Interview Course (10–12 Years Experience)

A complete, self-contained preparation course to crack **FAANG / top-tier senior & staff level interviews**. Covers System Design, DSA, Full-Stack (MERN + Kubernetes), and ML / Generative AI (RAG, Agents, Evals).

All content is in Markdown with **Mermaid diagrams** and **runnable code** for every DSA problem — and the whole course is also a **professional website** (see below).

> **Start here (3 steps)**
> 1. Pick a track from the **sidebar on the left** (on a phone, tap the menu button in the corner). New to interview prep? Start with **DSA**, then **System Design**.
> 2. Follow the **8-week plan** below — one module at a time, in order. Solve every practice question yourself before reading the answer.
> 3. Use the **search box** (top of sidebar) any time you need a topic fast, and check [Live AI & Tech News](./news.md) to stay current.

---

## Use It as a Website (recommended)

The course ships with a full responsive website (sidebar navigation, full-text search, rendered diagrams, copy buttons on code). To start it:

```bash
cd course
python3 serve.py 8000
```

Then open **http://localhost:8000** in your browser. (`serve.py` is a tiny wrapper around Python's built-in server that disables browser caching, so edits always show up on refresh. It always serves its own folder, so `python3 path/to/course/serve.py` works from any directory. Any static server works too; internet is needed once per session for CDN assets and for live news. If another app is already using a port, pick a different number, e.g. `python3 serve.py 8899`.)

Or study without a browser: start Sandy (`venv/bin/python -m sandy` in the folder above this one) and open its **Study** section. It shows today's module from the 8-week plan and every module by track, opens them right in the terminal (`n` / `p` turn the page, `m` marks one read), and has a **Start** button for this site. Sandy is the same screen that runs the job bots.

- **[Live AI & Tech News](./news.md)** — fetches today's AI/tech headlines from the internet (Hacker News + dev.to) right inside the site.
- **[Latest AI Trends 2025–26](./04-ml-genai-agents/11-latest-ai-trends.md)** — curated, interview-ready summary of what changed recently.

To publish it free on the internet: copy just this folder into its own GitHub repository and enable **GitHub Pages** (the `.nojekyll` file is already included). Never publish the folder above it: that is the job bots' repository.

---

## Tracks

| # | Track | Folder | What you get |
|---|-------|--------|--------------|
| 1 | **System Design** | [01-system-design/](./01-system-design/) | Fundamentals → distributed systems → 10 full case studies → interview framework + 30 questions |
| 2 | **DSA** | [02-dsa/](./02-dsa/) | 12 pattern modules, 70+ fully solved problems with runnable Python + test drivers, mock sets |
| 3 | **Full-Stack MERN + Kubernetes** | [03-fullstack-mern-kubernetes/](./03-fullstack-mern-kubernetes/) | Node, MongoDB, React deep dives → auth/security → Docker/CI-CD → full K8s deployment YAML → 60+ Q&A |
| 4 | **ML + GenAI + Agents** | [04-ml-genai-agents/](./04-ml-genai-agents/) | ML/DL fundamentals → transformers/LLMs → prompting, RAG, agents, MCP, eval harnesses, fine-tuning, LLMOps → 60+ Q&A → latest 2025–26 trends |
| 5 | **Behavioral & Leadership** | [05-behavioral-leadership/](./05-behavioral-leadership/) | STAR story bank, Amazon LPs / Google / Meta round guides, 40 senior-level questions, salary negotiation |

---

## How to Use This Course

### If you have 8 weeks (recommended)

| Week | Focus |
|------|-------|
| 1–2 | DSA patterns 1–6 (1 pattern/day, solve every problem yourself BEFORE reading the solution) |
| 3 | DSA patterns 7–12 + mock set 1 |
| 4–5 | System Design fundamentals (files 01–06), 1 case study per day from file 07 |
| 6 | MERN deep dives + Docker/K8s (do the practice tasks hands-on) |
| 7 | ML/GenAI track (prioritize transformers, RAG, agents, evals — this is what interviewers ask in 2025+) |
| 8 | Mock interviews: DSA mock sets, System Design framework drills, all interview-question files + **Behavioral track (05)** — build your STAR story bank |

### If you have 2 weeks (crash mode)
1. DSA: `12-mock-interview-sets.md` top-30 list — solve only those, by pattern.
2. System Design: `08-interview-framework-and-questions.md` + 4 case studies (URL shortener, chat, news feed, rate limiter).
3. MERN/K8s: `09-interview-questions.md` only.
4. GenAI: `03-transformers-and-llms.md`, `05-rag.md`, `06-agents-and-tool-use.md`, `10-interview-questions.md`.

---

## Running the DSA Code

Every problem includes a complete Python solution with a test driver:

```bash
# save any solution block to a file, then:
python3 solution.py
```

Or paste into an online compiler: [Programiz](https://www.programiz.com/python-programming/online-compiler/), [Replit](https://replit.com), or LeetCode's playground.

---

## Signaling Seniority (10–12 yr candidates)

Interviewers at this level grade you on judgment, not recall:

- **Always state trade-offs** ("I'd pick Kafka over SQS here because X, at the cost of Y").
- **Talk about failure modes first-class** (what happens when the cache dies, when the region goes down, when the model hallucinates).
- **Quantify** — do back-of-envelope math out loud (QPS, storage, cost).
- **Scope ruthlessly** — clarify requirements before designing; say what you're explicitly NOT building.
- **Own operations** — mention monitoring, rollout strategy, on-call impact. Staff engineers think past "it works".

Good luck. Do the reps.
