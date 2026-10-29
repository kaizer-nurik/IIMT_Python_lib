# Run in the genuine Windows guest through vm.py submit. ABI is set in the job wrapper.
param([ValidateSet('310','311','312','313','314','315')][string]$Abi = '310')
$ErrorActionPreference='Stop'
$Share='\\host.lan\Data'
$Work="C:\IIMTMatrix\cp$Abi"
$Out="$Share\python-matrix\results\cp$Abi"
New-Item -ItemType Directory -Force $Work,$Out | Out-Null
Remove-Item "$Out\passed.json" -ErrorAction SilentlyContinue
# All paths below are derived from the validated ABI and confined to this test lane.
foreach ($Name in @('raw','repaired')) {
 if (Test-Path "$Work\$Name") { Remove-Item "$Work\$Name" -Recurse -Force }
}
function Check([string]$Step) { if ($LASTEXITCODE) { throw "$Step failed: $LASTEXITCODE" } }
if (-not (Test-Path "$Work\python\tools\python.exe")) {
 Copy-Item "$Share\python-matrix\cp$Abi\python.nupkg" "$Work\python.zip" -Force
 Expand-Archive "$Work\python.zip" "$Work\python" -Force
}
$Base="$Work\python\tools\python.exe"
& $Base -VV; Check 'interpreter'
& $Base -m venv --clear "$Work\venv"; Check 'venv'
$Python="$Work\venv\Scripts\python.exe"
& $Python -m pip install --upgrade pip; Check 'pip'
& $Python -m pip install delvewheel; Check 'delvewheel'
New-Item -ItemType Directory -Force "$Work\raw" | Out-Null
Copy-Item "$Share\python-matrix\cp$Abi\raw\*" "$Work\raw" -Recurse -Force
$RawWheels=@(Get-ChildItem "$Work\raw\*-cp$Abi-cp$Abi-win_amd64.whl")
if ($RawWheels.Count -ne 1) { throw 'Expected exactly one ABI-matched raw wheel' }
$Raw=$RawWheels[0].FullName
& $Python -m delvewheel repair $Raw --analyze-existing --no-mangle iimtcl.dll --add-path "$Work\raw\cross-dlls;C:\Windows\System32" --include 'msvcp140.dll;vcruntime140.dll;vcruntime140_1.dll' -w "$Work\repaired"; Check 'repair'
$RepairedWheels=@(Get-ChildItem "$Work\repaired\*-cp$Abi-cp$Abi-win_amd64.whl")
if ($RepairedWheels.Count -ne 1) { throw 'Expected exactly one ABI-matched repaired wheel' }
$Wheel=$RepairedWheels[0].FullName
$WheelHash=(Get-FileHash -Algorithm SHA256 $Wheel).Hash.ToLower()
Copy-Item $Wheel $Out -Force
# PyYAML 6.0.3 has no cp315 Windows wheel. Its supported pure-Python build
# avoids requiring a compiler solely for Jupyter's optional YAML acceleration.
if ($Abi -eq '315') {
 $PreviousYamlOption=$env:PYYAML_FORCE_LIBYAML
 try {
  $env:PYYAML_FORCE_LIBYAML='0'
  & $Python -m pip install 'PyYAML==6.0.3'; Check 'pure-Python PyYAML'
 } finally {
  if ($null -eq $PreviousYamlOption) { Remove-Item Env:\PYYAML_FORCE_LIBYAML -ErrorAction SilentlyContinue }
  else { $env:PYYAML_FORCE_LIBYAML=$PreviousYamlOption }
 }
}
& $Python -m pip install "$Wheel[notebook,test]" pillow; Check 'install'
& $Python -m pip check; Check 'pip check'
& $Python -m pip freeze | Set-Content "$Out\packages.txt"
New-Item -ItemType Directory -Force "$Work\project" | Out-Null
Copy-Item "$Share\python-matrix\project\*" "$Work\project" -Recurse -Force
Set-Location "$Work\project"
$env:PATH="$Work\venv\Scripts;C:\Windows\System32;C:\Windows"
Remove-Item Env:\PYTHONPATH -ErrorAction SilentlyContinue
Remove-Item Env:\IIMT_NATIVE_MODULE -ErrorAction SilentlyContinue
Remove-Item Env:\IIMT_TEST_SDK -ErrorAction SilentlyContinue
& $Python scripts\wheel_smoke.py; Check 'wheel SDK/mock smoke'
& $Python -m pytest tests -v -ra "--junitxml=$Out\tests.xml"; Check 'pytest'
& $Python scripts\wheel_smoke.py --junit "$Out\tests.xml"; Check 'zero-skip gate'
Copy-Item "$Share\mesa_sitecustomize.py" "$Work\venv\Lib\site-packages\sitecustomize.py" -Force
try {
 & $Python scripts\gui_probe.py; Check 'native GUI'
 Copy-Item "$Share\gui" "$Out\gui" -Recurse -Force
} finally { Remove-Item "$Work\venv\Lib\site-packages\sitecustomize.py" -ErrorAction SilentlyContinue }
$NotebookPassed=$false
try {
& $Python -m ipykernel install --sys-prefix --name python3; Check 'kernel'
& $Python scripts\notebook_smoke.py; Check 'notebook'
New-Item -ItemType Directory -Force "$Out\notebooks" | Out-Null
Copy-Item results\* "$Out\notebooks" -Recurse -Force
 $NotebookPassed=$true
} catch {
 $_ | Out-String | Set-Content "$Out\notebook-error.txt"
 Write-Warning "Optional notebook smoke failed; see notebook-error.txt"
}
$Status=if ($NotebookPassed) { 'passed' } else { 'native_passed_notebook_failed' }
$NotebookStatus=if ($NotebookPassed) { 'passed' } else { 'failed' }
@{abi=$Abi; status=$Status; mandatory_status='passed'; notebook_status=$NotebookStatus; wheel_sha256=$WheelHash; notebook_passed=$NotebookPassed; utc=[DateTime]::UtcNow.ToString('o'); os=[Environment]::OSVersion.VersionString} | ConvertTo-Json | Set-Content "$Out\passed.json"
