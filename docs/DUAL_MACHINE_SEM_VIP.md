# Dual Machine Sem VIP (Seguro)

Objetivo: usar 2 notebooks com o mesmo ESP32 sem alterar firmware e sem usar IP virtual na interface de rede.

## Estrategia
- Cada notebook funciona em momentos diferentes (nunca simultaneo).
- O ESP32 usa `server_ip` por SSID em `wifi_profiles.json`.
- O backend continua rodando em `0.0.0.0:8000` via `start.ps1`.

Isso evita alterar gateway/DNS/rotas da placa Wi-Fi do Windows.

## Preparacao (uma vez)
1. Defina os hotspots:
- Maquina A: SSID e senha (senha >= 8 chars)
- Maquina B: SSID e senha (senha >= 8 chars)

1. Descubra o IP/porta do backend em cada maquina/rede:

```powershell
ipconfig
```

Use o IPv4 da interface conectada na rede alvo e porta `8000`.
Exemplo:
- Maquina A em `S20_Ders@0` -> `10.125.237.165:8000`
- Maquina B em `Dersao83` -> `192.168.0.108:8000`

1. Gere os arquivos de configuracao do ESP32:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\generate_dual_machine_hotspot_config.ps1 `
  -HotspotSsidA "S20_Ders@0" -HotspotPasswordA "F0xbam1844" -ServerIpA "10.125.237.165:8000" `
  -HotspotSsidB "Dersao83"   -HotspotPasswordB "986960440"   -ServerIpB "192.168.0.108:8000"
```

1. Os arquivos serao gerados em `tools/dual_machine_config_out/`:
- `device_config.json`
- `wifi_profiles.json`
- `LEIA_ME_TESTE_MAQUINA_A_B.txt`

1. Copie `device_config.json` e `wifi_profiles.json` para o ESP32 via Thonny:
- Save As -> MicroPython device -> `/device_config.json`
- Save As -> MicroPython device -> `/wifi_profiles.json`
- Reinicie o ESP32 (EN/RST).

## Teste Individual - Maquina A
1. Deixe apenas o hotspot da Maquina A ligado.
1. No projeto da Maquina A:

```powershell
.\start.ps1
Invoke-WebRequest http://127.0.0.1:8000/health
```

1. Confirme no monitor serial do ESP32 envio para o `ServerIpA` configurado.

## Teste Individual - Maquina B
1. Desligue hotspot/backend da Maquina A.
1. Ligue apenas hotspot da Maquina B.
1. No projeto da Maquina B:

```powershell
.\start.ps1
Invoke-WebRequest http://127.0.0.1:8000/health
```

1. Confirme que o ESP32 voltou a enviar normalmente.

## Observacoes
- Nao use os dois hotspots ao mesmo tempo.
- Essa abordagem nao usa VIP e nao altera stack de rede do Windows.
