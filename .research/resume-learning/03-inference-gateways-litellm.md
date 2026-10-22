# Inference Gateways (LiteLLM)

## What it is

An inference gateway is a thin service that sits between your application code and one or more LLM providers, exposing a single, uniform API (usually the OpenAI chat-completions shape) while translating requests to whichever provider and model is actually being called underneath. LiteLLM is the most common open-source implementation of this pattern: you point your client at the LiteLLM proxy instead of at OpenAI, Anthropic, Bedrock, or OpenRouter directly, and the proxy handles provider-specific request/response translation, authentication, retries, and - critically for cost-sensitive systems - usage accounting.

Running it as a **sidecar** (a small service deployed alongside your main application, often in the same pod/host) rather than a shared central gateway means each workload gets its own instance with its own config, rate limits, and keys, without a single shared gateway becoming a bottleneck or single point of failure for every team using it.

## How you used it

Per the resume, you routed **Claude on AWS Bedrock (with extended thinking), GPT-5.5, and OpenRouter** through a **LiteLLM inference sidecar that handles prompt caching and tracks cost on every request**. This sidecar is the single integration point the evaluation harness (and the rest of the platform) calls into - instead of the harness code needing three different SDKs and three different auth schemes, it calls one LiteLLM endpoint with a `model` string, and the sidecar resolves that to the right backend, including Bedrock-specific handling for Claude's extended-thinking mode (which returns a reasoning block alongside the final answer and needs different token accounting than a standard completion).

## Core concepts

**1. Why a gateway instead of direct SDK calls per provider?** Without a gateway, every caller in the codebase needs provider-specific credentials, request shapes, and error-handling, and switching a benchmark from "GPT-5.5" to "Claude on Bedrock" means changing code, not just a config string. A gateway collapses this to one interface:

```python
import litellm

response = litellm.completion(
    model="bedrock/anthropic.claude-sonnet-...",  # or "gpt-5.5", "openrouter/..."
    messages=[{"role": "user", "content": "..."}],
)
```

**2. Deploying as a sidecar.** Running LiteLLM as a local proxy process next to the service that calls it (rather than as one shared remote deployment) means network latency to the gateway is near-zero, a crashed sidecar only affects its own workload, and per-workload rate limits or provider keys can be scoped without affecting other teams' traffic.

```yaml
# litellm sidecar config (simplified)
model_list:
  - model_name: claude-bedrock
    litellm_params:
      model: bedrock/anthropic.claude-sonnet-...
      aws_region_name: us-east-1
  - model_name: gpt-5.5
    litellm_params:
      model: openai/gpt-5.5
      api_key: os.environ/OPENAI_API_KEY
  - model_name: openrouter-mix
    litellm_params:
      model: openrouter/meta-llama/llama-4-maverick
      api_key: os.environ/OPENROUTER_API_KEY
```

**3. Extended thinking on Bedrock.** Claude's extended-thinking mode produces an internal reasoning trace before the final answer, and that trace consumes its own token budget separate from the visible response. A gateway that supports this properly needs to (a) pass through the thinking-budget parameter Bedrock expects, (b) decide whether to surface or strip the thinking block to callers depending on the use case (a judge prompt might want to see it; a user-facing chat probably shouldn't), and (c) account thinking tokens separately in cost tracking, since they're billed but not part of the visible completion.

**4. Prompt caching.** Several providers let you mark a prefix of your prompt (a long system prompt, a large tool-definition block, a big piece of retrieved context) as cacheable, so repeated calls that share that prefix are billed at a fraction of the normal input-token rate and return faster. In an evaluation harness, the task description, tool schemas, and rubric are often identical across many judge calls or many turns of the same task - prime candidates for caching.

```python
messages = [
    {"role": "system", "content": LONG_TOOL_SCHEMA, "cache_control": {"type": "ephemeral"}},
    {"role": "user", "content": current_turn_input},
]
```

The gateway's job is to pass the cache-control markers through correctly per provider (Anthropic, Bedrock, and OpenRouter-hosted models don't all implement caching identically) and to make sure cost tracking distinguishes cache-write tokens, cache-read (hit) tokens, and regular tokens, since each has a different price.

**5. Cost tracking on every request.** This is usually implemented as a callback hook the gateway fires after every completion, logging `(model, input_tokens, output_tokens, cached_tokens, thinking_tokens, cost_usd)` to a database or metrics system. At benchmark scale - hundreds of mock services, three-judge councils, multi-agent sub-agent spawns - cost can balloon invisibly without per-request accounting, so this becomes the primary lever for answering "which part of the benchmark is expensive" and for enforcing budgets.

```python
def cost_callback(kwargs, response, start_time, end_time):
    usage = response.usage
    cost = litellm.completion_cost(completion_response=response)
    log_cost(model=kwargs["model"], usage=usage, cost=cost, duration=end_time - start_time)

litellm.success_callback = [cost_callback]
```

