#!/usr/bin/env bash
# Install Morrow locally, connect an AI assistant, and open the dashboard.
set -euo pipefail
umask 077
MORROW_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$MORROW_ROOT"
export PATH="$MORROW_ROOT/.runtime/node/bin:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
provider=""; login=1; start=1; browser=1; check=0
usage() {
  cat <<'HELP'
Usage: bash setup.sh [--provider claude|kiro] [--skip-login] [--no-start] [--no-open] [--check]

Installs the dashboard and Python dependencies, guides AI sign-in, and starts
the local dashboard and bot API at http://127.0.0.1:8100.
Supported: macOS and Linux. Your saved profile and answers are kept on reruns.

--provider     Choose the AI assistant to install/configure.
--skip-login   Keep your existing AI login; do not open a sign-in flow.
--no-start     Install only. Later: morrow start
--no-open      Print the dashboard link without opening a browser.
--check        Check prerequisites only; do not install or start anything.
HELP
}
while [ "$#" -gt 0 ]; do
  case "$1" in
    --provider) [ "$#" -ge 2 ] || { usage; exit 2; }; provider=$2; shift ;;
    --skip-login) login=0 ;;
    --no-start) start=0 ;;
    --no-open) browser=0 ;;
    --check) check=1 ;;
    --help|-h) usage; exit 0 ;;
    *) usage; exit 2 ;;
  esac
  shift
done
case "$provider" in ''|claude|kiro) ;; *) echo 'Choose --provider claude or --provider kiro.' >&2; exit 2 ;; esac
case "$(uname -s)" in Darwin) platform=darwin ;; Linux) platform=linux ;; *) echo 'Use macOS or Linux for this local browser-automation setup.' >&2; exit 1 ;; esac
find_python() {
  for candidate in python3.12 python3.13 python3.14 python3.11 python3; do
    if command -v "$candidate" >/dev/null && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' 2>/dev/null; then
      python_bin=$(command -v "$candidate"); return 0
    fi
  done
  return 1
}
node_ok() { command -v node >/dev/null && node -e 'const [a,b]=process.versions.node.split(".").map(Number);process.exit(a>22||a===22&&b>=19?0:1)' 2>/dev/null; }
if [ "$check" -eq 1 ]; then
  failed=0
  for tool in git curl pdftotext; do
    if command -v "$tool" >/dev/null; then echo "Ready: $tool"; else echo "Missing: $tool"; failed=1; fi
  done
  if find_python; then echo "Ready: $python_bin"; else echo 'Missing: Python 3.11+'; failed=1; fi
  if node_ok; then echo 'Ready: Node.js 22.19+'; else echo 'Missing: Node.js 22.19+'; failed=1; fi
  if command -v claude >/dev/null || command -v kiro-cli >/dev/null; then echo 'Ready: AI assistant installed (sign-in checked when preparing answers)'; else echo 'Missing: Claude or Kiro CLI'; failed=1; fi
  exit "$failed"
fi
echo 'Morrow · local setup'
echo '1/5 · Checking system tools'
if ! find_python || ! command -v pdftotext >/dev/null || ! command -v git >/dev/null || ! command -v curl >/dev/null; then
  if [ "$platform" = darwin ]; then
    command -v brew >/dev/null || { echo 'Install Homebrew from https://brew.sh, then run bash setup.sh again.' >&2; exit 1; }
    brew install python@3.12 poppler git curl
  elif command -v apt-get >/dev/null; then
    sudo apt-get update
    sudo apt-get install -y python3 python3-venv poppler-utils git curl lsof ca-certificates
  elif command -v dnf >/dev/null; then
    sudo dnf install -y python3 python3-pip poppler-utils git curl lsof
  else
    echo 'Install Python 3.11+, git, curl and Poppler with your package manager, then run this script again.' >&2; exit 1
  fi
fi
find_python || { echo 'Python 3.11+ is required. Install Python 3.12, then run this script again.' >&2; exit 1; }
mkdir -p .runtime/downloads
if ! node_ok; then
  case "$(uname -m)" in x86_64) arch=x64 ;; arm64|aarch64) arch=arm64 ;; *) echo 'Install Node.js 22.19+ for your CPU, then rerun setup.' >&2; exit 1 ;; esac
  node_archive="node-v24.14.0-$platform-$arch.tar.gz"
  echo 'Installing Node.js inside this workspace…'
  curl -fL --retry 3 "https://nodejs.org/dist/v24.14.0/$node_archive" -o ".runtime/downloads/$node_archive"
  curl -fL --retry 3 https://nodejs.org/dist/v24.14.0/SHASUMS256.txt -o .runtime/downloads/node-SHASUMS256.txt
  "$python_bin" - "$node_archive" <<'PY'
