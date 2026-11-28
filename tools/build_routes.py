"""Genera data/routes.json con el trazo y las paradas de cada ruta.

Dos tipos de ruta:
- Confirmadas ("kml"): trazo y paradas salen del KML exportado de Google My Maps (carpeta rutas/).
  Si el mapa trae la ruta partida en varios tramos, se unen en el orden del archivo. Las paradas
  son los puntos del KML; se acomodan en el orden en que la combi pasa por ellas.
  · "circuito": un solo sentido, se recorre en el orden en que se dibujó.
  · "ida_y_vuelta": el KML trae sólo la ida; la vuelta regresa por las mismas calles y para
    en las mismas paradas, en orden inverso.
- Sin "kml": ida y vuelta por una lista de paradas de STOPS, trazada sobre calles con OSRM
  (útil cuando la ruta llega descrita por texto y aún no hay trazo dibujado).

Uso:  python tools/build_routes.py
"""
import hashlib, json, math, re, time, unicodedata, urllib.request, pathlib
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent
KML_NS = {"k": "http://www.opengis.net/kml/2.2"}

# Paradas definidas a mano (para rutas sin KML o para compartir entre rutas).
STOPS = {}

# Nombres con los que se conoce cada parada en Taxco (confirmados nov 2026) para los puntos del KML. La llave es lo que va antes de la primera coma en el
# nombre del punto (Google Maps pone la dirección). Si un punto no está aquí, se usa esa dirección.
# El id "zocalo" importa: define la tarifa de $11.00.
NOMBRES_KML = {
    "Iguala - Taxco 501":         ("sanmiguel",       "Seguro IMSS"),
    "De Los Plateros 501":        ("plateros-501",    "Telmex"),
    "De Los Plateros 203b":       ("plateros-mora",   "La Terminal"),
    "De Los Plateros 280":        ("plateros-catarina-sur", "Comex"),
    "De Los Plateros 123":        ("plateros-fundiciones", "Reforma"),
    "FAD plateros":               ("fad-plateros",    "FAD Plateros"),
    "Elektra":                    ("elektra-plateros", "Elektra"),
    "De Los Plateros 131":        ("plateros-catarina-norte", "La Misión"),
    "Monumento al Minero":        ("minero",          "La Garita"),
    "C. Benito Juárez 63":        ("juarez-chavarrieta", "Chavarrieta 1"),
    "Cjón de las Palomas 29":     ("palomas",         "Chavarrieta 2"),
    "De Altillo 2":               ("altillo",         "Ex Convento"),
    "C. Benito Juárez 7":         ("juarez-centro",   "Castillos"),
    "Agustín de Tolsa 4":         ("zocalo",          "Zócalo"),
    "Agustín de Tolsa 7":         ("zocalo",          "Zócalo"),   # a 16 m del anterior
    "Carlos J. Nibbi 13":         ("nibbi",           "Plazuela"),
    "C. de Tetitlán 22":          ("tetitlan",        "Parque"),
    "De J. M. Morelos y Pavón 4": ("morelos-sanmiguel", "San Miguel"),
    # Ruta Plazuela – CBTIS (ida y vuelta comparten las de Nibbi 76 y Loma del Santito)
    "Carlos J. Nibbi 53":         ("paris",           "Paris"),
    "Carlos J. Nibbi 81":         ("taller-lugo",     "Taller Lugo"),
    "Carlos J. Nibbi 76":         ("nibbi-20-nov",    "20 de Noviembre"),
    "Loma del Santito 120":       ("la-cadena",       "La Cadena"),
    "Loma del Santito 160":       ("telmex-santito",  "Telmex"),
    "Loma del Santito 182":       ("montana-de-plata", "Montaña de Plata"),
    "H92J+JC":                    ("cbtis",           "Campamento"),
    "20 de Noviembre 21":         ("primaria-20-nov", "Primaria 20 de Noviembre"),
    "Tlachichilpan 10":           ("ojeda-1",         "Ojeda 1"),
    "Del Progreso 25":            ("ojeda-2",         "Ojeda 2"),
    # Ruta Arcos – Pedro Martín (los ids repetidos son paradas que comparte con la Zocalera)
    "Nueva Carretera a México 65": ("gasolinera-arcos", "Gasolinera Arcos"),
    "C. del Chorrillo 95A":       ("teleferico",      "Teleférico"),
    "Florida 29":                 ("la-florida",      "La Florida"),
    "Florida 18A1":               ("super-che",       "Super Che"),
    "De Los Plateros s/n":        ("minero",          "La Garita"),
    "Cuernavaca - Taxco 125":     ("plateros-catarina-norte", "La Misión"),
    "De Los Plateros 171":        ("plateros-fundiciones", "Reforma"),
    "De Los Plateros 217":        ("sanmiguel",       "Seguro IMSS"),
    "De Los Plateros 79":         ("estrella-de-oro", "Estrella de Oro"),
    "Huiyatengo 285":             ("huiyatengo",      "Huiyatengo"),
    "De Los Plateros 42":         ("pedro-martin",    "Pedro Martín"),
    "De Los Plateros 333":        ("gasolinera-pedro-martin", "Gasolinera Pedro Martín"),
    # Ruta CBTIS – Garita (los ids repetidos son paradas que comparte con otras rutas)
    "C. Coordinadores 16":        ("cbtis-82",        "CBTIS 82"),
    "Emiliano Zapata 1":          ("zapata",          "Zapata"),
    "Cuauhtémoc 48":              ("los-pocitos",     "Los Pocitos"),
    "Del Plomo 2":                ("fovissste",       "Fovissste"),
    "Cuauhtémoc 1":               ("gigante",         "Gigante"),
    "Iguala - Taxco 454":         ("gasolinera-pedro-martin", "Gasolinera Pedro Martín"),
    "De Los Plateros 277":        ("huiyatengo",      "Huiyatengo"),
    "De Los Plateros 380A":       ("estrella-de-oro", "Estrella de Oro"),
    "De Los Plateros 332":        ("coppel",          "Coppel"),
    "De Los Plateros 310":        ("plateros-501",    "Telmex"),
    "Taxco Iguala":               ("plateros-mora",   "La Terminal"),
    "De Los Plateros 232":        ("plateros-fundiciones", "Reforma"),
    "De Los Plateros 54":         ("fad-plateros",    "FAD Plateros"),
    "De Los Plateros 184":        ("elektra-plateros", "Elektra"),
    "De Los Plateros 164":        ("plateros-catarina-norte", "La Misión"),
    # Ruta Taxco – Tehuilotepec – Acamixtla (foránea)
    "De Los Plateros 278":        ("casa-janna",      "Casa Janna"),
    "Segunda de la Catarina 14":  ("plateros-fundiciones", "Reforma"),
    "Cuernavaca - Taxco 54":      ("fad-plateros",    "FAD Plateros"),
    "Adolfo López Mateos 1":      ("plateros-catarina-norte", "La Misión"),
    "De Los Plateros 68":         ("super-che",       "Super Che"),
    "De La Florida 31":           ("teleferico",      "Teleférico"),
    "Mirna Acevedo de Juárez Cisneros 22": ("el-gas", "El Gas"),
    "Toluca y México":            ("martelas",        "Martelas"),
    "Tonatico - Taxco":           ("tehuilotepec-1",  "Tehuilotepec 1"),
    "HC59+9R":                    ("tehuilotepec-2",  "Tehuilotepec 2 - El Crucero"),
    "El Cedro":                   ("el-cedrito",      "El Cedrito"),
    "Av. Cuauhtémoc 85":          ("secundaria-caudillos", "Secundaria Caudillos"),
    "Vicente Guerrero 7":         ("iglesia-acamixtla", "Iglesia Acamixtla"),
    "Juan N Álvarez 17":          ("zocalo-acamixtla", "Zócalo Acamixtla"),   # ojo: no es "zocalo"
}

