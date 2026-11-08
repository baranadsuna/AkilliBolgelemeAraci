# CLAUDE.md — `01_dogrulanmis_eklentiler/AkilliBolgelemeAraci/` (Anthropic Claude Directives)

> **Plugin Scope**: `c:\Users\lilba\OneDrive\Masaüstü\qgis_plugin\01_dogrulanmis_eklentiler\AkilliBolgelemeAraci\`

---

## 1. Claude Code Rules for `AkilliBolgelemeAraci` v1.1.0

- **Core Algorithm**: MPYY Spatially Constrained Ward Clustering + 3D Vulnerability Synthesis ($E / S / AC$).
- **Key Invariants**:
  1. Every polygon in the input `EPSG:5253` vector layer receives normalized `E_Skor`, `S_Skor`, `AC_Skor`, composite `Kirilgan` ($\in [0, 1]$), contiguous `Bolge_ID` ($1 \dots K$), and action strategy `Strat_Kat`.
  2. Orphan numeric columns are detected and require researcher justification (Rule 3).
  3. All DOIs in the report are verified via `05_araclar_ve_rehberler/doi_dogrula.py` (Rule 2).
  4. All UI widgets and HTML reports default to 100% English and support both Qt5 (QGIS 3.44) and Qt6 (QGIS 4.x).

---

## 2. Hardware & Verification

- **Developer**: Baran Adsuna (`https://github.com/baranadsuna`, Dokuz Eylül University, Urban & Regional Planning)
- **Workstation**: Windows 11 Pro, i7-13620H, RTX 4050 (`6141 MiB`), `16 GB` RAM.
- **Test Command**:
  ```powershell
  & "C:\Program Files\QGIS 3.44.14\bin\python-qgis-ltr.bat" 01_dogrulanmis_eklentiler/AkilliBolgelemeAraci/test_smoke.py
  ```
