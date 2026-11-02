/* App móvil del simulador: consulta /api/dashboard y dibuja el mismo estado que el escritorio. */
"use strict";

const API = "/api/dashboard";
const INTERVALO_MS = 2000;
const VELOCIDAD_LENTA_KMH = 15;
const TODOS = "Todos";
// (relleno pastel, borde, texto) — iguales a NIVELES_TRAFICO del dashboard de escritorio
const NIVELES = {
  fluido: ["#b9f6ca", "#4caf7d", "Fluido"],
  moderado: ["#fff3a3", "#e0b100", "Moderado"],
  alto: ["#ffcc99", "#f08a3c", "Alto"],
  severo: ["#ffaaaa", "#e05555", "Severo"],
  sin_dato: ["#e5e7eb", "#9ca3af", "Sin dato"],
  simulada: ["#FFCC99", "#F4A261", "Congestión simulada"],
};

const estado = {
  datos: null,
  municipio: TODOS,
  parada: "",
  firmaRutas: null,
  firmaZonas: null,
  zonasMunicipio: { clave: null, ids: new Set() },
  reloj: null,               // {segundos, instante} para avanzar el reloj entre consultas
  encuadrado: false,
};

const $ = (id) => document.getElementById(id);

// ── Mapa ─────────────────────────────────────────────────────────
const mapa = L.map("mapa", { zoomControl: false }).setView([6.2442, -75.5812], 13);
for (const [nombre, indice] of [["zonas", 350], ["rutas", 420], ["paradas", 620], ["buses", 650]]) {
  mapa.createPane(nombre).style.zIndex = indice;
}
const mapasBase = {
  "Esri Topográfico": L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
    { maxZoom: 19, attribution: "Tiles © Esri — Esri, HERE, Garmin, © OpenStreetMap" },
  ),
  OpenStreetMap: L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "© <a href=\"https://www.openstreetmap.org/copyright\">OpenStreetMap</a>",
  }),
};
mapasBase["Esri Topográfico"].addTo(mapa);
L.control.layers(mapasBase, null, { position: "bottomright" }).addTo(mapa);

const capaZonas = L.layerGroup().addTo(mapa);
const capaRutas = L.layerGroup().addTo(mapa);
const capaParadas = L.layerGroup().addTo(mapa);
const marcadoresBus = new Map();          // nombre -> {marcador, lento}
const poligonosZona = new Map();          // id -> polígono

// ── Utilidades ───────────────────────────────────────────────────
function elemento(etiqueta, clase, texto) {
  const nodo = document.createElement(etiqueta);
  if (clase) nodo.className = clase;
  if (texto !== undefined) nodo.textContent = texto;
  return nodo;
}

function escapar(texto) {
  return String(texto).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

function aclarar(color, proporcion = 0.35) {
  const canales = [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16));
  return `rgb(${canales.map((c) => Math.round(c + (255 - c) * proporcion)).join(",")})`;
}

const rutasPorCodigo = () => new Map(estado.datos.routes.map((r) => [r.codigo, r]));

function enMunicipio(codigo) {
  if (estado.municipio === TODOS) return true;
  const ruta = rutasPorCodigo().get(codigo);
  return Boolean(ruta && ruta.municipio === estado.municipio);
}

function trazado(ruta) {
  return ruta.coordenadas_regreso.length
    ? ruta.coordenadas.concat(ruta.coordenadas_regreso.slice(1))
    : ruta.coordenadas;
}

function puntoEnPoligono([lat, lon], poligono) {
  let dentro = false;
  for (let i = 0, j = poligono.length - 1; i < poligono.length; j = i++) {
    const [lat1, lon1] = poligono[i];
    const [lat2, lon2] = poligono[j];
    if ((lat1 > lat) !== (lat2 > lat) && lon < lon1 + ((lat - lat1) * (lon2 - lon1)) / (lat2 - lat1)) {
      dentro = !dentro;
    }
  }
  return dentro;
}

function listaVacia(lista, texto) {
  lista.replaceChildren(elemento("li", "vacio", texto));
}

// ── Filtros ──────────────────────────────────────────────────────
function rutasVisibles() {
  return estado.datos.routes.filter((ruta) => enMunicipio(ruta.codigo));
}

