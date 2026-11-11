"""How much of Naukri's daily allowance is left, for people and for the scheduler.

    python -m naukri_bot.quota            one line for a person
    python -m naukri_bot.quota --json     for scripts/apply_scheduler.sh
    python -m naukri_bot.quota --slots 10 when the next 10 slots free, not the next one

Counts every attempt the ledger marked quota_consumed in the last 24 hours: verified
applications and questionnaires Naukri had already accepted the click for. The cap is
DAILY_QUOTA, or Naukri's own 50 when DAILY_QUOTA=0.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from common import config
from common import ledger as ledger_module

NAUKRI_ACCOUNT_QUOTA = 50


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--slots", type=int, default=1, help="how many free slots to wait for (default 1)")
    parser.add_argument("--json", action="store_true", help="print one JSON object")
    parser.add_argument("--env", metavar="PATH", help="path to a .env file")
    args = parser.parse_args(argv)

    settings = config.load_settings(args.env)
    cap = settings.daily_quota if settings.daily_quota > 0 else NAUKRI_ACCOUNT_QUOTA
    ledger = ledger_module.open_ledger(settings)
    try:
        used = ledger.quota_used()
        frees_at = ledger.quota_frees_at(cap, max(1, args.slots))
    finally:
        ledger.close()
    remaining = max(0, cap - used)
    try:
        zone = ZoneInfo(settings.run_timezone or "Asia/Kolkata")
    except (ValueError, ZoneInfoNotFoundError):
        zone = timezone.utc
    local = frees_at.astimezone(zone) if frees_at else None

    if args.json:
        print(json.dumps({
            "used": used,
            "cap": cap,
            "remaining": remaining,
            "slots": max(1, args.slots),
            "frees_at": frees_at.isoformat() if frees_at else None,
            "frees_at_local": local.strftime("%Y-%m-%d %H:%M %Z") if local else None,
            "frees_in_s": max(0, int((frees_at - datetime.now(timezone.utc)).total_seconds())) if frees_at else 0,
        }))
        return 0
    if frees_at is None:
        print("Naukri slots: %d of %d used in the last 24h, %d free now." % (used, cap, remaining))
    else:
        print("Naukri slots: %d of %d used in the last 24h, %d free; %d free at %s." % (
            used, cap, remaining, max(1, args.slots), local.strftime("%H:%M %Z on %a %d %b")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
