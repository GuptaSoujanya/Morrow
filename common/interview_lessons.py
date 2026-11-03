"""Public reading material for the shared interview course.

The bundled course works without a resume, an AI service, or private workspace
files. Local pipeline lessons may enrich it; account readers use only lesson().
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from . import interview_course, interview_ai_basics, interview_system_basics, interview_fullstack_basics, interview_practice, interview_engineering


_TRACKS = (
    ('system_design', 'System design', '01-system-design'),
    ('ai_ml', 'AI and machine learning', '04-ml-genai-agents'),
    ('full_stack', 'Full-stack development', '03-fullstack-mern-kubernetes'),
)
_WORDS = re.compile(r'[a-z][a-z0-9]{2,}')
_STOP = {'the', 'and', 'for', 'with', 'from', 'how', 'your', 'why', 'into', 'what',
         'design', 'system', 'systems', 'learning', 'day', 'week', 'build', 'using'}

# These aliases connect a syllabus concept to an actual chapter section. They
# are deliberately narrower than matching a generic word such as "data".
_REFERENCE_ALIASES = {
    'system_design': (
        (r'web request|clients?, servers?|request path|request flow', '01-fundamentals', 'Client-Server Model'),
        (r'latency|throughput', '01-fundamentals', 'Latency vs Throughput'),
        (r'load balanc', '01-fundamentals', 'Load Balancers'),
        (r'horizontal|vertical', '01-fundamentals', 'Vertical vs Horizontal Scaling'),
        (r'cdn|content delivery', '01-fundamentals', 'CDN (Content Delivery Network)'),
        (r'sql versus|sql vs|persistent storage', '02-storage-and-databases', 'SQL vs NoSQL'),
        (r'index|query performance', '02-storage-and-databases', 'Indexing'),
        (r'transaction|isolation', '02-storage-and-databases', 'Isolation Levels'),
        (r'partition|shard|hot keys', '02-storage-and-databases', 'Sharding and Partitioning'),
        (r'replication|read scaling', '02-storage-and-databases', 'Replication'),
        (r'consistency and availability', '02-storage-and-databases', 'CAP Theorem and PACELC'),
        (r'cach', '03-caching-and-queues', 'Caching Strategies'),
        (r'queue|background job', '03-caching-and-queues', 'Message Queues'),
        (r'backpressure|streaming ingestion', '03-caching-and-queues', 'Backpressure'),
        (r'delivery guarantee', '03-caching-and-queues', 'Delivery Semantics'),
        (r'idempotenc|duplicate', '04-distributed-systems-advanced', 'Idempotency'),
        (r'event ordering', '04-distributed-systems-advanced', 'Clocks and Ordering'),
        (r'event.driven', '05-scalability-patterns', 'Event-Driven Architecture'),
        (r'rate limit|quota', '05-scalability-patterns', 'Rate Limiting Algorithms'),
        (r'circuit breaker|timeouts?', '05-scalability-patterns', 'Circuit Breakers'),
        (r'service boundar', '05-scalability-patterns', 'Microservices vs Monolith'),
        (r'logging|observability|monitoring|traceability|audit trails', '06-observability-and-reliability', 'Monitoring, Logging, Tracing'),
        (r'capacity|cost estimates|useful estimates|estimate scale', '06-observability-and-reliability', 'Capacity Estimation'),
        (r'service.level objective', '06-observability-and-reliability', 'SLI, SLO, SLA'),
        (r'url shortener', '07-case-studies', 'URL Shortener'),
        (r'notification', '07-case-studies', 'Notification System'),
        (r'feed|fan.out', '07-case-studies', 'News Feed'),
        (r'gather requirements|requirements and trade.offs|architecture walkthrough', '08-interview-framework-and-questions', 'The 4-Step Framework'),
    ),
    'ai_ml': (
        (r'what is machine learning|first model', '01-ml-fundamentals', 'Supervised vs. Unsupervised Learning'),
        (r'bias|variance|overfitting', '01-ml-fundamentals', 'Bias-Variance Tradeoff'),
        (r'training and test|cross.validation|data leakage', '01-ml-fundamentals', 'Train/Validation/Test Split'),
        (r'precision|recall|confusion|classification metrics', '01-ml-fundamentals', 'Evaluation Metrics'),
        (r'feature', '01-ml-fundamentals', 'Feature Engineering'),
        (r'linear regression|logistic regression|decision tree|random forest|ensemble|boosting|clustering', '01-ml-fundamentals', 'Classic Algorithms'),
        (r'neuron|activation|neural network', '02-deep-learning', 'What a Neural Network Actually Is'),
        (r'backpropagation', '02-deep-learning', 'Backpropagation'),
        (r'gradient descent|optimizer', '02-deep-learning', 'Optimizers'),
        (r'regularization|dropout', '02-deep-learning', 'Overfitting Remedies'),
        (r'embedding|representation', '02-deep-learning', 'Embeddings'),
        (r'token', '03-transformers-and-llms', 'Tokenization'),
        (r'attention', '03-transformers-and-llms', 'Self-Attention'),
        (r'transformer', '03-transformers-and-llms', 'The Transformer Block'),
        (r'pretraining|fine.tuning', '03-transformers-and-llms', 'Training Pipeline'),
        (r'structured output', '04-prompt-engineering', 'Structured Outputs'),
        (r'tool calling', '04-prompt-engineering', 'Function Calling'),
        (r'prompt injection|untrusted', '04-prompt-engineering', 'Prompt Injection'),
        (r'retrieval.augmented|rag trade.off', '05-rag', 'Why RAG Exists'),
        (r'chunking|hybrid retrieval|reranking|context selection', '05-rag', 'The Full RAG Pipeline'),
        (r'retrieval and answer quality|retrieval evaluation', '05-rag', 'RAG Evaluation'),
        (r'when to use an agent|agent.*simpler workflows', '06-agents-and-tool-use', 'The ReAct Loop'),
        (r'planning|bounded execution', '06-agents-and-tool-use', 'Planning'),
        (r'memory versus', '06-agents-and-tool-use', 'Memory'),
        (r'agent evaluation|agent reliability|failure analysis', '06-agents-and-tool-use', 'Failure Modes and Guardrails'),
        (r'hallucination|grounded answer', '07-evaluation-and-harness', 'Hallucination Measurement'),
        (r'online experiment', '07-evaluation-and-harness', 'A/B Testing'),
        (r'evaluation set|evaluation dataset', '07-evaluation-and-harness', 'Golden Datasets'),
        (r'model serving|batching', '08-fine-tuning-and-llmops', 'Serving Fine-Tuned and Base Models'),
        (r'ml lifecycle|model registry|model version', '08-fine-tuning-and-llmops', 'LLMOps Lifecycle'),
        (r'recommendation|candidate generation|ranking|cold start', '09-ml-system-design', 'Recommendation System'),
        (r'ml fundamentals interview', '10-interview-questions', 'Section A'),
        (r'deep learning interview', '10-interview-questions', 'Section B'),
        (r'llm.*interview', '10-interview-questions', 'Section C'),
        (r'ml system design interview', '10-interview-questions', 'Section E'),
    ),
    'full_stack': (
        (r'input validation|validate|validation', '05-fullstack-project-architecture', 'Request Validation'),
        (r'components|props|hooks', '03-react-advanced', 'Hooks Deep Dive'),
        (r'frontend state|state management', '03-react-advanced', 'State Management'),
        (r'test.*frontend|react.*test', '03-react-advanced', 'Testing with React Testing Library'),
        (r'authentication|sign.in|password', '04-auth-and-api-security', 'JWT vs Sessions'),
        (r'authorization|protected route|permission', '04-auth-and-api-security', 'RBAC'),
        (r'indexes|query plan', '02-mongodb', 'Indexes'),
        (r'transaction', '02-mongodb', 'Transactions'),
        (r'migrations', '02-mongodb', 'Mongoose Patterns'),
        (r'pagination|filtering|sorting|api client', '01-nodejs-express', 'REST API Design Principles'),
        (r'error|fallback', '01-nodejs-express', 'Centralized Error Handling'),
        (r'environment|configuration|secrets', '05-fullstack-project-architecture', 'Environment Configuration'),
        (r'logs|logging|error reporting', '05-fullstack-project-architecture', 'Logging'),
        (r'containers|reproducible build', '06-docker-cicd', 'Dockerfile Best Practices'),
        (r'continuous integration|test gates', '06-docker-cicd', 'CI/CD Pipeline'),
        (r'health check', '07-kubernetes', 'Probes'),
        (r'resource limit', '07-kubernetes', 'Resource Requests/Limits'),
        (r'rollback|roll back|release|deploy', '08-production-operations', 'Zero-Downtime Deploys'),
        (r'quality and latency dashboard|monitor', '08-production-operations', 'Monitoring with Prometheus and Grafana'),
        (r'debug.*pod|debug.*production', '08-production-operations', 'Debugging Pods'),
    ),
}

_FOUNDATION_PRIMERS = {
    ('ai_ml', 'Data, labels and features'): (
        'Data is the collection of examples you start with. A feature is an input you give a model. A label is the answer used to teach or check it.',
        'For house prices, floor area is a feature and the sale price is a label. Keep the label out of the inputs: otherwise the model can copy the answer instead of learning.'),
    ('ai_ml', 'Training versus using a model'): (
        'Training changes a model using examples. Inference means using the trained model to make a prediction for a new input. These are different jobs.',
        'Training a spam filter uses messages whose spam labels are known. Inference takes one new message and returns a spam score without retraining the whole model.'),
    ('ai_ml', 'A first prediction with a baseline'): (
        'A baseline is a simple prediction rule. Measure it before choosing a complex model so you know whether the extra work improves the result.',
        'If past delivery times are 20, 25 and 30 minutes, a mean baseline predicts 25 minutes. Compare its errors on new deliveries with the errors from a model using distance.'),
    ('ai_ml', 'Vectors and matrices in plain language'): (
        'A vector is an ordered list of numbers. A matrix is a rectangular table of numbers. They let us describe examples and apply the same calculation to many examples.',
        'Describe a house as [area, bedrooms], such as [80, 2]. Three houses make a matrix with three rows and two columns. Keep the column meanings and units the same in every row.'),
    ('ai_ml', 'Probability and uncertainty'): (
        'Probability describes how likely an outcome is under stated assumptions. A model score is an estimate; it is not a promise that one event will happen.',
        'A fair coin has a probability of one half for heads. That does not force every pair of flips to contain one head. Likewise, judge probability predictions across many outcomes.'),
    ('ai_ml', 'Mean, variance and distributions'): (
        'The mean describes a centre. Variance describes how far values spread around that centre. A distribution describes which values occur and how often.',
        'The lists [10, 10, 10] and [0, 10, 20] both have mean 10. The second is more spread out. Reporting only the mean hides that difference.'),
    ('ai_ml', 'Clean missing and messy data'): (
        'Before training, check missing values, duplicates, impossible values and inconsistent units. Decide how to handle each issue and record the rule.',
        'A height column containing 170, 165 and 1.8 probably mixes centimetres and metres. Fix units using source evidence; do not silently treat 1.8 as an extremely short adult.'),
    ('ai_ml', 'Explore a dataset before modelling'): (
        'Exploration means checking what the dataset contains before fitting a model. Inspect a few rows, column types, missing values, ranges and how the target is distributed.',
        'If 990 of 1,000 transactions are legitimate, always predicting legitimate gets 99% accuracy. Counting labels first reveals why that number alone is a weak fraud test.'),
    ('ai_ml', 'Review data quality and uncertainty'): (
        'Data quality asks whether the examples are correct, relevant and consistently recorded. Uncertainty asks how much your conclusion could change with different observations or assumptions.',
        'Suppose a survey has duplicate replies and only ten respondents. Removing duplicates fixes one quality problem, but the small sample still makes the estimate uncertain. Cleaning data does not remove all uncertainty.'),
    ('system_design', 'Deployment environments'): (
        'An environment is a place where an application runs with its own configuration and data. Development is for building, staging is for checking a release, and production serves real users.',
        'Test a new checkout version in staging with test orders and separate credentials. Release the same build to production only after checks pass; never point a test script at the real orders database.'),
    ('system_design', 'Stateful and stateless services'): (
        'A stateful service keeps information from earlier requests in a particular running instance. A stateless request includes, or can retrieve, everything needed to handle it.',
        'If a shopping cart exists only in server A\'s memory, routing the next request to server B loses it. Store the cart in shared durable storage and identify it in each request to avoid that dependency.'),
    ('system_design', 'APIs and status codes'): (
        'An API defines how programs request actions or information. HTTP status codes communicate the broad outcome; the response body supplies details.',
        'A request for an existing lesson can return 200 and its data. A missing lesson can return 404. A user without permission should receive an appropriate access error, not another learner\'s lesson.'),
    ('system_design', 'Authentication versus authorization'): (
        'Authentication checks who is making a request. Authorization checks whether that identity may perform this particular action.',
        'Signing in proves which learner you are. The server must still verify that a requested note belongs to you before returning it. A valid login does not grant access to everyone\'s notes.'),
    ('full_stack', 'Python collections and input validation'): (
        'A list keeps an ordered collection of values. A dictionary looks up a value by a key. Validation checks whether input has the expected type, shape and allowed values before it changes stored data.',
        'For a study session, use {"minutes": 25, "topic": "arrays"}. Check that minutes is a number greater than zero and topic is non-empty. Reject invalid input with a useful message rather than saving it.'),
    ('full_stack', 'SQL joins and grouped reports'): (
        'A join combines rows from tables using a related key. GROUP BY combines rows into groups so an aggregate, such as SUM or COUNT, can produce one result per group.',
        'Join learners.id to sessions.learner_id, then group by learner ID and sum sessions.minutes. Use a LEFT JOIN when learners with no sessions should still appear. Do not group only by name because two learners can share one.'),
    ('full_stack', 'Build a tested data dashboard'): (
        'A data dashboard turns stored records into a readable summary. Define what each number means, validate source records, compute the report on the server, and make loading or errors visible on the page.',
        'For sessions of 20 and 30 minutes, the weekly total should be 50. Test zero sessions, duplicate submissions and a failed request. A chart should not show a saved zero when the request actually failed.'),
}

_PRIMER_REFERENCES = {
    ('system_design', 'Deployment environments'): ('03-fullstack-mern-kubernetes/05-fullstack-project-architecture.md', 'Environment Configuration'),
    ('ai_ml', 'Review data quality and uncertainty'): ('04-ml-genai-agents/01-ml-fundamentals.md', 'Train/Validation/Test Split'),
    ('ai_ml', 'Data, labels and features'): ('04-ml-genai-agents/01-ml-fundamentals.md', 'Feature Engineering'),
    ('ai_ml', 'Training versus using a model'): ('04-ml-genai-agents/08-fine-tuning-and-llmops.md', 'LLMOps Lifecycle'),
    ('ai_ml', 'A first prediction with a baseline'): ('04-ml-genai-agents/01-ml-fundamentals.md', 'Evaluation Metrics'),
    ('full_stack', 'SQL joins and grouped reports'): ('01-system-design/02-storage-and-databases.md', 'SQL vs NoSQL'),
    ('full_stack', 'Build a tested data dashboard'): ('03-fullstack-mern-kubernetes/05-fullstack-project-architecture.md', 'Request Lifecycle'),
}

# The reference library assumes programming experience. These first exercises
# teach the prerequisites before pointing learners at its advanced chapters.
_STARTER_FULLSTACK = {
    1: ('A value is a piece of information, such as a number or some text. A variable gives it a name. '
        'A function is a named set of steps that you can reuse. An API lets another program ask your program to do something.',
        '```python\ndef progress(completed, total=90):\n    return {"completed": completed, "remaining": total - completed}\n\nprint(progress(3))\n# {"completed": 3, "remaining": 87}\n```\n\n'
        'Trace it: `3` enters the function as `completed`; `90 - 3` gives `87`; the dictionary groups the two named values. '
        'A web API could return these values after a browser requests learning progress.',
        'Run the function with 0, 3 and 90 completed days. Add a check that rejects negative values and values above the total.'),
    2: ('HTML gives a page its structure. CSS changes how that structure looks. Use a real button for an action '
        'so keyboard users can reach it and activate it.',
        '```html\n<h1>My learning</h1>\n<p>Day 1 of 90</p>\n<button type="button">Continue lesson</button>\n<style>button { padding: 12px 20px; font-size: 16px; }</style>\n```\n\n'
        'The heading names the page, the paragraph shows progress, and the button offers one next action.',
        'Save this as an HTML file and open it. Use Tab to reach the button. Add a label and text field for a study note.'),
    3: ('JavaScript adds behaviour to a page. An event tells you something happened, such as a button click. '
        'Keep the data separate from the code that displays it.',
        '```javascript\nlet completed = 0;\nfunction finishLesson() {\n  completed = completed + 1;\n  return `${completed} lessons complete`;\n}\nconsole.log(finishLesson()); // 1 lessons complete\n```',
        'Call the function twice and explain why the value changes. Connect it to a button and display the result in a paragraph.'),
    4: ('JSON is a text format for sending simple data between programs. A request asks for data; a response '
        'returns a status and, often, a body containing JSON. A successful status does not guarantee that every field is valid.',
        '```javascript\nconst response = await fetch("/api/progress");\nif (!response.ok) throw new Error("Progress could not load");\nconst data = await response.json();\nconsole.log(data.completed);\n```\n\n'
        'This example needs a server that provides `/api/progress`. The first await waits for the response; '
        'the second reads and parses its body.',
        'Write an example JSON response with completed and remaining fields. Sketch what the page should show while loading and when the server fails.'),
    5: ('A database keeps information after your program stops. A table stores rows with named columns. '
        'A primary key identifies one row, and SQL is a language for asking questions about these rows.',
        '```sql\nCREATE TABLE lessons (id INTEGER PRIMARY KEY, title TEXT, completed INTEGER);\nINSERT INTO lessons VALUES (1, \'How a request travels\', 0);\nSELECT title FROM lessons WHERE completed = 0;\n```\n\n'
        'The query returns the title of each unfinished lesson. The integer flag uses 0 for unfinished and 1 for completed.',
        'Add a second lesson, mark the first complete with UPDATE, and query unfinished lessons again.'),
    6: ('The frontend is the page people use. The backend checks requests and applies rules. The database stores the result. '
        'Treat the browser as an untrusted caller: the server must check which learner is allowed to update a lesson.',
        'Trace a completion: click Finish → send lesson ID → server checks the learner → update the learner’s row → '
        'return the saved result → show a confirmation. If saving fails, keep the lesson unfinished on screen.',
        'Draw this request path. Describe what happens if the user clicks twice or loses their connection before the response arrives.'),
    7: ('A small complete project is easier to explain than several disconnected demos. Your study tracker joins a page, '
        'an API and stored progress. Start with one learner and one lesson; add more only after that path works.',
        'Use three checks: the page can read progress; finishing a lesson saves once; reloading the page shows the saved value. '
        'Explain where each check belongs: browser, API or database.',
        'Build or sketch the complete tracker. Demonstrate one success and one failure, then explain the request path without reading your notes.'),
}


def _words(value):
    return {word.rstrip('s') for word in _WORDS.findall(value.lower()) if word not in _STOP}


def _sections(text):
    # Only real headings count; code examples may contain Markdown strings.
    from pipeline.links import headings
    marks = [(level, title, start) for level, title, start in headings(text) if level == 2]
    result = []
    for index, (_, title, start) in enumerate(marks):
        if title.lower() in ('table of contents', 'practice questions', 'practice tasks', 'interview questions'):
            continue
        end = marks[index + 1][2] if index + 1 < len(marks) else len(text)
        result.append((title, text[start:end].strip()))
    return result


@lru_cache(maxsize=128)
def _file_sections(path, modified):
    return _sections(Path(path).read_text(encoding='utf-8'))


def _reading(spec, key, folder, course_root):
    """Select a relevant reference, or openly identify a reference-library gap.

    Weekly chapter preferences only break ties. They never make an unrelated
    first section stand in for a syllabus concept the chapter does not teach.
    """
    from pipeline.course import _demote
    from pipeline.links import headings
    base = Path(course_root).resolve()
    track = base / folder
    topic = str(spec[key])
    generic = {'simple', 'first', 'small', 'clear', 'review', 'basic', 'fundamental',
               'interview', 'explain', 'implement', 'add', 'repeat', 'complete',
               'one', 'new', 'model', 'data', 'app', 'application', 'service',
               'example', 'real', 'practical', 'useful', 'end', 'practice'}
    wanted = _words(topic) - generic
    requested = spec.get('reading_paths', {})
    preferred_path = requested.get(key) if isinstance(requested, dict) else None
    candidates = []
    for path in sorted(track.glob('[0-9][0-9]-*.md')):
        if not path.is_file() or not path.resolve().is_relative_to(track.resolve()):
            continue
        # Current news comes from Discover. A dated trends chapter is not a
        # substitute for a stable technical explanation in the core course.
        if path.name == '11-latest-ai-trends.md':
            continue
        for index, (title, body) in enumerate(_file_sections(str(path), path.stat().st_mtime_ns)):
            title_words = _words(title) - generic
            subheadings = ' '.join(text for level, text, _ in headings(body) if level > 2)
            nested_words = _words(subheadings) - generic
            overlap = wanted & title_words
            nested_overlap = wanted & nested_words
            relevant = (len(overlap) >= 2 and len(overlap) / max(1, len(wanted)) >= .5)
            relevant = relevant or (len(nested_overlap) >= 2 and len(nested_overlap) / max(1, len(wanted)) >= .6)
            score = len(overlap) * 10 + len(nested_overlap) * 3
            preferred = path.relative_to(base).as_posix() == preferred_path
            candidates.append({'score': score, 'preferred': preferred, 'index': index,
                               'path': path, 'title': title, 'body': body, 'relevant': relevant})
    if not candidates:
        raise ValueError('The bundled interview course is missing reading material. Restore the course files and retry.')
    chosen = None
    for pattern, chapter, fragment in _REFERENCE_ALIASES.get(key, ()):
        if not re.search(pattern, topic, re.I):
            continue
        chosen = next((item for item in candidates if item['path'].stem == chapter
                       and fragment.casefold() in item['title'].casefold()), None)
        if chosen:
            chosen = {**chosen, 'relevant': True}
            break
    if chosen is None:
        chosen = max(candidates, key=lambda item: (item['relevant'], item['score'], item['preferred'], -item['index']))
    path, title, body = chosen['path'], chosen['title'], chosen['body']
    primer = _FOUNDATION_PRIMERS.get((key, topic))
    primer_reference = _PRIMER_REFERENCES.get((key, topic))
    if primer and primer_reference:
        reference_path = base / primer_reference[0]
        if reference_path.is_file() and reference_path.resolve().is_relative_to(base):
            reference = next(((heading, text) for heading, text in _file_sections(str(reference_path), reference_path.stat().st_mtime_ns)
                              if primer_reference[1].casefold() in heading.casefold()), None)
            if reference:
                path, (title, body) = reference_path, reference
    route = '/course/#/' + path.relative_to(base).as_posix().removesuffix('.md')
    if primer:
        explanation, example = primer
        text = explanation + '\n\n**Worked example**\n\n' + example
        text += ('\n\nThe linked reference chapter is additional background. '
                 'This short guide introduces today’s topic; the daily lesson can develop it with more exercises.')
        match = 'primer'
        title = topic + ' — short guide'
    elif chosen['relevant']:
        text = _demote(body, 3)
        match = 'topic'
    else:
        # Do not embed a first/random section under a misleading lesson title.
        # The learner can still open an explicitly labelled background chapter.
        text = ('The bundled reference library does not yet contain a dedicated explanation of **%s**. '
                'The linked chapter is related background, not a full lesson on this topic. '
                'Prepare the next daily lesson for an explanation, worked example and exercise matched to today’s course topics.' % topic)
        title = 'Related background: ' + title
        match = 'related'
    return {'title': title, 'text': text, 'path': path.relative_to(base).as_posix(),
            'route': route, 'match': match, 'topic': topic}


_DAY_ONE = {
    'ai_ml': {
        'title': 'Decide what the study tracker should predict',
        'words': {'rule': 'Steps a developer writes directly, such as adding session minutes.',
                  'model': 'A function whose behavior can be learned from examples.',
                  'feature': 'An input available when a prediction is made.',
                  'label': 'The observed answer used to train or check a prediction.',
                  'baseline': 'A simple method measured before a more complex method.',
                  'mean absolute error': 'The average size of a numerical prediction error, ignoring its direction.'},
        'idea': '''The project is a study tracker. It records completed sessions and helps a learner plan the next one. These are two different jobs. “How many minutes have I already studied?” is an exact calculation over saved records. “How long will my next lesson take?” is uncertain. A prediction may help with the second question, but it is not needed for the first.

Machine learning uses examples to choose a model's behavior. For this prediction, one example could contain the lesson length, its topic and the learner's earlier experience. These are features if they are known before the session starts. The actual time taken is the label, observed after the session. Supervised learning means learning from examples that include an observed answer. Predicting a number is regression. Predicting a category, such as “likely to take more than 30 minutes”, is classification. Both require a precise target.

Write the timing of the decision before picking an algorithm. Using the session's final duration as an input when predicting that same duration leaks the answer. A high test score produced this way would not help a real learner. Also decide whether the prediction is personalized: mixing one learner's past and future sessions randomly can make a test more optimistic than a real future prediction.

First compare a simple baseline with a candidate model. A baseline might always predict a typical duration measured from earlier training records. The candidate might use lesson length and experience. Keep the final test examples separate from choosing the method. Today you will calculate error and describe the evaluation; you do not need to train a neural network.

At work, explain the decision, data available at that moment, baseline, success measure and limits. “We used AI” does not answer whether the feature improved planning. A model that saves one minute of average error but doubles latency may not be the right choice.''',
        'example': '''Assume a baseline was fixed at 25 minutes using earlier records. On three separate evaluation sessions, actual durations are `[20, 30, 40]`. Baseline predictions `[25, 25, 25]` have absolute errors `[5, 5, 15]`, giving `(5 + 5 + 15) / 3 = 8.33` minutes.

A candidate predicts `[22, 28, 35]`. Its errors are `[2, 2, 5]`, giving `3` minutes. On these examples it has lower mean absolute error. This does not establish reliable improvement on the population: there are only three observations, and we have not checked different topics or learners.

```python
def mean_absolute_error(actual, predicted):
    if len(actual) != len(predicted) or not actual:
        raise ValueError("provide equal, non-empty observation lists")
    return sum(abs(a - p) for a, p in zip(actual, predicted)) / len(actual)

assert mean_absolute_error([20, 30, 40], [22, 28, 35]) == 3
```

This calculation assumes already validated, finite numerical inputs. `zip` pairs the corresponding actual and predicted values. `abs` removes the sign of each error; adding and dividing produces the average error in minutes. Input validation is a separate boundary, as in today's full-stack implementation. See the [scikit-learn metric definition](https://scikit-learn.org/stable/modules/model_evaluation.html#mean-absolute-error) and [data-leakage guide](https://scikit-learn.org/stable/common_pitfalls.html#data-leakage).''',
        'steps': ["Name the user's decision before naming a model.",
                  'List what is known before prediction and what becomes known afterwards.',
                  'Fix a baseline using earlier examples, then compare errors on separate evaluation examples.',
                  'State what this tiny experiment cannot prove and what evidence you would gather next.'],
        'task': 'Explain why adding recorded session minutes needs a rule, while estimating an unseen session may use a learned model.',
        'answer': 'Adding known minutes has an exact rule and a checkable answer. A future duration is not known, so a model can estimate it from inputs available in advance. Compare that estimate with a baseline using later observed durations; neither a model nor its score makes the future certain.',
    },
    'system_design': {
        'title': 'Trace the study-summary request',
        'words': {'API': 'A contract one program uses to ask another program for an action or data.',
                  'HTTP request': 'A message with a method, an address, headers and sometimes a body.',
                  'validation': 'Checking that incoming data meets an explicit contract.',
                  'response': 'The status and data sent back to the caller.',
                  'durable': 'Stored so it can survive the process stopping.',
                  'stateless calculation': 'A calculation whose result depends on the supplied input, without remembering an earlier request.'},
        'idea': '''Follow one action: the learner asks for a summary of three study sessions. The browser sends `POST /api/study-summary` with a JSON body `{"minutes": [20, 30, 40]}`. POST is used here to submit data for processing. This endpoint only calculates; it does not create a saved session.

Before the application sees that message, the browser resolves the server name when necessary, establishes or reuses a connection, and uses TLS for an HTTPS connection. DNS maps a name to network information. TLS protects data in transit and helps the client verify the server. These steps may be reused from earlier requests; they are not guaranteed to repeat for every click.

The application checks the path and method, enforces a body-size limit, parses JSON, and validates its fields. Then it calls the summary function. A successful response has status 200 and a body containing count, total minutes and mean minutes. Invalid duration data receives a documented client error such as 400. A server fault is different from a user's invalid input and should be recorded internally without exposing its stack trace.

A successful calculation is not evidence of a saved record. On Day 6 the project connects the page, API and storage. That write path needs an identity, permission checks and a policy for duplicate requests. If a response is lost after a write, the browser cannot infer whether the save happened just from its timeout.

Keep the current design small. A web process and a pure calculation are enough for this endpoint. Adding a queue, cache and separate model server before measuring a need creates more failure paths. For a future prediction endpoint, add the model version, evaluation and fallback behavior deliberately.''',
        'example': '''Trace the normal case and a failure without changing the story:

| Step | Valid request | Invalid request |
| --- | --- | --- |
| Browser sends | `{"minutes": [20, 30, 40]}` | `{"minutes": [20, "later"]}` |
| Boundary check | All durations pass | Text is rejected |
| Calculation | Count 3; total 90; mean 30 | Not called with invalid values |
| Response | 200 and the summary | 400 and a field error |
| Screen | Shows the returned summary | Keeps the input and explains the problem |

Suppose the request takes 120 ms of network time and 5 ms in the application. Optimizing the addition loop from 1 ms to 0.5 ms barely changes the user experience. Measure the critical path before choosing a performance fix. These times are illustrative assumptions, not benchmark results.''',
        'steps': ['Write the exact request and success response.', 'Trace parsing, validation and calculation in order.',
                  'Explain what the screen should do for invalid input, server failure and a lost response.',
                  'State which operation stores data and which only calculates.'],
        'task': 'The browser times out after sending the summary request. Can it repeat the calculation? Can the same reasoning automatically justify repeating a saved-session creation?',
        'answer': 'Repeating this stateless summary calculation has no saved side effect. A creation request may already have committed, so a safe retry needs a stable operation identifier and server-side duplicate handling, or a check of the saved outcome. HTTP method alone does not tell you whether your implementation is safe to repeat.',
    },
    'full_stack': {
        'title': 'Build a summary you can test',
        'words': {'function': 'A named unit of code that receives inputs and returns a result.',
                  'contract': 'The allowed inputs, outputs and failure behavior of a function or API.',
                  'boundary': 'Where information enters from another program or an untrusted caller.',
                  'pure calculation': 'A computation that returns a result without changing stored state or calling external services.',
                  'assertion': 'A check that stops the example if an expected result is false.'},
        'idea': '''A developer with experience should be able to separate three responsibilities: receiving outside input, calculating a result, and storing a change. Today, implement the first two for a study summary. Storage comes later. This separation lets you test the calculation without starting a browser, database or web server.

Define the contract before the code. `minutes` is a list of finite numbers between 0 and 1,440, with at most 10,000 entries. Return `count`, `total_minutes` and `mean_minutes`. For an empty list, count and total are zero, but mean is `None`: there was no observation to average. Do not turn missing information into a made-up zero.

Validation is part of behavior, not a decorative check. Python treats a boolean as a kind of integer, so `isinstance(True, int)` is true. The exact-type check in the implementation rejects it. A successful JSON parse also does not prove that a field has the right shape or type. Reject malformed input before any state change.

Read the implementation below, then close it and rebuild the function. The request handler translates a validation failure into a status and an error object. It does not print an answer and hope the browser can find it. The function returns a value that another caller can serialize, display or test.

For the next project step, attach this behavior to your web framework. Define how it receives a JSON body and returns the status and fields. Keep the calculation unchanged. If moving from a unit test to an HTTP handler requires rewriting the arithmetic, the responsibilities are still mixed.''',
        'example': '''For `[20, 30, 40]`, the returned object is `{"count": 3, "total_minutes": 90.0, "mean_minutes": 30.0}`. For `[]`, it is `{"count": 0, "total_minutes": 0.0, "mean_minutes": null}` after JSON serialization. For `[True]`, `[-1]` or `["20"]`, the handler returns a client error.

The implementation lab includes a calculation function and a handler. Run its assertions before adding any web framework. Then change one input at a time and predict the result before running it. This is how you connect readable code with observable behavior.''',
        'steps': ['Write the input and output contract in a short comment.', 'Implement validation before arithmetic.',
                  'Run normal, empty, zero and invalid-input checks.', 'Explain how an HTTP adapter will call the same function.'],
        'task': 'Why should an empty list return no mean instead of zero, and why should True be rejected as a duration?',
        'answer': 'No mean exists for no observations; zero is a real observed value and would tell a different story. True is a boolean, even though Python permits it in arithmetic. The application contract expects numerical durations, so the boundary rejects it instead of silently recording one minute.',
    },
}


def _dsa_material(spec, course_root):
    """Read an actual pattern chapter; label reused chapter context honestly."""
    if spec['day'] == 1:
        return '''### One scan, with a reason it works

Use the same study durations as the API: `[20, 30, 40]`. An array is an ordered collection; Python's list is the collection used in the example. Read one value at a time and keep a running total. You do not need to sort these values to add them.

| Values already visited | Count | Running total |
| --- | --- | --- |
| none | 0 | 0 |
| 20 | 1 | 20 |
| 20, 30 | 2 | 50 |
| 20, 30, 40 | 3 | 90 |

The invariant is a statement that remains true as the loop runs: **after visiting the first k values, total is their sum**. Initially no values have been visited and the sum is zero. Adding the next value makes the statement true for k+1. When the loop ends, all values have been visited, so total is the required sum. This is a short correctness argument, not just a claim that a test passed.

The scan takes O(n) time because it visits n values once. It uses O(1) extra memory because total and count do not grow into another collection; this excludes the input and returned object. An empty input has total zero and no mean. A valid zero value is still an observation. Repeated values count repeatedly because two sessions may have the same duration; removing duplicates would change the question.

Implement the scan yourself, then compare it with the full-stack function. Test `[]`, `[0]`, `[20]`, `[20, 20]` and `[20, 30, 40]`. Say the expected count and total before running the test. Finally explain why sorting first adds work without helping this task.

### Coding follow-up

If session minutes arrive one at a time, can you keep a running mean without storing the whole history? Keep a count and total, then derive the mean when count is nonzero. If the product allows correcting an earlier session, that small state alone cannot identify which old value to replace; you need the original record or a correction event. A changed requirement changes the information you must retain.'''
    topic = spec['dsa'].lower()
    rules = (
        (r'dynamic programming|knapsack|subsequence|grids', '09-dynamic-programming'),
        (r'trie|bit manipulation', '11-tries-bit-manipulation'),
        (r'backtracking|subsets|combinations', '08-backtracking'),
        (r'tree|recursion', '05-trees-bst'),
        (r'graph|breadth.first|depth.first|topological|shortest|union.find', '07-graphs'),
        (r'heap|top k|scheduling', '06-heaps-priority-queues'),
        (r'interval|greedy', '10-greedy-intervals'),
        (r'binary search|sorting', '04-binary-search'),
        (r'two pointers|sliding window|window interview', '02-two-pointers-sliding-window'),
        (r'stack|queue|linked list', '03-stack-queue-linkedlist'),
        (r'array|string|hash|maps|prefix sums', '01-arrays-strings-hashing'),
    )
    chapter = next((name for pattern, name in rules if re.search(pattern, topic)), '12-mock-interview-sets')
    path = Path(course_root) / '02-dsa' / (chapter + '.md')
    route = '/course/#/02-dsa/' + chapter
    if not path.is_file() or not path.resolve().is_relative_to(Path(course_root).resolve()):
        return 'Write a small example for **' + spec['dsa'] + '**. Explain a correct baseline, its invariant and its cost, then test a boundary case. The public practice chapter is unavailable on this installation; the DSA practice workspace remains linked below.'
    from pipeline.course import _demote
    sections = _file_sections(str(path), path.stat().st_mtime_ns)
    # Shared concept/template sections are labelled as pattern references, not
    # passed off as 90 separately authored question sets. Worked exercises stay
    # in the practice chapter and workspace.
    if chapter == '12-mock-interview-sets':
        from pipeline.links import headings
        mocks = [(title, body) for title, body in sections if title.startswith('Mock Set ')]
        if mocks:
            title, body = mocks[(spec['day'] - 1) % len(mocks)]
            marks = [(level, name, start) for level, name, start in headings(body) if level == 3 and name.startswith('Problem ')]
            prompts = []
            for index, (_, name, start) in enumerate(marks[:2]):
                end = marks[index + 1][2] if index + 1 < len(marks) else len(body)
                prompt = body[start:end].split('**Approach:**', 1)[0].strip()
                prompts.append(_demote(prompt, 4))
            return ('### Timed coding practice\n\n'
                    'Take 35 minutes for these two exercises: five to clarify inputs and outline a correct approach, '
                    'twenty to implement, and ten to trace boundary cases and explain time and memory cost. '
                    'These are practice timings, not a claim about a company’s interview.\n\n'
                    + '\n\n'.join(prompts) + f'\n\nAfter your attempt, [compare the worked solutions in {title}]({route}). '
                    'Record the first incorrect assumption or failing test, then solve a changed example without the guide.')
    selected = [(title, body) for title, body in sections if re.search(r'concept|template|complexity summary', title, re.I)]
    reference = '\n\n'.join(_demote(body, 4) for _, body in selected[:3])
    return ('### Pattern reference for today\n\n'
            f'Your focus is **{spec["dsa"]}**. Use this related pattern family and its template below to reason about a problem, '
            'then solve one suitable exercise in the linked chapter. The chapter is shared across related course days. '
            'A template is a starting point; explain why its invariant fits the input before using it.\n\n'
            + reference + f'\n\n[Open the pattern chapter and worked problems]({route})')

def lesson(day, course_root):
    """Join daily teaching with visible technical reading and weekly cases."""
    spec = interview_course.day_spec(day)
    subjects = (
        ('ai_ml', 'AI and machine learning', _DAY_ONE['ai_ml'] if day == 1 else interview_ai_basics.lesson(day)),
        ('system_design', 'System design', _DAY_ONE['system_design'] if day == 1 else interview_system_basics.lesson(day)),
        ('full_stack', 'Full-stack development', _DAY_ONE['full_stack'] if day == 1 else interview_fullstack_basics.lesson(day)),
    )
    readings = []
    for key, label, folder in _TRACKS:
        try:
            readings.append({'track': key, **_reading(spec, key, folder, course_root)})
        except (OSError, ValueError):
            # The authored daily material and notebook remain self-contained.
            continue
    parts = [f"# Day {day}: {spec['title']}", '',
             '## Start here', '',
             'This course is for working developers with around three years of experience. '
             'Read the technical explanation and system flow, trace the examples, implement the task, then defend your decisions in an interview. '
             'Keep the answers closed until you have tried. '
             'Allow around 3–4 hours for reading and practice, or split the lesson across sessions. There is no daily reading limit.', '',
             '**Today you will practise:**', '',
             *[f"{index}. {entry['title']}" for index, (_, _, entry) in enumerate(subjects, 1)],
             '4. Solve DSA problems, explain why the algorithm works, and compare its time and memory costs.', '']
    for index, (key, label, entry) in enumerate(subjects, 1):
        practice = interview_practice.subject(day, key)
        notebook = interview_engineering.notebook(day, key)
        guide = next(item for item in spec['learning_path'] if item['key'] == key)
        if day == 1:
            practice['drill'] = guide['task']
            practice['checks'] = guide['checks']
            practice['explanation'] = 'Keep today’s exact summary separate from a prediction about a future session.'
            practice['scenario'] = entry['example']
            practice['mistake'] = {'ai_ml': 'Do not describe a summary of known minutes as a prediction or use the future duration as an input.', 'system_design': 'Do not report a saved session when this endpoint has only calculated a summary.', 'full_stack': 'Do not show zero for an unavailable mean, or accept a boolean as a duration.'}[key]
        reference = next((item for item in readings if item['track'] == key and item['match'] == 'topic'), None)
        # Keep broad interview lists in the question bank. Embed only actual
        # technical sections, never a fallback chapter under the day's title.
        technical = []
        if reference and not re.search(r'interview-(?:framework-and-)?questions', reference['path']):
            from pipeline.course import _demote
            technical = ['#### Technical detail', '',
                         f"This reference develops **{reference['title']}**, which supports today’s topic.", '',
                         _demote(reference['text'], 5), '',
                         f"[Open the full chapter: {reference['title']}]({reference['route']})", '']
        parts += [f"## {index}. {entry['title']}", '', f'**Subject: {label}**', '',
                  '### Words you need', '',
                  *[f'- **{word}:** {meaning}' for word, meaning in entry['words'].items()], '',
                  '### The idea', '', entry['idea'], '', practice['explanation'], '',
                  *technical,
                  f"#### Engineering notebook · Week {notebook['week']}", '',
                  f"**{notebook['title']}**", '',
                  'This case connects the week’s topics. Reuse the same system as you study each new part. '
                  f"Today, focus on **{notebook['focus']}** and explain where it affects the flow.", '',
                  notebook['text'], '',
                  *([interview_engineering.implementation_lab(day), ''] if key == 'full_stack' else []),
                  '### A small example', '', entry['example'], '',
                  *[f'{step}. {instruction}' for step, instruction in enumerate(entry['steps'], 1)], '',
                  *(['#### A real-world case', '', practice['scenario'], ''] if day != 1 else []),
                  '### Your turn', '', practice['drill'], '',
                  'Use the system flow above to trace a successful request and one failure. '
                  'Write down the inputs, state changes, expected output and the reason for your design choice.', '',
                  '#### Your task is ready when', '',
                  *['- ' + item for item in practice['checks']], '',
                  '### Check your answer', '',
                  'Check the result against these criteria. Keep evidence such as a trace, test output or a measured comparison.', '',
                  *['- ' + item for item in practice['checks']], '',
                  '#### Quick foundation check', '', entry['task'], '', entry['answer'], '',
                  '### Interview practice', '',
                  'Say your answer out loud before opening the guide. Explain your choice, give an example, and name a limit.', '']
        for number, question in enumerate(practice['questions'], 1):
            parts += [f'#### Question {number}', '', question['question'], '',
                      '##### Show answer', '', question['answer'], '',
                      '##### Follow-up', '', question['follow_up'], '',
                      '###### Show follow-up answer', '', question['follow_up_answer'], '']
        parts += ['#### Common mistake', '', practice['mistake'], '']
    parts += ['## Build and test', '',
              f"**This week’s project:** {spec['project']}", '',
              f"**Today’s output:** {spec['deliverable']}", '',
              'Keep one small project folder. Add today’s work to it, with a short record of the input, expected result, actual result and decision. '
              'This connects the daily exercises into a project you can demonstrate and explain.', '',
              '### Check today’s build', '',
              *['- ' + item for item in spec['learning_path'][2]['checks']], '',
              '## DSA practice', '',
              f"**Course practice focus:** {spec['dsa']}", '',
              _dsa_material(spec, course_root), '',
              'Continue through Learn, Worked example, Practice and Review. '
              'Study the invariant, trace the changing values, then solve the assigned problems before reviewing.', '',
              '### Use an interview routine', '',
              '1. Ask what the input and output mean. Check the size limit and whether values can repeat.',
              '2. Work one tiny example by hand. Explain a simple correct solution before improving it.',
              '3. Say why your steps work. Then write the code and trace the changing values.',
              '4. Test an empty input, one item and a repeated value when those inputs are allowed.',
              '5. Explain time cost (how work grows with input size) and space cost (extra memory used).', '',
              '[Continue DSA practice](#/learning/dsa)', '',
              'Your next DSA topic follows your saved practice. If it feels hard, stay on that topic and try again.', '',
              '## Interview and recall', '',
              'Close the notes. Say these answers out loud. Simple words are enough.', '',
              '1. What did you learn? Give one example.',
              '2. Why does your solution work, and where can it fail?',
              '3. Which alternative did you reject, and what evidence would change your choice?', '',
              'Write down one question you needed help with. Try it again tomorrow without the answer.', '']
    if spec['review']:
        assessment = interview_practice.weekly_assessment(spec['week'])
        parts += ['## Weekly project and mock interview', '',
                  f"### {assessment['title']}", '', assessment['brief'], '',
                  '### Your project is ready when', '', *['- ' + check for check in assessment['checks']], '',
                  '### Timed interview', '', assessment['timing'], '', assessment['mock_question'], '',
                  '#### Show answer', '', assessment['mock_answer'], '',
                  '### Review your performance', '', 'Use this self-check for your reasoning, example, tests and trade-off. It is practice feedback, not a hiring score.', '',
                  *['- ' + item for item in assessment['rubric']], '']
    parts += ['## Interview question bank', '',
              'Revise one subject or search for a weak topic. Questions include answer guides and follow-ups.', '',
              '[Open the interview question bank](#/learning/weekly?view=questions)', '',
              '## Extra reading (optional)', '',
              'The main lesson already includes technical reading and a system flow. These full chapters provide further context.', '',
              *[f"- [{entry['title']}]({entry['route']})" for entry in readings], '',
              'Discover has research papers, GitHub projects, and tech news. '
              'You do not need to read them to finish this lesson.', '',
              '[Open Discover](#/learning/discover)', '',
              '## Review and finish', '',
              'Finish when you can explain today’s ideas, show your implementation or trace, and describe one failure case. '
              'Opening a lesson or reading an answer does not mark the day complete. Use the completion control when you are ready.', '',
              *['- ' + item['outcome'] for item in spec['learning_path']], '',
              'If one part is still unclear, keep this day open and return to that part. The course advances from your saved completion, not the calendar.', '']
    identifier = f'interview/day-{day}'
    return {'id': identifier, 'key': identifier, 'day': day, 'title': spec['title'],
            'text': '\n'.join(parts), 'category': 'Learning', 'source': 'bundled',
            'lesson': spec, 'readings': readings}


def _saved_enrichment(spec, learning_root):
    """Read current generated material without assembling the public fallback."""
    day = spec['day']
    root = Path(learning_root) / interview_course.COURSE_ID
    path = root / 'weeks' / f"week-{spec['week']:02d}.md"
    if path.is_file() and path.resolve().is_relative_to(root.resolve()):
        try:
            metadata_path = path.with_suffix('.meta.json')
            if not metadata_path.resolve().is_relative_to(root.resolve()):
                raise ValueError('Invalid course metadata path.')
            meta = json.loads(metadata_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            meta = {}
        if (isinstance(meta, dict) and meta.get('course_id') == interview_course.COURSE_ID
                and meta.get('course_version') == interview_course.COURSE_VERSION):
            from pipeline.learning import split_days
            text = split_days(path.read_text(encoding='utf-8')).get(day)
            if text:
                sources = meta.get('day_sources', {})
                source = sources.get(str(day), {}) if isinstance(sources, dict) else {}
                # Preserve saved files. Until fresh enrichment is ready, show
                # the current public lesson with its technical notebook.
                if not isinstance(source, dict) or source.get('teaching_version') != interview_course.TEACHING_VERSION:
                    return None
                if source.get('source') == 'bundled':
                    return None
                return {'text': text, 'file': path}
    return None


def saved_source(day, learning_root):
    """Return the reader's source for a roadmap without building lesson text.

    Generated provenance alone is not enough: the selected day must actually
    exist in its saved week. Public lessons need no reference files or rendering
    to be available, so their expensive optional reading lookup is deferred.
    """
    spec = interview_course.day_spec(day)
    return 'generated' if _saved_enrichment(spec, learning_root) else 'bundled'


def saved_lesson(day, learning_root, course_root):
    """Prefer a validated local enrichment, otherwise use the public guide."""
    spec = interview_course.day_spec(day)
    enrichment = _saved_enrichment(spec, learning_root)
    if enrichment:
        identifier = f'interview/day-{day}'
        return {'id': identifier, 'key': identifier, 'day': day, 'title': spec['title'],
                'text': enrichment['text'], 'category': 'Learning', 'source': 'generated',
                'lesson': spec, 'file': enrichment['file']}
    return lesson(day, course_root)


def render(text):
    """Render lesson Markdown without raw HTML, trackers, or local file links."""
    from markdown_it import MarkdownIt
    md = MarkdownIt('commonmark', {'html': False}).enable(['table', 'strikethrough'])
    tokens = md.parse(text)
    for token in tokens:
        for child in token.children or []:
            if child.type == 'image':
                child.type = 'text'; child.content = '[Image omitted]'
                child.children = None; child.tag = ''; child.attrs = {}
            if child.type != 'link_open':
                continue
            href = child.attrGet('href') or ''
            parsed = urlsplit(href)
            if parsed.scheme in ('https', 'http') and parsed.hostname and not parsed.username:
                child.attrSet('target', '_blank'); child.attrSet('rel', 'noopener noreferrer')
            elif href.startswith(('#/learning/', '/#/learning/', '/course/#/')) and '\\' not in href:
                child.attrSet('target', '_top')
            elif href.startswith('#') and not href.startswith('#/'):
                pass
            else:
                child.attrSet('href', '#')
    # Only these fixed, trusted wrappers create HTML. HTML supplied in the
    # Markdown is still escaped. Hide answers until the learner asks for them.
    from markdown_it.token import Token
    rendered = []
    disclosure_level = None
    index = 0
    while index < len(tokens):
        token = tokens[index]
        # Generated subjects use bold labels for compatibility with the saved
        # week format. A subject label must never be swallowed by an answer.
        if (disclosure_level is not None and token.type == 'paragraph_open'
                and index + 1 < len(tokens)
                and re.match(r'^\*\*(?:ML / GenAI:|System Design:|Full-stack:|DSA:|Recall\*\*|Go deeper\*\*)',
                             tokens[index + 1].content)):
            closing = Token('html_block', '', 0); closing.content = '</details>\n'
            rendered.append(closing); disclosure_level = None
        if token.type == 'hr' and disclosure_level is not None:
            closing = Token('html_block', '', 0); closing.content = '</details>\n'
            rendered.append(closing); disclosure_level = None
        if token.type == 'heading_open':
            level = int(token.tag[1:])
            if disclosure_level is not None and level <= disclosure_level:
                closing = Token('html_block', '', 0); closing.content = '</details>\n'
                rendered.append(closing); disclosure_level = None
            title = tokens[index + 1].content.strip().lower()
            labels = {'check your answer': 'Check your answer', 'extra reading (optional)': 'Extra reading (optional)',
                      'show answer': 'Show answer', 'show follow-up answer': 'Show follow-up answer'}
            if title in labels:
                if disclosure_level is not None:
                    closing = Token('html_block', '', 0); closing.content = '</details>\n'
                    rendered.append(closing)
                label = labels[title]
                opening = Token('html_block', '', 0)
                opening.content = f'<details><summary>{label}</summary>\n'
                rendered.append(opening); disclosure_level = level
                index += 3
                continue
        rendered.append(token)
        index += 1
    if disclosure_level is not None:
        closing = Token('html_block', '', 0); closing.content = '</details>\n'
        rendered.append(closing)
    return md.renderer.render(rendered, md.options, {})
