# Docker, CI/CD, EC2, and Git LFS

## What it is

This file covers the production/delivery infrastructure that turns an evaluation platform from "runs on my machine" into something reliably reproducible and shippable: **Docker** for sandbox isolation and dependency packaging, **CI/CD** for automated delivery pipelines, **EC2** as the compute environment benchmark runs execute on, and **Git LFS** for versioning large binary/trajectory artifacts that don't belong in a normal git history.

## How you used it

The resume states you took the agent evaluation platform to production with **Docker sandbox isolation, offline dependency vendoring, Whisper audio transcription, multimodal trajectory handling, and a dated delivery pipeline running on EC2 with Git LFS**. Each piece addresses a specific production concern: Docker isolates untrusted/semi-autonomous agent execution from the host and from real external systems; offline vendoring means the sandbox never needs live internet access (removing both a reliability dependency and a potential exfiltration path); the delivery pipeline is "dated," meaning each release is a timestamped, reproducible snapshot rather than a floating branch; EC2 is the compute environment hosting the benchmark runs; and Git LFS handles the large trajectory and dataset files (including multimodal/audio content) that a normal git repository would choke on.

## Core concepts

**1. Why Docker for agent sandboxing specifically.** An agent under evaluation might call arbitrary tools, and if those tools are real (even mock) services with real processes behind them, you want a hard boundary preventing the agent from affecting anything outside its own task run. A container gives process isolation, a controlled filesystem, and (critically) a network namespace you can lock down to only the mock services the task needs - no live internet.

```dockerfile
FROM python:3.11-slim

# vendor all dependencies at build time - no pip install at runtime
COPY vendor/ /opt/vendor/
RUN pip install --no-index --find-links=/opt/vendor/ -r requirements.txt

COPY harness/ /app/harness/
WORKDIR /app
ENTRYPOINT ["python", "-m", "harness.run_task"]
```

```bash
docker run --rm --network=mock-services-only \
  --memory=2g --cpus=2 \
  -v "$TASK_DIR:/app/task:ro" \
  eval-sandbox:latest --task-id "$TASK_ID"
```

The `--network` flag here is doing real work: it attaches the container only to a Docker network that contains the mock services (and nothing else), so even if an agent tries to reach the real internet, there's no route to it.

**2. Offline dependency vendoring.** "Vendoring" means downloading and bundling dependencies into the image or repo at build time, rather than fetching them at run time. For a sandbox with no live network access, this isn't optional - any tool call that triggers a `pip install` or `npm install` at runtime would simply fail. It also makes builds reproducible: the exact dependency versions are frozen into the image rather than resolved fresh (and potentially differently) on every build.

```bash
# at image-build time, on a machine with internet access
pip download -r requirements.txt -d vendor/
# later, inside the no-network sandbox build
pip install --no-index --find-links=vendor/ -r requirements.txt
```

**3. Resource limits as part of sandboxing, not just performance.** Memory and CPU limits (`--memory`, `--cpus` above) aren't only about fair resource sharing across concurrent benchmark runs - they're a safety mechanism paired with the tool-call/token/time budgets described in the agent-evaluation-harnesses file, so a runaway agent or sub-agent can't consume unbounded host resources.

**4. The "dated delivery pipeline" pattern.** Rather than deploying off a continuously-moving branch, each production delivery is tagged/stamped with a date (or a date-plus-build-number) and treated as an immutable snapshot. This matters enormously for an evaluation platform because benchmark results need to be reproducible against the exact platform version that produced them - if someone asks "why did this model score X on this task," you need to be able to check out the exact harness, mock-service, and rubric version from that date, not whatever the harness looks like today.

```yaml
# simplified CI pipeline concept
stages:
  - build
  - test
  - tag-and-deliver

tag-and-deliver:
  script:
    - DATE_TAG="delivery-$(date +%Y%m%d)-${CI_PIPELINE_ID}"
    - git tag "$DATE_TAG"
    - docker build -t "eval-platform:$DATE_TAG" .
    - docker push "eval-platform:$DATE_TAG"
  only:
    - main
```

**5. Why EC2 rather than a fully managed CI runner or serverless platform.** Running many concurrent sandboxed containers for a large benchmark sweep (potentially across 101 mock services and multiple models/judges per task) needs sustained compute with full control over networking (for the locked-down mock-service-only network) and storage (for trajectory artifacts), which is more naturally handled on EC2 instances you provision and configure directly than on a shared, time-limited CI runner or a serverless function with execution-time and local-disk constraints.

**6. Git LFS fundamentals.** Git stores every version of every file in its object database forever; a binary file (audio recordings, large trajectory JSON dumps, model checkpoints) that changes between commits bloats the repo permanently and makes clones slow. Git LFS replaces the actual file content in the repo with a small pointer file, storing the real content in a separate LFS store, fetched on demand.

```bash
git lfs install
git lfs track "*.wav" "trajectories/*.jsonl.gz"
git add .gitattributes
git add some_large_trajectory.jsonl.gz
git commit -m "add trajectory artifact"
```

```text
# what actually gets committed to the git history (a pointer, not the blob)
version https://git-lfs.github.com/spec/v1
oid sha256:4d7a214614ab2935c943f9e0ff69d22eadbb8f32b1258daaa5e2ca24d17e2393
size 52428800
```

**7. Why Git LFS matters specifically for this platform.** Multimodal trajectory handling means some task runs include recorded audio (fed through Whisper) and the resulting trajectory logs can be large; a dated delivery pipeline that snapshots the full platform state, including example trajectories or regression-test fixtures, would make the repository unusably large and slow to clone without LFS managing those specific large files separately.

