# 09 — Interview Questions Bank (60+ Q&A, Senior Depth)

This is a self-test bank. Cover the answers, try to answer out loud as if in an interview, then check yourself. Organized into: Node.js (15), React (15), MongoDB (10), Docker/Kubernetes (15), and Scenario-Based (10).

---

## Section A — Node.js (15 questions)

**A1. What is the event loop, and why is Node still able to handle high concurrency despite being single-threaded for JS execution?**
Node delegates I/O work (network, disk, DNS) to the OS kernel's async facilities or libuv's thread pool, and the event loop's job is to pick up completed I/O results and run their callbacks on the single JS thread. Because the thread isn't blocked waiting for I/O to complete (it moves on to other work and comes back when notified), a single thread can juggle thousands of concurrent connections — the limiting factor becomes CPU-bound work in your own code, not I/O waiting.

**A2. What's the execution order of `process.nextTick`, Promise microtasks, and `setTimeout(fn, 0)`?**
`process.nextTick` callbacks run first (fully drained), then Promise microtasks (fully drained), both happening before the event loop proceeds to its next phase — and only then does a `setTimeout(fn, 0)` callback run, since timers are a distinct event loop phase processed after both queues are empty.

**A3. Why can recursive `process.nextTick` calls starve the event loop?**
The nextTick queue must be fully drained before Node proceeds to the next event loop phase (including the Poll phase where I/O callbacks run). If code keeps scheduling new `nextTick` callbacks from within existing ones, the queue never empties, and I/O callbacks (and therefore all other work) never get a chance to execute — effectively freezing the application while it appears to still be "running."

**A4. Explain the difference between `cluster` and `worker_threads`.**
`cluster` forks multiple OS processes that each run a full copy of your app with independent memory, used to scale request-handling across CPU cores (no shared memory; cross-process communication needs IPC or an external store). `worker_threads` runs multiple threads within a single process, optionally sharing memory via `SharedArrayBuffer`, and is the right tool for offloading CPU-intensive computation without blocking the main event loop.

**A5. What is backpressure in Node streams, and how does `.pipe()` handle it automatically?**
Backpressure is the situation where a writable destination can't consume data as fast as a readable source produces it. `.pipe()` automatically pauses the readable source when the writable's internal buffer is full (when `write()` returns `false`) and resumes it once the writable emits a `'drain'` event, preventing unbounded memory growth from buffering data faster than it can be written out.

**A6. Why is `stream.pipeline()` preferred over manually chaining `.pipe()` calls?**
`pipeline()` ensures that if any stream in the chain errors or is prematurely closed, all streams in the chain are properly destroyed and resources released, and it surfaces errors through a single callback. Manual `.pipe()` chains don't propagate errors between streams automatically and can leave dangling, unclosed streams on failure, risking memory or file-descriptor leaks.

**A7. What's the difference between `useLayoutEffect`-style synchronous work and Node's deferred async work, in terms of blocking the event loop? (A node-specific angle: why avoid synchronous APIs like `fs.readFileSync` in request handlers?)**
Synchronous APIs block the single JS thread for their entire duration — while `fs.readFileSync` is running, the event loop cannot process any other request, timer, or I/O callback, so every concurrent user of your server is delayed. The async equivalent (`fs.readFile` or `fs.promises.readFile`) offloads the actual file I/O to libuv's thread pool and returns control to the event loop immediately, letting other requests continue to be processed while the file read completes in the background.

**A8. Why should error-handling middleware in Express have exactly 4 parameters?**
Express distinguishes error-handling middleware from regular middleware purely by function arity (parameter count) — a function with signature `(err, req, res, next)` is registered as an error handler, while `(req, res, next)` is treated as regular middleware. This arity check is how Express knows to route a `next(err)` call to the correct handler in the middleware chain.

