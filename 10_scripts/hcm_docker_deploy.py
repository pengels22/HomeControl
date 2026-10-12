#!/usr/bin/env python3

import argparse
import http.client
import json
import socket
import sys
import time
from copy import deepcopy
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote


SOCKET = "/var/run/docker.sock"


class DockerDeployError(RuntimeError):
    pass


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__("localhost")
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.path)


def docker(method, path, body=None, ok=(200, 201, 204, 304)):
    # type: (str, str, Optional[Dict[str, Any]], Tuple[int, ...]) -> Dict[str, Any]
    conn = UnixHTTPConnection(SOCKET)
    payload = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    conn.request(method, path, body=payload, headers=headers)
    response = conn.getresponse()
    data = response.read()
    conn.close()
    if response.status not in ok:
        detail = data.decode(errors="replace")
        raise DockerDeployError(f"Docker API {method} {path} failed: HTTP {response.status}: {detail}")
    if not data:
        return {}
    return json.loads(data)


def inspect_container(name):
    # type: (str) -> Dict[str, Any]
    return docker("GET", f"/containers/{quote(name, safe='')}/json")


def container_exists(name):
    # type: (str) -> bool
    try:
        inspect_container(name)
    except DockerDeployError:
        return False
    return True


def stop_container(name):
    # type: (str) -> None
    docker("POST", f"/containers/{quote(name, safe='')}/stop?t=20", ok=(204, 304))


def start_container(name):
    # type: (str) -> None
    docker("POST", f"/containers/{quote(name, safe='')}/start", ok=(204, 304))


def rename_container(old, new):
    # type: (str, str) -> None
    docker("POST", f"/containers/{quote(old, safe='')}/rename?name={quote(new, safe='')}", ok=(204,))


def remove_container(name):
    # type: (str) -> None
    docker("DELETE", f"/containers/{quote(name, safe='')}?force=true", ok=(204, 404))


def create_clone(source, image, name):
    # type: (Dict[str, Any], str, str) -> None
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


def published_health_url(name):
    # type: (str) -> str
    container = inspect_container(name)
    bindings = (container.get("HostConfig") or {}).get("PortBindings") or {}
    published = []
    for item in bindings.get("8080/tcp") or []:
        host = item.get("HostIp") or ""
        port = item.get("HostPort") or ""
        if host in ("", "0.0.0.0", "::") or not port:
            continue
        published.append((host, port))
    if len(published) != 1:
        raise DockerDeployError("expected one concrete 8080/tcp binding, found {}".format(bindings.get("8080/tcp")))
    host, port = published[0]
    return "http://{}:{}/api/v1/health".format(host, port)


def healthcheck(name, url, timeout):
    # type: (str, Optional[str], int) -> None
    if url is None:
        url = published_health_url(name)
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
    raise DockerDeployError(f"health check failed for {url}: {last}")


def deploy(image, name, rollback_name, health_url, timeout):
    # type: (str, str, str, Optional[str], int) -> None
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


def rollback(name, rollback_name, health_url, timeout):
    # type: (str, str, Optional[str], int) -> None
    if not container_exists(rollback_name):
        raise DockerDeployError(f"rollback container {rollback_name} is missing")
    if container_exists(name):
        stop_container(name)
        remove_container(name)
    rename_container(rollback_name, name)
    start_container(name)
    healthcheck(name, health_url, timeout)


def main(argv=None):
    # type: (Optional[list]) -> int
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("deploy", "rollback"))
    parser.add_argument("--image")
    parser.add_argument("--name", default="hcm-test")
    parser.add_argument("--rollback-name", default="hcm-rollback-before-deploy")
    parser.add_argument("--health-url", default=None)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args(argv)
    if args.action == "deploy":
        if not args.image:
            parser.error("--image is required for deploy")
        try:
            deploy(args.image, name=args.name, rollback_name=args.rollback_name, health_url=args.health_url, timeout=args.timeout)
        except DockerDeployError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    else:
        try:
            rollback(name=args.name, rollback_name=args.rollback_name, health_url=args.health_url, timeout=args.timeout)
        except DockerDeployError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
