"""Descarga calles de OpenStreetMap (Overpass) y genera data/basemap.json: un mapa base
vectorial ligero para la versión publicada (donde no se pueden cargar teselas externas).
Datos © colaboradores de OpenStreetMap, licencia ODbL.

Uso:  python tools/build_basemap.py
"""
import json, urllib.request, urllib.parse, pathlib

TOWN = (18.538, -99.622, 18.578, -99.568)        # mancha urbana: todas las calles
CORRIDOR = (18.468, -99.625, 18.578, -99.560)    # hasta Taxco el Viejo: sólo vías principales
CLASS = {  # highway -> clase de dibujo
    "motorway": "major", "trunk": "major", "primary": "major", "secondary": "major",
    "motorway_link": "major", "trunk_link": "major", "primary_link": "major", "secondary_link": "major",
    "tertiary": "mid", "tertiary_link": "mid", "unclassified": "mid",
    "residential": "minor", "living_street": "minor", "service": "minor", "road": "minor",
    "pedestrian": "foot", "footway": "foot", "steps": "foot", "path": "foot", "track": "foot",
}

q = f"""[out:json][timeout:90];
(
  way["highway"~"^(residential|living_street|service|road|pedestrian|footway|steps|path|tertiary|tertiary_link|unclassified|track)$"]{TOWN};
  way["highway"~"^(motorway|trunk|primary|secondary)(_link)?$"]{CORRIDOR};
  way["natural"="water"]{TOWN};
  way["leisure"="park"]{TOWN};
);
out tags geom;"""


def rnd(g):  # 5 decimales ≈ 1 m
    return [[round(p["lat"], 5), round(p["lon"], 5)] for p in g]


def simplify(pts, tol=0.00003):
    """Douglas-Peucker sencillo en grados (~3 m)."""
    if len(pts) < 3:
        return pts
    (ax, ay), (bx, by) = pts[0], pts[-1]
    dmax, idx = 0, 0
    for i in range(1, len(pts) - 1):
        px, py = pts[i]
        num = abs((by - ay) * px - (bx - ax) * py + bx * ay - by * ax)
        den = ((by - ay) ** 2 + (bx - ax) ** 2) ** 0.5 or 1e-12
        if num / den > dmax:
            dmax, idx = num / den, i
    if dmax > tol:
        return simplify(pts[: idx + 1], tol)[:-1] + simplify(pts[idx:], tol)
    return [pts[0], pts[-1]]


def main():
    req = urllib.request.Request("https://overpass-api.de/api/interpreter",
                                 data=urllib.parse.urlencode({"data": q}).encode(),
                                 headers={"User-Agent": "transit-prototype/0.1"})
    els = json.load(urllib.request.urlopen(req, timeout=120))["elements"]
    out = {"major": [], "mid": [], "minor": [], "foot": [], "park": [], "names": []}
    seen_names = set()
    for e in els:
        t, g = e.get("tags", {}), e.get("geometry")
        if not g:
            continue
        pts = simplify(rnd(g))
        if t.get("leisure") == "park" or t.get("natural") == "water":
            out["park"].append(pts); continue
        cls = CLASS.get(t.get("highway"))
        if not cls:
            continue
        out[cls].append(pts)
        name = t.get("name")
        if name and cls in ("major", "mid") and name not in seen_names and len(pts) >= 2:
            seen_names.add(name)
            mid = pts[len(pts) // 2]
            out["names"].append([name, mid[0], mid[1], cls])
    dst = pathlib.Path(__file__).resolve().parent.parent / "data" / "basemap.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print({k: len(v) for k, v in out.items()}, f"{dst.stat().st_size/1024:.0f} KB")


if __name__ == "__main__":
    main()
