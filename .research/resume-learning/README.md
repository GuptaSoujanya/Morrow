# Whisper and AWS (Bedrock, EC2)

## What it is

This file covers two AWS-adjacent pieces of the stack: **Whisper**, OpenAI's open-source automatic speech recognition (ASR) model used here for audio transcription, and **AWS** infrastructure - specifically **Bedrock** (AWS's managed service for calling foundation models like Claude, including Claude's extended-thinking mode) and **EC2** (the compute the evaluation platform's pipeline runs on). These are grouped together because they represent the "real infrastructure" layer that turns model-calling code and audio-processing code into a deployed, production system.

## How you used it

Per the resume, the evaluation platform includes **Whisper audio transcription** and **multimodal trajectory handling** as part of taking the platform to production, and separately the **LiteLLM inference sidecar** routes **Claude on AWS Bedrock (with extended thinking)** alongside GPT-5.5 and OpenRouter. The **dated delivery pipeline runs on EC2 with Git LFS**. The **AWS Academy Cloud Architecting** and **AWS Academy Cloud Foundations** certifications listed under Education & Certifications reinforce that AWS fundamentals (not just the two services used in this specific platform) are part of your background.

## Core concepts

**1. What Whisper does and how it's used in a trajectory pipeline.** Whisper is a sequence-to-sequence transformer trained on a large corpus of audio paired with transcripts, supporting multiple model sizes (tiny through large) trading accuracy for speed/compute cost. In an evaluation-harness context, a persona-pack task that includes a recorded voice interaction gets run through Whisper to produce a text transcript, which then becomes part of the trajectory that judges and pytest suites operate on (as covered in the agent-evaluation-harnesses and judge files) - keeping the scoring pipeline uniform across text, tool-call, and now transcribed-audio content.

```python
import whisper

model = whisper.load_model("small")
result = model.transcribe("persona_task_042.wav", language="en")

trajectory_entry = {
    "type": "audio_transcript",
    "text": result["text"],
    "segments": result["segments"],  # timestamped chunks, useful for alignment
}
```

**2. Model-size tradeoffs and why they matter for a production pipeline.** Larger Whisper models (medium, large) are more accurate, especially on accented speech, background noise, or domain-specific vocabulary, but cost more compute and take longer per transcription - a real tradeoff when running at benchmark scale inside resource-limited, sandboxed containers (as described in the Docker/CI file) rather than on a dedicated GPU box. Choosing a model size is a deliberate accuracy-versus-throughput decision, not a default.

**3. Offline/vendored Whisper weights.** Consistent with the no-live-network sandbox constraint described elsewhere, Whisper's model weights need to be downloaded once and baked into the sandbox image (or mounted from a pre-fetched cache) rather than fetched from the internet at run time inside an isolated container.

```dockerfile
# at build time, with network access
RUN python -c "import whisper; whisper.load_model('small')"
# this caches the weights into the image's filesystem (e.g., ~/.cache/whisper)
```

**4. Why extended thinking needs special handling on Bedrock.** Claude's extended-thinking mode produces an internal reasoning block before its final answer, consuming its own token budget. On Bedrock specifically, this means the request needs a thinking-budget parameter, and the response needs to be parsed to separate the thinking content from the final answer - the gateway (LiteLLM, covered in its own file) is the layer that normalizes this across providers, but understanding the raw mechanics matters for debugging when something looks wrong (e.g., unexpectedly high token cost, or a judge accidentally being shown the raw thinking trace when it shouldn't be).

```python
import boto3
import json

client = boto3.client("bedrock-runtime", region_name="us-east-1")
response = client.invoke_model(
    modelId="anthropic.claude-sonnet-...",
    body=json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 4096,
        "thinking": {"type": "enabled", "budget_tokens": 2048},
        "messages": [{"role": "user", "content": "..."}],
    }),
)
result = json.loads(response["body"].read())
thinking_block = next(b for b in result["content"] if b["type"] == "thinking")
answer_block = next(b for b in result["content"] if b["type"] == "text")
```

**5. Why Bedrock specifically, rather than calling Anthropic's API directly.** Bedrock gives AWS-native IAM-based access control, billing consolidated into existing AWS infrastructure, and regional data-residency options - relevant when a platform already runs its compute (EC2, the delivery pipeline) inside AWS and wants a single cloud provider's security/billing boundary rather than managing a separate API key and billing relationship with each model vendor directly. This is a common enterprise reason to route Claude traffic through Bedrock instead of Anthropic's API, even though the model itself is the same.

**6. EC2 as the compute layer for the whole platform.** EC2 instances host the containerized sandbox runs (per the Docker/CI file), likely sized and selected based on the workload - CPU-optimized instances for running many concurrent lightweight mock-service containers, versus needing more memory/CPU headroom if Whisper transcription or other heavier processing runs on the same instances rather than being offloaded elsewhere.

