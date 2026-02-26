# Guia Rapido - Outra Maquina (Codex)

Objetivo: preparar a outra maquina para funcionar com ESP32 sem atualizar firmware.

## 1) O que precisa ficar igual
1. SSID: `S20_Ders@0`
2. Senha do Wi-Fi/hotspot: mesma usada no ESP32
3. Porta backend: `8000`

## 2) Comandos na outra maquina
Abra PowerShell na pasta do projeto e execute:

```powershell
cd C:\xampp\htdocs\oracle_fast_api_iot_esp32_MPU6050_project

# Descobrir IP real da maquina no Wi-Fi
$ip = (Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias "Wi-Fi" | Where-Object {$_.IPAddress -notlike "169.254*"} | Select-Object -First 1 -ExpandProperty IPAddress)
$ip

# Subir backend (abre index/control automaticamente)
.\start.ps1

# Testes de health
Invoke-WebRequest http://127.0.0.1:8000/health
Invoke-WebRequest http://$ip:8000/health
```

Se o segundo health falhar:

```powershell
netsh advfirewall firewall add rule name="ESP32 FastAPI 8000" dir=in action=allow protocol=TCP localport=8000 profile=any
Invoke-WebRequest http://$ip:8000/health
```

Resultado esperado: `StatusCode 200` nos dois health checks.

## 3) Fixar IP no Samsung (para nao quebrar depois)
No celular Samsung:
1. Configuracoes
2. Conexoes
3. Roteador Wi-Fi Movel
4. Dispositivos conectados
5. Selecione esta maquina
6. Ative `Sempre atribuir mesmo endereco IP`

## 4) Valor que deve voltar para o ESP32
Use este formato:

```text
server_ip=<IP_DA_MAQUINA>:8000
```

Exemplo:

```text
server_ip=10.125.237.85:8000
```

## 5) Prompt pronto para colar no Codex da outra maquina
```text
Estou na maquina B. Execute do zero:
1) detectar meu IP Wi-Fi atual
2) subir backend com .\start.ps1
3) validar /health em 127.0.0.1 e no IP da LAN
4) se falhar no IP da LAN, criar regra de firewall para porta 8000 e validar novamente
5) me devolver somente o server_ip final no formato IP:8000
Diretorio do projeto: C:\xampp\htdocs\oracle_fast_api_iot_esp32_MPU6050_project
```
