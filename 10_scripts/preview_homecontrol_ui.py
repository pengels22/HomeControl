#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import time
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "01_HCM" / "www"
PREVIEW_TOKEN = "homecontrol-preview-token"
PREVIEW_READONLY_TOKEN = "homecontrol-preview-readonly-token"
CHANNELS = [f"{bank}{channel}" for bank in ("A", "B", "C", "D") for channel in range(1, 9)]
LCM_LIGHT_CHANNELS = [f"A{channel}" for channel in range(1, 9)]
LCM_DIMMER_CHANNELS = [f"10-{channel}" for channel in range(1, 11)] + [f"HV-{channel}" for channel in range(1, 5)]
LCM_CHANNELS = LCM_LIGHT_CHANNELS + LCM_DIMMER_CHANNELS
SIM_ANALOG_CHANNELS = [f"AI-{channel}" for channel in range(1, 11)]


def _now() -> str:
    return "2026-10-13T00:00:00Z"


def _module(
    hostname: str,
    role: str,
    device_id: str,
    *,
    online: bool = True,
    simulation: bool = False,
    physical_outputs_enabled: bool = True,
) -> dict[str, Any]:
    return {
        "id": sum(ord(char) for char in hostname),
        "device_id": device_id,
        "module_uuid": None,
        "identity_interface": "preview",
        "module_type": "RCM" if role == "UNASSIGNED" else role,
        "hostname": hostname,
        "ip_address": "127.0.0.1",
        "heartbeat_ip": None,
        "online": online,
        "control_session_online": online,
        "supervision_state": "online" if online else "offline",
        "supervision_last_seen": _now() if online else None,
        "supervision_fresh_until": _now() if online else None,
        "last_seen": _now() if online else None,
        "software_version": "preview",
        "hardware_revision": "preview-fixture",
        "config_version": 1,
        "last_state": {
            "state": {
                "lab_role": role,
                "simulation": simulation,
                "physical_outputs_enabled": physical_outputs_enabled,
                "relays": {},
            }
        },
        "last_health": {"preview": True},
        "commissioned_at": _now(),
        "capabilities": _capabilities(role),
    }


def _capabilities(role: str) -> list[dict[str, Any]]:
    mapping = {
        "RCM": ["relay-32"],
        "LCM": ["lighting", "relay-8", "analog-out-10", "high-voltage-dimmer"],
        "SIM": ["rmc-can", "telemetry", "faults", "hexa-aio", "hexa-dio"],
        "UNASSIGNED": [],
    }
    return [
        {"capability": item, "details": {"preview": True}, "first_seen_at": _now(), "updated_at": _now()}
        for item in mapping.get(role, [])
    ]


