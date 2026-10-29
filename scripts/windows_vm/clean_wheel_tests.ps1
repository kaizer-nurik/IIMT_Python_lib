$ErrorActionPreference='Stop'
$Python='C:\IIMTVerify\Scripts\python.exe'
Remove-Item C:\IIMTVerify\Lib\site-packages\sitecustomize.py -ErrorAction SilentlyContinue
$Project='C:\IIMTVerifyProject'
New-Item -ItemType Directory -Force $Project | Out-Null
Copy-Item '\\host.lan\Data\artifacts\project\*' $Project -Recurse -Force
Remove-Item Env:\PYTHONPATH -ErrorAction SilentlyContinue
Remove-Item Env:\IIMT_NATIVE_MODULE -ErrorAction SilentlyContinue
Remove-Item Env:\IIMT_TEST_SDK -ErrorAction SilentlyContinue
$env:PATH='C:\IIMTVerify\Scripts;C:\Windows\System32;C:\Windows'
Set-Location $Project
& $Python scripts\wheel_smoke.py
if ($LASTEXITCODE) { exit $LASTEXITCODE }
& $Python -m pytest tests -v -ra --junitxml=windows-tests.xml
if ($LASTEXITCODE) { Copy-Item windows-tests.xml '\\host.lan\Data\windows-tests.xml' -Force; exit $LASTEXITCODE }
& $Python scripts\wheel_smoke.py --junit windows-tests.xml
$Result=$LASTEXITCODE
Copy-Item windows-tests.xml '\\host.lan\Data\windows-tests.xml' -Force
exit $Result
