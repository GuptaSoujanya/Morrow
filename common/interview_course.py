"""Public, versioned syllabus for the same 90-day interview course for everyone.

This module contains no account, resume or generated workspace data. Learning
progress and lesson generation are private; the teaching sequence is shared.
"""
from __future__ import annotations

import re
from datetime import date

COURSE_ID = 'interview-90'
COURSE_VERSION = 1
# Teaching style can improve without changing the syllabus or resetting progress.
TEACHING_VERSION = 5
COURSE_TITLE = '90-day interview course'
TOTAL_DAYS = 90

SUBJECTS = ('AI & machine learning', 'System design', 'Full-stack development', 'DSA & interviews')
DAILY_SESSION = (
    ('ai_ml', 'AI & machine learning', 55),
    ('system_design', 'System design', 55),
    ('full_stack', 'Full-stack development', 55),
    ('dsa', 'DSA practice', 60),
    ('recall', 'Explain it in your own words', 15),
)
PHASES = (
    ('Build your foundations', 1, 28),
    ('Build and connect real systems', 29, 56),
    ('Design, deliver and practise interviews', 57, 84),
    ('Review and mock interviews', 85, 90),
)

# Each week's seven aligned rows are a deliberate progression, not topics chosen
# from a resume. The last week has six days so the course ends exactly on day 90.
_WEEKS = (
    ('How software and learning systems work', 'A small study tracker with a tested API', (
        ('What is machine learning?', 'How a web request travels', 'Python values, functions and a tiny API', 'Arrays: read, update and scan'),
        ('Data, labels and features', 'Clients, servers and HTTP', 'HTML, CSS and an accessible page', 'Strings and frequency counts'),
        ('Training versus using a model', 'APIs and status codes', 'JavaScript variables, functions and events', 'Hash maps and sets'),
        ('A first prediction with a baseline', 'Latency, throughput and availability', 'Send and receive JSON', 'Big O time and space'),
        ('Training and test data', 'Databases and persistent storage', 'SQL tables, keys and simple queries', 'Two pointers'),
        ('Errors, bias and data leakage', 'Stateful and stateless services', 'Connect the page, API and database', 'Sliding windows'),
        ('Explain your first model', 'Trace the complete request path', 'Build and explain the study tracker', 'Review arrays and hashing'),
    )),
    ('Data and reliable application basics', 'A data dashboard with clean inputs and useful tests', (
        ('Vectors and matrices in plain language', 'Requirements and useful estimates', 'Python collections and input validation', 'Prefix sums'),
        ('Probability and uncertainty', 'SQL versus document databases', 'SQL joins and grouped reports', 'Sorting and comparators'),
        ('Mean, variance and distributions', 'Indexes and query performance', 'Database indexes and query plans', 'Binary search'),
        ('Clean missing and messy data', 'Transactions and consistency', 'Transactions and migrations', 'Linked lists'),
        ('Explore a dataset before modelling', 'Caching basics', 'HTTP errors and loading states', 'Stacks'),
        ('Prepare features without leakage', 'API contracts and versioning', 'Unit and API integration tests', 'Queues'),
        ('Review data quality and uncertainty', 'Design a simple dashboard service', 'Build a tested data dashboard', 'Review search and linear structures'),
    )),
    ('Classical machine learning and secure apps', 'A baseline prediction service with sign-in', (
        ('Linear regression and loss', 'Load balancing', 'Components, props and state', 'Recursion'),
        ('Gradient descent step by step', 'Horizontal and vertical scaling', 'Forms and validation', 'Backtracking: subsets'),
        ('Classification and logistic regression', 'Sessions and tokens', 'Authentication and password handling', 'Backtracking: combinations'),
        ('Precision, recall and confusion matrices', 'Authentication versus authorization', 'Authorization and protected routes', 'Trees and traversals'),
        ('Decision trees and overfitting', 'Rate limits and quotas', 'Pagination, filtering and sorting', 'Binary search trees'),
        ('Cross-validation and model selection', 'Logging and health checks', 'Serve a model behind an API', 'Breadth-first search'),
        ('Compare a model with a baseline', 'Design a prediction API', 'Demo and test the prediction service', 'Review recursion and trees'),
    )),
    ('Better models and asynchronous systems', 'A queued prediction service with visible job status', (
        ('Random forests and ensembles', 'Queues and background jobs', 'Background jobs and status endpoints', 'Depth-first search'),
        ('Boosting and tabular baselines', 'Retries and exponential backoff', 'Retries, timeouts and cancellation', 'Heaps and top K'),
        ('Class imbalance and thresholds', 'Idempotency and duplicate messages', 'Idempotent API writes', 'Intervals'),
        ('Clustering and distance', 'Event-driven systems', 'Events and real-time job progress', 'Greedy choices'),
        ('Dimensionality reduction', 'Batch versus stream processing', 'Batch imports and data validation', 'Graphs and adjacency lists'),
        ('Model explanations and limitations', 'Observability: logs, metrics and traces', 'Structured logs and error reporting', 'Graph BFS and DFS'),
        ('Review classical ML trade-offs', 'Design an asynchronous ML service', 'Build and explain the queued service', 'Foundation coding mock'),
    )),
    ('Neural networks and production delivery', 'A deployed neural-network demo with a repeatable build', (
        ('Neurons, layers and activations', 'Deployment environments', 'Containers and reproducible builds', 'Dynamic programming: repeated subproblems'),
        ('Backpropagation intuitively', 'CI and safe releases', 'Continuous integration and test gates', 'Dynamic programming: one dimension'),
        ('Training loops and optimizers', 'Configuration and secrets', 'Environment configuration and secrets', 'Dynamic programming: grids'),
        ('Regularization and dropout', 'Object storage and CDNs', 'File uploads and object storage', 'Dynamic programming: subsequences'),
        ('Embeddings and representation learning', 'Capacity and cost estimates', 'Deployment and health checks', 'Dynamic programming: knapsack'),
        ('Experiment tracking and reproducibility', 'Rollback and recovery', 'Monitor and roll back a release', 'Review dynamic programming patterns'),
        ('Explain a neural network experiment', 'Design a model deployment', 'Deploy and demonstrate the model app', 'Timed dynamic programming practice'),
    )),
    ('Language models and useful AI features', 'A streamed AI assistant with tests and clear limits', (
        ('Tokens and language modelling', 'Streaming responses', 'Streaming UI and server events', 'Tries'),
        ('Attention with a small example', 'Latency budgets', 'Async requests and cancellation', 'String matching patterns'),
        ('Transformer building blocks', 'Concurrency and resource limits', 'Concurrency and connection pools', 'Topological sorting'),
        ('Pretraining, fine-tuning and prompting', 'API gateways and service boundaries', 'A typed API client', 'Shortest paths'),
        ('Prompt structure and structured output', 'Validation at system boundaries', 'Validate structured AI responses', 'Union-find'),
        ('Hallucinations and grounded answers', 'Failure modes and graceful degradation', 'Fallbacks and useful error messages', 'Mixed graph practice'),
        ('Evaluate a language-model feature', 'Design an AI assistant', 'Build a tested streaming assistant', 'Language-model and coding mock'),
    )),
    ('Retrieval and search systems', 'A document assistant with citations and a retrieval evaluation', (
        ('Retrieval-augmented generation', 'Search system requirements', 'Document import and parsing', 'Binary search on an answer'),
        ('Chunking and text preparation', 'Search indexes', 'Chunk documents and store metadata', 'Sliding window review'),
        ('Embedding similarity', 'Vector search architecture', 'Build a retrieval endpoint', 'Heap and top K review'),
        ('Keyword and hybrid retrieval', 'Replication and read scaling', 'Search UI, filters and pagination', 'Tree path problems'),
        ('Reranking and context selection', 'Caching search results', 'Add citations to generated answers', 'Graph reachability review'),
        ('Measure retrieval and answer quality', 'Freshness and index updates', 'A small evaluation dataset and runner', 'Mixed dynamic programming practice'),
        ('Explain RAG trade-offs', 'Design a document question-answering system', 'Demo and evaluate the document assistant', 'RAG and coding mock'),
    )),
    ('Agents, tools and dependable workflows', 'A tool-using assistant with approval and recovery', (
        ('When to use an agent', 'Workflow state machines', 'Model a multi-step workflow', 'Backtracking with pruning'),
        ('Tool calling and schemas', 'Synchronous versus asynchronous work', 'Implement and validate tool inputs', 'Scheduling with heaps'),
        ('Planning and bounded execution', 'Timeouts and circuit breakers', 'Execution limits and cancellation', 'Monotonic stacks'),
        ('Memory versus retrieved context', 'Durable state and checkpoints', 'Save and resume workflow state', 'Monotonic queues'),
        ('Prompt injection and untrusted inputs', 'Permissions and trust boundaries', 'Approval for actions with side effects', 'Graph cycle detection'),
        ('Agent evaluation and failure analysis', 'Audit trails and traceability', 'Trace tool calls and test failures', 'Choose the right DSA pattern'),
        ('Compare agents with simpler workflows', 'Design a dependable assistant workflow', 'Build and test the tool-using assistant', 'Agent and coding mock'),
    )),
    ('ML systems at scale', 'A monitored ML pipeline with versioned data and models', (
        ('Training and serving skew', 'Offline and online architecture', 'Data validation in a training pipeline', 'Arrays and hashing interview set'),
        ('Feature pipelines and freshness', 'Streaming ingestion and backpressure', 'Batch and event ingestion', 'Two pointers and window interview set'),
        ('Model registry and versioning', 'Storage partitioning', 'Versioned models and reproducible data', 'Tree interview set'),
        ('Model serving and batching', 'Throughput, batching and autoscaling', 'Batch inference and resource limits', 'Graph interview set'),
        ('Monitoring drift and performance', 'Service-level objectives', 'Quality and latency dashboards', 'Heap and interval interview set'),
        ('Canary tests and model rollback', 'Disaster recovery', 'Release a new model safely', 'Dynamic programming interview set'),
        ('Review the complete ML lifecycle', 'Design a monitored ML platform', 'Build and explain the monitored pipeline', 'ML systems and coding mock'),
    )),
    ('Recommendations and distributed systems', 'A recommendation feature with a clear evaluation plan', (
        ('Recommendation baselines', 'Consistency and availability trade-offs', 'Recommendations API and UI', 'Mixed easy and medium coding'),
        ('Candidate generation and ranking', 'Sharding and hot keys', 'Efficient queries and pagination', 'Binary search interview practice'),
        ('Cold start and feedback loops', 'Fan-out and feed systems', 'Record user feedback safely', 'Tree interview practice'),
        ('Offline ranking metrics', 'Event ordering and delivery guarantees', 'Event processing and deduplication', 'Graph interview practice'),
        ('Online experiments and guardrails', 'Experimentation infrastructure', 'Feature flags and experiment assignment', 'Dynamic programming interview practice'),
        ('Fairness, privacy and responsible data use', 'Data retention and deletion', 'Privacy controls and deletion workflows', 'Timed mixed coding'),
        ('Explain a recommendation experiment', 'Design a recommendation system', 'Demo and evaluate the recommendation feature', 'Recommendation and coding mock'),
    )),
    ('Capstone: an AI product end to end', 'An interview-ready AI product with architecture and evaluation', (
        ('Define a measurable AI product goal', 'Gather requirements and constraints', 'Plan the capstone and user flow', 'Select patterns from problem statements'),
        ('Choose a baseline and evaluation set', 'Design APIs and data models', 'Build the core frontend and API', 'Explain code before writing it'),
        ('Implement the model or retrieval layer', 'Estimate scale and identify bottlenecks', 'Connect the AI capability', 'Test boundary and error cases'),
        ('Evaluate failures and improve the baseline', 'Design failure recovery', 'Add tests, permissions and validation', 'Compare time and space trade-offs'),
        ('Measure quality, cost and latency', 'Add monitoring and deployment design', 'Deploy and measure the capstone', 'Timed pair of coding problems'),
        ('Document limitations and next experiments', 'Write architecture decisions', 'Write the README, demo and setup guide', 'Review the weakest coding pattern'),
        ('Explain your capstone decisions', 'Present and critique the architecture', 'Record a complete project walkthrough', 'Capstone and coding mock'),
    )),
    ('Interview practice and focused revision', 'A polished portfolio and a record of mock feedback', (
        ('ML fundamentals interview', 'Design a URL shortener', 'Explain frontend state and accessibility', 'Arrays, strings and maps mock'),
        ('Data and model evaluation interview', 'Design a notification service', 'Explain APIs, authentication and databases', 'Trees and recursion mock'),
        ('Deep learning interview', 'Design a file storage service', 'Debug a slow full-stack feature', 'Graphs and shortest paths mock'),
        ('LLM and RAG interview', 'Design a document assistant', 'Explain testing and delivery decisions', 'Dynamic programming mock'),
        ('ML system design interview', 'Design a recommendation feed', 'Review the capstone code and architecture', 'Timed mixed coding mock'),
        ('Agent reliability interview', 'Design a background job platform', 'Prepare clear project and teamwork stories', 'Repeat mistakes with new examples'),
        ('Review weak concepts from mocks', 'Review weak design decisions', 'Polish the portfolio and project walkthrough', 'Full technical interview rehearsal'),
    )),
    ('Final review and interview readiness', 'A completed review checklist and a practical next-step plan', (
        ('Explain ML foundations without jargon', 'Review requirements and trade-offs', 'Review language, browser and API basics', 'Review your coding mistake log'),
        ('Explain LLMs, RAG and agents clearly', 'Review reliability and scaling', 'Review databases, security and testing', 'One timed coding interview'),
        ('Defend your model evaluation choices', 'One timed system-design interview', 'Debug and explain a full-stack change', 'Review and redo the missed problem'),
        ('One timed AI/ML interview', 'Review feedback from the design mock', 'Present the capstone in five minutes', 'One mixed coding interview'),
        ('Revisit the weakest AI/ML topic', 'Revisit the weakest design topic', 'Check portfolio links and project setup', 'Revisit the weakest DSA pattern'),
        ('Final AI/ML mock and reflection', 'Final architecture walkthrough', 'Final project demo and interview plan', 'Final coding mock and wrap-up'),
    )),
)

