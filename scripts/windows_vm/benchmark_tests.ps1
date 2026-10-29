$ErrorActionPreference='Stop'
$env:PATH='C:\IIMTVerify\Scripts;C:\Windows\System32;C:\Windows'
$env:MPLBACKEND='Agg'
Remove-Item Env:\PYTHONPATH -ErrorAction SilentlyContinue
Set-Location C:\IIMTVerifyProject
& C:\IIMTVerify\Scripts\python.exe scripts\benchmark.py
$Result=$LASTEXITCODE
Copy-Item results '\\host.lan\Data\benchmark-results' -Recurse -Force
exit $Result
