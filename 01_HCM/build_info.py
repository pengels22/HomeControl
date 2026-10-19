"""Non-secret identity baked into the image, independent of .git and cloned env."""
import json
from pathlib import Path

BUILD_INFO_PATH = Path(__file__).with_name('build_info.json')


def build_info():
    if BUILD_INFO_PATH.exists():
        return json.loads(BUILD_INFO_PATH.read_text())
    return {'version': '0.1.0', 'git_sha': 'unknown', 'build_time': 'unknown'}
