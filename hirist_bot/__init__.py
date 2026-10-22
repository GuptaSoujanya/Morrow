"""Hirist bot: refresh the Hirist profile and apply to Hirist jobs.

    python3 -m hirist_bot [--limit 10] [--dry-run] [--update-profile]
    python3 -m hirist_bot.update_profile [--dry-run]

What is Hirist-specific (its pages, links and button words) is in board.py;
the collect / rank / apply / verify loop and the profile agent it runs are
shared with the other boards in sites_bot.platforms.
"""
