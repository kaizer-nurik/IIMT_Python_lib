"""Verify wheel RECORD, x64 PE machine type, ABI tag and CPython imports."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import tempfile
import zipfile
from pathlib import Path

import pefile
from package_raw import require_pe64


def verify(wheel: Path) -> dict:
    tag = wheel.name.split("-")[-3]
    assert tag.startswith("cp") and tag[2:] in {str(v) for v in range(310, 316)}, tag
    expected_tag = f"{tag}-{tag}-win_amd64"
    assert wheel.name.endswith(expected_tag + ".whl"), wheel
    modules = {}
    with zipfile.ZipFile(wheel) as archive, tempfile.TemporaryDirectory() as temporary:
        names = [info.filename for info in archive.infolist() if not info.is_dir()]
        assert len(names) == len(set(names)), "Duplicate wheel entries"
        record_name = next(n for n in names if n.endswith(".dist-info/RECORD"))
        rows = list(csv.reader(io.StringIO(archive.read(record_name).decode())))
        assert {row[0] for row in rows} == set(names), "Incomplete RECORD"
        for name, digest, size in rows:
            data = archive.read(name)
            if name == record_name:
                assert not digest and not size
            else:
                expected = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
                assert digest == "sha256=" + expected.decode(), name
                assert int(size) == len(data), name
            if name.endswith((".pyd", ".dll")):
                path = Path(temporary) / Path(name).name
                path.write_bytes(data)
                require_pe64(path)
                if name.endswith(".pyd"):
                    assert name.endswith(f".{tag}-win_amd64.pyd"), name
                    # delvewheel may move the import table beyond the range parsed by
                    # GNU objdump; pefile also powers delvewheel's own PE analysis.
                    pe = pefile.PE(str(path))
                    dlls = [entry.dll.decode("ascii") for entry in pe.DIRECTORY_ENTRY_IMPORT]
                    pe.close()
                    assert [d.lower() for d in dlls if "python" in d.lower()] == [
                        f"python{tag[2:]}.dll"
                    ], (name, dlls)
                    modules[name] = dlls
        assert len(modules) == 3, modules
        metadata = archive.read(next(n for n in names if n.endswith(".dist-info/WHEEL")))
        assert f"Tag: {expected_tag}\n".encode() in metadata
    return {
        "wheel": wheel.name,
        "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "tag": expected_tag,
        "record_verified": True,
        "pe_x64_verified": True,
        "modules": modules,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheels", nargs="+", type=Path)
    args = parser.parse_args()
    print(json.dumps([verify(wheel) for wheel in args.wheels], indent=2))
