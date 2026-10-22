# Agent Evaluation Harnesses

## What it is

An agent evaluation harness is the scaffolding that lets you run an AI agent against a fixed set of tasks, capture everything it does (tool calls, reasoning, intermediate state), and produce a reproducible score at the end. A harness is different from a single "prompt and check the output" eval: agents act over multiple turns, call tools, and change the state of a simulated world, so the harness has to own three things:

- **Task definitions** - the starting state, the goal, and the pass/fail or partial-credit criteria.
- **An environment** - usually a set of mock services (APIs, databases, filesystems) the agent can act against instead of touching production systems.
- **An agent loop and scorer** - code that feeds the agent its context, executes whatever tools it calls, hands back results, and eventually judges the full trajectory against the task's rubric.

OpenClaw-style harnesses (the lineage WildClawBench forks from) add two further ideas on top of the basic loop: they treat the environment as *stateful and mutable during the run* (not just a static fixture), and they standardize how trajectories - including multimodal ones - are logged so that later stages (judges, pytest graders, humans) can replay exactly what happened.

## How you used it

At Ethara AI you grew the open-source WildClawBench benchmark, running on the OpenClaw harness, into an internal platform for evaluating frontier models. Concretely, per the resume:

- You built a **drift-injection system spanning 101 FastAPI mock services** such as Slack, GitHub, Stripe, and Gmail. Each mock service paired a **mutable store** with a **hidden admin API**, and a **host-side director** used that admin API to quietly change backend state mid-run - testing whether an agent re-checks its assumptions instead of trusting stale context.
- You added **bounded multi-agent support**: a task could spawn up to **5 concurrent sub-agents**, each capped at **50 tool calls, 16k tokens, and 600 seconds**, with a **full audit trail of every spawn**.
- You wrote **13-turn persona task packs** featuring staged silent mutations, safety red lines, and confirmation gates - adversarial, narrative task scripts that exercise an agent's judgment, not just its tool-calling accuracy.
- You took the platform to production with **Docker sandbox isolation**, **offline dependency vendoring** (so the sandbox never needs live internet access), **Whisper audio transcription** and **multimodal trajectory handling**, and a **dated delivery pipeline running on EC2 with Git LFS** (for versioning the large trajectory/dataset artifacts).

## Core concepts

**1. The agent loop.** At its simplest:

```python
def run_task(agent, task, env):
    env.reset(task.initial_state)
    trajectory = []
    for turn in range(task.max_turns):
        observation = env.render()
        action = agent.step(observation, trajectory)
        result = env.execute(action)
        trajectory.append((observation, action, result))
        if env.is_terminal():
            break
    return trajectory
```

A real harness wraps this with timeouts, token budgets, and tool-call budgets per agent - exactly the 50-tool-call / 16k-token / 600-second caps described on the resume. Those caps exist because without them, a buggy or looping agent (or a malicious prompt-injection payload) can burn unbounded cost, and a multi-agent system without a spawn limit can fork exponentially.

**2. Mock services and the mutable store.** Instead of hitting the real Slack or Stripe API, the harness stands up a FastAPI service that *behaves* like Slack for the handful of endpoints a task needs (list channels, post message, read thread). The mock keeps its state in memory or a lightweight store (SQLite, a dict), and exposes that state only to the agent through the "public" surface of the API.

```python
from fastapi import FastAPI
app = FastAPI()
store = {"channels": {"general": {"messages": []}}}

@app.post("/channels/{name}/messages")
def post_message(name: str, body: dict):
    store[name]["messages"].append(body)
    return {"ok": True}
```

**3. Drift injection.** The key idea the resume highlights is that agents often cache an early observation ("channel #general has no messages") and act on it several turns later without re-checking. A drift-injection harness adds a second, *hidden* admin surface that a separate "director" process can call mid-task to mutate the store - e.g., someone else posts a message, a Stripe charge gets refunded, a GitHub PR gets closed - without the agent being told.

```python
@app.post("/_admin/channels/{name}/inject")  # hidden from the agent's tool list
def inject_message(name: str, body: dict):
    store[name]["messages"].append(body)
    return {"injected": True}

# host-side director, running alongside the agent loop
def director_step(turn_index, env):
    if turn_index == DRIFT_TURN:
        env.call_admin("/channels/general/inject", {"text": "actually, scope changed"})
```

Scoring then checks not just whether the agent reached the goal, but whether it *noticed* the drift - did it re-read state before acting on it, or did it act on a now-stale assumption? This is a much stronger signal of real-world robustness than static single-turn benchmarks.

**4. Persona task packs.** A "13-turn persona task pack" is a scripted, multi-turn conversation where a simulated user (a persona) has a particular communication style, makes staged silent mutations to the environment as the conversation proceeds, and occasionally tests a safety red line (e.g., "delete all the production data") expecting the agent to refuse or ask for confirmation. These packs combine conversational realism with the drift-injection mechanics above.

**5. Sandboxing and offline vendoring.** Running untrusted or semi-autonomous agent code means every task executes inside a Docker container with no real network access; all Python/Node dependencies the agent's tools might need are vendored into the image ahead of time so a run never depends on - or can exfiltrate data through - a live network call.

**6. Multimodal and audio trajectories.** Some tasks include voice input or recorded calls. Whisper transcribes that audio into text that becomes part of the trajectory log, so the same scoring pipeline (judges, pytest) can operate uniformly over text, tool calls, and transcribed speech.

**7. Delivery pipeline.** Benchmark runs, datasets, and trajectory logs get large (especially with audio/multimodal content), so they're stored with Git LFS and shipped through a dated pipeline on EC2 - each delivery is a dated snapshot rather than an ever-mutating branch, which matters for reproducibility when a client or judge model's behavior is later questioned.

