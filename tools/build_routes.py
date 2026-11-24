"""Genera data/routes.js con el trazo de cada ruta.

Dos tipos de ruta:
- Confirmadas ("kml"): el trazo sale tal cual del KML/My Maps que dibujó quien conoce la ruta
  (carpeta rutas/). Si es un circuito de un solo sentido, se recorre en el orden en que se dibujó.
- De ejemplo (sin "kml"): ida y vuelta por la misma lista de paradas, trazada sobre calles con OSRM.

Uso:  python tools/build_routes.py
"""
import json, math, time, urllib.request, pathlib
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent

STOPS = {
    # --- confirmadas ---
    "sanmiguel":  ("Barrio de San Miguel (Plateros 501)", 18.55365, -99.60253),
    "zocalo":     ("Zócalo / Plaza Borda",         18.55658, -99.60548),
    # --- de ejemplo ---
    "arcos":      ("Los Arcos",                    18.56840, -99.60343),
    "cepe":       ("Teleférico / CEPE UNAM",        18.56740, -99.60538),
    "platn":      ("Av. de los Plateros Norte",    18.56538, -99.60388),
    "garita":     ("La Garita",                    18.56116, -99.60269),
    "juarez":     ("Calle Benito Juárez",          18.55926, -99.60286),
    "eblanca":    ("Terminal Estrella Blanca",     18.55578, -99.60228),
    "martelas":   ("Las Martelas (IMSS)",          18.55331, -99.60190),
    "bermeja":    ("Bermeja",                      18.55284, -99.60042),
    "eoro":       ("Terminal Estrella de Oro",     18.55355, -99.60616),
    "plats":      ("Av. de los Plateros Sur",      18.54767, -99.61189),
    "mercado":    ("Mercado Tetitlán",             18.55547, -99.60563),
    "guadalupe":  ("Templo de Guadalupe",          18.55865, -99.60681),
    "panoramica": ("La Panorámica",                18.55982, -99.60826),
    "llano":      ("Deportiva El Llano",           18.56223, -99.60959),
    "cristo":     ("Cristo Monumental (Atachi)",   18.56088, -99.61013),
    "libramiento":("Libramiento de Taxco",         18.56420, -99.59439),
    "tehui":      ("Tehuilotepec",                 18.55278, -99.57889),
    "tviejo":     ("Taxco el Viejo (UAGro)",       18.47617, -99.58052),
}

# Tarifas urbanas confirmadas (nov 2026): $11.00 si la ruta llega al Zócalo, $11.50 cualquier otra
# ruta dentro de la ciudad. Las foráneas llevan su propia tarifa ("fare"); mientras no esté confirmada,
# "fare_pending": True la marca en la app como "por confirmar".
TARIFA_ZOCALO = 11.00
TARIFA_URBANA = 11.50
VEL_COMBI_MS = 4.5   # velocidad media en movimiento para rutas KML (~16 km/h), sin contar paradas


def tarifa(r):
    if r["tipo"] == "foranea":
        return r["fare"]
    return TARIFA_ZOCALO if "zocalo" in r["stops"] else TARIFA_URBANA


ROUTES = [
    {"id": "ZOC", "name": "Ruta Zocalera · San Miguel – Zócalo", "short": "Z", "chip": "Zocalera", "color": "#1267ff",
     "tipo": "urbana", "confirmada": True, "kml": "rutas/ruta_zocalera.kml", "circuito": True,
     "units": 4, "units_pending": True, "stops": ["sanmiguel", "zocalo"]},
    {"id": "R1", "name": "Ruta 1 · Los Arcos – Estrella de Oro", "short": "1", "color": "#0891b2",
     "tipo": "urbana", "units": 5, "stops": ["arcos", "platn", "garita", "eblanca", "martelas", "eoro", "plats"]},
    {"id": "R2", "name": "Ruta 2 · Centro – Panorámica – Cristo", "short": "2", "color": "#16a34a",
     "tipo": "urbana", "units": 3, "stops": ["eblanca", "mercado", "guadalupe", "panoramica", "llano", "cristo"]},
    {"id": "R3", "name": "Ruta 3 · Los Arcos – Chorrillo – Zócalo", "short": "3", "color": "#dc2626",
     "tipo": "urbana", "units": 4, "stops": ["arcos", "cepe", "garita", "juarez", "zocalo", "eblanca"]},
    {"id": "R4", "name": "Ruta 4 · Bermeja – Tehuilotepec", "short": "4", "color": "#9333ea",
     "tipo": "foranea", "fare": 14, "fare_pending": True, "units": 2, "stops": ["eblanca", "bermeja", "libramiento", "tehui"]},
    {"id": "S1", "name": "Suburbana · Taxco – Taxco el Viejo", "short": "S", "color": "#ea580c",
     "tipo": "foranea", "fare": 22, "fare_pending": True, "units": 3, "stops": ["eoro", "plats", "tviejo"]},
]

