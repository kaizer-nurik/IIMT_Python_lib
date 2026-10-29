# Native Windows verification VM

This is an isolated **real Windows Server 2022 Evaluation guest**, not Wine.
It is a developer/test environment, never a production robot controller.

- Upstream automation: https://github.com/dockur/windows/tree/013ea27498e0e820a46b3861a0fa047d5b19d846
- Pinned image: `dockurr/windows@sha256:16fd7c39a3e48bb946d29c59dc6015942e5b900a1fa5d7e5552053bfc48ee2ea`
- Image OCI revision matches that source, release 6.06. MIT covers automation,
  **not Windows**.
- Official evaluation media: https://www.microsoft.com/en-us/evalcenter/download-windows-server-2022
- Published Microsoft ISO redirect: https://go.microsoft.com/fwlink/p/?LinkID=2195280&clcid=0x409&country=US&culture=en-us
- CPython installer: https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe
- Official VC++ runtime: https://aka.ms/vs/17/release/vc_redist.x64.exe

Windows evaluation has separate Microsoft terms, a 180-day evaluation period and
online activation requirements stated on the Microsoft page. No production license,
redistribution right or account registration is implied. No fake registration is
performed. Do not distribute the ISO/guest disk with this project.

## Isolation

Only `/dev/kvm` is mapped. No privileged mode, NET_ADMIN, TUN, published host ports,
or entire-workspace mount. Guest uses 3 GiB RAM and 2 CPUs, 80 GiB sparse qcow2 disk.
The container has a 4 GiB memory cap. `NETWORK=user` is outbound NAT; testing must use
only localhost mock endpoints, never physical robot IPs. Host folders are restricted
to `.build/windows-vm/{storage,shared,oem,downloads}`. OEM and ISO are read-only.
Ephemeral local credentials live in ignored `.build/windows-vm/credentials.json`
with 0600 permissions and are not printed.

## Bootstrap and job bridge

Copy these three files to `.build/windows-vm/oem/`: `install.bat`, `bootstrap.ps1`,
`agent.ps1`; place the two official installers alongside them. Save the official ISO
as `.build/windows-vm/downloads/server2022-eval.iso` and its SHA256 in `iso.sha256`.
The bootstrap verifies installer Authenticode signatures, installs Python/runtime,
and runs a scheduled task in the logged-in interactive Windows user session.
That permits actual GUI creation instead of accidentally testing session 0.

`agent.ps1` opens **no network listener**. It reads paired `.ps1`/`.json` jobs only
from the explicitly mounted share (`\\host.lan\Data\jobs`) and writes stdout/stderr,
exit code and timestamps to `shared/results`. Treat this share as trusted code.

```bash
python scripts/windows_vm/vm.py start --host-project /path/on/docker/daemon/iimt_native
python scripts/windows_vm/vm.py configure-share  # after Samba starts; before guest jobs
python scripts/windows_vm/vm.py status
python scripts/windows_vm/vm.py logs
python scripts/windows_vm/vm.py submit --script scripts/windows_vm/probe.ps1 --timeout 120
python scripts/windows_vm/vm.py stop
```

`--host-project` must be the Docker daemon host path, which differs from `/workspace`
inside the coding container. A saved exact container ID and label are checked before
status/stop; other containers are untouched. Stop retains disk and artifacts.

The agent writes `shared/agent-ready.json` only after real Windows boots and Python
installation succeeds. A container that is running or an ISO that booted is **not**
evidence of successful Windows wheel execution. Test reports, library imports,
actual SDK/mock runs, planning and GUI evidence are separate gates.

## Software OpenGL for this VM only

The real Windows WGL probe reported `OpenGL 1.1.0 / GDI Generic`, below the
viewer's OpenGL 2.1 requirement. GUI validation therefore uses Mesa llvmpipe from
[mesa-dist-win 26.2.4](https://github.com/pal1000/mesa-dist-win/releases/tag/26.2.4)
in a dedicated test environment. This is a third-party binary distribution of
Mesa, not a Microsoft driver. Its release metadata, download hash and notices are
retained under the ignored VM directory. **Mesa is not included in the library
wheel and no system graphics driver is replaced.** A normal Windows machine with
an OpenGL 2.1+ graphics driver does not need this test-only workaround.

The bridge holds a named mutex to prevent duplicate queue consumers. Guest jobs
have unique IDs. If a guest reboot interrupts a job, its SMB output leases can
remain until the old session disconnects; do not start another bridge to bypass
that wait. Inspect only this container's `smbstatus` when diagnosing it.

`configure-share` disables SMB leases only inside this verification container.
This is necessary because Linux creates queue files outside Samba; otherwise a
Windows directory lease can hide new jobs indefinitely. Run it after each container
start, before using the guest bridge. It never changes host Samba configuration.

For this software-renderer VM, `prepare_clean_env.ps1` creates a clean
`C:\IIMTVerify` venv and copies only Mesa's `opengl32.dll`/`libgallium_wgl.dll` to
its private `mesa` folder. `mesa_sitecustomize.py` preloads that driver in the
venv (including spawned viewer processes). The stock base Python and System32
remain untouched. Stage this helper as `shared/mesa_sitecustomize.py`; retain
Mesa's original archive/readme separately. The GUI test environment must explicitly
report llvmpipe; GDI Generic is not sufficient proof.

`gui_tests.ps1` enables that private preload only for GUI jobs and removes it in
`finally`. `clean_wheel_tests.ps1` and notebook tests explicitly remove the preload,
so native-wheel dependency qualification uses only the repaired wheel and Windows
system DLLs, not Mesa or crossbuild directories on PATH.
