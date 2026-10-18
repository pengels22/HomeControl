from __future__ import annotations
import asyncio, base64, hashlib, hmac, json, os, sqlite3, time
from pathlib import Path
from importlib import import_module
protocol = import_module('07_servises.common.protocol')
artifact_policy = import_module('07_servises.common.update_artifacts')

class UpdateService:
    def __init__(self, host='0.0.0.0', port=6503, allow_execute=False, target_module=None, hardware_revision=None, trusted_public_key=None, signature_verifier=None, request_secret=None, staging_root=Path('/var/lib/homecontrol/updates/staging'), clock=None, replay_store_path=None):
        self.host=host; self.port=port; self.allow_execute=allow_execute
        self.target_module = target_module
        self.hardware_revision = hardware_revision
        self.trusted_public_key = trusted_public_key
        self.signature_verifier = signature_verifier
        self.request_secret = request_secret
        self.staging_root = Path(staging_root)
        self.clock = clock or time.time
        self._accepted_operations = {}
        self.replay_store_path = Path(replay_store_path) if replay_store_path else None

    def _replay_connection(self):
        if not self.replay_store_path:
            return None
        self.replay_store_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.replay_store_path)
        conn.execute('CREATE TABLE IF NOT EXISTS accepted_update_operations(operation_id TEXT PRIMARY KEY, accepted_at REAL NOT NULL, artifact_id TEXT NOT NULL)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_accepted_update_operations_time ON accepted_update_operations(accepted_at)')
        return conn

    @classmethod
    def from_environment(cls):
        enabled = os.getenv('HCM_UPDATE_EXECUTION_ENABLED', 'false').lower() in {'1', 'true', 'yes'}
        target = os.getenv('HCM_UPDATE_TARGET_MODULE')
        revision = os.getenv('HCM_UPDATE_HARDWARE_REVISION')
        key_path = os.getenv('HCM_UPDATE_PUBLIC_KEY_FILE')
        secret_path = os.getenv('HCM_UPDATE_REQUEST_SECRET_FILE')
        if enabled and (not target or not revision or not key_path or not secret_path):
            raise RuntimeError('enabled updater requires target module, hardware revision, public key, and request secret')
        public_key = cls._read_public_key(Path(key_path)) if key_path else None
        request_secret = Path(secret_path).read_bytes().strip() if secret_path else None
        if enabled and not request_secret:
            raise RuntimeError('enabled updater requires a request authentication secret')
        return cls(
            host=os.getenv('HCM_UPDATE_BIND', '127.0.0.1'),
            port=int(os.getenv('HCM_UPDATE_PORT', '6503')),
            allow_execute=enabled,
            target_module=target,
            hardware_revision=revision,
            trusted_public_key=public_key,
            request_secret=request_secret,
            staging_root=Path(os.getenv('HCM_UPDATE_STAGING_ROOT', '/var/lib/homecontrol/updates/staging')),
            replay_store_path=Path(os.getenv('HCM_UPDATE_REPLAY_STORE', '/var/lib/homecontrol/update-replay.sqlite3')),
        )

    @staticmethod
    def _read_public_key(path: Path) -> bytes:
        raw = path.read_bytes().strip()
        if len(raw) == 32:
            return raw
        try:
            decoded = bytes.fromhex(raw.decode('ascii'))
        except (ValueError, UnicodeDecodeError):
            try:
                decoded = base64.b64decode(raw, validate=True)
            except Exception as exc:
                raise RuntimeError('invalid Ed25519 public key encoding') from exc
        if len(decoded) != 32:
            raise RuntimeError('Ed25519 public key must be 32 bytes')
        return decoded

    def _authenticate_update_request(self, req: dict, payload: dict) -> tuple[str, str]:
        auth = req.get('auth') if isinstance(req.get('auth'), dict) else {}
        operation_id = str(auth.get('operation_id') or '')
        artifact_id = str(auth.get('artifact_id') or (payload.get('artifact') or {}).get('artifact_id') or '')
        timestamp = auth.get('timestamp')
        mac = str(auth.get('mac') or '')
        if not self.request_secret or not operation_id or not artifact_id or timestamp is None or not mac:
            raise ValueError('authenticated update request required')
        try:
            timestamp_f = float(timestamp)
        except (TypeError, ValueError) as exc:
            raise ValueError('invalid update request timestamp') from exc
        if abs(self.clock() - timestamp_f) > 300:
            raise ValueError('stale update request')
        canonical = json.dumps({'type': req.get('type'), 'payload': payload, 'request_id': req.get('request_id'), 'operation_id': operation_id, 'artifact_id': artifact_id, 'timestamp': timestamp_f}, sort_keys=True, separators=(',', ':')).encode()
        expected = hmac.new(self.request_secret, canonical, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, mac):
            raise ValueError('invalid update request authentication')
        now = self.clock()
        self._accepted_operations = {key: value for key, value in self._accepted_operations.items() if now - value < 600}
        durable_duplicate = False
        if self.replay_store_path:
            with self._replay_connection() as conn:
                conn.execute('DELETE FROM accepted_update_operations WHERE accepted_at < ?', (now - 600,))
                durable_duplicate = conn.execute(
                    'SELECT 1 FROM accepted_update_operations WHERE operation_id=?', (operation_id,)
                ).fetchone() is not None
        if operation_id in self._accepted_operations or durable_duplicate:
            raise ValueError('duplicate update operation')
        return operation_id, artifact_id

    def _record_operation(self, operation_id: str, artifact_id: str) -> None:
        now = self.clock()
        self._accepted_operations[operation_id] = now
        if self.replay_store_path:
            with self._replay_connection() as conn:
                conn.execute(
                    'INSERT INTO accepted_update_operations(operation_id, accepted_at, artifact_id) VALUES(?,?,?)',
                    (operation_id, now, artifact_id),
                )
    async def handle(self, reader, writer):
        try:
            req = await protocol.read_frame(reader)
            payload=req.get('payload',{})
            if req.get('type')=='update_status':
                await protocol.write_frame(writer, {'type':'update_status','payload':{'ok':True}})
            elif req.get('type')=='update_run':
                if 'command' in payload or 'argv' in payload:
                    result={'ok':False,'reason':'arbitrary commands are not supported'}
                else:
                    try:
                        operation_id, _ = self._authenticate_update_request(req, payload)
                        if not self.allow_execute:
                            result={'ok':False,'dry_run':True,'reason':'execution disabled'}
                        else:
                            artifact = artifact_policy.verify_artifact(
                                payload.get('artifact') or {}, target_module=self.target_module,
                                hardware_revision=self.hardware_revision,
                                trusted_public_key=self.trusted_public_key,
                                signature_verifier=self.signature_verifier,
                                staging_root=self.staging_root,
                            )
                            self._record_operation(operation_id, artifact.artifact_id)
                            executable = artifact_policy.INSTALLERS[(artifact.target_module, artifact.installer)]
                            proc=await asyncio.create_subprocess_exec(*executable, str(artifact.path), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
                            out,_=await proc.communicate(); result={'ok':proc.returncode==0,'returncode':proc.returncode,'artifact_id':artifact.artifact_id,'output':out.decode(errors='replace')[-20000:]}
                    except Exception as exc:
                        result={'ok':False,'reason':str(exc)}
                await protocol.write_frame(writer, {'type':'update_result','payload':result,'request_id':req.get('request_id')})
        finally:
            writer.close(); await writer.wait_closed()
    async def run(self):
        server=await asyncio.start_server(self.handle,self.host,self.port)
        async with server: await server.serve_forever()

if __name__=='__main__':
    asyncio.run(UpdateService.from_environment().run())
