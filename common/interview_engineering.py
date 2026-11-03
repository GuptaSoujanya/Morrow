"""Engineering notebooks shared by each week's seven connected lessons.

These are explicitly weekly companion cases, not 270 supposedly unique lessons.
Daily explanations, exercises and interviews remain topic-specific. The notebooks
connect those topics to a concrete implementation, numbers and failure paths.
"""
import re

from . import interview_course


_NOTEBOOKS = (
    {
        'title': '''A study tracker from input to evidence''',
        'ai_ml': '''The tracker has two different outputs. Its summary reports observed study time. Its prediction estimates the duration of an unseen lesson. Use an exact calculation for the first and evaluate whether a learned model is useful for the second. Keeping these outputs separate prevents a guessed value from being presented as a saved fact.

```mermaid
flowchart TD
  A[Earlier study sessions] --> B[Define features and duration label]
  B --> C[Split earlier and later examples]
  C --> D[Fit a baseline and candidate]
  D --> E[Choose with validation examples]
  E --> F[Measure on held-out sessions]
  F --> G[Compare errors and decide]
```

A feature must be available when planning the next lesson: its word count and topic can be known in advance, while its final duration cannot. A label is the duration observed afterwards. Record when each value becomes available. This timing check often matters more than the choice of model.

Separate learning parameters, choosing a version and evaluating the chosen version. Validation examples help choose among candidates. The held-out test checks the selected candidate. If you keep changing the model after seeing the final test result, that test has become part of selection and you need another honest evaluation.

Use the worked error calculation in this subject to compare a fixed 25-minute baseline with a candidate. Then inspect groups: does the improvement hold for short lessons, long lessons and unfamiliar topics? A tiny example explains the arithmetic but cannot establish production quality. Save a result table with the split rule, number of observations, baseline and metric so another engineer can repeat the comparison.''',
        'system_design': '''Start with the summary feature before adding prediction or storage. Its request includes a list of minutes, its boundary checks the list, and its calculation returns a summary. The arrows must explain actual information: do not draw a model service or database when this operation needs neither.

```mermaid
sequenceDiagram
  participant Browser
  participant API
  participant Summary
  Browser->>API: POST minutes 20, 30, 40
  API->>API: Check JSON, types and limits
  API->>Summary: Valid durations
  Summary-->>API: Count 3, total 90, mean 30
  API-->>Browser: 200 with summary
```

Write the contract beside this diagram: the list limit, duration units, empty-list behavior and invalid-input response. A network failure before the request arrives and a lost response after calculation can look identical to the browser. Repeating this pure summary is safe because it changes no stored state. A future saved-session endpoint has different retry requirements.

Write a latency budget, meaning how you divide the allowed response time. For an illustrative 300 ms target, allow 100 ms for network travel, 50 ms for parsing and validation, 50 ms for computation, and 100 ms spare. Measure before treating these numbers as capacity facts. Sequential steps add; parallel branches contribute the slowest branch on the critical path. Averages can hide slow requests, so examine percentiles and errors.

At 100 requests per second and an average time in the system of 0.2 seconds, Little's Law gives an average of about 20 requests in flight under stable conditions. This is not a safe maximum. Bursts and slow dependencies can raise concurrency. Bound work and timeouts. When the project later saves sessions, add identity, ownership checks, durable storage and a duplicate-request policy explicitly.''',
        'full_stack': '''Treat the page and server as separate programs with one documented contract. The page owns the draft input and visible request state. The server owns validation and the returned summary. A button click is not proof of a response, and a summary response is not proof of a saved study session.

```mermaid
flowchart TD
  A[Enter study-session minutes] --> B{Input shape and values valid?}
  B -->|No| C[Keep input and show field error]
  B -->|Yes| D[Show pending state]
  D --> E[Request the summary]
  E --> F{Valid successful response?}
  F -->|Yes| G[Show count, total and mean]
  F -->|No| H[Keep input and offer retry]
```

Keep calculation separate from receiving HTTP and drawing the page. The implementation lab below returns a value from a pure function and uses a small handler to map validation failure to a client error. This makes tests fast and keeps the same arithmetic usable from a command line, a web handler or a later batch job.

Validate in the browser for helpful feedback and again on the server because another caller can bypass the page. Preserve the learner's typed data when a request fails. Distinguish an empty observed list from a request that never completed. For the empty list, count and total are zero and mean is absent; for a failed request, no summary is available.

Test two requests finishing in reverse order. Only the latest requested summary should update the current result. Abort obsolete work where possible and still check response ownership. On later days, connect an accessible form, JSON requests and stored sessions to this same tested calculation rather than rebuilding its rules in each layer.''',
    },
    {
        'title': 'A dashboard whose numbers can be trusted',
        'ai_ml': '''A numerical table needs a contract before it becomes training data. State what one row means, when it was collected, and what each column measures. Three deliveries with two features form a matrix with shape `(3, 2)`: three rows and two columns. A weight vector with shape `(2,)` produces three scores through matrix-vector multiplication. Element-wise multiplication is a different operation.

```mermaid
flowchart TD
  A[Raw rows and timestamps] --> B[Check types and units]
  B --> C[Separate train and evaluation rows]
  C --> D[Fit missing-value and scale rules on training rows]
  D --> E[Apply the same rules to each split]
  E --> F[Inspect quality by group]
```

For a row `[distance_km, stops] = [4, 2]`, weights `[3, 5]` and intercept 1 give `4*3 + 2*5 + 1 = 23` minutes. The column order is part of the model contract. Swap the values without changing their names and the calculation still runs but means something else. Shape checks alone cannot detect that error.

Missing data can mean “not recorded”, “not applicable” or an upstream failure. Those causes need different treatment. For a median replacement, calculate the median using training rows only, store it, and apply the stored value to validation and serving inputs. Add a missing-value flag when missingness itself may carry useful information, then evaluate whether that relationship remains stable.

The lists `[10, 10, 10]` and `[0, 10, 20]` have the same mean. Their population variances are 0 and `200/3`. A sample-variance calculation instead divides by `n-1`. State which quantity you are reporting. Inspect distributions, duplicates and extreme values before training. A low error is not meaningful if a repeated customer or future outcome leaks into both sides of the evaluation.''',
        'system_design': '''Define a dashboard number precisely: “sum of accepted session minutes for this learner during this UTC date range”. Decide whether corrections replace an earlier record or create a compensating record. An append-only event log and an editable sessions table need different aggregation rules.

```mermaid
sequenceDiagram
  participant Client
  participant API
  participant DB
  Client->>API: Submit session with unique request ID
  API->>DB: Insert once within a transaction
  DB-->>API: Saved row or existing result
  API-->>Client: Confirm saved ID
  Client->>API: Read weekly total
  API->>DB: Aggregate authorized rows and date range
  DB-->>API: Total plus update time
  API-->>Client: Render confirmed total
```

Use a database constraint for uniqueness, not only a check followed by an insert. Two requests can pass the same check before either inserts. A transaction groups changes, but its isolation level determines which concurrent effects are possible. With PostgreSQL Read Committed, separate statements can see different committed data. Choose locking or a stronger isolation level when the invariant requires it, and handle retryable conflicts.

For a weekly report, index columns that fit the filter, such as `(learner_id, started_at)`. Confirm with an execution plan and realistic data. The index costs write work and storage. It may not help a report that reads most rows. If you cache the total, define acceptable staleness and invalidate or version the cache after corrections.

Estimate storage separately from query cost. At 100,000 sessions per day and an assumed 200 bytes of logical fields per session, raw fields alone are about 20 MB per day. Row overhead, indexes, replicas and backups add more. State these assumptions rather than presenting the raw estimate as disk usage.''',
        'full_stack': '''A report query should preserve the people who have no activity. A left join retains those learners. Put conditions on the optional session rows inside the join when you want to retain learners with zero matching sessions.

```sql
SELECT l.id, COALESCE(SUM(s.minutes), 0) AS total_minutes
FROM learners AS l
LEFT JOIN sessions AS s
  ON s.learner_id = l.id
  AND s.started_at >= :start_at
  AND s.started_at < :end_at
WHERE l.id = :authorized_learner_id
GROUP BY l.id;
```

The named parameters are placeholders for your database driver's binding mechanism; do not build the query by joining user text. The half-open time range includes the start and excludes the end, so adjacent reporting windows do not double-count a boundary. `SUM` of no matched values is null, so `COALESCE` turns that result into zero. Group by identity, not a display name that two people can share.

```mermaid
flowchart TD
  A[Loading report] --> B{Request succeeds?}
  B -->|No| C[Error with retry]
  B -->|Yes| D{Rows exist?}
  D -->|No| E[Honest empty state]
  D -->|Yes| F[Totals and rows]
  F --> G[Correction saved]
  G --> A
```

Test a learner with sessions of 20 and 30 minutes, another with none, and a third with a session exactly at the end boundary. The first total is 50; the second is zero; the boundary session belongs to the next window. Joining another one-to-many table before aggregation can multiply session rows and inflate the total. Aggregate each relationship first or prove the join cardinality.

Keep “failed to load” distinct from zero. Show the measurement window and an update time beside the total. Verify that a user cannot change a query parameter to read another learner's report. That check belongs on the server.''',
    },
    {
        'title': 'A measured model behind a secure API',
        'ai_ml': '''Start model comparison with a loss and an evaluation design. For regression, mean squared error gives large mistakes extra weight because it squares each error. Mean absolute error is easier to interpret in the target's units. Neither metric alone explains how errors affect the product. Keep a simple baseline in the same report.

```mermaid
flowchart TD
  A[Training split] --> B[Fit preprocessing]
  B --> C[Fit candidate model]
  C --> D[Validation predictions]
  D --> E[Choose settings and threshold]
  E --> F[One final held-out comparison]
```

For binary classification, a score and a decision are separate. Suppose 10 of 100 cases are positive. A model flags 8 cases, of which 6 are truly positive. Precision is `6/8 = 75%`; recall is `6/10 = 60%`. Four positives were missed and two negatives were flagged. An always-negative baseline has 90% accuracy here but zero recall. Choose a threshold using the cost of these errors and validation evidence.

Cross-validation repeats training across several splits. Preprocessing must be fitted inside each training fold. If a customer contributes several rows, keep related rows in the same group where the deployment question requires unseen customers. For future forecasting, use time-aware splits rather than random mixing.

A decision tree repeatedly divides the feature space. A deep tree can memorize small groups. Limit its complexity and compare training with validation results. A good interview answer explains why your split resembles production, why the metric matches the decision, and what simpler alternative you tested. “The score improved” is incomplete without the baseline, sample size and affected groups.''',
        'system_design': '''Separate authentication, authorization, quota checking and prediction. Authentication identifies the caller. Authorization decides whether that caller may use a resource. Quotas limit consumption. None replaces the others. The prediction service should not trust a learner or tenant ID merely because it arrived in a request body.

```mermaid
flowchart TD
  A[Authenticated request] --> B{Allowed resource?}
  B -->|No| C[Reject access]
  B -->|Yes| D{Within quota?}
  D -->|No| E[Rate-limit response]
  D -->|Yes| F[Validate feature schema]
  F --> G[Predict with loaded model]
  G --> H[Return result and model version]
```

Load a model once per worker when practical. Loading a large artifact on every request wastes time and can exhaust memory during bursts. Several worker processes may each hold a copy. Estimate that memory before choosing a worker count. A load balancer distributes requests; it does not make a shared database or model server infinitely fast.

Keep the response contract stable across model versions. For example, return prediction, model version and a request ID. Do not expose private training examples in explanations. Record latency, validation failures and prediction failures without logging raw sensitive inputs by default.

If the model call times out, distinguish a temporary service failure from invalid input. Retrying malformed input does not help. Before retrying a chargeable or state-changing prediction request, define whether the operation can safely be repeated. For capacity, measure throughput at an acceptable tail latency, not only the fastest single request on an idle laptop.''',
        'full_stack': '''Make authentication and model errors visible without losing the user's form. Validate field types, ranges and units before sending. The server repeats validation and verifies access. Give errors a stable code and a readable message so the page does not parse human text to decide its behavior.

```mermaid
sequenceDiagram
  participant UI
  participant API
  participant Auth
  participant Model
  UI->>API: Prediction request with session
  API->>Auth: Check identity and permission
  Auth-->>API: Allowed
  API->>Model: Validated features
  Model-->>API: Prediction
  API-->>UI: JSON result and version
```

Use component state for values the user edits. Derived values, such as whether required fields are present, can usually be calculated from that state. Duplicating them in separate state introduces synchronization bugs. Server state needs its own pending, success and failure handling. When input changes during a request, an older response must not overwrite a newer result.

Test the boundary between the page and API. A valid form should show a result. Expired credentials should lead to a clear sign-in path. A forbidden resource must remain inaccessible even if the caller edits the URL. Invalid features should show field feedback; a server failure should retain input and offer retry.

For database-backed pagination, choose a stable order and a tie-breaker such as a unique ID. Filtering can change which rows exist between requests. Explain the trade-off between simple offset pagination and a cursor. The useful interview story is one complete feature with correctness and failure handling, rather than a list of frontend and backend libraries.''',
    },
    {
        'title': 'A queued prediction service that survives retries',
        'ai_ml': '''Ensembles combine models, but different combinations solve different problems. A random forest trains trees on varied samples and feature choices, then combines their predictions. This can reduce variance compared with one unstable tree. Boosting adds models sequentially to improve the current prediction. Its behavior depends on loss, learning rate, depth and stopping rules.

```mermaid
flowchart TD
  A[Fixed evaluation split] --> B[Simple baseline]
  A --> C[Random forest]
  A --> D[Boosted trees]
  B --> E[Compare quality and serving cost]
  C --> E
  D --> E
  E --> F[Choose and document limits]
```

Hold the comparison conditions constant. Use the same eligible rows, feature rules and evaluation metric. Tune settings on validation data. If positives are rare, inspect precision-recall behavior rather than celebrating majority-class accuracy. Class weights and sampling change training; a decision threshold changes how scores become actions. These are different levers.

Distance-based methods need careful scaling. A distance in kilometres can dominate a small-valued feature purely because of its units. Principal component analysis finds directions of variance, not necessarily directions best for predicting the label. An attractive two-dimensional plot does not prove that clusters represent useful groups.

For an explanation, identify whether it describes one prediction or average model behavior. Correlated features can share or distort apparent importance. Explain that an association is not automatically a cause. In the queued service, save the model version and feature schema with each job so a retry does not silently use an incompatible version.''',
        'system_design': '''A queue moves work outside the request's waiting time. It also creates a state-management problem. The API must tell the truth about whether the job was accepted, queued, running, finished or failed. Acknowledging a message too early can lose work; acknowledging after work can cause repetition if the worker crashes before the acknowledgment arrives.

```mermaid
sequenceDiagram
  participant Client
  participant API
  participant DB
  participant Worker
  Client->>API: Submit with idempotency key
  API->>DB: Commit job and outbox event together
  DB-->>Worker: Relay publishes committed job
  Worker->>DB: Claim job and save result once
  Client->>API: GET job status
  API->>DB: Read authorized job
  API-->>Client: State and result when ready
```

The outbox is a table of events saved in the same transaction as the job. A separate relay publishes those events. This avoids a gap where a job is committed but publication is lost. The relay can publish twice, so workers still need idempotent processing: repeated delivery should not repeat the business effect.

For a worker taking 0.5 seconds per job, one worker has an ideal upper bound of 2 jobs per second before overhead. Ten workers cannot safely sustain an arrival rate above 20 jobs per second. At 25 arrivals and 20 completions per second, the backlog grows by about 300 jobs per minute. Scale, reject, slow producers or reduce work; retries alone worsen overload.

Use bounded attempts with backoff and jitter for temporary failures. Store the last failure reason and expose a recovery path for permanent failures. A queue does not provide exactly-once side effects automatically. Explain the transaction boundary, duplicate handling and worker-crash behavior explicitly.''',
        'full_stack': '''A long operation should return a job identity and a status endpoint. A useful response includes the current state and where to check again. The page shows accepted work immediately, but it must not show a finished prediction before the worker has saved one.

```mermaid
flowchart TD
  A[Idle] --> B[Submitting]
  B --> C[Queued]
  C --> D[Running]
  D --> E[Succeeded]
  D --> F[Failed]
  C --> G[Cancel requested]
  D --> G
  G --> H[Cancelled if work can stop]
```

Cancellation is a request, not a promise that all effects are undone. Define the point after which a worker cannot cancel safely. A UI timeout also does not prove the server stopped. After an uncertain submission, look up the request using its idempotency key instead of blindly creating another job.

Generate one key for one intended operation and reuse it for retries. Store a hash of the relevant payload with the key. If the same key arrives with different input, reject the conflict instead of returning an unrelated earlier result. Scope keys to the authorized account and define their retention period.

Test a lost response after a successful commit, a duplicate queue message, a worker crash after saving a result, and a user revisiting the page. In each case the page should recover from server state. Poll with a bounded interval or use server events where appropriate. Stop polling when the job is terminal or the view closes. Keep a useful manual refresh path when the live connection fails.''',
    },
    {
        'title': 'A reproducible neural-network release',
        'ai_ml': '''A training step has four distinct parts: calculate predictions, calculate loss, calculate gradients, and update parameters. A gradient describes how a small parameter change affects the loss locally. The optimizer uses that information; it does not guarantee the globally best model.

```mermaid
flowchart TD
  A[Batch of examples] --> B[Forward calculation]
  B --> C[Loss against labels]
  C --> D[Backpropagate gradients]
  D --> E[Optimizer updates weights]
  E --> F[Clear gradients before next step]
  F --> A
```

For a one-weight model `prediction = w*x`, let `x=2`, target `y=6`, and `w=1`. Using squared error, the prediction is 2 and loss is 16. The derivative is `2*x*(w*x-y) = -16`. With learning rate 0.1, the next weight is `1 - 0.1*(-16) = 2.6`. The new prediction is 5.2 and loss is 0.64. A much larger step can overshoot. This tiny example explains the update, not the behavior of every deep network.

Track training and validation curves separately. Dropout and other training-specific behavior must be disabled or changed appropriately for evaluation. Evaluation should not update model weights. Keep the preprocessing, data version, model settings and code version with the artifact. Seeds help reproduce runs, but hardware and nondeterministic operations may still cause differences.

Before a release, compare quality and inference memory against the previous model. A model that is slightly better offline but exceeds the application's memory or latency budget may be the wrong release. Show those constraints in the experiment report.''',
        'system_design': '''A deployable model needs an artifact, a compatible runtime and a recovery plan. Keep build-time dependencies separate from runtime configuration. Use the same tested artifact across environments, while credentials and endpoints remain environment-specific.

```mermaid
flowchart TD
  A[Versioned code and data] --> B[Train and evaluate]
  B --> C[Immutable model artifact]
  C --> D[Build tested service image]
  D --> E[Staging checks]
  E --> F[Small production rollout]
  F --> G{Quality and service checks pass?}
  G -->|Yes| H[Increase traffic]
  G -->|No| I[Restore previous version]
```

Distinguish readiness from liveness. A service loading its model may be alive but unable to serve predictions. Readiness should prevent traffic from reaching it too soon. A liveness check that fails merely because a dependency is slow can create a restart storm. Choose checks based on the recovery action they trigger.

Capacity includes model memory, request buffers, runtime overhead and headroom. A 2 GB artifact does not imply exactly 2 GB of resident memory. Loading formats, precision, framework allocation and worker duplication change the result. Measure steady-state and peak memory during rollout, when old and new versions may overlap.

Rollback requires compatible contracts and data changes. Reverting a container does not reverse a destructive schema migration. Prefer a staged schema change when versions must coexist: add the new field, support both versions, migrate data, then remove the old field later. In an interview, explain what the deployment checks measure and what would cause an automatic or manual rollback.''',
        'full_stack': '''A repeatable build starts with declared dependencies and a clear startup command. Keep secrets outside the image and repository. Validate required configuration at startup with useful errors. Do not wait for a user request to discover that the model path or database address is missing.

```mermaid
sequenceDiagram
  participant CI
  participant Registry
  participant Service
  participant Router
  CI->>CI: Test code and model contract
  CI->>Registry: Publish immutable build
  Registry->>Service: Start selected version
  Service->>Service: Load model and check readiness
  Service-->>Router: Ready
  Router->>Service: Send production traffic
```

A useful test gate covers more than whether the process starts. Check valid inference, malformed input, missing authorization, model-schema mismatch and an unavailable dependency. Keep a small fixture model or controlled test adapter so routine tests do not depend on an external model service.

For uploads, bound file size before expensive parsing and verify the format from content where possible. Store untrusted files separately from executable application code. Use generated storage names and authorization checks instead of trusting a supplied path. A filename is presentation metadata, not a safe filesystem location.

When the service shuts down, stop accepting new work, allow bounded time for active work, then exit. Record the version in health information and logs so an incident can be tied to a release. A README should include setup, one successful request, one failure example and rollback instructions. Run those instructions in a clean environment before calling the project reproducible.''',
    },
    {
        'title': 'A streaming assistant with bounded work',
        'ai_ml': '''A language model predicts a next token from its context. Tokens can be parts of words, punctuation or other encoded units. A fluent answer is evidence of plausible text generation, not proof that the claims are true. Evaluation must measure the actual task, including unsupported answers and refusal behavior.

```mermaid
flowchart TD
  A[Validated user input] --> B[Instructions and allowed context]
  B --> C[Tokenize]
  C --> D[Model generates tokens]
  D --> E[Validate final structured result]
  E --> F[Answer or explicit failure]
```

Attention compares a query with keys to calculate weights, then combines values using those weights. In scaled dot-product attention, scaling helps control the magnitude of the dot products before softmax. Softmax turns relative scores into positive weights that sum to one. This is an internal computation; it is not a reliable explanation of why a model made a particular claim.

For structured output, validate both shape and meaning. An object with a correctly typed date field may still contain an impossible booking date. A schema does not establish factual correctness or permission. Keep business-rule checks after parsing. For citations, verify that the cited source was actually supplied and supports the statement.

Separate time to first token from time to complete the answer. Streaming may improve perceived responsiveness while the total work remains expensive. Bound input size, output tokens and total execution time. Compare prompting, retrieval and fine-tuning using a fixed evaluation set before adopting a more expensive approach.''',
        'system_design': '''Streaming changes a single response into a connection that may last much longer. Capacity now depends on concurrent streams, buffers and upstream work. A client closing the page should release work where possible, but cancellation must be passed through the entire call chain.

```mermaid
sequenceDiagram
  participant Browser
  participant API
  participant Model
  Browser->>API: Start stream
  API->>Model: Request with deadline and limits
  Model-->>API: Output chunk
  API-->>Browser: Progress event
  Browser->>API: Disconnect
  API->>Model: Cancel remaining work where supported
  API->>API: Release buffers and record outcome
```

Set a total deadline as well as appropriate connection and inactivity timeouts. Receiving one small chunk should not allow a stuck request to run forever. Bound queues and buffers. If the client reads slowly, apply backpressure or end the stream with a documented error rather than allowing memory to grow without limit.

Suppose requests arrive at 5 per second and last 20 seconds on average. Under stable conditions that suggests about 100 concurrent streams. It says nothing about worst-case bursts. Measure memory per connection, model concurrency and queue delay before increasing limits.

Partial output complicates retries. Restarting a request can produce different text or duplicate downstream actions. Do not automatically retry a tool action merely because the stream failed. Record an operation ID and the state of any side effects. Explain a fallback for model failure and clearly distinguish a completed answer from an interrupted one.''',
        'full_stack': '''A streamed page needs states for connecting, receiving, finished, interrupted and cancelled. Keep partial text visible after a connection failure, but label it as incomplete. A Cancel button should stop local reading and request server cancellation where supported.

```mermaid
flowchart TD
  A[Idle] --> B[Connecting]
  B --> C[Receiving chunks]
  C --> D[Complete]
  B --> E[Failed]
  C --> F[Interrupted with partial text]
  C --> G[Cancelled]
```

Network chunks do not necessarily match messages or characters. An event or JSON object may arrive across several chunks. Use a proper streaming decoder and accumulate complete frames according to the chosen protocol. Do not call a JSON parser on every arbitrary network chunk and assume each is a whole event.

Treat model text as untrusted content. Render escaped text or pass Markdown through a strict sanitizer. A code block in an answer must not execute in the page. Validate links and keep generated instructions separate from application permission controls.

Use a request identity to prevent chunks from an old request entering a new conversation. Stop subscriptions and timers when the view closes. For accessibility, avoid announcing every token to a screen reader; announce useful status changes and let the person read the finished answer. Test split messages, a multibyte character crossing a chunk boundary, a connection loss, cancellation and a malformed final payload.''',
    },
    {
        'title': 'Document search with evidence and citations',
        'ai_ml': '''Retrieval-augmented generation has two evaluation problems: finding useful evidence and writing a supported answer. A correct-looking answer can hide bad retrieval, while good evidence can still be misused by generation. Measure the stages separately.

```mermaid
flowchart TD
  A[Question] --> B[Keyword and vector candidates]
  B --> C[Merge and rerank]
  C --> D[Select allowed evidence within budget]
  D --> E[Generate answer with source IDs]
  E --> F[Check support and citations]
```

Chunking trades context against retrieval precision. Very small chunks can lose the sentence that explains a term. Very large chunks can dilute relevance and consume the prompt budget. Preserve document identity, location, version and permissions with each chunk. Test chunk choices on actual questions rather than selecting a size by habit.

Cosine similarity compares vector direction after normalization. It is not a calibrated probability that two statements have the same meaning. A high similarity score can retrieve a nearby but wrong fact. Keyword search can help exact names and identifiers. Hybrid retrieval combines signals, but the merge strategy and reranker need evaluation too.

For a teaching set of 20 questions with known supporting passages, suppose retrieval finds relevant evidence in the top five for 16 questions. That gives 80% success under that defined measure. Now inspect the four failures and score answer support separately. Include questions with no answer in the documents. The system should be able to say the evidence is missing instead of inventing a citation.''',
        'system_design': '''Draw ingestion separately from query serving. Ingestion reads files, extracts text, records versions, creates chunks and updates indexes. Query serving checks access, searches the correct versions, selects evidence and calls the model. These paths have different throughput and freshness requirements.

```mermaid
flowchart TD
  A[Authorized upload] --> B[Parse and version document]
  B --> C[Chunk and embed]
  C --> D[Keyword and vector indexes]
  E[Authorized question] --> F[Search with permission filters]
  D --> F
  F --> G[Rerank and select evidence]
  G --> H[Generate cited answer]
```

Permissions must constrain retrieval before evidence reaches the model. Removing a citation afterward does not undo the exposure of private context. Cache keys must include the relevant account, permission scope, document version and query settings. A shared query string alone is an unsafe cache key for private search.

Version updates need a consistent switch. If half the chunks are from an old document and half from a new one, an answer can combine contradictory policies. Build a new version and publish its index manifest only when ready, or document an explicit weaker freshness guarantee. Deletion must eventually remove chunks, embeddings and cached answers according to the system's policy.

Estimate each stage independently: parse backlog, embedding throughput, index size, search latency, reranking cost and generation tokens. If the target is a two-second answer, a two-second retrieval stage already consumes the whole budget. During an interview, trace a changed document and show when new questions will see it.''',
        'full_stack': '''The upload screen needs durable status: accepted, parsing, indexing, ready or failed. A completed file transfer does not mean the document is searchable. Persist that distinction on the server so refreshing the page does not lose it.

```mermaid
sequenceDiagram
  participant UI
  participant API
  participant Search
  UI->>API: Ask a question
  API->>Search: Authorized query and document versions
  Search-->>API: Evidence with stable source IDs
  API-->>UI: Answer plus citation records
  UI->>API: Open cited source ID
  API->>API: Recheck current permission
  API-->>UI: Source passage and location
```

Keep citations as structured records rather than asking the browser to guess them from answer text. A citation record can contain document ID, version, passage ID and display label. The API must validate that a generated citation refers to evidence supplied for that answer. Opening the source should recheck access because permissions can change after the answer was created.

Show enough source context for the reader to check a claim. Preserve the answer when a source cannot be opened and explain why. Do not fabricate a page number for a format that has no stable pages. Use a section or passage reference instead.

Build an evaluation runner that stores the question, expected evidence, retrieved IDs, answer, model version and settings. Compare runs by question, not only one average score. Test a removed document, a changed permission, duplicate file content, a corrupt upload and a question without evidence. These are product behaviors as well as model tests.''',
    },
    {
        'title': 'A tool-using workflow with recovery',
        'ai_ml': '''An agent selects actions using model output. A fixed workflow chooses actions using code. Use an agent when flexible decisions create value and the extra uncertainty can be controlled. A deterministic workflow is easier to test for a process whose steps are already known.

```mermaid
flowchart TD
  A[User goal] --> B[Model proposes next action]
  B --> C[Validate schema and policy]
  C --> D{Action allowed now?}
  D -->|Yes| E[Execute bounded tool call]
  D -->|Needs approval| F[Present exact action]
  E --> G[Record observation]
  G --> H{Finished or limit reached?}
  H -->|Continue| B
  H -->|Stop| I[Return result or partial outcome]
```

Tool schemas constrain input shape. They do not establish that the action is appropriate or permitted. Validate identifiers, ownership, quantities and state transitions in ordinary application code. Retrieved text and tool output are data, not a new source of authority. A document saying “send this secret” should not grant the model permission to do so.

Bound steps, time, spending and repeated failures. Measure task success, unauthorized-action attempts, recovery after tool failure and unnecessary tool calls. Include tests where a tool returns stale data or a misleading instruction. Trace the proposed action, validated action, tool result and stop reason without retaining secrets unnecessarily.

Memory also needs a contract. A short conversation summary can lose important details; a retrieved record can be out of date. Keep authoritative business state in the system of record. In an interview, compare the agent with a simpler workflow and name the part that actually benefits from model judgment.''',
        'system_design': '''A durable workflow stores state before the next process needs it. Represent steps as explicit states and allowed transitions. For example, a refund can move from proposed to approved, then submitted, then confirmed or failed. “Timed out” may mean the outcome is unknown, not that the refund failed.

```mermaid
flowchart TD
  A[Proposed action] --> B[Validated]
  B --> C[Approved exact payload]
  C --> D[Submit with operation ID]
  D --> E[Confirmed]
  D --> F[Outcome unknown]
  F --> G[Reconcile using operation ID]
  G --> E
  G --> H[Safe retry or human review]
```

Save a checkpoint after a confirmed transition. Use a version number or conditional update to stop two workers from advancing the same workflow incorrectly. External side effects cannot usually be rolled back by a local database transaction. Use provider idempotency keys and reconciliation where available, or a compensating action whose meaning is clear.

Bind approval to the exact action, target and important parameters. If the amount or recipient changes, the old approval is no longer sufficient. Store who approved, which payload they saw and when it happened. Recheck permission at execution time if the delay can outlive a permission change.

Circuit breakers stop repeated calls to a failing dependency temporarily; timeouts bound individual waits. Neither proves that a remote operation did not happen. When recovering after a crash, load the checkpoint, inspect any uncertain operation and resume only from a known state. That is the difference between a diagram that looks reliable and a workflow that can be recovered.''',
        'full_stack': '''A useful workflow page shows what happened, what is happening, and what needs a decision. Keep durable server state separate from temporary animations or progress indicators. A spinner is not a business state and cannot explain an interrupted operation.

```mermaid
sequenceDiagram
  participant User
  participant UI
  participant API
  participant Worker
  Worker-->>API: Approval required for exact action
  API-->>UI: Action details and version
  UI-->>User: Show target, effect and parameters
  User->>UI: Approve
  UI->>API: Approve action ID and version
  API->>Worker: Execute if still valid
  Worker-->>API: Durable outcome
  API-->>UI: Updated state
```

An approval control should describe the effect in plain language. If the action is a refund, show the amount and destination. Do not hide those details behind a generic Continue button. Protect approval endpoints with authorization and appropriate request protections; disabling a browser button is not enforcement.

On refresh, load the workflow from the server. If another tab approved the action already, show the recorded outcome rather than submitting again. Return a conflict when the page's version is stale. Make retry available only for states where retry is meaningful.

Test a process restart between tool execution and checkpoint save, an expired approval, a changed payload and a user losing permission. Record an audit trail with stable operation IDs. Logs should support diagnosis while avoiding raw secrets or unnecessary private model context. A good demo includes one interrupted workflow that recovers successfully.''',
    },
    {
        'title': 'A monitored ML pipeline with compatible versions',
        'ai_ml': '''Training-serving skew means the model sees different feature logic or data conditions at serving time. Drift means a distribution changes over time. These can occur independently. A feature can drift even when the code is identical, and two code paths can disagree even on unchanged data.

```mermaid
flowchart TD
  A[Versioned source data] --> B[Shared feature definition]
  B --> C[Training dataset]
  B --> D[Serving features]
  C --> E[Model and evaluation]
  E --> F[Registry version]
  F --> G[Canary traffic]
  D --> G
  G --> H[Outcomes and quality checks]
```

A registry record should connect the artifact with feature schema, training data snapshot, code, evaluation results and intended use. A model version alone is insufficient when preprocessing changed. Check compatibility before routing production requests to the new version.

Monitor missing features, ranges, prediction distributions and real outcome quality. Distribution changes are useful alerts, but they do not prove that quality declined. Labels may arrive hours or weeks later. Keep immediate data checks separate from delayed performance metrics, and account for which outcomes are still missing.

For a canary, send a controlled portion of eligible traffic to the new model. Compare service errors and latency immediately. Evaluate product and model outcomes with appropriate time windows and group breakdowns. A rollback must restore a compatible model and feature path. Write the decision rule before looking at the results so the release is not accepted merely because one favorable metric appears.''',
        'system_design': '''Offline processing builds datasets and model artifacts. Online serving answers requests under tighter latency limits. Sharing definitions is useful; forcing both paths to use the same execution pattern is not always appropriate. Keep the ownership and freshness contract explicit.

```mermaid
flowchart TD
  A[Events] --> B[Validated ingestion]
  B --> C[Durable history]
  C --> D[Offline training]
  B --> E[Online feature updates]
  D --> F[Versioned model registry]
  E --> G[Prediction service]
  F --> G
  G --> H[Service and quality monitoring]
```

Partition events by a key that matches the required ordering, such as account ID. A hot account can overload one partition even when the rest are idle. Explain how you would detect that imbalance and whether splitting the key would weaken an ordering guarantee.

Choose service-level indicators that match user experience. Successful predictions within a latency threshold are more useful than process uptime alone. Define the denominator: all eligible requests, including failures, rather than only completed requests. Track queue age as well as queue length because the same length can mean different delays at different service rates.

Recovery objectives are separate: how much recent data may be lost, and how long service restoration may take. A backup is only useful if restoration is tested. Replay must preserve deduplication and event-time rules. A recovered feature store built from different logic can be available but incompatible with the model. Include data and model compatibility in the recovery exercise.''',
        'full_stack': '''A pipeline needs explicit input and output contracts. Validate schema, required values, acceptable ranges and timestamps before training. Quarantine rejected records with a reason and a count. Silently dropping many records can change the population the model learns from.

```mermaid
flowchart TD
  A[Incoming batch or events] --> B{Contract passes?}
  B -->|No| C[Quarantine and alert]
  B -->|Yes| D[Versioned data snapshot]
  D --> E[Train and evaluate]
  E --> F[Publish model manifest]
  F --> G[Deploy compatible serving code]
```

The model manifest should identify the artifact checksum, feature schema and compatible runtime. Verify the checksum before loading. Keep artifact paths under controlled storage and avoid loading untrusted serialized objects. The model-loading mechanism itself is a security boundary.

Batch inference should expose partial failure. If 98 of 100 records succeed, do not return an unqualified success for all 100. Record per-record identifiers and error categories so a retry can target failures without duplicating successful side effects. Bound batch size and total memory use.

A quality dashboard needs dates, sample counts and model versions. A metric calculated from 12 newly labelled cases should not look equally certain as one from 12,000. Link an alert to the affected version and a runbook. Test a missing column, an unexpected category, an old schema, a corrupt artifact and a rollback. This creates evidence that the pipeline is operable, not merely runnable once.''',
    },
    {
        'title': 'Recommendations with honest feedback',
        'ai_ml': '''Separate candidate generation from ranking. Candidate generation finds a manageable set from a large catalogue. Ranking orders that set for the user and context. A perfect ranker cannot recover an item that candidate generation never supplied.

```mermaid
flowchart TD
  A[User and context] --> B[Popular and personalized candidates]
  B --> C[Eligibility and safety filters]
  C --> D[Ranking model]
  D --> E[Diversity and product rules]
  E --> F[Shown recommendations]
  F --> G[Exposure and outcome records]
```

Compare with a popularity or recency baseline. For a new user, useful preferences may be absent. For a new item, interaction history may be absent. Content features, exploration and simple defaults can help, but each needs evaluation. Do not interpret “not clicked” as an explicit dislike when the item may never have been visible.

Offline ranking metrics depend on how relevance labels and candidate sets were constructed. A high score on a convenient negative sample may not reflect the live catalogue. Check leakage from interactions that happened after the recommendation time. Split by time when evaluating future behavior.

Online experiments need a product objective and guardrails. More clicks can coexist with lower satisfaction or harmful repetition. Track exposure, position, outcome delay and affected groups. Feedback loops can reinforce items already shown often. In the interview, explain how the system learns without assuming that every observed interaction is an unbiased statement of preference.''',
        'system_design': '''A recommendation page can often tolerate slightly stale ranked results, while permission and eligibility checks may require fresher information. State these guarantees separately instead of calling the entire system “eventually consistent”.

```mermaid
flowchart TD
  A[User events] --> B[Durable event log]
  B --> C[Feature and candidate updates]
  C --> D[Cached ranked candidates]
  E[Page request] --> F[Read candidate list]
  D --> F
  F --> G[Apply current eligibility]
  G --> H[Return list and log exposure]
```

For a feed, fan-out on write precomputes recipients' lists; fan-out on read assembles the list when requested. A celebrity with millions of followers makes write fan-out expensive. A hybrid can precompute ordinary accounts and merge very large accounts at read time. The right choice depends on read/write rates and freshness requirements.

Deduplicate interaction events by a stable event ID. Delivery can repeat and arrive out of order. Event time describes when the action happened; processing time describes when the system handled it. Decide how late events affect aggregates and experiments.

Experiment assignment should remain stable for the intended unit, such as account. Cache and routing choices must not accidentally mix variants. Deletion needs a workflow across primary records, derived features, indexes and caches, with clear treatment of backups under the applicable policy. Explain what is immediate, what is asynchronous and how completion is verified.''',
        'full_stack': '''Record what the person was shown as well as what they clicked. A click event without an exposure record cannot tell you which alternatives were available or in which position the item appeared. Give each request and exposure stable identifiers.

```mermaid
sequenceDiagram
  participant UI
  participant API
  participant Events
  UI->>API: Request eligible recommendations
  API-->>UI: Items, request ID and variant
  UI->>Events: Record actual displayed exposures
  UI->>Events: Record click with exposure ID
  Events->>Events: Deduplicate and validate ownership
```

Do not send duplicate impressions on every component render. Define visibility rules, such as whether an item actually entered the viewport, and test them. Keep analytics failure from blocking the main interaction where the product allows it. Bound retries and avoid collecting unnecessary personal information.

For cursor pagination, keep the ranking context or snapshot stable enough for the promised behavior. A constantly changing list can produce missing or repeated items between pages. State whether that is acceptable and provide a refresh action when the ranking changes materially.

Feature flags should come from a trusted assignment mechanism. The browser may display a variant but should not decide authorization. Test logged-out users, users with no history, empty eligible lists, removed items and a failed ranking dependency. A baseline fallback should be labelled and should still apply permission and eligibility filters.''',
    },
    {
        'title': 'A capstone with evidence behind each decision',
        'ai_ml': '''Choose one measurable product task. “Build an AI assistant” is too broad to evaluate. “Answer questions from this document set with supported citations” gives you inputs, outputs and a way to inspect errors. Define unacceptable failures as well as average success.

```mermaid
flowchart TD
  A[Specific user task] --> B[Baseline and evaluation set]
  B --> C[First complete implementation]
  C --> D[Inspect failures by category]
  D --> E[Change one major variable]
  E --> F[Compare quality cost and latency]
  F --> G[Document evidence and limits]
```

Keep a development set for iteration and a held-out set for the final comparison. For document questions, include straightforward facts, multi-passage questions, outdated information, missing evidence and adversarial text. A test collection containing only friendly examples will overstate usefulness.

Write a small results table with baseline, candidate, sample count, quality measure, median and tail latency, and cost per completed task. Explain the measurement environment. If several model calls are needed for one task, count the whole task cost, including failed attempts and retries.

Inspect individual regressions before accepting an average improvement. Record what you changed and what remains uncertain. A model-generated judge can help organize reviews, but its scores need calibration against human examples and known failure modes. The strongest interview demonstration includes a failure, the evidence that located it, and the trade-off behind the repair.''',
        'system_design': '''Start with functional requirements, scale assumptions and failure tolerance. Then draw the smallest architecture that satisfies them. Every additional service creates another contract and operational responsibility. Add one because it solves a demonstrated constraint, not because it looks impressive.

```mermaid
flowchart TD
  A[User flow and requirements] --> B[API and data contracts]
  B --> C[Normal request path]
  C --> D[Capacity and latency estimate]
  D --> E[Failure and recovery path]
  E --> F[Observability and release plan]
```

For a document assistant, distinguish synchronous questions from asynchronous ingestion. State when a file becomes searchable, how access is checked and which versions an answer used. Estimate peak request rate, average and tail duration, data growth and expensive dependency calls. Mark unknowns as measurements to collect.

Write an architecture decision record for one meaningful choice. Include context, options, chosen approach, consequences and the condition that would cause you to revisit it. For example, choosing a database-backed queue may reduce operational work at modest scale, while a dedicated broker may become useful when throughput or routing requirements change.

Run a failure exercise: stop the model provider, interrupt a worker, or make storage temporarily unavailable in a safe test environment. Describe the user-visible effect and how recovery is verified. A diagram should show persistent state and trust boundaries, not only boxes connected by arrows. This gives the interviewer something concrete to challenge.''',
        'full_stack': '''Build one vertical slice before expanding features: user input, authorization, server validation, useful work, saved outcome and clear display. A complete path gives you an integration surface to test. Five unfinished screens do not establish that the product works.

```mermaid
flowchart TD
  A[User action] --> B[Accessible form]
  B --> C[Authorized validated API]
  C --> D[Model or retrieval operation]
  D --> E[Persisted result and evidence]
  E --> F[Useful success or failure view]
  F --> G[Automated journey check]
```

Separate unit checks for calculations from integration checks for boundaries and browser checks for the critical journey. Choose failures that matter: another user's resource, duplicate submission, stale response, interrupted upload and unavailable dependency. Tests that repeat the implementation line by line add little confidence.

The setup guide must name supported runtime versions, required variables, dependency installation, startup and test commands. Use sample data that can be shared. Include a clear way to reset only the demo data. Do not require private credentials just to inspect the project or run isolated tests.

Prepare a five-minute demo: problem, successful flow, architecture, measured result and one limitation. Keep a recorded or local fallback for unreliable networks. Verify portfolio links and commands from a clean checkout. The goal is that another engineer can reproduce your evidence and understand your decisions without guessing missing steps.''',
    },
    {
        'title': 'A realistic technical interview rehearsal',
        'ai_ml': '''Practise reasoning from evidence instead of reciting model definitions. For each answer, state the task, data available at prediction time, baseline, evaluation split, metric and main failure mode. Then explain how you would detect a regression after release.

```mermaid
flowchart TD
  A[Interview problem] --> B[Clarify decision and available data]
  B --> C[Baseline and split]
  C --> D[Candidate and trade-offs]
  D --> E[Evaluation and error analysis]
  E --> F[Serving and monitoring]
```

Try this scenario: offline accuracy rises from 90% to 96%, but users report worse results. First verify that the evaluation population and labels match production. Check leakage, class balance, threshold changes, feature skew and delayed outcomes. Compare errors by group. Do not immediately retrain a larger model; that can hide the diagnosis.

For language models, separate retrieval failure, unsupported generation, invalid output and tool execution failure. A single “answer quality” score cannot locate the defect. Choose one failed example, trace the intermediate evidence and propose a targeted change with a test.

Record mock answers and inspect where you skipped an assumption or used unexplained jargon. Re-answer with a concrete example and one limitation. If a question is outside your experience, state what you know, name the uncertainty and describe a sensible experiment. Confident guesses are weaker evidence than a clear verification plan.''',
        'system_design': '''Use the interview time to develop one coherent design. Clarify the users and operations, estimate the important load, sketch the normal path, then examine the most consequential bottleneck or failure. Do not spend the whole session listing technologies.

```mermaid
flowchart TD
  A[Clarify requirements] --> B[Estimate important quantities]
  B --> C[Sketch API data and request path]
  C --> D[Choose one deep dive]
  D --> E[Failure handling and trade-offs]
  E --> F[Summarize limits and next measurements]
```

For a URL shortener, separate creating a short key from redirecting an existing key. Redirect traffic may dominate writes. Discuss collision handling, custom aliases, expiration, malicious destinations, caching and analytics. A cache accelerates lookup but needs a freshness policy when a destination is disabled.

For notifications, define delivery versus user reading. A provider accepting a message does not mean the person saw it. Deduplication, per-user preferences, retry rules and provider failures affect the design. For file storage, separate metadata permissions from object transfer and explain interrupted uploads.

Use numbers as checks. If you assume one million reads per day, the daily average is about 11.6 reads per second, not one million per second. Estimate peaks separately and state the factor. When challenged, update the assumption and show which part of the design changes. That flexibility is more useful than defending every initial box.''',
        'full_stack': '''An experienced developer should be able to debug across browser, API and storage boundaries. Start with the observed failure and reproduce it. Identify whether the delay or error occurs before the request, in the network, in server processing or in rendering. Change one hypothesis at a time.

```mermaid
flowchart TD
  A[Reproduce user symptom] --> B[Inspect request and response]
  B --> C[Trace server work and queries]
  C --> D[Find smallest supported cause]
  D --> E[Repair and add regression check]
  E --> F[Verify original journey and failure case]
```

For a slow search page, measure request duration and render cost separately. Check duplicate requests, stale responses, excessive payloads, missing indexes and expensive rendering. Debouncing changes request frequency; it does not repair a slow database query. Memoization does not repair incorrect state ownership.

Prepare a project story with context, your action, a technical decision, evidence and reflection. Be precise about your own contribution. A useful example can be a race condition you fixed, a migration you made safer, or a failing release you diagnosed. Include the test or measurement that showed the repair worked.

During a code review exercise, inspect correctness, access control, input validation, concurrency and failure behavior before stylistic preferences. Explain the highest-impact issue with a concrete failing input. Suggest a small repair and a meaningful test. This demonstrates judgment beyond remembering framework APIs.''',
    },
    {
        'title': 'Final review based on mistakes, not confidence',
        'ai_ml': '''Use a mistake log to choose revision. Each entry should contain the question, your original reasoning, the exact error, a corrected example and a new test question. Reading the corrected answer repeatedly can feel fluent without proving that you can apply it.

```mermaid
flowchart TD
  A[Cold attempt without notes] --> B[Compare reasoning with evidence]
  B --> C[Classify the mistake]
  C --> D[Repair with a worked example]
  D --> E[Try a changed problem later]
  E --> F[Record remaining uncertainty]
```

Distinguish a definition gap from a design gap. Forgetting precision's denominator needs a small confusion-matrix exercise. Choosing accuracy for rare-event detection needs a discussion of error costs and deployment behavior. Mixing these problems leads to unfocused revision.

Defend one complete evaluation plan aloud. State the prediction moment, label timing, split, baseline, metric, group analysis and release checks. Then change an assumption: labels arrive two weeks late, the user population changes, or the model must fit a smaller memory budget. Explain what changes and what remains valid.

Use the final mock to identify next steps, not to claim mastery. Keep the actual measurements and uncertainty in your portfolio. A strong answer can say that the current evidence is insufficient and propose the experiment needed to decide. That is a practical engineering skill.''',
        'system_design': '''Revisit decisions that failed under follow-up questions. Perhaps a cache key omitted permission scope, a retry duplicated a write, or an estimate ignored burst traffic. Repair the reasoning, redraw the affected path and name the invariant the design must preserve.

```mermaid
flowchart TD
  A[Original design] --> B[Introduce one realistic failure]
  B --> C[Trace stored state and user result]
  C --> D[Find broken guarantee]
  D --> E[Choose repair and cost]
  E --> F[Repeat with changed scale]
```

Run a timed design mock with a written requirement sheet. Reserve time for recovery and trade-offs. Afterward, check whether every persistent record has an owner, every external call has a failure path, and every important number has units. These checks catch many polished but incomplete diagrams.

Practise comparing alternatives without declaring a universal winner. A relational database, document database, queue or cache is useful under specific access patterns and constraints. Explain what evidence would make you change your choice. The same applies to consistency: state which operation requires which guarantee.

Finish with an operational walkthrough. Describe how to detect a bad release, reduce impact, restore service and verify data correctness. “Roll back” is not enough if the new version already changed stored data. Keep this explanation tied to the capstone so your answer has concrete APIs, records and recovery steps.''',
        'full_stack': '''Verify that another engineer can run the project and follow its main journey. Use a clean setup, the documented commands and shared sample data. Check the demo with ordinary user permissions, not only an administrator account.

```mermaid
flowchart TD
  A[Clean checkout] --> B[Documented setup]
  B --> C[Tests and build]
  C --> D[Main user journey]
  D --> E[Permission and failure checks]
  E --> F[Demo and technical explanation]
```

Review the language and browser fundamentals behind your framework: values and mutation, asynchronous work, HTTP semantics, state ownership and accessibility. When explaining a hook or middleware, connect it to the problem it solves. Avoid answering with a library name alone.

Choose one small debugging task and complete it under time pressure. State the symptom, form a hypothesis, inspect evidence, make a minimal repair and run a regression check. Explain remaining risk. This is closer to everyday engineering work than memorizing a large list of commands.

Check repository links, setup instructions, screenshots and claimed results. Remove secrets and private sample data from the demo materials. Write an honest next-step plan based on mock feedback: which patterns need repetition, which explanations need clarity and which project gap needs work. Completing 90 days is a record of practice, not a guarantee of an offer.''',
    },
)


