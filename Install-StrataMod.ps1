param([switch]$Check)
$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$Python = Join-Path (Split-Path $Root -Parent) 'Strata\.venv\Scripts\python.exe'
$Target = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.local\bin\StrataMod.cmd'
$Data = Join-Path (Split-Path $Root -Parent) 'Strata-data'
$LockPaths = @((Join-Path $Data 'records\cli-operation.lock'), (Join-Path $Data 'records\runtime.lock'))
$Bytes = [Text.Encoding]::ASCII.GetBytes("@echo off`r`ncall `"$(Join-Path $Root 'StrataMod.cmd')`" %*`r`nexit /b %errorlevel%`r`n")
$Hasher = [Security.Cryptography.SHA256]::Create()
try { $ExpectedSha = ([BitConverter]::ToString($Hasher.ComputeHash($Bytes))).Replace('-', '').ToLowerInvariant() }
finally { $Hasher.Dispose() }
$ExpectedLength = $Bytes.Length
$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$Admin = ([Security.Principal.WindowsPrincipal]::new($Identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Write-Host "[StrataMod] Native writer user=$($Identity.Name), administrator-token-active=$Admin; fixed $ExpectedLength bytes"

function Invoke-FixedGuard {
    # Only this fixed script was loaded with process Bypass. Child checks and
    # their existing profile-enabled shell lookups inherit the caller's policy.
    $WriterPolicy = [Environment]::GetEnvironmentVariable('PSExecutionPolicyPreference', 'Process')
    try {
        if ($env:STRATAMOD_INSTALL_PRIOR_POLICY_PRESENT -eq '1') {
            $env:PSExecutionPolicyPreference = $env:STRATAMOD_INSTALL_PRIOR_POLICY_VALUE
        } else {
            [Environment]::SetEnvironmentVariable('PSExecutionPolicyPreference', $null, 'Process')
        }
        $Text = & $Python -B -X utf8 -m local_runtime.normal_runtime install-guard
        if ($LASTEXITCODE -ne 0) { throw "Read-only Python guard failed ($LASTEXITCODE); no launch file written" }
        return (($Text -join "`n") | ConvertFrom-Json)
    } finally {
        [Environment]::SetEnvironmentVariable('PSExecutionPolicyPreference', $WriterPolicy, 'Process')
    }
}

function Assert-FixedBytes {
    if ([IO.Directory]::Exists($Target)) { throw 'Fixed launch target is a directory' }
    if (-not [IO.File]::Exists($Target)) { return $false }
    $Info = [IO.FileInfo]::new($Target)
    if (($Info.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $Info.Length -ne $ExpectedLength) {
        throw 'Foreign/reparse launch target; no overwrite'
    }
    $Hash = [Security.Cryptography.SHA256]::Create()
    try { $Actual = ([BitConverter]::ToString($Hash.ComputeHash([IO.File]::ReadAllBytes($Target)))).Replace('-', '').ToLowerInvariant() }
    finally { $Hash.Dispose() }
    if ($Actual -ne $ExpectedSha) { throw 'Foreign launch target bytes; no overwrite' }
    return $true
}

$Streams = [Collections.Generic.List[IO.FileStream]]::new()
$ExitCode = 0
try {
    Set-Location -LiteralPath $Root
    foreach ($Path in $LockPaths) {
        $Stream = [IO.FileStream]::new($Path, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::ReadWrite)
        try {
            if ($Stream.Length -lt 1) { throw 'Existing shared lock is empty' }
            $Stream.Lock(0, 1)
        } catch { $Stream.Dispose(); throw }
        $Streams.Add($Stream)
    }
    $Guard = Invoke-FixedGuard
    if ($Guard.status -ne 'checked' -or $Guard.shim -ne $Target -or $Guard.bytes -ne $ExpectedLength -or $Guard.sha256 -ne $ExpectedSha -or $Guard.asset_body_digest_calls -ne 0) {
        throw 'Fixed read-only guard result mismatch; no launch file written'
    }
    $Parent = [IO.DirectoryInfo]::new([IO.Path]::GetDirectoryName($Target))
    while ($null -ne $Parent) {
        if (-not $Parent.Exists -or ($Parent.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Launch directory missing/reparse; no change' }
        $Parent = $Parent.Parent
    }
    $Already = Assert-FixedBytes
    if (-not $Check -and -not $Already) {
        $Out = [IO.FileStream]::new($Target, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        try { $Out.Write($Bytes, 0, $Bytes.Length); $Out.Flush($true) }
        finally { $Out.Dispose() }
        if (-not (Assert-FixedBytes)) { throw 'Launch file readback failed' }
    }
    $Status = if ($Check) { 'checked' } elseif ($Already) { 'already-installed' } else { 'installed' }
    [pscustomobject]@{status=$Status;target=$Target;bytes=$ExpectedLength;sha256=$ExpectedSha;written=(-not $Check -and -not $Already);writer_pid=$PID;writer_user=$Identity.Name;administrator_token_active=$Admin;generation_requests=0} | ConvertTo-Json
} catch {
    Write-Error $_ -ErrorAction Continue
    $ExitCode = 1
} finally {
    for ($Index=$Streams.Count-1; $Index -ge 0; $Index--) {
        try { $Streams[$Index].Unlock(0, 1) } finally { $Streams[$Index].Dispose() }
    }
}
exit $ExitCode
