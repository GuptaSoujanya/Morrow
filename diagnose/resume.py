"""Does the resume say what the applied-for postings ask for, in words a screener reads?

The job-fit and ATS checks follow the public rubrics in art2url/career-agent-skills
(job-fit-analyzer, ats-resume-checker; MIT): keyword coverage against the real
postings, quantified bullets, no "toy project" wording, a headline that names
the job. Everything is computed from the postings this person actually applied
to, not a generic keyword list.
"""

import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

from common.models import Settings

#: Terms screeners and ATS filters match on. Each entry: display name, regex.
TERMS = [(name, re.compile(r"(?<![\w+#])%s(?![\w+#])" % pattern, re.IGNORECASE)) for name, pattern in (
    ("Python", r"python"), ("Java", r"java"), ("JavaScript", r"javascript|\bjs\b"), ("TypeScript", r"typescript"),
    ("Go", r"\bgolang\b|\bgo\b(?= lang| developer|,)"), ("C++", r"c\+\+"), ("C#", r"c#"), ("Node.js", r"node\.?js|nodejs"),
    ("React", r"react(\.js)?"), ("Next.js", r"next\.?js"), ("Angular", r"angular"), ("Vue", r"vue(\.js)?"),
    ("Django", r"django"), ("Flask", r"flask"), ("FastAPI", r"fastapi"), ("Spring Boot", r"spring ?boot|spring"),
    ("Express", r"express(\.js)?"), ("NestJS", r"nest\.?js"), ("GraphQL", r"graphql"), ("REST APIs", r"rest(ful)? apis?"),
    ("Microservices", r"micro-?services"), ("SQL", r"\bsql\b"), ("PostgreSQL", r"postgres(ql)?"), ("MySQL", r"mysql"),
    ("MongoDB", r"mongo(db)?"), ("Redis", r"redis"), ("Elasticsearch", r"elastic ?search"), ("Kafka", r"kafka"),
    ("RabbitMQ", r"rabbitmq"), ("Docker", r"docker"), ("Kubernetes", r"kubernetes|\bk8s\b"), ("AWS", r"\baws\b|amazon web services"),
    ("Azure", r"azure"), ("GCP", r"\bgcp\b|google cloud"), ("Terraform", r"terraform"), ("CI/CD", r"ci/cd|ci cd|jenkins|github actions"),
    ("Linux", r"linux"), ("Git", r"\bgit\b"), ("Machine Learning", r"machine learning|\bml\b"), ("Deep Learning", r"deep learning"),
    ("PyTorch", r"pytorch|torch"), ("TensorFlow", r"tensorflow|\btf\b"), ("Scikit-learn", r"scikit-?learn|sklearn"),
    ("Pandas", r"pandas"), ("NumPy", r"numpy"), ("NLP", r"\bnlp\b|natural language"), ("Computer Vision", r"computer vision|opencv"),
    ("LLM", r"\bllms?\b|large language model"), ("RAG", r"\brag\b|retrieval[- ]augmented"), ("LangChain", r"langchain"),
    ("LangGraph", r"langgraph"), ("Vector DB", r"vector (database|db|store)|pinecone|weaviate|chroma|faiss|qdrant|milvus"),
    ("OpenAI API", r"openai|gpt-?4|chatgpt api"), ("Anthropic", r"anthropic|claude"), ("Hugging Face", r"hugging ?face|transformers"),
    ("Prompt Engineering", r"prompt engineering"), ("Agents", r"\bagentic\b|ai agents?|multi-agent"), ("MLOps", r"mlops"),
    ("Data Pipelines", r"data pipelines?|\betl\b"), ("Spark", r"\bspark\b"), ("Airflow", r"airflow"),
    ("System Design", r"system design"), ("Data Structures", r"data structures|algorithms|\bdsa\b"),
    ("Unit Testing", r"unit test|pytest|jest|junit"), ("Agile", r"agile|scrum"), ("HTML/CSS", r"html|css"),
    ("Tailwind", r"tailwind"), ("WebSockets", r"websockets?"), ("gRPC", r"grpc"), ("OAuth", r"oauth|jwt"),
    ("Selenium", r"selenium|playwright"), ("Bash", r"\bbash\b|shell script"), ("Evaluation", r"\bevals?\b|evaluation"),
)]