**6. Retries and fallbacks.** A gateway is also the natural place to implement provider-level retry/backoff and model fallback chains (if Bedrock throttles, fall back to OpenRouter's hosted copy of a comparable model) without that logic leaking into every call site.

**7. Provider-agnostic benchmarking.** Because the harness calls one interface, swapping or adding a model under test - GPT, Claude, LLaMA via OpenRouter - is a config change, which is exactly what's needed to benchmark "OpenAI, Gemini, Claude, LLaMA, and Grok" (as the resume's model-evaluation bullet describes) without touching harness code for each new provider.

## Interview questions and answers

**Q1: Why run LiteLLM as a sidecar instead of a single shared gateway service?**
A sidecar keeps the gateway close (low latency) to the caller, isolates failures and rate limits per workload, and lets each workload tune its own provider config without affecting others. A shared central gateway becomes a bottleneck and a single point of failure across every team's traffic.

**Q2: How does extended thinking change cost tracking compared to a normal completion?**
Extended thinking produces a reasoning trace that consumes its own token budget, billed separately from the visible output. Cost tracking has to record thinking tokens as their own line item rather than lumping them into output tokens, since they have different pricing and the reasoning trace may or may not be surfaced to the caller.

**Q3: What's prompt caching and where does it pay off most in an eval harness?**
It lets you mark a prompt prefix - a long system prompt, tool schema, or rubric - as cacheable so repeated calls sharing that prefix are billed and served faster via a cache hit. It pays off most in judge calls (same rubric, many trajectories) and multi-turn agent tasks (same tool schema, growing conversation), where the cacheable prefix is large and reused across many requests.

**Q4: How would you track cost per task across a benchmark with hundreds of mock services and multiple judges?**
Every completion call fires a cost callback that logs model, token breakdown (input/output/cached/thinking), and dollar cost tagged with the task ID and judge/agent ID that made the call. Aggregating by task ID gives per-task cost; aggregating by judge or sub-agent ID shows which parts of the grading pipeline are the most expensive.

**Q5: What happens if a provider is down or rate-limiting you mid-benchmark?**
The gateway layer is where retry-with-backoff and fallback-to-a-different-provider logic lives, so a Bedrock throttle can fall back to an OpenRouter-hosted equivalent model without the harness code needing to know a failure happened - though the cost and latency characteristics of the fallback need to be logged distinctly so benchmark results aren't silently skewed.

**Q6: How do you add a new model provider to the benchmark without rewriting harness code?**
Add a new entry to the gateway's model list config pointing at the new provider/model, and reference it by name from the benchmark config. Because the harness only ever calls the gateway's uniform `completion()` interface, no call-site code changes.

**Q7: Why not call provider SDKs directly from the harness?**
Direct SDK calls mean the harness needs per-provider auth, request/response shape handling, and error semantics baked into business logic, making it hard to add providers or run the same task across many models for comparison. A gateway centralizes that complexity once.

**Q8: What's a subtle correctness bug you'd worry about with caching across providers?**
Cache-control semantics differ across providers (what counts as cacheable, minimum prefix length, cache lifetime), so a config that works for Anthropic directly may silently not cache (or error) when the same model is reached via Bedrock or OpenRouter. You need provider-specific testing of the cache-hit rate, not just a single "it worked once" check.

**Q9: How do you budget cost for a large evaluation run before it starts?**
Use historical cost-per-task data from the tracking logs to estimate per-task average cost for a given model and multiply by the number of tasks and judges; this is also why cost tracking on every single request (not just aggregated sampling) matters - estimates based on rough sampling undercount outlier-expensive tasks like long multi-agent trajectories.

**Q10: What's the tradeoff of using OpenRouter versus calling a provider like Bedrock directly?**
OpenRouter gives access to many models (including ones you can't reach directly, like certain open-weight models) through one API and can be cheaper or more available for some models, but adds another hop and another party's reliability/latency into the path, and its pricing and rate limits are separate from the underlying provider's - cost tracking has to treat it as its own provider, not assume it inherits the underlying model's normal pricing.

## Hands-on

1. **Stand up a local LiteLLM proxy** with two model entries (e.g., any OpenAI-compatible model and a mocked/local model) and call both through the same `litellm.completion()` interface, logging token usage and cost via a `success_callback`.
2. **Simulate prompt caching savings.** Write a function that computes cost for N repeated calls with a shared 2000-token system prompt, once assuming no caching (full price every call) and once assuming a cache hit after the first call (discounted rate on the cached portion), and compare total cost.

## Read next

- [LiteLLM documentation](https://docs.litellm.ai/docs/)
- [AWS Bedrock documentation](https://docs.aws.amazon.com/bedrock/)
- [Anthropic prompt caching guide](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching)
- [OpenRouter documentation](https://openrouter.ai/docs)
- [../../course/04-ml-genai-agents/03-transformers-and-llms.md](../../course/04-ml-genai-agents/03-transformers-and-llms.md)
- [../../course/04-ml-genai-agents/08-fine-tuning-and-llmops.md](../../course/04-ml-genai-agents/08-fine-tuning-and-llmops.md)
