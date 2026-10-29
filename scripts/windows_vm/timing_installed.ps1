$ErrorActionPreference='Stop'
$env:PATH='C:\IIMTVerify\Scripts;C:\Windows\System32;C:\Windows'
Remove-Item Env:\PYTHONPATH,Env:\IIMT_TEST_SDK -ErrorAction SilentlyContinue
Set-Location C:\IIMTVerifyProject
& C:\IIMTVerify\Scripts\python.exe scripts\timing_probe.py
exit $LASTEXITCODE
