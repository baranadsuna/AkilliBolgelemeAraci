# Third-Party Conceptual Attributions & Notices

This plugin (**Akıllı Bölgeleme ve Kırılganlık Analiz Aracı / Smart Zoning & Vulnerability Analyzer**, `v1.9.1`) is authored and maintained cleanly by **Baran Adsuna** (Dokuz Eylül University, Department of Urban and Regional Planning) under the **GNU General Public License v3.0 (GPL-3.0)**.

---

## Clean-Room Conceptual Attribution

1. **PlanX Urban Analysis Suite (`YusufEminoglu/PlanX`, GPL-3.0, Dr. Yusuf Eminoğlu)**
   - **Nature of Attribution**: High-level domain methodology synthesis ONLY (clean-room engineering; zero code lines duplicated or copied).
   - **Concepts Synthesized Independently in PyQGIS**:
     - Multi-variable **Spacematrix** morphometric classification (`FSI = TAKS × L`, `GSI`, and `OSR = (1 - TAKS) / FSI`, originally grounded in Berghauser Pont & Haupt, 2010).
     - Seismic **Street Canyon Debris Blockage Ratio** (`H/W = (3.0 m × average floors) / road width`, marking `H/W ≥ 1.5` bottlenecks in Adaptive Capacity).
     - Topological **Cul-de-sac / Dead-end Street Endpoint Ratio** on spatial street centerlines for earthquake evacuation assessment.
     - **MPYY Active Facility per Capita (`m² / resident`)** and normalized **Shannon Land-Use Mix Entropy** evaluation.
     - Plain-language **"How to Read the Results" (`Sonuçları Nasıl Okumalı?`)** self-explanatory field breakdown structure.

2. **Scientific & Planning Foundations**
   - **IPCC AR5 / AR6 Disaster Vulnerability Framework**: Decomposition into Exposure ($E$), Sensitivity ($S$), and Adaptive Capacity ($AC$), where $V = f(E, S, AC)$.
   - **Ward (1963) Spatially-Constrained Hierarchical Agglomerative Clustering**: Minimum variance $\Delta\text{ESS}$ merging on planar block adjacency graphs.
   - **Berghauser Pont & Haupt (2010)**: Spacematrix urban form and density typology (`GSI`, `FSI`, `OSR`, `L`).
   - **Kuhn-Munkres (Hungarian) Assignment**: Optimal matching against Turkish urban planning intervention & MPYY standard profiles.