OSRM = "https://router.project-osrm.org/route/v1/driving/"


def haversine(a, b):
    R, toR = 6371000, math.pi / 180
    dlat, dlon = (b[0] - a[0]) * toR, (b[1] - a[1]) * toR
    h = math.sin(dlat / 2) ** 2 + math.cos(a[0] * toR) * math.cos(b[0] * toR) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def osrm(points):
    coords = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in points)
    url = OSRM + coords + "?overview=full&geometries=geojson&steps=false"
    req = urllib.request.Request(url, headers={"User-Agent": "transit-prototype/0.1"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def read_kml_line(path):
    """Primer LineString del KML como [[lat, lon], ...] (sin puntos repetidos)."""
    ns = {"k": "http://www.opengis.net/kml/2.2"}
    txt = ET.parse(path).getroot().find(".//k:LineString/k:coordinates", ns).text
    pts = []
    for tok in txt.split():
        lon, lat = map(float, tok.split(",")[:2])
        p = [round(lat, 6), round(lon, 6)]
        if not pts or p != pts[-1]:
            pts.append(p)
    return pts


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
    path = read_kml_line(ROOT / r["kml"])
    cum = [0.0]
    for i in range(1, len(path)):
        cum.append(cum[-1] + haversine(path[i - 1], path[i]))
    L = cum[-1]
    placed = []
    for s in r["stops"]:
        pos, off = project(path, cum, (STOPS[s][1], STOPS[s][2]))
        if off > 60:
            raise SystemExit(f"{r['id']}: la parada {s} queda a {off:.0f} m del trazo")
        placed.append((pos, s))
    placed.sort()
    if not r.get("circuito"):
        raise SystemExit(f"{r['id']}: por ahora las rutas KML deben ser circuitos de un sentido")
    # circuito: el trazo empieza y termina en la primera parada (terminal)
    seq = [s for _, s in placed] + [placed[0][1]]
    stop_m = [round(p, 1) for p, _ in placed] + [round(L, 1)]
    toward = [STOPS[seq[k + 1]][0] for k in range(len(seq) - 1)]
    return {**r, "fare": tarifa(r), "sequence": seq, "stop_m": stop_m, "toward": toward,
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
    return {**r, "fare": tarifa(r), "sequence": seq, "stop_m": stop_pos,
            "length_m": round(route["distance"], 1), "osrm_s": round(route["duration"]), "path": geom}


def main():
    out_routes = []
    for r in ROUTES:
        o = build_kml_route(r) if r.get("kml") else build_osrm_route(r)
        out_routes.append(o)
        kind = "circuito (KML)" if r.get("kml") else "ida+vuelta (OSRM)"
        print(f"{r['id']}: {o['length_m']/1000:.1f} km {kind}, {len(o['path'])} puntos, "
              f"paradas en {o['stop_m']}, tarifa ${o['fare']:.2f}")
    data = {"generated": time.strftime("%Y-%m-%d"),
            "stops": {k: {"name": v[0], "lat": v[1], "lon": v[2]} for k, v in STOPS.items()},
            "routes": out_routes}
    dst = ROOT / "data" / "routes.js"
    dst.write_text("// Generado por tools/build_routes.py — no editar a mano\nwindow.TAXCO_DATA = "
                   + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    print("OK ->", dst)


if __name__ == "__main__":
    main()
