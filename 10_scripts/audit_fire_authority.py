#!/usr/bin/env python3
"""Inventory every requested safety/fire search occurrence in versioned source."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = '09_documentation/FIRE_AUTHORITY_OCCURRENCES.tsv'
TERMS = ['fire', 'fire_alarm', 'fire_alarm_s', 'fire_alarm_P', 'life_safety', 'SafetyController', 'safety_inputs']
CLASSES = {
    '00_Heartbeat': 'Conflict/Heartbeat supervision and independent input support',
    '01_HCM': 'HCM authority/API/UI',
    '02_SIM': 'SIM commanded safety/local safe-off only',
    '03_LCM': 'LCM commanded safety/local safe-off only',
    '04_RCM': 'RCM commanded safety/local safe-off only',
    '05_PNL': 'PNL interface only',
    '06_config': 'Configuration/manifests/deployment (component in path)',
    '07_servises': 'Shared arbitration/input primitives and operational services',
    '08_database': 'Persistence/schema; no independent authority',
    '09_documentation': 'Documentation; historical material is not runtime authority',
    '10_scripts': 'Operational/test/preview tooling; no independent authority',
    '11_tests': 'Software test coverage',
    '12_hardware_tests': 'Explicitly gated hardware test coverage',
}


def main():
    paths = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT).decode().split('\0')
    rows = ['path\tline\tcomponent/classification\tterm:count (case-insensitive, overlapping search terms)']
    for name in sorted(set(paths)):
        if not name or name == OUTPUT:
            continue
        try:
            lines = (ROOT / name).read_text().splitlines()
        except (UnicodeError, IsADirectoryError):
            continue
        category = CLASSES.get(name.split('/')[0], 'Repository policy/build/support documentation')
        for lineno, line in enumerate(lines, 1):
            counts = [(term, len(re.findall(re.escape(term), line, re.I))) for term in TERMS]
            found = ','.join('{}:{}'.format(term, count) for term, count in counts if count)
            if found:
                rows.append('{}\t{}\t{}\t{}'.format(name, lineno, category, found))
    (ROOT / OUTPUT).write_text('\n'.join(rows) + '\n')
    print('{} matching lines inventoried'.format(len(rows) - 1))


if __name__ == '__main__':
    main()