_READINGS = (
    ('01-ml-fundamentals', '01-fundamentals', '01-nodejs-express'),
    ('01-ml-fundamentals', '02-storage-and-databases', '02-mongodb'),
    ('01-ml-fundamentals', '05-scalability-patterns', '04-auth-and-api-security'),
    ('01-ml-fundamentals', '03-caching-and-queues', '05-fullstack-project-architecture'),
    ('02-deep-learning', '06-observability-and-reliability', '06-docker-cicd'),
    ('03-transformers-and-llms', '05-scalability-patterns', '03-react-advanced'),
    ('05-rag', '02-storage-and-databases', '05-fullstack-project-architecture'),
    ('06-agents-and-tool-use', '06-observability-and-reliability', '04-auth-and-api-security'),
    ('08-fine-tuning-and-llmops', '04-distributed-systems-advanced', '07-kubernetes'),
    ('09-ml-system-design', '04-distributed-systems-advanced', '08-production-operations'),
    ('07-evaluation-and-harness', '07-case-studies', '05-fullstack-project-architecture'),
    ('10-interview-questions', '08-interview-framework-and-questions', '09-interview-questions'),
    ('10-interview-questions', '08-interview-framework-and-questions', '09-interview-questions'),
)

_INTRODUCTIONS = (
    ('A machine-learning model learns a pattern from examples. An application makes that model useful by accepting input, asking for a prediction and showing the result.',
     'A study tracker receives the minutes you studied, stores them, and shows your weekly total. A simple model could predict tomorrow\'s study time from earlier days.'),
    ('Good systems start with reliable data. A missing value, a duplicate row or a slow query can make an otherwise correct application give the wrong result.',
     'If two copies of the same study session enter a report, the total doubles. Validate each entry and give it an ID before counting it.'),
    ('A baseline is a simple solution you can measure. Improve it only when a more complex model solves the problem better on data it has not already seen.',
     'For a spam filter, compare a simple word rule with a learned classifier. Check missed spam and real messages incorrectly blocked; accuracy alone can hide these mistakes.'),
    ('Some work takes longer than a user should wait. A queue lets the application accept a job now, process it later and show whether it succeeded.',
     'Uploading a dataset returns a job ID immediately. A worker cleans the data and runs predictions while the page asks for the job\'s status.'),
    ('A neural network combines small calculations into a prediction. Training adjusts their numbers to reduce mistakes; deployment makes the trained model usable by an application.',
     'A digit recognizer starts with a blurry guess. After many labelled examples, its prediction improves. A saved model and a repeatable build let someone else run the same experiment.'),
    ('A language model predicts tokens, which are pieces of text. Fluent output can still be wrong, so an application must validate what the model returns.',
     'Ask a model for a JSON object containing a title and a date. Check both fields before saving them, and show a clear error if the response is invalid.'),
    ('Retrieval finds relevant information before an answer is written. Giving a language model selected evidence can make its answer easier to check.',
     'A document assistant searches your handbook for the leave policy, gives that paragraph to the model, and shows a citation beside the answer.'),
    ('An agent combines a model with tools and a controlled workflow. The useful question is whether each action is necessary, permitted and recoverable.',
     'An assistant can look up an order automatically, but asks for approval before issuing a refund. It saves each step so a retry does not refund the order twice.'),
    ('An ML system includes the data, model, application and monitoring around them. A useful model needs fresh inputs, measurable quality and a way to recover from mistakes.',
     'A fraud model can perform well in a test and later miss a new kind of fraud. Track real outcomes and keep the previous model ready for rollback.'),
    ('Large services split work across machines. This helps them handle more users, but creates choices about delay, duplicate work and which copy of the data is current.',
     'A recommendation page can show yesterday\'s cached list while a new ranking is calculated. A bank transfer needs stronger guarantees than that list.'),
    ('A capstone joins the course ideas into one small product. A complete, tested feature with clear limits is more useful in an interview than many unfinished features.',
     'Build a document assistant with sign-in, uploads, cited answers, an evaluation set and a deployed demo. Explain one mistake it still makes and how you measured it.'),
    ('An interview tests how you reason as well as what you remember. Explain assumptions, compare choices, work through an example and check your answer.',
     'Before coding a duplicate finder, ask whether order matters and whether values fit in memory. Compare a set with sorting, then test empty input and repeated values.'),
    ('The final review uses evidence from your practice. Revisit the ideas you could not explain or apply, then repeat a timed interview with a new example.',
     'If you missed a graph problem because you marked nodes too late, write down the error, solve a related problem and explain why the corrected traversal terminates.'),
)