## Interview questions and answers

**Q1: What's the difference between an eval harness and a benchmark dataset?**
A dataset is the set of tasks and expected outcomes; a harness is the runtime that executes an agent against those tasks, manages state, enforces resource limits, and produces scores. The same dataset can run under different harnesses with different sandboxing or scoring rules.

**Q2: Walk me through the drift-injection system you built.**
I built 101 FastAPI mock services modeling tools like Slack, GitHub, Stripe, and Gmail. Each had a mutable in-memory/SQLite store and a public API surface the agent could call. I added a hidden admin API per service that a host-side "director" process could call mid-run to change state - post a message, close a PR, refund a charge - without telling the agent. Scoring then checked whether the agent re-verified state before acting on stale assumptions, which is a much more realistic test of agentic robustness than a static single-turn benchmark.

**Q3: Why cap sub-agents at 50 tool calls, 16k tokens, and 600 seconds?**
Multi-agent systems can spawn sub-agents that spawn further sub-agents; without hard per-agent budgets, a single task can blow up in cost and wall-clock time, or never terminate if an agent gets stuck in a tool-call loop. The caps bound worst-case cost and let you detect and kill runaway agents deterministically, and the audit trail lets you reconstruct exactly which sub-agent did what if a run misbehaves.

**Q4: How do you prevent an agent under test from affecting real systems?**
Everything runs against mock services inside a Docker sandbox with no live network access; dependencies are vendored offline ahead of time. The agent only ever sees simulated Slack/Stripe/GitHub/Gmail endpoints, so even a compromised or adversarially-prompted agent can't reach anything real.

**Q5: What's a "persona task pack" and why use scripted personas instead of free-form user turns?**
A persona pack is a scripted multi-turn (13-turn, in our case) conversation with a defined communication style, staged environment mutations at specific turns, and built-in safety red lines (e.g., a request to do something destructive) along with confirmation gates. Scripting it lets you reproduce the exact same adversarial scenario across model versions and compare behavior apples-to-apples, which free-form user simulation can't guarantee.

**Q6: How do you evaluate an agent that failed a task - was it the model, the harness, or the mock service?**
This is why full trajectory logging matters: you can replay the exact sequence of observations, actions, and results. If the mock returned malformed data, that's a harness bug; if the agent had the right data and still acted wrong, that's a model/reasoning failure. Separating these requires the mock service's behavior and the admin-driven mutations to be deterministic and logged alongside the agent's own actions.

**Q7: Why run on EC2 with Git LFS instead of a managed CI runner?**
Trajectory artifacts, especially multimodal ones with transcribed audio, get large and don't diff well in git - Git LFS stores pointers in the repo and the actual blobs in a separate store, keeping the repo itself fast to clone. EC2 gives control over long-running, resource-heavy benchmark sweeps (many concurrent sandboxed containers) that would be awkward or expensive on a shared CI runner with tighter time limits.

**Q8: How would you extend this harness to a brand-new tool integration, say a calendar API?**
Stand up a new FastAPI mock with the calendar endpoints the tasks need, back it with the same mutable-store-plus-admin-API pattern, write a handful of tasks exercising normal use and at least one drift scenario, and register it with the host-side director so it can be included in persona packs. The scoring layer (judges + pytest) doesn't need to change since it operates on the trajectory abstraction, not the specific tool.

**Q9: What failure modes does resource bounding (tool calls/tokens/time) actually catch in practice?**
Infinite retry loops where an agent keeps calling the same tool with the same arguments after a failure; context-window blowup from an agent re-reading large tool outputs repeatedly; and multi-agent fan-out where a coordinator spawns more sub-agents than the task needs. The audit trail turns "something ran too long" into "sub-agent 3, spawned at turn 7, hit the 600s cap while retrying a Stripe call."

**Q10: How is multimodal (audio) trajectory handling different from text-only?**
Audio has to be transcribed (Whisper) into text before most scoring logic - judges and pytest - can reason about it, but you still want to keep the raw audio in the trajectory for cases where transcription quality itself is being evaluated or where a human reviewer needs to listen back. So the trajectory format carries both the raw modality and a derived text view, with timestamps tying them together.

## Hands-on

1. **Build a tiny drift-injection mock.** Write a FastAPI service with a `/notes` list, a public `GET /notes` and `POST /notes`, and a hidden `POST /_admin/notes/inject` that appends a note without the "agent" knowing. Write a two-turn script: turn 1 the agent reads notes, turn 2 (after an injected note) the agent is asked "what's new?" - check whether your scoring logic can detect if a hard-coded "agent" that never re-reads would miss the injected note.
2. **Implement a bounded spawner.** Write a `Spawner` class with `max_children=5`, `max_tool_calls=50`, `max_tokens=16000`, `max_seconds=600` per child, and a list that records `(child_id, parent_id, start_time, tool_calls_used)` for every spawn - this is the audit trail pattern in miniature. Add a test that a sixth spawn attempt raises.

## Read next

- [OpenAI Evals framework docs](https://github.com/openai/evals)
- [Anthropic's guide to building effective agents](https://www.anthropic.com/research/building-effective-agents)
- [FastAPI official docs](https://fastapi.tiangolo.com/)
- [../../course/04-ml-genai-agents/06-agents-and-tool-use.md](../../course/04-ml-genai-agents/06-agents-and-tool-use.md)
- [../../course/04-ml-genai-agents/07-evaluation-and-harness.md](../../course/04-ml-genai-agents/07-evaluation-and-harness.md)
