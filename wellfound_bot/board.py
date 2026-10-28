"""Wellfound: its pages, job links and the words on its Apply and Applied controls."""

from sites_bot.board import Board

BOARD = Board(
    name="wellfound",
    label="Wellfound",
    home="https://wellfound.com/jobs",
    profile_url="https://wellfound.com/profile/edit",
    feeds=("https://wellfound.com/jobs",),
    search="https://wellfound.com/role/r/{slug}",
    search_page="https://wellfound.com/role/r/{slug}?page={page}",
    search_in_city="https://wellfound.com/role/l/{slug}/{city}?page={page}",
    job_link=r"^https://wellfound\.com/jobs/\d+-",
    job_id=r"/jobs/(\d+)-",
    apply=r"^(?:apply|apply now|send application)$",
    applied=r"^(?:applied|application sent)(?: on .{0,20})?$",
    signed_out=r"^(?:log ?in|sign ?in)$",
    company_first=False,
    page_title=r"^(?P<title>.+?) (?:at|@) (?P<company>[^•|]+?)(?: [•|].*)?$",
)