**A9. What's the purpose of wrapping async route handlers with a utility like `asyncHandler`?**
Express doesn't automatically catch rejected Promises thrown inside `async` route handlers — an unhandled rejection in an async handler won't invoke your error-handling middleware by default, and can crash the process or silently hang the request. `asyncHandler` wraps the handler so any rejected Promise is explicitly passed to `next(err)`, correctly routing it into Express's centralized error handling.

**A10. Why is logging passwords, tokens, or full request bodies a security risk, even in "just debug logs"?**
Logs are often retained for long periods, shipped to third-party aggregation services, and accessible to a broader set of engineers (support, on-call) than the production database itself — logging sensitive data multiplies the number of places a secret can leak from, and debug logs have a habit of accidentally being left enabled in production. Use log redaction (stripping sensitive fields before logging) as a structural safeguard rather than relying on remembering not to log them.

**A11. How would you prevent a single slow downstream API call from taking down your entire Node service under load?**
Enforce request timeouts on all outbound calls (so a hung dependency doesn't tie up your event loop's resources indefinitely waiting), and consider a circuit breaker pattern (e.g., using a library like `opossum`) that stops sending requests to a dependency that's already failing repeatedly, failing fast instead of queueing more requests behind an already-struggling service — this prevents a slow dependency from cascading into exhausting your own server's connection pool/memory.

**A12. What's the risk of NoSQL injection in an Express + MongoDB app, with a concrete example?**
If `req.body.username` is passed directly into a Mongoose/MongoDB query without validating it's actually a string, an attacker can send `{"username": {"$gt": ""}}` as JSON — since `$gt: ""` matches any non-empty string, this can bypass an authentication check entirely by matching the first document instead of a specific user. The fix is schema validation (Zod/Joi) enforcing primitive types before the value ever reaches a query, plus sanitization middleware like `express-mongo-sanitize` that strips `$`/`.`-prefixed keys from user input.

**A13. Why does Helmet remove the `X-Powered-By` header?**
That header advertises `Express` (and sometimes version info) by default, giving attackers an easy signal about your technology stack, which can help them target known framework-specific vulnerabilities. Removing it is a small but free reduction in fingerprinting surface — it doesn't fix any actual vulnerability, but it removes one piece of reconnaissance information.

**A14. In a multi-replica deployment, why does `express-rate-limit`'s default in-memory store fail to enforce a correct global rate limit?**
The default store keeps counts in the memory of a single process; with multiple replicas behind a load balancer, each replica tracks its own independent count for the same client, so a client could effectively get `limit × number of replicas` total requests instead of the intended single `limit`. The fix is a shared store (like `rate-limit-redis`) so all replicas read/write the same counter.

**A15. How do you decide whether a CPU-heavy task (like PDF generation) belongs in `worker_threads`, a separate microservice, or a background job queue?**
If the task is relatively quick (sub-second) but still CPU-intensive enough to notably block the event loop, `worker_threads` keeps it in-process while avoiding blocking request handling. If the task is slow (seconds to minutes), resource-intensive at scale, or needs independent scaling/retries, a background job queue (BullMQ/Redis, or a dedicated worker microservice) is more appropriate — it decouples the task's lifecycle from the request/response cycle entirely, lets you retry failures, and scales workers independently from the API layer.

---

## Section B — React (15 questions)

**B1. Why must hooks be called unconditionally at the top level of a component?**
React tracks hook state as a linked list indexed purely by call order on a component's Fiber node, not by hook name — if a hook is conditionally skipped on some render, every subsequent hook's position in that list shifts, causing React to read or write the wrong stored state for each hook, leading to bugs or an explicit "rendered fewer/more hooks than expected" error.

**B2. What problem does the functional form of `setState` (`setCount(prev => prev + 1)`) solve?**
Each call within the same render closes over the state value as it was at the start of that render (the latest "known" render-time value), so calling `setCount(count + 1)` multiple times in the same event handler only ever adds 1 total, since each call reads the same stale `count`. The functional form receives the most up-to-date pending state value at the time each queued update is actually applied, correctly accumulating multiple updates within a single batch.

