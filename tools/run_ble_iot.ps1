param(
    [int]$Port = 8000,
    [string]$BleDeviceName = "ESP32-MPU6050-BLE",
    [switch]$NoCommands = $true
)

$ErrorActionPreference = "Stop"

function Test-Health {
    param([string]$Url)
    try {
        $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 4 -ErrorAction Stop
        return ($r.StatusCode -eq 200)
    } catch {
        return $false
    }
}

$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $projectRoot

$healthUrl = "http://127.0.0.1:$Port/health"
if (-not (Test-Health -Url $healthUrl)) {
    Write-Host "[APP] Backend inativo. Iniciando uvicorn..." -ForegroundColor Yellow
    $env:ORACLE_HOST = if ($env:ORACLE_HOST) { $env:ORACLE_HOST } else { "localhost" }
    $env:ORACLE_PORT = if ($env:ORACLE_PORT) { $env:ORACLE_PORT } else { "1521" }
    $env:ORACLE_SERVICE_NAME = if ($env:ORACLE_SERVICE_NAME) { $env:ORACLE_SERVICE_NAME } else { "xepdb1" }
    $env:ORACLE_USER = if ($env:ORACLE_USER) { $env:ORACLE_USER } else { "dersao" }
    $env:ORACLE_PASSWORD = if ($env:ORACLE_PASSWORD) { $env:ORACLE_PASSWORD } else { "986960440" }

    $proc = Start-Process -FilePath "py" `
        -ArgumentList "-3.11 -m uvicorn backend.server:app --host 0.0.0.0 --port $Port --no-access-log" `
        -WorkingDirectory $projectRoot `
        -PassThru
    Write-Host "[APP] PID: $($proc.Id)"

    $ok = $false
    for ($i = 1; $i -le 45; $i++) {
        Start-Sleep -Seconds 1
        if (Test-Health -Url $healthUrl) {
            $ok = $true
            break
        }
    }
    if (-not $ok) {
        throw "Backend nao respondeu em $healthUrl"
    }
}

Write-Host "[APP] OK em $healthUrl" -ForegroundColor Green
Write-Host "[BLE] Iniciando bridge BLE -> backend..." -ForegroundColor Cyan

$bridgeScript = Join-Path $PSScriptRoot "ble_bridge_to_backend.py"
if (-not (Test-Path $bridgeScript)) {
    throw "Arquivo ausente: $bridgeScript"
}

$args = @(
    "-3.11",
    $bridgeScript,
    "--device-name", $BleDeviceName,
    "--backend-url", "http://127.0.0.1:$Port/api/ingest"
)
if ($NoCommands) {
    $args += "--disable-commands"
}

Write-Host "[INFO] Comando: py $($args -join ' ')"
Write-Host "[INFO] Pressione Ctrl+C para encerrar o bridge."
& py @args