class PreviewState:
    def __init__(self) -> None:
        self.modules = {
            "LAB1": _module(
                "LAB1",
                "UNASSIGNED",
                "2ccf675d3414",
                online=True,
                simulation=True,
                physical_outputs_enabled=False,
            ),
            "RCM1": _module("RCM1", "RCM", "48b02d87db10"),
            "RCM2": _module("RCM2", "RCM", "48b02d87db20"),
            "LCM1": _module("LCM1", "LCM", "48b02d87dc10"),
            "LCM2": _module("LCM2", "LCM", "48b02d87dc20"),
            "SIM1": _module("SIM1", "SIM", "48b02d87dd10"),
            "SIM2": _module("SIM2", "SIM", "48b02d87dd20"),
            "RCM3": _module("RCM3", "RCM", "48b02d87db30", online=False),
        }
        self.modules["LAB1"]["ip_address"] = None
        self.modules["RCM1"]["ip_address"] = "192.168.20.31"
        self.modules["RCM1"]["last_state"]["state"]["management"] = {"emergency_url": "http://192.168.20.31:8088/"}
        self.modules["RCM2"]["ip_address"] = "192.168.20.32"
        self.modules["LCM1"]["ip_address"] = "192.168.20.41"
        self.modules["LCM1"]["last_state"]["state"]["management"] = {"emergency_url": "https://192.168.20.41:8443/"}
        self.modules["LCM2"]["ip_address"] = "192.168.20.42"
        self.modules["SIM1"]["ip_address"] = "192.168.20.51"
        self.modules["SIM2"]["ip_address"] = "192.168.20.52"
        self.modules["RCM3"]["ip_address"] = "192.168.20.33"
        self.role_transitions: dict[str, dict[str, Any]] = {}
        self.git_settings = {
            "storage_root": "runtime/preview-homecontrol",
            "commit_name": "Preview Admin",
            "commit_email": "preview@example.test",
            "repo_url": "",
            "remote_name": "origin",
            "github_enabled": False,
            "github_token_configured": False,
            "status": {
                "local_enabled": True,
                "remote_configured": False,
                "dirty": False,
                "display": "Local Git enabled (no GitHub remote)",
            },
        }
        self.rcm: dict[str, dict[str, dict[str, Any]]] = {}
        for hostname in ("RCM1", "RCM2", "RCM3"):
            self.rcm[hostname] = {
                channel: {
                    "name": f"{hostname} Channel {index}",
                    "value": False,
                    "maintenance_locked": False,
                }
                for index, channel in enumerate(CHANNELS, start=1)
            }
        self.lcm: dict[str, dict[str, dict[str, Any]]] = {}
        for hostname in ("LCM1", "LCM2"):
            self.lcm[hostname] = {}
            for index, channel in enumerate(["A1", "A2", "A3", "A4"], start=1):
                self.lcm[hostname][channel] = {
                    "kind": "light",
                    "name": f"{hostname} Light {index}",
                    "value": False,
                    "maintenance_locked": channel == "A4" and hostname == "LCM1",
                    "emergency_lighting": channel == "A1",
                }
            dimmer_fixtures = [
                ("10-1", 35, 100, 3.0),
                ("10-2", 0, 75, 2.5),
                ("10-9", 15, 90, 3.5),
                ("HV-1", 60, 85, 4.0),
            ]
            for channel, percent, maximum, fade in dimmer_fixtures:
                self.lcm[hostname][channel] = {
                    "kind": "dimmer",
                    "name": f"{hostname} Dimmer {channel}",
                    "percent": float(percent),
                    "last_nonzero_percent": float(percent or maximum),
                    "max_intensity": int(maximum),
                    "fade_seconds": float(fade),
                    "maintenance_locked": channel == "10-2" and hostname == "LCM1",
                    "emergency_lighting": channel == "10-1",
                }
        self.sim: dict[str, dict[str, Any]] = {
            "SIM1": {
                "can_loops": [
                    {"label": "A", "interface": "can0", "status": "Online", "diagnostics": {"rx_count": 124, "last_frame": {"arbitration_id": 0x110}}},
                    {"label": "B", "interface": "can1", "status": "Online", "diagnostics": {"rx_count": 52, "last_frame": {"arbitration_id": 0x120}}},
                    {"label": "C", "interface": "can2", "status": "Fault", "diagnostics": {"fault": "loop_voltage_off"}},
                ],
                "rmcs": [
                    {
                        "id": "RMC:can0:1",
                        "logical_identifier": "SIM1 Living RMC East",
                        "name": "Living Room East",
                        "room": "Living Room",
                        "room_id": 1,
                        "can_interface": "can0",
                        "can_node_address": 1,
                        "status": "Online",
                        "last_seen": _now(),
                        "last_heartbeat": _now(),
                        "firmware_version": "0.1.1",
                        "hardware_revision": "RMC-NANO-ATMEGA328P",
                        "health_flags": 31,
                        "faults": [],
                        "readings": {
                            "temperature_f": {"value": 72.1, "unit": "F", "status": "OK"},
                            "humidity_pct": {"value": 43, "unit": "%", "status": "OK"},
                            "lux": {"value": 318, "unit": "lux", "status": "OK"},
                            "aqi": {"value": 2, "unit": None, "status": "OK"},
                            "presence": {"value": True, "unit": None, "status": "OK"},
                        },
                        "bound": True,
                    },
                    {
                        "id": "RMC:can0:2",
                        "logical_identifier": "SIM1 Living RMC West",
                        "name": "Living Room West",
                        "room": "Living Room",
                        "room_id": 1,
                        "can_interface": "can0",
                        "can_node_address": 2,
                        "status": "Online",
                        "last_seen": _now(),
                        "last_heartbeat": _now(),
                        "firmware_version": "0.1.1",
                        "hardware_revision": "RMC-NANO-ATMEGA328P",
                        "health_flags": 31,
                        "faults": [],
                        "readings": {
                            "temperature_f": {"value": 71.6, "unit": "F", "status": "OK"},
                            "humidity_pct": {"value": 44, "unit": "%", "status": "OK"},
                            "lux": {"value": 286, "unit": "lux", "status": "OK"},
                            "aqi": {"value": 1, "unit": None, "status": "OK"},
                            "presence": {"value": False, "unit": None, "status": "OK"},
                        },
                        "bound": True,
                    },
                    {
                        "id": "RMC:can1:3",
                        "logical_identifier": "SIM1 Kitchen RMC",
                        "name": "Kitchen",
                        "room": "Kitchen",
                        "room_id": 2,
                        "can_interface": "can1",
                        "can_node_address": 3,
                        "status": "Stale",
                        "last_seen": "2026-10-12T23:40:00Z",
                        "last_heartbeat": "2026-10-12T23:40:00Z",
                        "firmware_version": "0.1.0",
                        "hardware_revision": "RMC-NANO-ATMEGA328P",
                        "health_flags": 31,
                        "faults": [],
                        "readings": {
                            "temperature_f": {"value": 70.4, "unit": "F", "status": "Stale"},
                            "humidity_pct": {"value": 41, "unit": "%", "status": "Stale"},
                            "lux": {"value": None, "unit": "lux", "status": "Unknown"},
                            "aqi": {"value": None, "unit": None, "status": "Unknown"},
                            "presence": {"value": None, "unit": None, "status": "Unknown"},
                        },
                        "bound": True,
                    },
                    {
                        "id": "RMC:can2:4",
                        "logical_identifier": "RMC:can2:4",
                        "name": "RMC:can2:4",
                        "room": "Unassigned",
                        "room_id": None,
                        "can_interface": "can2",
                        "can_node_address": 4,
                        "status": "Fault",
                        "last_seen": _now(),
                        "last_heartbeat": None,
                        "firmware_version": None,
                        "hardware_revision": None,
                        "health_flags": 32,
                        "faults": ["ens160"],
                        "readings": {
                            "temperature_f": {"value": None, "unit": "F", "status": "Unknown"},
                            "humidity_pct": {"value": None, "unit": "%", "status": "Unknown"},
                            "lux": {"value": None, "unit": "lux", "status": "Unknown"},
                            "aqi": {"value": None, "unit": None, "status": "Unknown"},
                            "presence": {"value": False, "unit": None, "status": "OK"},
                        },
                        "bound": False,
                    },
                ],
                "analog_inputs": {
                    "AI-1": {"name": "Supply Pressure", "value": 2.41, "unit": "V", "status": "OK", "source": "ADS 0x48 CH0", "bound": True},
                    "AI-2": {"name": "Return Pressure", "value": 1.87, "unit": "V", "status": "OK", "source": "ADS 0x48 CH1", "bound": True},
                    "AI-3": {"name": "Filter Sensor", "value": None, "unit": "V", "status": "Unknown", "source": "ADS 0x48 CH2", "bound": True},
                    "AI-4": {"name": "Stale Probe", "value": 3.02, "unit": "V", "status": "Stale", "source": "ADS 0x48 CH3", "bound": True},
                },
            },
            "SIM2": {
                "can_loops": [
                    {"label": "A", "interface": "can0", "status": "Unknown", "diagnostics": {}},
                    {"label": "B", "interface": "can1", "status": "Unknown", "diagnostics": {}},
                    {"label": "C", "interface": "can2", "status": "Unknown", "diagnostics": {}},
                ],
                "rmcs": [],
                "analog_inputs": {"AI-1": {"name": "SIM2 Input 1", "value": 0.48, "unit": "V", "status": "OK", "source": "ADS 0x48 CH0", "bound": True}},
            },
        }
        self.hvac = {
            "mode": "HEAT_COOL",
            "setpoint_f": 70.0,
            "average_f": 68.4,
            "fan": False,
            "heat": False,
            "cool": False,
        }
        self.users = {
            "preview-admin": {"username": "preview-admin", "role": "ADMIN", "enabled": True, "created_at": _now(), "password": "preview-admin-password"},
            "household": {"username": "household", "role": "READONLY", "enabled": True, "created_at": _now(), "password": "household-password"},
        }
        self._sync_relays()

    def _sync_relays(self) -> None:
        for hostname, channels in self.rcm.items():
            relays = {
                channel: {"on": bool(state["value"])}
                for channel, state in channels.items()
            }
            self.modules[hostname]["last_state"]["state"]["relays"] = relays
        for hostname, channels in self.lcm.items():
            relays = {}
            lv_dimmers = {}
            hv_dimmers = {}
            for channel, channel_state in channels.items():
                if channel_state["kind"] == "light":
                    relays[channel] = {"on": bool(channel_state["value"])}
                elif channel.startswith("10-"):
                    lv_dimmers[channel] = {"percent": float(channel_state["percent"])}
                else:
                    hv_dimmers[channel] = {"percent": float(channel_state["percent"])}
            self.modules[hostname]["last_state"]["state"]["relays"] = relays
            self.modules[hostname]["last_state"]["state"]["lv_dimmers"] = lv_dimmers
            self.modules[hostname]["last_state"]["state"]["hv_dimmers"] = hv_dimmers
        for hostname, sim_state in self.sim.items():
            can = {
                item["interface"]: {
                    "label": f"CAN {item['label']}",
                    "status": item["status"],
                    **item.get("diagnostics", {}),
                }
                for item in sim_state["can_loops"]
            }
            rmc_nodes = {
                str(item["can_node_address"]): {
                    "rmc_id": item["id"],
                    "address": item["can_node_address"],
                    "can_interface": item["can_interface"],
                    "last_seen": item["last_seen"],
                    "last_heartbeat": item["last_heartbeat"],
                    "firmware_version": item["firmware_version"],
                    "hardware_revision": item["hardware_revision"],
                    "status_flags": item["health_flags"],
                    "faults": item["faults"],
                    "temperature_f": item["readings"]["temperature_f"]["value"],
                    "humidity_pct": item["readings"]["humidity_pct"]["value"],
                    "lux": item["readings"]["lux"]["value"],
                    "aqi": item["readings"]["aqi"]["value"],
                    "presence": item["readings"]["presence"]["value"],
                    "stale": item["status"] == "Stale",
                    "fault_active": item["status"] == "Fault",
                }
                for item in sim_state["rmcs"]
            }
            analog_inputs = {
                f"a{index}": {
                    "label": channel.replace("AI-", "A"),
                    "source": item.get("source"),
                    "unit": item.get("unit"),
                    "value": item.get("value"),
                    "status": item.get("status"),
                }
                for index, (channel, item) in enumerate(sim_state["analog_inputs"].items(), start=1)
                if index <= 8
            }
            self.modules[hostname]["last_state"]["state"].update({
                "can": can,
                "rmc_nodes": rmc_nodes,
                "hexa_board": {"aio": {"analog_inputs": analog_inputs}, "can": can},
            })

    def module(self, identifier: str) -> dict[str, Any]:
        clean = identifier.upper()
        if clean in self.modules:
            return self.modules[clean]
        for module in self.modules.values():
            if module["device_id"] == identifier.lower():
                return module
        raise HTTPException(404, f"preview device {identifier} not found")

    def device_admin(self, identifier: str) -> dict[str, Any]:
        module = self.module(identifier)
        nested = module["last_state"]["state"]
        return {
            "module": copy.deepcopy(module),
            "effective_role": nested["lab_role"],
            "role_source": "preview_fixture",
            "simulation": nested["simulation"],
            "physical_outputs_enabled": nested["physical_outputs_enabled"],
            "replacement_ready": {
                "supported": True,
                "automatic_reassignment_enabled": False,
                "note": "Preview only: future replacement workflows preserve logical identities but do not reassign hardware automatically.",
            },
        }

    def rcm_channels(self, identifier: str) -> dict[str, Any]:
        device = self.device_admin(identifier)
        hostname = device["module"]["hostname"]
        if device["effective_role"] != "RCM":
            raise HTTPException(400, f"{hostname} is not an RCM preview fixture")
        channel_state = self.rcm[hostname]
        control_session_online = bool(device["module"]["control_session_online"])
        channels = []
        for index, channel in enumerate(CHANNELS, start=1):
            state = channel_state[channel]
            reason = None
            if not control_session_online:
                reason = "No authenticated control session"
            elif state["maintenance_locked"]:
                reason = "Maintenance lockout"
            channels.append({
                "number": index,
                "channel": channel,
                "binding_id": index,
                "logical_device_id": index,
                "logical_name": f"{hostname} {channel}",
                "name": state["name"],
                "bound": True,
                "enabled": True,
                "maintenance_locked": state["maintenance_locked"],
                "online": bool(device["module"]["online"]),
                "control_session_online": control_session_online,
                "physical_outputs_enabled": True,
                "value": state["value"],
                "control_enabled": reason is None,
                "disabled_reason": reason,
            })
        return {"device": device, "channels": channels}

    def rename_channel(self, identifier: str, channel: str, name: str) -> dict[str, Any]:
        hostname = self.device_admin(identifier)["module"]["hostname"]
        channel = channel.upper()
        if channel not in self.rcm[hostname]:
            raise HTTPException(404, channel)
        self.rcm[hostname][channel]["name"] = name.strip()
        return self.rcm_channels(hostname)

    def lcm_channels(self, identifier: str) -> dict[str, Any]:
        device = self.device_admin(identifier)
        hostname = device["module"]["hostname"]
        if device["effective_role"] != "LCM":
            raise HTTPException(400, f"{hostname} is not an LCM preview fixture")
        control_session_online = bool(device["module"]["control_session_online"])
        channels = []
        for index, channel in enumerate(LCM_CHANNELS, start=1):
            channel_state = self.lcm[hostname].get(channel)
            is_bound = channel_state is not None
            reason = None
            if not is_bound:
                reason = "No logical binding"
            elif channel_state["maintenance_locked"]:
                reason = "Maintenance lockout"
            elif not control_session_online:
                reason = "No authenticated control session"
            is_dimmer = channel in LCM_DIMMER_CHANNELS
            channel_type = "Relay"
            if channel.startswith("10-"):
                channel_type = "0-10V"
            elif channel.startswith("HV-"):
                channel_type = "110V"
            percent = float(channel_state.get("percent", 100 if channel_state.get("value") else 0)) if channel_state else None
            channels.append({
                "number": index,
                "channel": channel,
                "kind": "dimmer" if is_dimmer else "light",
                "type": channel_type,
                "type_label": channel_type,
                "binding_id": index if is_bound else None,
                "logical_device_id": index if is_bound else None,
                "logical_name": f"{hostname} {channel}" if is_bound else None,
                "name": channel_state["name"] if is_bound else "",
                "bound": is_bound,
                "enabled": is_bound,
                "maintenance_locked": bool(channel_state["maintenance_locked"]) if is_bound else False,
                "emergency_lighting": bool(channel_state["emergency_lighting"]) if is_bound else False,
                "max_intensity": int(channel_state.get("max_intensity", 100)) if is_bound else 100,
                "fade_seconds": float(channel_state.get("fade_seconds", 3)) if is_bound else 3,
                "last_nonzero_percent": float(channel_state.get("last_nonzero_percent", channel_state.get("max_intensity", 100))) if is_bound else 100.0,
                "online": bool(device["module"]["online"]),
                "control_session_online": control_session_online,
                "value": (percent or 0) > 0 if is_dimmer else (bool(channel_state["value"]) if is_bound else None),
                "percent": percent if is_dimmer else None,
                "control_enabled": reason is None,
                "disabled_reason": reason,
            })
        return {"device": device, "channels": channels}

    def lcm_settings(self, identifier: str, channel: str, body: dict[str, Any]) -> dict[str, Any]:
        hostname = self.device_admin(identifier)["module"]["hostname"]
        channel = channel.upper()
        if channel not in self.lcm[hostname]:
            raise HTTPException(404, channel)
        state = self.lcm[hostname][channel]
        name = str(body.get("name", "")).strip()
        if not name:
            raise HTTPException(400, "channel name is required")
        state["name"] = name
        state["emergency_lighting"] = bool(body.get("emergency_lighting"))
        if state["kind"] == "dimmer":
            max_intensity = int(body.get("max_intensity", state.get("max_intensity", 100)))
            fade_seconds = float(body.get("fade_seconds", state.get("fade_seconds", 3)))
            if max_intensity < 0 or max_intensity > 100 or fade_seconds < 0 or fade_seconds > 60:
                raise HTTPException(400, "invalid dimmer settings")
            state["max_intensity"] = max_intensity
            state["fade_seconds"] = fade_seconds
            if state["percent"] > max_intensity:
                state["percent"] = float(max_intensity)
        self._sync_relays()
        return self.lcm_channels(hostname)

    def sim_dashboard(self, identifier: str) -> dict[str, Any]:
        device = self.device_admin(identifier)
        hostname = device["module"]["hostname"]
        if device["effective_role"] != "SIM":
            raise HTTPException(400, f"{hostname} is not a SIM preview fixture")
        sim_state = self.sim[hostname]
        room_groups: dict[str, dict[str, Any]] = {}
        rmcs = []
        for item in sim_state["rmcs"]:
            rmc = copy.deepcopy(item)
            rmc["binding_id"] = 100 + len(rmcs) if rmc["bound"] else None
            rmc["logical_device_id"] = 200 + len(rmcs) if rmc["bound"] else None
            rmcs.append(rmc)
            key = str(rmc["room_id"] or rmc["room"])
            room_groups.setdefault(key, {"room_id": rmc["room_id"], "room": rmc["room"], "rmcs": []})["rmcs"].append(rmc)
        analog_inputs = []
        for index, channel in enumerate(SIM_ANALOG_CHANNELS, start=1):
            state = sim_state["analog_inputs"].get(channel)
            bound = bool(state and state.get("bound"))
            analog_inputs.append({
                "number": index,
                "channel": channel,
                "firmware_channel": f"A{index}" if index <= 8 else None,
                "name": state.get("name", "") if state else "",
                "bound": bound,
                "binding_id": 300 + index if bound else None,
                "logical_device_id": 400 + index if bound else None,
                "logical_name": f"{hostname} {channel}" if bound else None,
                "enabled": bound,
                "value": state.get("value") if state else None,
                "unit": state.get("unit") if state else None,
                "status": state.get("status", "Unknown") if state else "Unknown",
                "source": state.get("source") if state else None,
                "config_enabled": bound,
                "disabled_reason": None if bound else "No logical binding",
            })
        return {
            "device": device,
            "can_loops": copy.deepcopy(sim_state["can_loops"]),
            "room_clusters": list(room_groups.values()),
            "rmcs": rmcs,
            "analog_inputs": analog_inputs,
            "diagnostics": {
                "can": {item["interface"]: item for item in sim_state["can_loops"]},
                "io_mode": "preview",
                "hexa_board_model": "ViaGasaFamido preview",
            },
        }

    def sim_rmc_settings(self, identifier: str, rmc_id: str, body: dict[str, Any]) -> dict[str, Any]:
        hostname = self.device_admin(identifier)["module"]["hostname"]
        name = str(body.get("name", "")).strip()
        if not name:
            raise HTTPException(400, "name is required")
        for rmc in self.sim[hostname]["rmcs"]:
            if rmc["id"] == rmc_id:
                if not rmc.get("bound"):
                    raise HTTPException(404, rmc_id)
                rmc["name"] = name
                self._sync_relays()
                return self.sim_dashboard(hostname)
        raise HTTPException(404, rmc_id)

    def sim_analog_settings(self, identifier: str, channel: str, body: dict[str, Any]) -> dict[str, Any]:
        hostname = self.device_admin(identifier)["module"]["hostname"]
        channel = channel.upper()
        name = str(body.get("name", "")).strip()
        if not name:
            raise HTTPException(400, "name is required")
        state = self.sim[hostname]["analog_inputs"].get(channel)
        if not state or not state.get("bound"):
            raise HTTPException(404, channel)
        state["name"] = name
        self._sync_relays()
        return self.sim_dashboard(hostname)

    def command_logical(self, logical_name: str, command: dict[str, Any]) -> dict[str, Any]:
        hostname, channel = self._split_logical(logical_name)
        if hostname in self.rcm:
            state = self.rcm[hostname][channel]
            if state["maintenance_locked"] and command.get("value") is True:
                raise HTTPException(423, "maintenance lockout active")
            state["value"] = bool(command.get("value"))
        else:
            state = self.lcm[hostname][channel]
            if state["maintenance_locked"]:
                activating = command.get("value") is True or float(command.get("percent", 0) or 0) > 0
                if activating:
                    raise HTTPException(423, "maintenance lockout active")
            if state["kind"] == "light":
                state["value"] = bool(command.get("value"))
            else:
                requested = float(command.get("percent", command.get("value", 100)) or 0)
                effective = max(0.0, min(float(state["max_intensity"]), requested))
                state["percent"] = effective
                if effective > 0:
                    state["last_nonzero_percent"] = effective
        self._sync_relays()
        return {
            "ok": True,
            "logical_name": logical_name,
            "acknowledged": True,
            "requested": command,
            "effective": copy.deepcopy(state),
            "preview": True,
        }

    def set_lockout(self, logical_name: str, active: bool) -> dict[str, Any]:
        hostname, channel = self._split_logical(logical_name)
        state = self.rcm[hostname][channel] if hostname in self.rcm else self.lcm[hostname][channel]
        state["maintenance_locked"] = bool(active)
        if active:
            if state.get("kind") == "dimmer":
                state["percent"] = 0.0
            else:
                state["value"] = False
        self._sync_relays()
        return {"ok": True, "logical_name": logical_name, "maintenance_locked": bool(active), "preview": True}

    def logical_devices(self) -> list[dict[str, Any]]:
        devices = []
        for hostname, channels in {**self.rcm, **self.lcm}.items():
            for channel, channel_state in channels.items():
                if channel_state is None:
                    continue
                devices.append({
                    "logical_name": f"{hostname} {channel}",
                    "device_class": channel_state.get("kind", "relay"),
                    "enabled": True,
                    "maintenance_locked": bool(channel_state.get("maintenance_locked")),
                    "metadata": {"preview": True, "channel": channel},
                    "room": None,
                })
        return devices

    def hvac_state(self) -> dict[str, Any]:
        return copy.deepcopy(self.hvac)

    def set_hvac_setpoint(self, value: Any) -> dict[str, Any]:
        try:
            target = float(value)
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, "setpoint_f must be numeric") from exc
        if target < 45 or target > 90:
            raise HTTPException(422, "setpoint_f must be between 45 and 90")
        self.hvac["setpoint_f"] = target
        return {"ok": True, "setpoint_f": target, "preview": True}

    def set_hvac_mode(self, mode: Any) -> dict[str, Any]:
        normalized = str(mode or "").upper().replace("-", "_").replace("/", "_")
        if normalized == "AUTO":
            normalized = "HEAT_COOL"
        allowed = {"OFF", "HEAT", "COOL", "HEAT_COOL", "FAN"}
        if normalized not in allowed:
            raise HTTPException(422, "unsupported preview HVAC mode")
        self.hvac["mode"] = normalized
        self.hvac["fan"] = normalized == "FAN"
        self.hvac["heat"] = False
        self.hvac["cool"] = False
        return {"ok": True, "mode": normalized, "preview": True}

    def dashboard_status(self) -> dict[str, Any]:
        lockouts = []
        for hostname, channels in {**self.rcm, **self.lcm}.items():
            for channel, channel_state in channels.items():
                if channel_state.get("maintenance_locked"):
                    lockouts.append({
                        "module": hostname,
                        "module_type": self.modules[hostname]["module_type"],
                        "logical_name": f"{hostname} {channel}",
                        "channel_name": channel_state.get("name", f"{hostname} {channel}"),
                        "channel": channel,
                        "locked": True,
                        "reason": "Preview maintenance task" if channel in {"A4", "10-2"} else None,
                        "locked_at": _now() if channel == "A4" else None,
                    })
        faults = [
            {"source": "module_supervision", "severity": "warning", "module": "RCM3", "component": "supervision", "code": "offline", "description": "Module supervision state is offline", "reported_at": None, "active": True},
            {"source": "sim_rmc_state", "severity": "warning", "module": "SIM1", "component": "RMC:can2:4", "code": "ens160", "description": "ens160", "reported_at": _now(), "active": True},
            {"source": "safety_events", "severity": "critical", "module": "HCM", "component": "safety", "code": "alarm_contact_fault", "description": "preview alarm contact diagnostic", "reported_at": _now(), "active": True},
        ]
        return {
            "maintenance_lockouts": {"count": len(lockouts), "items": lockouts},
            "active_faults": {
                "count": len(faults),
                "items": faults,
                "unsupported_sources": ["Preview does not connect to Conflict or production safety services."],
            },
            "conflict_supervisor": {
                "status": "Healthy",
                "available": True,
                "host": "preview-conflict",
                "port": 6004,
                "protocol": "hcm-heartbeat-v3",
                "reason": "Preview fixture has recent simulated heartbeat acknowledgments.",
                "last_heartbeat_received_age_seconds": 4.0,
                "hcm_device_id": "48b02d87db16",
                "conflict_device_id": "3c53bbf7adb2",
            },
        }

    def module_roles(self) -> dict[str, Any]:
        module = self.modules["LAB1"]
        transition = None
        if self.role_transitions:
            transition = sorted(self.role_transitions.values(), key=lambda item: item["requested_at"])[-1]
        nested = module["last_state"]["state"]
        return {
            "roles": ["UNASSIGNED", "RCM", "SIM", "LCM"],
            "modules": [{
                "id": module["id"],
                "device_id": module["device_id"],
                "hostname": module["hostname"],
                "module_type": module["module_type"],
                "ip_address": module["ip_address"],
                "online": module["online"],
                "control_session_online": module["control_session_online"],
                "last_seen": module["last_seen"],
                "last_state": copy.deepcopy(module["last_state"]),
                "role_management": {
                    "enabled": True,
                    "current_role": nested.get("lab_role"),
                    "requested_role": None,
                    "last_transition": copy.deepcopy(transition),
                    "simulation": nested.get("simulation"),
                    "physical_outputs_enabled": nested.get("physical_outputs_enabled"),
                },
            }],
        }

    def request_module_role(self, device_id: str, body: dict[str, Any]) -> dict[str, Any]:
        module = next((item for item in self.modules.values() if item["device_id"] == device_id.lower()), None)
        if not module:
            raise HTTPException(404, "preview module not found")
        if not module["control_session_online"]:
            raise HTTPException(409, "module has no authenticated online control session")
        if not body.get("confirm"):
            raise HTTPException(400, "explicit confirmation is required")
        requested = str(body.get("requested_role", "")).upper()
        if requested not in {"UNASSIGNED", "RCM", "SIM", "LCM"}:
            raise HTTPException(400, "unsupported role")
        operation_id = f"preview-{len(self.role_transitions) + 1}"
        previous_role = module["last_state"]["state"].get("lab_role")
        module["last_state"]["state"]["lab_role"] = requested
        module["last_state"]["state"]["simulation"] = True
        module["last_state"]["state"]["physical_outputs_enabled"] = False
        transition = {
            "operation_id": operation_id,
            "device_id": module["device_id"],
            "previous_role": previous_role,
            "requested_role": requested,
            "status": "CONFIRMED",
            "simulation_required": True,
            "error": None,
            "rejection_reason": None,
            "ack_payload": {"ok": True, "accepted": True, "preview": True},
            "requested_at": _now(),
            "sent_at": _now(),
            "accepted_at": _now(),
            "completed_at": _now(),
        }
        self.role_transitions[operation_id] = transition
        return copy.deepcopy(transition)

    def module_role_transition(self, operation_id: str) -> dict[str, Any]:
        transition = self.role_transitions.get(operation_id)
        if not transition:
            raise HTTPException(404, "preview transition not found")
        return copy.deepcopy(transition)

    def settings_network(self) -> dict[str, Any]:
        modules = []
        for module in self.modules.values():
            emergency_url = module["last_state"]["state"].get("management", {}).get("emergency_url")
            modules.append({
                "hostname": module["hostname"],
                "module_type": module["module_type"],
                "effective_role": module["last_state"]["state"]["lab_role"],
                "ip_address": module["ip_address"],
                "address_source": "current" if module["online"] and module["ip_address"] else "last_known" if module["ip_address"] else "unknown",
                "online": bool(module["online"]),
                "status": "Online" if module["online"] else "Offline",
                "last_seen": module["last_seen"] or module["supervision_last_seen"],
                "emergency_interface": {
                    "available": bool(emergency_url),
                    "url": emergency_url,
                    "reason": "Verified preview emergency URL" if emergency_url else "Emergency interface not verified",
                },
            })
        return {
            "host_interfaces": {
                "available": True,
                "reason": None,
                "source": "preview_fixture",
                "interfaces": [
                    {"name": "eth0", "ipv4": ["192.168.20.27/24"], "ipv6": ["fe80::20:27/64"], "status": "Up", "network": "192.168.20.0/24"},
                    {"name": "eth0.60", "ipv4": ["192.168.60.27/24"], "ipv6": [], "status": "Up", "network": "192.168.60.0/24"},
                    {"name": "tailscale0", "ipv4": ["100.64.10.27/32"], "ipv6": ["fd7a:115c:a1e0::27/128"], "status": "Up", "network": "100.64.10.27/32"},
                    {"name": "spare0", "ipv4": [], "ipv6": [], "status": "Down", "network": None},
                ],
            },
            "modules": modules,
        }

    def git_status(self) -> dict[str, Any]:
        return copy.deepcopy(self.git_settings)

    def update_git_settings(self, body: dict[str, Any]) -> dict[str, Any]:
        repo_url = str(body.get("repo_url", self.git_settings["repo_url"])).strip()
        if "@" in repo_url.split("//", 1)[-1].split("/", 1)[0]:
            raise HTTPException(400, "Repository URL must not contain embedded credentials")
        self.git_settings.update({
            "commit_name": str(body.get("commit_name", self.git_settings["commit_name"])).strip(),
            "commit_email": str(body.get("commit_email", self.git_settings["commit_email"])).strip(),
            "repo_url": repo_url,
            "github_enabled": bool(body.get("github_enabled", self.git_settings["github_enabled"])),
        })
        if body.get("github_pat"):
            self.git_settings["github_token_configured"] = True
        self.git_settings["status"] = {
            "local_enabled": True,
            "remote_configured": bool(self.git_settings["repo_url"] and self.git_settings["github_enabled"]),
            "dirty": False,
            "display": "Git Repository: Not Synced" if self.git_settings["github_enabled"] else "Local Git enabled (no GitHub remote)",
        }
        return self.git_status()

    def disconnect_github(self) -> dict[str, Any]:
        self.git_settings["github_enabled"] = False
        self.git_settings["github_token_configured"] = False
        self.git_settings["status"] = {
            "local_enabled": True,
            "remote_configured": False,
            "dirty": False,
            "display": "Local Git enabled (no GitHub remote)",
        }
        return self.git_status()

    def list_users(self) -> list[dict[str, Any]]:
        return [
            {key: value for key, value in user.items() if key != "password"}
            for user in sorted(self.users.values(), key=lambda item: item["username"])
        ]

    def create_user(self, body: dict[str, Any]) -> dict[str, Any]:
        username = str(body.get("username", "")).strip()
        password = str(body.get("password", ""))
        role = str(body.get("role", "READONLY")).upper()
        if not username:
            raise HTTPException(400, "invalid username")
        if username in self.users:
            raise HTTPException(409, "user already exists")
        if role not in {"ADMIN", "READONLY"}:
            raise HTTPException(400, "invalid role")
        if len(password) < 10:
            raise HTTPException(400, "password must be at least 10 characters")
        self.users[username] = {"username": username, "role": role, "enabled": True, "created_at": _now(), "password": password}
        return {"ok": True, **{key: value for key, value in self.users[username].items() if key != "password"}}

    def update_user_role(self, username: str, body: dict[str, Any]) -> dict[str, Any]:
        user = self.users.get(username)
        if not user:
            raise HTTPException(404, "user not found")
        role = str(body.get("role", "")).upper()
        if role not in {"ADMIN", "READONLY"}:
            raise HTTPException(400, "invalid role")
        if user["role"] == "ADMIN" and role != "ADMIN":
            admins = [item for item in self.users.values() if item["role"] == "ADMIN" and item["enabled"]]
            if len(admins) <= 1:
                raise HTTPException(409, "cannot demote final administrator")
        user["role"] = role
        return {"ok": True, **{key: value for key, value in user.items() if key != "password"}, "sessions_revoked": True}

    def reset_user_password(self, username: str, body: dict[str, Any]) -> dict[str, Any]:
        user = self.users.get(username)
        if not user:
            raise HTTPException(404, "user not found")
        password = str(body.get("password", ""))
        if len(password) < 10:
            raise HTTPException(400, "password must be at least 10 characters")
        user["password"] = password
        return {"ok": True, **{key: value for key, value in user.items() if key != "password"}, "sessions_revoked": True}

    def _split_logical(self, logical_name: str) -> tuple[str, str]:
        parts = logical_name.split()
        if len(parts) != 2:
            raise HTTPException(404, logical_name)
        hostname, channel = parts[0].upper(), parts[1].upper()
        module_channels = self.rcm.get(hostname) or self.lcm.get(hostname)
        if not module_channels or channel not in module_channels:
            raise HTTPException(404, logical_name)
        if not self.modules[hostname]["control_session_online"]:
            raise HTTPException(503, f"{hostname} offline")
        return hostname, channel


