param(
    [switch]$SkipSmokeTest
)

$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
}
$RequiredPythonMajor = 3
$RequiredPythonMinor = 13

function New-PythonCandidate {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,

        [string[]]$ArgumentList = @()
    )
    [pscustomobject]@{ FilePath = $FilePath; ArgumentList = $ArgumentList }
}

function Get-PythonVersion {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Python
    )
    $version = & $Python.FilePath @($Python.ArgumentList + @("-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"))
    if ($LASTEXITCODE -ne 0) {
        return $null
    }
    return [string]$version
}

function Format-CommandForLog {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Command
    )
    return (@($Command.FilePath) + @($Command.ArgumentList) | Where-Object { $_ }) -join ' '
}

function Test-CompatiblePython {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Version
    )
    $parts = $Version.Split('.')
    return [int]$parts[0] -eq $RequiredPythonMajor -and [int]$parts[1] -eq $RequiredPythonMinor
}

function Resolve-Python {
    $candidates = @()
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        $candidates += New-PythonCandidate -FilePath $pythonCommand.Source
    }
    $python313Command = Get-Command python3.13 -ErrorAction SilentlyContinue
    if ($python313Command) {
        $candidates += New-PythonCandidate -FilePath $python313Command.Source
    }
    $pyCommand = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCommand) {
        $candidates += New-PythonCandidate -FilePath $pyCommand.Source -ArgumentList @("-3.13")
        $candidates += New-PythonCandidate -FilePath $pyCommand.Source
    }

    $seen = @{}
    foreach ($candidate in $candidates) {
        $key = Format-CommandForLog $candidate
        if ($seen.ContainsKey($key)) { continue }
        $seen[$key] = $true
        if (-not (Test-Path -LiteralPath $candidate.FilePath)) { continue }
        $version = Get-PythonVersion $candidate
        if (-not $version) { continue }
        if (Test-CompatiblePython $version) {
            Write-Host "Using Python $version ($key)"
            return $candidate
        }
        Write-Host "Skipping Python $version ($key); need $RequiredPythonMajor.$RequiredPythonMinor."
    }
    throw "Python $RequiredPythonMajor.$RequiredPythonMinor not found. Install Python only for rebuilding; release\STO_CRM.exe runs without Python."
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Command,

        [string[]]$ArgumentList = @()
    )
    & $Command.FilePath @($Command.ArgumentList + $ArgumentList)
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with code ${LASTEXITCODE}: $(Format-CommandForLog $Command) $($ArgumentList -join ' ')"
    }
}

function Remove-DirectoryIfExists {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}

function Get-FreeTcpPort {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    try {
        $listener.Start()
        return [int]$listener.LocalEndpoint.Port
    }
    finally {
        $listener.Stop()
    }
}

function Write-ReleaseMetadata {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ReleaseDir,

        [Parameter(Mandatory = $true)]
        [string]$ReleaseExe,

        [Parameter(Mandatory = $true)]
        [string]$Repository,

        [Parameter(Mandatory = $true)]
        [string]$Tag
    )

    $config = Get-Content (Join-Path $ProjectRoot "sto_crm\config.py") -Raw
    if ($config -notmatch 'APP_VERSION\s*=\s*"([^"]+)"') { throw "APP_VERSION not found in sto_crm/config.py" }
    $version = $Matches[1]
    if ($Tag -notmatch '^v') { $Tag = "v$Tag" }
    $exe = Get-Item -LiteralPath $ReleaseExe
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $exe.FullName).Hash.ToLowerInvariant()
    "$hash  STO_CRM.exe" | Set-Content -Encoding ASCII (Join-Path $ReleaseDir "STO_CRM.exe.sha256")
    $manifest = [ordered]@{
        version = $version
        tag = $Tag
        name = "СТО CRM $version"
        release_url = "https://github.com/$Repository/releases/tag/$Tag"
        asset = [ordered]@{
            name = "STO_CRM.exe"
            size = $exe.Length
            sha256 = $hash
            download_url = "https://github.com/$Repository/releases/download/$Tag/STO_CRM.exe"
        }
    }
    $manifestJson = $manifest | ConvertTo-Json -Depth 4
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText((Join-Path $ReleaseDir "latest.json"), $manifestJson, $utf8NoBom)
}

