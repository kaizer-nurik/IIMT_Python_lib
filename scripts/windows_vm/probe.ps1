$ErrorActionPreference = 'Stop'
Write-Output '=== Native Windows environment ==='
Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber,OSArchitecture | Format-List
Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer,Model,TotalPhysicalMemory | Format-List
& C:\Python312\python.exe -c "import sys,platform,ctypes; print(sys.version); print(platform.platform()); print('kernel32=',ctypes.windll.kernel32.GetCurrentProcessId())"
if ($LASTEXITCODE) { exit $LASTEXITCODE }
& C:\Python312\python.exe -m pip --version
if ($LASTEXITCODE) { exit $LASTEXITCODE }
Write-Output 'PASS native Windows Python and Win32 API'