def notebook(day, track):
    spec = interview_course.day_spec(day)
    if track not in ('ai_ml', 'system_design', 'full_stack'):
        raise ValueError('Choose an engineering subject.')
    entry = _NOTEBOOKS[spec['week'] - 1]
    label = {'ai_ml': 'AI and ML', 'system_design': 'System design', 'full_stack': 'Implementation'}[track]
    text = re.sub(r'(```mermaid\n[^\n]+\n)',
                  lambda match: match[1] + f'accTitle: {label} — {entry["title"]}\n', entry[track])
    sources = {
        (1, 'full_stack'): ('React: preventing stale request results', 'https://react.dev/learn/synchronizing-with-effects#fetching-data'),
        (2, 'ai_ml'): ('NumPy: array broadcasting and shape rules', 'https://numpy.org/doc/stable/user/basics.broadcasting.html'),
        (2, 'system_design'): ('PostgreSQL: transaction isolation', 'https://www.postgresql.org/docs/current/transaction-iso.html'),
        (2, 'full_stack'): ('PostgreSQL: joins between tables', 'https://www.postgresql.org/docs/current/tutorial-join.html'),
        (3, 'ai_ml'): ('scikit-learn: avoiding data leakage', 'https://scikit-learn.org/stable/common_pitfalls.html'),
    }
    if source := sources.get((spec['week'], track)):
        text += f'\n\nCheck the implementation detail in [{source[0]}]({source[1]}).'
    return {
        'title': entry['title'],
        'week': spec['week'],
        'text': text,
        'focus': spec[track],
    }

