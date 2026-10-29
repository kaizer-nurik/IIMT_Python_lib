$ErrorActionPreference = 'Stop'
$env:PYTHONPATH = '\\host.lan\Data\artifacts\control-v3;\\host.lan\Data\artifacts\control-tests\src'
$env:IIMT_NATIVE_MODULE = '_control'
$env:IIMT_TEST_SDK = 'C:\IIMTTests\iimtcl.dll'
& C:\Python312\python.exe '\\host.lan\Data\artifacts\control-tests\timing_probe.py'
exit $LASTEXITCODE
