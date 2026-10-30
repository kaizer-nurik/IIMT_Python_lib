# Verification — 2026-10-29

> **Historical CPython 3.12 baseline.** The later Python 3.10–3.15 rebuild replaces
> the wheel files with the same version/ABI names. Current hashes and per-version
> qualification are in [WHEEL_MATRIX.md](WHEEL_MATRIX.md) and
> `wheelhouse/SHA256SUMS`; the hashes and timing measurements below identify the
> earlier artifacts, not a new measurement of every matrix cell.

> **GUI correction, 2026-10-30:** the early Linux GUI checks asserted API return
> values, not rendered pixels. They missed a split-GLdispatch packaging defect
> that produced a black window. They must not be treated as proof of visible
> Linux rendering. See [VIEWER_LINUX.md](VIEWER_LINUX.md) for the reproduction,
> fix and replacement pixel-based checks. This does not invalidate the separate
> controller/SDK tests or the Windows screenshots.

> **Mesh correction, 2026-10-30:** screenshots and pixel checks did not validate
> link orientation. Assimp's automatic COLLADA up-axis conversion rotated the
> visual meshes incorrectly on both platforms. The loader now follows RViz's
> axis-preserving policy; ten numerical regressions cover this defect. Original
> CI05 STL collision geometry and FK were not changed. See
> [VIEWER_MESHES.md](VIEWER_MESHES.md) and the current wheel matrix.

## Earlier tested artifacts

Both wheels are **CPython 3.12, x86-64**, installable without an end-user compiler.
Neither is a renamed artifact from the other operating system.

| Platform | Wheel in `wheelhouse/` | SHA256 |
|---|---|---|
| Linux, glibc >= 2.39 (Ubuntu 24.04) | `iimt_native-0.1.0-cp312-cp312-manylinux_2_39_x86_64.whl` | `f1b3675b6fd8423d34eda66732300f8d7a811b43732b289a7fb369141bc58eaa` |
| Windows x64 | `iimt_native-0.1.0-cp312-cp312-win_amd64.whl` | `88fcf52c3ed0a37a56a8883983bb62de0e3e7e2f97ccf73ccbf9c566857f9e3f` |

Linux wheel ~24 MB; Windows ~29 MB. Each contains native `_control`, `_model`,
`_viewer`, the platform vendor SDK, original CI05 assets, repaired native dependency
closure and notices. The Linux artifact does **not** support Ubuntu 22.04's glibc
2.35. Windows requires the high-resolution waitable timer API (Windows 10 1803+);
actual runtime qualification used **Windows Server 2022 Standard Evaluation,
build 20348, official CPython 3.12.10 AMD64**. Other Python/OS combinations in the
CI recipe have not been separately built/tested in this run.

## Fresh installed-wheel tests

| Environment | Passed | Failed/errors/skipped |
|---|---:|---:|
| Linux clean virtualenv, installed repaired wheel | 70 | 0 |
| Isolated Ubuntu 24.04 runtime container | 70 | 0 |
| Native Windows clean virtualenv, installed repaired wheel | 70 | 0 |

Coverage includes actual manufacturer SDK calls to independent localhost TCP mocks,
not a substituted controller mock branch:

- independent read/send, scheduled/advanced starts, nominal reference timestamps;
- read timeout preserves timestamp; stale state aborts; slow reads do not add an
  extra full idle period after their completion;
- shared dual start/cancel, fault latching, informative stop failure;
- protective-stop release never implicit; opt-in Clear only after successful Stop;
- final target is actually sent even if a preceding sample meets goal tolerance;
- no replay on reconnect; cancellation interrupts a long future start; reader wait
  interrupts on shutdown; Windows timer requests are released;
