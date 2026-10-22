# Metrics and Dataset Quality

## What it is

This topic covers two related but distinct concerns in ML/LLM evaluation work: **metrics** - the quantitative measures used to score model or agent outputs (CodeBLEU, n-gram similarity, dataflow match, and human-eval rubrics are the four named on the resume) - and **dataset quality** - the practices that keep the underlying evaluation and training data itself trustworthy, covering taxonomy classification, entropy checks, and inter-rater agreement. A benchmark is only as good as the metrics it scores with and the data it scores against; both need deliberate engineering, not just a default library call.

## How you used it

The resume lists, under LLM evaluation skills, **CodeBLEU, n-gram similarity, dataflow match, and human-eval rubrics**, and the EvalAgentFlow project description confirms these were blended together in practice: EvalAgentFlow is "an eight-agent pipeline that turns raw CSV evaluation data into finished benchmark reports... blending human-eval rubrics with CodeBLEU, n-gram similarity, and dataflow-match metrics." Separately, under model evaluation and dataset quality, the resume states you **owned training-data quality from end to end, covering taxonomy classification, entropy checks, and inter-rater agreement**, **handled NLP preprocessing and structured annotation**, and **built an internal Odoo app for labeling golden datasets**.

## Core concepts

**1. CodeBLEU.** BLEU (from machine translation) scores n-gram overlap between a candidate and a reference text; CodeBLEU extends this for code by adding three more signals on top of plain n-gram match: weighted n-gram match (keyword tokens weighted more heavily than generic tokens), syntactic AST match (does the candidate's abstract syntax tree structurally resemble the reference's), and dataflow match (do variables get defined and used in a structurally similar sequence). The combined score is a weighted average of these four components, which makes it far more sensitive to code correctness than plain BLEU, since two functionally similar code snippets can have very different surface tokens (variable names, formatting) but similar AST/dataflow structure.

```python
# conceptual shape of a CodeBLEU-style score
score = (
    w1 * ngram_match(candidate, reference)
    + w2 * weighted_ngram_match(candidate, reference)
    + w3 * ast_match(candidate, reference)
    + w4 * dataflow_match(candidate, reference)
)
```

**2. Dataflow match, standalone.** Dataflow match specifically checks whether the sequence of variable definitions and uses lines up between candidate and reference - it's one of CodeBLEU's four components but is also useful on its own as a signal when code style differs but logical structure should match (e.g., grading whether a generated function reads and writes state in the same order as a reference solution, independent of variable naming).

**3. N-gram similarity.** The simplest of the metrics: break both texts into n-grams (sequences of n consecutive tokens) and measure overlap (via precision, recall, or an F-score like ROUGE). It's cheap, fast, and reasonable as a first-pass filter, but it's purely surface-level - it doesn't understand meaning, so paraphrases score low and near-duplicates with trivial differences score artificially high.

```python
def ngram_overlap(candidate, reference, n=2):
    def ngrams(tokens, n):
        return set(tuple(tokens[i:i+n]) for i in range(len(tokens) - n + 1))
    cand_ngrams, ref_ngrams = ngrams(candidate.split(), n), ngrams(reference.split(), n)
    overlap = cand_ngrams & ref_ngrams
    return len(overlap) / max(len(ref_ngrams), 1)
```

**4. Human-eval rubrics.** A rubric is a checklist of specific, usually binary or small-scale criteria a human (or an LLM judge, per the judge file) checks an output against, rather than a single holistic "rate 1-5" score. Rubrics are more reliable than holistic ratings because they force raters to evaluate the same specific things rather than letting personal taste or halo effects dominate a single number - this is the same principle behind the judge council's per-criterion voting in the LLM-as-judge file.

**5. Why blend multiple metrics instead of picking one.** Each metric has a different blind spot: n-gram similarity rewards surface overlap but misses semantically equivalent rewrites; CodeBLEU's AST/dataflow components catch structural correctness that surface metrics miss but can still be fooled by structurally similar but logically wrong code; human-eval rubrics catch things no automated metric can (does this actually solve the user's real intent) but are slow and expensive. Blending them - as EvalAgentFlow does - gives a composite signal where no single metric's blind spot dominates the final score, and large disagreements between metrics (high n-gram overlap but low dataflow match, for instance) are themselves diagnostic.

