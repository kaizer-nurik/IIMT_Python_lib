$ErrorActionPreference='Stop'
Remove-Item C:\IIMTVerify\Lib\site-packages\sitecustomize.py -ErrorAction SilentlyContinue
$env:PATH='C:\IIMTVerify\Scripts;C:\Windows\System32;C:\Windows'
Remove-Item Env:\PYTHONPATH -ErrorAction SilentlyContinue
Set-Location C:\IIMTVerifyProject
& C:\IIMTVerify\Scripts\python.exe -m ipykernel install --sys-prefix --name python3
if ($LASTEXITCODE) { exit $LASTEXITCODE }
& C:\IIMTVerify\Scripts\python.exe scripts\notebook_smoke.py
$Result=$LASTEXITCODE
if (Test-Path results) { Copy-Item results '\\host.lan\Data\notebook-results' -Recurse -Force }
exit $Result
