#!/usr/bin/env python3
"""Explicit Jetson input-access setup; never reads or changes GPIO values.

Run --apply only during an authorized physical-input rollout. Wiring must be
confirmed separately; this script deliberately enables no connected contacts.
Compatible with the installed host Python 3.6.
"""
import argparse
import fcntl
import grp
import json
import os
from pathlib import Path
import struct
import subprocess

CONFIG = Path('/etc/hcm/safety-inputs.json')
CHIP = '/dev/gpiochip0'
GROUP = 'hcm-gpio'


def verify_chip():
    fd = os.open(CHIP, os.O_RDONLY)
    try:
        chip = bytearray(68)
        fcntl.ioctl(fd, 0x8044b401, chip, True)
        name, label, count = struct.unpack('=32s32sI', chip)
        if label.rstrip(b'\0') != b'tegra-gpio' or count != 224:
            raise RuntimeError('unexpected Jetson GPIO chip')
        for line, expected in ((159, b'I2S0_DIN'), (158, b'I2S0_DOUT')):
            info = bytearray(struct.pack('=II32s32s', line, 0, b'', b''))
            fcntl.ioctl(fd, 0xc048b402, info, True)
            _, flags, name, consumer = struct.unpack('=II32s32s', info)
            if name.rstrip(b'\0') != expected or flags & 2:
                raise RuntimeError('GPIO mapping mismatch or output line: {}'.format(line))
    finally:
        os.close(fd)


def apply():
    verify_chip()
    try:
        group = grp.getgrnam(GROUP)
    except KeyError:
        subprocess.check_call(['groupadd', '--system', GROUP])
        group = grp.getgrnam(GROUP)
    rule = ('SUBSYSTEM=="gpio", KERNEL=="gpiochip0", KERNELS=="2200000.gpio", '
            'GROUP="hcm-gpio", MODE="0640"\n')
    Path('/etc/udev/rules.d/70-hcm-fire-inputs.rules').write_text(rule)
    subprocess.check_call(['udevadm', 'control', '--reload-rules'])
    os.chown(CHIP, 0, group.gr_gid)
    os.chmod(CHIP, 0o640)
    if not CONFIG.exists():
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps({'gpio_abi': 'v1', 'connected_inputs': []}, indent=2)+'\n')
        os.chmod(str(CONFIG), 0o644)
    print('Verified gpiochip0: FIRE=159 AC=158; dedicated group {}; wiring preserved'.format(group.gr_gid))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if args.apply:
        apply()
    else:
        verify_chip()
        print('Jetson GPIO mapping verified (metadata only)')
