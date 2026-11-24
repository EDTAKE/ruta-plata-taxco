"""Genera data/routes.js con el trazo y las paradas de cada ruta.

Dos tipos de ruta:
- Confirmadas ("kml"): trazo y paradas salen del KML exportado de Google My Maps (carpeta rutas/).
  Si el mapa trae la ruta partida en varios tramos, se unen en el orden del archivo. Las paradas
  son los puntos del KML; se acomodan en el orden en que la combi pasa por ellas. Si es un
  circuito de un solo sentido, se recorre en el orden en que se dibujó.
- Sin "kml": ida y vuelta por una lista de paradas de STOPS, trazada sobre calles con OSRM
  (útil cuando la ruta llega descrita por texto y aún no hay trazo dibujado).

Uso:  python tools/build_routes.py
"""
import json, math, re, time, unicodedata, urllib.request, pathlib
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent
KML_NS = {"k": "http://www.opengis.net/kml/2.2"}

# Paradas definidas a mano (para rutas sin KML o para compartir entre rutas).
STOPS = {}

# Nombre corto para los puntos del KML. La llave es lo que va antes de la primera coma en el
# nombre del punto (Google Maps pone la dirección). Si un punto no está aquí, se usa esa dirección.
# El id "zocalo" importa: define la tarifa de $11.00.
NOMBRES_KML = {
    "Iguala - Taxco 501":         ("sanmiguel",       "San Miguel · Terminal (Plateros 501)"),
    "De Los Plateros 501":        ("plateros-501",    "Plateros, San Miguel"),
    "De Los Plateros 203b":       ("plateros-mora",   "Plateros, Barrio de Mora"),
    "De Los Plateros 280":        ("plateros-catarina-sur", "Plateros, La Catarina (sur)"),
    "De Los Plateros 123":        ("plateros-fundiciones", "Plateros, Fundiciones"),
    "FAD plateros":               ("fad-plateros",    "FAD Plateros"),
    "Elektra":                    ("elektra-plateros", "Elektra (Plateros)"),
    "De Los Plateros 131":        ("plateros-catarina-norte", "Plateros, La Catarina (norte)"),
    "Monumento al Minero":        ("minero",          "Monumento al Minero"),
    "C. Benito Juárez 63":        ("juarez-chavarrieta", "Calle Juárez, Chavarrieta"),
    "Cjón de las Palomas 29":     ("palomas",         "Callejón de las Palomas"),
    "De Altillo 2":               ("altillo",         "Calle del Altillo"),
    "C. Benito Juárez 7":         ("juarez-centro",   "Calle Juárez, Centro"),
    "Agustín de Tolsa 4":         ("zocalo",          "Zócalo / Plaza Borda"),
    "Carlos J. Nibbi 13":         ("nibbi",           "Calle Carlos J. Nibbi"),
    "C. de Tetitlán 22":          ("tetitlan",        "Calle Tetitlán"),
    "De J. M. Morelos y Pavón 4": ("morelos-sanmiguel", "Calle Morelos, San Miguel"),
}

# Tarifas urbanas confirmadas (nov 2026): $11.00 si la ruta llega al Zócalo, $11.50 cualquier otra
# ruta dentro de la ciudad. Las foráneas llevan su propia tarifa ("fare"); mientras no esté confirmada,
# "fare_pending": True la marca en la app como "por confirmar".
TARIFA_ZOCALO = 11.00
TARIFA_URBANA = 11.50
VEL_COMBI_MS = 4.5   # velocidad media en movimiento para rutas KML (~16 km/h), sin contar paradas
MAX_DIST_PARADA_M = 60


def tarifa(r, stops):
    if r["tipo"] == "foranea":
        return r["fare"]
    return TARIFA_ZOCALO if "zocalo" in stops else TARIFA_URBANA


ROUTES = [
    {"id": "ZOC", "name": "Ruta Zocalera · San Miguel – Zócalo", "short": "Z", "chip": "Zocalera", "color": "#1267ff",
     "tipo": "urbana", "confirmada": True, "kml": "rutas/ruta_zocalera.kml", "circuito": True,
     "units": 4, "units_pending": True},
]

OSRM = "https://router.project-osrm.org/route/v1/driving/"