function zonasVisibles() {
  const zonas = estado.datos.traffic_zones;
  if (estado.municipio === TODOS || zonas.mode !== "tomtom") return zonas.zones;
  // Hexágonos que cruzan alguna ruta del municipio (muestras cada ~45 m sobre el trazado).
  const rutas = rutasVisibles();
  const clave = [estado.municipio, ...zonas.zones.map((z) => z.id), ...rutas.map((r) => r.codigo + trazado(r).length)].join("|");
  if (clave !== estado.zonasMunicipio.clave) {
    const puntos = [];
    for (const ruta of rutas) {
      const linea = trazado(ruta);
      for (let i = 1; i < linea.length; i++) {
        const [a, b] = [linea[i - 1], linea[i]];
        const pasos = Math.max(1, Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1]) / 0.0004));
        for (let k = 0; k <= pasos; k++) {
          puntos.push([a[0] + ((b[0] - a[0]) * k) / pasos, a[1] + ((b[1] - a[1]) * k) / pasos]);
        }
      }
    }
    const ids = new Set();
    for (const zona of zonas.zones) {
      const lats = zona.polygon.map((p) => p[0]);
      const lons = zona.polygon.map((p) => p[1]);
      const [laMin, laMax, loMin, loMax] = [Math.min(...lats), Math.max(...lats), Math.min(...lons), Math.max(...lons)];
      if (puntos.some((p) => p[0] >= laMin && p[0] <= laMax && p[1] >= loMin && p[1] <= loMax
          && puntoEnPoligono(p, zona.polygon))) {
        ids.add(zona.id);
      }
    }
    estado.zonasMunicipio = { clave, ids };
  }
  return zonas.zones.filter((zona) => estado.zonasMunicipio.ids.has(zona.id));
}

function paradasVisibles() {
  return estado.datos.stops
    .filter((parada) => parada.codigos.some(enMunicipio))
    .map((parada) => parada.nombre)
    .sort((a, b) => a.localeCompare(b, "es"));
}

// ── Dibujo del mapa ──────────────────────────────────────────────
function dibujarRutas() {
  const rutas = rutasVisibles();
  const firma = JSON.stringify([estado.municipio, rutas.map((r) => [r.codigo, r.color, trazado(r).length, trazado(r)[1]])]);
  if (firma === estado.firmaRutas) return;
  estado.firmaRutas = firma;
  capaRutas.clearLayers();
  capaParadas.clearLayers();
  for (const ruta of rutas) {
    L.polyline(trazado(ruta), { pane: "rutas", color: ruta.color, weight: 5, opacity: 0.9 })
      .bindTooltip(ruta.nombre, { sticky: true })
      .addTo(capaRutas);
  }
  for (const parada of estado.datos.stops) {
    const visibles = parada.codigos.filter(enMunicipio);
    if (!visibles.length) continue;
    const ruta = rutasPorCodigo().get(visibles[0]);
    L.circleMarker([parada.latitud, parada.longitud], {
      pane: "paradas",
      radius: 6,
      color: visibles.length === 1 ? ruta.color : "#222222",
      weight: 3,
      fillColor: "#ffffff",
      fillOpacity: 1,
    })
      .bindTooltip(parada.nombre)
      .on("click", () => elegirParada(parada.nombre, true))
      .addTo(capaParadas);
  }
}

function dibujarZonas() {
  const zonas = zonasVisibles();
  const firma = JSON.stringify(zonas.map((z) => [z.id, z.severity]));
  if (firma !== estado.firmaZonas) {
    estado.firmaZonas = firma;
    capaZonas.clearLayers();
    poligonosZona.clear();
    for (const zona of [...zonas].reverse()) {          // las más lentas quedan encima
      const [relleno, borde] = NIVELES[zona.severity];
      const fluido = zona.severity === "fluido" || zona.severity === "sin_dato";
      const poligono = L.polygon(zona.polygon, {
        pane: "zonas",
        color: borde,
        weight: fluido ? 1 : 2,
        fillColor: relleno,
        fillOpacity: fluido ? 0.28 : 0.5,
      })
        .bindPopup(() => contenidoZona(zona.id))         // se arma al abrir, con los datos del momento
        .addTo(capaZonas);
      poligonosZona.set(zona.id, poligono);
    }
    dibujarLeyenda();
  }
}

function contenidoZona(id) {
  const zona = estado.datos.traffic_zones.zones.find((z) => z.id === id);
  const caja = elemento("div");
  if (!zona) return caja;
  caja.append(elemento("strong", "", zona.label));
  if (zona.severity === "sin_dato") {
    caja.append(elemento("div", "", "TomTom no respondió en esta zona; se mide de nuevo en la próxima actualización."));
  } else if (zona.current_kmh === null) {
    caja.append(elemento("div", "", "Zona simulada: cada bus frena entre 50 % y 70 %."));
  } else {
    caja.append(
      elemento("div", "", `Nivel: ${NIVELES[zona.severity][2]}`),
      elemento("div", "", zona.closed ? "Vía cerrada" : `Actual ${Math.round(zona.current_kmh)} km/h · libre ${Math.round(zona.free_kmh)} km/h`),
      elemento("div", "", `Los buses frenan ${Math.round(zona.slowdown * 100)} %`),
    );
  }
  caja.append(elemento("div", "", `Buses dentro: ${zona.buses}`));
  return caja;
}

