#!/usr/bin/env python3
from __future__ import annotations

import argparse
import http.client
import json
import socket
import sys
import time
from copy import deepcopy
from urllib.parse import quote


SOCKET = "/var/run/docker.sock"


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path: str):
        super().__init__("localhost")
        self.path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.path)


def docker(method: str, path: str, body: dict | None = None, ok: tuple[int, ...] = (200, 201, 204, 304)) -> dict:
    conn = UnixHTTPConnection(SOCKET)
    payload = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    conn.request(method, path, body=payload, headers=headers)
    response = conn.getresponse()
    data = response.read()
    conn.close()
    if response.status not in ok:
        detail = data.decode(errors="replace")
        raise SystemExit(f"Docker API {method} {path} failed: HTTP {response.status}: {detail}")
    if not data:
        return {}
    return json.loads(data)


def inspect_container(name: str) -> dict:
    return docker("GET", f"/containers/{quote(name, safe='')}/json")


def container_exists(name: str) -> bool:
    try:
        inspect_container(name)
    except SystemExit:
        return False
    return True


def stop_container(name: str) -> None:
    docker("POST", f"/containers/{quote(name, safe='')}/stop?t=20", ok=(204, 304))


def start_container(name: str) -> None:
    docker("POST", f"/containers/{quote(name, safe='')}/start", ok=(204, 304))


def rename_container(old: str, new: str) -> None:
    docker("POST", f"/containers/{quote(old, safe='')}/rename?name={quote(new, safe='')}", ok=(204,))


def remove_container(name: str) -> None:
    docker("DELETE", f"/containers/{quote(name, safe='')}?force=true", ok=(204, 404))


def create_clone(source: dict, *, image: str, name: str) -> None:
    config = deepcopy(source["Config"])
    host_config = deepcopy(source["HostConfig"])
    networks = source.get("NetworkSettings", {}).get("Networks", {})
    endpoints = {}
    for network_name, network in networks.items():
        endpoint = {}
        if network.get("Aliases"):
            endpoint["Aliases"] = network["Aliases"]
        if network.get("MacAddress"):
            endpoint["MacAddress"] = network["MacAddress"]
        # Do not pin dynamic IPs unless the live container already had a user-specified static IPAM config.
        endpoints[network_name] = endpoint
    config["Image"] = image
    body = {
        "Hostname": config.get("Hostname"),
        "Domainname": config.get("Domainname", ""),
        "User": config.get("User", ""),
        "AttachStdin": False,
        "AttachStdout": False,
        "AttachStderr": False,
        "Tty": config.get("Tty", False),
        "OpenStdin": config.get("OpenStdin", False),
        "Env": config.get("Env"),
        "Cmd": config.get("Cmd"),
        "Entrypoint": config.get("Entrypoint"),
        "Image": image,
        "Labels": config.get("Labels"),
        "ExposedPorts": config.get("ExposedPorts"),
        "WorkingDir": config.get("WorkingDir", ""),
        "HostConfig": host_config,
        "NetworkingConfig": {"EndpointsConfig": endpoints},
    }
    docker("POST", f"/containers/create?name={quote(name)}", body=body, ok=(201,))


def healthcheck(name: str, url: str, timeout: int) -> None:
    deadline = time.time() + timeout
    import urllib.request

    last = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status < 400:
                    return
        except Exception as exc:  # pragma: no cover - exercised on target host
            last = exc
        time.sleep(2)
    raise SystemExit(f"health check failed for {url}: {last}")


def deploy(image: str, *, name: str, rollback_name: str, health_url: str, timeout: int) -> None:
    source = inspect_container(name)
    if container_exists(rollback_name):
        rollback = inspect_container(rollback_name)
        if rollback.get("Config", {}).get("Image") != source.get("Config", {}).get("Image"):
            raise SystemExit(f"rollback container {rollback_name} exists and does not match current {name}; refusing to overwrite")
        remove_container(rollback_name)
    stop_container(name)
    rename_container(name, rollback_name)
    try:
        create_clone(source, image=image, name=name)
        start_container(name)
        healthcheck(name, health_url, timeout)
    except Exception:
        remove_container(name)
        rename_container(rollback_name, name)
        start_container(name)
        raise


def rollback(*, name: str, rollback_name: str, health_url: str, timeout: int) -> None:
    if not container_exists(rollback_name):
        raise SystemExit(f"rollback container {rollback_name} is missing")
    if container_exists(name):
        stop_container(name)
        remove_container(name)
    rename_container(rollback_name, name)
    start_container(name)
    healthcheck(name, health_url, timeout)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("deploy", "rollback"))
    parser.add_argument("--image")
    parser.add_argument("--name", default="hcm-test")
    parser.add_argument("--rollback-name", default="hcm-rollback-before-deploy")
    parser.add_argument("--health-url", default="http://127.0.0.1:8080/api/v1/health")
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args(argv)
    if args.action == "deploy":
        if not args.image:
            parser.error("--image is required for deploy")
        deploy(args.image, name=args.name, rollback_name=args.rollback_name, health_url=args.health_url, timeout=args.timeout)
    else:
        rollback(name=args.name, rollback_name=args.rollback_name, health_url=args.health_url, timeout=args.timeout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
