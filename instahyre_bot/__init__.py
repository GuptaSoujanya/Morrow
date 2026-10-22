"""Instahyre bot: refresh the Instahyre profile and apply to Instahyre jobs.

    python3 -m instahyre_bot [--limit 10] [--dry-run] [--update-profile]
    python3 -m instahyre_bot.update_profile [--dry-run]

What is Instahyre-specific (its pages, links and button words) is in board.py;
the collect / rank / apply / verify loop and the profile agent it runs are
shared with the other boards in sites_bot.platforms.
"""