function dibujarLeyenda() {
  const leyenda = $("leyenda");
  const niveles = estado.datos.traffic_zones.mode === "tomtom"
    ? ["fluido", "moderado", "alto", "severo"] : ["simulada"];
  if (zonasVisibles().some((zona) => zona.severity === "sin_dato")) niveles.push("sin_dato");
  leyenda.replaceChildren(...niveles.map((nivel) => {
    const [relleno, borde, texto] = NIVELES[nivel];
    const fila = elemento("span");
    const muestra = elemento("i");
    muestra.style.background = relleno;
    muestra.style.borderColor = borde;
    fila.append(muestra, texto);
    return fila;
  }));
}

function iconoBus(bus, lento) {
  // El emoji (bus, carro, moto...) viene del tipo con que se registró el vehículo.
  return L.divIcon({
    className: "icono-bus",
    iconSize: [28, 28],
    iconAnchor: [14, 14],
    html: `<span class="bus${lento ? " lento" : ""}" style="--c:${escapar(bus.color)}">`
      + `<i>${escapar(bus.emoji ?? "🚌")}</i><b>${escapar(bus.name)}</b></span>`,
  });
}

function dibujarBuses() {
  const visibles = estado.datos.buses.filter((bus) => enMunicipio(bus.route_code));
  const nombres = new Set(visibles.map((bus) => bus.name));
  for (const [nombre, { marcador }] of marcadoresBus) {
    if (!nombres.has(nombre)) {
      marcador.remove();
      marcadoresBus.delete(nombre);
    }
  }
  for (const bus of visibles) {
    const lento = bus.speed_kmh > 0 && bus.speed_kmh < VELOCIDAD_LENTA_KMH;
    const actual = marcadoresBus.get(bus.name);
    if (!actual) {
      const marcador = L.marker([bus.latitude, bus.longitude], { pane: "buses", icon: iconoBus(bus, lento), keyboard: false })
        .bindTooltip(() => textoBus(bus.name))
        .addTo(mapa);
      marcadoresBus.set(bus.name, { marcador, lento });
      continue;
    }
    actual.marcador.setLatLng([bus.latitude, bus.longitude]);
    if (actual.lento !== lento) {
      actual.marcador.setIcon(iconoBus(bus, lento));
      actual.lento = lento;
    }
  }
}

function textoBus(nombre) {
  const bus = estado.datos.buses.find((b) => b.name === nombre);
  return bus ? `${bus.name} · ${bus.speed_kmh.toFixed(1)} km/h · ${bus.next_stop} en ${bus.remaining_text}` : nombre;
}

function encuadrar() {
  const puntos = rutasVisibles().flatMap(trazado);
  if (puntos.length) mapa.fitBounds(puntos, { padding: [30, 30] });
}

// ── Paneles ──────────────────────────────────────────────────────
function insignia(texto, color) {
  const nodo = elemento("span", "insignia", texto);
  nodo.style.background = aclarar(color);
  return nodo;
}

function dato(principal, secundario, lento = false) {
  const nodo = elemento("div", "dato");
  nodo.append(elemento("strong", lento ? "lento" : "", principal), elemento("small", "", secundario));
  return nodo;
}

function actualizarLlegadas() {
  const lista = $("lista-llegadas");
  const llegadas = estado.datos.arrivals.filter((llegada) => enMunicipio(llegada.route_code));
  if (!llegadas.length) return listaVacia(lista, "Ningún bus pasa pronto por esta parada.");
  const rutas = rutasPorCodigo();
  const emojis = new Map(estado.datos.buses.map((bus) => [bus.name, bus.emoji ?? "🚌"]));
  lista.replaceChildren(...llegadas.map((llegada) => {
    const fila = elemento("li");
    const lento = llegada.speed_kmh > 0 && llegada.speed_kmh < VELOCIDAD_LENTA_KMH;
    fila.append(
      insignia(`${emojis.get(llegada.name) ?? "🚌"} ${llegada.name}`, rutas.get(llegada.route_code)?.color ?? "#94a3b8"),
      elemento("span", "principal", `Hacia ${llegada.direction}`),
      dato(llegada.remaining_text, llegada.arrival_time),
      elemento("span", "secundario" + (lento ? " lento" : ""), `${llegada.speed_kmh.toFixed(1)} km/h`),
    );
    return fila;
  }));
}

