from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from importlib import import_module
from typing import Any

from . import db
from .registry import registry

protocol = import_module('07_servises.common.protocol')
rmc_firmware = import_module('07_servises.common.rmc_firmware')
log = logging.getLogger(__name__)


class UpdateOrchestrator:
    """One-module-at-a-time staged updater.

    The firewall hook is dry-run by default. Site-specific Zyxel/nftables integration
    can replace the hook without changing updater sequencing.
    """

    def __init__(self, hook: str = '07_servises/firewall_update_hook.sh', update_port: int = 6503):
        self.hook = Path(hook)
        self.update_port = update_port
        self._lock = asyncio.Lock()

    async def _firewall(self, action: str, ip: str) -> None:
        proc = await asyncio.create_subprocess_exec(str(self.hook), action, ip)
        rc = await proc.wait()
        if rc != 0:
            raise RuntimeError(f'firewall hook failed ({action} {ip}) rc={rc}')

    async def _request_update(self, ip: str, command: list[str] | None = None) -> dict:
        reader, writer = await asyncio.open_connection(ip, self.update_port)
        try:
            await protocol.write_frame(writer, {
                'type': 'update_run',
                'payload': {'command': command or ['sudo', 'apt-get', 'update']},
            })
            return (await protocol.read_frame(reader)).get('payload', {})
        finally:
            writer.close()
            await writer.wait_closed()

    async def update_module(self, hostname: str, command: list[str] | None = None, return_timeout_s: int = 180) -> dict:
        async with self._lock:
            async with db.acquire() as conn:
                row = await conn.fetchrow('SELECT module_uuid, ip_address FROM modules WHERE hostname=$1', hostname)
            if not row:
                raise KeyError(hostname)
            module_uuid, ip = str(row['module_uuid']), str(row['ip_address'])
            await self._firewall('open', ip)
            try:
                result = await self._request_update(ip, command)
                if not result.get('ok') and not result.get('dry_run'):
                    raise RuntimeError(f'update failed: {result}')
                deadline = asyncio.get_running_loop().time() + return_timeout_s
                while asyncio.get_running_loop().time() < deadline:
                    conn = registry.connections.get(module_uuid)
                    if conn and conn.last_heartbeat:
                        return {'ok': True, 'module': hostname, 'update': result, 'verified': True}
                    await asyncio.sleep(2)
                raise TimeoutError(f'{hostname} did not return heartbeat after update')
            finally:
                await self._firewall('close', ip)

    async def update_rmc_via_sim(
        self,
        *,
        target_rmc_id: str,
        sim_hostname: str,
        can_interface: str,
        node_id: int,
        firmware_image: bytes,
        firmware_version: str,
        hardware_revision: str = 'RMC-NANO-ATMEGA328P',
        timeout_s: float = 120.0,
    ) -> dict[str, Any]:
        async with self._lock:
            package = rmc_firmware.make_package(
                image=firmware_image,
                firmware_version=firmware_version,
                hardware_revision=hardware_revision,
            )
            async with db.acquire() as conn:
                sim_row = await conn.fetchrow('SELECT id FROM modules WHERE hostname=$1 AND module_type=$2', sim_hostname, 'SIM')
                if not sim_row:
                    raise KeyError(sim_hostname)
                release_row = await conn.fetchrow('''
                    INSERT INTO firmware_releases(
                        target_module, hardware_revision, firmware_version, package_version,
                        image_length, image_sha256, image_crc32, build_id, package
                    )
                    VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb)
                    ON CONFLICT(target_module, hardware_revision, firmware_version)
                    DO UPDATE SET package=EXCLUDED.package, image_sha256=EXCLUDED.image_sha256, image_crc32=EXCLUDED.image_crc32
                    RETURNING id
                ''',
                    'RMC',
                    hardware_revision,
                    firmware_version,
                    int(package['package_version']),
                    int(package['image_length']),
                    package['image_sha256'],
                    package.get('image_crc32'),
                    package.get('build_id'),
                    json.dumps(package),
                )
                await conn.execute('''
                    INSERT INTO rmc_firmware_updates(
                        session_id, target_rmc_id, sim_module_id, can_interface, node_id,
                        firmware_release_id, state, progress_pct, details
                    )
                    VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb)
                ''',
                    package['session_id'],
                    target_rmc_id,
                    sim_row['id'],
                    can_interface,
                    node_id,
                    release_row['id'],
                    'SENDING_TO_SIM',
                    0,
                    json.dumps({'hcm_state': 'SENDING_TO_SIM'}),
                )
            result = await registry.command_by_hostname(
                sim_hostname,
                {
                    'op': 'rmc_firmware_update',
                    'target': {
                        'rmc_id': target_rmc_id,
                        'node_id': node_id,
                        'can_interface': can_interface,
                    },
                    'package': package,
                },
                timeout=timeout_s,
            )
            if not result.get('ok'):
                async with db.acquire() as conn:
                    await conn.execute('''
                        UPDATE rmc_firmware_updates
                        SET state=$2, error=$3, details=$4::jsonb, updated_at=now()
                        WHERE session_id=$1
                    ''', package['session_id'], 'FAILED', str(result.get('error', 'SIM update failed')), json.dumps({'sim_result': result}))
                return {
                    'ok': False,
                    'state': 'FAILED',
                    'target_rmc_id': target_rmc_id,
                    'sim_hostname': sim_hostname,
                    'result': result,
                }
            reported = result.get('reported_firmware_version')
            state = 'COMPLETE' if reported == firmware_version else 'FAILED'
            async with db.acquire() as conn:
                await conn.execute('''
                    UPDATE rmc_firmware_updates
                    SET state=$2, progress_pct=$3, reported_firmware_version=$4,
                        error=$5, details=$6::jsonb, updated_at=now(), completed_at=now()
                    WHERE session_id=$1
                ''',
                    package['session_id'],
                    state,
                    100 if state == 'COMPLETE' else int(result.get('session', {}).get('progress_pct', 0)),
                    reported,
                    None if state == 'COMPLETE' else 'VERSION_MISMATCH',
                    json.dumps({'sim_result': result}),
                )
            return {
                'ok': state == 'COMPLETE',
                'state': state,
                'target_rmc_id': target_rmc_id,
                'sim_hostname': sim_hostname,
                'can_interface': can_interface,
                'node_id': node_id,
                'firmware_version': firmware_version,
                'reported_firmware_version': reported,
                'session': result.get('session'),
            }

updater = UpdateOrchestrator()
