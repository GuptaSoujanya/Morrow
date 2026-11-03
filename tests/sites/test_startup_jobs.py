"""Startup jobs from YC's job posts and HN's "Who is hiring?" thread, with no network.

A post is kept only when someone in India could take it, and goes to the
cold-email drafter when it gives a hiring address, else to the company-site
list when it gives an application link.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from common.models import Profile, Settings
from sites_bot import startup_jobs as sj

NOW = 1_800_000_000.0
DAY = 86400

THREAD_SEARCH = {"hits": [
    {"title": "Ask HN: Who wants to be hired? (November 2026)", "objectID": "1"},
    {"title": "Ask HN: Who is hiring? (November 2026)", "objectID": "500", "created_at_i": NOW - 2 * DAY},
]}

COMMENTS = [
    {"id": 501, "created_at_i": NOW - DAY,
     "text": "Acme AI | Senior Backend Engineer | Bangalore, India | Full-time<p>We build agents. "
             "Email <a href=\"mailto:jobs@acme.ai\">jobs@acme.ai</a> or see "
             "<a href=\"https://acme.ai\">https://acme.ai</a>"},
    {"id": 502, "created_at_i": NOW - DAY,
     "text": "Globex | ML Engineer | REMOTE (US only) | Series B<p>Apply: "
             "<a href=\"https://jobs.lever.co/globex/1\">https://jobs.lever.co/globex/1</a>"},
    {"id": 503, "created_at_i": NOW - DAY,
     "text": "Initech | Founding Engineer | Remote (worldwide) | Seed<p>Apply at "
             "<a href=\"https://jobs.ashbyhq.com/initech\">https://jobs.ashbyhq.com/initech</a>"},
    {"id": 504, "created_at_i": NOW - DAY,
     "text": "Hooli | Data Scientist | Onsite, San Francisco, CA<p>hello@hooli.com"},
    {"id": 505, "text": ""},
]

YC_ITEMS = {
    11: {"id": 11, "type": "job", "time": NOW - 3 * DAY,
         "title": "Stark (YC W24) Is Hiring a Founding Engineer (Remote)",
         "url": "https://www.ycombinator.com/companies/stark/jobs/1"},
    12: {"id": 12, "type": "job", "time": NOW - 3 * DAY, "dead": True, "title": "Dead (YC S20) Is Hiring"},
    13: {"id": 13, "type": "story", "title": "Not a job"},
}


def _fetch(url):
    if url.endswith("/jobstories.json"):
        return [11, 12, 13]
    if "/item/" in url:
        return YC_ITEMS[int(url.rsplit("/", 1)[1].split(".")[0])]
    if "search_by_date" in url:
        return THREAD_SEARCH
    if url.endswith("/items/500"):
        return {"id": 500, "children": COMMENTS}
    raise AssertionError("unexpected fetch %s" % url)


def _profile():
    return Profile(current_location="Bengaluru", preferred_locations=["Pune"], skills=["Python"])


def test_yc_titles_give_company_batch_and_role():
    assert sj.parse_yc_title("Stark (YC W24) Is Hiring a Founding Engineer") == ("Stark", "YC W24", "Founding Engineer")
    assert sj.parse_yc_title("Wayne Corp is hiring for Backend Engineers") == ("Wayne Corp", "", "Backend Engineers")
    assert sj.parse_yc_title("Just a title")[0] == "Just a title"


def test_yc_jobs_skip_dead_posts_and_stories():
    posts = sj.yc_jobs(_fetch, NOW)
    assert [p.job.job_id for p in posts] == ["yc:11"]
    job = posts[0].job
    assert (job.company, job.title, job.source) == ("Stark", "Founding Engineer", "yc:jobs")
    assert job.posted_days_ago == 3.0 and "YC W24" in job.tags and "remote" in job.tags
    assert posts[0].apply_url == "https://www.ycombinator.com/companies/stark/jobs/1"


def test_hn_posts_are_kept_only_when_open_to_india():
    posts = {p.job.job_id: p for p in sj.hn_jobs(_profile(), _fetch, NOW)}
    assert set(posts) == {"hn:501", "hn:503"}  # US-only remote and San Francisco onsite are dropped
    acme = posts["hn:501"]
    assert acme.job.company == "Acme AI"
    assert acme.job.title == "Senior Backend Engineer"
    assert acme.job.source.startswith("hn:whoishiring:")
    assert acme.hiring_email == "jobs@acme.ai"
    assert acme.website == "https://acme.ai"
    assert "jobs@acme.ai" not in acme.job.description  # the ranking model never sees addresses
    assert posts["hn:503"].apply_url == "https://jobs.ashbyhq.com/initech"


def test_location_rules():
    places = sj.home_places(_profile())
    assert sj.open_to_india("X | Engineer | Pune", places)
    assert sj.open_to_india("X | Engineer | Remote (India, APAC)", places)
    assert sj.open_to_india("X | Engineer | Remote", places)
    assert not sj.open_to_india("X | Engineer | Remote (US/Canada)", places)
    assert not sj.open_to_india("X | Engineer | Berlin, Germany | Onsite", places)
    assert not sj.open_to_india("X | Engineer | Remote, Europe only", places)


def test_contacts_are_labelled_and_ordered_for_applying():
    found = sj.contacts("write to jane@x.io, founders@x.io, careers@x.io, noreply@x.io or logo@x.png")
    assert [(c.email, c.kind) for c in found] == [
        ("careers@x.io", "hiring"), ("founders@x.io", "founders"), ("jane@x.io", "person")]


def test_one_failing_source_does_not_cost_the_other():
    def half(url):
        if "algolia" in url:
            raise OSError("down")
        return _fetch(url)

    assert [p.job.job_id for p in sj.collect(_profile(), half, NOW)] == ["yc:11"]
