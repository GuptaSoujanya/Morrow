"""Naukri auto-apply bot (rebuilt).

A resume-ranked, quota-aware Naukri application bot designed to run once per
morning with no human in the loop.

Design rules that every module in this package obeys:

* Nothing is reported as a success unless it was *verified*. Login, job
  application, and chatbot answer submission each have an explicit verification
  step; a click that did not raise is not proof of anything.
* The 50/day Naukri quota is only debited for applications that were confirmed
  to be Naukri-native. An "Apply on company site" redirect consumes zero quota
  and is never counted.
* Screening questions are answered only from facts the user supplied. If a fact
  is missing, the bot abstains and abandons that application rather than
  guessing. There is no fuzzy matching anywhere in this package.
* Ranking is ours, not Naukri's: candidates are scored against the user's own
  resume and freshness, never accepted in the order Naukri returns them.

The legacy scripts (``legacy/Naukri-Edge.py``, ``legacy/Naukri-Recommended.py``)
are kept untouched; this package does not import from them.
"""

__version__ = "2.0.0"

__all__ = ["__version__"]
