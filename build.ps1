param(
    [switch]$SkipSmokeTest
)

$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
}
$PyInstallerRequirement = "pyinstaller>=6.10,<7"

function Resolve-Python {
    $candidates = @()
    if ($env:LOCALAPPDATA) {
        $candidates += Join-Path $env:LOCALAPPDATA "Python\pythoncore-3.14-64\python.exe"
    }
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        $candidates += $pythonCommand.Source
    }
    $pyCommand = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCommand) {
        $candidates += $pyCommand.Source
    }

    foreach ($candidate in $candidates | Where-Object { $_ } | Select-Object -Unique) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }
    throw "Python not found. Install Python only for rebuilding; release\STO_CRM.exe runs without Python."
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,

        [string[]]$ArgumentList = @()
    )
    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with code ${LASTEXITCODE}: $FilePath $($ArgumentList -join ' ')"
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
        $quotedDbPath = '"' + $dbPath + '"'
        $process = Start-Process -FilePath $ExePath -ArgumentList @("--no-browser", "--port", $port.ToString(), "--db", $quotedDbPath) -PassThru -WindowStyle Hidden
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
    $testPath = Join-Path $ProjectRoot "tests\test_sto_crm.py"
    $specPath = Join-Path $ProjectRoot "STO_CRM.spec"
    $buildDir = Join-Path $ProjectRoot "build"
    $distDir = Join-Path $ProjectRoot "dist"
    $releaseDir = Join-Path $ProjectRoot "release"
    $distExe = Join-Path $distDir "STO_CRM.exe"
    $releaseExe = Join-Path $releaseDir "STO_CRM.exe"

    Write-Host "Ensuring $PyInstallerRequirement is available (requires internet access unless pip cache already satisfies it)..."
    Invoke-Checked $python @("-m", "pip", "install", "--disable-pip-version-check", $PyInstallerRequirement)

    Invoke-Checked $python @("-m", "py_compile", $sourcePath, $testPath)
    Invoke-Checked $python @("-m", "unittest", "discover", "-v")

    Remove-DirectoryIfExists $buildDir
    Remove-DirectoryIfExists $distDir
    Invoke-Checked $python @("-m", "PyInstaller", "--clean", $specPath)

    if (-not (Test-Path -LiteralPath $distExe)) {
        throw "PyInstaller did not create expected artifact: $distExe"
    }

    New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null
    Get-ChildItem -LiteralPath $releaseDir -Force | Remove-Item -Recurse -Force
    Copy-Item -LiteralPath $distExe -Destination $releaseExe -Force

    if (-not $SkipSmokeTest) {
        Invoke-ReleaseSmokeTest -ExePath $releaseExe
    }

    $unexpected = Get-ChildItem -LiteralPath $releaseDir -File | Where-Object { $_.Name -ne "STO_CRM.exe" }
    if ($unexpected) {
        throw "Release directory must contain only STO_CRM.exe. Unexpected files: $($unexpected.Name -join ', ')"
    }

    Write-Host "Done: $releaseExe"
}
finally {
    Pop-Location
}
