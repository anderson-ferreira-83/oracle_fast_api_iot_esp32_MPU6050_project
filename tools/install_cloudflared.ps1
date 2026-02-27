param(
    [string]$DestinationDir = "",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Content
    )
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $enc)
}

if (-not $DestinationDir) {
    $DestinationDir = Join-Path $PSScriptRoot "bin"
}

New-Item -ItemType Directory -Path $DestinationDir -Force | Out-Null

$target = Join-Path $DestinationDir "cloudflared.exe"
$tmp = Join-Path $env:TEMP "cloudflared-windows-amd64.exe"
$downloadUrl = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"

if ((Test-Path $target) -and -not $Force) {
    Write-Host "[OK] cloudflared ja existe em: $target"
    try {
        & $target --version
    } catch {}
    exit 0
}

Write-Host "[DL] Baixando cloudflared..."
$downloadErrors = @()
$downloaded = $false

try {
    [Net.ServicePointManager]::SecurityProtocol = `
        [Net.SecurityProtocolType]::Tls12 -bor `
        [Net.SecurityProtocolType]::Tls11 -bor `
        [Net.SecurityProtocolType]::Tls
} catch {}

try {
    Invoke-WebRequest -Uri $downloadUrl -OutFile $tmp
    $downloaded = $true
} catch {
    $downloadErrors += "Invoke-WebRequest: $($_.Exception.Message)"
}

if (-not $downloaded) {
    try {
        Start-BitsTransfer -Source $downloadUrl -Destination $tmp -ErrorAction Stop
        $downloaded = $true
    } catch {
        $downloadErrors += "Start-BitsTransfer: $($_.Exception.Message)"
    }
}

if (-not $downloaded) {
    try {
        $wc = New-Object System.Net.WebClient
        $wc.DownloadFile($downloadUrl, $tmp)
        $downloaded = $true
    } catch {
        $downloadErrors += "WebClient: $($_.Exception.Message)"
    }
}

if (-not $downloaded) {
    throw ("Falha no download de cloudflared. Detalhes: " + ($downloadErrors -join " | "))
}

Copy-Item -Path $tmp -Destination $target -Force
Remove-Item -Path $tmp -Force -ErrorAction SilentlyContinue

if (-not (Test-Path $target)) {
    throw "Falha ao salvar cloudflared em '$target'."
}

Write-Host "[OK] cloudflared instalado em: $target"
try {
    & $target --version
} catch {
    Write-Host "[WARN] Nao foi possivel validar versao: $($_.Exception.Message)"
}

$readmePath = Join-Path $DestinationDir "LEIA_ME_cloudflared.txt"
$txt = @"
cloudflared instalado localmente.

Executavel:
$target

Para usar scripts deste projeto:
1) start_quick_tunnel.ps1
2) setup_named_tunnel.ps1

Se quiser usar no terminal global, adicione ao PATH:
$DestinationDir
"@
Write-Utf8NoBom -Path $readmePath -Content $txt
Write-Host "[OK] Arquivo auxiliar: $readmePath"
