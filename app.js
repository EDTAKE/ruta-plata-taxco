/* Ruta Plata · Prototipo de transporte público con GPS para Taxco de Alarcón.
 * Las unidades se simulan en el navegador. En producción, sus posiciones llegarían
 * del GPS de cada conductor vía WebSocket (ver README.md). */
(async () => {
'use strict';

// Local: data/routes.js define TAXCO_DATA. Versión publicada: se lee data/routes.json.
const DATA = window.TAXCO_DATA || await (await fetch('data/routes.json')).json();
const TAXCO_CENTER = [18.5585, -99.6045];
const DEFAULT_ME = [18.5576, -99.6033]; // cerca de Calle Juárez / Zócalo
const WALK_M_PER_MIN = 70;             // calles empinadas: caminar es lento
const DWELL_S = 20;                    // segundos detenida en cada parada
const MAX_WALK_M = 1000;
const SERVICE_HOURS = '5:30 – 22:00';

const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/* ---------------- geometría ---------------- */
function haversine(a, b) {
  const R = 6371000, toR = Math.PI / 180;
  const dLat = (b[0] - a[0]) * toR, dLon = (b[1] - a[1]) * toR;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a[0] * toR) * Math.cos(b[0] * toR) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}
function bearing(a, b) {
  const toR = Math.PI / 180;
  const y = Math.sin((b[1] - a[1]) * toR) * Math.cos(b[0] * toR);
  const x = Math.cos(a[0] * toR) * Math.sin(b[0] * toR) - Math.sin(a[0] * toR) * Math.cos(b[0] * toR) * Math.cos((b[1] - a[1]) * toR);
  return (Math.atan2(y, x) / toR + 360) % 360;
}
const fmtMin = s => s < 45 ? 'llegando' : `${Math.round(s / 60)} min`;
const fmtFare = r => `$${r.fare.toFixed(2)} MXN${r.fare_pending ? ' (por confirmar)' : ''}`;
const fmtDist = m => m < 1000 ? `${Math.round(m / 10) * 10} m` : `${(m / 1000).toFixed(1)} km`;

/* ---------------- modelo de rutas ---------------- */
const routes = DATA.routes.map(r => {
  const cum = [0];
  for (let i = 1; i < r.path.length; i++) cum.push(cum[i - 1] + haversine(r.path[i - 1], r.path[i]));
  const L = cum[cum.length - 1];
  const scale = L / r.length_m;                    // corrige pequeñas diferencias con OSRM
  const stopM = r.stop_m.map(m => m * scale);
  const moving = Math.min(9, Math.max(3.2, (r.length_m / r.osrm_s) * 0.6)); // m/s
  const half = r.stops.length - 1;
  const visits = r.sequence.slice(0, -1).map((stopId, k) => ({
    k, stopId, pos: stopM[k],
    // circuitos (KML) traen su sentido explícito; las de ida y vuelta lo deducen
    toward: r.toward ? r.toward[k] : k < half ? DATA.stops[r.stops[r.stops.length - 1]].name : DATA.stops[r.stops[0]].name,
  }));
  const cycleS = L / moving + DWELL_S * (r.sequence.length - 1);
  return { ...r, cum, L, stopM, moving, visits, cycleS, visible: true };
});
const routeById = Object.fromEntries(routes.map(r => [r.id, r]));

/** Nombre de la parada; si otra parada se llama igual (p. ej. dos "Telmex"), agrega qué rutas pasan */
const nameCount = {};
Object.values(DATA.stops).forEach(s => { nameCount[s.name] = (nameCount[s.name] || 0) + 1; });
function stopLabel(id) {
  const name = DATA.stops[id].name;
  if (nameCount[name] < 2) return name;
  return `${name} (${routes.filter(r => r.stops.includes(id)).map(r => r.chip || r.short).join(', ')})`;
}

function pointAt(route, d) {
  const { cum, path, L } = route;
  d = ((d % L) + L) % L;
  let lo = 0, hi = cum.length - 1;
  while (lo < hi - 1) { const mid = (lo + hi) >> 1; if (cum[mid] <= d) lo = mid; else hi = mid; }
  const seg = cum[hi] - cum[lo] || 1, t = (d - cum[lo]) / seg;
  const a = path[lo], b = path[hi];
  return { latlng: [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t], heading: bearing(a, b) };
}
function subPath(route, from, to) {
  // trozo del trazo entre dos distancias (puede cruzar el final del circuito)
  const out = [];
  const len = ((to - from) % route.L + route.L) % route.L;
  const steps = Math.max(2, Math.ceil(len / 15));
  for (let i = 0; i <= steps; i++) out.push(pointAt(route, from + (len * i) / steps).latlng);
  return out;
}

/* ---------------- simulación de unidades ---------------- */
let seed = 7;
const rand = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
const units = [];
routes.forEach(r => {
  for (let i = 0; i < r.units; i++) {
    units.push({
      id: `${r.short === 'S' ? 'S' : 'T'}-${r.short === 'S' ? 3 : r.short}${String(i + 1).padStart(2, '0')}`,
      route: r, d: (r.L / r.units) * i + rand() * 60,
      speed: r.moving * (0.85 + rand() * 0.3), dwell: 0,
      seats: 15, occupied: Math.floor(4 + rand() * 10), lastStop: -1,
    });
  }
});
let simSpeed = 1;
let followed = null, followTarget = null, alerted = false; // unidad que sigue el pasajero

function stepUnit(u, dt) {
  if (u.dwell > 0) { u.dwell -= dt; return; }
  const r = u.route, prev = u.d;
  u.d = (u.d + u.speed * dt) % r.L;
  // ¿cruzó una parada?
  for (let k = 0; k < r.visits.length; k++) {
    const p = r.visits[k].pos;
    const crossed = prev <= u.d ? (p > prev && p <= u.d) : (p > prev || p <= u.d);
    if (crossed && k !== u.lastStop) {
      u.d = p; u.dwell = DWELL_S * (0.6 + rand() * 0.8); u.lastStop = k;
      u.occupied = Math.max(0, Math.min(u.seats, u.occupied + Math.round(rand() * 6 - 3)));
      break;
    }
  }
}

/** segundos estimados para que la unidad u llegue a la posición p de su ruta */
function etaTo(u, p) {
  const r = u.route;
  const dist = ((p - u.d) % r.L + r.L) % r.L;
  if (dist < 1) return u.dwell > 0 ? 0 : r.cycleS;
  let between = 0;
  for (const v of r.visits) {
    const dv = ((v.pos - u.d) % r.L + r.L) % r.L;
    if (dv > 1 && dv < dist - 1) between++;
  }
  return dist / u.speed + between * DWELL_S + Math.max(0, u.dwell);
}
/** próximas llegadas a una visita (parada + sentido) ordenadas */
function arrivalsFor(route, visit) {
  return units.filter(u => u.route === route)
    .map(u => ({ u, s: etaTo(u, visit.pos) }))
    .sort((a, b) => a.s - b.s);
}

/* ---------------- mapa ---------------- */
const isDark = () => {
  const t = document.documentElement.dataset.theme;
  return t ? t === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches;
};
const dark = isDark();
const map = L.map('map', { zoomControl: false, attributionControl: true }).setView(TAXCO_CENTER, 15);
L.control.zoom({ position: 'bottomright' }).addTo(map);
if (window.RP_VECTOR_BASEMAP) loadVectorBasemap(window.RP_VECTOR_BASEMAP);
else L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19, className: dark ? 'tiles-dark' : '',
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
}).addTo(map);

