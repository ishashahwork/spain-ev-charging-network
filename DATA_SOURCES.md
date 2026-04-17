# Data Sources — IE Iberdrola Datathon

All sources extracted from the official challenge PDF. Download and place raw files in `data/raw/`.

---

## Mandatory Sources

### 1. Road Routes — Ministry of Transport and Sustainable Mobility
- **Purpose:** Foundational interurban road network (autopistas, autovías, carreteras nacionales). Provides road geometry, classification, and traffic flow data.
- **Portal:** https://www.mitma.gob.es/carreteras/trafico-velocidades-y-accidentes/mapas-de-trafico
- **Search for:** "Red de carreteras del Estado" or "aforos de tráfico"
- **Format:** Shapefile / GeoJSON
- **Key use:** Road backbone for station placement, filtering out urban sections.

### 2. EV Charging Points — National Access Point for Traffic and Mobility
- **Purpose:** Existing charging station baseline. Must filter to interurban roads only.
- **Portal:** https://nap.dgt.es/dataset/puntos-de-recarga-para-vehiculos-electricos
- **Format:** CSV / JSON
- **Key use:** `total_existing_stations_baseline` in File 1; coverage gap analysis.

### 3. Route to Electrification — datos.gob.es GitHub (MANDATORY FORK)
- **Purpose:** Predicts EV fleet growth in Spain. **Exercise 3 output = `total_ev_projected_2027`.**
- **GitHub:** https://github.com/datos-gob-es/movilidad-electrica (search for the official repo linked from datos.gob.es)
- **Portal:** https://datos.gob.es/es/noticia/ruta-hacia-la-electrificacion-descifrando-el-crecimiento-de-los-vehiculos-electricos-en-espana-mediante-el-analisis-de-datos
- **Action required:** Fork the repository, run exercise 3, extract 2027 EV projection.
- **Key use:** Mandatory input for demand model and File 1 KPI.

---

## Additional Sources — Grid Capacity

### 4. i-DE (Iberdrola) — Consumption Capacity Map
- **Purpose:** Substation-level available capacity (MW) and coordinates for Iberdrola's distribution network.
- **Portal:** https://www.i-de.es/consumidores/web/guest/mapa-capacidad-consumo
- **Format:** Downloadable dataset (CSV or similar)
- **Coverage:** Central and northern Spain (Iberdrola distribution zones)
- **Key use:** `grid_status` classification + `distributor_network = i-DE` in File 3.

### 5. Endesa / e-distribución — Network Capacity Nodes
- **Purpose:** Node-level access capacity for Endesa's distribution areas.
- **Portal:** https://www.edistribucion.com/es/red-electrica/capacidad-acceso.html
- **Format:** CSV / XLSX (historical access capacity documents)
- **Coverage:** Southern Spain, Balearic Islands, Canary Islands, parts of Catalonia
- **Key use:** `grid_status` classification + `distributor_network = Endesa` in File 3.

### 6. Viesgo — Interactive Grid Map
- **Purpose:** Substation-level capacity data for northern Spain.
- **Portal:** https://www.viesgo.com/distribucion/mapa-interactivo/
- **Format:** Web map (may require manual export or scraping)
- **Coverage:** Cantabria, Asturias, Murcia
- **Key use:** `grid_status` classification + `distributor_network = Viesgo` in File 3.

---

## Supporting Sources

### 7. DGT — Vehicle Registrations in Spain
- **Purpose:** Historical monthly EV registrations by province. Use to weight charging demand forecasts geographically.
- **Portal:** https://www.dgt.es/inicio/estadisticas-e-indicadores/parque-de-vehiculos/
- **Format:** Excel / CSV
- **Key use:** Geographic weighting of EV adoption for demand model.

### 8. Local Open Data Portals — Municipal Charger Datasets
- **Purpose:** Granular local charger data to validate/enrich national figures.
- **Example (Vigo):** https://datos.gob.es/es/catalogo/l01360594-puntos-de-recarga-para-coches-electricos
- **Search:** https://datos.gob.es → "puntos de recarga vehículos eléctricos"
- **Key use:** Supplementary validation of charger coverage; may reveal unlisted regional chargers.

---

## Recommended Extra Sources (to differentiate your proposal)

| Source | URL hint | Use case |
|---|---|---|
| CNMC grid zones map | cnmc.es | Map distributor territories to route segments |
| REE (Red Eléctrica) demand data | ree.es | National grid load context |
| ADIF rail traffic | adif.es | Multimodal hubs near highways |
| INE population/mobility survey | ine.es | Origin-destination flow data |
| OpenStreetMap (via osmnx) | openstreetmap.org | Road network as backup / enrichment |
| EDGAR / EEA emissions data | eea.europa.eu | Transport emissions by region |
| EU AFIR regulation text | eur-lex.europa.eu | Regulatory spacing requirements for chargers |

---

## Download Checklist

- [ ] Ministry of Transport road network (shapefiles)
- [ ] National Access Point EV charging points (CSV)
- [ ] datos.gob.es GitHub repo — forked and exercise 3 run
- [ ] i-DE capacity dataset downloaded
- [ ] Endesa capacity CSV/XLSX downloaded
- [ ] Viesgo data exported
- [ ] DGT vehicle registrations (2020–2025 monthly)
- [ ] At least one local open data portal charger dataset