# One practical reason for each daily topic. These are learning goals, not
# claims about any company's questions or a promise of employment.
_JOB_RELEVANCE = (
    ('Choose whether a prediction feature needs learning or a clear rule before spending time building it.', 'Follow a failing screen action through the network and server instead of guessing which box is broken.', 'Keep calculations separate from HTTP so the same behavior can be tested without a browser.'),
    ('Choose inputs that will exist when a real prediction is requested, and define the answer you will measure.', 'Write a request contract that works for browsers, phones and other services.', 'Build a page people can use with a keyboard, with labels that explain each action.'),
    ('Keep model training out of the request path so users do not wait for a new training run.', 'Give clients reliable success and failure meanings so they can recover correctly.', 'Make user actions change explicit state rather than relying on what happens to be on screen.'),
    ('Check whether a simple rule already solves the product problem before adding model complexity.', 'Turn a slow-service complaint into separate response-time, traffic and availability measurements.', 'Handle network failures and invalid response data without showing a false success.'),
    ('Use unseen examples to estimate how the model might behave after release.', 'Choose what must survive a process restart and where it is stored.', 'Store records with stable keys and retrieve the exact rows a feature needs.'),
    ('Recognize an impressive test score that depends on future information and would fail in production.', "Make requests safe to route between server instances without losing a user's work.", 'Save a change through the browser, API and database and show only confirmed results.'),
    ('Explain the data, baseline, errors and limits behind a model choice in a technical interview.', 'Explain one working feature from the first request to the saved record and response.', 'Demonstrate a small working product, including a failed request and recovery.'),
    ('Check feature order and array shapes before a model calculation silently uses the wrong inputs.', 'Estimate traffic and storage from stated assumptions before selecting infrastructure.', 'Reject malformed input before it changes data or produces misleading calculations.'),
    ('Explain what a probability score does and does not promise to a product team.', 'Choose storage from access patterns and consistency needs rather than fashion.', 'Build useful reports without double-counting joined records or hiding users with no activity.'),
    ('Inspect the spread of errors so a good average does not hide a badly served group.', 'Explain why a query is slow using its access path instead of adding servers first.', 'Check whether an index helps the real query and justify its write and storage cost.'),
    ('Find unit errors, duplicates and missing values before they reach a training pipeline.', 'Prevent a partial update from leaving related records inconsistent.', 'Change stored data safely and explain what happens when a migration fails.'),
    ('Inspect target balance and suspicious patterns before choosing a model or metric.', 'Choose what can be cached and what users should see when it becomes stale.', 'Distinguish loading, empty results and failure so users do not mistake missing data for zero.'),
    ('Fit data-preparation rules using training data and apply exactly the same rules later.', 'Evolve an API without unexpectedly breaking older clients.', 'Test a function in isolation and also test the behavior across the HTTP boundary.'),
    ('Explain which findings are supported by the data and which remain uncertain.', 'Define a dashboard number precisely enough that another engineer can verify it.', 'Deliver a dashboard with trustworthy totals, boundary tests and visible failures.'),
    ('Translate prediction error into a loss that matches the outcome the product needs.', 'Spread requests while deciding how health checks and failed instances affect routing.', 'Choose who owns UI state so components show consistent information.'),
    ('Trace how an update changes model parameters and identify an unstable learning rate.', 'Explain which bottleneck more instances can solve and which requires a larger machine or redesign.', 'Validate a form in both the browser and server and keep useful error messages.'),
    ('Explain why a classifier returns a score and how a threshold becomes a product decision.', 'Choose how an authenticated session expires, is revoked and reaches the server.', 'Store passwords appropriately and separate login failure from a server failure.'),
    ('Choose a metric using the cost of false alarms and missed cases rather than accuracy alone.', 'Enforce what a signed-in user is allowed to read or change.', "Stop a user from accessing another user's data by changing an identifier."),
    ('Detect a model that memorizes training examples and test whether it generalizes.', 'Protect shared resources from one client consuming all available capacity.', 'Return stable pages and validate filters so large result sets remain usable.'),
    ('Compare candidate models without repeatedly tuning against the final test set.', 'Use health checks and logs to distinguish a dead instance from a slow dependency.', 'Expose a versioned prediction through a validated API with measurable failures.'),
    ("Defend whether the model's improvement over a baseline is worth its added complexity.", 'Design a prediction request around latency, model availability and input validation.', 'Show a complete prediction feature with an evaluation result and a failure demo.'),
    ('Explain when combining models reduces instability and what extra serving cost it adds.', 'Move long work out of a request and explain how a user learns its final outcome.', 'Represent queued, running, failed and finished jobs without claiming early success.'),
    ('Compare strong tabular baselines fairly before choosing a more complicated learner.', 'Retry temporary failures without multiplying load during an outage.', 'Cancel obsolete work and show a retry action only when repeating is safe.'),
    ('Set a threshold from rare-event costs and operational capacity, not a default value.', 'Handle duplicate delivery without repeating a payment or another side effect.', 'Make a repeated write return the existing result using a stable request identity.'),
    ('Choose a useful distance and explain why a cluster is not automatically a real business category.', 'Define event ownership and the consequences of delayed or out-of-order messages.', 'Show live job progress while retaining a reliable final state on the server.'),
    ('Reduce feature size without discarding information needed for the prediction task.', 'Choose when results must be immediate and when a scheduled batch is simpler.', 'Import many rows with validation, useful error reports and a clear partial-failure policy.'),
    ('Explain a prediction without pretending an explanation proves causation or correctness.', 'Connect a user-visible failure to logs, metrics and a trace through services.', 'Record enough context to debug failures without putting private data into logs.'),
    ('Compare classical models using measured quality, operational cost and failure behavior.', 'Draw a queue-based ML service and explain retries, capacity and uncertain outcomes.', 'Demonstrate that a queued job survives a worker failure without duplicate effects.'),
    ('Explain how layers and nonlinear functions change what a neural network can represent.', 'Keep testing environments separate from real users and production data.', 'Build the same artifact reliably on another machine instead of depending on your laptop.'),
    ('Trace how an error changes earlier weights and identify a broken gradient path.', 'Release only builds that pass useful checks and can be identified later.', 'Use automated checks to block a broken change before deployment.'),
    ('Make training experiments repeatable and diagnose unstable updates.', 'Separate configuration from code and keep credentials out of artifacts and logs.', 'Reject missing configuration early and load secrets through a controlled boundary.'),
    ('Reduce overfitting and explain the difference between training and inference behavior.', 'Serve large files efficiently while defining cache lifetime and access control.', 'Accept uploads with size and type boundaries and store them away from the web process.'),
    ('Compare learned representations using the task they support instead of a visually pleasing plot.', 'Estimate model memory and concurrency before choosing a serving shape.', 'Check that a deployed process is actually ready to serve requests.'),
    ('Connect a reported result to the exact data, code and settings that produced it.', 'Restore a compatible previous version when a release fails.', 'Observe a new release and roll it back using evidence rather than hope.'),
    ('Defend a neural-network experiment with a baseline, split strategy and reproducible result.', 'Explain model loading, readiness, versioning and failure handling in a deployment.', 'Run a reproducible demonstration with clear setup and an observable prediction path.'),
    ('Explain how token limits affect context, response length and product cost.', 'Deliver partial results while handling disconnection and incomplete work.', 'Render streamed text without confusing a partial answer with a finished one.'),
    ('Trace how attention combines relevant inputs rather than describing it as magic.', 'Allocate a response-time budget and measure which stage consumes it.', 'Cancel an older request and stop its late response replacing the latest result.'),
    ("Explain a transformer's main blocks and the resources that grow with sequence length.", 'Bound concurrent work so one slow dependency does not exhaust the service.', 'Choose limits for connections and tasks and explain what happens when they fill up.'),
    ('Choose prompting, retrieval or tuning from the kind of behavior and knowledge needed.', 'Place responsibilities at boundaries that keep services understandable and independently testable.', 'Use types to help callers while still validating untrusted runtime data.'),
    ('Define the output contract and validate it before AI output changes application state.', 'Reject bad data at each trust boundary rather than relying on a previous caller.', 'Handle invalid AI output with useful errors and bounded recovery.'),
    ('Distinguish a plausible answer from an answer supported by evidence.', 'Choose a degraded behavior that remains honest when a dependency fails.', 'Offer a useful fallback while clearly showing that the normal path is unavailable.'),
    ('Measure an AI feature with realistic tasks, failure cases and user-facing outcomes.', 'Design an assistant whose context, response path and limits can be explained.', 'Demonstrate streaming, cancellation, evaluation and error handling together.'),
    ('Use retrieval when an answer needs current or private reference material.', 'Define searchable content, access rules, freshness and expected query behavior.', 'Parse documents into a predictable representation and report unsupported files.'),
    ('Choose chunk boundaries that preserve meaning and can be traced to the source.', 'Keep an index consistent with the source records users are allowed to search.', 'Store source identifiers and positions so retrieved text can be explained and cited.'),
    ('Understand what similarity ranks and why the nearest vector may still be irrelevant.', 'Choose a retrieval layout from index size, filtering and latency needs.', 'Return ranked evidence through an endpoint with explicit metadata and empty-result handling.'),
    ('Combine exact-term and semantic retrieval when either alone misses useful evidence.', 'Scale reads without promising that every replica has the newest write.', 'Keep search state, filters and pagination consistent as requests finish asynchronously.'),
    ('Select evidence under a context budget and explain why reranking helps or fails.', 'Cache only results whose query, permissions and freshness rules match.', 'Attach citations to actual supporting passages rather than decorative links.'),
    ('Separate retrieval failure from answer-generation failure in an evaluation.', 'Update or remove indexed content without silently serving obsolete evidence.', 'Run a repeatable evaluation that names the cases and records the results.'),
    ('Defend chunking, retrieval, ranking and answer-quality choices using measurements.', 'Design a document assistant with access controls, citations and freshness handling.', 'Show which questions work, which fail and how the evaluation revealed the difference.'),
    ('Decide whether a bounded workflow is enough before allowing model-directed actions.', "Represent state transitions so a crash does not leave an operation's outcome ambiguous.", 'Make every workflow transition explicit and reject invalid transitions.'),
    ('Define tool inputs and results as contracts rather than trusting model-generated arguments.', 'Choose whether a caller should wait or receive a durable job identifier.', 'Validate and authorize tool arguments before executing their effect.'),
    ('Limit steps and time so a confused agent does not loop indefinitely.', 'Stop repeated calls to an unhealthy dependency and define how recovery is tested.', 'Cancel work across layers and preserve a clear final status.'),
    ('Choose what to remember, what to retrieve and how stale state is corrected.', 'Resume work from a durable checkpoint without repeating an already completed effect.', 'Persist the minimum state needed to continue and reconcile uncertain outcomes.'),
    ('Treat retrieved pages and documents as data, not instructions to grant permissions.', 'Draw trust boundaries and decide which component can approve each action.', 'Require an explicit, scoped approval before an action that changes external state.'),
    ('Use traces and failure examples to improve an agent rather than judging a single attractive demo.', 'Keep evidence of who requested an action and what happened to it.', 'Make a failed tool call understandable and reproducible without leaking secrets.'),
    ('Compare an agent with a simpler workflow using quality, reliability and maintenance cost.', 'Explain how a workflow recovers when a tool succeeds but its response is lost.', 'Demonstrate a bounded assistant with approved actions, recovery and regression cases.'),
    ('Detect differences between training features and the values used in real predictions.', 'Separate offline computation from the latency-sensitive online request path.', 'Validate data contracts before a new dataset enters training.'),
    ('Check whether a feature is available and fresh enough at prediction time.', 'Apply backpressure so producers cannot overwhelm downstream processing.', 'Process batches and events with explicit limits, error handling and progress.'),
    ('Connect each model version to compatible features, data and evaluation evidence.', 'Choose partition keys from access patterns and avoid concentrating traffic.', 'Reproduce a model result using named versions instead of mutable latest files.'),
    ('Improve serving efficiency while measuring the delay introduced by batching.', 'Scale from measured bottlenecks rather than assuming more workers always help.', 'Bound a batch by size, wait time and memory and reject oversized work clearly.'),
    ('Investigate changed inputs and delayed outcomes without treating drift as proof of lower quality.', 'Define an SLO using a meaningful user-facing success measure.', 'Show quality and latency measurements with units, time windows and data freshness.'),
    ('Release a new model gradually and decide when evidence requires rollback.', 'Restore the service and its compatible data after a failure.', 'Use a small rollout, health checks and a tested rollback procedure.'),
    ('Explain the whole lifecycle from data ingestion to production evaluation and recovery.', 'Design an ML platform whose versions, dependencies and monitoring fit together.', 'Demonstrate compatible feature and model versions plus a controlled failure recovery.'),
    ('Start recommendations with a measurable simple policy before adding a ranking model.', 'Choose consistency behavior from what users can tolerate during failures.', 'Serve recommendations with useful empty, loading and error states.'),
    ('Separate finding candidates from ranking them to control latency and relevance.', 'Avoid hot partitions by understanding how request popularity is distributed.', 'Measure query cost and return stable pages under large result sets.'),
    ('Help new users or items while detecting feedback loops created by earlier recommendations.', 'Choose how feeds are assembled and where fan-out cost is paid.', 'Record feedback with a stable identity and prevent accidental duplicate events.'),
    ('Choose ranking metrics that match what users see in the first few results.', 'Define ordering and deduplication rules for events that may be redelivered.', 'Process a repeated event once and handle late events deliberately.'),
    ('Run an experiment with stable assignment and guardrails against harmful side effects.', 'Build experiment infrastructure that separates assignment from measurement.', 'Keep a user in the same experiment group and make rollback straightforward.'),
    ('Limit data use to what the feature needs and evaluate who may be harmed.', 'Make retention and deletion reach replicas, indexes and downstream copies.', 'Implement deletion as a verifiable workflow rather than hiding a button.'),
    ('Defend a recommendation experiment using both offline results and product guardrails.', 'Explain candidate retrieval, ranking, freshness and failure behavior together.', 'Demonstrate the recommendation path and show the evidence behind one design change.'),
    ('Define the user decision and measurable outcome before selecting an AI technique.', 'Turn a vague request into requirements, constraints and explicit assumptions.', 'Plan a small end-to-end user path with a testable definition of success.'),
    ('Choose an honest baseline and evaluation set before trying to improve a capstone.', 'Make data ownership and API behavior clear before drawing more services.', 'Build one complete user action from the page through the API.'),
    ('Integrate a model or retrieval component while keeping its inputs and outputs testable.', 'Estimate scale and locate the likely bottleneck in the critical path.', 'Connect the AI component through a validated contract with useful failure behavior.'),
    ('Choose an improvement from failure evidence rather than adding features blindly.', 'Recover from a failed dependency or uncertain write without corrupting state.', 'Test permission boundaries, invalid inputs and network failures in the actual product.'),
    ('Balance measured quality against latency and resource consumption.', 'Monitor the critical user path and define a deployment and rollback strategy.', 'Deploy the same build you tested and record a reproducible measurement.'),
    ('Document known limitations so another engineer can use the system responsibly.', 'Record why a design was chosen and what evidence would change it.', 'Make the project runnable by someone who has never seen your machine.'),
    ('Explain how evidence changed a capstone decision and what you would test next.', 'Defend a diagram by tracing real data and challenging its assumptions.', 'Tell a coherent project story backed by a working demonstration.'),
    ('Answer a foundation question with a clear definition, example and limit.', 'Design a URL shortener while explaining key generation, redirects and hot reads.', 'Explain state ownership and accessibility through a real UI interaction.'),
    ('Defend a split strategy and metric when the interviewer changes the data conditions.', 'Design notifications with retry, deduplication and delivery-status semantics.', 'Trace authentication, authorization and data access in one API operation.'),
    ('Explain neural-network training behavior and diagnose a concrete failure.', 'Design file storage with upload boundaries, metadata and durable object storage.', 'Find a performance problem using evidence and verify the repair.'),
    ('Compare retrieval and tuning while identifying unsupported answers.', 'Design a document assistant whose retrieval and answer paths are evaluated separately.', 'Explain which tests protect a release and how rollback works.'),
    ('Connect model choices to data, serving and monitoring constraints under time pressure.', 'Design a recommendation feed with freshness, fan-out and ranking trade-offs.', 'Review code against its stated architecture and identify one material risk.'),
    ('Explain how a bounded agent recovers from tool failures and uncertain outcomes.', 'Design background work with durable jobs, limited retries and useful status.', 'Describe your own contribution to a team decision using concrete evidence.'),
    ('Repair a weak answer by working a different example and checking the same concept.', 'Revisit an assumption that made a previous design fail.', 'Make the project walkthrough clear enough that a reviewer can verify your claims.'),
    ('Explain a model concept in ordinary words while retaining its technical meaning.', 'State requirements and trade-offs before proposing components.', 'Show that you understand language and browser behavior underneath a framework.'),
    ('Explain how language models, retrieval and tools fit together without merging their roles.', 'Reason about reliability and scaling from a specific failure or workload.', 'Connect database, security and test decisions to user-visible behavior.'),
    ('Defend evaluation choices and identify what the available evidence cannot prove.', 'Complete a timed design while prioritizing the critical path and major risks.', 'Debug a change, explain the cause and show a regression check.'),
    ('Practice concise AI reasoning with a new scenario and a clear stopping point.', 'Use mock feedback to change an actual design decision.', 'Present the problem, implementation, evidence and limits within five minutes.'),
    ('Use a new example to check whether a previously weak concept is now understood.', 'Challenge the weakest assumption with a concrete failure scenario.', 'Check that a reviewer can open the links and run the documented setup.'),
    ('Finish with evidence of what you can explain and build, plus an honest improvement plan.', 'Walk through a complete architecture and defend one alternative.', 'Demonstrate the finished user path and prepare the next practice targets.'),
)


