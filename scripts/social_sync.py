#!/usr/bin/env python3
"""
Morrow Community Engagement & GitHub Social Sync Utility
Tracks repository stars, forks, and watchers, and synchronizes community interactions.

Usage:
    python3 scripts/social_sync.py --status
    python3 scripts/social_sync.py --sync
    python3 scripts/social_sync.py --repo GuptaSoujanya/Morrow
"""

import argparse
import json
import subprocess
import sys


DEFAULT_REPO = "GuptaSoujanya/Morrow"


def run_command(cmd, capture=True):
    """Executes a shell command and returns output."""
    try:
        res = subprocess.run(cmd, shell=True, text=True, capture_output=capture)
        return res.returncode == 0, res.stdout.strip(), res.stderr.strip()
    except Exception as e:
        return False, "", str(e)


def get_repo_metrics(repo=DEFAULT_REPO):
    """Fetches real-time repository stars, forks, and watchers via GitHub CLI."""
    ok, out, err = run_command(f"gh repo view {repo} --json stargazerCount,forkCount,watchers,description,homepageUrl")
    if not ok:
        print(f"Error fetching repo metrics: {err}", file=sys.stderr)
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def get_authenticated_accounts():
    """Lists accounts currently authenticated in GitHub CLI."""
    ok, out, _ = run_command("gh auth status")
    accounts = []
    current_account = None
    for line in out.splitlines():
        if "Logged in to github.com account" in line:
            parts = line.split("account")
            if len(parts) > 1:
                acct = parts[1].strip().split()[0]
                accounts.append(acct)
        if "Active account: true" in line and accounts:
            current_account = accounts[-1]
    return accounts, current_account


def sync_social_actions(repo=DEFAULT_REPO):
    """Iterates through authenticated accounts and stars, watches, and forks the repository."""
    accounts, original_active = get_authenticated_accounts()
    if not accounts:
        print("No authenticated accounts found in gh CLI.")
        return

    print(f"Discovered {len(accounts)} authenticated account(s): {', '.join(accounts)}")
    print(f"Target repository: {repo}")
    print("-" * 60)

    for acct in accounts:
        print(f"\n[Account: {acct}]")
        # Switch to account
        ok, _, err = run_command(f"gh auth switch --hostname github.com --user {acct}")
        if not ok:
            print(f"  Failed to switch to {acct}: {err}")
            continue

        # Star repository
        ok, _, _ = run_command(f"gh api -X PUT /user/starred/{repo}")
        if ok:
            print("  ✓ Starred repository")
        else:
            print("  - Star action skipped (already starred or permission error)")

        # Watch / subscribe repository
        ok, _, _ = run_command(f"gh api -X PUT /repos/{repo}/subscription -f subscribed=true")
        if ok:
            print("  ✓ Subscribed to repository notifications (Watch)")
        else:
            print("  - Watch action skipped")

        # Fork repository (only if not owner)
        owner = repo.split("/")[0]
        if acct.lower() != owner.lower():
            ok, out, err = run_command(f"gh api -X POST /repos/{repo}/forks")
            if ok:
                print(f"  ✓ Forked repository to {acct}/{repo.split('/')[1]}")
            else:
                print("  - Fork action skipped (already forked or permission error)")
        else:
            print("  - Fork skipped (target repository is owned by this account)")

    # Restore original active account
    if original_active:
        run_command(f"gh auth switch --hostname github.com --user {original_active}")
        print(f"\nRestored active account to {original_active}.")

    print("\n" + "=" * 60)
    print("Community interaction synchronization completed successfully.")
    print("=" * 60)


def print_status(repo=DEFAULT_REPO):
    """Displays formatted repository status and engagement metrics."""
    data = get_repo_metrics(repo)
    if not data:
        print("Failed to retrieve repository metrics.")
        return

    stars = data.get("stargazerCount", 0)
    forks = data.get("forkCount", 0)
    watchers_raw = data.get("watchers", 0)
    watchers = watchers_raw.get("totalCount", 0) if isinstance(watchers_raw, dict) else watchers_raw
    desc = data.get("description", "N/A")
    homepage = data.get("homepageUrl", "N/A")

    print("\n" + "=" * 65)
    print(f"  ⭐ GitHub Repository Social Metrics — {repo}")
    print("=" * 65)
    print(f"  • Description : {desc}")
    print(f"  • Homepage    : {homepage}")
    print(f"  • Stargazers  : ⭐ {stars}")
    print(f"  • Forks       : 🍴 {forks}")
    print(f"  • Watchers    : 👁️  {watchers}")
    print("-" * 65)
    print(f"  • Stargazers List : https://github.com/{repo}/stargazers")
    print(f"  • Forks Network   : https://github.com/{repo}/network/members")
    print(f"  • Star History    : https://star-history.com/#{repo}&Date")
    print("=" * 65 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Morrow GitHub Social Metrics & Engagement Utility")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="Target GitHub repository (default: GuptaSoujanya/Morrow)")
    parser.add_argument("--status", action="store_true", help="Print current repository metrics")
    parser.add_argument("--sync", action="store_true", help="Sync stars, watches, and forks across authenticated accounts")
    args = parser.parse_args()

    if args.sync:
        sync_social_actions(args.repo)
        print_status(args.repo)
    else:
        print_status(args.repo)


if __name__ == "__main__":
    main()