/* Mapa base vectorial (calles de OSM dibujadas en canvas) para cuando no se pueden
 * cargar teselas externas, p. ej. la versión publicada en claude.ai. */
async function loadVectorBasemap(url) {
  map.attributionControl.addAttribution('&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> (ODbL)');
  map.createPane('basemap').style.zIndex = 250;
  const renderer = L.canvas({ pane: 'basemap', padding: 0.3 });
  let bm;
  try { bm = await (await fetch(url)).json(); } catch { return; }
  const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const layers = [];
  const add = (lines, style, poly) => lines.forEach(pts => {
    const l = (poly ? L.polygon : L.polyline)(pts, { renderer, interactive: false, ...style() });
    l._style = style; layers.push(l); l.addTo(map);
  });
  add(bm.park, () => ({ stroke: false, fill: true, fillColor: css('--map-park'), fillOpacity: 1 }), true);
  add(bm.foot, () => ({ color: css('--map-foot'), weight: 1.2, dashArray: '2 3' }));
  add(bm.minor, () => ({ color: css('--map-minor-casing'), weight: 6, lineCap: 'round' }));
  add(bm.minor, () => ({ color: css('--map-minor'), weight: 4, lineCap: 'round' }));
  add(bm.mid, () => ({ color: css('--map-minor-casing'), weight: 7.5, lineCap: 'round' }));
  add(bm.mid, () => ({ color: css('--map-mid'), weight: 5.5, lineCap: 'round' }));
  add(bm.major, () => ({ color: css('--map-major-casing'), weight: 9, lineCap: 'round' }));
  add(bm.major, () => ({ color: css('--map-major'), weight: 7, lineCap: 'round' }));
  const labels = L.layerGroup().addTo(map);
  bm.names.forEach(([name, lat, lon, cls]) => L.marker([lat, lon], {
    interactive: false, keyboard: false, pane: 'overlayPane', _cls: cls,
    icon: L.divIcon({ className: '', iconSize: null, html: `<div class="street-label">${esc(name)}</div>` }),
  }).addTo(labels));
  const showLabels = () => labels.eachLayer(m => {
    const el = m.getElement(); if (el) el.hidden = map.getZoom() < (m.options._cls === 'major' ? 15 : 16);
  });
  map.on('zoomend', showLabels); showLabels();
  const restyle = () => layers.forEach(l => l.setStyle(l._style()));
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', restyle);
  new MutationObserver(restyle).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
}

