#Requires -RunAsAdministrator
<#
  Abre el simulador (Docker dentro de WSL) a la red Wi-Fi:
    - app movil              -> http://IP-del-PC:8080/movil/
    - dashboard en navegador -> http://IP-del-PC:6081

  Ejecutar en PowerShell como administrador, desde la carpeta del proyecto:

    powershell -ExecutionPolicy Bypass -File docker\abrir-en-red.ps1          # abrir
    powershell -ExecutionPolicy Bypass -File docker\abrir-en-red.ps1 -Cerrar  # deshacer

  Repetirlo despues de reiniciar el PC: la IP interna de WSL cambia.
  Requiere SIMULADOR_IP_PUBLICA=0.0.0.0 (y VNC_PASSWORD) en .env y "docker compose up -d".
#>
param(
    [string]$Distro = "Ubuntu-26.04",
    [switch]$Cerrar
)

$ErrorActionPreference = "Stop"
$regla = "Simulador buses (app movil)"
# Puerto en Windows -> puerto en WSL. Windows ya usa 8000 y 6080 solo para este PC.
$puertos = [ordered]@{ 8080 = 8000; 6081 = 6080 }

# Quita lo que haya dejado una ejecucion anterior.
foreach ($puerto in $puertos.Keys) {
    netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=$puerto 2>$null | Out-Null
}
Get-NetFirewallRule -DisplayName $regla -ErrorAction SilentlyContinue | Remove-NetFirewallRule

if ($Cerrar) {
    Write-Host "Listo: se quitaron las redirecciones y la regla del firewall."
    return
}

$envPath = Join-Path (Split-Path $PSScriptRoot -Parent) ".env"
if (-not (Select-String -Path $envPath -Pattern '^VNC_PASSWORD=.+' -Quiet -ErrorAction SilentlyContinue)) {
    Write-Warning ("El dashboard (6081) no tiene contrasena: cualquiera en la red podria " +
        "crear o borrar rutas. Agrega VNC_PASSWORD=... en .env y ejecuta 'docker compose up -d'.")
}

# 1. Windows -> contenedores en WSL.
$ipWsl = ((wsl.exe -d $Distro hostname -I) -split '\s+' | Where-Object { $_ })[0]
if (-not $ipWsl) {
    throw "No se obtuvo la IP de WSL. Inicia la distribucion $Distro y los contenedores."
}
# Se recorren los pares: con claves numericas, $puertos[8080] buscaria la posicion 8080.
foreach ($par in $puertos.GetEnumerator()) {
    netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=$($par.Key) `
        connectaddress=$ipWsl connectport=$($par.Value) | Out-Null
}
$sinDestino = netsh interface portproxy show v4tov4 | Select-String "$([regex]::Escape($ipWsl))\s*$"
if ($sinDestino) { throw "La redireccion quedo sin puerto de destino: $sinDestino" }

# 2. Firewall: permite esos puertos solo en redes privadas.
New-NetFirewallRule -DisplayName $regla -Direction Inbound -Protocol TCP `
    -LocalPort ([int[]]$puertos.Keys) -Action Allow -Profile Private | Out-Null

# 3. En una red marcada como Publica Windows bloquea las conexiones entrantes.
foreach ($red in Get-NetConnectionProfile | Where-Object NetworkCategory -eq "Public") {
    $respuesta = Read-Host ("La red '{0}' esta marcada como Publica y bloquea a los otros " +
        "dispositivos. Si es tu red de casa o de confianza, la marco como Privada? (s/n)") -f $red.Name
    if ($respuesta -match '^[sS]') {
        Set-NetConnectionProfile -InterfaceIndex $red.InterfaceIndex -NetworkCategory Private
        Write-Host "La red '$($red.Name)' ahora es Privada."
    } else {
        Write-Warning "La red '$($red.Name)' sigue Publica: el firewall seguira bloqueando el acceso."
    }
}

# 4. Prueba local y direcciones para los otros dispositivos.
$ipLan = (Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.InterfaceAlias -notlike "vEthernet*" -and $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
    Select-Object -First 1).IPAddress
foreach ($prueba in @("http://${ipLan}:8080/movil/", "http://${ipLan}:6081/vnc.html")) {
    try {
        Invoke-WebRequest $prueba -UseBasicParsing -TimeoutSec 5 | Out-Null
    } catch {
        Write-Warning "No respondio $prueba : revisa que los contenedores esten corriendo (docker compose ps)."
    }
}
Write-Host ""
Write-Host "Desde el celular o el otro computador (misma red Wi-Fi):"
Write-Host "    App movil:               http://${ipLan}:8080/movil/" -ForegroundColor Cyan
Write-Host "    Dashboard de escritorio: http://${ipLan}:6081" -ForegroundColor Cyan
