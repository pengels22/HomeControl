#!/usr/bin/env python3
"""Small authenticated WebRTC signaling relay for the Sonic tablets."""
import asyncio
import hmac
import json
import os
from collections import defaultdict

import websockets

TOKEN = os.environ.get("SONIC_FIRE7_TOKEN", "")
rooms = defaultdict(dict)


def allowed(path, headers):
    supplied = headers.get("Authorization", "")
    return bool(TOKEN) and hmac.compare_digest(supplied, "Bearer " + TOKEN)


async def handler(ws):
    query = ws.request.path.split("?", 1)[-1] if "?" in ws.request.path else ""
    values = dict(item.split("=", 1) for item in query.split("&") if "=" in item)
    tablet = values.get("tablet", "")
    target = values.get("target", "")
    if not tablet or not target or not allowed(ws.request.path, ws.request.headers):
        print("intercom rejected", tablet, target, flush=True)
        await ws.close(code=1008, reason="unauthorized")
        return
    print("intercom connected", tablet, target, flush=True)
    key = "-".join(sorted((tablet, target)))
    rooms[key][tablet] = ws
    try:
        async for raw in ws:
            message = json.loads(raw)
            peer = rooms[key].get(target)
            if peer and peer.open:
                await peer.send(json.dumps({"from": tablet, **message}, separators=(",", ":")))
    finally:
        print("intercom disconnected", tablet, target, flush=True)
        if rooms[key].get(tablet) is ws:
            del rooms[key][tablet]
        if not rooms[key]:
            del rooms[key]


async def main():
    async with websockets.serve(handler, "0.0.0.0", 8768, max_size=65536):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