/** padding para que el panel no tape lo que se encuadra */
function fitPad() {
  if (window.innerWidth >= 900) return { paddingTopLeft: [440, 70], paddingBottomRight: [70, 30] };
  return { paddingTopLeft: [24, 70], paddingBottomRight: [24, $('#sheet').getBoundingClientRect().height + 16] };
}
const routeLayers = {};
routes.forEach(r => {
  routeLayers[r.id] = L.layerGroup([
    L.polyline(r.path, { color: '#fff', weight: 8, opacity: dark ? 0.15 : 0.9 }),
    L.polyline(r.path, { color: r.color, weight: 4.5, opacity: 0.85 }),
  ]).addTo(map);
});

const stopMarkers = {};
Object.entries(DATA.stops).forEach(([id, s]) => {
  if (!routes.some(r => r.stops.includes(id))) return;
  stopMarkers[id] = L.marker([s.lat, s.lon], {
    icon: L.divIcon({ className: '', html: '<div class="stop-dot"></div>', iconSize: [14, 14], iconAnchor: [7, 7] }),
    title: s.name, zIndexOffset: 100,
  }).addTo(map).bindPopup(() => stopPopup(id), { maxWidth: 280 });
});

function vehIcon(u, heading) {
  const c = u.route.color;
  return L.divIcon({
    className: '', iconSize: [30, 30], iconAnchor: [15, 15],
    html: `<div class="veh ${u === followed ? 'followed' : ''} ${u.dwell > 0 ? 'dwell' : ''}" style="--c:${c}">
             <div class="arrow" style="transform:rotate(${heading.toFixed(0)}deg)"></div>
             <div class="body" style="background:${c}">${esc(u.route.short)}</div></div>`,
  });
}
units.forEach(u => {
  const { latlng, heading } = pointAt(u.route, u.d);
  u.marker = L.marker(latlng, { icon: vehIcon(u, heading), zIndexOffset: 500, title: u.id })
    .addTo(map).bindPopup(() => unitPopup(u), { maxWidth: 260 });
});

/* ---------------- mi ubicación ---------------- */
let me = { latlng: DEFAULT_ME, source: 'simulada' };
const meMarker = L.marker(me.latlng, {
  draggable: true, zIndexOffset: 1000, title: 'Mi ubicación (arrástrame)',
  icon: L.divIcon({ className: '', html: '<div class="me-dot"></div>', iconSize: [20, 20], iconAnchor: [10, 10] }),
}).addTo(map);
let geoWatch = null;
const stopGeoWatch = () => { if (geoWatch != null) navigator.geolocation.clearWatch(geoWatch); geoWatch = null; };
meMarker.on('dragend', () => { stopGeoWatch(); setMe(Object.values(meMarker.getLatLng()), 'elegida en el mapa'); });

function setMe(latlng, source) {
  me = { latlng, source };
  meMarker.setLatLng(latlng);
  $('#originLabel').textContent = `Mi ubicación (${source})`;
  renderNotice();
  renderActive(true);
}
function renderNotice(extra) {
  const n = $('#locNotice');
  const far = haversine(me.latlng, TAXCO_CENTER);
  if (me.source === 'GPS' && far < 25000) { n.hidden = true; return; }
  n.hidden = false;
  if (me.source === 'GPS') {
    n.innerHTML = `📍 Usando tu GPS: estás a ${fmtDist(far)} de Taxco, así que no hay paradas cerca. <button id="backTaxco">Volver a Taxco</button>`;
    $('#backTaxco').onclick = () => { stopGeoWatch(); setMe(DEFAULT_ME, 'de prueba'); map.flyTo(DEFAULT_ME, 16); };
    return;
  }
  n.innerHTML = `${extra ? esc(extra) + ' ' : ''}📍 Ubicación ${esc(me.source)}. Arrastra el punto azul o
    <button id="useGps">usa tu GPS</button>.`;
  $('#useGps').onclick = locate;
}
function locate() {
  if (!navigator.geolocation) { renderNotice('Tu navegador no tiene GPS.'); return; }
  toast('Buscando tu ubicación…');
  stopGeoWatch();
  let first = true;
  // sigue la ubicación mientras te mueves; arrastrar el punto o "Volver a Taxco" la detiene
  geoWatch = navigator.geolocation.watchPosition(pos => {
    const ll = [pos.coords.latitude, pos.coords.longitude];
    setMe(ll, 'GPS');
    if (first) { first = false; map.flyTo(ll, 16); }
  }, err => renderNotice(err.code === 1 ? 'Aquí no hay acceso al GPS.' : 'No se pudo obtener el GPS.'),
  { enableHighAccuracy: true, timeout: 10000 });
}
$('#locateBtn').onclick = locate;