**B3. What's the Fiber architecture, and what capability does it unlock that the old reconciler couldn't provide?**
Fiber represents each unit of rendering work as a plain JS object (rather than a native call stack frame), which can be paused, resumed, prioritized, or discarded. This unlocks interruptible rendering — React can pause a large render mid-tree to handle more urgent work (like responding to user input) and resume later, which is the foundation for React 18's concurrent features like `useTransition` and Suspense for data fetching.

**B4. Why is using array index as a list `key` risky?**
React's diffing uses `key` to match elements between renders; with index keys, reordering, inserting, or removing items from the middle of a list shifts the indices of unrelated items, causing React to misattribute component state (like input focus or internal state) to the wrong logical item, and often triggering unnecessary unmounts/remounts that are both a correctness bug and a performance cost.

**B5. `React.memo` isn't preventing re-renders as expected — what's the likely cause, and what's the fix?**
Almost always, the parent is passing new object/array/function references as props on every render (e.g., an inline arrow function or object literal created directly in JSX), which fails `memo`'s shallow prop comparison even though the logical content is unchanged. Fix by memoizing those references on the parent side with `useCallback` (for functions) or `useMemo` (for objects/arrays) so they only change when their actual dependencies change.

**B6. When should you use `useLayoutEffect` instead of `useEffect`?**
Use `useLayoutEffect` only when you need to read the DOM's layout (size/position) and synchronously adjust it before the browser paints, to avoid a visible flicker — e.g., measuring an element and repositioning a tooltip based on that measurement. `useLayoutEffect` blocks painting until it completes, so overusing it hurts performance; default to `useEffect` for anything that doesn't specifically require pre-paint DOM reads.

**B7. Explain the Context re-render problem, and describe one way to mitigate it.**
Every component consuming a Context via `useContext` re-renders whenever the Provider's `value` reference changes, with no built-in mechanism to subscribe to only a slice of that value — unlike Redux/Zustand's selector-based subscriptions. One mitigation is memoizing the Provider's `value` object with `useMemo` so it only changes when its actual dependencies change, though this doesn't fully solve the problem for Contexts with many fields updated independently — splitting into multiple smaller Contexts, one per logically-independent piece of state, is a more complete fix.

**B8. What's the practical difference between Redux Toolkit and Zustand in terms of architecture?**
Redux Toolkit enforces a single global store with reducers, actions, and middleware, providing strong conventions, time-travel debugging, and a large ecosystem (RTK Query for data fetching) — valuable at scale with many contributors needing shared patterns. Zustand provides a much smaller API surface with no required Provider wrapper, selector-based subscriptions built in by default (so components only re-render for the slice they read), and works even outside React components — less boilerplate, less enforced structure, well-suited to small-to-mid apps or teams that don't need Redux's full tooling.

**B9. Why shouldn't server data (API responses) typically be stored in Redux/Zustand directly?**
Server data has a fundamentally different lifecycle than client UI state — it can go stale, needs caching/deduplication of concurrent fetches for the same resource, often needs background refetching and retry logic, and is keyed by query parameters rather than being a single global value. Dedicated data-fetching libraries (TanStack Query, RTK Query) handle all of this out of the box; reimplementing it manually inside a Redux slice duplicates significant, error-prone logic that already exists in well-tested form elsewhere.

**B10. Explain SSR vs SSG vs ISR with a concrete use case for each.**
SSR renders on the server per request, ideal for personalized/frequently-changing pages like a logged-in dashboard, at the cost of per-request server render latency. SSG renders once at build time into static files served instantly (often via CDN), ideal for content identical for every visitor that changes rarely, like a marketing page. ISR statically generates at build time but regenerates in the background on a timer, giving static-like performance for content that updates occasionally but doesn't need to be instantly fresh, like a product catalog page.

**B11. What's the architectural benefit of React Server Components over traditional client-side data fetching?**
Server Components run only on the server, can access databases/secrets directly, and contribute zero JavaScript to the client bundle — they never need to be hydrated. This lets you push interactivity (`'use client'` boundaries) down to only the small leaf components that actually need it, significantly shrinking the JS shipped to the browser compared to an architecture where the entire page tree is a client-rendered bundle that then fetches data after mount.

