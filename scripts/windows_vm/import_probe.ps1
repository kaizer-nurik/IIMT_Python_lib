$ErrorActionPreference = 'Stop'
& C:\Python312\python.exe '\\host.lan\Data\artifacts\control-probe\import_smoke.py'
if ($LASTEXITCODE) { exit $LASTEXITCODE }