- joint/array/time/config validation, rate reciprocal and SDK-float underflow guards;
- URDF FK, original meshes, limits, self/inter-arm/world collisions, floor/workspace;
- Unicode URDF directory/file/mesh paths and package URI handling;
- RRTConnect checked edges, sparse geometric waypoints, not stops at every check sample;
- cancel during preflight, invalidated prepared goals, no new work during close;
- stale GUI plans rejected, old results cannot consume newer goal samples;
- shutdown uncertainty surfaced; partial UTC/error plots remain available after abort.

Evidence: `results/wheel-tests.xml`, `results/container-tests.xml`,
`results/windows/windows-tests.xml`. The wheel smoke imports native modules before
explicit ctypes SDK loading, so preloading cannot hide missing runtime dependencies.
Independent final review found no remaining blockers in its timing/lifecycle/path
scope after the Unicode and numeric-bound fixes.

## Isolated runtime evidence

Linux: fresh Ubuntu 24.04 container, **no ROS, compiler, CMake or OMPL/FCL/Assimp
build packages**; ordinary Python/OpenGL/X11 runtime only. Network disconnected
before tests: only localhost mocks reachable. All tests, SDK execution/load smoke
and native Xvfb GUI passed. Exact temporary container removed after testing.
`results/container-install.log`, `results/container-runtime.log`.

Windows: actual locally provisioned KVM guest, **not Wine**, no external Windows
runner or GitHub login. Real AMD64 PE modules cross-built with MinGW and official
Windows CPython headers/import library, then repaired using delvewheel inside the
Windows guest. Clean installed-wheel tests use only venv + Windows system PATH,
no cross-build/vcpkg DLL directories and no Mesa preload. SDK runtime closure is
bundled; user-side compilation is not performed.

GUI only: the VM's stock GDI Generic exposes OpenGL 1.1, so private test-only Mesa
llvmpipe enabled OpenGL 4.6 compatibility. It was removed from non-GUI tests and is
**not in the wheel or System32**. The dual screenshot shows about 4 FPS under
software rendering in this 2-vCPU VM; this is not a GPU performance claim. A normal
OpenGL 2.1+ driver is needed for desktop use. Headless control does not open a GUI.

VM installer signatures and native OS/Python identity were checked. All queued
jobs finished before the exact verification VM was stopped; disk/evidence retained.
No physical robot or unrelated container was touched. Details and reproducible
steps: [DISTRIBUTION.md](DISTRIBUTION.md), `scripts/windows_cross/`,
`scripts/windows_vm/`. Portable Windows logs are indexed in
`results/windows/evidence-index.json`; VM images are excluded from Git/source archives.

## Full CSV at target 125 Hz

121 input points, exactly 4 seconds, positions-only, no invented CSV derivatives.
Actual vendor SDK, external mock, collision preflight, separate RRTConnect approach
and return, shared nominal UTC start. All four executions (six arm traces) below succeeded with **501
commands, zero missed command slots, zero read timeouts and zero timing warnings**
in their captured controller diagnostics.

| OS | Setup/arm | Commands | Mean rate Hz | p99 interval ms | Max interval ms | Last receipt relative to nominal start s |
|---|---|---:|---:|---:|---:|---:|
| Linux | Single | 501 | 125.00075 | 8.06777 | 8.09781 | 4.0001239 |
| Linux | Dual left | 501 | 124.99137 | 8.16128 | 9.22714 | 4.0004103 |
| Linux | Dual right | 501 | 124.99102 | 8.17017 | 9.23048 | 4.0004223 |
| Windows VM | Single | 501 | 125.00272 | 9.12086 | 13.79210 | 4.0004038 |
| Windows VM | Dual left | 501 | 124.99574 | 9.10537 | 15.15090 | 4.0007189 |
| Windows VM | Dual right | 501 | 124.98297 | 9.08891 | 14.85960 | 4.0007189 |

These intervals are recorded at the **mock's TCP receiver**, including its Python
thread/socket scheduling, not only native SDK dispatch jitter. For example, final
Windows controller `max_send_interval` remained below 9.57 ms while receiver maxima
were larger. Both are retained separately; receiver outliers are not relabelled as
controller timing. Actual network/firmware/mechanics are untested. This proves a
best-effort command cadence, not hard realtime, fresh hardware feedback at 125 Hz,
or mechanical tracking accuracy.