def course_info():
    from .interview_practice import bank_rows
    return {
        'id': COURSE_ID, 'version': COURSE_VERSION, 'title': COURSE_TITLE,
        'description': 'For developers with around three years of experience: technical explanations, system flows, implementation cases and interview practice in simple English.',
        'shared': True, 'total_days': TOTAL_DAYS, 'daily_minutes': 240,
        'audience': 'Working developers with around 3 years of experience',
        'engineering_notebooks': 13,
        'interview_questions': len(bank_rows()), 'project_assessments': 13,
        'session_label': '3–4 hours, at your own pace',
        'study_note': 'Allow around 3–4 hours for detailed reading and practice. This is a guide, not a limit. Split a lesson across sessions when needed; projects and mocks can take longer.',
        'subjects': list(SUBJECTS),
        'phases': [{'title': title, 'start_day': start, 'end_day': end} for title, start, end in PHASES],
        'daily_session': [{'key': key, 'title': title, 'minutes': minutes} for key, title, minutes in DAILY_SESSION],
    }


def day_spec(day):
    if type(day) is not int or not 1 <= day <= TOTAL_DAYS:
        raise ValueError('Choose a course day from 1 to 90.')
    week, offset = (day - 1) // 7, (day - 1) % 7
    title, project, rows = _WEEKS[week]
    topics = dict(zip(('ai_ml', 'system_design', 'full_stack', 'dsa'), rows[offset]))
    review = offset == len(rows) - 1
    reading = _READINGS[week]
    explanation, example = _INTRODUCTIONS[week]
    job_relevance = dict(zip(('ai_ml', 'system_design', 'full_stack'), _JOB_RELEVANCE[day - 1]))
    job_relevance['dsa'] = 'Explain a correct algorithm, test its boundaries and justify its time and memory costs in a coding interview.'
    from . import interview_ai_interviews, interview_system_interviews, interview_fullstack_interviews
    guides = {key: module.lesson(day) for key, module in zip(('ai_ml', 'system_design', 'full_stack'),
        (interview_ai_interviews, interview_system_interviews, interview_fullstack_interviews))}
    if day == 1:
        guides['ai_ml'].update(drill='Compare a 25-minute baseline with predictions of 22, 28 and 35 minutes for actual study times of 20, 30 and 40. Calculate both mean absolute errors and explain what the small sample cannot prove.', checks=['I can separate a rule, a learned model and a measured outcome.', 'I can calculate errors of 8.33 and 3 minutes and explain why three examples do not prove production quality.'])
        guides['system_design'].update(drill='Trace POST /api/study-summary with minutes [20, 30, 40]. Define success, invalid input and a lost response. Explain why this calculation can be repeated but a saved study session needs separate duplicate handling.', checks=['I can trace the request through validation, calculation and response.', 'I can distinguish a successful calculation from a durable saved record.'])
        guides['full_stack'].update(drill='Implement summarise_sessions and a request handler. Return count 3, total_minutes 90 and mean_minutes 30 for [20, 30, 40]. Reject invalid types and values, define the empty case, and run the supplied checks.', checks=['I can test the calculation without a web server.', 'I can reject booleans, text, negative and non-finite values and explain each validation check.'])
    path = []
    for key, label, _ in DAILY_SESSION[:3]:
        entry = guides[key]
        checks = [check.removeprefix('I can ').removeprefix('I ') for check in entry['checks']]
        path.append({'key': key, 'title': label, 'topic': topics[key],
                     'outcome': checks[0][0].upper() + checks[0][1:], 'job_use': job_relevance[key],
                     'task': entry['drill'], 'checks': entry['checks'][:]})
    path.append({'key': 'dsa', 'title': 'DSA practice', 'topic': topics['dsa'],
                 'outcome': 'Trace and solve ' + topics['dsa'].lower() + '.', 'job_use': job_relevance['dsa'],
                 'task': 'Work one example by hand, write a correct solution, then test a boundary case and explain its cost.',
                 'checks': ['Explain why the algorithm is correct.', 'Test a normal case and an allowed boundary case.',
                            'State time and extra-memory costs using the input size.']})
    if day == 1:
        path[-1].update(outcome='Scan study-session minutes once, keep a running total and prove why it is correct.', task='Trace [20, 30, 40] by hand. Implement a one-pass summary with an empty-input rule, then explain why sorting is unnecessary.', checks=['After each step, the total equals the sum of the values already visited.', 'The scan takes O(n) time and O(1) extra memory, excluding the input and output.', 'Empty input has count 0 and no mean; no division by zero occurs.'])
    return {
        'day': day, 'week': week + 1,
        'title': ('Review and project: ' if review else '') + topics['ai_ml'],
        **topics, 'practice': project if review else topics['full_stack'],
        'job_relevance': job_relevance, 'learning_path': path,
        'project': project, 'deliverable': ('A tested study-session summary, an API contract, an array trace and a baseline comparison.' if day == 1 else guides['full_stack']['drill']),
        'session_label': '3–4 hours, at your own pace',
        'review': review, 'prerequisites': [day - 1] if day > 1 else [],
        'explanation': explanation, 'example': example,
        'reading_paths': {'ai_ml': '04-ml-genai-agents/' + reading[0] + '.md',
                          'system_design': '01-system-design/' + reading[1] + '.md',
                          'full_stack': '03-fullstack-mern-kubernetes/' + reading[2] + '.md'},
        'topics': [{'key': key, 'title': label, 'topic': topics[key]} for key, label, _ in DAILY_SESSION[:4]],
        'objectives': [item['outcome'] for item in path],
    }


