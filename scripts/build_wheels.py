"""Build/repair one native wheel; never publish, cross-compile, or fake platform tags."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    print("+", " ".join(map(str, args)), flush=True)
    env = os.environ.copy()
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    subprocess.run(list(map(str, args)), check=True, cwd=ROOT, env=env)


def add_notices(wheel, destination, vcpkg):
    """Attach build-library notices and SDK provenance, rewriting wheel RECORD."""
    with zipfile.ZipFile(wheel) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    record = next(name for name in contents if name.endswith(".dist-info/RECORD"))
    prefix = record.rsplit("/", 1)[0] + "/licenses/"
    contents[prefix + "SDK_PROVENANCE.md"] = (ROOT / "vendor/PROVENANCE.md").read_bytes()
    notices = []
    if vcpkg:
        notices = sorted(vcpkg.glob("share/*/copyright"))
    elif sys.platform == "linux":
        for pattern in (
            "libassimp*",
            "libdraco*",
            "libfcl*",
            "libccd*",
            "libompl*",
            "libboost*",
            "libglfw*",
            "libimgui*",
            "libstb*",
            "libtinyxml2*",
            "libeigen3*",
            "zlib*",
            "libglvnd*",
            "libgl1*",
            "libglx*",
            "libopengl*",
            "liboctomap*",
            "libode*",
            "libpugixml*",
            "libminizip*",
        ):
            notices.extend(Path("/usr/share/doc").glob(pattern + "/copyright"))
    if not notices:
        raise RuntimeError(
            "No dependency license notices found; supply --vcpkg-installed or build on supported Debian/Ubuntu"
        )
    for path in notices:
        contents[prefix + path.parent.name + ".txt"] = path.read_bytes()
    manifest = {
        "python": sys.version,
        "platform": sys.platform,
        "vcpkg_baseline": json.loads((ROOT / "vcpkg.json").read_text())["builtin-baseline"],
        "source_wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
    }
    contents[prefix + "BUILD_INPUT.json"] = json.dumps(manifest, indent=2).encode()
    rows = []
    for name, data in sorted(contents.items()):
        if name == record:
            continue
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        rows.append((name, "sha256=" + digest, str(len(data))))
    rows.append((record, "", ""))
    stream = io.StringIO(newline="")
    csv.writer(stream).writerows(rows)
    contents[record] = stream.getvalue().encode()
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in contents.items():
            archive.writestr(name, data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, help="Repair existing raw wheel instead of building")
    parser.add_argument("--output", type=Path, default=ROOT / "wheelhouse")
    parser.add_argument("--platform", help="Linux auditwheel policy, e.g. manylinux_2_35_x86_64")
    parser.add_argument(
        "--vcpkg-installed",
        type=Path,
        help="Windows installed triplet directory (contains bin/share)",
    )
    args = parser.parse_args()
    if sys.platform not in ("linux", "win32"):
        parser.error("Only native Linux x64 and Windows x64 builds are supported")
    if sys.platform == "linux" and not args.platform:
        parser.error(
            "Linux requires an explicit --platform; repair cannot lower the compiled glibc floor"
        )
    if sys.platform == "win32" and not args.vcpkg_installed:
        parser.error("Windows requires --vcpkg-installed with the built x64-windows triplet")
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="iimt-wheel-") as directory:
        temp = Path(directory)
        if args.wheel:
            wheel = args.wheel.resolve()
        else:
            run(
                sys.executable,
                "-m",
                "pip",
                "wheel",
                ".",
                "--no-deps",
                "--no-build-isolation",
                "-w",
                temp,
            )
            wheels = list(temp.glob("iimt_native-*.whl"))
            if len(wheels) != 1:
                raise RuntimeError(f"Expected one new wheel, found {wheels}")
            wheel = wheels[0]
        staging = temp / "notices"
        staging.mkdir()
        prepared = staging / wheel.name
        vcpkg = args.vcpkg_installed.resolve() if args.vcpkg_installed else None
        add_notices(wheel, prepared, vcpkg)
        if sys.platform == "linux":
            run(sys.executable, "-m", "auditwheel", "show", prepared)
            run(
                sys.executable,
                "-m",
                "auditwheel",
                "repair",
                "--plat",
                args.platform,
                "-w",
                args.output,
                prepared,
            )
        else:
            # Vendor SDK is loaded with LoadLibrary, not linked into a .pyd.
            # --analyze-existing is mandatory to include its runtime DLL closure.
            search = os.pathsep.join([str(vcpkg / "bin"), str(ROOT / "vendor/windows")])
            run(
                sys.executable,
                "-m",
                "delvewheel",
                "show",
                "--analyze-existing",
                "--add-path",
                search,
                prepared,
            )
            run(
                sys.executable,
                "-m",
                "delvewheel",
                "repair",
                "--analyze-existing",
                "--no-mangle",
                "iimtcl.dll",
                "--add-path",
                search,
                "-w",
                args.output,
                prepared,
            )
    print(f"Native repair completed in {args.output}; install/runtime tests are still required.")


if __name__ == "__main__":
    main()
