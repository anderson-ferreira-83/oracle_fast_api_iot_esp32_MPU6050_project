param(
    [int]$Port = 8000,
    [ValidateSet("http2", "quic", "auto")]
    [string]$Protocol = "http2"
)

$ErrorActionPreference = "Stop"

$installScript = Join-Path $PSScriptRoot "install_cloudflared.ps1"
$quickScript = Join-Path $PSScriptRoot "start_quick_tunnel.ps1"
$applyScript = Join-Path $PSScriptRoot "apply_tunnel_host_to_esp32.ps1"
$urlFile = Join-Path $PSScriptRoot "quick_tunnel_url.txt"

if (-not (Test-Path $installScript)) { throw "Script ausente: $installScript" }
if (-not (Test-Path $quickScript)) { throw "Script ausente: $quickScript" }
if (-not (Test-Path $applyScript)) { throw "Script ausente: $applyScript" }

Write-Host "[1/3] Instalando cloudflared (se necessario)..."
& powershell -NoProfile -ExecutionPolicy Bypass -File $installScript
if ($LASTEXITCODE -ne 0) { throw "Falha na instalacao do cloudflared." }

Write-Host "[2/3] Subindo backend + quick tunnel..."
& powershell -NoProfile -ExecutionPolicy Bypass -File $quickScript -Port $Port -Protocol $Protocol
if ($LASTEXITCODE -ne 0) { throw "Falha ao abrir quick tunnel." }

if (-not (Test-Path $urlFile)) {
    throw "URL do quick tunnel nao encontrada em $urlFile"
}

$url = (Get-Content -Raw $urlFile).Trim()
if (-not $url) {
    throw "Arquivo de URL do quick tunnel vazio."
}

Write-Host "[3/3] Aplicando host no ESP32 config..."
& powershell -NoProfile -ExecutionPolicy Bypass -File $applyScript -TargetHost $url
if ($LASTEXITCODE -ne 0) { throw "Falha ao aplicar host no config do ESP32." }

Write-Host ""
Write-Host "[OK] Quick tunnel pronto: $url" -ForegroundColor Green
Write-Host "[OK] Configs atualizados:"
Write-Host " - tools/device_config.json"
Write-Host " - tools/wifi_profiles.json"
Write-Host ""
Write-Host "Proximo passo: copiar esses 2 arquivos para o ESP32 via Thonny."
