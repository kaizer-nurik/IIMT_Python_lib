$ErrorActionPreference='Stop'
$Source='\\host.lan\Data\artifacts\wheels'
$Work='C:\IIMTWheels'
New-Item -ItemType Directory -Force "$Work\raw","$Work\repaired","$Work\cross-dlls" | Out-Null
Copy-Item "$Source\*.whl" "$Work\raw" -Force
Copy-Item "$Source\cross-dlls\*" "$Work\cross-dlls" -Recurse -Force
$Wheel=(Get-ChildItem "$Work\raw\*.whl" | Select-Object -First 1).FullName
& C:\Python312\python.exe -m delvewheel repair $Wheel --analyze-existing --no-mangle iimtcl.dll --add-path "$Work\cross-dlls;C:\Windows\System32" --include 'msvcp140.dll;vcruntime140.dll;vcruntime140_1.dll' -w "$Work\repaired"
if ($LASTEXITCODE) { exit $LASTEXITCODE }
New-Item -ItemType Directory -Force '\\host.lan\Data\repaired-wheels' | Out-Null
Copy-Item "$Work\repaired\*.whl" '\\host.lan\Data\repaired-wheels' -Force
$Repaired=(Get-ChildItem "$Work\repaired\*.whl" | Select-Object -First 1).FullName
& C:\IIMTVerify\Scripts\python.exe -m pip install "$Repaired[notebook,test]"
exit $LASTEXITCODE