**B12. Why does React Testing Library discourage querying by CSS class or component internals?**
Testing internal implementation details ties tests to how a component happens to be built rather than how it behaves for an actual user, making tests brittle to harmless refactors and poor at catching genuine behavioral regressions. RTL's recommended query priority (role, label text, visible text, with test ID as a last resort) mirrors how a real user or assistive technology perceives the page, so tests validate the actual user-facing contract and remain stable as long as that contract doesn't change.

**B13. Why use MSW (Mock Service Worker) instead of mocking `fetch` directly in component tests?**
MSW intercepts requests at the network layer, so the component code under test runs completely unmodified (it still calls real `fetch`/`axios` as it would in production) — this gives higher-fidelity tests than replacing `fetch` with a hand-rolled mock, and the same mock handler definitions can be reused across unit tests, integration tests, and tools like Storybook, rather than duplicating mock logic per test file.

**B14. What's a practical checklist for diagnosing a React performance problem before reaching for `useMemo`/`React.memo` everywhere?**
Start by measuring with the React DevTools Profiler to identify which components actually re-render unnecessarily and how long they take, rather than guessing. Check for route-level code splitting opportunities, verify large lists are virtualized, confirm state is colocated close to where it's used rather than lifted unnecessarily high (causing broad re-render fan-out), and only then apply targeted memoization to the specific components the profiler flags as expensive — blanket memoization everywhere adds its own overhead and complexity without guaranteed benefit.

**B15. Why does `useEffect` depending on an inline object or array literal cause the effect to re-run every render, and how do you fix it?**
An object or array literal created inline during render (e.g., `{ page, limit }` written directly in the component body) is a brand-new reference on every render, even if its contents are identical to the previous render's — React's dependency comparison uses `Object.is` (reference equality), so it sees a "changed" dependency every time. Fix by either depending on the primitive values directly (`[page, limit]`) instead of the wrapping object, or memoizing the object itself with `useMemo` so its reference only changes when its actual underlying values change.

---

## Section C — MongoDB (10 questions)

**C1. How do you decide between embedding and referencing for a one-to-many relationship?**
Embed when the related data is always read together with the parent, is bounded in size, and updates at a similar frequency to the parent (respecting the 16MB document size limit). Reference when the related data is unbounded in growth (can accumulate indefinitely, like comments or order history) or is frequently queried/updated independently of the parent.

**C2. Explain the ESR rule for compound index design.**
Equality fields should come first in the index (narrows to an exact match immediately), Sort fields come next (so results are already in the needed order without an expensive in-memory sort), and Range-filtered fields come last (since they scan a contiguous span of the index rather than a point lookup) — getting this order wrong forces MongoDB to scan far more index entries than necessary for a given query.

**C3. A query looks like it should use an index but is still slow — how do you diagnose it?**
Run `.explain("executionStats")` and verify the winning plan's stage is `IXSCAN`, not `COLLSCAN`. Compare `totalDocsExamined` against `nReturned` — a large gap signals a poorly selective index or an index/query field order mismatch (ESR violation); also check for operators (`$ne`, unanchored regex) that inherently can't use an index efficiently.

**C4. When should you use a multi-document transaction, and when should you avoid one?**
Use one when an operation must atomically update multiple documents, possibly across collections, where a partial failure would leave data inconsistent (a funds transfer touching two account documents). Avoid one when the same guarantee can be achieved with a single atomic document update instead (MongoDB guarantees atomicity within one document including nested arrays) — reaching for a transaction when a schema redesign would eliminate the need adds unnecessary locking overhead and latency.

**C5. What's the difference between replication and sharding?**
Replication copies the same dataset across multiple nodes for high availability and automatic failover (one primary, multiple secondaries). Sharding partitions a dataset across multiple independent shards to scale write throughput and total storage beyond a single machine/replica set's capacity — in production, each shard is itself typically a replica set, combining both techniques.