**8. Whisper in the production pipeline.** Whisper transcribes audio inputs (e.g., a persona-pack task involving a recorded voice interaction) into text that becomes part of the trajectory the judges and pytest suites operate on. In production this typically runs as a step inside the same sandboxed container (vendored as an offline model/dependency, consistent with the no-live-network constraint) or as a separate pre-processing service that hands off transcribed text plus the original audio reference to the main harness run.

```python
import whisper

model = whisper.load_model("base")  # model weights vendored/cached offline
result = model.transcribe("task_audio.wav")
transcript_text = result["text"]
```

**9. CI/CD beyond delivery tagging.** The build and test stages of the pipeline run the same pytest suites (and likely a smaller internal regression benchmark) against every candidate change to the harness or mock services before it's eligible to be tagged for delivery - this is standard CI practice, but it matters more than usual here because the harness itself is the grading infrastructure, so a bug in the harness can silently corrupt every benchmark score it produces until caught.

## Interview questions and answers

**Q1: Why run agent evaluation inside Docker rather than directly on the host?**
Containers give process and filesystem isolation plus a controllable network namespace, so an agent under test - which might call arbitrary tools - can be restricted to only reach the mock services it needs, with no path to the real internet or the host system. This is a hard security/reliability boundary that running directly on the host can't give you as cleanly.

**Q2: What does "offline dependency vendoring" solve, and what would break without it?**
It means all dependencies are downloaded and bundled into the image ahead of time rather than fetched at runtime; without it, a fully network-isolated sandbox (required for safe agent execution) would fail the moment any setup step tried to `pip install` or `npm install`, and even with partial network access, runtime dependency resolution isn't reproducible across builds.

**Q3: Why is a "dated" delivery pipeline important for an evaluation platform specifically?**
Benchmark scores need to be reproducible against the exact platform version that produced them - rubrics, mock-service behavior, and judge prompts can all change over time. A dated, immutable snapshot lets you answer "why did model X score Y on this task" months later by checking out the exact delivery that produced that score, rather than whatever the current branch looks like.

**Q4: What problem does Git LFS solve that plain git doesn't?**
Plain git stores every version of every file forever in its object history, which is fine for text/code but makes repos with large or frequently-changing binaries (audio files, big trajectory dumps) bloat and slow to clone. LFS stores a small pointer in the git history and keeps the actual blob in a separate store fetched on demand, keeping the repo itself fast.

**Q5: Why choose EC2 over a managed CI runner for running the benchmark sweeps?**
Running many concurrent sandboxed containers with controlled, locked-down networking and enough local storage for trajectory artifacts needs sustained, fully-controllable compute; shared CI runners often impose execution-time limits and less networking control than you'd want for a fleet of isolated mock-service networks.

**Q6: How do resource limits on the Docker sandbox (memory, CPU) relate to the agent-level tool-call/token/time budgets?**
They're complementary layers of the same safety idea: the agent-level budgets (50 tool calls, 16k tokens, 600 seconds) bound an individual agent's behavior logically, while container resource limits bound the physical resource consumption of the whole sandboxed process, catching cases - like a runaway subprocess spawned by a tool - that the logical budgets alone might not.

**Q7: Where does Whisper fit in the pipeline, and why does it need to run inside the same sandboxing constraints?**
Whisper transcribes audio task inputs into text that becomes part of the trajectory judges and pytest operate on. Since transcription is part of processing (potentially sensitive) task content, it runs within the same offline, sandboxed environment as everything else, with the model weights vendored ahead of time rather than fetched over the network at run time.

**Q8: What would you check first if a benchmark delivery suddenly produced different scores than the previous one for the same tasks?**
Diff the dated delivery tags to see what actually changed - harness code, mock-service behavior, rubric wording, or judge prompts - since the dated/tagged pipeline makes this a straightforward git diff between two known-good reference points, rather than guessing at what changed in a continuously moving branch.

**Q9: How would you decide what to track with Git LFS versus what stays as plain git-tracked text?**
Track large or frequently-changing binaries - audio files, compressed trajectory dumps, model checkpoints - via `.gitattributes` patterns; keep code, configs, and rubric text (which benefit from normal diffing and small size) as plain git-tracked files, since LFS adds overhead that's wasted on small text files that diff well anyway.

**Q10: What's a concrete failure you'd design the CI pipeline to catch before a delivery is tagged?**
A regression where a change to a mock service's admin API accidentally makes it visible in the public OpenAPI schema (breaking the hidden-admin-API assumption drift injection relies on) - a CI test that asserts the admin routes are absent from `/openapi.json` for every mock service would catch this before it's tagged and delivered.

## Hands-on

1. **Write a locked-down Docker run command.** Build a minimal image with vendored dependencies (pick any small Python package, download its wheel ahead of time, install with `--no-index`), and run it with `--network=none` to confirm it still works without live internet access - then intentionally add a runtime `pip install` call and confirm it fails exactly as expected.
2. **Set up Git LFS on a scratch repo.** Initialize a new repo, run `git lfs track "*.bin"`, commit a large binary file, then run `git cat-file -p HEAD:yourfile.bin` and observe that the committed content is a small LFS pointer, not the actual binary data.

## Read next

- [Docker documentation](https://docs.docker.com/)
- [Git LFS documentation](https://git-lfs.com/)
- [AWS EC2 documentation](https://docs.aws.amazon.com/ec2/)
- [OpenAI Whisper repository and docs](https://github.com/openai/whisper)
- [../../course/03-fullstack-mern-kubernetes/06-docker-cicd.md](../../course/03-fullstack-mern-kubernetes/06-docker-cicd.md)
- [../../course/03-fullstack-mern-kubernetes/08-production-operations.md](../../course/03-fullstack-mern-kubernetes/08-production-operations.md)
