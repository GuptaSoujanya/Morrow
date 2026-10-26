"""The Board record: everything the shared board loop needs to know about one job board.

Each board has its own bot package (hirist_bot, instahyre_bot, cutshort_bot,
wellfound_bot) holding its Board in board.py; sites_bot.platforms is the loop
they all run.
"""

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class Board:
    name: str
    label: str
    home: str
    # Pages listing jobs picked for the signed-in profile, read before any search.
    feeds: Tuple[str, ...]
    # "{slug}" is the keyword in lower-case-hyphen form, "{query}" the URL-encoded keyword; "" = feeds only.
    search: str
    job_link: str
    job_id: str
    apply: str
    applied: str
    external: str = r"company (?:site|website)|apply on company|external"
    signed_out: str = r"^(?:log ?in|sign ?in|login / register|candidate login)$"
    # Card heading is "Company - Title".
    company_first: bool = True
    # The job page's <title>, with named groups "title" and "company" when the board puts both there.
    page_title: str = ""
    # The board's terms forbid automated use; it is skipped unless named on purpose.
    risky: bool = False
    # Address the board moves to once an application went through.
    applied_url: str = ""
    # A board whose Apply only opens its own job view, with a second Apply there.
    # The Applied marker then shows on that view, not on the public job page.
    second_apply: str = ""
    # The signed-in candidate's own profile page, where the morning profile update starts.
    profile_url: str = ""
    # Pages the same profile is spread over: a board that edits it as a form wizard keeps the About
    # text, skills and preferences on those steps, so the verifier reads them after profile_url.
    profile_pages: Tuple[str, ...] = ()
