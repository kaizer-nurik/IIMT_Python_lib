#!/usr/bin/env bash
# Requires the dependency cache populated by build.sh; creates only raw PE wheels.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
CACHE=${IIMT_CROSS_CACHE:-/tmp/iimt-win-cross}
WORK=${IIMT_MATRIX_WORK:-$ROOT/.build/windows-matrix}
PYTHON=${PYTHON:-python3}
HEADERS=${PYBIND11_HEADERS:-$("$PYTHON" -c 'import pybind11; print(pybind11.get_include())')}
mkdir -p "$WORK"
for abi in ${*:-310 311 312 313 314 315}; do
  read -r version checksum < <("$PYTHON" -c 'import json,sys; p=json.load(open(sys.argv[1]))[sys.argv[2]]; print(p["version"],p["sha256"])' "$ROOT/scripts/windows_cross/python_versions.json" "$abi")
  dir="$WORK/cp$abi"
  mkdir -p "$dir"
  url="https://api.nuget.org/v3-flatcontainer/python/$version/python.$version.nupkg"
  [[ -f "$dir/python.nupkg" ]] || curl --fail --location --retry 2 "$url" -o "$dir/python.nupkg"
  echo "$checksum  $dir/python.nupkg" | sha256sum --check
  sha256sum "$dir/python.nupkg" > "$dir/python.sha256"
  [[ -f "$dir/python/tools/include/Python.h" ]] || unzip -q "$dir/python.nupkg" -d "$dir/python"
  cmake -S "$ROOT/scripts/windows_cross" -B "$dir/modules" -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_SYSTEM_NAME=Windows \
    -DCMAKE_C_COMPILER=x86_64-w64-mingw32-gcc -DCMAKE_CXX_COMPILER=x86_64-w64-mingw32-g++ \
    -DCMAKE_TOOLCHAIN_FILE="$CACHE/vcpkg/scripts/buildsystems/vcpkg.cmake" \
    -DVCPKG_TARGET_TRIPLET=x64-mingw-dynamic -DVCPKG_HOST_TRIPLET=x64-linux \
    -DVCPKG_INSTALLED_DIR="$CACHE/installed" -DVCPKG_MANIFEST_MODE=OFF \
    -DPYTHON_WINDOWS_ROOT="$dir/python/tools" -DPYTHON_ABI="$abi" -DPYBIND11_HEADERS="$HEADERS" \
    -DCMAKE_INSTALL_PREFIX="$dir/staging"
  cmake --build "$dir/modules" --parallel 2
  cmake --install "$dir/modules"
  "$PYTHON" "$ROOT/scripts/windows_cross/package_raw.py" --python-abi "$abi" \
    --modules "$dir/staging/iimt" --deps "$CACHE/installed/x64-mingw-dynamic/bin" --output "$dir/raw"
done
