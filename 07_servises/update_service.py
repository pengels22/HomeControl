from __future__ import annotations
import asyncio, json, os, shlex, subprocess
from importlib import import_module
protocol = import_module('07_servises.common.protocol')

class UpdateService:
    def __init__(self, host='0.0.0.0', port=6503, allow_execute=False):
        self.host=host; self.port=port; self.allow_execute=allow_execute
    async def handle(self, reader, writer):
        try:
            req = await protocol.read_frame(reader)
            payload=req.get('payload',{})
            if req.get('type')=='update_status':
                await protocol.write_frame(writer, {'type':'update_status','payload':{'ok':True}})
            elif req.get('type')=='update_run':
                if not self.allow_execute:
                    result={'ok':False,'dry_run':True,'reason':'execution disabled'}
                else:
                    cmd=payload.get('command',['sudo','apt-get','update'])
                    proc=await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
                    out,_=await proc.communicate(); result={'ok':proc.returncode==0,'returncode':proc.returncode,'output':out.decode(errors='replace')[-20000:]}
                await protocol.write_frame(writer, {'type':'update_result','payload':result,'request_id':req.get('request_id')})
        finally:
            writer.close(); await writer.wait_closed()
    async def run(self):
        server=await asyncio.start_server(self.handle,self.host,self.port)
        async with server: await server.serve_forever()

if __name__=='__main__':
    asyncio.run(UpdateService(allow_execute=os.getenv('HCM_ALLOW_UPDATES')=='1').run())
