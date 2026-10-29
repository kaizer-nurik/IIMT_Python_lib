# Private file-based job bridge inside the disposable Windows evaluation guest.
# No network listener. Only the explicitly mounted verification share is read.
$ErrorActionPreference = 'Stop'
# Only one interactive bridge may own the queue after a restart or manual recovery.
$AgentMutex = New-Object System.Threading.Mutex($false, 'Local\IIMTVerificationAgent')
if (-not $AgentMutex.WaitOne(0)) { exit 0 }
$Share = '\\host.lan\Data'
$Local = 'C:\IIMTJobs'
New-Item -ItemType Directory -Force $Local | Out-Null
while (-not (Test-Path "$Share\jobs")) { Start-Sleep -Seconds 2 }
$Jobs = "$Share\jobs"
$Results = "$Share\results"
New-Item -ItemType Directory -Force $Results | Out-Null
@{status='ready'; utc=[DateTime]::UtcNow.ToString('o'); os=[Environment]::OSVersion.VersionString; user=$env:USERNAME; python='C:\Python312\python.exe'} | ConvertTo-Json | Set-Content -Encoding UTF8 "$Share\agent-ready.json"
while ($true) {
    if (Test-Path "$Share\stop-agent") { break }
    foreach ($RequestFile in Get-ChildItem $Jobs -Filter '*.json' | Sort-Object Name) {
        $Id = $RequestFile.BaseName
        if ($Id -notmatch '^[a-zA-Z0-9_-]+$') { continue }
        if (Test-Path "$Results\$Id.json") { continue }
        $Started = [DateTime]::UtcNow
        $ExitCode = -1
        $Failure = $null
        try {
            $Request = Get-Content -Raw $RequestFile.FullName | ConvertFrom-Json
            $Script = Join-Path $Jobs "$Id.ps1"
            if (-not (Test-Path $Script)) { continue }
            $Timeout = if ($Request.timeout_s) { [Math]::Min(3600, [Math]::Max(1, [int]$Request.timeout_s)) } else { 600 }
            $LocalScript = Join-Path $Local "$Id.ps1"
            Copy-Item $Script $LocalScript -Force
            @{status='running'; id=$Id; utc=$Started.ToString('o')} | ConvertTo-Json | Set-Content -Encoding UTF8 "$Share\agent-status.json"
            $Process = Start-Process -FilePath "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',$LocalScript) -PassThru -RedirectStandardOutput "$Results\$Id.stdout.txt" -RedirectStandardError "$Results\$Id.stderr.txt"
            # Keep the native process handle open so Windows PowerShell preserves ExitCode.
            $ProcessHandle = $Process.Handle
            if (-not $Process.WaitForExit($Timeout * 1000)) {
                & taskkill.exe /PID $Process.Id /T /F | Out-Null
                $Failure = "Job exceeded $Timeout seconds; its process tree was terminated"
            } else {
                $Process.Refresh()
                $ExitCode = $Process.ExitCode
            }
        } catch { $Failure = $_.Exception.ToString() }
        @{id=$Id; exit_code=$ExitCode; error=$Failure; started_utc=$Started.ToString('o'); finished_utc=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json | Set-Content -Encoding UTF8 "$Results\$Id.json"
    }
    Start-Sleep -Seconds 1
}
