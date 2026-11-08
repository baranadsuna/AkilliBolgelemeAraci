# Academic Methodology & Operational Guide: `AkilliBolgelemeAraci` (v1.1.0)

* **Plugin Name:** Akıllı Bölgeleme Aracı (`AkilliBolgelemeAraci`)
* **Version:** `1.1.0` (QGIS 3.x & 4.x Compatible, `supportsQt6=True`, `qgisMaximumVersion=4.99`)
* **Standard Projected CRS:** `EPSG:5253` (TUREF / TM30)
* **Author:** Baran Adsuna (`https://github.com/baranadsuna`)

---

## 1. Overview & Urban Planning Problem Statement

Urban master planning (1/5000 Nazım İmar Planı and 1/1000 Uygulama İmar Planı) requires partitioning heterogeneous urban landscapes into internally cohesive, spatially contiguous sub-zones (*Alt Bölgeler*) with transparent, reproducible, and legally defensible boundary justifications.

`AkilliBolgelemeAraci` automates this synthesis through a 7-stage spatial pipeline implemented across [`algoritma.py`](../src/AkilliBolgelemeAraci/algoritma.py), [`analiz.py`](../src/AkilliBolgelemeAraci/analiz.py), and [`bolgeleme_dialog.py`](../src/AkilliBolgelemeAraci/bolgeleme_dialog.py), eliminating arbitrary manual boundary drawing and preventing "orphan analyses" (*Öksüz Analiz Yok* principle).

---

## 2. Mathematical Formulation

### 2.1 Topological Street-Block Cellularization & Sliver Absorption (`analiz.py :: build_cells_from_roads`)
Given a metric study boundary polygon $B$ (enforced as a projected CRS such as `EPSG:5253`) and road centerline geometries $\mathcal{R}$, the union of linear boundaries $\mathcal{U} = \partial B \cup (\bigcup_{r \in \mathcal{R}} (r \cap B))$ is polygonized into candidate urban faces $\{c_1, \dots, c_m\}$.

To prevent road medians, roundabouts, and topological slivers from acting as artificial sub-zones, each candidate face $c$ without a real building block is evaluated via Polsby-Popper compactness $PP(c)$ and morphological thickness $T(c)$:

$$PP(c) = \frac{4\pi A_c}{P_c^2}, \qquad T(c) = \frac{2 A_c}{P_c}$$

If $A_c < 450\text{ m}^2$, $PP(c) < 0.10$, $T(c) < 14.0\text{ m}$, or the inward buffer $\text{buffer}(c, -7.0\text{ m}) = \emptyset$, the sliver cell is merged via union-find into the neighboring cell sharing the longest common boundary edge.

### 2.2 Winsorized Z-Score Standardization (`algoritma.py :: zscore_columns`)
For each active variable $k$ across $n$ street-block cells, raw values $x_{i,k}$ are standardized and clipped to $[-3.0, +3.0]$ to bound the influence of extreme statistical outliers:

$$\mu_k = \frac{1}{n}\sum_{i=1}^{n} x_{i,k}, \qquad \sigma_k = \sqrt{\frac{1}{n}\sum_{i=1}^{n}(x_{i,k} - \mu_k)^2}$$

$$z_{i,k} = \max\!\left(-3.0,\; \min\!\left(3.0,\; \frac{x_{i,k} - \mu_k}{\sigma_k}\right)\right)$$

Variables are organized into four thematic groups $g \in \{\text{lu}, \text{yapi}, \text{dogal}, \text{geo}\}$ with user-configurable weights $W_g$. Each standardized column within group $g$ (containing $|G_g|$ active variables) receives effective weight:

$$w_k = \sqrt{\frac{W_g}{|G_g|}}, \qquad \tilde{z}_{i,k} = w_k \cdot z_{i,k}$$