function actualizarFlota() {
  const lista = $("lista-flota");
  const buses = estado.datos.buses.filter((bus) => enMunicipio(bus.route_code));
  if (!buses.length) return listaVacia(lista, "No hay buses en este municipio.");
  lista.replaceChildren(...buses.map((bus) => {
    const fila = elemento("li");
    const boton = elemento("button", "fila");
    boton.type = "button";
    boton.addEventListener("click", () => mapa.setView([bus.latitude, bus.longitude], Math.max(mapa.getZoom(), 15)));
    const lento = bus.speed_kmh > 0 && bus.speed_kmh < VELOCIDAD_LENTA_KMH;
    boton.append(
      insignia(`${bus.emoji ?? "🚌"} ${bus.name}`, bus.color),
      elemento("span", "principal", bus.next_stop),
      dato(`${bus.speed_kmh.toFixed(1)} km/h`, bus.arrival_time, lento),
      elemento("span", "secundario", `Llega en ${bus.remaining_text}`),
    );
    fila.append(boton);
    return fila;
  }));
}

function actualizarTrafico() {
  const datos = estado.datos.traffic_zones;
  const zonas = zonasVisibles();
  const lista = $("lista-trafico");
  if (datos.mode !== "tomtom") {
    $("resumen-trafico").textContent = "Sin medición de TomTom todavía: se usa la zona de congestión simulada.";
  } else {
    const lentas = zonas.filter((z) => z.severity !== "fluido" && z.severity !== "sin_dato").length;
    const donde = estado.municipio === TODOS ? "los recorridos" : `las rutas de ${estado.municipio}`;
    $("resumen-trafico").textContent =
      `TomTom midió ${zonas.length} hexágonos sobre ${donde} (${datos.updated_at}, cada ${datos.refresh_minutes} min); ${lentas} con tráfico lento. Toca una zona para verla.`;
  }
  if (!zonas.length) return listaVacia(lista, "No hay zonas medidas en este municipio.");
  lista.replaceChildren(...zonas.map((zona) => {
    const [relleno, , nivel] = NIVELES[zona.severity];
    const fila = elemento("li");
    const boton = elemento("button", "fila");
    boton.type = "button";
    boton.addEventListener("click", () => {
      const poligono = poligonosZona.get(zona.id);
      if (!poligono) return;
      mapa.fitBounds(poligono.getBounds(), { padding: [40, 40], maxZoom: 15 });
      poligono.openPopup();
    });
    const marca = elemento("span", "insignia", nivel);
    marca.style.background = relleno;
    const velocidad = zona.severity === "sin_dato" ? "Sin dato"
      : zona.current_kmh === null ? "—" : zona.closed ? "Cerrada" : `${Math.round(zona.current_kmh)} km/h`;
    const frena = zona.slowdown === null ? "50-70 %" : `-${Math.round(zona.slowdown * 100)} %`;
    boton.append(
      marca,
      elemento("span", "principal", zona.label),
      dato(velocidad, frena),
      elemento("span", "secundario", `${zona.buses} bus(es) dentro`),
    );
    fila.append(boton);
    return fila;
  }));
}

function actualizarKpis() {
  const buses = estado.datos.buses.filter((bus) => enMunicipio(bus.route_code));
  const enMarcha = buses.map((bus) => bus.speed_kmh).filter((v) => v > 0);
  const lentos = enMarcha.filter((v) => v < VELOCIDAD_LENTA_KMH).length;
  $("kpi-activos").textContent = buses.length;
  $("kpi-media").textContent = enMarcha.length
    ? `${Math.round(enMarcha.reduce((a, b) => a + b, 0) / enMarcha.length)} km/h` : "0 km/h";
  $("kpi-lentos").textContent = lentos;
  $("kpi-lentos").style.color = lentos ? "var(--peligro)" : "var(--exito)";
}

function actualizarSelectores() {
  const municipios = [TODOS, ...new Set(estado.datos.routes.map((r) => r.municipio).filter(Boolean))].sort(
    (a, b) => (a === TODOS ? -1 : b === TODOS ? 1 : a.localeCompare(b, "es")),
  );
  if (!municipios.includes(estado.municipio)) estado.municipio = TODOS;
  rellenarSelect($("municipio"), municipios, estado.municipio);
  const paradas = paradasVisibles();
  if (!paradas.includes(estado.parada)) {
    estado.parada = paradas[0] ?? "";
    return true;                                        // hay que pedir las llegadas de la nueva parada
  }
  rellenarSelect($("parada"), paradas, estado.parada);
  return false;
}