function Invoke-ReleaseSmokeTest {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ExePath
    )

    $smokeRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("sto-crm-smoke-" + [System.Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $smokeRoot | Out-Null
    $port = Get-FreeTcpPort
    $dbPath = Join-Path $smokeRoot "smoke.sqlite3"
    $process = $null

    try {
        $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
        $startInfo.FileName = $ExePath
        $startInfo.UseShellExecute = $true
        $startInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
        foreach ($argument in @("--no-browser", "--port", $port.ToString(), "--db", $dbPath)) {
            [void]$startInfo.ArgumentList.Add([string]$argument)
        }
        $process = [System.Diagnostics.Process]::Start($startInfo)
        $baseUrl = "http://127.0.0.1:$port"
        $health = $null

        for ($attempt = 1; $attempt -le 30; $attempt++) {
            if ($process.HasExited) {
                throw "Release smoke test failed: STO_CRM.exe exited early with code $($process.ExitCode)."
            }
            try {
                $health = Invoke-RestMethod -Uri "$baseUrl/api/health" -TimeoutSec 2
                break
            }
            catch {
                Start-Sleep -Milliseconds 500
            }
        }

        if (-not $health -or -not $health.ok) {
            throw "Release smoke test failed: /api/health did not return ok=true."
        }

        $bootstrap = Invoke-RestMethod -Uri "$baseUrl/api/bootstrap" -TimeoutSec 5
        $token = [string]$bootstrap.app.csrf_token
        if ([string]::IsNullOrWhiteSpace($token)) {
            throw "Release smoke test failed: bootstrap response does not contain a CSRF token."
        }

        Invoke-RestMethod -Method Post -Uri "$baseUrl/api/shutdown" -Headers @{ "X-CSRF-Token" = $token } -ContentType "application/json" -Body "{}" -TimeoutSec 5 | Out-Null
        if (-not $process.WaitForExit(10000)) {
            throw "Release smoke test failed: STO_CRM.exe did not stop after /api/shutdown."
        }
    }
    finally {
        if ($process -and -not $process.HasExited) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
        Remove-Item -LiteralPath $smokeRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Push-Location $ProjectRoot
try {
    $python = Resolve-Python
    $sourcePath = Join-Path $ProjectRoot "sto_crm.py"
    $specPath = Join-Path $ProjectRoot "STO_CRM.spec"
    $buildDir = Join-Path $ProjectRoot "build"
    $distDir = Join-Path $ProjectRoot "dist"
    $releaseDir = Join-Path $ProjectRoot "release"
    $distExe = Join-Path $distDir "STO_CRM.exe"
    $releaseExe = Join-Path $releaseDir "STO_CRM.exe"

    Write-Host "Ensuring development and packaging requirements are available (requires internet access unless pip cache already satisfies them)..."
    Invoke-Checked $python @("-m", "pip", "install", "--disable-pip-version-check", "-r", (Join-Path $ProjectRoot "requirements-dev.txt"))

    Invoke-Checked $python @("-m", "compileall", "-q", $sourcePath, (Join-Path $ProjectRoot "sto_crm"), (Join-Path $ProjectRoot "tests"))
    Invoke-Checked $python @("-m", "unittest", "discover", "-v")
    Invoke-Checked $python @("-m", "pytest", "-q")
    Invoke-Checked $python @("-m", "ruff", "check", ".")

    Remove-DirectoryIfExists $buildDir
    Remove-DirectoryIfExists $distDir
    Invoke-Checked $python @("-m", "PyInstaller", "--clean", $specPath)

    if (-not (Test-Path -LiteralPath $distExe)) {
        throw "PyInstaller did not create expected artifact: $distExe"
    }

    New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null
    Get-ChildItem -LiteralPath $releaseDir -Force | Remove-Item -Recurse -Force
    Copy-Item -LiteralPath $distExe -Destination $releaseExe -Force

    $config = Get-Content (Join-Path $ProjectRoot "sto_crm\config.py") -Raw
    if ($config -notmatch 'GITHUB_REPOSITORY\s*=\s*"([^"]+)"') { throw "GITHUB_REPOSITORY not found in sto_crm/config.py" }
    $releaseRepository = $Matches[1]
    if ($config -notmatch 'APP_VERSION\s*=\s*"([^"]+)"') { throw "APP_VERSION not found in sto_crm/config.py" }
    Write-ReleaseMetadata -ReleaseDir $releaseDir -ReleaseExe $releaseExe -Repository $releaseRepository -Tag ("v" + $Matches[1])

    if (-not $SkipSmokeTest) {
        Invoke-ReleaseSmokeTest -ExePath $releaseExe
    }

    $allowedReleaseFiles = @("STO_CRM.exe", "STO_CRM.exe.sha256", "latest.json")
    $unexpected = Get-ChildItem -LiteralPath $releaseDir -File | Where-Object { $allowedReleaseFiles -notcontains $_.Name }
    if ($unexpected) {
        throw "Release directory contains unexpected files: $($unexpected.Name -join ', ')"
    }

    Write-Host "Done: $releaseExe"
}
finally {
    Pop-Location
}
