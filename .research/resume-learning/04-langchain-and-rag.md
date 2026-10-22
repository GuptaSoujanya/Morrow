# LangChain and RAG

## What it is

LangChain is a framework for composing LLM calls, tools, memory, and retrieval into pipelines, using a common set of abstractions (chains, agents, retrievers, document loaders) so you don't rebuild the same plumbing - prompt templating, output parsing, calling a vector store, orchestrating multi-step chains - from scratch for every project. RAG (Retrieval-Augmented Generation) is the pattern of grounding an LLM's answer in documents retrieved from an external knowledge source at query time, rather than relying solely on what the model memorized during training: embed a query, search a vector store for the most relevant chunks, and feed those chunks into the prompt alongside the question.

## How you used it

The resume lists LangChain and RAG explicitly under AI/LLM skills, and describes building **Python and LangChain pipelines that benchmark OpenAI, Gemini, Claude, LLaMA, and Grok across finance, e-commerce, and healthcare tasks** as part of the model-evaluation and dataset-quality work. This means LangChain was used as the orchestration layer for running the *same* task prompts and tool definitions against five different model providers in a uniform way, collecting their outputs, and feeding those outputs into the evaluation metrics (CodeBLEU, n-gram similarity, dataflow match, human-eval rubrics - covered in the metrics file) consistently regardless of which model produced them. The **EvalAgentFlow** project is a directly related, LangChain-based system: an eight-agent pipeline (Python, LangChain) that turns raw CSV evaluation data into finished benchmark reports, moving through ingestion, cleaning, statistics, anomaly detection, insight extraction, and export, blending human-eval rubrics with CodeBLEU, n-gram similarity, and dataflow-match metrics.

## Core concepts

**1. Chains as composable pipelines.** A LangChain chain wires together a prompt template, a model call, and an output parser into one callable unit, and chains can be composed into larger pipelines:

```python
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI

prompt = ChatPromptTemplate.from_template(
    "Summarize this {domain} transaction log in 3 bullet points:\n{content}"
)
model = ChatOpenAI(model="gpt-5.5")
chain = prompt | model | StrOutputParser()

result = chain.invoke({"domain": "finance", "content": raw_log})
```

**2. Model-agnostic benchmarking.** The same chain structure can swap its model component to compare providers on identical prompts:

```python
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI

models = {
    "gpt": ChatOpenAI(model="gpt-5.5"),
    "claude": ChatAnthropic(model="claude-sonnet-..."),
    "gemini": ChatGoogleGenerativeAI(model="gemini-..."),
}

results = {name: (prompt | m | StrOutputParser()).invoke(inputs) for name, m in models.items()}
```

This is the core pattern behind benchmarking "OpenAI, Gemini, Claude, LLaMA, and Grok across finance, e-commerce, and healthcare tasks" - one set of domain prompts, run through a uniform chain shape, with only the model component varying, so differences in output are attributable to the model rather than to inconsistent prompting or parsing across providers.

**3. Multi-agent pipelines (EvalAgentFlow pattern).** LangChain (and its graph-oriented sibling LangGraph) supports structuring a workflow as a sequence of specialized agents, each responsible for one stage, passing a shared state object forward:

```python
def ingest_agent(state):
    state["df"] = pd.read_csv(state["csv_path"])
    return state

def clean_agent(state):
    state["df"] = state["df"].dropna(subset=["prediction", "reference"])
    return state

def stats_agent(state):
    state["stats"] = compute_summary_stats(state["df"])
    return state

pipeline = [ingest_agent, clean_agent, stats_agent, anomaly_agent, insight_agent, export_agent]
for stage in pipeline:
    state = stage(state)
```

An eight-agent version of this extends the stage list (ingestion, cleaning, statistics, anomaly detection, insight extraction, export, plus others) and each stage can itself be backed by an LLM call (e.g., the insight-extraction agent asks a model to summarize what the statistics mean in plain language) or by deterministic code (the stats agent is likely pure pandas/numpy, not an LLM call at all) - mixing deterministic and LLM-backed steps in one pipeline is a common and effective pattern.

**4. Document loaders and chunking for RAG.** Before you can retrieve anything, you need to load and split source documents into chunks small enough to embed meaningfully and large enough to carry context:

```python
from langchain_text_splitters import RecursiveCharacterTextSplitter

splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)
chunks = splitter.split_documents(loaded_docs)
```

Chunk size and overlap are a real tuning problem: too small and you lose context within a chunk; too large and irrelevant text dilutes the embedding and wastes context window at query time.

**5. Embeddings and vector stores.** Each chunk is embedded into a vector, stored in a vector database (Chroma, FAISS, pgvector, etc.), and retrieved at query time by nearest-neighbor similarity to the embedded query:

```python
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import Chroma

vectorstore = Chroma.from_documents(chunks, embedding=OpenAIEmbeddings())
retriever = vectorstore.as_retriever(search_kwargs={"k": 4})
```

**6. The RAG chain.** Retrieval is wired into the chain as a step before the model call, so the prompt is built with retrieved context rather than the raw question alone:

```python
from langchain_core.runnables import RunnablePassthrough

rag_chain = (
    {"context": retriever, "question": RunnablePassthrough()}
    | prompt
    | model
    | StrOutputParser()
)
```

**7. Why RAG matters for evaluation specifically.** In a benchmarking context, RAG shows up in two ways: as a capability under test (does an agent correctly retrieve and cite relevant mock-service data before answering, similar in spirit to the drift-injection re-verification test), and as infrastructure for the evaluation pipeline itself (retrieving relevant prior examples, rubric sections, or domain reference documents to ground a judge's or pipeline stage's own reasoning).