**C6. What causes a "hot shard," and how do you avoid it?**
A shard key that concentrates writes (or reads) disproportionately onto one shard — commonly a monotonically increasing value like a timestamp or auto-incrementing ID, where every new write lands on the shard owning the current highest key range. Avoid it by choosing a high-cardinality, evenly-distributed shard key, or using a hashed shard key to pseudo-randomly distribute values regardless of their natural ordering.

**C7. Why use `.lean()` in Mongoose for read-heavy endpoints, and what's the tradeoff?**
`.lean()` returns plain JS objects instead of full Mongoose Documents, skipping change tracking, virtuals, and instance methods, which is meaningfully faster and lower-memory for pure read paths. The tradeoff is losing the ability to call `.save()` on the result or use schema-defined virtuals/methods, so it's appropriate only for data you're reading and returning, not mutating and persisting.

**C8. Explain the `$facet` aggregation stage and a practical use case.**
`$facet` runs multiple independent sub-pipelines against the same input documents in parallel, returning all their results in one combined document — a common use case is computing a paginated page of results and a total count simultaneously in a single aggregation call (one sub-pipeline does `$skip`/`$limit`, another does `$count`), avoiding two separate round trips to the database.

**C9. Why put `$match` as early as possible in an aggregation pipeline?**
If `$match` is the very first stage, MongoDB can use an existing index to satisfy it before any other processing, and it reduces the number of documents flowing into every subsequent (often more expensive) stage like `$unwind` or `$group`. Once you've passed through `$unwind` or `$group`, you've lost the ability to leverage an index for any later filtering.

**C10. What's the "extended reference" pattern, and what problem does it solve?**
It embeds a small, denormalized snapshot of frequently-needed fields from a referenced document (e.g., a product's name and price-at-purchase-time embedded directly in an order) alongside the actual reference (`productId`), avoiding both an unbounded embed and a join for the common read path. It also solves a correctness problem: if the referenced data changes later (like a product's price), historical records (like past orders) still correctly show the value as it was at the time, rather than silently reflecting the current value through a join.

---

## Section D — Docker/Kubernetes (15 questions)

**D1. Why use a multi-stage Dockerfile?**
It separates the environment needed to build/compile the app (which may include compilers, dev dependencies, source maps) from the final runtime image, which only needs the production build output and production dependencies — producing a smaller, less vulnerable final image since build tooling never ships to production.

**D2. Why run containers as a non-root user?**
If an attacker achieves remote code execution in your application, running as root inside the container gives them root-level privileges within that container's namespace, meaningfully increasing the impact of any container escape vulnerability. A dedicated non-root user limits what a compromised process can do even in a worst-case scenario.

**D3. Why doesn't `depends_on` alone guarantee a dependent service won't fail at startup in docker-compose?**
`depends_on` only ensures the dependency's container has *started*, not that the service inside it has finished its own initialization and is ready to accept connections (which commonly takes additional seconds for databases). Pairing it with a `healthcheck` and `condition: service_healthy` makes Compose wait for genuine readiness — the same concept implemented by Kubernetes readiness probes.

**D4. Explain the Kubernetes reconciliation loop model.**
You declare a desired state (e.g., "3 replicas of this Pod spec") which is persisted by the API server into etcd; controllers continuously compare that desired state against the actual observed cluster state and take whatever actions close the gap, forever, automatically healing deviations like a crashed Pod. This is why `kubectl apply` is idempotent — it updates desired state rather than issuing a one-time imperative command.

**D5. Liveness vs readiness probes — what's the risk of conflating them?**
Liveness answers "is this container stuck and needs restarting," failing it causes a restart; readiness answers "is this container currently able to serve traffic," failing it only removes the Pod from Service endpoints without restarting. Using the same check for both means a transient, recoverable issue (like a brief downstream dependency blip) can trigger unnecessary restarts across potentially all replicas simultaneously, turning a minor hiccup into a cascading "restart storm."