def week_spec(week):
    if type(week) is not int or not 1 <= week <= len(_WEEKS):
        raise ValueError('Choose a course week from 1 to 13.')
    first = (week - 1) * 7 + 1
    title, project, rows = _WEEKS[week - 1]
    days = [day_spec(day) for day in range(first, first + len(rows))]
    return {'number': week, 'title': title, 'project': project,
            'start_day': first, 'end_day': first + len(rows) - 1,
            'milestones': [{'day': item['day'], 'topic': item['full_stack'],
                            'output': item['deliverable'], 'checks': item['learning_path'][2]['checks'][:]} for item in days],
            'days': days}


def syllabus():
    return [week_spec(week) for week in range(1, len(_WEEKS) + 1)]


def is_current(metadata):
    return (isinstance(metadata, dict) and metadata.get('course_id') == COURSE_ID
            and type(metadata.get('course_version')) is int and metadata['course_version'] == COURSE_VERSION)


def state_for(data):
    """Read course progress without importing or changing the earlier plan."""
    state = data.get('interview_course')
    if state is None:
        return {'course_id': COURSE_ID, 'course_version': COURSE_VERSION, 'done': [], 'marked': {}}
    if (not isinstance(state, dict) or not is_current(state)
            or not isinstance(state.get('done', []), list)
            or any(type(day) is not int or not 1 <= day <= TOTAL_DAYS for day in state.get('done', []))
            or not isinstance(state.get('marked', {}), dict)
            or any(not isinstance(date, str) or type(day) is not int or not 1 <= day <= TOTAL_DAYS
                   for date, day in state.get('marked', {}).items())):
        raise ValueError('Saved interview-course progress is invalid. It has not been reset.')
    try:
        dates = list(state.get('marked', {})) + ([state['start']] if 'start' in state else [])
        if any(not isinstance(value, str) or date.fromisoformat(value).isoformat() != value for value in dates):
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError('Saved interview-course dates are invalid. They have not been reset.') from None
    return state