/* ---------------- popups ---------------- */
function arrivalsListHTML(stopId, limitPerVisit = 2) {
  const rows = [];
  routes.filter(r => r.visible).forEach(r => r.visits.filter(v => v.stopId === stopId).forEach(v => {
    const arr = arrivalsFor(r, v).slice(0, limitPerVisit);
    if (!arr.length) return;
    rows.push({ r, v, arr });
  }));
  rows.sort((a, b) => a.arr[0].s - b.arr[0].s);
  if (!rows.length) return '<p class="muted">Sin rutas visibles en esta parada.</p>';
  return `<ul class="arrivals">${rows.map(({ r, v, arr }) => `
    <li><span class="badge" style="background:${r.color}">${esc(r.short)}</span>
      <span class="dir">→ ${esc(v.toward)}</span>
      <span class="eta ${arr[0].s < 45 ? 'now' : ''}">${fmtMin(arr[0].s)}${arr[1] ? ` <small>· ${fmtMin(arr[1].s)}</small>` : ''}</span>
      <button class="link-btn" data-follow="${esc(arr[0].u.id)}" data-stop="${esc(stopId)}" data-visit="${v.k}" title="Seguir la próxima unidad">Seguir</button>
    </li>`).join('')}</ul>`;
}
// Leaflet aísla los clics de los popups: se enlazan directamente
function bindFollow(el) {
  el.querySelectorAll('[data-follow]').forEach(b => b.addEventListener('click', ev => {
    ev.stopPropagation(); follow(b.dataset.follow, b.dataset.stop, b.dataset.visit);
  }));
  return el;
}
function stopPopup(id) {
  const s = DATA.stops[id];
  const el = document.createElement('div');
  el.className = 'pop';
  el.innerHTML = `<h4>🚏 ${esc(stopLabel(id))}</h4><p>A ${fmtDist(haversine(me.latlng, [s.lat, s.lon]))} de ti</p>${arrivalsListHTML(id)}`;
  return bindFollow(el);
}
function unitPopup(u) {
  const r = u.route;
  const next = r.visits.map(v => ({ v, s: etaTo(u, v.pos) })).filter(x => x.s > 0).sort((a, b) => a.s - b.s)[0];
  const el = document.createElement('div');
  el.className = 'pop';
  el.innerHTML = `<h4><span class="badge" style="background:${r.color}">${esc(r.short)}</span> Unidad ${esc(u.id)}</h4>
    <p>${esc(r.name)}</p>
    <p>Siguiente parada: <b>${esc(DATA.stops[next.v.stopId].name)}</b> (${fmtMin(next.s)})</p>
    <p>Ocupación: <b>${u.occupied}/${u.seats}</b> · ${(u.speed * 3.6).toFixed(0)} km/h</p>
    <button class="btn" data-follow="${esc(u.id)}" data-stop="${esc(next.v.stopId)}" data-visit="${next.v.k}">Seguir esta unidad</button>`;
  return bindFollow(el);
}

/* ---------------- seguir una unidad ---------------- */
function follow(unitId, stopId, visitK) {
  const u = units.find(x => x.id === unitId);
  if (!u) return;
  followed = u; followTarget = { stopId, visit: u.route.visits[+visitK] }; alerted = false;
  map.closePopup();
  map.flyTo(u.marker.getLatLng(), 16);
  renderTracker();
}
function renderTracker() {
  const t = $('#tracker');
  if (!followed) { t.hidden = true; return; }
  const s = etaTo(followed, followTarget.visit.pos);
  const name = DATA.stops[followTarget.stopId].name;
  // si el ETA "salta" hacia arriba, la unidad ya pasó por la parada
  if (!driver.on && followTarget.lastS != null && followTarget.lastS < 90 && s > followTarget.lastS + 120) {
    toast(`✅ La ${followed.id} ya pasó por ${name}.`);
    followed = null; t.hidden = true; return;
  }
  followTarget.lastS = s;
  t.hidden = false;
  t.innerHTML = `<span class="badge" style="background:${followed.route.color}">${esc(followed.route.short)}</span>
    <div class="info"><strong>${esc(followed.id)} · ${s < 1 ? 'en tu parada' : fmtMin(s)}</strong><br>
      <span class="muted">a ${esc(name)} → ${esc(followTarget.visit.toward)} · ${followed.occupied}/${followed.seats} lugares</span></div>
    <button class="x" id="unfollow" aria-label="Dejar de seguir">✕</button>`;
  $('#unfollow').onclick = () => { followed = null; renderTracker(); };
  if (!alerted && s < 120) {
    alerted = true;
    toast(`🚐 ¡La ${followed.id} está a menos de 2 min de ${name}!`);
    if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
  }
}
document.addEventListener('click', e => {
  const b = e.target.closest('[data-follow]');
  if (b) follow(b.dataset.follow, b.dataset.stop, b.dataset.visit);
});

