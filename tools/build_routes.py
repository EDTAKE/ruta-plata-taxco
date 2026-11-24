"""Genera data/routes.js con el trazo de cada ruta.

Dos tipos de ruta:
- Confirmadas ("kml"): el trazo sale tal cual del KML/My Maps que dibujó quien conoce la ruta
  (carpeta rutas/). Si es un circuito de un solo sentido, se recorre en el orden en que se dibujó.
- Sin "kml": ida y vuelta por la misma lista de paradas, trazada sobre calles con OSRM
  (útil cuando la ruta llega descrita por texto y aún no hay trazo dibujado).

Uso:  python tools/build_routes.py
"""
import json, math, time, urllib.request, pathlib
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent

STOPS = {
    "sanmiguel":  ("Barrio de San Miguel (Plateros 501)", 18.55365, -99.60253),
    "zocalo":     ("Zócalo / Plaza Borda",         18.55658, -99.60548),
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