**8. Domain-specific pitfalls.** Finance, e-commerce, and healthcare tasks each bring their own retrieval and grounding challenges - financial figures need exact-match precision (a RAG system paraphrasing a number is a correctness bug, not a style choice), healthcare content carries real-world risk if hallucinated, and e-commerce catalogs are large and noisy, making chunk relevance harder to get right. A benchmarking pipeline across these domains needs per-domain evaluation criteria, not one generic rubric.

## Interview questions and answers

**Q1: Walk me through the LangChain pipeline you built for benchmarking multiple model providers.**
I defined a single prompt template and output-parsing structure per domain task (finance, e-commerce, healthcare), then swapped only the model component - OpenAI, Gemini, Claude, LLaMA, Grok - across identical chains, so any difference in output was attributable to the model rather than to inconsistencies in how each provider was prompted or parsed. Outputs then fed into our evaluation metrics (CodeBLEU, n-gram similarity, dataflow match, human-eval rubrics) for comparison.

**Q2: Describe EvalAgentFlow - what does each agent do?**
It's an eight-agent LangChain pipeline that turns raw CSV evaluation data into a finished benchmark report. Stages move through ingestion (load the CSV), cleaning (drop invalid/missing rows), statistics (aggregate metrics), anomaly detection (flag outlier scores or suspicious patterns), insight extraction (summarize what the stats mean, often LLM-backed), and export (produce the final report). Some stages are deterministic pandas/numpy code; others are LLM calls - mixing both in one pipeline kept cost down while still producing readable, synthesized insights.

**Q3: What is RAG, and why use it instead of just stuffing all documents into the prompt?**
RAG retrieves only the most relevant chunks of a larger corpus at query time via embedding similarity, rather than including everything - which would blow the context window and dilute relevance with irrelevant text. It also lets the knowledge base update without retraining or re-prompting the model from scratch each time documents change.

**Q4: How do you choose chunk size and overlap for a RAG pipeline?**
It's a tradeoff: too small loses context within a chunk and fragments related information across chunk boundaries; too large dilutes the embedding's relevance signal and wastes context window with irrelevant text. In practice this is tuned empirically per domain - dense technical content (finance figures, healthcare dosages) needs smaller, more precise chunks than narrative text.

**Q5: What's a concrete failure mode of RAG you'd watch for in a healthcare or finance domain?**
Retrieval returning a plausible but wrong chunk (e.g., the wrong year's figures, or a similar-sounding but different drug) that the model then confidently builds an answer around - this is worse than an obvious hallucination because it looks grounded. Domain-specific evaluation criteria and exact-match checks on key figures (not just semantic similarity) are needed to catch it.

**Q6: Why structure a pipeline as multiple specialized agents instead of one big LLM call?**
Splitting into stages (ingest, clean, stats, anomaly, insight, export) makes each stage independently testable, lets you use cheap deterministic code where an LLM call isn't needed (cleaning, statistics), and keeps each LLM-backed stage's prompt focused and small, which improves reliability compared to asking one model to do everything in one shot.

**Q7: How would you add a new model provider to a LangChain benchmarking pipeline?**
Swap in the corresponding LangChain chat-model integration (or route it through an inference gateway like LiteLLM) as the model component of the existing chain; the prompt template, output parser, and downstream evaluation metrics don't need to change since the chain's interface stays uniform.

**Q8: What's the difference between a LangChain "chain" and a LangChain "agent"?**
A chain executes a fixed sequence of steps; an agent decides at runtime which tools to call and in what order based on the model's own reasoning, typically looping until it decides the task is done. EvalAgentFlow's stage sequence is closer to a fixed chain/pipeline, while a benchmark-under-test agent (as in the harness file) makes its own tool-call decisions.

**Q9: How do you evaluate retrieval quality separately from generation quality in a RAG system?**
Check whether the retrieved chunks actually contain the information needed to answer the question (retrieval precision/recall against a labeled set of question-to-relevant-chunk mappings) independently of whether the final generated answer used that information correctly - a system can retrieve the right chunk and still generate a wrong answer, or retrieve the wrong chunk and still generate a correct answer by luck, and you want to tell those cases apart.

**Q10: What would you change about this pipeline if the CSV inputs started arriving at much higher volume?**
Move the deterministic stages (ingestion, cleaning, statistics) to a batch/streaming data-processing path outside the LangChain pipeline entirely, and only route to the LLM-backed stages (insight extraction) the subset of data that actually needs synthesis, since LLM calls are the expensive and slow part of the pipeline and don't need to scale linearly with raw row count.

## Hands-on

1. **Build a two-provider benchmarking chain.** Write one prompt template and swap between two chat-model integrations (or two LiteLLM-routed models) to compare their outputs on the same five inputs, logging both outputs side by side.
2. **Implement a minimal RAG chain.** Load 3-5 short text documents, split them into chunks, embed and store them in an in-memory vector store, and answer a question by retrieving the top 2 chunks and feeding them into a prompt - then check, by hand, whether the retrieved chunks actually contained the answer.

## Read next

- [LangChain documentation](https://python.langchain.com/docs/introduction/)
- [LangChain RAG tutorial](https://python.langchain.com/docs/tutorials/rag/)
- [../../course/04-ml-genai-agents/05-rag.md](../../course/04-ml-genai-agents/05-rag.md)
- [../../course/04-ml-genai-agents/06-agents-and-tool-use.md](../../course/04-ml-genai-agents/06-agents-and-tool-use.md)
