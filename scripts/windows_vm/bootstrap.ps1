$ErrorActionPreference = 'Stop'
$Log = 'C:\OEM\bootstrap.log'
Start-Transcript -Path $Log -Force
try {
    foreach ($Installer in @('python-3.12.10-amd64.exe','vc_redist.x64.exe')) {
        $Signature = Get-AuthenticodeSignature "C:\OEM\$Installer"
        if ($Signature.Status -ne 'Valid') { throw "Invalid Authenticode signature on $Installer : $($Signature.Status)" }
        Write-Output "$Installer verified signer: $($Signature.SignerCertificate.Subject)"
    }
    $Runtime = Start-Process 'C:\OEM\vc_redist.x64.exe' -ArgumentList '/install /quiet /norestart' -PassThru -Wait
    if ($Runtime.ExitCode -notin @(0,3010,1638)) { throw "VC runtime installation failed $($Runtime.ExitCode)" }
    $Python = Start-Process 'C:\OEM\python-3.12.10-amd64.exe' -ArgumentList '/quiet InstallAllUsers=1 TargetDir=C:\Python312 Include_test=0 Include_launcher=0 PrependPath=0' -PassThru -Wait
    if ($Python.ExitCode -notin @(0,3010)) { throw "Python installation failed $($Python.ExitCode)" }
    & C:\Python312\python.exe --version
    if ($LASTEXITCODE -ne 0) { throw 'Installed Python failed' }
    # Run in the logged-in interactive user session so GUI tests are genuine.
    $Action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -ExecutionPolicy Bypass -File C:\OEM\agent.ps1'
    $Trigger = New-ScheduledTaskTrigger -AtLogOn
    $Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
    Register-ScheduledTask -TaskName 'IIMTVerificationAgent' -Action $Action -Trigger $Trigger -Principal $Principal -Force | Out-Null
    Start-ScheduledTask -TaskName 'IIMTVerificationAgent'
    Write-Output 'IIMT file-based verification bridge started'
} catch {
    $_ | Out-String | Add-Content $Log
    throw
} finally {
    Stop-Transcript
    $Share='\\host.lan\Data'
    if (Test-Path $Share) { Copy-Item $Log "$Share\bootstrap.log" -Force }
}
