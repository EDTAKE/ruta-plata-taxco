# Ruta Plata · Prototipo de transporte público con GPS para Taxco de Alarcón

Prototipo web (mobile‑first, instalable como PWA) que muestra en un mapa las combis/urvans de Taxco
moviéndose en tiempo real, cuánto tarda la próxima en llegar a tu parada y qué ruta tomar para ir a
un destino. Las unidades están **simuladas** en el navegador; el trazo de las rutas sí sigue calles
reales de OpenStreetMap.

**Demo en línea (con GPS):** <https://edtake.github.io/ruta-plata-taxco/> — se publica solo con cada
`git push` a `main` (GitHub Pages). Ábrelo en el celular y acepta el permiso de ubicación.

## Cómo correrlo

```powershell
python -m http.server 8765 --directory "D:\Beecker\Pruebas varias\taxco-gps-transporte"
```

Abre <http://localhost:8765>. Para probarlo en el celular dentro de la misma red usa la IP de la PC
(el GPS del navegador sólo funciona en `localhost` o con HTTPS; para el teléfono publícalo en HTTPS,
p. ej. GitHub Pages o Netlify).

## Qué incluye

| Pantalla | Qué hace |
|---|---|
| **Cerca de mí** | Las 4 paradas más cercanas, minutos caminando y próximas llegadas por ruta y sentido. |
| **¿A dónde vas?** | Planificador: dónde subir, qué unidad pasa y en cuánto, paradas, tarifa y tiempo total. Avisa si caminando llegas antes. |
| **Rutas** | Las 5 rutas con tarifa, frecuencia, unidades, km y lista de paradas; mostrar/ocultar en el mapa. |
| **Conductor** | Cómo sería la app del chofer: comparte GPS cada 5 s, controla ocupación, reporta incidentes y muestra el paquete JSON que se enviaría al servidor. |
| **Seguir unidad** | Tarjeta flotante con ETA en vivo y alerta (toast + vibración) cuando falta < 2 min. |

Extras: botón **x1 / x5 / x20** para acelerar la simulación en demos, modo oscuro automático, punto azul
arrastrable. El GPS real se usa a cualquier distancia; fuera de Taxco aparece un aviso con
"Volver a Taxco" para regresar a la ubicación de prueba.

## Archivos

- `index.html`, `styles.css`, `app.js` — la app (Leaflet 1.9.4 + teselas de OpenStreetMap, sin build).
- `data/routes.js` — paradas y trazos generados; **no editar a mano**.
- `tools/build_routes.py` — define paradas/rutas y obtiene el trazo por calles con OSRM. Edita las
  listas `STOPS` y `ROUTES` y vuelve a correr `python tools/build_routes.py`.
- `manifest.json`, `icon.svg` — para "Agregar a pantalla de inicio".

> ⚠️ Rutas, paradas, tarifas ($12 urbana, $14 Tehuilotepec, $22 Taxco el Viejo) y frecuencias son
> **ilustrativas**. Antes de piloto hay que levantarlas con los concesionarios / Dirección de
> Transporte del municipio (idealmente en formato GTFS).

## Camino a una versión real

```
 App conductor (Android)  ──GPS cada 5 s──▶  API / broker (MQTT o WebSocket)
   · ubicación en 2º plano                     · valida unidad y ruta
   · ocupación, incidentes                     · guarda en Redis (posición viva)
                                               · histórico en PostGIS
                                                      │
 App pasajero (PWA / Android) ◀──WebSocket─────────────┘
   · mapa, ETA, planificador                  Motor de ETA: velocidades históricas por tramo
   · alertas push (FCM)                       Panel web de la central: flota, alertas, reportes
```

Pasos sugeridos:

1. **Datos**: levantar rutas reales (grabar el recorrido con el GPS de un chofer) y publicarlas en GTFS.
2. **App del conductor**: Android nativo (Kotlin) con servicio en primer plano para GPS continuo y
   bajo consumo de datos; modo sin conexión que reenvía al recuperar señal (frecuente en las barrancas de Taxco).
3. **Backend**: endpoint de posiciones (MQTT/WebSocket), Redis para el estado vivo, PostGIS para
   histórico; ETA con velocidades medias por tramo y hora del día.
4. **App pasajero**: esta PWA conectada al WebSocket en lugar de la simulación (`stepUnit` → mensajes del servidor).
5. **Mapas en producción**: las teselas públicas de OSM no son para alto tráfico; usar un proveedor
   (MapTiler, Stadia, Mapbox) o teselas propias.
6. **Pendientes**: transbordos en el planificador, taxis/"vochos" colectivos, accesibilidad, pago
   digital, horarios nocturnos y avisos de la central (cierres por festividades, p. ej. Jornadas Alarconianas o Semana Santa).