**6. Taxonomy classification.** Before you can check inter-rater agreement or compute entropy meaningfully, every data point needs to be classified into a defined taxonomy (e.g., task type, domain, difficulty tier, failure mode category). A clear, mutually exclusive taxonomy is a prerequisite for every downstream quality check - an ambiguous taxonomy where two categories overlap will itself produce artificially low inter-rater agreement that looks like a labeling problem but is actually a taxonomy design problem.

**7. Entropy checks.** Entropy, in this context, measures how uncertain or spread-out a label distribution is for a given item or dataset slice. A high-entropy item - one where raters' answers are spread across many categories rather than concentrated on one - is a strong signal of an ambiguous example, a flawed taxonomy, or an item that genuinely needs expert adjudication rather than majority vote.

```python
import math

def entropy(label_counts):
    total = sum(label_counts.values())
    return -sum((c / total) * math.log2(c / total) for c in label_counts.values() if c > 0)

# entropy({"A": 5, "B": 0}) -> 0.0 (unanimous)
# entropy({"A": 3, "B": 2}) -> higher, indicates disagreement
```

**8. Inter-rater agreement.** When multiple annotators label the same data, you need a statistic that accounts for chance agreement - raw percent agreement overstates reliability when one label is much more common than others. Cohen's kappa (two raters) and Fleiss' kappa (three or more raters) are the standard choices:

```python
# conceptual: kappa = (observed_agreement - chance_agreement) / (1 - chance_agreement)
```

