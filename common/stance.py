"""How every agent phrases an answer: in the employer's terms, in the candidate's favour, and true.

The bots used to answer like a database lookup: the saved fact, verbatim, whatever the posting
asked for. A recruiter reading "Others" for a location or a bare "No" where a qualified true
answer existed moved on. This module is the one place that says how an answer is chosen and
worded, and every prompt that answers an employer (the Naukri chatbot, board forms, the browser
agent, questionnaires, Gmail replies) includes it.
"""

import re
from typing import List

EMPLOYER_STANCE = """How to answer, so it reads the way this employer hopes and stays true:
- A question is about THIS role. Read what the posting asks for (skills, years, location, shift,
  work mode) before answering, and answer that.
- Lead with the candidate's facts that match what the posting asks, in the posting's own words for
  the same thing: their LLM evaluation work answers a question about "Generative AI", their FastAPI
  services answer "backend experience", their Gurugram base answers a Delhi NCR role.
- When more than one answer is true, give the one that fits the role best: the job's city when it is
  among their preferred locations, the option whose range holds their number, "Yes" to relocation,
  shifts or a work mode they have said they accept, the broader skill the posting names when their
  experience includes it.
- Never a bare "No" or "0" when a qualified true answer exists and the field takes text; with
  options, pick the true option that fits best.
- Never state what the facts do not make true: no rounded-up years, no skill they have not used, no
  city, notice period or salary they have not given. A false answer is caught at the first call and
  costs the offer, so the truth, well chosen and well worded, is the only answer that gets a call."""

_REQUIREMENT = re.compile(
    r"\b(must|should|required?|requirements?|mandatory|need(?:ed|s)?|experience|years?|yrs|skills?|"
    r"knowledge|proficien|hands[- ]on|strong|expertise|familiar|exposure|qualification|degree|"
    r"location|notice|shift|remote|hybrid|onsite|on-site|work from)\b", re.I)
_NOISE = re.compile(r"^(about (us|the company)|benefits?|perks|we offer|why join|equal opportunity)", re.I)
MAX_REQUIREMENT_CHARS = 1200


def requirements(description: str, limit: int = MAX_REQUIREMENT_CHARS) -> str:
    """The lines of a posting that say what the employer wants, one per line, within `limit` characters.

    Empty when the posting has none; the whole text is never passed on, so a chatbot prompt stays small.
    """
    lines: List[str] = []
    seen = set()
    for raw in re.split(r"[\n\r]+|(?<=[.;])\s+(?=[A-Z•\-*])", description or ""):
        line = " ".join(raw.replace("•", " ").split()).strip(" -*·")
        if len(line) < 12 or _NOISE.match(line) or not _REQUIREMENT.search(line):
            continue
        key = line.casefold()
        if key in seen:
            continue
        seen.add(key)
        lines.append(line[:200])
    text = ""
    for line in lines:
        if len(text) + len(line) + 1 > limit:
            break
        text = "%s\n%s" % (text, line) if text else line
    return text