import hashlib, pathlib, sys
folder = pathlib.Path('.runtime/downloads')
name = sys.argv[1]
expected = {line.split()[1]: line.split()[0] for line in (folder / 'node-SHASUMS256.txt').read_text().splitlines()}[name]
if hashlib.sha256((folder / name).read_bytes()).hexdigest() != expected:
    raise SystemExit('Node.js checksum failed. Run setup again to retry the download.')
PY
  mkdir -p .runtime/node
  tar -xzf ".runtime/downloads/$node_archive" -C .runtime/node --strip-components=1
fi
echo '2/5 · Installing the dashboard and bot dependencies'
if [ ! -f froned-dashbord/package.json ]; then
  git submodule update --init -- froned-dashbord
fi
# Personal inputs, memory, and research are local folders, never fetched repos.
mkdir -p user/inputs user/resume user/db user/logs user/reports user/worklists user/memory user/research user/browser
if [ ! -x venv/bin/python ]; then "$python_bin" -m venv venv; fi
venv/bin/python -m pip install --upgrade pip
venv/bin/python -m pip install --require-hashes -r requirements.lock
npm --prefix froned-dashbord ci
echo 'Checking the browser used by your job-site connections…'
if ! venv/bin/python -c 'from common.connections import chrome_binary; import sys; sys.exit(0 if chrome_binary() else 1)'; then
  if [ "$platform" = darwin ] && command -v brew >/dev/null; then
    brew install --cask google-chrome
  elif [ "$platform" = linux ] && command -v apt-get >/dev/null; then
    sudo apt-get install -y chromium chromium-driver
  elif [ "$platform" = linux ] && command -v dnf >/dev/null; then
    sudo dnf install -y chromium chromedriver
  else
    echo 'Install Google Chrome from https://www.google.com/chrome/, then run setup again.' >&2; exit 1
  fi
fi
venv/bin/python -c 'from common.connections import chrome_binary; import sys; sys.exit(0 if chrome_binary() else "Chrome/Chromium is unavailable. Install it, then retry setup.")'
echo '3/5 · Connecting your AI assistant'
if [ -z "$provider" ] && [ -f .env ]; then
  provider=$(venv/bin/python -c 'from dotenv import dotenv_values; print({"claude-cli":"claude","kiro-cli":"kiro"}.get(dotenv_values(".env").get("LLM_BACKEND"), ""))')
fi
if [ -z "$provider" ]; then
  if command -v claude >/dev/null; then provider=claude
  elif command -v kiro-cli >/dev/null; then provider=kiro
  elif [ -t 0 ]; then read -r -p 'Choose your AI assistant [claude/kiro, default claude]: ' provider; provider=${provider:-claude}
  else provider=claude; fi
fi
case "$provider" in
  claude) binary=claude; installer=https://claude.ai/install.sh ;;
  kiro) binary=kiro-cli; installer=https://cli.kiro.dev/install ;;
  *) echo 'Choose claude or kiro and run setup again.' >&2; exit 2 ;;
esac
if ! command -v "$binary" >/dev/null; then
  curl -fL --retry 3 "$installer" -o ".runtime/downloads/$provider-install.sh"
  bash ".runtime/downloads/$provider-install.sh"
fi
command -v "$binary" >/dev/null || { echo "Open a new terminal, then run bash setup.sh --provider $provider again." >&2; exit 1; }
if [ "$login" -eq 1 ]; then
  if [ "$provider" = claude ]; then
    if ! claude auth status >/dev/null 2>&1; then claude auth login; fi
  else
    if ! kiro-cli whoami >/dev/null 2>&1; then kiro-cli login; fi
  fi
fi
venv/bin/python scripts/setup_defaults.py "$provider"
# Install the `morrow` command (a symlink in ~/.local/bin) so `morrow start` works from any directory.
scripts/morrow install
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "Add ~/.local/bin to your PATH to use the morrow command, or run scripts/morrow start from this folder." ;; esac
echo '4/5 · Building your dashboard'
if [ "$start" -eq 0 ]; then npm --prefix froned-dashbord run build; fi
echo '5/5 · Opening your workspace'
if [ "$start" -eq 1 ]; then
  if [ -n "${MORROW_PORT:-}" ]; then scripts/morrow start --port "$MORROW_PORT"; else scripts/morrow start; fi
  if [ "$browser" -eq 1 ]; then
    if [ "$platform" = darwin ]; then open "http://127.0.0.1:${MORROW_PORT:-8100}/#/onboarding"
    elif command -v xdg-open >/dev/null; then xdg-open "http://127.0.0.1:${MORROW_PORT:-8100}/#/onboarding" >/dev/null 2>&1 || true; fi
  fi
else
  echo 'Installed. Start later with: morrow start'
fi
echo 'Finish the guided setup in your browser. Morrow will prepare answers.txt for you.'
