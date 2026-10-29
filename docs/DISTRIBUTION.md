# Binary wheel distribution

## What is and is not verified

The binary matrix covers standard-GIL CPython **3.10–3.15**, **Linux x86_64 and
Windows x64**. Current artifacts, exact interpreter versions and per-ABI results:
[WHEEL_MATRIX.md](WHEEL_MATRIX.md). No compiler is needed by wheel users.
A CMake branch or CI recipe alone is not execution evidence: the Windows artifact
was cross-compiled as real AMD64 PE with MinGW, repaired with delvewheel on native
Windows, and tested on an actual local Windows Server 2022 KVM guest. No external
runner, GitHub credentials or Wine were needed. [VERIFICATION.md](VERIFICATION.md)
retains the earlier single-ABI baseline and hardware limitations; its old hashes
are not the hashes of the newly rebuilt matrix artifacts.

The local Ubuntu 24.04 native dependencies have symbol requirements up to glibc 2.38
and GLIBCXX_3.4.32. Auditwheel selects `manylinux_2_39_x86_64`, not manylinux2014 or
Ubuntu 20.04 compatibility. CI builds on Ubuntu 22.04 and requests
`manylinux_2_35_x86_64`; it fails rather than relabelling an incompatible wheel.
Only the artifact's actual filename and audit report determine its minimum platform.

The unexecuted native CI recipe targets CPython 3.10–3.15 x64. It uses separate clean environments, imports
all native modules, loads the bundled vendor SDK, exercises localhost-only real-SDK
mock control, runs regression tests with **zero skips**, and runs the native GUI
smoke. No compiler is invoked by wheel installation. An OpenGL-capable desktop
session is required for a visible viewer; headless control needs no display.
Windows GUI smoke failure is a real release failure, not a silently skipped check.
The shipped Windows controller uses high-resolution waitable timers (Windows 10
1803+). Server 2022 is the OS actually tested; other Windows editions are not
separately qualified. GUI qualification used a private test-only Mesa llvmpipe
driver because the VM's default GDI Generic exposes only OpenGL 1.1. Mesa is not
bundled in the wheel or installed into System32; a normal GPU driver is preferred.

## Install an existing wheel (no C++ toolchain)

Use a wheel matching your Python/platform tag, from `wheelhouse/` or a successful
private CI artifact. There is no published PyPI release:

```bash
python -m pip install /path/to/iimt_native-0.1.0-cp312-cp312-manylinux_2_39_x86_64.whl
python -m pip install "iimt-native[notebook]" --no-index --find-links /path/to/offline-wheelhouse
```

Replace both `cp312` tags with `cp310`, `cp311`, `cp313`, `cp314` or `cp315` when
using that interpreter, and use `win_amd64` on Windows. These are independently
compiled CPython ABI wheels, not `abi3` or free-threaded (`cp3XYt`) wheels.
Do not install every file using `pip install wheelhouse/*.whl`: most are deliberately
incompatible with the active interpreter/OS. Install exactly its matching file.

The second command is an **offline** example and requires *all* optional dependency
wheels in that directory. With network access, use the wheel filename with the
`[notebook]` extra on the first install instead. Linux system glibc/libstdc++, OS
windowing/OpenGL drivers and Windows OS graphics services are not replaced by the
package. Repair tools bundle non-policy native dependencies; installation still
resolves the Python `numpy` dependency normally.