state = PreviewState()
app = FastAPI(title="HomeControl UI Preview", version="preview")
app.mount("/static", StaticFiles(directory=WEB_ROOT), name="static")


def _require_preview_auth(authorization: str | None) -> None:
    if authorization not in {f"Bearer {PREVIEW_TOKEN}", f"Bearer {PREVIEW_READONLY_TOKEN}"}:
        raise HTTPException(401, "preview login required")


def _require_preview_admin(authorization: str | None) -> None:
    _require_preview_auth(authorization)
    if authorization != f"Bearer {PREVIEW_TOKEN}":
        raise HTTPException(403, "preview admin role required")


@app.get("/api/v1/preview-mode")
async def preview_mode(authorization: str | None = Header(default=None)):
    _require_preview_auth(authorization)
    return {"preview": True, "production_connected": False}


@app.post("/api/v1/auth/login")
async def login(body: dict[str, Any]):
    username = str(body.get("username", ""))
    if username == "household":
        return {"token": PREVIEW_READONLY_TOKEN, "preview": True}
    return {"token": PREVIEW_TOKEN, "preview": True}


@app.get("/api/v1/auth/session")
async def session(authorization: str | None = Header(default=None)):
    _require_preview_auth(authorization)
    if authorization == f"Bearer {PREVIEW_READONLY_TOKEN}":
        return {"user": "household", "role": "READONLY"}
    return {"user": "preview-admin", "role": "ADMIN"}


