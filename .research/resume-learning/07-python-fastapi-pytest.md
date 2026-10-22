# Python, FastAPI, and pytest

## What it is

Python is the language underneath nearly every system described elsewhere in this set of notes - the evaluation harness, the LangChain pipelines, the LiteLLM sidecar integration. FastAPI is a Python web framework built on type hints and Pydantic models, chosen heavily in this kind of work because it makes it fast to stand up many small, strictly-typed HTTP services (exactly what a mock-service fleet needs). pytest is Python's dominant testing framework, used here not just for unit-testing application code but as a first-class *grading mechanism* inside the evaluation harness itself.

## How you used it

The resume's skills list names **Python** as a primary language and **FastAPI** and **pytest** explicitly under Data & Infra / Languages. Concretely: the drift-injection system is built on **101 FastAPI mock services** (Slack, GitHub, Stripe, Gmail, etc.), each presumably a small FastAPI app with its own routes, mutable store, and hidden admin endpoints. The grading system is backed by **weighted pytest suites (both LLM-generated and hand-written)** as a second scoring path alongside the three-judge council - meaning pytest here isn't testing your own code's correctness, it's asserting facts about agent trajectories and mock-service final state to produce benchmark scores.

## Core concepts

**1. FastAPI's type-driven request/response model.** FastAPI uses Python type hints and Pydantic to validate requests and serialize responses automatically, which matters a lot when you're hand-rolling 101 mock services - you want each one defined declaratively and correctly, not via manual JSON parsing in every handler.

```python
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class Message(BaseModel):
    channel: str
    text: str

@app.post("/channels/{name}/messages")
def post_message(name: str, body: Message):
    store[name]["messages"].append(body.model_dump())
    return {"ok": True}
```

**2. Structuring many mock services without duplicating boilerplate.** With 101 services, a factory pattern that generates a FastAPI app (or router) from a declarative service spec avoids writing near-identical CRUD boilerplate 101 times:

```python
def make_mock_service(name: str, resources: dict) -> FastAPI:
    app = FastAPI(title=name)
    store = {r: {} for r in resources}

    for resource in resources:
        app.include_router(build_resource_router(resource, store))

    # hidden admin router, mounted separately and not advertised in the agent's tool list
    app.include_router(build_admin_router(resource, store), prefix="/_admin")
    return app
```

**3. Separating the public and admin API surfaces.** The drift-injection design depends on the admin API being reachable by the host-side director but invisible to the agent. In FastAPI this is usually done by mounting the admin router under a path/prefix that's simply never included in the OpenAPI schema or tool manifest exposed to the agent, and sometimes additionally gated by an internal-only header or network path.

```python
admin_router = APIRouter(prefix="/_admin", include_in_schema=False)

@admin_router.post("/channels/{name}/inject")
def inject(name: str, body: Message):
    store[name]["messages"].append(body.model_dump())
    return {"injected": True}
```

**4. Dependency injection for shared state.** FastAPI's `Depends()` system is a clean way to share the mutable store, auth checks, or request logging across many route handlers without repeating setup code in every function:

```python
from fastapi import Depends

def get_store():
    return app.state.store

@app.get("/channels/{name}/messages")
def list_messages(name: str, store: dict = Depends(get_store)):
    return store[name]["messages"]
```

**5. Async vs. sync handlers.** FastAPI supports both `def` and `async def` route handlers; for mock services that don't do real I/O (no actual network calls, no real database round-trips), plain `def` handlers are simpler and FastAPI runs them in a thread pool automatically. Async matters once a service needs to await something genuinely asynchronous (a real database driver, an outbound call), which is more relevant to the LiteLLM sidecar and real backend services than to in-memory mocks.

**6. pytest as a benchmark grader, not just a test runner.** The unusual and important idea here is pytest being pointed at *trajectory data* rather than at your own source code. A "test" in this context is a parametrized assertion about what the agent did or what the final mock-service state looks like:

```python
import pytest

@pytest.mark.weight(3)  # custom marker for weighted scoring
def test_refund_issued_correct_amount(trajectory, final_state):
    refunds = final_state["stripe"]["refunds"]
    assert len(refunds) == 1
    assert refunds[0]["amount"] == 4200

@pytest.mark.weight(1)
def test_agent_confirmed_before_refund(trajectory):
    confirm_steps = [s for s in trajectory if s.action_type == "ask_confirmation"]
    assert len(confirm_steps) >= 1
```

A pytest plugin or conftest.py fixture loads the specific task's trajectory and final state into each test via fixtures (`trajectory`, `final_state` above), and a custom marker (`weight`) lets the harness combine individual test results into the weighted score described on the resume - failing a weight-3 safety check costs more than failing a weight-1 formatting check.

```python
# conftest.py
import pytest

@pytest.fixture
def trajectory(request):
    return load_trajectory(request.node.task_id)

@pytest.fixture
def final_state(request):
    return load_final_mock_state(request.node.task_id)
```

**7. LLM-generated vs. hand-written pytest tests.** Hand-written tests are authored by someone who designed the task and knows exactly what correct behavior looks like; LLM-generated tests are proposed by a model reading the task rubric and then reviewed by a human before being trusted into the weighted suite - this scales test coverage across many tasks without losing a human correctness check, directly mirroring the practice described in the LLM-as-judge and fine-tuning files.

**8. Collecting and running tests dynamically per task.** Since each benchmark task may have its own test file (or a dynamically generated one), the harness needs to point pytest at a per-task test module and collect results programmatically rather than via the CLI:

