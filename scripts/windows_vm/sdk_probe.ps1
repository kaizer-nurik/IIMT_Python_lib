$ErrorActionPreference='Stop'
Get-Item C:\Windows\System32\msvcp140.dll,C:\Windows\System32\vcruntime140.dll,C:\Windows\System32\vcruntime140_1.dll | Select-Object FullName,Length
$Script = @'
import ctypes, os, pathlib
paths = ['msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', r'\\host.lan\Data\artifacts\control-tests\vendor\iimtcl.dll']
for path in paths:
    for flags in [None,0,0x1100]:
        try:
            lib = ctypes.WinDLL(path, winmode=flags)
            print('PASS',path,flags,hex(lib._handle))
        except Exception as exc:
            print('FAIL',path,flags,repr(exc))
'@
$Script | Set-Content -Encoding ASCII C:\IIMTJobs\sdk_probe.py
& C:\Python312\python.exe C:\IIMTJobs\sdk_probe.py
exit $LASTEXITCODE
