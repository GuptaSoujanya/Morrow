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
TEACHING_VERSION = 4
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


def course_info():
    return {
        'id': COURSE_ID, 'version': COURSE_VERSION, 'title': COURSE_TITLE,
        'description': 'For developers with around three years of experience: technical explanations, system flows, implementation cases and interview practice in simple English.',
        'shared': True, 'total_days': TOTAL_DAYS, 'daily_minutes': 240,
        'audience': 'Working developers with around 3 years of experience',
        'engineering_notebooks': 13,
        'interview_questions': 540, 'project_assessments': 13,
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
    return {
        'day': day, 'week': week + 1,
        'title': ('Review and project: ' if review else '') + topics['ai_ml'],
        **topics, 'practice': project if review else topics['full_stack'],
        'review': review, 'prerequisites': [day - 1] if day > 1 else [],
        'explanation': explanation, 'example': example,
        'reading_paths': {'ai_ml': '04-ml-genai-agents/' + reading[0] + '.md',
                          'system_design': '01-system-design/' + reading[1] + '.md',
                          'full_stack': '03-fullstack-mern-kubernetes/' + reading[2] + '.md'},
        'topics': [{'key': key, 'title': label, 'topic': topics[key]} for key, label, _ in DAILY_SESSION[:4]],
        'objectives': ['Explain ' + topics['ai_ml'].lower() + ' with an example.',
                       'Describe ' + topics['system_design'].lower() + ' and one trade-off.',
                       'Practise ' + topics['full_stack'].lower() + '.',
                       'Solve and explain ' + topics['dsa'].lower() + ' problems.'],
    }


def week_spec(week):
    if type(week) is not int or not 1 <= week <= len(_WEEKS):
        raise ValueError('Choose a course week from 1 to 13.')
    first = (week - 1) * 7 + 1
    title, project, rows = _WEEKS[week - 1]
    return {'number': week, 'title': title, 'project': project,
            'start_day': first, 'end_day': first + len(rows) - 1,
            'days': [day_spec(day) for day in range(first, first + len(rows))]}


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