def ensure_course_state(data):
    """Create only the course namespace; call within the caller's transaction."""
    state = state_for(data)
    data.setdefault('interview_course', state)
    return state


def completed_days(data):
    done = set(state_for(data).get('done', []))
    for identifier, entry in data.get('documents', {}).items():
        match = re.fullmatch(r'interview/day-(\d{1,2})', identifier)
        if match and 1 <= int(match[1]) <= TOTAL_DAYS and entry.get('done'):
            done.add(int(match[1]))
    return sorted(done)


def next_day(data):
    done = set(completed_days(data))
    return next((day for day in range(1, TOTAL_DAYS + 1) if day not in done), None)


def record_completion(data, day, done, at=None):
    """Record a shared-course completion without changing legacy plan progress."""
    from . import learning_memory
    spec = day_spec(day)
    if type(done) is not bool:
        raise ValueError('Course completion must be true or false.')
    if (day in completed_days(data)) == done:
        return
    state = ensure_course_state(data)
    at = at or learning_memory.stamp()
    data.setdefault('documents', {})
    data.setdefault('history', [])
    learning_memory.record(data, 'research', 'interview/day-%d' % day,
                           'Day %d: %s' % (day, spec['title']), done, at=at)
    days = set(state.get('done', []))
    days.add(day) if done else days.discard(day)
    state['done'] = sorted(days)
    state.setdefault('start', at[:10])
    marked = state.setdefault('marked', {})
    if done:
        marked[at[:10]] = day
        # Today's interview questions come back for recall tomorrow, then on a spaced schedule.
        from . import interview_practice, interview_review
        interview_review.seed(data, interview_practice.day_question_ids(day), date.fromisoformat(at[:10]))
    else:
        state['marked'] = {date: number for date, number in marked.items() if number != day}
