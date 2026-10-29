$ErrorActionPreference = 'Stop'
& C:\Python312\python.exe -m pip install numpy pytest
if ($LASTEXITCODE) { exit $LASTEXITCODE }
$env:PYTHONPATH = '\\host.lan\Data\artifacts\control-v3;\\host.lan\Data\artifacts\control-tests\src'
$env:IIMT_NATIVE_MODULE = '_control'
New-Item -ItemType Directory -Force C:\IIMTTests | Out-Null
Copy-Item '\\host.lan\Data\artifacts\control-tests\vendor\iimtcl.dll' C:\IIMTTests\iimtcl.dll -Force
$env:IIMT_TEST_SDK = 'C:\IIMTTests\iimtcl.dll'
& C:\Python312\python.exe -m pytest '\\host.lan\Data\artifacts\control-tests\tests\test_control_native.py' -v -ra
exit $LASTEXITCODE
