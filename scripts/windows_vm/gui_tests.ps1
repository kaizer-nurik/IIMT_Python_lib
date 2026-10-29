$ErrorActionPreference='Stop'
$env:PATH='C:\IIMTVerify\Scripts;C:\Windows\System32;C:\Windows'
Remove-Item Env:\PYTHONPATH -ErrorAction SilentlyContinue
Set-Location C:\IIMTVerifyProject
Copy-Item '\\host.lan\Data\mesa_sitecustomize.py' C:\IIMTVerify\Lib\site-packages\sitecustomize.py -Force
try {
    & C:\IIMTVerify\Scripts\python.exe scripts\gui_probe.py
    $Result=$LASTEXITCODE
} finally {
    Remove-Item C:\IIMTVerify\Lib\site-packages\sitecustomize.py -ErrorAction SilentlyContinue
}
exit $Result