/* ---------------- pestaña: cerca de mí ---------------- */
function renderNear() {
  const near = Object.keys(stopMarkers)
    .map(id => ({ id, d: haversine(me.latlng, [DATA.stops[id].lat, DATA.stops[id].lon]) }))
    .sort((a, b) => a.d - b.d).slice(0, 4);
  $('#tab-near').innerHTML = `<h3 class="section">Paradas más cercanas</h3>` + near.map(({ id, d }) => `
    <div class="card">
      <div class="card-head"><strong>🚏 ${esc(stopLabel(id))}</strong>
        <span class="muted">${d > 3000 ? fmtDist(d) : `🚶 ${Math.max(1, Math.round(d / WALK_M_PER_MIN))} min · ${fmtDist(d)}`}</span></div>
      ${arrivalsListHTML(id)}
      <button class="link-btn" data-goto="${esc(id)}">Ver en el mapa</button>
    </div>`).join('') +
    `<p class="muted small">Horario de servicio aprox. ${SERVICE_HOURS}. Tiempos estimados con GPS de las unidades.</p>`;
}
document.addEventListener('click', e => {
  const b = e.target.closest('[data-goto]');
  if (!b) return;
  const s = DATA.stops[b.dataset.goto];
  map.flyTo([s.lat, s.lon], 17);
  setTimeout(() => stopMarkers[b.dataset.goto].openPopup(), 600);
});

/* ---------------- pestaña: rutas ---------------- */
function renderRoutes() {
  $('#tab-routes').innerHTML = routes.map(r => {
    const n = units.filter(u => u.route === r).length;
    const freq = Math.round(r.cycleS / n / 60);
    const km = r.circuito ? `${(r.L / 1000).toFixed(1)} km por vuelta` : `${(r.L / 2000).toFixed(1)} km por sentido`;
    return `<div class="card">
      <div class="route-row"><span class="badge" style="background:${r.color}">${esc(r.short)}</span>
        <div class="info"><strong>${esc(r.name)}</strong>
          ${r.confirmada ? '<span class="tag tag-ok">Recorrido confirmado</span>' : ''}
          <div class="muted">${fmtFare(r)} · cada ~${freq} min${r.units_pending ? ' (estimado)' : ''} · ${n} unidades · ${km}${r.circuito ? ' · circuito de un sentido' : ''}</div></div></div>
      <details><summary class="link-btn">Paradas (${r.stops.length})</summary>
        <ol class="stops-line" style="--c:${r.color}">${r.stops.map(id => `<li>${esc(DATA.stops[id].name)}</li>`).join('')}</ol>
      </details>
      <div class="row"><button class="link-btn" data-fit="${r.id}">Ver ruta</button>
        <button class="link-btn" data-toggle="${r.id}">${r.visible ? 'Ocultar' : 'Mostrar'}</button></div>
    </div>`;
  }).join('') + `<p class="muted small">Tarifas urbanas: $11.00 en rutas que llegan al Zócalo y $11.50 en las demás. Iremos agregando más rutas conforme se confirmen sus recorridos.</p>`;
}
document.addEventListener('click', e => {
  const f = e.target.closest('[data-fit]');
  if (f) { const r = routeById[f.dataset.fit]; if (!r.visible) toggleRoute(r.id); map.fitBounds(L.latLngBounds(r.path), fitPad()); }
  const t = e.target.closest('[data-toggle]');
  if (t) toggleRoute(t.dataset.toggle);
});

function renderChips() {
  $('#routeChips').innerHTML = routes.map(r => `
    <button class="route-chip ${r.visible ? '' : 'off'}" data-toggle="${r.id}" aria-pressed="${r.visible}" title="${esc(r.name)}">
      <span class="badge" style="background:${r.color}">${esc(r.short)}</span>${esc(r.chip || (r.name.split('·')[1] ? r.name.split('·')[1].split('–')[0].trim() : r.name))}
    </button>`).join('');
}
function toggleRoute(id) {
  const r = routeById[id];
  r.visible = !r.visible;
  if (r.visible) routeLayers[id].addTo(map); else map.removeLayer(routeLayers[id]);
  units.filter(u => u.route === r).forEach(u => r.visible ? u.marker.addTo(map) : map.removeLayer(u.marker));
  if (!r.visible && followed && followed.route === r) { followed = null; renderTracker(); }
  renderChips(); renderActive(true);
}

/* ---------------- pestaña: planear viaje ---------------- */
const planLayer = L.layerGroup().addTo(map);
let planOptions = [], selectedPlan = 0;

function fillDest() {
  const sel = $('#destSelect');
  sel.innerHTML = '<option value="">Elige un destino…</option>' + Object.keys(stopMarkers)
    .sort((a, b) => stopLabel(a).localeCompare(stopLabel(b), 'es'))
    .map(id => `<option value="${id}">${esc(stopLabel(id))}</option>`).join('');
  sel.onchange = () => { selectedPlan = 0; renderPlan(true); };
}

