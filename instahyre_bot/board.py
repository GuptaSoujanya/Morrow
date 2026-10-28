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
    # The signed-in Opportunities feed is an Angular list: its cards open a modal and hold no job link,
    # but each row's scope carries the job with its public URL, title, location and keywords.
    cards_script=r"""
const out = [];
if (typeof angular === 'undefined') return out;
for (const row of document.querySelectorAll('.employer-row')) {
  let opp = null;
  try { const scope = angular.element(row).scope(); opp = scope && (scope.opp || (scope.$parent && scope.$parent.opp)); } catch (e) { continue; }
  const job = opp && opp.job;
  if (!job || !job.opportunity_url) continue;
  const company = job.hiring_company_name || (opp.employer || {}).company_name || '';
  const heading = (company ? company + ' - ' : '') + (job.title || '');
  const lines = [heading, job.locations || ''].concat(Array.isArray(job.keywords) ? job.keywords : []);
  out.push({href: location.origin + job.opportunity_url, heading: heading, lines: lines.filter(Boolean)});
}
return out;
""",
)