@app.get("/api/v1/auth/users")
async def users(authorization: str | None = Header(default=None)):
    _require_preview_admin(authorization)
    return {"users": state.list_users(), "roles": ["ADMIN", "READONLY"]}


@app.post("/api/v1/auth/users")
async def create_user(body: dict[str, Any], authorization: str | None = Header(default=None)):
    _require_preview_admin(authorization)
    return state.create_user(body)


@app.patch("/api/v1/auth/users/{username}/role")
async def update_user_role(username: str, body: dict[str, Any], authorization: str | None = Header(default=None)):
    _require_preview_admin(authorization)
    return state.update_user_role(username, body)


@app.post("/api/v1/auth/users/{username}/password")
async def reset_user_password(username: str, body: dict[str, Any], authorization: str | None = Header(default=None)):
    _require_preview_admin(authorization)
    return state.reset_user_password(username, body)


@app.get("/api/v1/health")
async def health(authorization: str | None = Header(default=None)):
    _require_preview_auth(authorization)
    return {
        "ok": True,
        "preview": True,
        "database": "not used",
        "production_connected": False,
        "heartbeat_supervisor": {
            "status": "Online",
            "host": "preview-local",
            "port": 6004,
            "source": "preview_fixture",
        },
        "fire_life_safety": {
            "status": "Unavailable",
            "source": "preview_fixture",
            "detail": "No production safety controller is connected to preview.",
        },
        "active_fault_count": 2,
    }


