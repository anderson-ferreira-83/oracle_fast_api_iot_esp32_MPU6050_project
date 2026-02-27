param(
    [int]$Port = 8000,
    [int]$StartupTimeoutSec = 40,
    [switch]$OpenPages,
    [ValidateSet("http2", "quic", "auto")]
    [string]$Protocol = "http2"
)

$ErrorActionPreference = "Stop"

function Test-Health {
    param([string]$Url)
    try {
        $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
        return ($r.StatusCode -eq 200)
    } catch {
        return $false
    }
}

function Resolve-CloudflaredPath {
    $candidates = @(
        "cloudflared",
        (Join-Path $PSScriptRoot "bin\\cloudflared.exe"),
        "C:\\Program Files\\cloudflared\\cloudflared.exe",
        "$env:USERPROFILE\\cloudflared.exe"
    )

    foreach ($c in $candidates) {
        try {
            if ($c -eq "cloudflared") {
                $cmd = Get-Command cloudflared -ErrorAction Stop
                if ($cmd -and $cmd.Source) { return $cmd.Source }
            } elseif (Test-Path $c) {
                return $c
            }
        } catch {}
    }
    return $null
}

$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $projectRoot

$cloudflaredPath = Resolve-CloudflaredPath
if (-not $cloudflaredPath) {
    Write-Host "[ERRO] cloudflared nao encontrado." -ForegroundColor Red
    Write-Host "Instale em: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/" -ForegroundColor Yellow
    Write-Host "Depois rode novamente este script."
    exit 1
}

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
    for ($i = 1; $i -le $StartupTimeoutSec; $i++) {
        Start-Sleep -Seconds 1
        if (Test-Health -Url $healthUrl) {
            $ok = $true
            break
        }
    }
    if (-not $ok) {
        Write-Host "[ERRO] Backend nao respondeu em $StartupTimeoutSec s." -ForegroundColor Red
        exit 1
    }
}

Write-Host "[APP] OK em $healthUrl" -ForegroundColor Green
Write-Host "[TUNNEL] Abrindo Quick Tunnel..." -ForegroundColor Cyan

$logPath = Join-Path $PSScriptRoot "quick_tunnel.log"
$errLogPath = Join-Path $PSScriptRoot "quick_tunnel.err.log"
if (-not (Test-Path $PSScriptRoot)) { New-Item -ItemType Directory -Path $PSScriptRoot -Force | Out-Null }

# Isola o quick tunnel de qualquer config antiga/named em ~/.cloudflared.
$quickCfgPath = Join-Path $PSScriptRoot "quick_tunnel_config.yml"
if (-not (Test-Path $quickCfgPath)) {
    Set-Content -Path $quickCfgPath -Value "# quick tunnel isolated config`n" -Encoding UTF8
}

try {
    if (Test-Path $logPath) { Remove-Item $logPath -Force -ErrorAction Stop }
    if (Test-Path $errLogPath) { Remove-Item $errLogPath -Force -ErrorAction Stop }
} catch {
    $tag = Get-Date -Format "yyyyMMdd_HHmmss"
    $logPath = Join-Path $PSScriptRoot ("quick_tunnel_{0}.log" -f $tag)
    $errLogPath = Join-Path $PSScriptRoot ("quick_tunnel_{0}.err.log" -f $tag)
    Write-Host "[WARN] Log padrao em uso por outro processo. Usando logs alternativos:"
    Write-Host "       $logPath"
    Write-Host "       $errLogPath"
}

$args = @("--config", $quickCfgPath, "tunnel", "--url", "http://127.0.0.1:$Port", "--no-autoupdate")
if ($Protocol -ne "auto") {
    $args += @("--protocol", $Protocol)
}
$tunnelProc = Start-Process -FilePath $cloudflaredPath `
    -ArgumentList $args `
    -WorkingDirectory $projectRoot `
    -RedirectStandardOutput $logPath `
    -RedirectStandardError $errLogPath `
    -PassThru

$tunnelUrl = $null
for ($i = 1; $i -le 40; $i++) {
    Start-Sleep -Seconds 1
    $text = ""
    if (Test-Path $logPath) {
        $text += (Get-Content -Raw $logPath)
    }
    if (Test-Path $errLogPath) {
        $text += ("`n" + (Get-Content -Raw $errLogPath))
    }

    if ($text) {
        $m = [regex]::Match($text, "https://[a-z0-9\-]+\.trycloudflare\.com")
        if ($m.Success) {
            $tunnelUrl = $m.Value
            break
        }
    }
    if ($tunnelProc.HasExited) { break }
}

if (-not $tunnelUrl) {
    Write-Host "[ERRO] Nao foi possivel obter URL do Quick Tunnel." -ForegroundColor Red
    Write-Host "Verifique os logs: $logPath e $errLogPath"
    exit 1
}

$urlOut = Join-Path $PSScriptRoot "quick_tunnel_url.txt"
Set-Content -Path $urlOut -Value $tunnelUrl -Encoding UTF8

Write-Host ""
Write-Host "[OK] Tunnel ativo: $tunnelUrl" -ForegroundColor Green
Write-Host "[OK] URL salva em: $urlOut"
Write-Host "[INFO] Processo cloudflared PID: $($tunnelProc.Id)"
Write-Host "[INFO] Mantenha esta sessao/servico ativo para o ESP32 continuar acessando."

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
