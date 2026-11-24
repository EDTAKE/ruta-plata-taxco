"""Genera data/routes.js con el trazo de cada ruta sobre calles reales (OSRM + OpenStreetMap).

Uso:  python tools/build_routes.py
Las paradas y rutas son ILUSTRATIVAS: reemplazar por el levantamiento real (o GTFS)
de las rutas concesionadas en Taxco antes de cualquier uso productivo.
"""
import json, time, urllib.request, pathlib

STOPS = {
    "arcos":      ("Los Arcos",                    18.56840, -99.60343),
    "cepe":       ("Teleférico / CEPE UNAM",        18.56740, -99.60538),
    "platn":      ("Av. de los Plateros Norte",    18.56538, -99.60388),
    "garita":     ("La Garita",                    18.56116, -99.60269),
    "juarez":     ("Calle Benito Juárez",          18.55926, -99.60286),
    "zocalo":     ("Zócalo / Santa Prisca",        18.55636, -99.60474),
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


def tarifa(r):
    if r["tipo"] == "foranea":
        return r["fare"]
    return TARIFA_ZOCALO if "zocalo" in r["stops"] else TARIFA_URBANA


ROUTES = [
    {"id": "R1", "name": "Ruta 1 · Los Arcos – Estrella de Oro", "short": "1", "color": "#2563eb",
     "tipo": "urbana", "headway_min": 6, "units": 5, "stops": ["arcos", "platn", "garita", "eblanca", "martelas", "eoro", "plats"]},
    {"id": "R2", "name": "Ruta 2 · Centro – Panorámica – Cristo", "short": "2", "color": "#16a34a",
     "tipo": "urbana", "headway_min": 10, "units": 3, "stops": ["eblanca", "mercado", "guadalupe", "panoramica", "llano", "cristo"]},
    {"id": "R3", "name": "Ruta 3 · Los Arcos – Chorrillo – Zócalo", "short": "3", "color": "#dc2626",
     "tipo": "urbana", "headway_min": 8, "units": 4, "stops": ["arcos", "cepe", "garita", "juarez", "zocalo", "eblanca"]},
    {"id": "R4", "name": "Ruta 4 · Bermeja – Tehuilotepec", "short": "4", "color": "#9333ea",
     "tipo": "foranea", "fare": 14, "fare_pending": True, "headway_min": 15, "units": 2, "stops": ["eblanca", "bermeja", "libramiento", "tehui"]},
    {"id": "S1", "name": "Suburbana · Taxco – Taxco el Viejo", "short": "S", "color": "#ea580c",
     "tipo": "foranea", "fare": 22, "fare_pending": True, "headway_min": 20, "units": 3, "stops": ["eoro", "plats", "tviejo"]},
]

OSRM = "https://router.project-osrm.org/route/v1/driving/"


def osrm(points):
    coords = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in points)
    url = OSRM + coords + "?overview=full&geometries=geojson&steps=false"
    req = urllib.request.Request(url, headers={"User-Agent": "transit-prototype/0.1"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def main():
    out_routes = []
    for r in ROUTES:
        # Recorrido de ida y vuelta: A..B y de regreso B..A (circuito cerrado)
        seq = r["stops"] + r["stops"][-2::-1]
        pts = [(STOPS[s][1], STOPS[s][2]) for s in seq]
        res = osrm(pts)
        if res.get("code") != "Ok":
            raise SystemExit(f"OSRM falló en {r['id']}: {res}")
        route = res["routes"][0]
        geom = [[round(lat, 6), round(lon, 6)] for lon, lat in route["geometry"]["coordinates"]]
        # distancia acumulada (m) de cada parada sobre el trazo
        cum, stop_pos = 0.0, [0.0]
        for leg in route["legs"]:
            cum += leg["distance"]
            stop_pos.append(round(cum, 1))
        out_routes.append({**r, "fare": tarifa(r), "sequence": seq, "stop_m": stop_pos,
                           "length_m": round(route["distance"], 1),
                           "osrm_s": round(route["duration"]), "path": geom})
        print(f"{r['id']}: {route['distance']/1000:.1f} km ida+vuelta, {len(geom)} puntos")
        time.sleep(1.5)
    data = {"generated": time.strftime("%Y-%m-%d"),
            "stops": {k: {"name": v[0], "lat": v[1], "lon": v[2]} for k, v in STOPS.items()},
            "routes": out_routes}
    dst = pathlib.Path(__file__).resolve().parent.parent / "data" / "routes.js"
    dst.write_text("// Generado por tools/build_routes.py — no editar a mano\nwindow.TAXCO_DATA = "
                   + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    print("OK ->", dst)


if __name__ == "__main__":
    main()
