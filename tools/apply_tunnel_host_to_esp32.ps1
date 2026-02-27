param(
    [Parameter(Mandatory = $true)]
    [Alias("HostName")]
    [string]$TargetHost,

    [string]$DeviceConfigPath = "",
    [string]$WifiProfilesPath = "",
    [switch]$KeepFallbackIps
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

function Set-JsonProp {
    param(
        [Parameter(Mandatory = $true)]$Obj,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)]$Value
    )
    if ($Obj.PSObject.Properties.Name -contains $Name) {
        $Obj.$Name = $Value
    } else {
        $Obj | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
    }
}

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Content
    )
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $enc)
}

$cleanHost = Normalize-HostEntry -Value $TargetHost
if (-not $cleanHost) {
    throw "Host invalido."
}

if (-not $DeviceConfigPath) {
    $DeviceConfigPath = Join-Path $PSScriptRoot "device_config.json"
}
if (-not $WifiProfilesPath) {
    $WifiProfilesPath = Join-Path $PSScriptRoot "wifi_profiles.json"
}

if (-not (Test-Path $DeviceConfigPath)) {
    throw "Arquivo nao encontrado: $DeviceConfigPath"
}
if (-not (Test-Path $WifiProfilesPath)) {
    throw "Arquivo nao encontrado: $WifiProfilesPath"
}

$cfg = Get-Content -Raw $DeviceConfigPath | ConvertFrom-Json
$profiles = Get-Content -Raw $WifiProfilesPath | ConvertFrom-Json

if (-not ($profiles -is [System.Collections.IEnumerable])) {
    throw "wifi_profiles.json invalido (esperado lista)."
}

Set-JsonProp -Obj $cfg -Name "server_hostname" -Value $cleanHost
Set-JsonProp -Obj $cfg -Name "boot_require_server_probe" -Value $false

if (-not $KeepFallbackIps) {
    Set-JsonProp -Obj $cfg -Name "server_fallback_ip" -Value ""
    Set-JsonProp -Obj $cfg -Name "server_fallback_ips" -Value @()
}

$defaultProfiles = @()
if ($cfg.PSObject.Properties.Name -contains "default_wifi_profiles" -and $cfg.default_wifi_profiles) {
    foreach ($p in $cfg.default_wifi_profiles) {
        if (-not $p) { continue }
        $ssid = [string]$p.ssid
        if (-not $ssid) { continue }
        $entry = [ordered]@{
            ssid = $ssid
            password = [string]$p.password
            server_ip = $cleanHost
        }
        $defaultProfiles += [pscustomobject]$entry
    }
}
if ($defaultProfiles.Count -gt 0) {
    Set-JsonProp -Obj $cfg -Name "default_wifi_profiles" -Value $defaultProfiles
}

$newProfiles = @()
foreach ($p in $profiles) {
    if (-not $p) { continue }
    $ssid = [string]$p.ssid
    if (-not $ssid) { continue }
    $entry = [ordered]@{
        ssid = $ssid
        password = [string]$p.password
        server_ip = $cleanHost
    }
    $newProfiles += [pscustomobject]$entry
}
if ($newProfiles.Count -eq 0) {
    throw "wifi_profiles.json ficou vazio apos normalizacao."
}

$cfgJson = $cfg | ConvertTo-Json -Depth 32
$profilesJson = $newProfiles | ConvertTo-Json -Depth 8
Write-Utf8NoBom -Path $DeviceConfigPath -Content $cfgJson
Write-Utf8NoBom -Path $WifiProfilesPath -Content $profilesJson

Write-Host "[OK] device_config atualizado: $DeviceConfigPath"
Write-Host "[OK] wifi_profiles atualizado: $WifiProfilesPath"
Write-Host "[OK] Host aplicado: $cleanHost"
if ($KeepFallbackIps) {
    Write-Host "[INFO] Fallback IPs locais preservados."
} else {
    Write-Host "[INFO] Fallback IPs locais limpos para forcar uso do tunnel."
}
