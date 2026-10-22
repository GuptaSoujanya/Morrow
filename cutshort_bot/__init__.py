"""Cutshort bot: refresh the Cutshort profile and apply to Cutshort jobs.

    python3 -m cutshort_bot [--limit 10] [--dry-run] [--update-profile]
    python3 -m cutshort_bot.update_profile [--dry-run]

What is Cutshort-specific (its pages, links and button words) is in board.py;
the collect / rank / apply / verify loop and the profile agent it runs are
shared with the other boards in sites_bot.platforms.
"""