### 2.3 Adjacency-Constrained Ward Minimum Variance Clustering (`algoritma.py :: ward_merge`)
Extending **Ward (1963)** ([DOI: `10.1080/01621459.1963.10500845`](https://doi.org/10.1080/01621459.1963.10500845)) to planar Dual Contiguity Graphs $G = (V, E_{\text{adj}})$, only clusters $A$ and $B$ sharing a physical boundary $> 1.0\text{ m}$ are eligible to merge. With initial cell mass $W_i = \sqrt{A_i}$ and area capacity threshold $C_{\text{area}} = \frac{\sum_{i=1}^n A_i}{K} \cdot m_{\text{cap}}$, the merge objective is:

$$\Delta \text{ESS}(A, B) = \frac{W_A W_B}{W_A + W_B}\left(\sum_{k=1}^{D} (\tilde{z}_{A,k} - \tilde{z}_{B,k})^2 + \varepsilon\right) \cdot \left(1 + \left(\frac{\text{Area}_A + \text{Area}_B}{C_{\text{area}}}\right)^{p}\right)$$

where $\varepsilon = 0.05$ and $p = 2.0$. At each step, the minimum-cost valid edge in a lazy-versioned binary min-heap (`heapq`) is popped until exactly $K$ contiguous sub-zones remain.

### 2.4 Optimal Bipartite Archetype Matching (`algoritma.py :: hungarian`)
Each clustered sub-zone $i \in \{1, \dots, K\}$ is matched to a planning archetype $j \in \{1, \dots, M\}$ ($A_1\text{–}A_{28}$ in Standard Mode; $M_1\text{–}M_{28}$ in Advanced Intervention Mode) by minimizing total weighted squared profile deviation plus cardinal orientation divergence via **Kuhn (1955)** ([DOI: `10.1002/nav.3800020109`](https://doi.org/10.1002/nav.3800020109)):

$$C_{i,j} = \frac{\sum_{f \in \mathcal{F}_j} \omega_f (m_{i,f} - t_{j,f})^2}{\sum_{f \in \mathcal{F}_j} \omega_f} + 0.35 \cdot \frac{1 - (\mathbf{d}_i \cdot \mathbf{d}_j)}{2}$$

### 2.5 3D Disaster Vulnerability Synthesis (`analiz.py :: compute_vulnerability`)
Following **Turner et al. (2003)** ([DOI: `10.1073/pnas.1231335100`](https://doi.org/10.1073/pnas.1231335100)), each sub-zone is evaluated along three dimensions scaled to $[1.0, 5.0]$:
1. **Exposure ($E$):** Weighted combination of residential population density ($\text{persons/ha}$) and building count:
   $$E = 0.6\,e_{\text{dens}} + 0.4\,e_{\text{bldg}}$$
2. **Sensitivity ($S_{\text{seismic}}, S_{\text{flood}}$):** Weighted function of poor building condition share (`kotu_pay`), floor height (`kat`), attached building order (`bitisik`), and ground coverage (`taks`):
   $$S_{\text{seismic}} = 0.35\,s_{\text{kotu}} + 0.25\,s_{\text{kat}} + 0.20\,s_{\text{bit}} + 0.20\,s_{\text{taks}}$$
   $$S_{\text{flood}} = 0.40\,s_{\text{taks}} + 0.30\,s_{\text{kotu}} + 0.30\,s_{\text{bit}}$$
3. **Adaptive Capacity ($AC_{\text{seismic}}, AC_{\text{flood}}$):** Incorporates distance to active fault lines (`fay`), distance to stream beds (`dere`), mean road width (`yg`), permeable surface ratio ($1 - \text{TAKS}$), DEM elevation (`rakim`), and social infrastructure accessibility modeled on 2SFCA (**Luo & Wang, 2003**, [DOI: `10.1068/b29120`](https://doi.org/10.1068/b29120)) and street-network integration (**Hillier et al., 1976**, [DOI: `10.1068/b030147`](https://doi.org/10.1068/b030147)):
   $$V_{\text{seismic}} = \frac{E \times S_{\text{seismic}}}{\max(1.0,\, AC_{\text{seismic}})}, \qquad V_{\text{flood}} = \frac{E \times S_{\text{flood}}}{\max(1.0,\, AC_{\text{flood}})}, \qquad V_{\text{general}} = 0.6\,V_{\text{seismic}} + 0.4\,V_{\text{flood}}$$

---

## 3. The Five Methodological Invariants

1. **Invariant 1 — Zero Population in Industrial & Agricultural Zones (`cell_residential_weight`, `apply_population_settings`):**
   Industrial/storage zones (`lu_sanayi >= 0.45`, e.g., OSB `A28`) and agricultural/open areas (`lu_tarim >= 0.70` or $\text{TAKS} < 5\%$) are assigned a strict population weight of $0.0$. Population is distributed exclusively across residential (`lu_konut`) and mixed residential-commercial (`lu_konut + 0.35 * lu_ticaret`) cells.
2. **Invariant 2 — TAKS < 5% Open Space Rule (`zone_stats`):**
   Sub-zones with $\text{TAKS} < 5\%$ or agricultural share $> 70\%$ are never labeled `"Bitişik Nizam"`. They are assigned `"Yapısız / Açık Alan"` ($\text{TAKS} < 1.5\%$) or `"Seyrek Kırsal Doku"` with `bitisik = 0.0`.
3. **Invariant 3 — Footprint-Weighted Floor Average (`accumulate_polygons`, `zone_stats`):**
   Average story height is computed as $\bar{K}_z = \frac{\sum K_i A_{\text{bldg},i}}{\sum A_{\text{bldg},i}}$, preventing isolated structures in open or agricultural zones from skewing sub-zone floor averages.
4. **Invariant 4 — Explicit Tracking of `kotu_yapi`, `sit2`, and `sit3` (`get_extra_Sit_params`, `describe_concise`):**
   Dilapidated building share (`Kotu_Durumdaki_Yapi_Orani_Yuzde`), registered heritage share (`Tescilli_Alan_Orani_sit2_Yuzde`), and disaster risk/renewal share (`Afet_Risk_Donusum_sit3_Yuzde`) are explicitly tracked and written to both the vector attribute table and narrative summaries.
5. **Invariant 5 — Top-3 $|\Delta Z|$ Boundary Justification (`build_contrast_explanation`):**
   For every sub-zone $A$ and its contiguous neighbors $B \in \mathcal{N}(A)$, the algorithm ranks all non-coordinate standardized variables by $|\bar{Z}_{A,k} - \bar{Z}_{B,k}|$ and reports the top 3 physical drivers of boundary separation in `Komsu_Bolgelerden_Ayrim_Nedeni`.

---

## 4. Real PyQGIS GUI Workflow

| Stage | Screenshot Asset | Operational Description |
| :--- | :--- | :--- |
| **Stage 1: Main Dialog & Parameter Binding** | ![Stage 1 Main Dialog](assets/gui_step1_main_dialog.png) | Select study boundary, road network, building blocks, optional individual buildings, DEM/slope raster, and natural/institutional threshold layers (`dere`, `fay`, `sit`, `risk`, `donati`). Configure population distribution mode and thematic group weights. |
| **Stage 2: Advanced Mode (M1–M28) & Synthesis Output** | ![Stage 2 Advanced Mode](assets/gui_step2_advanced_mode.png) | Switch to Advanced Mode (`M1–M28` Intervention Atlas), execute the 7-stage pipeline, inspect Top-3 $|\Delta Z|$ boundary justifications and 3D vulnerability classes, and export the CSV Analysis Tracking Matrix. |

---

## 5. Verified Academic References (Crossref Validated)

1. **Ward, J. H. (1963).** *Hierarchical Grouping to Optimize an Objective Function*. Journal of the American Statistical Association, 58(301), 236–244. **DOI:** [`10.1080/01621459.1963.10500845`](https://doi.org/10.1080/01621459.1963.10500845)
2. **Kuhn, H. W. (1955).** *The Hungarian method for the assignment problem*. Naval Research Logistics Quarterly, 2(1–2), 83–97. **DOI:** [`10.1002/nav.3800020109`](https://doi.org/10.1002/nav.3800020109)
3. **Turner, B. L., Kasperson, R. E., Matson, P. A., McCarthy, J. J., Corell, R. W., Christensen, L., ... & Schiller, A. (2003).** *A framework for vulnerability analysis in sustainability science*. Proceedings of the National Academy of Sciences (PNAS), 100(14), 8074–8079. **DOI:** [`10.1073/pnas.1231335100`](https://doi.org/10.1073/pnas.1231335100)
4. **Luo, W., & Wang, F. (2003).** *Measures of Spatial Accessibility to Health Care in a GIS Environment: Synthesis and a Case Study in the Chicago Region*. Environment and Planning B: Planning and Design, 30(6), 865–884. **DOI:** [`10.1068/b29120`](https://doi.org/10.1068/b29120)
5. **Hillier, B., Leaman, A., Stansall, P., & Bedford, M. (1976).** *Space syntax*. Environment and Planning B: Planning and Design, 3(2), 147–185. **DOI:** [`10.1068/b030147`](https://doi.org/10.1068/b030147)
