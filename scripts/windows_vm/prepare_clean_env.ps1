$ErrorActionPreference='Stop'
if (-not (Test-Path C:\IIMTVerify\Scripts\python.exe)) {
    & C:\Python312\python.exe -m venv C:\IIMTVerify
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
}
# Test-only Mesa in this venv. Windows venv launchers execute the base Python,
# so preload via sitecustomize rather than replace a System32 or base-Python DLL.
New-Item -ItemType Directory -Force C:\IIMTVerify\mesa | Out-Null
$Mesa='\\host.lan\Data\artifacts\mesa\x64'
Copy-Item "$Mesa\opengl32.dll","$Mesa\libgallium_wgl.dll" C:\IIMTVerify\mesa -Force
Copy-Item '\\host.lan\Data\mesa_sitecustomize.py' C:\IIMTVerify\Lib\site-packages\sitecustomize.py -Force
Remove-Item C:\IIMTVerify\Scripts\opengl32.dll,C:\IIMTVerify\Scripts\libgallium_wgl.dll -ErrorAction SilentlyContinue
try {
    & C:\IIMTVerify\Scripts\python.exe '\\host.lan\Data\artifacts\gl_probe.py'
    $Result=$LASTEXITCODE
} finally {
    Remove-Item C:\IIMTVerify\Lib\site-packages\sitecustomize.py -ErrorAction SilentlyContinue
}
exit $Result
