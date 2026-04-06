param(
    [string]$EnvTemplate = ".env.ha.windows",
    [string]$EnvTarget = ".env.ha.local",
    [int]$MdServerPort = 19842,
    [switch]$NoBuild,
    [switch]$NoRelay
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
$envTemplatePath = Join-Path $scriptDir $EnvTemplate
$envTargetPath = Join-Path $scriptDir $EnvTarget
$composeFile = Join-Path $scriptDir "docker-compose.ha.yml"
$mdServerScript = Join-Path $repoRoot "runtime\md_tts\md_server.py"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Ensure-Command([string]$CommandName, [string]$InstallHint) {
    if (-not (Get-Command $CommandName -ErrorAction SilentlyContinue)) {
        throw "$CommandName is not installed. $InstallHint"
    }
}

function Sync-EnvFile {
    if (-not (Test-Path $envTemplatePath)) {
        throw "Env template not found: $envTemplatePath"
    }

    Copy-Item -LiteralPath $envTemplatePath -Destination $envTargetPath -Force
    Write-Host "Wrote $envTargetPath" -ForegroundColor Green
}

function Test-MdServerRunning {
    try {
        $tcp = New-Object Net.Sockets.TcpClient
        $iar = $tcp.BeginConnect("127.0.0.1", $MdServerPort, $null, $null)
        $connected = $iar.AsyncWaitHandle.WaitOne(800)
        if ($connected -and $tcp.Connected) {
            $tcp.EndConnect($iar) | Out-Null
            $tcp.Close()
            return $true
        }
        $tcp.Close()
        return $false
    } catch {
        return $false
    }
}

function Start-MdRelay {
    if ($NoRelay) {
        Write-Host "Skipped host md_server startup. Make sure port $MdServerPort already has a live relay." -ForegroundColor Yellow
        return
    }

    if (Test-MdServerRunning) {
        Write-Host "Detected md_server on 127.0.0.1:$MdServerPort. Reusing existing relay." -ForegroundColor Green
        return
    }

    if (-not (Test-Path $mdServerScript)) {
        throw "md_server script not found: $mdServerScript"
    }

    Write-Host "Starting Windows host relay: $mdServerScript $MdServerPort" -ForegroundColor Green
    Start-Process -FilePath "python" `
        -ArgumentList @("-u", $mdServerScript, "$MdServerPort") `
        -WorkingDirectory $repoRoot `
        -WindowStyle Normal | Out-Null

    Start-Sleep -Seconds 3
    if (-not (Test-MdServerRunning)) {
        Write-Host "md_server process was launched, but the port is not ready yet. Check the Python window for login or credential errors." -ForegroundColor Yellow
    }
}

function Start-DockerStack {
    $composeArgs = @("compose", "-f", $composeFile, "--env-file", $envTargetPath, "up", "-d")
    if (-not $NoBuild) {
        $composeArgs += "--build"
    }

    docker @composeArgs
}

Ensure-Command -CommandName "docker" -InstallHint "Install and start Docker Desktop first."
Ensure-Command -CommandName "python" -InstallHint "Install Python first and ensure the `python` command works."

Write-Step "Prepare Windows real-data env file"
Sync-EnvFile

Write-Step "Start host md_server relay"
Start-MdRelay

Write-Step "Start Docker HA stack"
Start-DockerStack

Write-Step "Service endpoints"
Write-Host "Dashboard: http://localhost:18080"
Write-Host "Admin:     http://localhost:18081"
Write-Host ""
Write-Host "Logs:" -ForegroundColor Cyan
Write-Host "docker compose -f `"$composeFile`" --env-file `"$envTargetPath`" logs -f seed worker dashboard admin"
Write-Host ""
Write-Host "If the dashboard has no real ticks, check whether md_server logged in successfully." -ForegroundColor Yellow