function computePlans(destId) {
  const dest = [DATA.stops[destId].lat, DATA.stops[destId].lon];
  const direct = haversine(me.latlng, dest);
  const opts = [];
  routes.filter(r => r.visible).forEach(r => {
    let best = null;
    r.visits.forEach(bv => {
      const bs = DATA.stops[bv.stopId];
      const walk1 = haversine(me.latlng, [bs.lat, bs.lon]) * 1.3; // factor de calles
      if (walk1 > MAX_WALK_M) return;
      const walk1S = (walk1 / WALK_M_PER_MIN) * 60;
      r.visits.forEach(av => {
        if (av.stopId === bv.stopId) return;
        const as = DATA.stops[av.stopId];
        const walk2 = haversine([as.lat, as.lon], dest) * 1.3;
        if (walk2 > MAX_WALK_M) return;
        const rideM = ((av.pos - bv.pos) % r.L + r.L) % r.L;
        const nStops = r.visits.filter(v => { const d = ((v.pos - bv.pos) % r.L + r.L) % r.L; return d > 1 && d < rideM - 1; }).length;
        const rideS = rideM / r.moving + nStops * DWELL_S;
        const arr = arrivalsFor(r, bv).find(a => a.s >= walk1S) || arrivalsFor(r, bv)[0];
        const boardS = Math.max(walk1S, arr.s);
        const total = boardS + rideS + (walk2 / WALK_M_PER_MIN) * 60;
        if (walk1 + walk2 >= direct * 1.3) return; // caminar todo sería igual o mejor
        if (!best || total < best.total) best = { r, bv, av, walk1, walk2, rideM, rideS, nStops, unit: arr.u, waitS: arr.s, boardS, total };
      });
    });
    if (best) opts.push(best);
  });
  opts.sort((a, b) => a.total - b.total);
  return { opts: opts.slice(0, 3), direct };
}

function renderPlan(redraw) {
  const destId = $('#destSelect').value;
  const box = $('#planResults');
  if (!destId) { box.innerHTML = '<p class="muted">Elige a dónde vas y te decimos qué combi tomar, dónde subir y cuánto tardas.</p>'; planLayer.clearLayers(); return; }
  const { opts, direct } = computePlans(destId);
  planOptions = opts;
  const walkMin = Math.round((direct * 1.3) / WALK_M_PER_MIN);
  let html = '';
  if (!opts.length && walkMin <= 25) html += `<div class="card"><strong>🚶 Caminando llegas en ~${walkMin} min.</strong><p class="muted">Está cerca: ninguna ruta te ahorra tiempo.</p></div>`;
  else if (!opts.length) html += `<div class="card"><strong>No hay una ruta directa cerca.</strong><p class="muted">Prueba acercar tu ubicación a una parada o activa más rutas. (Transbordos: siguiente versión.)</p></div>`;
  opts.forEach((o, i) => {
    const mins = Math.round(o.total / 60);
    html += `<div class="card click ${i === selectedPlan ? 'selected' : ''}" data-plan="${i}">
      <div class="card-head"><span class="row"><span class="badge" style="background:${o.r.color}">${esc(o.r.short)}</span>
        <span class="muted">→ ${esc(o.bv.toward)}</span></span><span class="total">${mins} min</span></div>
      <ol class="steps">
        <li><span class="ico">🚶</span><span>Camina ${Math.max(1, Math.round(o.walk1 / WALK_M_PER_MIN))} min a <b>${esc(DATA.stops[o.bv.stopId].name)}</b></span></li>
        <li><span class="ico">⏱️</span><span>La unidad <b>${esc(o.unit.id)}</b> pasa en <b>${fmtMin(o.waitS)}</b>${o.waitS < (o.walk1 / WALK_M_PER_MIN) * 60 ? ' (¡apúrate!)' : ''}</span></li>
        <li><span class="ico">🚐</span><span>Viaja ${o.nStops + 1} parada${o.nStops ? 's' : ''} (${fmtDist(o.rideM)}, ~${Math.round(o.rideS / 60)} min) · <b>${fmtFare(o.r)}</b></span></li>
        <li><span class="ico">🏁</span><span>Baja en <b>${esc(DATA.stops[o.av.stopId].name)}</b>${o.walk2 > 60 ? ` y camina ${Math.round(o.walk2 / WALK_M_PER_MIN)} min` : ''}</span></li>
      </ol>
      <div class="row" style="margin-top:8px"><button class="btn" data-follow="${esc(o.unit.id)}" data-stop="${esc(o.bv.stopId)}" data-visit="${o.bv.k}">Avisarme cuando llegue</button></div>
    </div>`;
  });
  if (opts.length && walkMin <= Math.round(opts[0].total / 60)) html = `<div class="card"><strong>🚶 Caminando llegas en ~${walkMin} min.</strong><p class="muted">Es igual o más rápido que tomar transporte.</p></div>` + html;
  box.innerHTML = html;
  if (redraw) drawPlan();
}
function drawPlan() {
  planLayer.clearLayers();
  const o = planOptions[selectedPlan];
  const destId = $('#destSelect').value;
  if (!destId) return;
  const ds = DATA.stops[destId];
  L.marker([ds.lat, ds.lon], { icon: L.divIcon({ className: '', html: '<div class="dest-dot">🏁</div>', iconSize: [26, 26], iconAnchor: [6, 24] }), zIndexOffset: 900 }).addTo(planLayer);
  if (!o) return;
  const bs = DATA.stops[o.bv.stopId], as = DATA.stops[o.av.stopId];
  const ride = subPath(o.r, o.bv.pos, o.av.pos);
  L.polyline(ride, { color: '#111827', weight: 11, opacity: 0.25 }).addTo(planLayer);
  L.polyline(ride, { color: o.r.color, weight: 7 }).addTo(planLayer);
  L.polyline([me.latlng, [bs.lat, bs.lon]], { color: '#2563eb', weight: 4, dashArray: '2 8', lineCap: 'round' }).addTo(planLayer);
  L.polyline([[as.lat, as.lon], [ds.lat, ds.lon]], { color: '#2563eb', weight: 4, dashArray: '2 8', lineCap: 'round' }).addTo(planLayer);
  map.fitBounds(L.latLngBounds([me.latlng, [ds.lat, ds.lon], ...ride]), { ...fitPad(), maxZoom: 17 });
}
document.addEventListener('click', e => {
  const c = e.target.closest('[data-plan]');
  if (!c || e.target.closest('button')) return;
  selectedPlan = +c.dataset.plan; renderPlan(true);
});

