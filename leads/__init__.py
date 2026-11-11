"""Leads: every recruiter message, questionnaire, assessment or reply that is waiting on the candidate.

The diagnosis found the funnel's real loss: recruiters answered on the job boards and in
Gmail and nobody read it. This package is the daily answer to that.

    inbox:<board>   leads.boards  reads one board's own inbox (Naukri NVites, Hirist chats,
                                  Instahyre inbox, Cutshort conversations, Wellfound messages),
                                  records each thread as a lead and lets the browser agent
                                  answer it from the saved facts.
    leads:mail      leads.mail    reads Gmail (All Mail and Spam) over IMAP, records each
                                  hiring-positive mail as a lead and replies to it.

Both write to one journal, user/inputs/leads.json (leads.store), which the funnel audit
(`python3 -m diagnose`) and the dashboard (/api/leads) read. A thread is answered once:
the journal holds its state and the facts fingerprint it was answered with.
"""
