"""Enable or disable only the two schedules owned by this project."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import subprocess
import sys

SCHEDULES = {
    'profile': ('com.naukri-bot.profile-update', 'install_profile_updater.sh'),
    'linkedin': ('com.naukri-bot.linkedin-post', 'install_linkedin_poster.sh'),
}


def change_schedule(schedule, mode, run=subprocess.run, uid=None):
    if schedule not in SCHEDULES or mode not in ('enable', 'disable'):
        raise ValueError('Choose profile or linkedin, and enable or disable.')
    if sys.platform != 'darwin':
        raise ValueError('These schedules require macOS launchd.')
    label, installer = SCHEDULES[schedule]
    target = f'gui/{os.getuid() if uid is None else uid}/{label}'
    if mode == 'disable':
        # Persist disabled state, retaining the plist so no unrelated file is deleted.
        run(['/bin/launchctl', 'disable', target], check=True)
        result = run(['/bin/launchctl', 'bootout', target], capture_output=True, text=True)
        if result.returncode:
            # A schedule which wasn't loaded is already stopped. Other failures must surface.
            probe = run(['/bin/launchctl', 'print', target], capture_output=True, text=True)
            if probe.returncode == 0:
                raise RuntimeError('Future launches are disabled, but the loaded job could not be stopped. Check schedule status.')
        print(f'{schedule.title()} schedule disabled. Manual dashboard runs are still available.')
    else:
        run(['/bin/launchctl', 'enable', target], check=True)
        run(['/bin/zsh', str(Path(__file__).resolve().parent.parent / 'scripts' / installer)], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('schedule', choices=SCHEDULES)
    parser.add_argument('mode', choices=('enable', 'disable'))
    args = parser.parse_args()
    try:
        change_schedule(args.schedule, args.mode)
    except (ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