```python
import pytest

class ResultCollector:
    def __init__(self):
        self.results = []
    def pytest_runtest_logreport(self, report):
        if report.when == "call":
            self.results.append((report.nodeid, report.outcome))

collector = ResultCollector()
pytest.main(["-q", f"tests/task_{task_id}.py"], plugins=[collector])
```

**9. Fixtures, parametrization, and markers as general pytest skills.** Beyond the benchmark-grading use case, these are the same features that make pytest effective for ordinary application testing: fixtures for setup/teardown and shared state, `@pytest.mark.parametrize` to run one test body against many input/expected pairs, and custom markers to categorize or select subsets of tests (`pytest -m weight`).

## Interview questions and answers

**Q1: Why use pytest to grade agent trajectories instead of writing a custom scoring script?**
pytest already provides test discovery, fixtures for shared setup, parametrization, markers for categorization, and clear pass/fail reporting - reusing it means the grading logic gets a mature, well-understood test-running infrastructure for free, and engineers writing new task-specific checks can use a framework they already know instead of learning a bespoke scoring DSL.

**Q2: How did you structure 101 FastAPI mock services without massive duplication?**
I used a factory/router-generation pattern: a declarative spec per service (name, resources, schema) builds a FastAPI app or router from shared helper functions, rather than hand-writing near-identical route handlers 101 times. Admin routes were mounted under a separate, schema-hidden prefix so the same factory could produce both the public and hidden admin surfaces consistently.

**Q3: How do you keep the hidden admin API actually hidden from the agent?**
The admin router is excluded from the OpenAPI schema (`include_in_schema=False`) and never listed in the tool manifest the agent is given, and in some cases gated by an internal-only path or header that only the host-side director process uses - so even an agent that tried arbitrary paths wouldn't discover it through the normal tool-definition flow it's given.

**Q4: What does a "weighted" pytest suite mean in practice, and how do you implement weighting?**
Each test carries a weight (via a custom pytest marker), and the harness's result collector sums weights for passed tests over total possible weight to get a score, rather than treating every test as equally important. This lets a single critical safety-behavior test outweigh several minor formatting checks in the final grade.

**Q5: What's the risk of LLM-generated pytest tests, and how do you mitigate it?**
An LLM can propose an assertion that's subtly wrong - too strict (fails correct behavior), too loose (passes incorrect behavior), or testing something the rubric didn't actually require. Mitigation is a human review step before any LLM-generated test is added to the trusted weighted suite, same as reviewing LLM-generated code before merging it.

**Q6: Why would you choose FastAPI specifically over Flask for a fleet of mock services?**
FastAPI's type-hint-driven request/response validation via Pydantic catches a lot of mock-service bugs (wrong field name, wrong type) at the framework level rather than at runtime inside a handler, and automatic OpenAPI schema generation is directly useful for building the agent's tool manifests from the same service definitions, which Flask doesn't give you out of the box.

**Q7: How do you run pytest programmatically against a dynamically generated per-task test file?**
Call `pytest.main()` with the specific test file path and a custom plugin/result-collector object registered via the `plugins` argument, capturing `pytest_runtest_logreport` hook calls to build a structured result list instead of relying on parsing CLI output text.

**Q8: What's the difference between a FastAPI dependency and just importing a shared module-level variable?**
`Depends()` makes the dependency explicit in the function signature (better for readability and for FastAPI's automatic docs), and critically it's overridable in tests - `app.dependency_overrides[get_store] = lambda: test_store` lets you swap in a test double without touching the route handler code, which a bare module-level import doesn't give you as cleanly.

**Q9: How would you test that a FastAPI mock service's admin-triggered mutation is actually invisible to the agent's normal flow?**
Write a test that calls the admin endpoint directly to mutate state, then calls the public endpoint and asserts the mutation is reflected (state changed correctly) and separately assert the admin route does not appear in the `/openapi.json` schema or in whatever tool-manifest-generation code derives the agent's available tools from that schema.

**Q10: If a benchmark task's pytest suite and the three-judge council disagree on a result, how do you debug it?**
Pull the full trajectory and final mock-service state for that task, re-run the specific failing pytest assertion manually against that exact state to confirm it's not a flaky or environment-dependent test, and separately read the judges' per-criterion evidence citations to see what they thought happened - a mismatch usually reveals either a mechanically precise failure the judges missed (confirming pytest was right) or a rubric criterion that was satisfied in spirit but not in the exact form pytest checked for (suggesting the test is too strict).

## Hands-on

1. **Build a tiny mock service factory.** Write a function that takes a resource name and returns a FastAPI router with GET/POST routes backed by an in-memory dict, plus a parallel hidden admin router (`include_in_schema=False`) that can mutate the same dict; verify via `/openapi.json` that only the public routes appear.
2. **Write a weighted pytest suite against trajectory fixtures.** Create a `conftest.py` with a `trajectory` fixture returning a hard-coded list of action dicts, write two tests with different `@pytest.mark.weight(n)` markers, and write a small result-collector script that computes a weighted pass score from the test run.

## Read next

- [FastAPI documentation](https://fastapi.tiangolo.com/)
- [pytest documentation](https://docs.pytest.org/en/stable/)
- [Pydantic documentation](https://docs.pydantic.dev/latest/)
- [../../course/03-fullstack-mern-kubernetes/01-nodejs-express.md](../../course/03-fullstack-mern-kubernetes/01-nodejs-express.md)
- [../../course/04-ml-genai-agents/07-evaluation-and-harness.md](../../course/04-ml-genai-agents/07-evaluation-and-harness.md)
