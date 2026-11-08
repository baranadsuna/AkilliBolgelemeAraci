# AGENTS.md — `01_dogrulanmis_eklentiler/AkilliBolgelemeAraci/` (Smart Urban Zoning Tool v1.1.0)

> **Plugin Scope**: `c:\Users\lilba\OneDrive\Masaüstü\qgis_plugin\01_dogrulanmis_eklentiler\AkilliBolgelemeAraci\`
> **Version**: `v1.1.0` (Verified Production Plugin — QGIS 3.22 to 4.99, Qt5 & Qt6 Compatible, 100% English UI)

---

## 1. Domain Architecture & Mathematical Invariants

`AkilliBolgelemeAraci` (**Smart Urban Zoning & Vulnerability Synthesis Tool**) implements the **MPYY (Mekânsal Planlar Yapım Yönetmeliği / Spatial Plans Construction Regulation)** methodology for spatially constrained urban zoning and 3D vulnerability assessment:

1. **3D Vulnerability Framework ($E / S / AC$)**:
   - **Exposure ($E$ — Maruziyet)**: Population density, hazard exposure, or environmental load indicators.
   - **Sensitivity ($S$ — Hassasiyet)**: Structural vulnerability, building age/quality, or demographic sensitivity indicators.
   - **Adaptive Capacity ($AC$ — Uyum Kapasitesi)**: Green space access, healthcare/education proximity, or infrastructure resilience indicators.
   - **Vulnerability Synthesis Formula**:
     $$V_i = w_E \cdot \tilde{E}_i + w_S \cdot \tilde{S}_i - w_{AC} \cdot \tilde{AC}_i \quad \text{(normalized to } [0, 1]\text{)}$$
     where $\tilde{E}_i, \tilde{S}_i, \tilde{AC}_i \in [0, 1]$ are Robust/Min-Max scaled indicators and $w_E, w_S, w_{AC}$ are researcher-defined weights (Rule 5: Individual Responsibility).
2. **Spatially Constrained Ward Clustering**:
   - Builds topological contiguity ($W$) via `QgsSpatialIndex` bounding-box intersection + exact geometry touch/intersection checks.
   - Automatically connects isolated spatial islands using $k=1$ nearest centroid bridges so the connectivity graph forms a single connected component.
   - Applies Ward's minimum variance hierarchical clustering (`scipy.cluster.hierarchy` / `sklearn.cluster.AgglomerativeClustering(linkage='ward', connectivity=W)`) to partition polygons into $K$ contiguous homogeneous planning zones (`Bolge_ID`, `Strat_Kat`).
3. **Rule 1–5 Academic Invariants**:
   - **Rule 1 (Zero Hallucination)**: Rejects synthetic/hallucinated inputs; computes real descriptive statistics ($N$, min, max, mean, std, Moran's $I$ / ANOVA $F$-ratio).
   - **Rule 2 (Verified DOIs)**: Embeds verified academic citations:
     - Ward, J. H. (1963) — `10.1080/01621459.1963.10500845`
     - Anselin, L. (1995) LISA — `10.1111/j.1538-4632.1995.tb00338.x`
     - Duque, J. C., Anselin, L., & Rey, S. J. (2012) Max-p-regions — `10.1111/j.1467-9787.2011.00743.x`
   - **Rule 3 (No Orphan Analysis)**: Tracks every numeric field in the layer; any numeric attribute not assigned to $E$, $S$, or $AC$ requires a written exclusion justification logged in the final HTML synthesis report.
   - **Rule 4 (EPSG:5253 CRS Standard)**: Validates or reprojects input layers to `EPSG:5253` (TUREF / TM30) before computing centroids or contiguity distances.
   - **Rule 5 (Individual Responsibility)**: Researcher explicitly selects indicators, weights ($w_E, w_S, w_{AC}$), and number of zones ($K$).

---

## 2. File Structure & Responsibilities

- `__init__.py` — `classFactory(iface)` entry point.
- `akilli_bolgeleme.py` — Main plugin controller, English GUI dialog (`SmartZoningDialog`), action registration, and HTML report generator.
- `core_engine.py` — Pure PyQGIS + NumPy/SciPy spatial contiguity builder, Robust/Min-Max normalizer, E/S/AC vulnerability synthesizer, and spatially constrained Ward clustering engine.
- `metadata.txt` — QGIS Plugin Hub metadata (`version=1.1.0`, `supportsQt6=True`, `qgisMinimumVersion=3.22`, `qgisMaximumVersion=4.99`).
- `test_smoke.py` — Self-contained headless PyQGIS smoke and mathematical invariant test suite.

---

## 3. Workstation & Verification Commands

- **Developer**: Baran Adsuna (`https://github.com/baranadsuna`, Dokuz Eylül University, Urban & Regional Planning)
- **Hardware**: Windows 11 Pro (`10.0.26200`), Intel Core i7-13620H, RTX 4050 (`6141 MiB`), `16 GB` RAM.
- **Run Smoke Test**:
  ```powershell
  & "C:\Program Files\QGIS 3.44.14\bin\python-qgis-ltr.bat" 01_dogrulanmis_eklentiler/AkilliBolgelemeAraci/test_smoke.py
  ```
