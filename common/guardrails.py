"""Companies the bot must never apply to or write to, the current employer first.

Every route that submits an application or drafts an email checks here before
it acts: the ranking callers drop these postings before the LLM sees them, and
each apply function refuses them again before it opens a page, so a posting
that reaches a form through a retry file or a hand-picked list is still caught.
"""
import logging
import re
from typing import Any, Iterable, List, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Words that say nothing about which company it is, so "Ethara AI" and
# "Ethara AI Private Limited" are the same employer.
_NOISE = frozenset(
    "ai ltd limited pvt private inc llc llp plc corp corporation co company"
    " technologies technology tech labs lab solutions services software systems"
    " group india the".split()
)
# A single core word this short ("co", "it") would match everything.
_MIN_CORE_CHARS = 3
# Words that turn an employer's name into one of its products: "Microsoft Azure", "Amazon Web
# Services", "Google Cloud", "Meta Llama". A posting at another company that uses the product is
# not the employer's. "office" and "team" are left out: "our Microsoft office" is the employer.
_PRODUCT_WORDS = frozenset(
    "azure dynamics copilot fabric excel sql 365 power powerbi windows visual"
    " web aws sagemaker bedrock redshift dynamodb lambda alexa"
    " cloud gcp bigquery vertex firebase gemini analytics ads workspace maps android flutter"
    " llama pytorch react graph"
    " database db apex fusion erp ebs weblogic netsuite peoplesoft java"
    " watson db2 sap hana s4hana".split()
)


def protected_companies(profile: Any) -> List[str]:
    """The current employer, then anything listed under never_apply_to."""
    extra = getattr(profile, "extra_facts", None) or {}
    names = [extra.get("current_company")]
    listed = extra.get("never_apply_to")
    names.extend(listed if isinstance(listed, (list, tuple)) else [listed])
    seen = []  # type: List[str]
    for name in names:
        text = " ".join(str(name or "").split())
        if text and text.casefold() not in (s.casefold() for s in seen):
            seen.append(text)
    return seen


def _words(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", (text or "").casefold())


def _core(name: str) -> Tuple[str, ...]:
    words = _words(name)
    core = tuple(word for word in words if word not in _NOISE)
    return core or tuple(words)


def _contains_sequence(haystack: List[str], needle: Tuple[str, ...]) -> bool:
    if not needle or len(needle) > len(haystack):
        return False
    size = len(needle)
    return any(tuple(haystack[i:i + size]) == needle for i in range(len(haystack) - size + 1))


def _names_employer(words: List[str], core: Tuple[str, ...]) -> bool:
    """Whether the text names the employer itself: some mention of `core` is not a product name.

    A possessive is read through ("Google's Cloud"), and one product mention does not hide a
    later plain one ("built on Microsoft Azure; Microsoft is hiring").
    """
    size = len(core)
    for start in range(len(words) - size + 1):
        if tuple(words[start:start + size]) != core:
            continue
        after = words[start + size:start + size + 2]
        if after[:1] == ["s"]:
            after = after[1:]
        if not after or after[0] not in _PRODUCT_WORDS:
            return True
    return False


def _labels(url: str) -> List[str]:
    """Host labels and the first path segments: ethara.ai, careers.ethara.ai, lever.co/ethara."""
    if not url:
        return []
    if "@" in url and "://" not in url:
        parsed_host, path = url.rpartition("@")[2], ""
    else:
        parsed = urlparse(url if "://" in url else "https://" + url)
        parsed_host, path = parsed.netloc, parsed.path
    labels = [part for part in parsed_host.casefold().split(".") if part]
    labels += [part for part in re.split(r"[/?#]", path.casefold())[:3] if part]
    return labels


def own_company(profile: Any, company: str = "", url: str = "", email: str = "", text: str = "") -> str:
    """The protected company this job, address or page belongs to, else ''.

    A name matches when its core words appear in order in the company field, or
    in the text other than as one of its products ("Microsoft Azure", "Amazon Web
    Services"); a URL or address matches when a domain or path label is the name
    run together (ethara.ai, lever.co/etharaai) or spells it out with hyphens
    (naukri.com/job-listings-engineer-ethara-ai-gurugram).
    """
    for name in protected_companies(profile):
        core = _core(name)
        if not core or len("".join(core)) < _MIN_CORE_CHARS:
            continue
        joined = ("".join(core), "".join(_words(name)))
        if _contains_sequence(_words(company), core) or _names_employer(_words(text), core):
            return name
        for address in (url, email):
            labels = _labels(address)
            if any(label.replace("-", "") in joined for label in labels):
                return name
            if _contains_sequence([w for label in labels for w in label.split("-")], core):
                return name
    return ""


def guard_job(profile: Any, job: Any) -> str:
    """The protected company a posting is for, else ''."""
    return own_company(
        profile,
        company=getattr(job, "company", "") or "",
        url=getattr(job, "url", "") or "",
        text=getattr(job, "description", "") or "",
    )


def refusal(name: str) -> str:
    return "guardrail: %s is your current employer, so this is never applied to or written to" % name


def drop_own_company(jobs: Iterable[Any], profile: Any, source: str = "") -> Tuple[List[Any], int]:
    """Postings from the current employer taken out before ranking, with how many went."""
    kept = []  # type: List[Any]
    dropped = []  # type: List[Tuple[str, Any]]
    for job in jobs:
        name = guard_job(profile, job)
        if name:
            dropped.append((name, job))
        else:
            kept.append(job)
    if dropped:
        shown = "; ".join(
            "%s @ %s" % (job.title or "<no title>", job.company or name) for name, job in dropped[:5]
        )
        logger.warning(
            "%s: guardrail dropped %d posting(s) from your current employer %s, never applied to: %s%s",
            source or "Ranking",
            len(dropped),
            ", ".join(sorted({name for name, _ in dropped})),
            shown,
            " ..." if len(dropped) > 5 else "",
        )
    return kept, len(dropped)