# Tarifas urbanas confirmadas (nov 2026): $11.00 si la ruta llega al Zócalo, $11.50 cualquier otra
# ruta dentro de la ciudad. Las foráneas llevan su propia tarifa ("fare"); mientras no esté confirmada,
# "fare_pending": True la marca en la app como "por confirmar".
TARIFA_ZOCALO = 11.00
TARIFA_URBANA = 11.50
VEL_COMBI_MS = 4.5   # velocidad media en movimiento para rutas KML (~16 km/h), sin contar paradas
VEL_FORANEA_MS = 7.0  # foráneas: buena parte en carretera (~25 km/h)
MAX_DIST_PARADA_M = 60


def tarifa_por_tramo(r, stops):
    """Índice de tramo de cada parada: 0 dentro de Taxco, 1, 2, … para cada parada foránea.
    Tarifa entre dos paradas = max(mínima, máxima − baja × (N − |índice_a − índice_b|))."""
    t = r["tarifa_por_tramo"]
    idx, k, urbana = {}, 0, True
    for sid in stops:
        if not urbana:
            k += 1
        idx[sid] = k
        if sid == t["ultima_parada_urbana"]:
            urbana = False
    return {"fare_idx": idx, "fare_n": k, "fare_max": t["maxima"], "fare_step": t["baja_por_parada"],
            "fare_min": t["minima"]}