Intervals use `perf_counter_ns()` (QPC on Windows) and UTC alignment uses separate
`unix_ns` values. Do not subtract native and Python monotonic clocks with unrelated
epochs. SDK wire ASCII rounds angles to five decimal places.

Evidence: `results/benchmark_summary.json`, `results/wire_*.jsonl`,
`results/single/`, `results/dual/`; Windows counterparts under `results/windows/`,
plus a separate five-second single/dual timing probe in `timing_qpc.json`.
Reproduce: `python scripts/benchmark.py` (localhost only).

## Bugs exposed by native Windows testing

1. Standard timed waits produced only about **80.8 / 82.2 Hz** despite the 125 Hz
   request; `timeBeginPeriod(1)` alone did not fix that. Interruptible high-resolution
   waitable timers now drive Windows timed waits, with explicit cancel/shutdown
   events, no busy-spin and no silently weakened safety thresholds.
2. CPython 3.12 Windows `monotonic_ns()` used coarse GetTickCount64 in this guest;
   it falsely quantized wire intervals to about 15–16 ms. The external mock now uses
   QPC-backed `perf_counter_ns()` for intervals and simulated lag. Native scheduling
   never depends on this Python logging clock.
3. MinGW path resolution corrupted UNC SDK paths; Win32 wide path resolution fixes
   that. TinyXML2 narrow file opening also failed for Cyrillic paths under ACP 1252;
   native-path file reading + UTF-8 XML parsing fixes it. UNC model/relative meshes
   and four Unicode path cases were tested on actual Windows, not inferred from Linux.
4. Very small positive rates and ServoJ a/v values passed earlier validation but
   overflowed periods or underflowed SDK floats. They are now rejected before SDK use.

Before/after evidence is retained under `results/windows/evidence/`. API context:
[Python performance clocks](https://docs.python.org/3.12/library/time.html#time.perf_counter),
[Windows high-resolution waitable timer](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-createwaitabletimerexw).

## Actual notebooks / GUI

The real notebook cells executed in **single and dual mode on both operating
systems**: separate approach, CSV execution, success metadata, 2 / 4 inline PNGs.
Safe RUN flags changed only in test copies, not in the shipped notebook. The
notebook uses global UTC timestamps and still plots partial records after errors.
Executed notebooks are in `results/notebook_*_executed.ipynb` and
`results/windows/notebooks/`; reproduce with `python scripts/notebook_smoke.py`.

Native viewer checks cover cached transforms, 6/12 controls, input validation,
owner thread, close/reopen. Full separate viewer/controller processes were exercised
with the real CI05 meshes; Windows GUI also planned/executed RRTConnect goals against
external mocks. Screenshots: `results/windows/gui/`. Sliders do not send motion.

Ruff, Black100, compileall, notebook syntax, clang-format and scoped Linux/MinGW
syntax checks passed. Build/test scripts and logs are retained; CI recipes were
not passed off as executed workflows.

## Remaining limits

- **No physical robot qualification.** Queue/Stop/Clear semantics, advance, network
  latency and actual tracking must be validated on the user's firmware/stand.
- SDK Stop confirms a protocol state, not an independent physical emergency stop.
  Clear maps to protective-stop release; it is disabled by default. Queue purge is
  explicitly unconfirmed when skipped. No automatic power/brake recovery.
- Collision checks are discrete, not safety certification. Differing per-arm
  advances can leave the checked nominal joint-space line.
- Only compatible single/dual CI05, joint goals; no Cartesian IK, MoveIt TOTG,
  arbitrary hardware drivers or full ROS API compatibility.
- SDK/assets redistribution permission was not established. No public package,
  Windows media or VM image was uploaded; bundled notices do not grant that right.