WEAK_WORDS = re.compile(
    r"\b(mock|mocked|simulated|simulation|prototype|toy|dummy|sample|placeholder|local beta|beta|wip|"
    r"work in progress|proof of concept|poc|hobby|practice|tutorial|learning project|college project|academic)\b",
    re.IGNORECASE)
METRIC = re.compile(r"\d+(\.\d+)?\s*(%|x\b|ms\b|s\b|k\b|m\b|users|requests|rps|qps|hours|days|percent|\$|₹|lakh|crore|\+)",
                    re.IGNORECASE)
SENIOR_WORDS = re.compile(r"\b(senior|lead|architect|principal|staff|head of|manager)\b", re.IGNORECASE)


def resume_text(settings: Settings) -> str:
    from common.profile import extract_resume_text

    candidates = [settings.resume_path] if settings.resume_path else []
    folder = Path("user/resume")
    candidates += [str(p) for p in sorted(folder.glob("*.pdf"))] + [str(folder / "base.tex")]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            try:
                return extract_resume_text(candidate)
            except Exception:
                continue
    return ""


def _plain(text: str) -> str:
    text = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?", " ", text)  # LaTeX commands
    text = re.sub(r"[{}]", " ", text)
    return re.sub(r"\s+", " ", text)


def term_hits(text: str) -> Dict[str, int]:
    return {name: len(pattern.findall(text)) for name, pattern in TERMS if pattern.search(text)}


def analyse(settings: Settings, applications: List[Dict[str, Any]], profile: Dict[str, Any]) -> Dict[str, Any]:
    raw = resume_text(settings)
    text = _plain(raw)
    if not text.strip():
        return {"error": "No readable resume at RESUME_PATH or user/resume/."}
    resume_terms = term_hits(text)
    demand = Counter()
    descriptions = [record.get("description") or "" for record in applications
                    if record.get("status") in ("applied", "applied_platform", "applied_external")
                    and record.get("description")]
    for description in descriptions:
        for name in term_hits(description):
            demand[name] += 1
    total = len(descriptions)
    missing = [(name, count, round(count / total, 2)) for name, count in demand.most_common()
               if name not in resume_terms and count >= 3][:15]
    # A PDF comes out as a few very long lines, a .tex as one line per bullet;
    # sentences and bullet marks split both into the units a screener reads.
    bullets = [chunk.strip() for chunk in re.split(r"(?<=[.!?])\s+|\n+|•|\\item\b", text) if len(chunk.strip()) > 40]
    with_metric = [chunk for chunk in bullets if METRIC.search(chunk)]
    weak = sorted({match.group(0).lower() for match in WEAK_WORDS.finditer(text)})
    weak_lines = []
    for match in WEAK_WORDS.finditer(text):
        start = max(0, match.start() - 60)
        weak_lines.append("…" + text[start:match.end() + 60].strip() + "…")
        if len(weak_lines) >= 8:
            break
    headline_match = re.search(
        r"((Software|Full[- ]?Stack|Backend|Back-?end|Frontend|Front-?end|AI|ML|LLM|Data|Platform|Python|Web)"
        r"[\w /&,.+-]{0,40}?(Engineer|Developer|Scientist|Analyst)[^\n$|\\]{0,70})", text[:1500], re.IGNORECASE)
    headline = " ".join(headline_match.group(1).split()).strip(" ·-") if headline_match else ""
    words = len(text.split())
    return {
        "source_chars": len(raw),
        "words": words,
        "headline": headline,
        "headline_flags": [
            flag for flag, hit in (
                ("names a senior level", bool(SENIOR_WORDS.search(headline))),
                ("does not say 'Software Engineer' or 'Developer'", not re.search(r"software engineer|developer", headline, re.I)),
                ("longer than 70 characters", len(headline) > 70),
            ) if hit
        ],
        "terms_in_resume": sorted(resume_terms),
        "postings_analysed": total,
        "demand_top": demand.most_common(25),
        "missing_in_demand": missing,
        "coverage": round(sum(1 for name in demand if name in resume_terms) / len(demand), 2) if demand else None,
        "bullets": len(bullets),
        "bullets_with_metric": len(with_metric),
        "metric_share": round(len(with_metric) / len(bullets), 2) if bullets else None,
        "weak_words": weak,
        "weak_lines": weak_lines,
        "profile_skills_missing": sorted(
            skill for skill in (profile.get("skills") or []) if isinstance(skill, str)
            and not re.search(re.escape(skill), text, re.IGNORECASE))[:20],
    }
