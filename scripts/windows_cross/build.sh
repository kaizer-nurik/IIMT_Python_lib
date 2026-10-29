#!/usr/bin/env bash
# Native PE cross build only; execution verification is a separate Windows step.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
CACHE=${IIMT_CROSS_CACHE:-/tmp/iimt-win-cross}
PYTHON=${PYTHON:-python3}
BASELINE=$("$PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1]))["builtin-baseline"])' "$ROOT/vcpkg.json")
for tool in x86_64-w64-mingw32-g++ cmake ninja git curl unzip; do
  command -v "$tool" >/dev/null || { echo "Missing build tool: $tool" >&2; exit 1; }
done
mkdir -p "$CACHE/manifest"
if [[ ! -d "$CACHE/vcpkg/.git" ]]; then
  git clone --filter=blob:none --no-checkout https://github.com/microsoft/vcpkg.git "$CACHE/vcpkg"
fi
git -C "$CACHE/vcpkg" checkout "$BASELINE"
[[ -x "$CACHE/vcpkg/vcpkg" ]] || "$CACHE/vcpkg/bootstrap-vcpkg.sh" -disableMetrics
if [[ ! -f "$CACHE/python.nupkg" ]]; then
  curl --fail --location --retry 2 https://www.nuget.org/api/v2/package/python/3.12.10 -o "$CACHE/python.nupkg"
fi
echo "0eb85c2dfccccf1b17352de4c397f69194035b7d37149eacc16f1147d93de3b8  $CACHE/python.nupkg" | sha256sum --check
[[ -f "$CACHE/python/tools/include/Python.h" ]] || unzip -q "$CACHE/python.nupkg" -d "$CACHE/python"
cp "$ROOT/vcpkg.json" "$CACHE/manifest/vcpkg.json"
VCPKG_MAX_CONCURRENCY=${VCPKG_MAX_CONCURRENCY:-2} "$CACHE/vcpkg/vcpkg" install \
  --triplet x64-mingw-dynamic --host-triplet x64-linux \
  --overlay-ports="$ROOT/scripts/windows_cross/ports" \
  --x-manifest-root="$CACHE/manifest" --x-install-root="$CACHE/installed" --clean-after-build
HEADERS=${PYBIND11_HEADERS:-$("$PYTHON" -c 'import pybind11; print(pybind11.get_include())')}
cmake -S "$ROOT/scripts/windows_cross" -B "$CACHE/modules" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_SYSTEM_NAME=Windows \
  -DCMAKE_C_COMPILER=x86_64-w64-mingw32-gcc \
  -DCMAKE_CXX_COMPILER=x86_64-w64-mingw32-g++ \
  -DCMAKE_TOOLCHAIN_FILE="$CACHE/vcpkg/scripts/buildsystems/vcpkg.cmake" \
  -DVCPKG_TARGET_TRIPLET=x64-mingw-dynamic -DVCPKG_HOST_TRIPLET=x64-linux \
  -DVCPKG_INSTALLED_DIR="$CACHE/installed" -DVCPKG_MANIFEST_MODE=OFF \
  -DPYTHON_WINDOWS_ROOT="$CACHE/python/tools" -DPYBIND11_HEADERS="$HEADERS" \
  -DCMAKE_INSTALL_PREFIX="$CACHE/staging"
cmake --build "$CACHE/modules" --parallel "${CMAKE_BUILD_PARALLEL_LEVEL:-2}"
cmake --install "$CACHE/modules"
for binary in "$CACHE/staging/iimt/"*.pyd; do
  file "$binary"
  x86_64-w64-mingw32-objdump -p "$binary" | grep 'DLL Name'
done
echo "PE modules built in $CACHE/staging; NOT yet a verified Windows wheel."