@app.get("/api/v1/hvac")
async def hvac(authorization: str | None = Header(default=None)):
    _require_preview_auth(authorization)
    return state.hvac_state()


@app.put("/api/v1/hvac/setpoint")
async def hvac_setpoint(body: dict[str, Any], authorization: str | None = Header(default=None)):
    _require_preview_auth(authorization)
    return state.set_hvac_setpoint(body.get("setpoint_f"))


@app.put("/api/v1/hvac/mode")
async def hvac_mode(body: dict[str, Any], authorization: str | None = Header(default=None)):
    _require_preview_auth(authorization)
    return state.set_hvac_mode(body.get("mode"))


@app.get("/api/v1/modules")
async def modules(authorization: str | None = Header(default=None)):
    _require_preview_auth(authorization)
    return {"modules": [copy.deepcopy(module) for module in state.modules.values()]}


@app.get("/api/v1/module-roles")
async def module_roles(authorization: str | None = Header(default=None)):
    _require_preview_auth(authorization)
    return state.module_roles()


@app.post("/api/v1/modules/{device_id}/role")
async def module_role_change(device_id: str, body: dict[str, Any], authorization: str | None = Header(default=None)):
    _require_preview_admin(authorization)
    return state.request_module_role(device_id, body)


@app.get("/api/v1/module-role-transitions/{operation_id}")
async def module_role_transition(operation_id: str, authorization: str | None = Header(default=None)):
    _require_preview_auth(authorization)
    return state.module_role_transition(operation_id)