**D6. Why is MongoDB deployed as a StatefulSet rather than a Deployment in Kubernetes?**
StatefulSet gives each replica a stable, predictable network identity (e.g., `mongo-0`, `mongo-1`) needed for replica set members to consistently address each other, and a dedicated persistent volume per ordinal replica that follows it across rescheduling — properties a Deployment's interchangeable, identity-less Pods don't provide.

**D7. What controls a rolling update's behavior, and how do you achieve true zero-downtime with it?**
`maxSurge` caps how many extra Pods above the desired replica count can exist temporarily during rollout, and `maxUnavailable` caps how many Pods can be down simultaneously — setting `maxUnavailable: 0` guarantees full capacity is maintained throughout. True zero-downtime additionally requires correct readiness probes (so new Pods don't receive traffic before they're actually ready) and graceful shutdown handling in the application (so terminating old Pods finish in-flight requests rather than dropping them).

**D8. What's the difference between a resource request and a resource limit, and what happens when each is exceeded?**
A request is what the scheduler reserves when placing a Pod on a node; a limit is a hard ceiling on usage. Exceeding a memory limit gets the container OOMKilled and restarted, since memory is non-compressible. Exceeding a CPU limit doesn't kill the container — CPU is compressible, so the process is simply throttled, running slower but continuing.

**D9. Why isn't base64 encoding in a Kubernetes Secret sufficient protection for sensitive data?**
Base64 is trivially reversible, not encryption — anyone with read access to the Secret object can decode it with a single command. Real protection requires restricting RBAC on who can read Secrets, enabling encryption-at-rest for etcd, and avoiding committing raw Secret manifests to version control, often via tools like Sealed Secrets or an external secret manager integration.

**D10. Explain the difference between a ClusterIP, NodePort, and LoadBalancer Service.**
ClusterIP (default) is only reachable from inside the cluster, used for internal service-to-service traffic. NodePort exposes the Service on a static port across every node's IP, mostly used as a building block rather than directly in production. LoadBalancer provisions an external cloud load balancer, typically used for a small number of genuinely external entry points (often just the Ingress controller itself, with everything else routed through Ingress rules rather than individual LoadBalancer Services).

**D11. What role does an Ingress Controller play, and why is it not built into Kubernetes core?**
Ingress objects define HTTP(S) routing rules (host/path-based), but Kubernetes core has no built-in component that actually implements those rules — an Ingress Controller (like nginx-ingress or Traefik) must be separately installed to watch Ingress objects and configure an actual reverse proxy accordingly. This separation lets the ecosystem offer multiple interchangeable Ingress Controller implementations rather than Kubernetes mandating one specific proxy technology.

**D12. How does HPA decide when to scale, and what's a limitation of relying purely on CPU-based scaling for an I/O-bound Node.js API?**
HPA periodically compares observed metrics (via the Metrics Server, or custom metrics via an adapter) against a target utilization and adjusts replica count to converge toward that target. For an I/O-bound API, CPU usage can remain low even while requests are queued and effectively throughput-starved waiting on downstream calls, since CPU isn't the actual bottleneck — a request-based custom metric (requests-per-second per Pod, or queue depth) is often a more accurate scaling signal than CPU for such workloads.

**D13. Diagnose: a Pod shows `CrashLoopBackOff`. What's your process?**
Start with `kubectl describe pod` to check the Events section and last termination reason (often immediately reveals an OOMKill, failed probe, or plain crash). Then `kubectl logs <pod> --previous` is essential — the current, freshly-restarted container's log stream won't contain the crash's actual error, but the previous instance's logs almost always will, typically showing an uncaught exception, missing env var, or failed startup dependency.

**D14. Why use Helm instead of raw `kubectl apply -f manifests/`?**
Helm templates manifests so a single chart can be parameterized differently per environment via separate `values.yaml` files, avoiding near-duplicate raw YAML across dev/staging/production, and tracks a full set of resources as one versioned, atomic release that can be upgraded or rolled back as a unit (`helm upgrade`/`helm rollback`) rather than manually tracking which raw manifest edits shipped together.

