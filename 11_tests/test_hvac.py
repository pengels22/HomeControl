import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'01_HCM'))
import pytest
from hcm.hvac import HVACController, RoomReading, Mode

@pytest.mark.asyncio
async def test_cool_sequence(monkeypatch):
    events=[]
    async def out(n,v): events.append((n,v))
    async def damper(r,v): events.append((r.room,v))
    h=HVACController(out,damper)
    h.DAMPER_LEAD_S=0; h.FAN_LEAD_S=0; h.RESTART_LOCKOUT_S=0
    h.state.mode=Mode.COOL; h.state.setpoint_f=70
    h.rooms['Office']=RoomReading('Office',74,True,False)
    h.rooms['Kitchen']=RoomReading('Kitchen',74,True,True,'Kitchen Damper')
    await h.evaluate()
    assert ('FAN',True) in events and ('COOL',True) in events