/* ---------------- pestaña: conductor ---------------- */
const driver = { on: false, unit: null, watchId: null, gps: null, sent: 0, log: null, timer: null };
function renderDriver() {
  const p = $('#tab-driver');
  if (!driver.on) {
    p.innerHTML = `<div class="card"><strong>Modo conductor</strong>
      <p class="muted">Así funcionaría la app del chofer: comparte su GPS cada 5 s y los pasajeros ven la unidad en el mapa.</p>
      <label class="field"><span>Unidad</span><select id="drvUnit">${units.map(u => `<option value="${u.id}">${u.id} · ${esc(u.route.name)}</option>`).join('')}</select></label>
      <button class="btn" id="drvStart">Iniciar servicio</button></div>`;
    $('#drvStart').onclick = startDriver;
    return;
  }
  const u = driver.unit;
  p.innerHTML = `<div class="card">
      <div class="card-head"><strong><span class="badge" style="background:${u.route.color}">${esc(u.route.short)}</span> ${esc(u.id)} en servicio</strong>
        <span class="muted">${driver.sent} envíos</span></div>
      <p class="muted">Fuente de posición: ${driver.gps ? 'GPS del teléfono' : 'simulada (sin permiso de GPS o esperando señal)'}</p>
      <div class="row occ"><span>Pasajeros</span><button class="btn secondary" id="occMinus">−</button><b>${u.occupied}/${u.seats}</b><button class="btn secondary" id="occPlus">+</button></div>
      <div class="row" style="margin-top:10px">
        <button class="btn secondary" id="drvIncident">⚠️ Reportar incidente</button>
        <button class="btn danger" id="drvStop">Terminar servicio</button></div>
    </div>
    <h3 class="section">Último paquete enviado al servidor</h3>
    <div class="payload">${esc(driver.log || '…')}</div>`;
  $('#occMinus').onclick = () => { u.occupied = Math.max(0, u.occupied - 1); renderDriver(); };
  $('#occPlus').onclick = () => { u.occupied = Math.min(u.seats, u.occupied + 1); renderDriver(); };
  $('#drvStop').onclick = stopDriver;
  $('#drvIncident').onclick = () => { toast('Incidente enviado a la central: tráfico/obra reportado'); driver.log = JSON.stringify({ type: 'incident', unit_id: u.id, kind: 'trafico', ts: new Date().toISOString() }, null, 1); renderDriver(); };
}
function startDriver() {
  driver.unit = units.find(u => u.id === $('#drvUnit').value);
  driver.on = true; driver.sent = 0; driver.gps = null;
  if (navigator.geolocation) {
    driver.watchId = navigator.geolocation.watchPosition(pos => {
      const ll = [pos.coords.latitude, pos.coords.longitude];
      if (!driver.gps) map.flyTo(ll, 16);
      driver.gps = { ll, speed: pos.coords.speed, heading: pos.coords.heading, acc: pos.coords.accuracy };
    }, () => { driver.gps = null; }, { enableHighAccuracy: true, maximumAge: 3000 });
  }
  const send = () => {
    const u = driver.unit, p = pointAt(u.route, u.d);
    const ll = driver.gps ? driver.gps.ll : p.latlng;
    driver.log = JSON.stringify({
      type: 'position', unit_id: u.id, route_id: u.route.id,
      lat: +ll[0].toFixed(6), lon: +ll[1].toFixed(6),
      speed_kmh: driver.gps && driver.gps.speed != null ? +(driver.gps.speed * 3.6).toFixed(1) : +(u.dwell > 0 ? 0 : u.speed * 3.6).toFixed(1),
      heading: Math.round(driver.gps && driver.gps.heading != null ? driver.gps.heading : p.heading),
      accuracy_m: driver.gps ? Math.round(driver.gps.acc) : 5,
      occupancy: u.occupied, seats: u.seats, ts: new Date().toISOString(),
    }, null, 1);
    driver.sent++;
    if (activeTab === 'driver') renderDriver();
  };
  send(); driver.timer = setInterval(send, 5000);
  followed = driver.unit; followTarget = { stopId: driver.unit.route.visits[0].stopId, visit: driver.unit.route.visits[0] }; alerted = true;
  map.flyTo(driver.unit.marker.getLatLng(), 16);
  renderDriver(); renderTracker();
}
function stopDriver() {
  clearInterval(driver.timer);
  if (driver.watchId != null) navigator.geolocation.clearWatch(driver.watchId);
  Object.assign(driver, { on: false, unit: null, watchId: null, gps: null, log: null });
  followed = null; renderTracker(); renderDriver();
}

