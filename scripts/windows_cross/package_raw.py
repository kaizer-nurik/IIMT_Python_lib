"""Package cross-compiled Windows PE modules. Repair/test on Windows before release."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import shutil
import struct
import subprocess
import zipfile
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[2]


def require_pe64(path: Path) -> None:
    data = path.read_bytes()
    if data[:2] != b"MZ":
        raise ValueError(f"Not a Windows executable: {path}")
    offset = struct.unpack_from("<I", data, 0x3C)[0]
    if (
        data[offset : offset + 4] != b"PE\0\0"
        or struct.unpack_from("<H", data, offset + 4)[0] != 0x8664
    ):
        raise ValueError(f"Not x64 PE: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--modules", type=Path, required=True, help="Directory containing three .pyd modules"
    )
    parser.add_argument("--deps", type=Path, required=True, help="vcpkg release bin directory")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python-abi", choices=[f"3{x}" for x in range(10, 16)], default="312")
    args = parser.parse_args()
    tag = f"cp{args.python_abi}"
    args.output.mkdir(parents=True, exist_ok=True)
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    version = project["version"]
    info = f"iimt_native-{version}.dist-info"
    contents = {}
    for path in (ROOT / "src/iimt").rglob("*"):
        if (
            not path.is_file()
            or "__pycache__" in path.parts
            or path.suffix in {".so", ".pyc", ".pyd"}
        ):
            continue
        contents["iimt/" + path.relative_to(ROOT / "src/iimt").as_posix()] = path.read_bytes()
    for name in ("_control", "_model", "_viewer"):
        binary = args.modules / f"{name}.{tag}-win_amd64.pyd"
        require_pe64(binary)
        imports = subprocess.check_output(
            ["x86_64-w64-mingw32-objdump", "-p", str(binary)], text=True
        )
        python_dlls = {
            line.split(":", 1)[1].strip().lower()
            for line in imports.splitlines()
            if "DLL Name:" in line and "python" in line.lower()
        }
        expected = {f"python{args.python_abi}.dll"}
        if python_dlls != expected:
            raise ValueError(f"Wrong CPython imports in {binary}: {python_dlls} != {expected}")
        contents["iimt/" + binary.name] = binary.read_bytes()
    sdk = ROOT / "vendor/windows/iimtcl.dll"
    require_pe64(sdk)
    contents["iimt/vendor/iimtcl.dll"] = sdk.read_bytes()
    metadata = [
        "Metadata-Version: 2.1",
        "Name: iimt-native",
        f"Version: {version}",
        "Summary: " + project["description"],
        "Requires-Python: " + project["requires-python"],
        "Description-Content-Type: text/markdown",
    ]
    metadata.extend("Requires-Dist: " + item for item in project["dependencies"])
    for extra, dependencies in project["optional-dependencies"].items():
        metadata.append("Provides-Extra: " + extra)
        metadata.extend(f'Requires-Dist: {item}; extra == "{extra}"' for item in dependencies)
    contents[info + "/METADATA"] = (
        "\n".join(metadata) + "\n\n" + (ROOT / "README.md").read_text()
    ).encode()
    contents[info + "/WHEEL"] = (
        f"Wheel-Version: 1.0\nGenerator: iimt-native-windows-cross\nRoot-Is-Purelib: false\nTag: {tag}-{tag}-win_amd64\n".encode()
    )
    contents[info + "/entry_points.txt"] = b"[console_scripts]\niimt-mock = iimt.mock:main\n"
    contents[info + "/licenses/SDK_PROVENANCE.md"] = (ROOT / "vendor/PROVENANCE.md").read_bytes()
    for package in ("gcc-mingw-w64-base", "mingw-w64-common"):
        path = Path("/usr/share/doc") / package / "copyright"
        if path.exists():
            contents[info + "/licenses/" + package + ".txt"] = path.read_bytes()
    for path in args.deps.parent.glob("share/*/copyright"):
        contents[info + "/licenses/" + path.parent.name + ".txt"] = path.read_bytes()
    record = io.StringIO(newline="")
    writer = csv.writer(record)
    for name, data in sorted(contents.items()):
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        writer.writerow((name, "sha256=" + digest, len(data)))
    writer.writerow((info + "/RECORD", "", ""))
    contents[info + "/RECORD"] = record.getvalue().encode()
    wheel = args.output / f"iimt_native-{version}-{tag}-{tag}-win_amd64.whl"
    with zipfile.ZipFile(wheel, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in contents.items():
            archive.writestr(name, data)
    dlls = args.output / "cross-dlls"
    dlls.mkdir(exist_ok=True)
    for path in args.deps.glob("*.dll"):
        require_pe64(path)
        shutil.copy2(path, dlls / path.name)
    for name in ("libgcc_s_seh-1.dll", "libstdc++-6.dll", "libwinpthread-1.dll"):
        path = Path(
            subprocess.check_output(
                ["x86_64-w64-mingw32-g++", "-print-file-name=" + name], text=True
            ).strip()
        )
        require_pe64(path)
        shutil.copy2(path, dlls / name)
    print(f"RAW PE wheel: {wheel}; dependency search directory: {dlls}")
    print(
        "Not release-ready: run delvewheel repair --analyze-existing --no-mangle iimtcl.dll --add-path cross-dlls on Windows, then clean-install tests."
    )


if __name__ == "__main__":
    main()
