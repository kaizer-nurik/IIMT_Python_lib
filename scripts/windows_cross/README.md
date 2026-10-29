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
