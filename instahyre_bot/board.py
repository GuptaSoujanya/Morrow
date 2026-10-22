"""Instahyre: its pages, job links and the words on its Apply and Applied controls."""

from sites_bot.board import Board

BOARD = Board(
    name="instahyre",
    label="Instahyre",
    home="https://www.instahyre.com/candidate/opportunities/",
    profile_url="https://www.instahyre.com/candidate/profile/",
    feeds=("https://www.instahyre.com/candidate/opportunities/?matching=true",),
    search="https://www.instahyre.com/{slug}-jobs/",
    job_link=r"^https://www\.instahyre\.com/job-\d+-",
    job_id=r"/job-(\d+)-",
    apply=r"^(?:apply|apply now|i'?m interested|interested)$",
    # The Apply button turns into "Application sent!" the moment it is clicked.
    applied=r"^(?:applied|application sent|interest sent)!?(?: on .{0,20})?$",
    signed_out=r"^(?:log ?in|sign ?in)$",
    page_title=r"^(?P<title>.+?) job at (?P<company>.+?) - Instahyre$",
)
