# GEMINI.md — `01_dogrulanmis_eklentiler/AkilliBolgelemeAraci/` (Google Gemini Directives)

> **Plugin Scope**: `c:\Users\lilba\OneDrive\Masaüstü\qgis_plugin\01_dogrulanmis_eklentiler\AkilliBolgelemeAraci\`

---

## 1. Gemini Engineering Directives for `AkilliBolgelemeAraci` v1.1.0

1. **Preserve Core Clustering & E/S/AC Invariants**:
   - Do not weaken the spatial contiguity bridge or the E/S/AC vulnerability formula in `core_engine.py`.
   - Ensure output memory layers and GeoPackages preserve `E_Skor`, `S_Skor`, `AC_Skor`, `Kirilgan`, `Bolge_ID`, and `Strat_Kat` attributes in `EPSG:5253`.
2. **100% English UI & Report Output**:
   - All dialog tabs, group boxes, progress bars, message boxes, and generated HTML jury reports in `akilli_bolgeleme.py` must remain in 100% English.
3. **Qt5 & Qt6 Compatibility**:
   - Only import Qt classes from `qgis.PyQt.QtCore`, `qgis.PyQt.QtWidgets`, `qgis.PyQt.QtGui`.
   - Always test dialog instantiation in headless mode (`QT_QPA_PLATFORM=offscreen`) via `test_smoke.py`.

---

## 2. Immutable Academic & Ethical Rules ("Değişmez Akademik ve Etik Kurallar")

1. **Sıfır Halüsinasyon (Zero Hallucination)**: Yapay zekâya uydurma veri, hayali istatistik veya sentetik katman ürettirilemez.
2. **Gerçek DOI Zorunluluğu (Real DOI Requirement)**: Ward (1963) `10.1080/01621459.1963.10500845`, Anselin (1995) `10.1111/j.1538-4632.1995.tb00338.x`, Duque et al. (2012) `10.1111/j.1467-9787.2011.00743.x`.
3. **Öksüz Analiz Yok (No Orphan Analysis)**: Unassigned numeric columns must be documented with an explicit exclusion rationale in the HTML report.
4. **Koordinat Sistemi (CRS Standard)**: Enforce **EPSG:5253** (TUREF / TM30).
5. **Bireysel Sorumluluk (Individual Responsibility)**: All weights and cluster counts are explicitly chosen by the researcher.

---

## 3. Execution Command

```powershell
& "C:\Program Files\QGIS 3.44.14\bin\python-qgis-ltr.bat" 01_dogrulanmis_eklentiler/AkilliBolgelemeAraci/test_smoke.py
```
