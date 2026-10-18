from __future__ import annotations
import asyncio, json, os
from importlib import import_module
protocol = import_module('07_servises.common.protocol')
artifact_policy = import_module('07_servises.common.update_artifacts')

class UpdateService:
    def __init__(self, host='0.0.0.0', port=6503, allow_execute=False, target_module='RCM', hardware_revision='unknown', trusted_public_key=None, signature_verifier=None):
        self.host=host; self.port=port; self.allow_execute=allow_execute
        self.target_module = target_module
        self.hardware_revision = hardware_revision
        self.trusted_public_key = trusted_public_key
        self.signature_verifier = signature_verifier
    async def handle(self, reader, writer):
        try:
            req = await protocol.read_frame(reader)
            payload=req.get('payload',{})
            if req.get('type')=='update_status':
                await protocol.write_frame(writer, {'type':'update_status','payload':{'ok':True}})
            elif req.get('type')=='update_run':
                if 'command' in payload or 'argv' in payload:
                    result={'ok':False,'reason':'arbitrary commands are not supported'}
                elif not self.allow_execute:
                    result={'ok':False,'dry_run':True,'reason':'execution disabled'}
                else:
                    try:
                        artifact = artifact_policy.verify_artifact(
                            payload.get('artifact') or {}, target_module=self.target_module,
                            hardware_revision=self.hardware_revision,
                            trusted_public_key=self.trusted_public_key,
                            signature_verifier=self.signature_verifier,
                        )
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
    # A trusted key and target metadata are deployment configuration, not wire input.
    asyncio.run(UpdateService(allow_execute=os.getenv('HCM_ALLOW_UPDATES')=='1').run())
