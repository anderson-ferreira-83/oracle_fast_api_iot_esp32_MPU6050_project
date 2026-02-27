param(
    [int]$Port = 8000,
    [switch]$OpenPages = $true,
    [switch]$ForceNewTunnel,
    [ValidateSet("http2", "quic", "auto")]
    [string]$Protocol = "http2"
)

$ErrorActionPreference = "Stop"

function Normalize-HostEntry {
    param([string]$Value)
    $h = [string]$Value
    $h = $h.Trim()
    if ($h.StartsWith("http://")) { $h = $h.Substring(7) }
    elseif ($h.StartsWith("https://")) { $h = $h.Substring(8) }
    if ($h.Contains("/")) { $h = $h.Split("/", 2)[0] }
    return $h.Trim()
}

function Normalize-BaseUrl {
    param([string]$Value)
    $u = [string]$Value
    $u = $u.Trim()
    if (-not $u) { return "" }
    if (-not ($u.StartsWith("http://") -or $u.StartsWith("https://"))) {
        $u = "http://" + $u
    }
    return $u.TrimEnd("/")
}

function Test-UrlHealth {
    param([string]$BaseUrl, [int]$TimeoutSec = 6)
    if (-not $BaseUrl) { return $false }
    try {
        $r = Invoke-WebRequest -Uri ($BaseUrl + "/health") -UseBasicParsing -TimeoutSec $TimeoutSec -ErrorAction Stop
        return ($r.StatusCode -eq 200)
    } catch {
        return $false
    }
}

$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $projectRoot

$quickScript = Join-Path $PSScriptRoot "start_quick_tunnel.ps1"
$applyScript = Join-Path $PSScriptRoot "apply_tunnel_host_to_esp32.ps1"
$urlFile = Join-Path $PSScriptRoot "quick_tunnel_url.txt"
$cfgFile = Join-Path $PSScriptRoot "device_config.json"
$wifiFile = Join-Path $PSScriptRoot "wifi_profiles.json"

if (-not (Test-Path $quickScript)) { throw "Script ausente: $quickScript" }
if (-not (Test-Path $applyScript)) { throw "Script ausente: $applyScript" }
if (-not (Test-Path $cfgFile)) { throw "Arquivo ausente: $cfgFile" }
if (-not (Test-Path $wifiFile)) { throw "Arquivo ausente: $wifiFile" }

$activeUrl = ""
$needNewTunnel = $true

if (-not $ForceNewTunnel -and (Test-Path $urlFile)) {
    $saved = (Get-Content -Raw $urlFile).Trim()
    if ($saved) {
        $savedHttp = (Normalize-BaseUrl $saved) -replace "^https://", "http://"
        $savedHttps = (Normalize-BaseUrl $saved) -replace "^http://", "https://"
        if ((Test-UrlHealth -BaseUrl $savedHttp) -or (Test-UrlHealth -BaseUrl $savedHttps)) {
            $activeUrl = $savedHttp
            $needNewTunnel = $false
            Write-Host "[OK] Tunnel existente ainda ativo: $saved"
        }
    }
}

if ($needNewTunnel) {
    Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 700

    Write-Host "[RUN] Iniciando backend + quick tunnel..."
    if ($OpenPages) {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $quickScript -Port $Port -Protocol $Protocol -OpenPages
    } else {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $quickScript -Port $Port -Protocol $Protocol
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao iniciar quick tunnel."
    }
    if (-not (Test-Path $urlFile)) {
        throw "URL do quick tunnel nao encontrada em $urlFile"
    }
    $activeUrl = (Get-Content -Raw $urlFile).Trim()
    $activeUrl = Normalize-BaseUrl $activeUrl
} elseif ($OpenPages) {
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

$activeHost = Normalize-HostEntry $activeUrl
$cfg = Get-Content -Raw $cfgFile | ConvertFrom-Json
$cfgHost = Normalize-HostEntry ([string]$cfg.server_hostname)

if ($activeHost -and ($cfgHost -ne $activeHost)) {
    Write-Host "[SYNC] URL do tunnel mudou. Atualizando JSON do ESP32..."
    & powershell -NoProfile -ExecutionPolicy Bypass -File $applyScript -TargetHost $activeHost
    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao atualizar JSON do ESP32 com host atual."
    }
    Write-Host ""
    Write-Host "[ATENCAO] Reenvie no Thonny e reinicie ESP32:" -ForegroundColor Yellow
    Write-Host " - /device_config.json"
    Write-Host " - /wifi_profiles.json"
} else {
    Write-Host "[OK] Host do ESP32 ja esta alinhado ao tunnel atual."
}

Write-Host ""
Write-Host "[OK] Backend local: http://127.0.0.1:$Port/health"
Write-Host "[OK] Tunnel atual:  $activeUrl"