# Short implementation cases complement the conceptual notebooks. Each case is
# shared honestly across its week; daily tasks and interviews remain distinct.
_IMPLEMENTATION_LABS = (
'''#### Implementation lab: a summary with a clear contract

Build the calculation before connecting a web framework. Input is a list of study-session durations in minutes. Allow zero; reject negative numbers, text, booleans, infinity and NaN (a special value meaning “not a number”). A duration cannot exceed 1,440 minutes in this exercise. Limit the list to 10,000 entries so a request cannot ask for unbounded work. These are chosen product limits, not Python limits.

```python
import math

def summarise_sessions(minutes):
    if type(minutes) is not list or len(minutes) > 10_000:
        raise ValueError("minutes must be a list of at most 10000 values")
    total = 0.0
    for value in minutes:
        if type(value) not in (int, float):
            raise ValueError("each duration must be a number")
        if not 0 <= value <= 1440 or not math.isfinite(value):
            raise ValueError("each duration must be finite and between 0 and 1440")
        total += value
    count = len(minutes)
    return {"count": count, "total_minutes": total,
            "mean_minutes": total / count if count else None}

def handle_summary(payload):
    if type(payload) is not dict or set(payload) != {"minutes"}:
        return 400, {"error": "send an object containing only minutes"}
    try:
        return 200, summarise_sessions(payload["minutes"])
    except ValueError as error:
        return 400, {"error": str(error)}

assert summarise_sessions([20, 30, 40]) == {
    "count": 3, "total_minutes": 90.0, "mean_minutes": 30.0}
assert summarise_sessions([])["mean_minutes"] is None
assert handle_summary({"minutes": [True]})[0] == 400
```

Save the code in `study_summary.py` and run `python3 study_summary.py`. No output means these assertions passed. Add your own failing cases before changing the code. This is a calculation and a request-handler function, not a running HTTP server. A framework adapter must still parse the JSON body, enforce a body-size limit, call `handle_summary`, and serialize its status and result.

Read the loop slowly: `total` starts at zero; each valid value is added exactly once; `count` is the list length. For `[20, 30, 40]`, the total moves through `0 → 20 → 50 → 90`; dividing 90 by 3 gives 30. The empty case returns `None`, which JSON represents as `null`, because the mean of no observations is undefined. Showing zero would falsely report a measured zero-minute mean.

This code does not save a session and does not train a model. Its result is a summary of known facts. Floating-point addition can round decimal values; do not use exact equality for arbitrary decimal totals. A financial total would need a deliberate representation such as integer minor units. Keep that choice separate from today's minute-summary contract.

Try invalid cases `["20"]`, `[True]`, `[-1]`, `[float("nan")]`, `[float("inf")]` and a list longer than 10,000. Expect a useful validation error, with no partial result. Test `[0]` separately: it is a valid observed zero.''',
'''#### Implementation lab: include people with no sessions

A report should distinguish a known zero from a failed query. Assume `learners(id, name)` and `sessions(id, learner_id, minutes, started_at)`. Store UTC timestamps in a consistent database type. Bind `:start` and `:end` as parameters; do not build SQL by joining user text.

```sql
SELECT l.id, l.name, COALESCE(SUM(s.minutes), 0) AS total_minutes
FROM learners AS l
LEFT JOIN sessions AS s
  ON s.learner_id = l.id
 AND s.started_at >= :start
 AND s.started_at < :end
GROUP BY l.id, l.name
ORDER BY l.id;
```

The date filter belongs in the join condition here. Putting `s.started_at >= :start` in a `WHERE` clause would discard the unmatched rows and hide learners with no sessions. Group by the stable ID as well as the name; two people can have the same name. The half-open time range includes the start and excludes the end, so adjacent reports do not double-count a boundary session.

Build a fixture with two learners: one has sessions of 20 and 30 minutes, and one has none. Expect totals of 50 and 0. Add a session exactly at `:end`; it belongs to the next interval. Add another table with multiple rows per session and explain why a careless extra join could multiply the total. Return an error if the query fails; never convert a database failure into an empty report.''',
'''#### Implementation lab: turn scores into decisions

For a classifier, a score is not yet a decision. Choose a threshold and compare predictions with known outcomes. Here 1 means the positive class and 0 means the negative class. This function is an evaluation helper; it does not train a model.

```python
def confusion(labels, scores, threshold):
    if len(labels) != len(scores) or not labels:
        raise ValueError("labels and scores need the same nonzero length")
    if type(threshold) not in (int, float) or not 0 <= threshold <= 1:
        raise ValueError("threshold must be between 0 and 1")
    counts = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
    for actual, score in zip(labels, scores):
        if type(actual) is not int or actual not in (0, 1):
            raise ValueError("labels must be 0 or 1")
        if type(score) not in (int, float) or not 0 <= score <= 1:
            raise ValueError("scores must be numbers between 0 and 1")
        positive = score >= threshold
        key = ("tp" if positive else "fn") if actual else ("fp" if positive else "tn")
        counts[key] += 1
    return counts

assert confusion([1, 0, 1, 0], [.9, .7, .4, .1], .5) == {
    "tp": 1, "fp": 1, "tn": 1, "fn": 1}
```

At threshold 0.5, precision is `1/(1+1) = 0.5` and recall is also 0.5. At threshold 0.8, the false positive disappears but the missed positive remains: precision becomes 1 and recall stays 0.5. A smaller threshold of 0.3 finds both positives and still includes one false positive. Explain which error matters more for your feature. If a denominator is zero, report the metric as undefined under your chosen reporting convention instead of crashing or silently inventing success.''',
'''#### Implementation lab: claim a job once

A queue message may arrive twice. Give the job a stable ID and keep its state in durable storage. The following SQL illustrates a conditional transition, not a complete worker implementation.

```sql
UPDATE jobs
SET status = 'running', worker_id = :worker,
    lease_until = :lease_until
WHERE id = :job_id AND status = 'queued'
RETURNING id, input_json;
```

Exactly one worker can change a particular queued row to running when concurrent updates follow the database's locking rules. A worker that receives no returned row did not acquire this job and must not run its effect. This alone does not solve crashes: if the winning worker stops, its lease needs expiry and recovery. A lease is a time-limited ownership claim.

Store the completed output and an operation ID. If an external tool accepts a request but its response is lost, mark the outcome unknown and reconcile with that tool before retrying. A local transaction cannot atomically commit a remote side effect. Test duplicate delivery, a crash before the effect, and a crash after the effect but before the completion record. Explain which cases are safe to retry and which require reconciliation.''',
'''#### Implementation lab: configuration is part of the release

Keep environment variables as text at the boundary, then validate and convert once. The rest of the program should receive checked values. Do not log secret values when a check fails.

```python
def serving_config(env):
    raw = env.get("MAX_IN_FLIGHT", "8")
    if not isinstance(raw, str) or not raw.isascii() or not raw.isdigit():
        raise ValueError("MAX_IN_FLIGHT must be a whole number")
    limit = int(raw)
    if not 1 <= limit <= 128:
        raise ValueError("MAX_IN_FLIGHT must be between 1 and 128")
    version = env.get("MODEL_VERSION", "")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("MODEL_VERSION is required")
    return {"max_in_flight": limit, "model_version": version}

assert serving_config({"MODEL_VERSION": "v3"})["max_in_flight"] == 8
```

The numeric range is a teaching deployment policy; measure the right limit for your model and hardware. A process can be alive while its model has not loaded. Return ready only after the named model and its compatible preprocessing are available. A configuration error should stop startup with the field name, rather than start an apparently healthy server that fails every request. Test missing version, zero concurrency, text instead of a number and a deliberately failed model load. A rollback restores the compatible build, model and configuration together.''',
'''#### Implementation lab: a late response must not win

This browser example assumes an existing `showResult` function, a `showError` function and an API that accepts `q`. Each new request gets a larger number. The result is displayed only if that number still belongs to the latest request.

```javascript
let currentRequest = 0;
let activeController;
async function search(query) {
  const request = ++currentRequest;
  activeController?.abort();
  const controller = new AbortController();
  activeController = controller;
  try {
    const response = await fetch('/api/search?q=' + encodeURIComponent(query),
      { signal: controller.signal });
    if (!response.ok) throw new Error('Search failed');
    const result = await response.json();
    if (request === currentRequest) showResult(result);
  } catch (error) {
    if (request === currentRequest && error.name !== 'AbortError') {
      showError('Search could not finish. Try again.');
    }
  }
}
```

Cancellation saves work when supported. The request-number check protects the screen even when earlier work has already completed or cannot be cancelled. Test request A taking 500 ms and request B taking 50 ms after A starts. The final screen must show B. Test a malformed successful response separately: production code still needs runtime shape validation before `showResult`. For a streaming answer, apply the same ownership check to each arriving chunk, and mark a disconnected stream as incomplete.''',
'''#### Implementation lab: chunks need source positions

The following word-based splitter teaches overlap and metadata. It is not a tokenizer for a particular model. Real token budgets need that model's tokenizer, and documents with tables or headings need boundaries that respect structure.

```python
def word_chunks(text, size=4, overlap=1):
    if type(size) is not int or type(overlap) is not int or not 0 <= overlap < size:
        raise ValueError("require 0 <= overlap < size")
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = min(start + size, len(words))
        chunks.append({"start_word": start, "end_word": end,
                       "text": " ".join(words[start:end])})
        if end == len(words):
            break
        start = end - overlap
    return chunks

assert [c["text"] for c in word_chunks("a b c d e f")] == ["a b c d", "d e f"]
```

`end_word` is exclusive. The word at position 3 appears in both chunks because overlap is one. Empty input produces no chunks. Store a document ID and version beside these positions so a citation points to the exact source used during retrieval. Test zero overlap, overlap equal to size, one word and a changed source document. Never use overlapping chunks as independent evidence of two different sources.''',
'''#### Implementation lab: record an uncertain outcome

A workflow transition is a permitted move between named states. Keep the transition rule separate from the code that calls an external tool. This small function checks the rule; a real service must store the state change transactionally.

```python
ALLOWED = {
    "queued": {"running", "cancelled"},
    "running": {"succeeded", "failed", "unknown"},
    "unknown": {"succeeded", "failed"},
    "succeeded": set(), "failed": set(), "cancelled": set(),
}

def transition(current, following):
    if current not in ALLOWED or following not in ALLOWED[current]:
        raise ValueError("invalid workflow transition")
    return following

assert transition("running", "unknown") == "unknown"
```

Use `unknown` when a tool might have changed external state but no reliable response arrived. It is different from `failed before sending`. Reconcile using the external operation ID, a receipt or another authoritative check. Do not turn unknown into queued merely to make a retry button work. Test that a succeeded operation cannot run again, that cancellation before execution is allowed, and that an unknown outcome needs a resolution. Authorize the particular action and target before tool execution; valid JSON is not permission.''',
'''#### Implementation lab: serving must use the same feature contract

A model expects a named and ordered set of features. A mapping prevents callers from silently deciding column order. A version identifies the feature definition, not only the model artifact.

```python
import math
FEATURES = ("distance_km", "stops")

def serving_vector(record, schema_version):
    if schema_version != "delivery-features-v1":
        raise ValueError("unsupported feature schema")
    if type(record) is not dict or set(record) != set(FEATURES):
        raise ValueError("unexpected feature names")
    result = []
    for name in FEATURES:
        value = record[name]
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError("features must be finite non-negative numbers")
        result.append(float(value))
    return result

assert serving_vector({"stops": 2, "distance_km": 4}, "delivery-features-v1") == [4.0, 2.0]
```

The output order stays `[distance_km, stops]` even if input keys arrive in a different order. This teaching contract does not enforce an integer stop count; add that rule if the product requires it. Reuse the feature transformation in training and serving, record its version, and compare a known example through both paths. Test missing names, extra names, changed units and an incompatible version. Detecting schema mismatches does not prove that the incoming feature distribution has stayed stable.''',
'''#### Implementation lab: stable experiment assignment

Assign a signed-in user on the server using a stable user identifier and experiment identifier. Do not use Python's built-in `hash`, whose result is not a cross-process assignment contract.

```python
import hashlib

def experiment_group(user_id, experiment_id):
    if any(type(value) is not str or not value or "\\0" in value for value in (user_id, experiment_id)):
        raise ValueError("stable user and experiment IDs are required")
    value = (experiment_id + "\\0" + user_id).encode("utf-8")
    bucket = int.from_bytes(hashlib.sha256(value).digest()[:8], "big") % 100
    return "treatment" if bucket < 50 else "control"

assert experiment_group("user-7", "rank-v2") == experiment_group("user-7", "rank-v2")
```

This is a simple deterministic 50/50 assignment, not a guarantee that a small sample has exactly equal group sizes. Keep the algorithm and experiment ID fixed during the test. Record which version a user actually saw, because assignment without exposure can mislead analysis. Do not let the browser select its own group for a server-side effect. Test repeat visits, separate experiments, missing identities and a disabled feature flag. Predefine guardrails and stop rules before looking at favorable metrics.''',
'''#### Implementation lab: a measured release gate

Separate the measurement from the decision. State the sample and percentile rule. This helper uses the nearest-rank definition: sort `n` values and select position `ceil(0.95*n)`, counting positions from one.

```python
import math

def p95_ms(samples):
    if not samples:
        raise ValueError("measure at least one completed request")
    if any(type(x) not in (int, float) or not math.isfinite(x) or x < 0 for x in samples):
        raise ValueError("latency samples must be finite non-negative numbers")
    ordered = sorted(samples)
    return ordered[math.ceil(.95 * len(ordered)) - 1]

assert p95_ms(list(range(1, 101))) == 95
```

This list contains milliseconds from 1 to 100, so the selected value is 95 ms. With very few observations, a percentile estimate is unstable. Record the traffic conditions, sample size, time window and error rate beside latency. Do not improve latency by silently dropping slow failures from every reported outcome. Define a release gate that includes a quality check and a failure-rate check as well as latency, then document why those limits matter to the user.''',
'''#### Implementation lab: use evidence to repair a slow screen

Work a debugging case under a 20-minute limit. A search page takes two seconds after each keystroke. The browser starts a request on every input event; the server scans all rows; old responses sometimes replace new results. These are three separate defects, so one “performance fix” will not explain all symptoms.

First reproduce the problem with a fixed query and record the request count, network duration and database plan. Add a suitable index only after checking the filter and ordering. Reduce needless requests with a deliberate input policy such as debouncing; this means waiting briefly after typing stops. Guard stale results using request ownership even after cancellation. Measure again with the same conditions.

Your repair is ready when the result remains correct during rapid typing, the query uses the intended access path, errors remain visible and the measured improvement has a recorded baseline. Explain which change reduced server work and which change fixed correctness. A faster incorrect result is still a defect. In a mock interview, spend the last two minutes on the regression case and the limitation you have not yet tested.''',
'''#### Implementation lab: a fresh interview rehearsal

Choose a project change you have not rehearsed word for word. For example: a study tracker must now support corrections to previously saved sessions while keeping weekly totals correct. Spend five minutes clarifying whether a correction replaces a row or appends an adjustment, then draw the read and write paths. Spend fifteen minutes implementing one small part and five minutes testing and explaining it.

Use a fixture with sessions of 20 and 30 minutes. Correct 20 to 25; the total must become 55, not 75 or 30. Repeat the same correction and verify that it does not add another adjustment. Reject a correction from a different learner. Explain what happens if the response is lost after the save.

Write an honest review with three fields: the decision you made, the evidence from the trace or test, and what you would improve next. A correct explanation without working code and working code without an explanation reveal different practice needs. Keep those separate. Finish with one new example for your weakest concept; do not mark a skill mastered because you recognized a memorized answer.''',
)