@app.get("/api/v1/dashboard/status")
async def dashboard_status(authorization: str | None = Header(default=None)):
    _require_preview_auth(authorization)
    return state.dashboard_status()


@app.get("/api/v1/settings/network")
async def settings_network(authorization: str | None = Header(default=None)):
    _require_preview_auth(authorization)
    return state.settings_network()


@app.get("/api/v1/settings/git")
async def settings_git(authorization: str | None = Header(default=None)):
    _require_preview_admin(authorization)
    return state.git_status()


@app.put("/api/v1/settings/git")
async def settings_git_update(body: dict[str, Any], authorization: str | None = Header(default=None)):
    _require_preview_admin(authorization)
    return state.update_git_settings(body)


@app.post("/api/v1/settings/github/connect")
async def settings_github_connect(body: dict[str, Any], authorization: str | None = Header(default=None)):
    _require_preview_admin(authorization)
    return state.update_git_settings({**body, "github_enabled": True})


@app.delete("/api/v1/settings/github")
async def settings_github_disconnect(authorization: str | None = Header(default=None)):
    _require_preview_admin(authorization)
    return state.disconnect_github()


@app.get("/api/v1/logical-devices")
async def logical_devices(authorization: str | None = Header(default=None)):
    _require_preview_auth(authorization)
    return {"logical_devices": state.logical_devices()}


