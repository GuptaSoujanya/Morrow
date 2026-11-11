"""Why is nobody calling? A read-only audit of the whole application funnel.

`python3 -m diagnose` reads every local record (the Naukri ledger and its
backups, the company-site ledger, saved answers, profile, resume, employer
replies, cold-email contacts, the Cutshort questionnaire journal), then — unless
told not to — the Gmail account over IMAP and each job board's own
"applications / recruiter actions / inbox" pages in the saved browser profiles.
It never applies, never sends, never clicks a form. It writes
user/reports/<date>/diagnostics.md and diagnostics.json with ranked root
causes and the concrete change each one needs (env value, code, resume line,
answer, skill).
"""