**D15. Why can over-provisioned resource requests silently increase your cloud bill even when actual utilization is low?**
Cluster autoscalers provision node capacity based on aggregate *requested* resources across Pods, not real-time actual usage — inflating requests "just to be safe" directly inflates the number of nodes (and therefore cost) the autoscaler provisions, even if the real CPU/memory utilization sitting on those nodes is low. Right-sizing requests based on observed p95/p99 usage data, rather than guesswork, is the most common fix for this class of silent cost leak.

---

## Section E — Scenario-Based (10 questions)

**E1. "Our API works fine in staging but falls over under real production load. Walk me through your investigation."**
First check whether the service is actually scaled horizontally in production the way it is (or isn't) in staging — a single-replica Node process only uses one CPU core, and staging load tests often under-represent real concurrency. Next, profile for CPU-bound blocking code in the hot request path (synchronous crypto, JSON parsing on large payloads) using a profiler like `clinic doctor` or `node --prof`, since this would manifest specifically under real concurrent load, not in a light staging test. Also check database connection pool sizing and whether the database itself (not just the API layer) is the actual bottleneck under realistic concurrent query volume, and review whether rate limiting/caching that exists in production but not staging (or vice versa) is masking or revealing different behavior.

**E2. "A user reports they were logged out of your app unexpectedly across all their devices. How would you investigate, assuming refresh token rotation is implemented?"**
Check the refresh token store for that user — if a token reuse event was detected (an already-rotated-out token presented again), your system would have deliberately revoked the entire token family as a security measure, logging the user out everywhere; this could be a false positive from a race condition (e.g., two near-simultaneous refresh requests from the same legitimate client, perhaps from a flaky network retry) rather than actual theft. Investigate the exact sequence of refresh requests and timestamps in logs for that user to distinguish a genuine security event from a client-side bug causing duplicate/racing refresh calls.

**E3. "Your MongoDB collection has grown to the point that common queries are now slow. What's your step-by-step approach?"**
Run `.explain("executionStats")` on the slow queries first to confirm whether they're using an index at all (`IXSCAN` vs `COLLSCAN`), and check if `totalDocsExamined` is far larger than `nReturned`, indicating poor index selectivity or an ESR-order mismatch. If indexes are already optimal, consider whether the access pattern itself needs to change — e.g., introducing a cache layer for hot reads, denormalizing frequently-joined data, or, if write throughput/data volume genuinely exceeds a single replica set's capacity, planning a sharding strategy with a well-chosen shard key.

**E4. "You need to add a new required field to an existing collection with millions of documents, without downtime. How do you do it safely?"**
Never add it as a hard database-level required constraint immediately — first deploy application code that writes the new field going forward and has a sensible fallback/default when reading it from old documents that don't have it yet (backward-compatible). Then run a background migration script that backfills the field on existing documents in batches (to avoid long write locks or memory spikes), and only after confirming all documents have the field, if truly needed, enforce it as required at the application validation layer — treating this as a multi-release rollout rather than a single atomic schema change, exactly like the backward-compatible migration pattern needed for zero-downtime deploys.

**E5. "Your React app's initial load time is too slow on mobile. What are your first three optimizations?"**
Route-based code splitting with `React.lazy`/`Suspense` to avoid shipping JS for routes the user hasn't visited yet, since this typically has the highest leverage-to-effort ratio for reducing Time to Interactive. Audit and lazy-load below-the-fold images with modern formats (WebP/AVIF) and responsive sizing, since images are frequently the largest payload contributor on mobile. Then measure with Lighthouse/Web Vitals to identify the actual largest contentful paint blocker rather than guessing further — it might reveal a large third-party script or an unoptimized font loading strategy that wouldn't have been obvious without measurement.

**E6. "Your Kubernetes rolling update is causing a brief spike in 502 errors on every deploy. Diagnose and fix."**
The most common cause is a readiness probe that passes before the application is actually able to handle real traffic (e.g., it returns 200 immediately on process start rather than after confirming DB/Redis connectivity), so new Pods receive traffic before truly ready — fix by pointing readiness at a check that verifies actual downstream dependency connectivity. The second most common cause is missing graceful shutdown handling, where old Pods are killed before finishing in-flight requests; fix with a `SIGTERM` handler that stops accepting new connections but lets existing requests complete, plus a short `preStop` hook delay to account for Service endpoint propagation lag across the cluster.

**E7. "A teammate wants to store the JWT access token in `localStorage` for simplicity. How do you respond?"**
`localStorage` is readable by any JavaScript running on the page, including an injected script from an XSS vulnerability — if an attacker achieves even a minor XSS injection anywhere on the site, they can trivially steal every token stored there. I'd recommend keeping the access token in memory (a JS variable, lost on refresh but not exposed to XSS) and the longer-lived refresh token in an `httpOnly` cookie (not readable by JS at all even under XSS, though it does require CSRF protection via `SameSite` since cookies are sent automatically by the browser) — this combination gives meaningfully better protection against the most common real-world token theft vector.

**E8. "Your team wants to split a monolithic MERN app into microservices. What's your first question before agreeing to that plan?"**
I'd ask what specific problem microservices are meant to solve — independent team scaling (different teams needing independent deploy cadences), independent infrastructure scaling (one component has very different load characteristics than the rest), or technology diversity needs — because microservices introduce real complexity costs (distributed transactions instead of single-database ACID guarantees, network calls replacing function calls, more complex debugging/tracing, more deployment surface area) that aren't worth paying without a concrete problem they solve; a monolith with well-organized internal module boundaries (the routes/controllers/services/models layering from file 05) can scale a long way before that complexity tradeoff becomes worthwhile.

**E9. "Users in a specific geographic region report significantly higher latency than everyone else. How do you investigate?"**
First confirm it's actually network/infrastructure latency and not application logic by checking server-side request duration metrics (from file 08's instrumentation) filtered to requests from that region's IP ranges — if server-side processing time is normal but end-to-end latency is high, the issue is in transit (distance to the nearest server/CDN edge, or an inefficient routing path) rather than the application. If it IS server-side, check whether that region's traffic is being routed to a geographically distant cluster/database replica (e.g., cross-region database calls adding real round-trip latency) — the long-term fix is often deploying read replicas or edge caching closer to that user population.