def haversine(a, b):
    R, toR = 6371000, math.pi / 180
    dlat, dlon = (b[0] - a[0]) * toR, (b[1] - a[1]) * toR
    h = math.sin(dlat / 2) ** 2 + math.cos(a[0] * toR) * math.cos(b[0] * toR) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def slug(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def osrm(points):
    coords = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in points)
    url = OSRM + coords + "?overview=full&geometries=geojson&steps=false"
    req = urllib.request.Request(url, headers={"User-Agent": "transit-prototype/0.1"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def read_kml(path):
    """Devuelve (trazo [[lat, lon], ...] con todos los tramos unidos, puntos [(nombre, lat, lon)])."""
    root = ET.parse(path).getroot()
    line = []
    for i, el in enumerate(root.findall(".//k:LineString/k:coordinates", KML_NS)):
        seg = []
        for tok in el.text.split():
            lon, lat = map(float, tok.split(",")[:2])
            seg.append([round(lat, 6), round(lon, 6)])
        if line:
            gap = haversine(line[-1], seg[0])
            if gap > 30:
                raise SystemExit(f"{path.name}: el tramo {i + 1} empieza a {gap:.0f} m de donde acaba el anterior")
        for p in seg:
            if not line or p != line[-1]:
                line.append(p)
    points = []
    for pm in root.iter(f"{{{KML_NS['k']}}}Placemark"):
        c = pm.find(".//k:Point/k:coordinates", KML_NS)
        if c is None:
            continue
        lon, lat = map(float, c.text.strip().split(",")[:2])
        points.append((pm.findtext("k:name", "", KML_NS).strip(), round(lat, 6), round(lon, 6)))
    return line, points


def project(path, cum, pt):
    """Distancia a lo largo del trazo (m) del punto más cercano a pt, y qué tan lejos queda."""
    best = (float("inf"), 0.0)
    kx = math.cos(math.radians(pt[0]))
    for i in range(len(path) - 1):
        a, b = path[i], path[i + 1]
        ax, ay, bx, by, px, py = a[1] * kx, a[0], b[1] * kx, b[0], pt[1] * kx, pt[0]
        dx, dy = bx - ax, by - ay
        t = 0 if dx == dy == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        q = [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]
        d = haversine(q, pt)
        if d < best[0]:
            best = (d, cum[i] + t * (cum[i + 1] - cum[i]))
    return best[1], best[0]


def build_kml_route(r):
    if not r.get("circuito"):
        raise SystemExit(f"{r['id']}: por ahora las rutas KML deben ser circuitos de un sentido")
    path, points = read_kml(ROOT / r["kml"])
    cum = [0.0]
    for i in range(1, len(path)):
        cum.append(cum[-1] + haversine(path[i - 1], path[i]))
    L = cum[-1]
    placed, seen = [], set()
    for name, lat, lon in points:
        key = name.split(",")[0].strip()
        sid, label = NOMBRES_KML.get(key, (slug(key), key))
        if sid in seen:
            continue                      # la terminal y los puntos de unión vienen repetidos
        seen.add(sid)
        STOPS[sid] = (label, lat, lon)
        if haversine(path[0], (lat, lon)) < 30:
            pos, off = 0.0, haversine(path[0], (lat, lon))   # terminal: inicio del circuito
        else:
            pos, off = project(path, cum, (lat, lon))
        if off > MAX_DIST_PARADA_M:
            raise SystemExit(f"{r['id']}: la parada «{label}» queda a {off:.0f} m del trazo")
        placed.append((pos, sid))
    placed.sort()
    if placed[0][0] != 0.0:
        raise SystemExit(f"{r['id']}: ninguna parada coincide con el inicio del trazo (terminal)")
    stops = [s for _, s in placed]
    seq = stops + [stops[0]]
    stop_m = [round(p, 1) for p, _ in placed] + [round(L, 1)]
    toward = [STOPS[seq[k + 1]][0] for k in range(len(seq) - 1)]
    return {**r, "stops": stops, "fare": tarifa(r, stops), "sequence": seq, "stop_m": stop_m, "toward": toward,
            "length_m": round(L, 1), "osrm_s": round(L * 0.6 / VEL_COMBI_MS), "path": path}


def build_osrm_route(r):
    # Recorrido de ida y vuelta: A..B y de regreso B..A (circuito cerrado)
    seq = r["stops"] + r["stops"][-2::-1]
    res = osrm([(STOPS[s][1], STOPS[s][2]) for s in seq])
    if res.get("code") != "Ok":
        raise SystemExit(f"OSRM falló en {r['id']}: {res}")
    route = res["routes"][0]
    geom = [[round(lat, 6), round(lon, 6)] for lon, lat in route["geometry"]["coordinates"]]
    cum, stop_pos = 0.0, [0.0]
    for leg in route["legs"]:
        cum += leg["distance"]
        stop_pos.append(round(cum, 1))
    time.sleep(1.5)
    return {**r, "fare": tarifa(r, r["stops"]), "sequence": seq, "stop_m": stop_pos,
            "length_m": round(route["distance"], 1), "osrm_s": round(route["duration"]), "path": geom}


def main():
    out_routes = []
    for r in ROUTES:
        o = build_kml_route(r) if r.get("kml") else build_osrm_route(r)
        out_routes.append(o)
        kind = "circuito (KML)" if r.get("kml") else "ida+vuelta (OSRM)"
        print(f"{r['id']}: {o['length_m']/1000:.1f} km {kind}, {len(o['path'])} puntos, "
              f"{len(o['stops'])} paradas, tarifa ${o['fare']:.2f}")
        for sid, m in zip(o["sequence"], o["stop_m"]):
            print(f"   {m:7.0f} m  {STOPS[sid][0]}")
    used = {s for o in out_routes for s in o["sequence"]}
    data = {"generated": time.strftime("%Y-%m-%d"),
            "stops": {k: {"name": v[0], "lat": v[1], "lon": v[2]} for k, v in STOPS.items() if k in used},
            "routes": out_routes}
    dst = ROOT / "data" / "routes.js"
    dst.write_text("// Generado por tools/build_routes.py — no editar a mano\nwindow.TAXCO_DATA = "
                   + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    print("OK ->", dst)


if __name__ == "__main__":
    main()
