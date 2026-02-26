param(
    [string]$VirtualIp = "10.125.237.250"
)

$ErrorActionPreference = "Stop"

function Test-IsAdmin {
    $current = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($current)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-IsAdmin)) {
    throw "Execute este script como Administrador."
}

$procs = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match "^(python|python3|py)\.exe$" -and
    $_.CommandLine -match "uvicorn\s+backend\.server:app"
}

foreach ($p in $procs) {
    try {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
        Write-Host "[APP] Uvicorn encerrado (PID $($p.ProcessId))."
    } catch {
        Write-Host "[APP] Falha ao encerrar PID $($p.ProcessId): $($_.Exception.Message)"
    }
}

$ips = Get-NetIPAddress -AddressFamily IPv4 -IPAddress $VirtualIp -ErrorAction SilentlyContinue
foreach ($ip in $ips) {
    try {
        Remove-NetIPAddress -InterfaceIndex $ip.InterfaceIndex -IPAddress $ip.IPAddress -Confirm:$false -ErrorAction Stop
        Write-Host "[NET] VIP removido de ifIndex=$($ip.InterfaceIndex): $VirtualIp"
    } catch {
        Write-Host "[NET] Falha ao remover VIP em ifIndex=$($ip.InterfaceIndex): $($_.Exception.Message)"
    }
}
