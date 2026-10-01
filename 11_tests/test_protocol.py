import asyncio
import pytest
from importlib import import_module
p=import_module('07_servises.common.protocol')

@pytest.mark.asyncio
async def test_frame_roundtrip():
    got=[]
    async def handler(r,w):
        got.append(await p.read_frame(r)); w.close(); await w.wait_closed()
    server=await asyncio.start_server(handler,'127.0.0.1',0)
    port=server.sockets[0].getsockname()[1]
    r,w=await asyncio.open_connection('127.0.0.1',port)
    await p.write_frame(w,{'type':'heartbeat','payload':{'x':1}})
    w.close(); await w.wait_closed(); await asyncio.sleep(.05)
    server.close(); await server.wait_closed()
    assert got[0]['payload']['x']==1
