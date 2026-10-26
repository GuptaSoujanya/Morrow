"""Hirist: its pages, job links and the words on its Apply and Applied controls."""

from sites_bot.board import Board

BOARD = Board(
    name="hirist",
    label="Hirist",
    home="https://www.hirist.tech/jobfeed",
    profile_url="https://www.hirist.tech/myprofile",
    # My Profile shows roles, education and projects only; the summary, skills used, resume and
    # work preferences live on the registration steps.
    profile_pages=(
        "https://www.hirist.tech/registration/addWorkExperience",
        "https://www.hirist.tech/registration/addEducationalDetails",
        "https://www.hirist.tech/registration/addPersonalDetails",
        "https://www.hirist.tech/registration/addAdditionalDetails",
    ),
    feeds=("https://www.hirist.tech/jobfeed",),
    search="https://www.hirist.tech/search/{slug}",
    job_link=r"^https://www\.hirist\.tech/j/[a-z0-9-]+-\d+",
    job_id=r"-(\d+)/?$",
    apply=r"^(?:apply|apply now|quick apply)$",
    applied=r"^(?:applied|already applied)(?: on .{0,20})?$",
    page_title=r"^(?P<title>.+) - (?P<company>[^-|]+?) \| hirist\.tech$",
    applied_url=r"^https://www\.hirist\.tech/job/applied\b",
)