def tarifa(r, stops):
    if r.get("tarifa_por_tramo"):
        return r["tarifa_por_tramo"]["maxima"]
    if r["tipo"] == "foranea":
        return r["fare"]
    return TARIFA_ZOCALO if "zocalo" in stops else TARIFA_URBANA


ROUTES = [
    {"id": "ZOC", "name": "Ruta Zocalera · Seguro IMSS – Zócalo", "short": "Z", "chip": "Zocalera", "color": "#1267ff",
     "tipo": "urbana", "confirmada": True, "kml": "rutas/ruta_zocalera.kml", "circuito": True,
     "units": 10},
    {"id": "PCB", "name": "Ruta Plazuela – CBTIS", "short": "C", "chip": "Plazuela – CBTIS", "color": "#c026d3",
     "tipo": "urbana", "confirmada": True, "kml": "rutas/ruta_plazuela_cbtis.kml", "circuito": True,
     "units": 6},
    {"id": "APM", "name": "Ruta Arcos – Pedro Martín", "short": "A", "chip": "Arcos – P. Martín", "color": "#16a34a",
     "tipo": "urbana", "confirmada": True, "kml": "rutas/ruta_arcos_pm.kml", "ida_y_vuelta": True,
     "units": 8},
    {"id": "CBG", "name": "Ruta CBTIS – Garita", "short": "G", "chip": "CBTIS – Garita", "color": "#dc2626",
     "tipo": "urbana", "confirmada": True, "kml": "rutas/ruta_cbtis_garita.kml", "ida_y_vuelta": True,
     "units": 6},
    {"id": "TAC", "name": "Ruta Taxco – Tehuilotepec – Acamixtla", "short": "T", "chip": "Tehui – Acamixtla", "color": "#0d9488",
     "tipo": "foranea", "confirmada": True, "kml": "rutas/ruta_tehui_acamixtla.kml", "ida_y_vuelta": True, "units": 5,
     # De terminal a terminal $25; cada parada foránea que se deja de recorrer baja $2; dentro de Taxco $11.50.
     # Confirmado (nov 2026), también para viajes entre dos paradas intermedias.
     "tarifa_por_tramo": {"maxima": 25.00, "baja_por_parada": 2.00, "minima": TARIFA_URBANA,
                          "ultima_parada_urbana": "gasolinera-arcos"}},
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
    """Lee el KML por capas (Folder): cada capa con línea es un tramo (p. ej. IDA y VUELTA) con sus
    puntos. Devuelve (trazo [[lat, lon], ...] con los tramos unidos en orden,
    puntos [(nombre, lat, lon, i_ini, i_fin)]) donde i_ini..i_fin es el pedazo del trazo de su tramo."""
    k = f"{{{KML_NS['k']}}}"
    root = ET.parse(path).getroot()
    folders = root.findall(f".//{k}Folder") or [root.find(f"{k}Document")]
    line, points = [], []
    for folder in folders:
        coords_el = folder.findall(f".//{k}LineString/{k}coordinates")
        if not coords_el:
            continue                       # capas vacías ("Capa sin título")
        i_ini = max(0, len(line) - 1)
        for el in coords_el:
            seg = []
            for tok in el.text.split():
                lon, lat = map(float, tok.split(",")[:2])
                seg.append([round(lat, 6), round(lon, 6)])
            if line:
                gap = haversine(line[-1], seg[0])
                if gap > 30:
                    raise SystemExit(f"{path.name}: «{folder.findtext(k + 'name')}» empieza a {gap:.0f} m de donde acaba el tramo anterior")
            for p in seg:
                if not line or p != line[-1]:
                    line.append(p)
        i_fin = len(line) - 1
        for pm in folder.iter(f"{k}Placemark"):
            c = pm.find(f".//{k}Point/{k}coordinates")
            if c is not None:
                lon, lat = map(float, c.text.strip().split(",")[:2])
                points.append((pm.findtext(f"{k}name", "").strip(), round(lat, 6), round(lon, 6), i_ini, i_fin))
    return line, points


def project(path, cum, pt, i_ini=0, i_fin=None):
    """Distancia a lo largo del trazo (m) del punto más cercano a pt (buscando sólo entre los
    vértices i_ini..i_fin), y qué tan lejos queda."""
    best = (float("inf"), 0.0)
    kx = math.cos(math.radians(pt[0]))
    i_fin = len(path) - 1 if i_fin is None else i_fin
    for i in range(i_ini, i_fin):
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
    ida_vuelta = bool(r.get("ida_y_vuelta"))
    if not r.get("circuito") and not ida_vuelta:
        raise SystemExit(f"{r['id']}: indica si la ruta es \"circuito\" o \"ida_y_vuelta\"")
    path, points = read_kml(ROOT / r["kml"])
    # Cerrar el circuito: si la vuelta acaba un poco antes de donde arranca la ida (Google Maps
    # ubica la misma dirección en dos puntos), se une en línea recta y la terminal pasa a ser
    # donde acaba la vuelta.
    cierre = 0 if ida_vuelta else haversine(path[-1], path[0])
    if cierre > 30:
        if cierre > 150:
            raise SystemExit(f"{r['id']}: la vuelta acaba a {cierre:.0f} m del inicio de la ida; no cierra el circuito")
        path = [path[-1]] + path
        points = [(n, la, lo, a + 1, b + 1) for n, la, lo, a, b in points]
    cum = [0.0]
    for i in range(1, len(path)):
        cum.append(cum[-1] + haversine(path[i - 1], path[i]))
    L = cum[-1]

    def circ(a, b):
        if ida_vuelta:                    # en ida y vuelta el inicio y el final son terminales distintas
            return abs(a - b)
        d = abs(a - b) % L
        return min(d, L - d)

    placed = []
    # primero el punto de la terminal, para que gane sobre otra copia suya unos metros adelante
    points.sort(key=lambda p: haversine(path[0], (p[1], p[2])) >= 30)
    for name, lat, lon, i_ini, i_fin in points:
        key = name.split(",")[0].strip()
        sid, label = NOMBRES_KML.get(key, (slug(key), key))
        candidatos = [(lat, lon)]
        if sid in STOPS and (STOPS[sid][1], STOPS[sid][2]) != (lat, lon):
            candidatos.insert(0, (STOPS[sid][1], STOPS[sid][2]))   # parada compartida: mismo punto en todas
        STOPS.setdefault(sid, (label, lat, lon))
        pos = off = None
        for clat, clon in candidatos:       # ¿alguno de sus puntos es una terminal de este trazo?
            if haversine(path[0], (clat, clon)) < 30:
                pos, off = 0.0, haversine(path[0], (clat, clon))   # terminal: inicio del trazo
                break
            if ida_vuelta and haversine(path[-1], (clat, clon)) < 30:
                pos, off = L, haversine(path[-1], (clat, clon))    # terminal del otro extremo
                break
        if pos is None:
            for clat, clon in candidatos:
                pos, off = project(path, cum, (clat, clon), i_ini, i_fin)   # sólo sobre su tramo (ida o vuelta)
                if off > MAX_DIST_PARADA_M:
                    pos, off = project(path, cum, (clat, clon))
                if off <= MAX_DIST_PARADA_M:
                    break
        if off > MAX_DIST_PARADA_M:
            raise SystemExit(f"{r['id']}: la parada «{label}» queda a {off:.0f} m del trazo")
        # la misma parada puede servir ida y vuelta (dos pasadas), pero un punto repetido
        # en el mismo lugar (terminal, unión de tramos) cuenta una sola vez
        if any(s == sid and circ(p, pos) < 150 for p, s in placed):
            continue
        placed.append((pos, sid))
    placed.sort()
    if placed[0][0] != 0.0:
        raise SystemExit(f"{r['id']}: ninguna parada coincide con el inicio del trazo (terminal)")
    stops = [s for _, s in placed]
    if ida_vuelta:
        if placed[-1][0] != L:
            raise SystemExit(f"{r['id']}: ninguna parada coincide con el final de la ida (terminal)")
        ida_m = [p for p, _ in placed]
        seq = stops + stops[-2::-1]                       # ida y regreso por las mismas paradas
        stop_m = [round(p, 1) for p in ida_m] + [round(2 * L - p, 1) for p in ida_m[-2::-1]]
        n = len(stops) - 1
        toward = [STOPS[stops[-1]][0] if k < n else STOPS[stops[0]][0] for k in range(len(seq) - 1)]
        path, L = path + path[-2::-1], 2 * L
    else:
        seq = stops + [stops[0]]
        stop_m = [round(p, 1) for p, _ in placed] + [round(L, 1)]
        toward = [STOPS[seq[k + 1]][0] for k in range(len(seq) - 1)]
    extra = tarifa_por_tramo(r, stops) if r.get("tarifa_por_tramo") else {}
    return {**r, **extra, "stops": stops, "fare": tarifa(r, stops), "sequence": seq, "stop_m": stop_m, "toward": toward,
            "length_m": round(L, 1),
            "osrm_s": round(L * 0.6 / (VEL_FORANEA_MS if r["tipo"] == "foranea" else VEL_COMBI_MS)), "path": path}


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
        kind = ("circuito (KML)" if r.get("circuito") else "ida y vuelta (KML)") if r.get("kml") else "ida+vuelta (OSRM)"
        print(f"{r['id']}: {o['length_m']/1000:.1f} km {kind}, {len(o['path'])} puntos, "
              f"{len(o['stops'])} paradas, tarifa " + (f"${o['fare']:.2f}" if o['fare'] is not None else "por confirmar"))
        for sid, m in zip(o["sequence"], o["stop_m"]):
            print(f"   {m:7.0f} m  {STOPS[sid][0]}")
    used = {s for o in out_routes for s in o["sequence"]}
    data = {"generated": time.strftime("%Y-%m-%d"),
            "stops": {k: {"name": v[0], "lat": v[1], "lon": v[2]} for k, v in STOPS.items() if k in used},
            "routes": out_routes}
    dst = ROOT / "data" / "routes.json"   # generado: no editar a mano
    dst.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    old = ROOT / "data" / "routes.js"
    if old.exists():
        old.unlink()                       # formato anterior
    print("OK ->", dst)
    stamp_index()


def stamp_index():
    """Agrega ?v=<huella> a los archivos que carga index.html; cambia sólo si cambia el archivo."""
    idx = ROOT / "index.html"
    html = idx.read_text(encoding="utf-8")
    for f in ("styles.css", "app.js"):
        v = hashlib.sha1((ROOT / f).read_bytes()).hexdigest()[:8]
        html = re.sub(rf'"{re.escape(f)}(\?v=\w+)?"', f'"{f}?v={v}"', html)
    idx.write_text(html, encoding="utf-8")


if __name__ == "__main__":
    main()
