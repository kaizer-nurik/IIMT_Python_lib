# Linux-hosted Windows cross-build experiment

This directory builds **real Windows PE extensions**, never renames Linux ELF
artifacts. It is isolated from the normal MSVC/native-Linux wheel build.

Inputs used in the initial experiment:
- Ubuntu MinGW-w64 GCC13 POSIX x64 toolchain.
- Official CPython 3.12.10 NuGet `python` package: Windows Python.h and COFF import library.
- pybind11 headers from the normal build environment.
- Repository-pinned vcpkg baseline, `x64-mingw-dynamic`, host `x64-linux`.

Native target compilation alone is NOT Windows runtime verification. A wheel must
be installed and tested with Windows CPython, preferably in an actual Windows VM.
Wine evidence, if collected, must be identified separately.

Microsoft documents the MinGW cross triplets as community-supported, not covered
by vcpkg's curated CI: https://learn.microsoft.com/en-us/vcpkg/users/platforms/mingw
CPython documents NuGet packages for build/CI use:
https://docs.python.org/3.12/using/windows.html#the-nuget-org-packages

See `build.sh` for reproducible inputs/commands. Do not mix these MinGW C++
dependencies with MSVC-built C++ libraries. The vendor SDK boundary is C ABI
(integers and packed POD), not C++ STL ABI.

The local FCL overlay retains the pinned upstream port and adds only
`-Wa,-mbig-obj` for MinGW. Without extended COFF sections, GCC fails to assemble
FCL collision template instantiations (34,618–49,368 sections). The OMPL overlay uses static linkage on MinGW as on MSVC: its DLL debug
build auto-exports 81,131 symbols, exceeding the PE ordinal limit. All other
packages use the unmodified baseline. Modules and C++ dependency DLLs share the dynamic MinGW
runtime; do not inject MSVC C++ dependency binaries into this build.

```bash
PYTHON=/path/to/python-with-pybind11 ./scripts/windows_cross/build.sh
python scripts/windows_cross/package_raw.py \
  --modules /tmp/iimt-win-cross/staging/iimt \
  --deps /tmp/iimt-win-cross/installed/x64-mingw-dynamic/bin \
  --output /tmp/iimt-win-cross/raw-wheel
```

`package_raw.py` rejects non-AMD64 PE modules, writes valid wheel RECORD hashes,
and stages release dependency DLLs separately. The raw wheel is not portable yet:
repair it using `delvewheel` on Windows, including the installed official Visual
C++ redistributable needed by the vendor DLL. Preserve `iimtcl.dll`'s basename
(`--no-mangle iimtcl.dll`) because the SDK is loaded dynamically. Test the repaired
wheel in a clean Windows virtual environment without the dependency build paths.

Build proof collected on Linux: all `_control`, `_model`, `_viewer` modules are
AMD64 PE32+ DLLs and export their expected `PyInit__*` entry points. The initial raw
wheel contains 140 RECORD entries, all hashes/sizes validated, and no `.so` files.
This is compilation/packaging evidence only; see project release qualification
reports for actual Windows runtime and timing results.

## CPython 3.10–3.15 matrix

`PYTHON=/path/to/host/python scripts/windows_cross/build_matrix.sh` reuses the
native dependency cache populated by `build.sh`, builds each ABI independently
with at most two compiler jobs, and writes raw wheels below
`.build/windows-matrix/cp3XX/raw`. Optional arguments select ABI digits, e.g.
`310 315`. The host Python needs pybind11 3.1+ headers. Official standard x64
CPython NuGet versions and SHA256 pins are in `python_versions.json`; older
security-only Python branches use their last available Windows binary release.
Each target uses its own headers and `python3XX.lib`, never a renamed Linux module
or a renamed CPython ABI. Raw wheels are not release-qualified artifacts.

Stage each target's `python.nupkg` and `raw/` in the VM's private
`shared/python-matrix/cp3XX/`, and the tests/data/notebooks/smoke scripts in
`shared/python-matrix/project/`. Submit `scripts/windows_vm/python_matrix.ps1`
with its ABI parameter set in the submitted script. The real Windows job creates
a target-specific venv, repairs with delvewheel, installs the wheel, checks
SDK/mock operation, runs the full zero-skip pytest gate, then checks the native
viewer using the existing test-only Mesa setup. The optional notebook smoke runs
after these mandatory gates, with the Mesa preload removed. Results and
repaired wheels go to `shared/python-matrix/results/cp3XX/`. Only promote a wheel
after its corresponding job and `passed.json` prove the mandatory native gates
succeeded. Notebook status is reported separately; a failed optional notebook
check is labeled `native_passed_notebook_failed`, never an all-gates pass.

For CPython 3.15 the harness first installs PyYAML 6.0.3 with its supported
`PYYAML_FORCE_LIBYAML=0` build option, scoped to that installation. This Jupyter
dependency has no matching Windows wheel in that release; its pure-Python build
does not need MSVC. The option does not affect the IIMT C++ modules or SDK.
Source URL, SHA256 and the upstream option implementation are recorded in
`results/python-matrix/windows/pyyaml-build-evidence.json`.

`python scripts/windows_cross/verify_wheel.py path/to/repaired.whl` validates all
RECORD hashes/sizes, the wheel ABI tag, x64 PE headers and each module's actual
CPython DLL import, and emits JSON with the wheel SHA256. This validation helper
uses the `pefile` inspection tool (also used by delvewheel), not a runtime project
dependency. GNU objdump can truncate the relocated import table after repair.
