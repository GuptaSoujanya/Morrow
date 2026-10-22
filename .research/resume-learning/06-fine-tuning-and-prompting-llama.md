# Fine-Tuning and Prompting (LLaMA)

## What it is

Fine-tuning adapts a pretrained model's weights to a specific task, domain, or behavior using a curated dataset of examples, as opposed to prompting, which shapes model behavior purely through the input text at inference time without changing any weights. In practice, a fine-tuning *program* - the kind delivered to an AI data platform as a data/training product rather than a single model checkpoint - is mostly a data and evaluation problem: the actual training run is often a small fraction of the effort compared to writing the domain prompts that generate training examples and the rubrics that determine whether a fine-tuned model's outputs are actually better.

## How you used it

The resume states you **wrote the domain prompts and evaluation rubrics for a Meta LLaMA 4 Maverick fine-tuning program delivered to a leading AI data platform**. This sits alongside the broader model-evaluation work (LangChain benchmarking across providers, dataset-quality ownership) and the skills list, which includes **prompt engineering** explicitly. In this kind of program, you are not training the model yourself in most cases - the AI data platform or its customer runs the actual fine-tuning job - but you are producing the two artifacts that determine what the model learns and how its success is measured: the **domain prompts** (the task instructions and examples used to elicit the kind of input/output pairs the fine-tune should learn from, or used at inference time to steer the base/fine-tuned model) and the **evaluation rubrics** (the checklist criteria, directly connected to the rubric-driven grading described in the LLM-as-judge and metrics files, used to judge whether the fine-tuned model's outputs meet the target behavior).

## Core concepts

**1. Fine-tuning vs. prompting - when each is the right tool.** Prompting is fast to iterate, requires no training infrastructure, and works well when the base model already "knows" the behavior you want but needs to be steered toward it. Fine-tuning is the right tool when you need the behavior to be reliable without a long prompt every time (shorter inference-time cost), when you need a style or format baked in across thousands of varied inputs, or when few-shot examples in the prompt alone can't reliably teach the pattern. A well-run fine-tuning program usually starts by trying to get the target behavior via prompting first - if prompting can't get there even with good examples, that's a strong signal fine-tuning is needed, and the same prompts become the seed for generating training data.

**2. Domain prompts as training-data generators.** In a fine-tuning program for a specific domain (finance, e-commerce, healthcare - the same domains that show up in the LangChain benchmarking work), domain prompts are often used to *generate* candidate training examples: a prompt instructs a strong model to produce a realistic input/output pair for the target domain and task, which is then reviewed, corrected, and folded into the training set. Writing these prompts well means being specific about the domain's actual edge cases (ambiguous financial terminology, product-catalog inconsistencies, healthcare caveats) rather than generic instructions, since generic prompts produce generic - and often unrepresentative - training data.

```python
DOMAIN_PROMPT_TEMPLATE = """
You are generating a training example for a {domain} assistant.
Produce a realistic user request and an ideal response that:
- uses domain-correct terminology for {domain}
- handles the following edge case: {edge_case}
- follows this response format: {format_spec}

Return as JSON: {{"input": ..., "ideal_output": ...}}
"""
```

**3. Rubrics as the bridge between training and evaluation.** The same rubric criteria used to judge whether a generated training example is "ideal" should be reusable, with minimal adaptation, as the evaluation rubric for the fine-tuned model's outputs later - otherwise you're training toward one definition of success and evaluating against another. This is the same per-criterion rubric structure used by the LLM-as-judge council: binary or small-scale checkable criteria, not a single holistic score.

**4. Instruction tuning and the shape of training data.** LLaMA-family instruction fine-tuning typically uses a chat/instruction format (system/user/assistant turns), and the domain prompts need to produce data in exactly that shape:

```python
{
  "messages": [
    {"role": "system", "content": "You are a healthcare documentation assistant..."},
    {"role": "user", "content": "<generated domain input>"},
    {"role": "assistant", "content": "<ideal output, rubric-checked>"}
  ]
}
```

**5. Why rubric quality matters more than volume at this stage.** A fine-tuning dataset built from mediocre rubrics will consistently teach the mediocre behavior at scale - unlike a single bad prompt at inference time, a flawed rubric baked into thousands of training examples reinforces the flaw across the whole fine-tune. This is why "wrote the domain prompts and evaluation rubrics" is itself a deliverable, not a side task: the rubric is effectively the specification for what "good" means for this model.

**6. Evaluating the fine-tuned model.** After training, the same (or a held-out variant of the) rubric is applied to the fine-tuned model's outputs on a fresh set of domain prompts it hasn't seen, ideally scored by the same kind of multi-rater/multi-judge process described in the metrics and LLM-as-judge files, so the evaluation isn't just "did it memorize the training examples" but "does it generalize the target behavior to new inputs in the domain."

**7. Prompt engineering as a standalone discipline.** Beyond fine-tuning-specific prompts, general prompt engineering - system prompt structure, few-shot example selection, explicit output-format constraints, chain-of-thought scaffolding where appropriate - is the skill that makes every other piece of this work (judge prompts, domain-prompt generation, benchmarking across providers) reliable. A recurring failure mode across all of it is under-specifying the output format and then having to post-hoc parse free text; explicit structured-output instructions (and where supported, actual schema-constrained generation) remove an entire class of downstream parsing bugs.

**8. Model-specific considerations for LLaMA 4 Maverick.** Open-weight models like the LLaMA family are commonly chosen for fine-tuning programs specifically because the resulting weights can be owned, hosted, and further adapted by the customer, unlike a closed API-only model. Prompting and rubric-writing for an open-weight target model also needs awareness of that model's particular quirks (context length, instruction-following strictness, tendency toward certain formatting habits) rather than assuming behavior observed on a closed frontier model transfers directly.

## Interview questions and answers

**Q1: What exactly did you deliver on the LLaMA 4 Maverick fine-tuning program?**
I wrote the domain prompts used to generate and steer training examples, and the evaluation rubrics used to judge whether those examples - and later the fine-tuned model's outputs - met the target behavior for the program's domains. I didn't run the training job itself; the value I added was in specifying, precisely, what "correct" looked like for this domain, both as generation instructions and as checkable criteria.

**Q2: How do you decide whether a problem needs fine-tuning or just better prompting?**
Try to achieve the target behavior through prompting first, including good few-shot examples; if the base model's quality is inconsistent across many varied inputs even with strong prompting, or if you need the behavior reliably without paying the inference-time cost of a long prompt every call, that's when fine-tuning earns its cost. The prompting attempt isn't wasted even if you move to fine-tuning - it typically becomes the seed for generating training data.

**Q3: Why should the rubric used to generate training data and the rubric used to evaluate the final model be the same (or closely related)?**
If they diverge, you're training toward one definition of "good" and evaluating against another, which can make a model look like it failed when it actually learned exactly what it was trained to do - just not what you're now testing for. Keeping them aligned makes the evaluation an honest check of whether the model generalized the intended behavior.

**Q4: What's a concrete risk of a poorly written domain prompt used to generate fine-tuning data?**
A generic prompt produces generic, unrepresentative examples - missing the domain's actual edge cases (ambiguous terminology, inconsistent formats, caveats specific to the domain) - and because fine-tuning bakes patterns in across thousands of examples, that gap gets reinforced at scale rather than showing up as one bad response you can catch and ignore.

**Q5: How would you catch a rubric that's systematically wrong before it poisons a training set?**
Run the rubric against a small, carefully hand-reviewed golden set first (the same golden-dataset concept used for dataset-quality work) and check whether rubric-approved examples actually look good to an expert reviewer; large disagreement between rubric scoring and expert judgment on the golden set is the signal to revise the rubric before generating data at scale.

**Q6: What's the difference between instruction tuning and raw next-token fine-tuning, in terms of what your prompts need to look like?**
Instruction tuning trains on structured conversational turns (system/user/assistant), so domain prompts need to produce data already shaped as that message format with a clear instruction and an ideal response; raw continuation fine-tuning would just need coherent domain text without that conversational structure, and the two approaches aren't interchangeable in how you'd design the generation prompts.

**Q7: Why might a company choose an open-weight model like LLaMA for a fine-tuning program instead of fine-tuning a closed API model?**
Open-weight models let the customer own and host the resulting weights, adapt them further without depending on a provider's API or fine-tuning offering, and avoid per-token costs tied to someone else's infrastructure - important for a data platform delivering a reusable asset to its own customers rather than a one-off API integration.

**Q8: How do you evaluate whether a fine-tuned model has actually generalized versus just memorized training examples?**
Score it on a held-out set of domain prompts it never saw during training, using the same rubric criteria, and compare its rubric coverage against its performance on training-adjacent examples; a model that scores well on held-out prompts but was never exposed to those specific inputs is evidence of generalization rather than memorization.

**Q9: What's a prompt-engineering mistake you see often, and how do you avoid it?**
Under-specifying the output format and relying on post-hoc text parsing to extract structure, which produces brittle downstream code and silent failures when the model's phrasing shifts slightly. The fix is to be explicit about the exact output schema in the prompt itself, and use structured-output or schema-constrained generation where the model/provider supports it.

**Q10: How does the work on this fine-tuning program connect to the LLM-as-judge and metrics work elsewhere on your resume?**
The rubric-writing skill is the same muscle: defining specific, checkable, per-criterion standards rather than a single holistic judgment. The fine-tuning rubrics feed the same kind of multi-rater or multi-judge scoring process used in the evaluation harness, just applied to "is this a good training example" and later "did the fine-tuned model learn the intended behavior" instead of "did this agent pass this benchmark task."

## Hands-on

1. **Write a domain-prompt template.** Pick a narrow domain (e.g., customer-support ticket triage) and write a generation prompt that produces a realistic input/output pair handling at least one explicit edge case, output as structured JSON matching an instruction-tuning message format.
2. **Draft a rubric for that same domain prompt's output**, with 5 specific, binary, checkable criteria (not a 1-5 holistic score), and manually apply it to three example outputs you write by hand, noting where criteria are ambiguous enough that two reasonable people might disagree.

## Read next

- [Meta LLaMA model documentation](https://www.llama.com/docs/)
- [OpenAI fine-tuning guide (for comparison on instruction-tuned data format)](https://platform.openai.com/docs/guides/fine-tuning)
- [Anthropic prompt engineering guide](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/overview)
- [../../course/04-ml-genai-agents/04-prompt-engineering.md](../../course/04-ml-genai-agents/04-prompt-engineering.md)
- [../../course/04-ml-genai-agents/08-fine-tuning-and-llmops.md](../../course/04-ml-genai-agents/08-fine-tuning-and-llmops.md)
