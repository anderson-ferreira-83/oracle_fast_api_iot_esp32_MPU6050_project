# Guia Cloudflare Tunnel (Quick Tunnel)

Objetivo: publicar o backend local sem abrir porta no roteador, para o ESP32 funcionar em qualquer rede (casa/faculdade/hotspot) usando URL `trycloudflare`.

## Custo
- Quick Tunnel (`trycloudflare`): gratis, imediato, URL muda a cada reinicio.

## Pre-requisitos
- Python 3.11 instalado.
- Backend funcional em `http://127.0.0.1:8000/health`.

## Scripts usados
- `tools/install_cloudflared.ps1`
- `tools/start_quick_tunnel.ps1`
- `tools/apply_tunnel_host_to_esp32.ps1`
- `tools/bootstrap_quick_tunnel_esp32.ps1`
- `tools/run_iot.ps1`

## Fluxo rapido (primeira execucao)
1. Instalar `cloudflared` local no projeto:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\install_cloudflared.ps1
```

2. Subir backend + quick tunnel:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\bootstrap_quick_tunnel_esp32.ps1
```

3. Copiar para o ESP32 via Thonny:
- `tools/device_config.json` -> `/device_config.json`
- `tools/wifi_profiles.json` -> `/wifi_profiles.json`

Observacao: o `device_config.json` inclui `"dns_server": "1.1.1.1"` para evitar DNS de rede que bloqueia `*.trycloudflare.com`.

## Operacao diaria (1 comando)

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\run_iot.ps1
```

O script:
1. Reutiliza tunnel atual se ainda estiver vivo.
2. Cria novo quick tunnel apenas se necessario.
3. Abre `control.html` e `index.html`.
4. Atualiza JSON local do ESP32 quando a URL muda e avisa se precisa reenviar via Thonny.

## Checklist de validacao
1. Local:
```powershell
Invoke-WebRequest http://127.0.0.1:8000/health -UseBasicParsing
```
2. URL publica atual:
```powershell
$u = (Get-Content .\tools\quick_tunnel_url.txt -Raw).Trim()
Invoke-WebRequest "$u/health" -UseBasicParsing
```
3. ESP32 serial:
- Deve conectar no Wi-Fi e entrar no `main_lite.py`.
- Deve mostrar `[STAT] OK` aumentando.

## Problemas comuns
- `cloudflared nao encontrado`: rode `tools/install_cloudflared.ps1`.
- `530 The origin has been unregistered`: rode `tools/run_iot.ps1 -ForceNewTunnel`.
- URL do tunnel mudou: reenvie no Thonny `/device_config.json` e `/wifi_profiles.json`.
- `hostname trycloudflare nao resolve`: a rede local pode estar bloqueando DNS. No PC, troque DNS para `1.1.1.1`/`8.8.8.8`; no ESP32, mantenha `"dns_server": "1.1.1.1"` no `device_config.json`.
