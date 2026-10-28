"""Cutshort: its pages, job links and the words on its Apply and Applied controls."""

from sites_bot.board import Board

BOARD = Board(
    name="cutshort",
    label="Cutshort",
    home="https://cutshort.io/jobs/datascience-jobs",
    profile_url="https://cutshort.io/profile",
    # Cutshort's keyword search gave the same nine jobs for every keyword; its category pages are the feed.
    feeds=("https://cutshort.io/jobs/datascience-jobs", "https://cutshort.io/jobs/backend-developer-jobs",
           "https://cutshort.io/jobs/frontend-developer-jobs", "https://cutshort.io/jobs/fullstack-developer-jobs",
           "https://cutshort.io/jobs/python-jobs", "https://cutshort.io/jobs/python-jobs-in-pune",
           "https://cutshort.io/jobs/python-jobs-in-indore", "https://cutshort.io/jobs/backend-developer-jobs-in-pune",
           "https://cutshort.io/jobs/fullstack-developer-jobs-in-pune"),
    search="",
    job_link=r"^https://cutshort\.io/job/[A-Za-z0-9-]+-[A-Za-z0-9]{8}$",
    job_id=r"-([A-Za-z0-9]{8})/?$",
    # Only the posting's own button: the related jobs below it each have an "Apply now".
    apply=r"^apply to this job$",
    applied=r"^(?:applied|application sent|already applied)!?(?: on .{0,20})?$",
    company_first=False,
    page_title=r"^(?P<company>.+?) is hiring (?P<title>.+?) job in .+\| Cutshort$",
    # "Apply to this job" leads to /profile/all-jobs?jobid=..., where "Apply now" opens the form.
    second_apply=r"^apply now$",
)
