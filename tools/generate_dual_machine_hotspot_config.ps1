param(
    [Parameter(Mandatory = $true)]
    [string]$HotspotSsidA,

    [Parameter(Mandatory = $true)]
    [string]$HotspotPasswordA,

    [Parameter(Mandatory = $true)]
    [string]$HotspotSsidB,

    [Parameter(Mandatory = $true)]
    [string]$HotspotPasswordB,

    [string]$ServerIp = "",
    [string]$ServerIpA = "",
    [string]$ServerIpB = "",
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"

if ($HotspotPasswordA.Length -lt 8 -or $HotspotPasswordB.Length -lt 8) {
    throw "As senhas do hotspot devem ter pelo menos 8 caracteres."
}

if (-not $OutputDir) {
    $OutputDir = Join-Path $PSScriptRoot "dual_machine_config_out"
}

if (-not $ServerIp -and -not $ServerIpA -and -not $ServerIpB) {
    $ServerIp = "192.168.137.1:8000"
}

$effectiveServerIpA = if ($ServerIpA) { $ServerIpA } elseif ($ServerIp) { $ServerIp } else { "" }
$effectiveServerIpB = if ($ServerIpB) { $ServerIpB } elseif ($ServerIp) { $ServerIp } else { "" }

if (-not $effectiveServerIpA -or -not $effectiveServerIpB) {
    throw "Defina ServerIp (unico) ou ServerIpA e ServerIpB."
}

$templatePath = Join-Path $PSScriptRoot "device_config.json"
if (-not (Test-Path $templatePath)) {
    $templatePath = Join-Path $PSScriptRoot "device_config.example.json"
}
if (-not (Test-Path $templatePath)) {
    throw "Nao foi encontrado template de device_config em tools/."
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

$cfg = Get-Content -Path $templatePath -Raw | ConvertFrom-Json

$profiles = @(
    [pscustomobject]@{
        ssid = $HotspotSsidA
        password = $HotspotPasswordA
        server_ip = $effectiveServerIpA
    },
    [pscustomobject]@{
        ssid = $HotspotSsidB
        password = $HotspotPasswordB
        server_ip = $effectiveServerIpB
    }
)

Set-JsonProp -Obj $cfg -Name "ssid" -Value $HotspotSsidA
Set-JsonProp -Obj $cfg -Name "password" -Value $HotspotPasswordA
Set-JsonProp -Obj $cfg -Name "wifi_profile_file" -Value "/wifi_profiles.json"
Set-JsonProp -Obj $cfg -Name "server_hostname" -Value ""
Set-JsonProp -Obj $cfg -Name "server_fallback_ip" -Value $effectiveServerIpA
Set-JsonProp -Obj $cfg -Name "server_fallback_ips" -Value @($effectiveServerIpA, $effectiveServerIpB)
Set-JsonProp -Obj $cfg -Name "default_wifi_profiles" -Value $profiles
Set-JsonProp -Obj $cfg -Name "network_revision_file" -Value "/last_network_revision.txt"

New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

$deviceConfigPath = Join-Path $OutputDir "device_config.json"
$wifiProfilesPath = Join-Path $OutputDir "wifi_profiles.json"
$readmePath = Join-Path $OutputDir "LEIA_ME_TESTE_MAQUINA_A_B.txt"

$cfgJson = $cfg | ConvertTo-Json -Depth 32
$profilesJson = $profiles | ConvertTo-Json -Depth 8
Write-Utf8NoBom -Path $deviceConfigPath -Content $cfgJson
Write-Utf8NoBom -Path $wifiProfilesPath -Content $profilesJson

$txt = @"
CONFIG GERADA COM SUCESSO
Data: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")

Arquivos:
- device_config.json
- wifi_profiles.json

Servidor alvo fixo:
- Maquina A: $effectiveServerIpA
- Maquina B: $effectiveServerIpB

Hotspots configurados:
- Maquina A: $HotspotSsidA
- Maquina B: $HotspotSsidB

PASSO 1 - copiar para ESP32 (via Thonny):
1) Abra device_config.json (desta pasta) no PC
2) Save As -> MicroPython device -> /device_config.json
3) Abra wifi_profiles.json (desta pasta) no PC
4) Save As -> MicroPython device -> /wifi_profiles.json
5) Reinicie o ESP32 (botao EN/RST)

PASSO 2 - teste Maquina A:
1) Ligue APENAS o hotspot da Maquina A
2) Rode no PowerShell (na pasta do projeto):
   .\start.ps1
3) Verifique:
   Invoke-WebRequest http://127.0.0.1:8000/health
4) No log do ESP32, confirme envio para:
   http://$effectiveServerIpA/api/ingest

PASSO 3 - teste Maquina B (em outro momento):
1) Desligue hotspot/backend da Maquina A
2) Ligue APENAS o hotspot da Maquina B
3) Rode:
   .\start.ps1
4) Verifique:
   Invoke-WebRequest http://127.0.0.1:8000/health
5) Confira no log do ESP32 que voltou a enviar normalmente.

Regra de seguranca:
- Nunca ligar os dois hotspots ao mesmo tempo para este teste.
"@

Write-Utf8NoBom -Path $readmePath -Content $txt

Write-Host "[OK] Arquivos gerados em: $OutputDir"
Write-Host " - $deviceConfigPath"
Write-Host " - $wifiProfilesPath"
Write-Host " - $readmePath"