A kappa below roughly 0.4 usually means the taxonomy or instructions need revision before trusting the labels; a kappa approaching 1.0 means raters are highly consistent (which can also be a red flag if it's *too* perfect on genuinely subjective judgments - it may mean raters are anchoring on each other rather than labeling independently).

**9. NLP preprocessing and structured annotation.** Before any of the above checks are meaningful, raw text needs standard preprocessing (tokenization, normalization, deduplication, language detection) and the annotation itself needs a structured schema (not free-text notes) so that taxonomy labels, entropy, and kappa can all be computed programmatically rather than requiring manual re-reading of every annotation.

**10. Golden datasets and the Odoo labeling app.** A "golden dataset" is a small, high-confidence, carefully vetted set of examples used as ground truth to validate the rest of the pipeline (e.g., to sanity-check that a new judge model or a new metric correlates with known-correct answers before trusting it at scale). Building the labeling tool as an internal Odoo app (rather than a one-off spreadsheet) means the annotation workflow - assignment, structured fields matching the taxonomy, agreement tracking - is itself a maintained piece of software with proper access control and auditability, which matters when "golden" data is being used to validate everything downstream.

## Interview questions and answers

**Q1: Why blend CodeBLEU, n-gram similarity, dataflow match, and human-eval rubrics instead of using one metric?**
Each metric has a distinct blind spot - n-gram similarity is surface-level and misses semantically equivalent rewrites; CodeBLEU's structural components catch logical correctness that surface overlap misses but can still be fooled; human rubrics catch intent-level correctness no automated metric can but don't scale. Blending them means no single blind spot dominates the score, and disagreement between metrics is itself a useful diagnostic signal.

**Q2: What's the difference between CodeBLEU and plain BLEU, and why does it matter for code?**
Plain BLEU is pure n-gram overlap, which penalizes code that's logically identical but uses different variable names or formatting. CodeBLEU adds weighted n-gram match, AST structural match, and dataflow match on top, so code that's structurally and logically similar to the reference scores well even when surface tokens differ.

**Q3: Walk me through how you'd compute inter-rater agreement and what a low score tells you.**
Collect labels from at least two (ideally three or more) independent raters on the same items, then compute Cohen's or Fleiss' kappa rather than raw percent agreement, since raw agreement overstates reliability when one label dominates the distribution. A low kappa (roughly below 0.4) usually points to an ambiguous taxonomy or unclear annotation instructions rather than careless raters, and the fix is almost always to revise the taxonomy or guidelines, not to just relabel with the same instructions.

**Q4: What does entropy tell you that inter-rater agreement doesn't, or vice versa?**
Inter-rater agreement (kappa) is a dataset-level or rater-pair-level statistic; entropy can be computed per item, so it pinpoints exactly which examples are ambiguous rather than just telling you the dataset has a disagreement problem on average. In practice we'd use entropy to flag specific high-disagreement items for expert adjudication, and kappa to decide whether the taxonomy itself needs revision.

**Q5: Why is a clear taxonomy a prerequisite for meaningful quality checks?**
If categories in the taxonomy overlap or are ambiguous, raters will legitimately disagree not because the data is ambiguous but because the categories themselves are poorly defined - that shows up as low inter-rater agreement and high entropy that look like labeling problems but are actually taxonomy design problems, and no amount of relabeling with the same flawed taxonomy will fix it.

**Q6: What is a "golden dataset" and why build a dedicated app rather than a spreadsheet for labeling it?**
A golden dataset is a small, carefully vetted, high-confidence set of examples used as ground truth to validate the rest of the evaluation pipeline - for example, checking that a new judge model's verdicts correlate with known-correct answers before trusting it at scale. A dedicated app (we used Odoo) gives structured fields matching the taxonomy, access control, and built-in agreement tracking, which a spreadsheet can't enforce and which matters a lot given that golden data underwrites trust in everything downstream.

**Q7: How would you detect that a metric (say, n-gram similarity) is giving misleading scores on a particular domain?**
Compare it against the human-eval rubric scores on a sample where you trust the human judgment; if n-gram similarity and rubric scores diverge systematically on a domain or task type (e.g., n-gram scores paraphrased-but-correct answers low), that's a signal to down-weight or stop relying on that metric for that slice and lean more on the rubric or a structural metric like dataflow match.

**Q8: What NLP preprocessing steps matter before you can trust taxonomy and agreement numbers?**
Tokenization and normalization consistency (so the same text doesn't get split differently across pipeline runs), deduplication (duplicate items can silently inflate apparent agreement), and language detection/filtering if the dataset should be monolingual - skipping these can produce entropy and kappa numbers that look fine but are measuring noise rather than real rater behavior.

**Q9: How does EvalAgentFlow's pipeline structure (ingestion through export) relate to dataset quality work?**
The anomaly-detection stage in EvalAgentFlow is directly analogous to entropy/agreement checks on annotation data - both exist to flag data points that don't fit the expected pattern before they propagate into a final report or a trusted golden dataset; the insight-extraction stage is where blended-metric disagreement (like CodeBLEU vs. human rubric) would get surfaced in plain language for a report reader.

**Q10: If you had to pick one single metric to drop under time pressure, which would you drop and why?**
N-gram similarity, since it's the weakest signal on its own - it's the cheapest to compute and easiest to approximate informally, while CodeBLEU's structural components and human-eval rubrics each catch failure modes the other two can't. I'd keep n-gram similarity only as a cheap pre-filter, not as a scored component, if resources were constrained.

## Hands-on

1. **Implement entropy and kappa on toy label data.** Create a small dataset of 10 items each labeled by 3 raters from a 3-category taxonomy, compute per-item entropy, and compute an overall agreement statistic; identify which items have the highest entropy and inspect whether the taxonomy or the item itself looks ambiguous.
2. **Build a mini dataflow-match checker.** For two short Python functions that are logically equivalent but use different variable names, extract the sequence of (variable, define/use) events for each and compare the sequences structurally, ignoring the actual variable names.

## Read next

- [CodeBLEU paper (Microsoft Research)](https://arxiv.org/abs/2009.10297)
- [Fleiss' kappa reference (Wikipedia, as a starting point)](https://en.wikipedia.org/wiki/Fleiss%27_kappa)
- [Odoo documentation](https://www.odoo.com/documentation/)
- [../../course/04-ml-genai-agents/07-evaluation-and-harness.md](../../course/04-ml-genai-agents/07-evaluation-and-harness.md)
- [../../course/04-ml-genai-agents/10-interview-questions.md](../../course/04-ml-genai-agents/10-interview-questions.md)
