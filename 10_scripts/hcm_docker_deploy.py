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


def connect_network(container, network_name, endpoint):
    # type: (str, str, Dict[str, Any]) -> None
    body = {"Container": container}
    if endpoint:
        body["EndpointConfig"] = endpoint
    docker("POST", f"/networks/{quote(network_name, safe='')}/connect", body=body, ok=(200, 204))


def container_id(info):
    # type: (Dict[str, Any]) -> str
    return str(info.get("Id") or "")[:12]


def full_container_id(info):
    # type: (Dict[str, Any]) -> str
    return str(info.get("Id") or "")


def inspect_optional(name):
    # type: (str) -> Optional[Dict[str, Any]]
    try:
        return inspect_container(name)
    except DockerDeployError:
        return None


def create_clone(source, image, name):
    # type: (Dict[str, Any], str, str) -> None
    validate_clone_source(source)
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
        if network.get("DriverOpts"):
            endpoint["DriverOpts"] = network["DriverOpts"]
        if network.get("Links"):
            endpoint["Links"] = network["Links"]
        # Preserve only explicitly configured IPAM. Do not pin dynamic IPAddress values.
        if network.get("IPAMConfig"):
            endpoint["IPAMConfig"] = network["IPAMConfig"]
        endpoints[network_name] = endpoint
    if not endpoints:
        raise DockerDeployError("current container has no Docker networks to clone")
    primary_network = "hcm-control" if "hcm-control" in endpoints else sorted(endpoints)[0]
    additional_networks = [(network_name, endpoints[network_name]) for network_name in sorted(endpoints) if network_name != primary_network]
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
        "Healthcheck": config.get("Healthcheck"),
        "WorkingDir": config.get("WorkingDir", ""),
        "StopSignal": config.get("StopSignal"),
        "StopTimeout": config.get("StopTimeout"),
        "Shell": config.get("Shell"),
        "HostConfig": host_config,
        "NetworkingConfig": {"EndpointsConfig": {primary_network: endpoints[primary_network]}},
    }
    body = {key: value for key, value in body.items() if value is not None}
    docker("POST", f"/containers/create?name={quote(name)}", body=body, ok=(201,))
    for network_name, endpoint in additional_networks:
        try:
            connect_network(name, network_name, endpoint)
        except DockerDeployError as exc:
            raise DockerDeployError("failure connecting replacement container {} to network {}: {}".format(name, network_name, exc))


def validate_clone_source(source):
    # type: (Dict[str, Any]) -> None
    host_config = source.get("HostConfig") or {}
    networks = (source.get("NetworkSettings") or {}).get("Networks") or {}
    bindings = host_config.get("PortBindings") or {}
    mounts = source.get("Mounts") or []
    if "hcm-control" not in networks or "hcm-internal" not in networks:
        raise DockerDeployError("current container is missing required HCM Docker networks")
    if "8080/tcp" not in bindings:
        raise DockerDeployError("current container is missing HCM API port binding")
    destinations = {item.get("Destination") for item in mounts}
    if "/var/lib/postgresql/data" in destinations:
        raise DockerDeployError("refusing to clone HCM app container with PostgreSQL data mount")
    if not (source.get("Config") or {}).get("Image"):
        raise DockerDeployError("current container image is unknown")


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


def recover_original_container(active_name, rollback_name, original_id, health_url, timeout):
    # type: (str, str, str, Optional[str], int) -> str
    active = inspect_optional(active_name)
    rollback = inspect_optional(rollback_name)
    active_id = full_container_id(active) if active else None
    rollback_id = full_container_id(rollback) if rollback else None

    if active_id == original_id:
        try:
            start_container(active_name)
            healthcheck(active_name, health_url, timeout)
        except DockerDeployError as exc:
            raise DockerDeployError("failure restoring the original container already at {}: {}".format(active_name, exc))
        return "original_container_already_named_{}_id_{}_health=ok".format(active_name, container_id(active))

    if rollback_id == original_id:
        if active is not None:
            if active_id:
                try:
                    stop_container(active_name)
                except DockerDeployError as exc:
                    raise DockerDeployError("failure restoring the original container: could not stop replacement {} id {}: {}".format(active_name, container_id(active), exc))
                try:
                    remove_container(active_name)
                except DockerDeployError as exc:
                    raise DockerDeployError("failure restoring the original container: could not remove replacement {} id {}: {}".format(active_name, container_id(active), exc))
            else:
                raise DockerDeployError("manual intervention required: {} exists with no inspectable container ID; refusing removal".format(active_name))
        try:
            rename_container(rollback_name, active_name)
            start_container(active_name)
            healthcheck(active_name, health_url, timeout)
        except DockerDeployError as exc:
            raise DockerDeployError("failure restoring the original container from {}: {}".format(rollback_name, exc))
        return "original_container_restored_from_{}_id_{}_health=ok".format(rollback_name, container_id(rollback))

    if active is None and rollback is None:
        raise DockerDeployError("manual intervention required: original container id {} is not present as {} or {}".format(original_id[:12], active_name, rollback_name))
    raise DockerDeployError(
        "manual intervention required: ambiguous container identity after failure; "
        "{} id={}, {} id={}, expected original id {}; refusing destructive cleanup".format(
            active_name,
            container_id(active) if active else "missing",
            rollback_name,
            container_id(rollback) if rollback else "missing",
            original_id[:12],
        )
    )