**7. IAM and least-privilege for Bedrock access.** A production system calling Bedrock should use an IAM role (attached to the EC2 instance or the container's execution role) scoped to only the specific Bedrock model invocation permissions it needs, rather than long-lived access keys embedded in code or configuration - this is foundational AWS security practice and directly testable interview material given the AWS Academy certifications on the resume.

```json
{
  "Effect": "Allow",
  "Action": ["bedrock:InvokeModel"],
  "Resource": "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-sonnet-*"
}
```

**8. Cost visibility across AWS services and model providers.** The LiteLLM sidecar's per-request cost tracking (covered in its own file) needs to reconcile with AWS's own Bedrock billing and EC2 compute costs to get a true total cost of running the evaluation platform - model-inference cost and infrastructure cost are tracked by different systems (LiteLLM's cost callbacks versus AWS Cost Explorer/billing), and a mature platform needs both views to answer "what does running this benchmark actually cost end to end."

**9. Multimodal trajectory handling, tying it together.** A trajectory that includes an audio segment carries both the raw audio reference and its Whisper-derived text, timestamp-aligned (via Whisper's `segments` output) so that a judge or reviewer can, if needed, listen to the specific moment a transcript claims a safety red line was crossed, rather than trusting the transcript blindly - this matters especially for the persona-pack safety-red-line scenarios described in the agent-evaluation-harnesses file, where getting the exact wording and tone of a spoken instruction right can change how a response should be judged.

## Interview questions and answers

**Q1: Why use Whisper for transcription instead of a cloud ASR API like AWS Transcribe?**
Whisper can run fully offline once its weights are vendored, which matters for a sandboxed evaluation environment with no live network access; a cloud ASR API would need network calls out of the sandbox on every transcription, breaking the isolation guarantees the rest of the platform relies on.

**Q2: What's the accuracy/speed tradeoff across Whisper model sizes, and how would you choose one for a benchmark pipeline running at scale?**
Larger models (medium/large) are more accurate on accented speech, noise, and domain vocabulary but slower and more compute-hungry per transcription; at benchmark scale inside resource-limited sandboxed containers, you'd pick the smallest model size that still meets an acceptable accuracy bar for the task's actual audio characteristics, rather than defaulting to the largest model.

**Q3: Why route Claude traffic through AWS Bedrock instead of calling Anthropic's API directly?**
Bedrock gives AWS-native IAM access control, billing consolidated with existing AWS infrastructure, and regional data-residency options, which matters for an enterprise platform that already runs its compute on AWS and wants one cloud provider's security and billing boundary rather than a separate vendor relationship per model provider.

**Q4: How does Claude's extended-thinking mode change token cost tracking, and why does it matter on Bedrock specifically?**
Extended thinking produces a reasoning trace billed as its own token budget, separate from the final answer; cost tracking has to record thinking tokens as a distinct line item, and on Bedrock the request itself needs a thinking-budget parameter and the response needs parsing to separate the thinking block from the answer block - getting this wrong either undercounts real cost or accidentally leaks the raw reasoning trace somewhere it shouldn't be surfaced.

**Q5: What IAM practice would you follow for a service calling Bedrock from EC2?**
Attach a scoped IAM role to the EC2 instance (or the container's execution role) with only `bedrock:InvokeModel` permission on the specific model ARNs actually needed, rather than embedding long-lived access keys in code or config - least privilege, and credentials that rotate automatically rather than needing manual secret management.

**Q6: How would you keep Whisper's model weights available inside a sandbox that has no live network access at run time?**
Download and cache the weights at Docker image build time (when the build environment does have network access), baking them into the image filesystem, so the container never needs to fetch them when actually running a sandboxed, network-isolated task.

**Q7: Why might you offload Whisper transcription to separate infrastructure rather than running it inside the same sandboxed task containers?**
If transcription is CPU/GPU-intensive relative to the lightweight mock-service containers, running it inline could slow down or resource-starve the main task execution; a separate transcription step (still within the no-live-network constraint, but on differently-sized infrastructure) can be sized independently for throughput without affecting the sandboxed agent-execution containers' resource budgets.

**Q8: How do you reconcile LiteLLM's per-request cost tracking with actual AWS billing for Bedrock usage?**
LiteLLM's cost callbacks estimate cost per request based on token counts and known provider pricing, which should be periodically cross-checked against AWS Cost Explorer or Bedrock's own billing data for the same time window - discrepancies can reveal pricing-table drift (if a provider changes prices) or bugs in token accounting (e.g., thinking tokens not being counted correctly).

**Q9: What's a security risk specific to running an evaluation platform with Bedrock access from a sandboxed agent environment?**
If the agent-execution sandbox container somehow had the same IAM credentials as the orchestrating harness process, a compromised or adversarial agent could potentially make arbitrary Bedrock calls outside the intended evaluation flow; the mitigation is making sure only the orchestrating harness process (not the agent's own sandboxed execution context) holds Bedrock-calling credentials, with the agent only ever interacting with mock services.

**Q10: Why keep timestamp-aligned segments from Whisper rather than just the final transcript text?**
For persona-pack tasks with safety red lines or precise timing requirements, a reviewer or judge sometimes needs to verify the exact spoken wording and tone at a specific moment rather than trusting a flattened transcript - timestamped segments let you go back to the exact audio moment a judgment is being made about, which matters a lot when grading subjective, high-stakes scenarios.

## Hands-on

1. **Transcribe a short audio clip with Whisper locally.** Load the `tiny` or `base` model, transcribe a short recorded or downloaded sample clip, and inspect the `segments` output to see the timestamp-aligned chunks alongside the flattened `text` field.
2. **Write a minimal Bedrock extended-thinking request.** Using boto3 against a sandboxed/mocked Bedrock client (or by reading AWS's documented request/response shape if you don't have live Bedrock access), construct the request body enabling the `thinking` parameter and write a parser that separates the `thinking` content block from the `text` answer block in the response.

## Read next

- [OpenAI Whisper repository and documentation](https://github.com/openai/whisper)
- [AWS Bedrock documentation](https://docs.aws.amazon.com/bedrock/)
- [Anthropic extended thinking documentation](https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking)
- [AWS IAM best practices](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html)
- [../../course/04-ml-genai-agents/03-transformers-and-llms.md](../../course/04-ml-genai-agents/03-transformers-and-llms.md)
- [../../course/01-system-design/06-observability-and-reliability.md](../../course/01-system-design/06-observability-and-reliability.md)
- [Whisper and AWS (Bedrock, EC2)](12-whisper-aws.md)
