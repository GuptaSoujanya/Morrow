"""Set the chosen local AI provider without replacing credentials or saved inputs."""
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from common.shared_files import atomic_write_text, locked_file
from common.connections import chrome_binary


def configure(root, provider):
    if provider not in ('claude', 'kiro'):
        raise ValueError('Choose claude or kiro.')
    target = Path(root) / '.env'
    if target.is_symlink():
        raise ValueError('The settings file must be a regular file, not a symbolic link.')
    with locked_file(target):
        original = target.read_text() if target.exists() else '# Local Morrow settings; do not commit.\nDRY_RUN=true\nANSWER_MODE=auto\n'
        lines = [line for line in original.splitlines() if not re.match(r'^\s*(?:export\s+)?(?:LLM_BACKEND|PIPELINE_AI_CLI)\s*=', line)]
        from dotenv import dotenv_values
        current = dotenv_values(target) if target.exists() else {}
        binary = chrome_binary()
        if binary and not current.get('CHROME_BINARY'):
            lines.append("CHROME_BINARY='" + binary.replace("'", "\\'") + "'")
        driver = shutil.which('chromedriver')
        if driver and not current.get('CHROMEDRIVER'):
            lines.append("CHROMEDRIVER='" + driver.replace("'", "\\'") + "'")
        lines.extend(['LLM_BACKEND=' + provider + '-cli', 'PIPELINE_AI_CLI=' + provider])
        atomic_write_text(target, '\n'.join(lines) + '\n')
        target.chmod(0o600)


if __name__ == '__main__':
    configure(ROOT, sys.argv[1])