For **Windows CPython 3.15 with `[notebook]`**, this matrix needed a pure-Python
PyYAML 6.0.3 preinstall because that dependency had no matching Windows wheel.
The tested compiler-free command is in [WHEEL_MATRIX.md](WHEEL_MATRIX.md#установка).
This is a Jupyter dependency workaround, not an `iimt-native` C++ build step.

## Maintainer build: Linux

Ubuntu native prerequisites (build machine only):

```bash
sudo apt-get update
sudo apt-get install -y --no-install-recommends cmake ninja-build g++ pkg-config \
  libompl-dev libfcl-dev libassimp-dev libtinyxml2-dev libeigen3-dev \
  libglfw3-dev libgl1-mesa-dev libimgui-dev \
  libboost-filesystem-dev libboost-serialization-dev libboost-system-dev xvfb xauth
python -m pip install scikit-build-core==1.1.1 pybind11==3.1.0 auditwheel==6.8.2 patchelf==0.19.1.0
# Ubuntu 24.04 development host:
python scripts/build_wheels.py --platform manylinux_2_39_x86_64
# Or repair a previously built wheel without recompilation:
python scripts/build_wheels.py --wheel dist/iimt_native-0.1.0-cp312-cp312-linux_x86_64.whl \
  --platform manylinux_2_39_x86_64
```

`build_wheels.py` builds with the active interpreter, adds dependency notices and
SDK provenance to `.dist-info/licenses`, rewrites RECORD, then invokes auditwheel.
It cannot lower a compiled ABI floor. Keep raw `dist/` separate from repaired
`wheelhouse/`; distribute only a repaired, installation-tested artifact.

For the full Linux matrix, `scripts/linux_matrix/run.py` uses isolated uv-managed
interpreters and fresh test environments; native dependencies above are still
needed on the build host. `scripts/linux_matrix/run_notebooks.py` separately
installs notebook dependencies and qualifies the actual single/dual cells. The build
requires pybind11 >=3.1; the matrix uses its Python 3.15-capable headers rather than
retagging an older extension.

## Maintainer build: Windows

### Without an external Windows runner

The path used for the supplied artifact is documented in
[windows_cross/README.md](../scripts/windows_cross/README.md) and
[windows_vm/README.md](../scripts/windows_vm/README.md):

1. Linux MinGW cross-build, official CPython Windows headers/import library,
   pinned vcpkg dependencies; verify AMD64 PE exports, not ELF retagging.
2. Actual isolated Windows Server Evaluation VM through host KVM; official Python
   installer and Microsoft runtime with checked Authenticode signatures.
3. Native Windows delvewheel repair, clean install without cross-build DLL paths,
   full tests, real vendor SDK against external mocks, GUI/notebooks and cadence.

Evaluation media/license and guest disks are not distributed with the project.
The local VM is a build/test tool, not a supported real-robot control deployment.

`scripts/windows_cross/build_matrix.sh` extends this path to all six ABIs using
pinned official CPython NuGet inputs. Each extension must import the matching
`python3XY.dll`. Repair and execution remain native Windows steps:
`scripts/windows_vm/python_matrix.ps1`. Its mandatory native qualification and
optional long CSV notebook result are separate, hash-bound fields; a timing-guard
abort is retained, not silently labelled a successful notebook run.
The cross-packaging helper needs host Python 3.11+ (`tomllib`); this does not
change the supported target/runtime minimum of Python 3.10.

### Native MSVC build recipe

Use native Windows x64, MSVC 2022 build tools and CMake, Python x64. `vcpkg.json`
pins the native registry baseline to `d4c0a46cb8f63e5c9fa007d13baf1cb3e43bf7e3`.
The workflow checks out that exact vcpkg revision, builds `x64-windows`, and selects
the Visual Studio 2022 generator. Tool versions and all action commits are pinned.
Ubuntu APT package versions come from the runner repositories and are not a fully
bit-reproducible lockfile; audit and native tests are authoritative.

```powershell
# After bootstrap-vcpkg.bat and vcpkg install --triplet x64-windows:
$env:CMAKE_GENERATOR = 'Visual Studio 17 2022'
$env:CMAKE_GENERATOR_PLATFORM = 'x64'
$env:CMAKE_ARGS = '-DCMAKE_TOOLCHAIN_FILE=C:/vcpkg/scripts/buildsystems/vcpkg.cmake -DVCPKG_TARGET_TRIPLET=x64-windows -DVCPKG_INSTALLED_DIR=C:/project/vcpkg_installed'
python -m pip install scikit-build-core==1.1.1 pybind11==3.1.0 delvewheel==1.13.2
python scripts/build_wheels.py --vcpkg-installed C:/project/vcpkg_installed/x64-windows
```

The SDK DLL is already packaged at `iimt/vendor/iimtcl.dll`. Delvewheel uses
`--analyze-existing` to follow its runtime imports, retains its filename, and patches
package initialization for bundled dependencies. A clean installed-wheel smoke
removes developer/vcpkg PATH entries before imports; missing DLLs fail the test.
The manufacturer's Windows SDK behavior is validated through an external mock,
not substituted by the tested Linux SO. If the MSVC redistributable cannot be found
at repair time, fix the build environment/redistributable search path; do not
suppress that missing dependency or declare the wheel standalone.

## Final artifact checks

```bash
# Example for CPython 3.12 on Linux; select matching ABI/platform for other builds.
python3.12 -m venv /tmp/iimt-wheel-test
/tmp/iimt-wheel-test/bin/python -m pip install "./wheelhouse/iimt_native-0.1.0-cp312-cp312-manylinux_2_39_x86_64.whl[test,notebook]"
cd /tmp
/tmp/iimt-wheel-test/bin/python /path/to/repo/scripts/wheel_smoke.py
/tmp/iimt-wheel-test/bin/python -m pytest /path/to/repo/tests --junitxml=/tmp/iimt-wheel.xml
/tmp/iimt-wheel-test/bin/python /path/to/repo/scripts/wheel_smoke.py --junit /tmp/iimt-wheel.xml
xvfb-run -a /tmp/iimt-wheel-test/bin/python /path/to/repo/cpp/viewer/smoke.py
```

Clean virtualenv installation proves absence of Python build-tree imports, but on
a developer host alone does not prove native libraries were all bundled: retain
`auditwheel show`/`delvewheel show` evidence and test on a clean OS/container before
release. Record wheel SHA-256, OS/Python, SDK input hash and test report. Timing
measurements are best-effort OS evidence, not a hard-real-time guarantee.

## References and licensing

- [auditwheel: repair, ABI checks and dynamic-load limitation](https://github.com/pypa/auditwheel)
- [delvewheel: existing/runtime-loaded DLLs and DLL search](https://github.com/adang1345/delvewheel)
- [pinned vcpkg ImGui features](https://github.com/microsoft/vcpkg/blob/d4c0a46cb8f63e5c9fa007d13baf1cb3e43bf7e3/ports/imgui/vcpkg.json)
- [SDK and asset provenance](../vendor/PROVENANCE.md)

Bundled notices are not permission to redistribute the proprietary manufacturer
SDK or model assets. No automatic PyPI publication or GitHub Release upload exists.
