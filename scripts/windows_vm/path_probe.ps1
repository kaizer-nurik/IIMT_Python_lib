$ErrorActionPreference='Stop'
& '\\host.lan\Data\artifacts\control-probe\path_probe.exe' '\\host.lan\Data\artifacts\control-tests\vendor\iimtcl.dll'
& '\\host.lan\Data\artifacts\control-probe\path_probe.exe' 'C:\IIMTTests\iimtcl.dll'
exit $LASTEXITCODE