**E10. "Explain how you'd design the deployment pipeline for a MERN app from a fresh `git push` all the way to it running safely in production, mentioning every stage and why it exists."**
A push triggers CI: lint/type-check first (fastest feedback, fails cheap), then automated tests against real service containers (Mongo/Redis) to catch integration-level regressions, then building Docker images tagged with the immutable git SHA (for traceability and safe rollback), then scanning those images for known vulnerabilities (failing the pipeline on critical/high findings as a security gate), then pushing to a container registry. Deployment then proceeds to staging automatically via `kubectl set image`/Helm upgrade, waiting on `kubectl rollout status` to confirm the rolling update actually succeeded (not just that the command was issued), followed by an automated smoke test hitting a health endpoint. Only after staging passes does production deployment become eligible, typically gated by a manual approval step for business-sensitive releases, using the identical rolling-update + readiness-probe + graceful-shutdown mechanisms to guarantee zero downtime, with post-deploy monitoring (error rate, latency dashboards from file 08) watched actively for a period after each production release to catch regressions the automated checks might have missed.

---

## How to use this bank

- Don't just read the answers — **explain each one out loud, from memory, in your own words**, then compare against the written answer for gaps.
- For the scenario questions (Section E) especially, practice asking **clarifying questions first** in a real interview before launching into an answer — senior interviewers notice and reward this.
- Revisit this file a few days before an actual interview as a final refresher pass, after having done the Practice Tasks in files 01-08 — the hands-on practice is what makes these answers feel natural rather than memorized.