@app.get("/api/v1/device-admin/{identifier}")
async def device_admin(identifier: str, authorization: str | None = Header(default=None)):
    _require_preview_auth(authorization)
    return state.device_admin(identifier)


@app.get("/api/v1/device-admin/{identifier}/rcm-channels")
async def rcm_channels(identifier: str, authorization: str | None = Header(default=None)):
    _require_preview_auth(authorization)
    return state.rcm_channels(identifier)


@app.patch("/api/v1/device-admin/{identifier}/rcm-channels/{channel}/name")
async def rename_channel(identifier: str, channel: str, body: dict[str, Any], authorization: str | None = Header(default=None)):
    _require_preview_auth(authorization)
    return state.rename_channel(identifier, channel, str(body.get("name", "")))


@app.get("/api/v1/device-admin/{identifier}/lcm-channels")
async def lcm_channels(identifier: str, authorization: str | None = Header(default=None)):
    _require_preview_auth(authorization)
    return state.lcm_channels(identifier)


@app.patch("/api/v1/device-admin/{identifier}/lcm-channels/{channel}/settings")
async def lcm_settings(identifier: str, channel: str, body: dict[str, Any], authorization: str | None = Header(default=None)):
    _require_preview_auth(authorization)
    return state.lcm_settings(identifier, channel, body)


