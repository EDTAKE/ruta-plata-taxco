"""Empaqueta la app para publicarla como página de claude.ai (dist/).

claude.ai sólo admite scripts de CDNs conocidos e impide teselas e imágenes externas,
así que: CSS de Leaflet en línea, mapa base vectorial (data/basemap.json) y datos en JSON.
Uso:  python tools/build_artifact.py
"""
import json, pathlib, re, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
LEAFLET_JS = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.js"
LEAFLET_CSS = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.css"


def main():
    (DIST / "data").mkdir(parents=True, exist_ok=True)
    css = urllib.request.urlopen(LEAFLET_CSS, timeout=30).read().decode("utf-8")
    css = re.sub(r"url\([^)]*\)", "none", css)  # imágenes de controles que no usamos
    css += "\n" + (ROOT / "styles.css").read_text(encoding="utf-8")
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    body = html[html.index("<body>") + 6: html.index('<script src="https://unpkg.com/leaflet')]
    icon = (ROOT / "icon.svg").read_text(encoding="utf-8").replace('viewBox="0 0 64 64"', 'viewBox="0 0 64 64" width="28" height="28" aria-hidden="true"')
    body = body.replace('<img src="icon.svg" alt="" width="28" height="28">', icon.strip())
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    page = (
        "<title>Ruta Plata Taxco</title>\n"
        '<meta name="description" content="Prototipo de app de transporte público con GPS para Taxco de Alarcón.">\n'
        f"<style>\n{css}\n</style>\n{body.strip()}\n"
        f'<script src="{LEAFLET_JS}"></script>\n'
        "<script>window.RP_VECTOR_BASEMAP = 'data/basemap.json';</script>\n"
        f"<script>\n{app}</script>\n"
    )
    (DIST / "ruta-plata.html").write_text(page, encoding="utf-8")
    (DIST / "data" / "routes.json").write_bytes((ROOT / "data" / "routes.json").read_bytes())
    (DIST / "data" / "basemap.json").write_bytes((ROOT / "data" / "basemap.json").read_bytes())
    for f in sorted(DIST.rglob("*.*")):
        print(f"{f.relative_to(ROOT)}  {f.stat().st_size/1024:.0f} KB")


if __name__ == "__main__":
    main()