def implementation_lab(day):
    """A connected weekly implementation, available without network or user data."""
    spec = interview_course.day_spec(day)
    text = _IMPLEMENTATION_LABS[spec['week'] - 1]
    sources = {
        1: ('Python numerical and boolean types', 'https://docs.python.org/3/library/stdtypes.html#boolean-type-bool'),
        2: ('PostgreSQL joins', 'https://www.postgresql.org/docs/current/tutorial-join.html'),
        4: ('PostgreSQL conditional updates and RETURNING', 'https://www.postgresql.org/docs/current/sql-update.html'),
        6: ('React guidance on stale request results', 'https://react.dev/learn/synchronizing-with-effects#fetching-data'),
    }
    if source := sources.get(spec['week']):
        text += f'\n\nImplementation reference: [{source[0]}]({source[1]}).'
    return text

_KICKOFF_QUESTIONS = {
    'ai_ml': [
        {'question': 'Which part of the study tracker needs machine learning, and which part should remain a rule?',
         'answer': 'Adding observed session minutes is an exact calculation. Estimating the duration of an unseen lesson is uncertain and may benefit from learning patterns. Start that estimate with a simple baseline, define its error on later observations, and add complexity only when the evidence supports it.',
         'follow_up': 'The candidate has mean absolute error 3 minutes on three examples. Is that enough to release it?',
         'follow_up_answer': 'No. The calculation is correct for those examples, but the sample is too small to establish reliable performance. Check the split, compare with the fixed baseline on more representative later sessions, inspect important groups, and measure the user-facing cost and latency.'},
        {'question': 'Why is the final session duration an invalid input for predicting that same duration?',
         'answer': 'It is not known when the learner asks for an estimate. Using it during evaluation leaks the answer and makes the reported result unlike the production task. Record when every feature becomes available and apply the same timing rule to training and evaluation.',
         'follow_up': 'Could a previous session duration be a valid input?',
         'follow_up_answer': 'Yes, if that previous session genuinely finished before the prediction and the value is available in the serving system. Preserve timestamps and learner boundaries so future sessions are not accidentally used as past information.'},
    ],
    'system_design': [
        {'question': 'Trace POST /api/study-summary from the browser to the visible result.',
         'answer': 'The browser sends JSON through an HTTP connection. The server enforces size and method rules, parses and validates the body, calls the summary calculation, and returns a status plus structured data. The page validates the response and updates only the current request. This endpoint does not save a session.',
         'follow_up': 'Where would ownership checks go when the next version reads saved sessions?',
         'follow_up_answer': 'On the server, before reading the learner’s records. Derive identity from the authenticated request and filter by that identity; a learner ID supplied by the browser is not permission.'},
        {'question': 'The response is lost. What does the client know, and when is retry safe?',
         'answer': 'The client knows that it did not receive a reliable result. It does not know whether the server finished. Repeating this stateless summary is safe because it changes no stored state. A write operation needs its own duplicate-handling contract.',
         'follow_up': 'How would you safely retry creating a study session?',
         'follow_up_answer': 'Use a stable operation identifier with a uniqueness rule and a saved result on the server. A repeated request returns that result instead of creating another session. Define retention and what happens if the same identifier is reused with different input.'},
    ],
    'full_stack': [
        {'question': 'How would you separate the HTTP boundary from the summary calculation?',
         'answer': 'Keep summarise_sessions responsible for validated numerical behavior and a clear output. The handler validates the request object, maps expected validation errors to a documented client response, and returns the result. The framework adapter handles HTTP parsing and serialization. Test the calculation without a server and test the adapter contract separately.',
         'follow_up': 'Why does an ordinary integer type check accept True in Python?',
         'follow_up_answer': 'Python bool is a subclass of int. If the product contract rejects booleans, use an exact type check or an explicit boolean rejection before numerical validation. A value that can participate in arithmetic is not automatically a valid duration.'},
        {'question': 'Why return null for the mean of an empty list instead of returning zero?',
         'answer': 'An empty list has no observations, so there is no mean to report. Zero is a valid measured duration and communicates different information. The page should show an empty state for null, while preserving a genuine zero result for a list containing zero.',
         'follow_up': 'An existing client assumes mean is always a number. How would you change this contract?',
         'follow_up_answer': 'Identify the callers, document the new empty-state behavior and update validation and rendering tests. Coordinate the rollout or version the response if compatibility requires it. Do not silently switch semantics and hope older clients cope.'},
    ],
}


def kickoff_questions(track):
    """Day-one questions shared by the chapter and bank, with stable IDs."""
    from copy import deepcopy
    if track not in _KICKOFF_QUESTIONS:
        raise ValueError('Choose AI & ML, system design or full-stack.')
    return deepcopy(_KICKOFF_QUESTIONS[track])
