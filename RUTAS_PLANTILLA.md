# Plantilla para describir rutas reales

Copia el bloque de ejemplo una vez por ruta y llénalo. No hace falta que esté perfecto:
con eso armo el trazo sobre las calles, las paradas y la tarifa.

## Tres formas de darme el recorrido (de más a menos precisa)

1. **Grabar el recorrido con GPS.** Súbete a la ruta (o síguela en coche) con una app que grabe
   la traza, por ejemplo *GPS Logger* (Android) u *OsmAnd*, y exporta el archivo **GPX** o **KML**.
   Una grabación para la ida y otra para la vuelta. Es lo más exacto, sobre todo en los
   callejones del centro.
2. **Dibujarlo en Google My Maps** (mymaps.google.com): una línea para la ida, otra para la vuelta
   y un punto por cada parada. Luego *Exportar a KML/KMZ* y me pasas el archivo.
3. **Por texto**, con la plantilla de abajo: calles y puntos de referencia en orden. Escribe la
   ida y la vuelta por separado, porque en Taxco muchas calles son de un solo sentido.

Con cualquiera de las tres, la lista de **paradas** sí la necesito (nombre y referencia).

## Tarifas ya confirmadas

| Tipo de ruta | Tarifa |
|---|---|
| Urbana que llega al Zócalo | $11.00 |
| Cualquier otra urbana | $11.50 |
| Foránea | pendiente (cada ruta la suya) |

## Ejemplo (los datos son inventados)

```
RUTA: 7 · Los Arcos – Zócalo
TIPO: urbana              (urbana / foránea)
LLEGA AL ZÓCALO: sí       (define la tarifa urbana: sí = $11.00, no = $11.50)
TARIFA: —                 (sólo para foráneas, p. ej. $22)
COLOR / LETRERO: rojo, letrero "Zócalo"   (opcional)

IDA (de Los Arcos al Zócalo), en orden:
  - Sale de Los Arcos (frente a la gasolinera)
  - Baja por Av. de los Plateros hasta La Garita
  - Entra por Calle Juárez
  - Termina en Plazuela de San Juan

VUELTA (del Zócalo a Los Arcos), en orden:
  - Sale de Plazuela de San Juan
  - Sube por Calle Hidalgo ...
  - Sale a Av. de los Plateros y sube hasta Los Arcos

PARADAS (en orden; marca si son sólo de ida o sólo de vuelta):
  - Los Arcos — frente a la gasolinera
  - La Garita — esquina con Calle La Garita
  - Calle Juárez — afuera del Palacio Municipal (sólo ida)
  - Plazuela de San Juan — terminal
  - ¿Para donde le hagan la parada? sí / no

OPERACIÓN (si lo sabes):
  - Unidades en servicio: 6
  - Pasa cada: 5–8 min
  - Horario: 6:00 – 21:30
```

## Qué hago yo con esos datos

- Paso el recorrido a coordenadas sobre las calles de OpenStreetMap (con la traza GPS o KML lo
  uso tal cual; con texto lo armo por puntos de referencia y te lo enseño en el mapa para que
  lo corrijas).
- Separo ida y vuelta cuando van por calles distintas.
- Actualizo `tools/build_routes.py`, regenero `data/routes.js` y publico de nuevo
  (GitHub Pages y la versión de claude.ai).