/* ---------------- pestañas y panel ---------------- */
let activeTab = 'near';
document.querySelectorAll('.tabs button').forEach(b => b.onclick = () => {
  document.querySelectorAll('.tabs button').forEach(x => x.classList.toggle('active', x === b));
  document.querySelectorAll('.tab-panel').forEach(x => x.classList.toggle('active', x.id === `tab-${b.dataset.tab}`));
  activeTab = b.dataset.tab;
  $('#sheet').classList.remove('collapsed');
  if (activeTab !== 'plan') planLayer.clearLayers();
  renderActive(true);
});
$('#sheetHandle').onclick = () => {
  const s = $('#sheet');
  if (s.classList.contains('collapsed')) s.classList.remove('collapsed');
  else if (s.classList.contains('expanded')) { s.classList.remove('expanded'); s.classList.add('collapsed'); }
  else s.classList.add('expanded');
};
function renderActive(redraw) {
  if (activeTab === 'near') renderNear();
  else if (activeTab === 'plan') renderPlan(redraw);
  else if (activeTab === 'routes' && redraw) renderRoutes();
  else if (activeTab === 'driver' && redraw) renderDriver();
}

$('#speedBtn').onclick = e => {
  simSpeed = simSpeed === 1 ? 5 : simSpeed === 5 ? 20 : 1;
  e.currentTarget.textContent = `x${simSpeed}`;
  toast(simSpeed === 1 ? 'Simulación en tiempo real' : `Simulación acelerada x${simSpeed}`);
};

let toastTimer;
function toast(msg) {
  const t = $('#toast');
  t.textContent = msg; t.classList.add('show');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove('show'), 3500);
}

/* ---------------- bucle principal ---------------- */
let last = performance.now(), uiTick = 0;
function tick() {
  const now = performance.now();
  const dt = Math.min(2, (now - last) / 1000) * simSpeed;
  last = now;
  units.forEach(u => {
    stepUnit(u, dt);
    if (!u.route.visible) return;
    const { latlng, heading } = pointAt(u.route, u.d);
    u.marker.setLatLng(latlng);
    const key = `${Math.round(heading / 10)}|${u.dwell > 0}|${u === followed}`;
    if (key !== u.iconKey) { u.iconKey = key; u.marker.setIcon(vehIcon(u, heading)); }
  });
  if (followed && driver.on && driver.gps) followed.marker.setLatLng(driver.gps.ll);
  if (++uiTick % 4 === 0) {               // cada ~2 s refresca textos
    renderActive(false);
    renderTracker();
    if (followed && !driver.on && !map.getBounds().pad(-0.2).contains(followed.marker.getLatLng())) map.panTo(followed.marker.getLatLng());
  }
}
setInterval(tick, 500);

renderChips(); fillDest(); renderNotice(); renderActive(true);
// encuadre inicial: la mancha urbana (sin localidades foráneas)
const fitTown = () => map.fitBounds(L.latLngBounds(routes.flatMap(r => r.path)), { ...fitPad(), maxZoom: 17 });
// si la página carga oculta o sin tamaño (pestaña en segundo plano), encuadra cuando ya mida algo
if (map.getSize().x > 100) fitTown(); else { const once = () => { if (map.getSize().x > 100) { fitTown(); window.removeEventListener('resize', once); } }; window.addEventListener('resize', once); }
})();
