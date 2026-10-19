"""Bake validated build metadata; invoked only while building the HCM image."""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sha = sys.argv[1]
if not re.fullmatch('[0-9a-f]{40}', sha):
    raise SystemExit('HCM_GIT_SHA build argument must be a full Git commit SHA')
Path('01_HCM/build_info.json').write_text(json.dumps({
    'version': '0.1.0', 'git_sha': sha,
    'build_time': datetime.now(timezone.utc).isoformat(),
}) + '\n')
