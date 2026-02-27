param(
    [int]$Port = 8000,
    [string]$SerialPort = "",
    [int]$BaudRate = 115200,
    [switch]$OpenPages = $true
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

if ($OpenPages) {
    $pages = @(
        "http://127.0.0.1:$Port/web/control.html",
        "http://127.0.0.1:$Port/web/index.html"
    )
    Write-Host "[WEB] Abrindo paginas locais..." -ForegroundColor Yellow
    foreach ($p in $pages) {
        Start-Process $p
        Write-Host "  -> $p"
    }
}

$bridgeScript = Join-Path $PSScriptRoot "usb_bridge_to_backend.py"
if (-not (Test-Path $bridgeScript)) {
    throw "Arquivo ausente: $bridgeScript"
}

$args = @(
    "-3.11",
    $bridgeScript,
    "--backend-url", "http://127.0.0.1:$Port/api/ingest",
    "--baudrate", [string]$BaudRate
)
if ($SerialPort.Trim()) {
    $args += @("--port", $SerialPort.Trim())
}

Write-Host "[USB] Iniciando bridge USB -> backend..." -ForegroundColor Cyan
Write-Host "[INFO] Comando: py $($args -join ' ')"
Write-Host "[INFO] Pressione Ctrl+C para encerrar o bridge."
& py @args