function rellenarSelect(select, opciones, valor) {
  const actuales = [...select.options].map((o) => o.value);
  if (actuales.join("|") !== opciones.join("|")) {
    select.replaceChildren(...opciones.map((texto) => new Option(texto, texto)));
  }
  select.value = valor;
}

function actualizarEstadoTrafico() {
  const pill = $("estado-trafico");
  const enVivo = estado.datos.traffic_zones.mode === "tomtom" || estado.datos.traffic.available;
  pill.textContent = enVivo ? "Tráfico en vivo" : "Trazados guardados";
  pill.className = `pill ${enVivo ? "pill-ok" : "pill-alerta"}`;
}

// ── Reloj real ───────────────────────────────────────────────────
function sincronizarReloj(texto) {
  const [h, m, s] = texto.split(":").map(Number);
  estado.reloj = { segundos: h * 3600 + m * 60 + s, instante: performance.now() };
}

function pintarReloj() {
  if (!estado.reloj) return;
  const total = Math.floor(estado.reloj.segundos + (performance.now() - estado.reloj.instante) / 1000) % 86400;
  const partes = [Math.floor(total / 3600), Math.floor(total / 60) % 60, total % 60];
  $("reloj").textContent = partes.map((n) => String(n).padStart(2, "0")).join(":");
}
setInterval(pintarReloj, 250);

// ── Ciclo de consulta ────────────────────────────────────────────
function render() {
  if (actualizarSelectores()) return consultar();       // la parada cambió por el filtro
  dibujarZonas();
  dibujarRutas();
  dibujarBuses();
  actualizarKpis();
  actualizarLlegadas();
  actualizarFlota();
  actualizarTrafico();
  actualizarEstadoTrafico();
  if (!estado.encuadrado) {
    encuadrar();
    estado.encuadrado = true;
  }
}

let temporizador = null;

async function consultar() {
  clearTimeout(temporizador);
  try {
    const consulta = estado.parada ? `?parada=${encodeURIComponent(estado.parada)}` : "";
    const respuesta = await fetch(API + consulta, { cache: "no-store" });
    if (!respuesta.ok) throw new Error(`HTTP ${respuesta.status}`);
    estado.datos = await respuesta.json();
    sincronizarReloj(estado.datos.clock);
    $("aviso").hidden = true;
    render();
  } catch (error) {
    $("aviso").textContent = "Sin conexión con el simulador; reintentando…";
    $("aviso").hidden = false;
  } finally {
    // En segundo plano no se consulta, para ahorrar batería y datos.
    if (!document.hidden) temporizador = setTimeout(consultar, INTERVALO_MS);
  }
}

function elegirParada(nombre, mostrarLlegadas = false) {
  estado.parada = nombre;
  if (mostrarLlegadas) mostrarPanel("llegadas");
  consultar();
}

function mostrarPanel(nombre) {
  for (const boton of document.querySelectorAll(".pestanas button")) {
    boton.classList.toggle("activa", boton.dataset.panel === nombre);
    boton.setAttribute("aria-selected", boton.dataset.panel === nombre);
  }
  for (const panel of document.querySelectorAll(".panel")) {
    panel.hidden = panel.id !== `panel-${nombre}`;
  }
  $("hoja").classList.remove("recogida");
}

// ── Eventos ──────────────────────────────────────────────────────
$("municipio").addEventListener("change", (evento) => {
  estado.municipio = evento.target.value;
  // Los buses saltan al cambiar el filtro: sin animación en ese momento.
  mapa.getContainer().classList.add("sin-animacion");
  render();
  encuadrar();
  setTimeout(() => mapa.getContainer().classList.remove("sin-animacion"), 100);
});
$("parada").addEventListener("change", (evento) => elegirParada(evento.target.value));
$("centrar").addEventListener("click", encuadrar);
$("asa").addEventListener("click", () => {
  $("hoja").classList.toggle("recogida");
  setTimeout(() => mapa.invalidateSize(), 300);
});
for (const boton of document.querySelectorAll(".pestanas button")) {
  boton.addEventListener("click", () => mostrarPanel(boton.dataset.panel));
}
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) consultar();
});
window.addEventListener("resize", () => mapa.invalidateSize());

consultar();