@app.get("/api/v1/device-admin/{identifier}/sim-dashboard")
async def sim_dashboard(identifier: str, authorization: str | None = Header(default=None)):
    _require_preview_auth(authorization)
    return state.sim_dashboard(identifier)


@app.patch("/api/v1/device-admin/{identifier}/sim-rmcs/{rmc_id:path}/settings")
async def sim_rmc_settings(identifier: str, rmc_id: str, body: dict[str, Any], authorization: str | None = Header(default=None)):
    _require_preview_auth(authorization)
    return state.sim_rmc_settings(identifier, rmc_id, body)


@app.patch("/api/v1/device-admin/{identifier}/sim-analog-inputs/{channel}/settings")
async def sim_analog_settings(identifier: str, channel: str, body: dict[str, Any], authorization: str | None = Header(default=None)):
    _require_preview_auth(authorization)
    return state.sim_analog_settings(identifier, channel, body)


@app.post("/api/v1/device/command")
async def command(body: dict[str, Any], authorization: str | None = Header(default=None)):
    _require_preview_auth(authorization)
    return state.command_logical(str(body.get("logical_name", "")), body.get("command") or {})


@app.post("/api/v1/safety/maintenance-lockout")
async def maintenance_lockout(body: dict[str, Any], authorization: str | None = Header(default=None)):
    _require_preview_auth(authorization)
    return state.set_lockout(str(body.get("logical_name", "")), bool(body.get("active")))


@app.get("/api/v1/safety/hcm-relays")
async def hcm_relays(authorization: str | None = Header(default=None)):
    _require_preview_auth(authorization)
    return {"preview": True, "relays": {}, "updated_at": time.time()}


@app.get("/")
@app.get("/dashboard")
@app.get("/devices")
@app.get("/devices/{path:path}")
@app.get("/service")
@app.get("/settings")
@app.get("/users")
async def web_app():
    return FileResponse(WEB_ROOT / "index.html")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the standalone HomeControl UI development preview.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8081)
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("preview server must bind to 127.0.0.1/localhost only")
    print(f"HomeControl UI preview: http://127.0.0.1:{args.port}")
    print("Preview fixtures are simulated and never contact production HCM, PostgreSQL, Jetson, Conflict, LAB1, or modules.")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