def deploy(image, name, rollback_name, health_url, timeout, deployment_id=None):
    # type: (str, str, str, Optional[str], int, Optional[str]) -> None
    source = inspect_container(name)
    source_id = full_container_id(source)
    if not source_id:
        raise DockerDeployError("current container {} has no inspectable immutable ID".format(name))
    if container_exists(rollback_name):
        raise DockerDeployError("rollback container {} already exists; refusing to overwrite recovery point".format(rollback_name))
    validate_clone_source(source)
    print(
        "previous_container name={} id={} image={} rollback_name={} deployment_id={}".format(
            name,
            container_id(source),
            (source.get("Config") or {}).get("Image"),
            rollback_name,
            deployment_id or "unspecified",
        ),
        flush=True,
    )
    try:
        try:
            stop_container(name)
        except DockerDeployError as exc:
            raise DockerDeployError("failure stopping original container {} id {}: {}".format(name, container_id(source), exc))
        try:
            rename_container(name, rollback_name)
        except DockerDeployError as exc:
            raise DockerDeployError("failure renaming original container {} id {} to {}: {}".format(name, container_id(source), rollback_name, exc))
        rollback = inspect_container(rollback_name)
        if full_container_id(rollback) != source_id:
            raise DockerDeployError(
                "rollback container identity mismatch after rename: {} id {} != expected {}".format(
                    rollback_name,
                    container_id(rollback),
                    source_id[:12],
                )
            )
        print("rollback_container name={} id={} verified=true".format(rollback_name, container_id(rollback)), flush=True)
        try:
            create_clone(source, image=image, name=name)
        except DockerDeployError as exc:
            raise DockerDeployError("failure creating replacement container {} image {}: {}".format(name, image, exc))
        try:
            start_container(name)
        except DockerDeployError as exc:
            raise DockerDeployError("failure starting replacement container {} image {}: {}".format(name, image, exc))
        try:
            healthcheck(name, health_url, timeout)
        except DockerDeployError as exc:
            raise DockerDeployError("failure verifying replacement health for {} image {}: {}".format(name, image, exc))
        print("replacement_container name={} image={} health=ok".format(name, image), flush=True)
    except DockerDeployError as exc:
        try:
            recovery = recover_original_container(name, rollback_name, source_id, health_url, timeout)
        except DockerDeployError as recovery_exc:
            raise DockerDeployError("{}; recovery_failed={}".format(exc, recovery_exc))
        raise DockerDeployError("{}; recovery={}".format(exc, recovery))


def rollback(name, rollback_name, health_url, timeout):
    # type: (str, str, Optional[str], int) -> None
    if not container_exists(rollback_name):
        raise DockerDeployError("rollback container {} is missing".format(rollback_name))
    rollback_info = inspect_container(rollback_name)
    rollback_id = full_container_id(rollback_info)
    if not rollback_id:
        raise DockerDeployError("rollback container {} has no inspectable immutable ID".format(rollback_name))
    if container_exists(name):
        active = inspect_container(name)
        active_id = full_container_id(active)
        if active_id == rollback_id:
            start_container(name)
            healthcheck(name, health_url, timeout)
            return
        if not active_id:
            raise DockerDeployError("manual intervention required: {} exists with no inspectable container ID; refusing removal".format(name))
        stop_container(name)
        remove_container(name)
    rename_container(rollback_name, name)
    restored = inspect_container(name)
    if full_container_id(restored) != rollback_id:
        raise DockerDeployError("restored container identity mismatch after rollback")
    start_container(name)
    healthcheck(name, health_url, timeout)


def main(argv=None):
    # type: (Optional[list]) -> int
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("deploy", "rollback"))
    parser.add_argument("--image")
    parser.add_argument("--name", default="hcm-test")
    parser.add_argument("--rollback-name", required=True)
    parser.add_argument("--deployment-id")
    parser.add_argument("--health-url", default=None)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args(argv)
    if args.action == "deploy":
        if not args.image:
            parser.error("--image is required for deploy")
        try:
            deploy(args.image, name=args.name, rollback_name=args.rollback_name, health_url=args.health_url, timeout=args.timeout, deployment_id=args.deployment_id)
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
