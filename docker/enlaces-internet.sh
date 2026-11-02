#!/bin/sh
# Shows the public addresses of the Cloudflare quick tunnels.
# They change every time the tunnels start. Run from the project folder:
#   sh docker/enlaces-internet.sh
cd "$(dirname "$0")/.." || exit 1
export COMPOSE_PROFILES=internet,internet-panel   # the tunnels live in these profiles

enlace() {
    # The tunnel prints its address a few seconds after starting.
    for _ in $(seq 1 20); do
        url=$(docker compose logs "$1" 2>/dev/null | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' | tail -n 1)
        [ -n "$url" ] && { echo "$url"; return; }
        sleep 1
    done
}

app=$(enlace tunel-app)
if [ -n "$app" ]; then
    echo "App para celular (solo lectura): $app/movil/"
else
    echo "El túnel de la app no está activo: docker compose --profile internet up -d"
fi

if docker compose ps --services --status running 2>/dev/null | grep -qx tunel-panel; then
    if ! grep -q '^VNC_PASSWORD=.' .env 2>/dev/null; then
        echo "AVISO: el panel está publicado sin contraseña; cualquiera podría editar rutas."
        echo "       Pon VNC_PASSWORD en .env y ejecuta: docker compose --profile internet-panel up -d"
    fi
    panel=$(enlace tunel-panel)
    [ -n "$panel" ] && echo "Panel de administración (pide la contraseña de VNC_PASSWORD): $panel"
fi
