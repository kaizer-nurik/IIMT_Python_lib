"""Private native-Windows verification VM lifecycle over the local Docker socket."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import secrets
import socket
import struct
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / ".build/windows-vm"
IMAGE = "dockurr/windows@sha256:16fd7c39a3e48bb946d29c59dc6015942e5b900a1fa5d7e5552053bfc48ee2ea"
NAME = "iimt-native-windows-verification"
LABEL = "iimt.native.windows-verification"


class Docker(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(180)
        self.sock.connect("/var/run/docker.sock")


def request(method, path, value=None):
    client = Docker("localhost")
    body = None if value is None else json.dumps(value)
    client.request(method, path, body, {"Content-Type": "application/json"})
    response = client.getresponse()
    data = response.read()
    client.close()
    if response.status >= 300:
        raise RuntimeError(f"Docker {response.status}: {data.decode(errors='replace')}")
    return data


def instance():
    record = json.loads((WORK / "instance.json").read_text())
    inspect = json.loads(request("GET", f"/containers/{record['id']}/json"))
    if inspect["Config"]["Labels"].get(LABEL) != "true":
        raise RuntimeError("Container label mismatch; refusing lifecycle operation")
    return record, inspect


def start(host_project):
    if (WORK / "instance.json").exists():
        record, inspect = instance()
        if not inspect["State"]["Running"]:
            request("POST", f"/containers/{record['id']}/start")
        print(record["id"])
        return
    iso = WORK / "downloads/server2022-eval.iso"
    if iso.stat().st_size != 5_044_094_976 or not (iso.parent / "iso.sha256").exists():
        raise RuntimeError("Official ISO download/checksum is incomplete")
    hashes = (iso.parent / "iso.sha256").read_text().split()
    if not hashes:
        raise RuntimeError("ISO checksum is still being computed")
    expected = hashes[0]
    digest = hashlib.sha256()
    with iso.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024**2), b""):
            digest.update(block)
    if digest.hexdigest() != expected:
        raise RuntimeError("ISO checksum differs from recorded official-download digest")
    for name in (
        "python-3.12.10-amd64.exe",
        "vc_redist.x64.exe",
        "install.bat",
        "bootstrap.ps1",
        "agent.ps1",
    ):
        if not (WORK / "oem" / name).is_file():
            raise RuntimeError(f"Missing OEM input {name}")
    password = secrets.token_urlsafe(24) + "Aa1!"
    credentials = WORK / "credentials.json"
    credentials.write_text(json.dumps({"username": "Docker", "password": password}))
    os.chmod(credentials, 0o600)
    mounts = []
    for source, target, read_only in (
        ("storage", "/storage", False),
        ("shared", "/shared", False),
        ("oem", "/oem", True),
        ("downloads/server2022-eval.iso", "/custom.iso", True),
    ):
        mounts.append(
            {
                "Type": "bind",
                "Source": f"{host_project}/.build/windows-vm/{source}",
                "Target": target,
                "ReadOnly": read_only,
            }
        )
    config = {
        "Image": IMAGE,
        "Labels": {LABEL: "true"},
        "Env": [
            "VERSION=2022",
            "RAM_SIZE=3G",
            "CPU_CORES=2",
            "DISK_SIZE=80G",
            "DISK_FMT=qcow2",
            "NETWORK=user",
            "LOG=Y",
            "USERNAME=Docker",
            f"PASSWORD={password}",
            "AUTOLOGIN=Y",
        ],
        "HostConfig": {
            "Devices": [
                {"PathOnHost": "/dev/kvm", "PathInContainer": "/dev/kvm", "CgroupPermissions": "rw"}
            ],
            "Mounts": mounts,
            "NetworkMode": "bridge",
            "Memory": 4 * 1024**3,
            "NanoCpus": 2_000_000_000,
        },
        "StopTimeout": 120,
    }
    record = json.loads(request("POST", f"/containers/create?name={NAME}", config))
    identity = {
        "id": record["Id"],
        "name": NAME,
        "image": IMAGE,
        "created_unix": time.time(),
        "host_project": host_project,
    }
    (WORK / "instance.json").write_text(json.dumps(identity, indent=2))
    request("POST", f"/containers/{record['Id']}/start")
    print(record["Id"])


def logs():
    record, _ = instance()
    data = request("GET", f"/containers/{record['id']}/logs?stdout=1&stderr=1&tail=100")
    output = b""
    while len(data) >= 8:
        size = struct.unpack(">I", data[4:8])[0]
        output += data[8 : 8 + size]
        data = data[8 + size :]
    print((output + data).decode(errors="replace"))


def configure_share():
    """Disable SMB leases: jobs are created outside Samba by the Linux host."""
    record, _ = instance()
    command = (
        "test -f /etc/samba/smb.conf && "
        "(grep -q 'smb2 leases = no' /etc/samba/smb.conf || "
        "sed -i '/^\\[global\\]/a\\    smb2 leases = no' /etc/samba/smb.conf) && "
        "smbcontrol smbd reload-config"
    )
    execution = json.loads(
        request(
            "POST",
            f"/containers/{record['id']}/exec",
            {"AttachStdout": True, "AttachStderr": True, "Cmd": ["bash", "-lc", command]},
        )
    )
    request("POST", f"/exec/{execution['Id']}/start", {"Detach": False, "Tty": False})
    result = json.loads(request("GET", f"/exec/{execution['Id']}/json"))
    if result["ExitCode"] != 0:
        raise RuntimeError("Share configuration failed; wait until Samba starts and retry")
    print(
        "Disabled SMB leases in the verification container; new guest sessions see host-created jobs"
    )


def submit(script, timeout):
    name = f"job-{time.time_ns()}"
    jobs = WORK / "shared/jobs"
    (jobs / f"{name}.ps1").write_bytes(Path(script).read_bytes())
    (jobs / f"{name}.json").write_text(json.dumps({"timeout_s": timeout}))
    print(name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["start", "status", "logs", "stop", "submit", "configure-share"]
    )
    parser.add_argument("--host-project")
    parser.add_argument("--script", type=Path)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    if args.action == "start":
        if not args.host_project:
            parser.error("--host-project is required (Docker daemon host path, not container path)")
        start(args.host_project.rstrip("/"))
    elif args.action == "configure-share":
        configure_share()
    elif args.action == "logs":
        logs()
    elif args.action == "submit":
        if not args.script:
            parser.error("--script is required")
        submit(args.script, args.timeout)
    else:
        record, inspect = instance()
        if args.action == "stop":
            request("POST", f"/containers/{record['id']}/stop?t=120")
            print("Stopped exact verification VM; disk and artifacts retained")
        else:
            print(
                json.dumps(
                    {
                        "id": record["id"],
                        "state": inspect["State"],
                        "ports": inspect["NetworkSettings"]["Ports"],
                    },
                    indent=2,
                )
            )


if __name__ == "__main__":
    main()
