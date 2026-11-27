# -*- coding: utf-8 -*-
"""Strategic Synthesis Cartography, Data-Driven SWOT, Multi-Layer Overlay & QGIS Print Layout.

Implements clean-room, strictly data-grounded (Zero Hallucination, EPSG:5253 metric CRS)
cartographic rendering, multi-layer strategic overlays, grouped LayerTree management,
deterministic SWOT/GZFT synthesis, and A3/A1 QGIS Print Layout export (`QgsPrintLayout`),
compatible across QGIS 3.22..4.99 and Qt5/Qt6 (`qgis.PyQt`).
"""
from __future__ import annotations

import colorsys
import datetime
import heapq
import math
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

if os.name == "nt":
    _WIN_FONTS = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    if _WIN_FONTS.is_dir():
        os.environ.setdefault("QT_QPA_FONTDIR", str(_WIN_FONTS))

from qgis.PyQt.QtCore import Qt, QVariant
from qgis.PyQt.QtGui import QColor, QFont, QFontDatabase

try:
    from qgis.PyQt.QtCore import QMetaType as _QMetaType
except ImportError:  # pragma: no cover
    _QMetaType = None

from qgis.core import (
    Qgis,
    QgsBalloonCallout,
    QgsCallout,
    QgsCategorizedSymbolRenderer,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCsException,
    QgsFeature,
    QgsField,
    QgsFillSymbol,
    QgsGeometry,
    QgsInvertedPolygonRenderer,
    QgsLayoutExporter,
    QgsLayoutFrame,
    QgsLayoutItemLabel,
    QgsLayoutItemLegend,
    QgsLayoutItemMap,
    QgsLayoutItemPage,
    QgsLayoutItemPicture,
    QgsLayoutItemScaleBar,
    QgsLayoutItemShape,
    QgsLayoutItemTextTable,
    QgsLayoutMeasurement,
    QgsLayoutPoint,
    QgsLayoutSize,
    QgsLayoutTable,
    QgsLayoutTableColumn,
    QgsLegendStyle,
    QgsLinePatternFillSymbolLayer,
    QgsLineSymbol,
    QgsManhattanLineCallout,
    QgsMapLayer,
    QgsMarkerSymbol,
    QgsPalLayerSettings,
    QgsPointPatternFillSymbolLayer,
    QgsPointXY,
    QgsPrintLayout,
    QgsProject,
    QgsReadWriteContext,
    QgsRectangle,
    QgsRendererCategory,
    QgsRuleBasedLabeling,
    QgsRuleBasedRenderer,
    QgsSimpleFillSymbolLayer,
    QgsSimpleLineSymbolLayer,
    QgsSimpleMarkerSymbolLayer,
    QgsSingleSymbolRenderer,
    QgsSpatialIndex,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsUnitTypes,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
    QgsWkbTypes,
)

# ---------------------------------------------------------------------------
# Qt5 / Qt6 & QGIS 3 / 4 Compatibility Shims
# ---------------------------------------------------------------------------
_LAYOUT_MM = getattr(
    getattr(QgsUnitTypes, "LayoutUnit", QgsUnitTypes),
    "Millimeters",
    getattr(QgsUnitTypes, "LayoutMillimeters", 0),
)
_DIST_METERS = getattr(
    getattr(QgsUnitTypes, "DistanceUnit", QgsUnitTypes),
    "Meters",
    getattr(QgsUnitTypes, "DistanceMeters", 0),
)
_ORIENT_LANDSCAPE = getattr(
    getattr(QgsLayoutItemPage, "Orientation", QgsLayoutItemPage),
    "Landscape",
    getattr(QgsLayoutItemPage, "Landscape", 1),
)
_ORIENT_PORTRAIT = getattr(
    getattr(QgsLayoutItemPage, "Orientation", QgsLayoutItemPage),
    "Portrait",
    getattr(QgsLayoutItemPage, "Portrait", 0),
)
_EXPORT_SUCCESS = getattr(
    getattr(QgsLayoutExporter, "ExportResult", QgsLayoutExporter),
    "Success",
    getattr(QgsLayoutExporter, "Success", 0),
)
_BRUSH_NO = getattr(getattr(Qt, "BrushStyle", Qt), "NoBrush", getattr(Qt, "NoBrush", 0))
_BRUSH_SOLID = getattr(getattr(Qt, "BrushStyle", Qt), "SolidPattern", getattr(Qt, "SolidPattern", 1))
_PEN_SOLID = getattr(getattr(Qt, "PenStyle", Qt), "SolidLine", getattr(Qt, "SolidLine", 1))
_PEN_DASH = getattr(getattr(Qt, "PenStyle", Qt), "DashLine", getattr(Qt, "DashLine", 2))
_PEN_DOT = getattr(getattr(Qt, "PenStyle", Qt), "DotLine", getattr(Qt, "DotLine", 3))
_PEN_NO = getattr(getattr(Qt, "PenStyle", Qt), "NoPen", getattr(Qt, "NoPen", 0))

_ALIGN_LEFT = getattr(getattr(Qt, "AlignmentFlag", Qt), "AlignLeft", getattr(Qt, "AlignLeft", 1))
_ALIGN_CENTER = getattr(getattr(Qt, "AlignmentFlag", Qt), "AlignHCenter", getattr(Qt, "AlignHCenter", 4))
_ALIGN_TOP = getattr(getattr(Qt, "AlignmentFlag", Qt), "AlignTop", getattr(Qt, "AlignTop", 32))
_ALIGN_VCENTER = getattr(getattr(Qt, "AlignmentFlag", Qt), "AlignVCenter", getattr(Qt, "AlignVCenter", 128))

_GEOM_POINT = getattr(getattr(QgsWkbTypes, "GeometryType", QgsWkbTypes), "PointGeometry", 0)
_GEOM_LINE = getattr(getattr(QgsWkbTypes, "GeometryType", QgsWkbTypes), "LineGeometry", 1)
_GEOM_POLY = getattr(getattr(QgsWkbTypes, "GeometryType", QgsWkbTypes), "PolygonGeometry", 2)

_PIC_FORMAT_SVG = getattr(
    getattr(QgsLayoutItemPicture, "Format", QgsLayoutItemPicture),
    "SVG",
    getattr(QgsLayoutItemPicture, "FormatSVG", 0),
)
_PIC_RESIZE_ZOOM = getattr(
    getattr(QgsLayoutItemPicture, "ResizeMode", QgsLayoutItemPicture),
    "Zoom",
    getattr(QgsLayoutItemPicture, "Zoom", 0),
)
_LABEL_MODE_HTML = getattr(
    getattr(QgsLayoutItemLabel, "Mode", QgsLayoutItemLabel),
    "ModeHtml",
    getattr(QgsLayoutItemLabel, "ModeHtml", 1),
)
_LABEL_MODE_FONT = getattr(
    getattr(QgsLayoutItemLabel, "Mode", QgsLayoutItemLabel),
    "ModeFont",
    getattr(QgsLayoutItemLabel, "ModeFont", 0),
)
_SHAPE_RECT = getattr(
    getattr(QgsLayoutItemShape, "Shape", QgsLayoutItemShape),
    "Rectangle",
    getattr(QgsLayoutItemShape, "Rectangle", 1),
)
_CALLOUT_ANCHOR_POS = getattr(
    getattr(QgsCallout, "AnchorPoint", QgsCallout),
    "PointOnSurface",
    getattr(QgsCallout, "PointOnSurface", 1),
)
_PLACE_AROUND = getattr(
    getattr(Qgis, "LabelPlacement", QgsPalLayerSettings),
    "AroundPoint",
    getattr(QgsPalLayerSettings, "AroundPoint", 0),
)
_MARKER_CROSS2 = getattr(getattr(Qgis, "MarkerShape", Qgis), "Cross2", None)
_MARKER_CIRCLE = getattr(getattr(Qgis, "MarkerShape", Qgis), "Circle", None)

_LEG_STYLE_TITLE = getattr(getattr(QgsLegendStyle, "Style", QgsLegendStyle), "Title", getattr(QgsLegendStyle, "Title", 2))
_LEG_STYLE_GROUP = getattr(getattr(QgsLegendStyle, "Style", QgsLegendStyle), "Group", getattr(QgsLegendStyle, "Group", 3))
_LEG_STYLE_SUBGROUP = getattr(getattr(QgsLegendStyle, "Style", QgsLegendStyle), "Subgroup", getattr(QgsLegendStyle, "Subgroup", 4))
_LEG_STYLE_LABEL = getattr(getattr(QgsLegendStyle, "Style", QgsLegendStyle), "SymbolLabel", getattr(QgsLegendStyle, "SymbolLabel", 6))
_LEG_STYLE_SYMBOL = getattr(getattr(QgsLegendStyle, "Style", QgsLegendStyle), "Symbol", getattr(QgsLegendStyle, "Symbol", 5))
_TBL_WRAP_TEXT = getattr(getattr(QgsLayoutTable, "WrapBehavior", QgsLayoutTable), "WrapText", getattr(QgsLayoutTable, "WrapText", 1))
_TBL_HEADER_FIRST = getattr(getattr(QgsLayoutTable, "HeaderMode", QgsLayoutTable), "FirstFrame", getattr(QgsLayoutTable, "FirstFrame", 0))
_TBL_RESIZE_EXIST = getattr(getattr(QgsLayoutTable, "ResizeMode", QgsLayoutTable), "UseExistingFrames", getattr(QgsLayoutTable, "UseExistingFrames", 0))
_LAYER_TYPE_RASTER = getattr(getattr(QgsMapLayer, "LayerType", QgsMapLayer), "RasterLayer", getattr(QgsMapLayer, "RasterLayer", 1))


def _ensure_offscreen_fonts() -> None:
    """Ensure headless Qt offscreen sessions have readable Windows system fonts loaded."""
    try:
        fdb = QFontDatabase()
        if not fdb.families() and os.name == "nt":
            font_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
            for fname in ("segoeui.ttf", "segoeuib.ttf", "arial.ttf", "arialbd.ttf", "tahoma.ttf"):
                fp = font_dir / fname
                if fp.exists():
                    QFontDatabase.addApplicationFont(str(fp))
    except Exception:
        pass


def _qfield(name: str, kind: str) -> QgsField:
    """Create a QgsField compatible across QGIS 3 (QVariant) and QGIS 4 (QMetaType)."""
    if _QMetaType is not None and hasattr(_QMetaType, "Type"):
        mt = _QMetaType.Type
        mt_map = {
            "int": getattr(mt, "Int", None),
            "double": getattr(mt, "Double", None),
            "string": getattr(mt, "QString", None),
        }
        val = mt_map.get(kind)
        if val is not None:
            try:
                return QgsField(name, val)
            except TypeError:
                pass
    qv_map = {
        "int": getattr(QVariant, "Int", 2),
        "double": getattr(QVariant, "Double", 6),
        "string": getattr(QVariant, "String", 10),
    }
    return QgsField(name, qv_map[kind])


# ---------------------------------------------------------------------------
# Public Locked Constants
# ---------------------------------------------------------------------------
SYNTHESIS_FOCUS_AXES: List[Tuple[str, str, str, str, str]] = [
    (
        "balanced",
        "Balanced Multi-Criteria (Default)",
        "Dengeli Çok Kriterli (Varsayılan)",
        "多准则均衡（默认）",
        "Multicriterio Equilibrado (Predeterminado)",
    ),
    (
        "resilience",
        "Disaster & Seismic Resilience",
        "Afet ve Deprem Direnci",
        "灾害与抗震韧性",
        "Resiliencia Sísmica y ante Desastres",
    ),
    (
        "ecology",
        "Ecological & Green-Blue Network",
        "Ekolojik Sistem ve Yeşil-Mavi Ağ",
        "生态与蓝绿网络",
        "Red Ecológica y Verde-Azul",
    ),
    (
        "facility",
        "Social Facility & Accessibility",
        "Sosyal Donatı ve Erişilebilirlik",
        "公共设施与可达性",
        "Equipamientos Sociales y Accesibilidad",
    ),
    (
        "tourism_culture",
        "Heritage, Tourism & Cultural Axis",
        "Kültürel Miras, Sit ve Turizm Ekseni",
        "文化遗产与文旅轴线",
        "Patrimonio Cultural, Sitios y Turismo",
    ),
    (
        "production",
        "Agriculture, Industry & Logistics",
        "Tarım, Sanayi ve Lojistik Üretim",
        "农业、产业与物流生产",
        "Agricultura, Industria y Logística",
    ),
]

SYNTHESIS_PALETTE: Dict[str, str] = {
    "tourism_focus": "#EA580C",
    "education": "#2563EB",
    "ecology": "#15803D",
    "agriculture": "#A3C962",
    "water": "#0284C7",
    "industry_energy": "#7C3AED",
    "transport": "#1E293B",
    "heritage": "#B45309",
    "commercial": "#0D9488",
    "residential": "#E07A5F",
    "strategy": "#0F172A",
    "vulnerability": "#DC2626",
}

_FOCUS_AXIS_CODES = {row[0] for row in SYNTHESIS_FOCUS_AXES}

_VULN_HIGH_TIERS = ("Yüksek", "Çok Yüksek")


def _focus_label(axis_code: str, lang: str = "en") -> str:
    idx_map = {"en": 1, "tr": 2, "zh": 3, "es": 4}
    idx = idx_map.get(lang, 1)
    for row in SYNTHESIS_FOCUS_AXES:
        if row[0] == axis_code:
            return row[idx]
    return SYNTHESIS_FOCUS_AXES[0][idx]


def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    s = (hex_color or "#64748B").strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    try:
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except ValueError:
        return 100, 116, 139


def _clip_words(text: Any, limit: int, suffix: str = "...") -> str:
    """Truncate text cleanly at word or comma boundaries without mid-word clipping."""
    s = str(text or "").strip()
    if len(s) <= limit:
        return s
    cut_lim = max(8, limit - len(suffix))
    head = s[:cut_lim]
    split_pos = max(head.rfind(", "), head.rfind(" "))
    if split_pos >= int(cut_lim * 0.50):
        head = head[:split_pos]
    head = head.rstrip(" ,;:-")
    return f"{head}{suffix}" if head else s[:cut_lim] + suffix


def _hex_rgba(hex_color: str, alpha: int = 115, tint_shift: float = 0.0) -> str:
    rr, gg, bb = _hex_to_rgb(hex_color)
    if abs(tint_shift) > 1e-4:
        h, s, v = colorsys.rgb_to_hsv(rr / 255.0, gg / 255.0, bb / 255.0)
        h = (h + tint_shift * 0.035) % 1.0
        v = min(0.96, max(0.35, v + tint_shift * 0.06))
        rr_f, gg_f, bb_f = colorsys.hsv_to_rgb(h, s, v)
        rr, gg, bb = int(round(rr_f * 255)), int(round(gg_f * 255)), int(round(bb_f * 255))
    return f"{rr},{gg},{bb},{max(0, min(255, int(alpha)))}"


def _qcolor(hex_color: str, alpha: int = 255) -> QColor:
    rr, gg, bb = _hex_to_rgb(hex_color)
    return QColor(rr, gg, bb, max(0, min(255, int(alpha))))


def _safe_point_on_surface(geom: Optional[QgsGeometry]) -> Optional[QgsPointXY]:
    if geom is None or geom.isEmpty():
        return None
    try:
        pt_g = geom.pointOnSurface()
        if pt_g and not pt_g.isEmpty():
            return pt_g.asPoint()
    except Exception:
        pass
    try:
        c = geom.centroid()
        if c and not c.isEmpty():
            return c.asPoint()
    except Exception:
        pass
    return None


def _read_layer_geoms(layer: Any, work_crs: QgsCoordinateReferenceSystem) -> List[Tuple[Any, QgsGeometry]]:
    """Read and reproject valid vector geometries into work_crs safely."""
    if layer is None or not isinstance(layer, QgsVectorLayer) or not layer.isValid():
        return []
    xf = None
    if work_crs and work_crs.isValid() and layer.crs() != work_crs:
        xf = QgsCoordinateTransform(layer.crs(), work_crs, QgsProject.instance())
    out: List[Tuple[Any, QgsGeometry]] = []
    for feat in layer.getFeatures():
        if not feat.hasGeometry():
            continue
        g = QgsGeometry(feat.geometry())
        if g.isEmpty():
            continue
        if xf is not None:
            try:
                if g.transform(xf) != 0:
                    continue
            except (QgsCsException, RuntimeError):
                continue
        if g.type() == _GEOM_POLY and not g.isGeosValid():
            g2 = g.makeValid()
            if g2 and not g2.isEmpty():
                g = g2
        out.append((feat, g))
    return out


def _is_built_zone(z: Dict[str, Any]) -> bool:
    """Strictly distinguish built urban fabric from unbuilt agricultural/open zones."""
    n_bldg = int(z.get("n") or 0)
    taks = float(z.get("taks") or 0.0)
    return n_bldg > 0 and taks >= 0.015


def _get_zone_vuln(z: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(z.get("vuln"), dict) and "genel_kirilganlik" in z["vuln"]:
        return z["vuln"]
    try:
        from . import analiz  # lazy import avoids circular dependency
        vuln = analiz.compute_vulnerability(z)
        z["vuln"] = vuln
        return vuln
    except Exception:
        return {}


def _zone_kotu_share(z: Dict[str, Any]) -> Optional[float]:
    if z.get("kotu_pay") is not None:
        return float(z["kotu_pay"])
    ext = z.get("ext") or {}
    if ext.get("kotu_yapi") is not None:
        return float(ext["kotu_yapi"])
    return None


# ---------------------------------------------------------------------------
# 1. Data-Driven SWOT / GZFT Synthesis
# ---------------------------------------------------------------------------
_VULN_TIER_I18N: Dict[str, Dict[str, str]] = {
    "Çok Düşük": {"en": "Very Low", "tr": "Çok Düşük", "zh": "极低", "es": "Muy Baja"},
    "Düşük": {"en": "Low", "tr": "Düşük", "zh": "低", "es": "Baja"},
    "Orta": {"en": "Moderate", "tr": "Orta", "zh": "中", "es": "Moderada"},
    "Yüksek": {"en": "High", "tr": "Yüksek", "zh": "高", "es": "Alta"},
    "Çok Yüksek": {"en": "Very High", "tr": "Çok Yüksek", "zh": "极高", "es": "Muy Alta"},
}


def _localize_vuln_tier(tier_val: str, lang: str) -> str:
    loc = lang if lang in ("en", "tr", "zh", "es") else "en"
    return _VULN_TIER_I18N.get(str(tier_val), {}).get(loc, str(tier_val or "-"))


_SWOT_I18N: Dict[str, Dict[str, str]] = {
    "en": {
        "tok_per_cap": "m²/p",
        "tok_open_agri": "open/agri",
        "tok_permeable": "permeable",
        "tok_zero_bldg": "0 bldg",
        "tok_vacant": "vacant",
        "tok_sit": "heritage",
        "tok_stream": "stream",
        "tok_facilities": "facilities",
        "tok_min": "min",
        "tok_risk": "risk",
        "tok_ind": "ind",
        "tok_res": "res",
        "tok_idx": " idx",
        "h_s": "STRENGTHS (Measured Internal Assets)",
        "h_w": "WEAKNESSES (Measured Internal Deficits)",
        "h_o": "OPPORTUNITIES (Measured Spatial Potentials)",
        "h_t": "THREATS (Measured Hazard & Pressure Exposures)",
        "h_g": "DATA GAPS (Unmeasured / Missing Input Layers)",
        "no_s": "No strong threshold exceedance measured across active zones.",
        "no_w": "No critical internal fabric deficit detected in measured built zones.",
        "no_o": "No distinct spatial reserve or corridor potential measured.",
        "no_t": "No major measured hazard or land-use friction threshold exceeded.",
        "no_g": "All primary hazard, morphology, facility, thermal, and terrain layers supplied.",
        "s_donati": "Adequate active social/green facility provision (>=10 m²/person): {tags}.",
        "s_evac": "Open street canyon & wide evacuation axes (yg>=10 m, H/W<1.0): {tags}.",
        "s_bldg_ok": "Sound building stock (<5% deteriorated structures): {tags}.",
        "s_mix": "Balanced mixed-use urban vitality (entropy H>=0.55): {tags}.",
        "s_low_vuln": "Low composite disaster vulnerability under measured hazard layers: {tags}.",
        "s_open_eco": "Intact unbuilt permeable/agricultural or ecological continuity: {tags}.",
        "w_donati_cap": "MPYY active facility/green deficit (<10 m²/person): {tags}.",
        "w_donati_dist": "Long walking distance to nearest facility (>500 m): {tags}.",
        "w_hw": "Critical street-canyon debris obstruction risk (H/W>=1.4): {tags}.",
        "w_dead": "High cul-de-sac / dead-end street ratio (>=20%): {tags}.",
        "w_kotu": "Elevated deteriorated building stock (>=20% poor condition): {tags}.",
        "w_tight": "High ground coverage or narrow evacuation streets (TAKS>=45% or yg<7 m): {tags}.",
        "o_reserve": "Planned reserve capacity on non-agricultural vacant parcels (>=30% vacant, low hazard): {tags}.",
        "o_heritage": "Cultural heritage / conservation assets supporting adaptive cultural planning: {tags}.",
        "o_corridor": "Wide arterial street backbone (>=12 m) enabling green-mobility corridors: {tags}.",
        "o_eco": "Ecological / agricultural green-blue network preservation opportunity: {tags}.",
        "o_hubs": "Multi-point facility / strategic focus concentration: {tags}.",
        "t_fault": "Active fault proximity or direct crossing (<=350 m / min<=50 m): {tags}.",
        "t_flood": "Flood hazard overlap or near-stream exposure (risk>=10% or stream<=200 m): {tags}.",
        "t_slope": "Steep topographic slope constraint (>=15%): {tags}.",
        "t_ind_res": "Industry–residential land-use friction requiring environmental buffer: {tags}.",
        "t_lst": "Elevated Land Surface Temperature (LST / Urban Heat Island): {tags}.",
        "t_vuln": "High / Very High composite E-S/AC vulnerability: {tags}.",
        "gap_fay": "Active Fault (`fay`) layer not supplied — seismic proximity unmeasured.",
        "gap_risk": "Flood / Hazard Risk (`risk`) polygon layer not supplied — polygon risk share unmeasured.",
        "gap_donati": "Social Facility (`donati`) layer not supplied — point facility provision unmeasured.",
        "gap_kotu": "Building structural condition (`kotu_yapi`) attribute/layer not supplied — physical decay share unmeasured.",
        "gap_lst": "Thermal / Land Surface Temperature (`lst`) layer not supplied — urban heat island anomaly unmeasured.",
        "gap_dem": "DEM / Slope raster (`dem`) not supplied — terrain slope (%) and elevation (m) unmeasured.",
    },
    "tr": {
        "tok_per_cap": "m²/kişi",
        "tok_open_agri": "açık/tarım",
        "tok_permeable": "geçirimli",
        "tok_zero_bldg": "0 yapı",
        "tok_vacant": "boş",
        "tok_sit": "sit",
        "tok_stream": "dere",
        "tok_facilities": "donatı",
        "tok_min": "min.",
        "tok_risk": "risk",
        "tok_ind": "sanayi",
        "tok_res": "konut",
        "tok_idx": " indeks",
        "h_s": "GÜÇLÜ YÖNLER (Ölçülen İçsel Varlıklar)",
        "h_w": "ZAYIF YÖNLER (Ölçülen İçsel Eksiklikler)",
        "h_o": "FIRSATLAR (Ölçülen Mekânsal Potansiyeller)",
        "h_t": "TEHDİTLER (Ölçülen Tehlike ve Baskılar)",
        "h_g": "VERİ BOŞLUKLARI (Sağlanmayan / Ölçülemeyen Katmanlar)",
        "no_s": "Aktif bölgelerde belirgin güçlü eşik aşımı ölçülmedi.",
        "no_w": "Ölçülen yapılı bölgelerde kritik içsel doku eksiği saptanmadı.",
        "no_o": "Belirgin mekânsal rezerv veya koridor potansiyeli ölçülmedi.",
        "no_t": "Ölçülen büyük tehlike veya kullanım çakışması eşiği aşılmadı.",
        "no_g": "Tüm temel tehlike, morfoloji, donatı, termal ve topoğrafya katmanları mevcut.",
        "s_donati": "Yeterli kişi başı aktif donatı/yeşil alan (>=10 m²/kişi): {tags}.",
        "s_evac": "Geniş tahliye yolları ve açık sokak kanyonu (yg>=10 m, H/W<1.0): {tags}.",
        "s_bldg_ok": "Sağlıklı yapı stoğu (kötü yapı <%5): {tags}.",
        "s_mix": "Dengeli karma kullanım canlılığı (entropi H>=0.55): {tags}.",
        "s_low_vuln": "Ölçülen tehlike katmanlarına göre düşük bileşik kırılganlık: {tags}.",
        "s_open_eco": "Yapısız tarımsal/ekolojik açık alan sürekliliği: {tags}.",
        "w_donati_cap": "MPYY kişi başı aktif donatı yetersizliği (<10 m²/kişi): {tags}.",
        "w_donati_dist": "En yakın donatıya yüksek erişim mesafesi (>500 m): {tags}.",
        "w_hw": "Kritik sokak enkaz kapanma riski (H/W>=1.4): {tags}.",
        "w_dead": "Yüksek çıkmaz sokak oranı (>=%20): {tags}.",
        "w_kotu": "Yıpranmış/kötü durumdaki yapı stoğu oranı (>=%20): {tags}.",
        "w_tight": "Yüksek taban alanı sıkışıklığı veya dar yollar (TAKS>=%45 veya yg<7 m): {tags}.",
        "o_reserve": "Tarım dışı düşük tehlikeli boş parsel rezerv kapasitesi (>=%30 boş): {tags}.",
        "o_heritage": "Kültürel miras / sit varlıklarıyla koruma-geliştirme potansiyeli: {tags}.",
        "o_corridor": "Yeşil ulaşım ve omurga güçlendirmeye elverişli geniş arterler (>=12 m): {tags}.",
        "o_eco": "Ekolojik ve tarımsal yeşil-mavi ağ sürekliliği fırsatı: {tags}.",
        "o_hubs": "Çoklu donatı / stratejik odak yoğunlaşması: {tags}.",
        "t_fault": "Diri fay hattına yakınlık veya doğrudan kesim (<=350 m / min<=50 m): {tags}.",
        "t_flood": "Taşkın riski örtüşmesi veya dere yatağı yakınlığı (risk>=%10 veya dere<=200 m): {tags}.",
        "t_slope": "Yüksek topoğrafik eğim kısıtı (>=%15): {tags}.",
        "t_ind_res": "Çevresel tampon gerektiren sanayi–konut kullanım sürtüşmesi: {tags}.",
        "t_lst": "Yüksek Yüzey Sıcaklığı (LST / Kentsel Isı Adası baskısı): {tags}.",
        "t_vuln": "Yüksek / Çok Yüksek E-S/AC bileşik kırılganlık: {tags}.",
        "gap_fay": "Diri Fay (`fay`) katmanı sağlanmadı — sismik yakınlık ölçülemedi.",
        "gap_risk": "Taşkın / Afet Risk (`risk`) poligon katmanı sağlanmadı — risk alan payı ölçülemedi.",
        "gap_donati": "Sosyal Donatı (`donati`) katmanı sağlanmadı — nokta donatı dağılımı ölçülemedi.",
        "gap_kotu": "Yapı kalite/durum (`kotu_yapi`) özniteliği sağlanmadı — yıpranmış yapı payı ölçülemedi.",
        "gap_lst": "Yüzey Sıcaklığı (`lst`) katmanı sağlanmadı — kentsel ısı adası anomalisi ölçülemedi.",
        "gap_dem": "DEM / Eğim rasterı (`dem`) sağlanmadı — eğim (%) ve rakım (m) ölçülemedi.",
    },
    "zh": {
        "tok_per_cap": "m²/人",
        "tok_open_agri": "开敞/农业",
        "tok_permeable": "透水",
        "tok_zero_bldg": "0建筑",
        "tok_vacant": "空地",
        "tok_sit": "保护区",
        "tok_stream": "河道",
        "tok_facilities": "设施",
        "tok_min": "最近",
        "tok_risk": "风险",
        "tok_ind": "工业",
        "tok_res": "居住",
        "tok_idx": " 指数",
        "h_s": "优势 STRENGTHS（实测内部资源）",
        "h_w": "劣势 WEAKNESSES（实测内部短板）",
        "h_o": "机遇 OPPORTUNITIES（实测空间潜力）",
        "h_t": "威胁 THREATS（实测灾害与压力）",
        "h_g": "数据缺口 DATA GAPS（未提供/未测图层）",
        "no_s": "当前活动分区未测得显著优势阈值。",
        "no_w": "已建分区未测得显著内部肌理短板。",
        "no_o": "未测得明显空间储备或廊道潜力。",
        "no_t": "未测得显著灾害或用地冲突阈值超标。",
        "no_g": "全部主要灾害、形态、设施、热环境与地形图层均已提供。",
        "s_donati": "人均公共设施/绿地充足（>=10 m²/人）：{tags}。",
        "s_evac": "疏散道路宽阔、街谷通畅（yg>=10 m，H/W<1.0）：{tags}。",
        "s_bldg_ok": "建筑质量良好（破损建筑<5%）：{tags}。",
        "s_mix": "混合用地活力均衡（香农熵 H>=0.55）：{tags}。",
        "s_low_vuln": "实测灾害条件下综合脆弱性较低：{tags}。",
        "s_open_eco": "未建农林/生态开敞空间连续性完整：{tags}。",
        "w_donati_cap": "MPYY 人均公共设施/绿地不足（<10 m²/人）：{tags}。",
        "w_donati_dist": "最近公共设施步行距离过远（>500 m）：{tags}。",
        "w_hw": "街谷废墟阻塞风险高（H/W>=1.4）：{tags}。",
        "w_dead": "尽端路比例偏高（>=20%）：{tags}。",
        "w_kotu": "破损/老化建筑比例偏高（>=20%）：{tags}。",
        "w_tight": "建筑覆盖率过高或疏散街道偏窄（TAKS>=45% 或 yg<7 m）：{tags}。",
        "o_reserve": "低风险非农空地具备规划储备潜力（空地>=30%）：{tags}。",
        "o_heritage": "历史保护与文化遗产资产潜力：{tags}。",
        "o_corridor": "主干道宽度充足（>=12 m），利于绿色交通廊道升级：{tags}。",
        "o_eco": "蓝绿生态与农业保护廊道延续机会：{tags}。",
        "o_hubs": "多设施/战略节点集聚区：{tags}。",
        "t_fault": "邻近或穿越活动断层（<=350 m / min<=50 m）：{tags}。",
        "t_flood": "洪涝风险区重叠或临近河道（risk>=10% 或 河距<=200 m）：{tags}。",
        "t_slope": "陡坡地形制约（坡度>=15%）：{tags}。",
        "t_ind_res": "工业与居住邻接摩擦，需设置生态隔离缓冲带：{tags}。",
        "t_lst": "地表温度偏高（LST / 城市热岛效应）：{tags}。",
        "t_vuln": "综合脆弱性高/极高（E-S/AC）：{tags}。",
        "gap_fay": "未提供活动断层（`fay`）图层 — 地震断层距离未测。",
        "gap_risk": "未提供洪涝/灾害风险（`risk`）面图层 — 风险区占比未测。",
        "gap_donati": "未提供公共设施（`donati`）图层 — 点状设施供给未测。",
        "gap_kotu": "未提供建筑质量（`kotu_yapi`）字段/图层 — 破损建筑比例未测。",
        "gap_lst": "未提供地表温度（`lst`）图层 — 热岛异常未测。",
        "gap_dem": "未提供数字高程模型（`dem`）— 坡度（%）与高程（m）未测。",
    },
    "es": {
        "tok_per_cap": "m²/hab",
        "tok_open_agri": "abierto/agríc.",
        "tok_permeable": "permeable",
        "tok_zero_bldg": "0 edif.",
        "tok_vacant": "vacante",
        "tok_sit": "sitio",
        "tok_stream": "cauce",
        "tok_facilities": "equip.",
        "tok_min": "mín.",
        "tok_risk": "riesgo",
        "tok_ind": "ind.",
        "tok_res": "resid.",
        "tok_idx": " índ.",
        "h_s": "FORTALEZAS (Activos Medidos)",
        "h_w": "DEBILIDADES (Déficits Internos Medidos)",
        "h_o": "OPORTUNIDADES (Potenciales Espaciales Medidos)",
        "h_t": "AMENAZAS (Exposición a Riesgos y Presiones)",
        "h_g": "BRECHAS DE DATOS (Capas Faltantes / No Medidas)",
        "no_s": "No se midieron umbrales positivos destacados en las zonas activas.",
        "no_w": "No se detectaron déficits críticos en las zonas edificadas medidas.",
        "no_o": "No se midió reserva territorial ni corredor potencial destacado.",
        "no_t": "No se superaron umbrales críticos de amenaza o fricción de uso.",
        "no_g": "Se proporcionaron todas las capas principales de riesgo, morfología, equipamiento, térmico y DEM.",
        "s_donati": "Dotación verde/social adecuada (>=10 m²/persona): {tags}.",
        "s_evac": "Cañón urbano abierto y vías amplias de evacuación (yg>=10 m, H/W<1.0): {tags}.",
        "s_bldg_ok": "Parque edificado en buen estado (<5% deteriorado): {tags}.",
        "s_mix": "Vitalidad equilibrada de uso mixto (entropía H>=0.55): {tags}.",
        "s_low_vuln": "Baja vulnerabilidad compuesta bajo capas de amenaza medidas: {tags}.",
        "s_open_eco": "Continuidad permeable agrícola o ecológica sin edificación: {tags}.",
        "w_donati_cap": "Déficit de equipamiento activo MPYY (<10 m²/persona): {tags}.",
        "w_donati_dist": "Distancia elevada al equipamiento más cercano (>500 m): {tags}.",
        "w_hw": "Riesgo crítico de obstrucción por escombros en calle (H/W>=1.4): {tags}.",
        "w_dead": "Alta proporción de calles sin salida (>=20%): {tags}.",
        "w_kotu": "Proporción elevada de edificación deteriorada (>=20%): {tags}.",
        "w_tight": "Alta ocupación en planta o calles estrechas (TAKS>=45% o yg<7 m): {tags}.",
        "o_reserve": "Capacidad de reserva en parcelas vacantes no agrícolas de bajo riesgo (>=30%): {tags}.",
        "o_heritage": "Activos patrimoniales y sitios protegidos para planificación cultural: {tags}.",
        "o_corridor": "Ejes arteriales amplios (>=12 m) aptos para corredores verdes: {tags}.",
        "o_eco": "Oportunidad de conectividad ecológica y red verde-azul: {tags}.",
        "o_hubs": "Concentración de nodos de equipamiento y focos estratégicos: {tags}.",
        "t_fault": "Proximidad o cruce directo de falla activa (<=350 m / min<=50 m): {tags}.",
        "t_flood": "Solapamiento con riesgo de inundación o cercanía a cauce (risk>=10% o cauce<=200 m): {tags}.",
        "t_slope": "Restricción por pendiente topográfica fuerte (>=15%): {tags}.",
        "t_ind_res": "Fricción industrial-residencial que requiere franja de amortiguamiento: {tags}.",
        "t_lst": "Temperatura superficial elevada (LST / Isla de Calor Urbana): {tags}.",
        "t_vuln": "Vulnerabilidad compuesta E-S/AC Alta / Muy Alta: {tags}.",
        "gap_fay": "Capa de Falla Activa (`fay`) no suministrada — proximidad sísmica no medida.",
        "gap_risk": "Capa de Riesgo de Inundación (`risk`) no suministrada — área en riesgo no medida.",
        "gap_donati": "Capa de Equipamiento Social (`donati`) no suministrada — dotación puntual no medida.",
        "gap_kotu": "Atributo de estado constructivo (`kotu_yapi`) no suministrado — deterioro físico no medido.",
        "gap_lst": "Capa Térmica / LST (`lst`) no suministrada — isla de calor no medida.",
        "gap_dem": "Raster DEM / Pendiente (`dem`) no suministrado — pendiente (%) y cota (m) no medidas.",
    },
}


def build_swot_synthesis(
    zones: Optional[Sequence[Dict[str, Any]]],
    P: Optional[Dict[str, Any]] = None,
    lang: str = "en",
) -> Dict[str, Any]:
    """Build deterministic, strictly data-grounded SWOT/GZFT synthesis across zones.

    Enforces Rule 1 (Zero Hallucination):
    - Cites ONLY measured non-None values with `[Kod: metric]` tags.
    - Unbuilt zones (`n==0` or `taks<0.015`) never receive building/canyon bullets.
    - Missing inputs (`fay`, `risk`, `donati`, `kotu_yapi`, `lst`, `dem`) are routed to `data_gaps`.
    """
    loc = lang if lang in _SWOT_I18N else "en"
    T = _SWOT_I18N[loc]
    zlist = list(zones or [])
    p_dict = P or {}
    extra_roles = {
        str(ex.get("role", "")).lower()
        for ex in (p_dict.get("extras") or [])
        if isinstance(ex, dict) and ex.get("layer") is not None
    }

    # --- Detect measured inputs vs missing inputs ---
    has_fay = ("fay" in extra_roles) or any(
        (z.get("ext") or {}).get("fay") is not None or (z.get("ext_min") or {}).get("fay") is not None
        for z in zlist
    )
    has_risk = ("risk" in extra_roles) or any((z.get("ext") or {}).get("risk") is not None for z in zlist)
    has_donati = (
        any(r in extra_roles for r in ("donati", "saglik", "toplanma"))
        or any(
            (z.get("ext") or {}).get("donati") is not None
            or z.get("kisi_basi_donati_m2") is not None
            or z.get("donati_mesafe_m") is not None
            for z in zlist
        )
    )
    has_kotu = any(_zone_kotu_share(z) is not None for z in zlist)
    has_lst = any(r in extra_roles for r in ("lst", "isi_adasi")) or any(
        (z.get("ext") or {}).get("lst") is not None or (z.get("ext") or {}).get("isi_adasi") is not None
        for z in zlist
    )
    has_dem = (p_dict.get("dem") is not None) or any(
        z.get("egim") is not None
        or z.get("rakim") is not None
        or (z.get("ext") or {}).get("egim") is not None
        for z in zlist
    )

    data_gaps: List[str] = []
    missing_codes: List[str] = []
    for present, code, gap_key in (
        (has_fay, "fay", "gap_fay"),
        (has_risk, "risk", "gap_risk"),
        (has_donati, "donati", "gap_donati"),
        (has_kotu, "kotu_yapi", "gap_kotu"),
        (has_lst, "lst", "gap_lst"),
        (has_dem, "dem", "gap_dem"),
    ):
        if not present:
            data_gaps.append(T[gap_key])
            missing_codes.append(code)

    # --- Collect per-indicator measured [Kod: metric] hits ---
    s_donati, s_evac, s_bldg_ok, s_mix, s_low_vuln, s_open_eco = [], [], [], [], [], []
    w_donati_cap, w_donati_dist, w_hw, w_dead, w_kotu, w_tight = [], [], [], [], [], []
    o_reserve, o_heritage, o_corridor, o_eco, o_hubs = [], [], [], [], []
    t_fault, t_flood, t_slope, t_ind_res, t_lst, t_vuln = [], [], [], [], [], []

    total_area_m2 = 0.0
    total_pop = 0.0
    total_bldg = 0
    built_count = 0
    taks_w_sum = 0.0
    hw_vals: List[Tuple[float, float]] = []
    don_vals: List[Tuple[float, float]] = []
    fault_mins: List[float] = []
    high_vuln_codes: List[str] = []

    for idx, z in enumerate(zlist, 1):
        kod = str(z.get("kod") or f"Z{idx}")
        area = max(0.0, float(z.get("area") or 0.0))
        ha = area / 10000.0 if area > 0 else 0.0
        n_bldg = int(z.get("n") or 0)
        nufus = float(z.get("nufus") or 0.0)
        taks = float(z.get("taks") or 0.0)
        is_built = _is_built_zone(z)
        pay = z.get("pay") or {}
        ext = z.get("ext") or {}
        ext_min = z.get("ext_min") or {}
        vuln = _get_zone_vuln(z)

        total_area_m2 += area
        total_pop += nufus
        total_bldg += n_bldg
        taks_w_sum += taks * area
        if is_built:
            built_count += 1

        fay_min = ext_min.get("fay")
        fay_avg = ext.get("fay")
        fay_eff = float(fay_min) if fay_min is not None else (float(fay_avg) if fay_avg is not None else None)
        if fay_eff is not None:
            fault_mins.append(fay_eff)

        dere_min = ext_min.get("dere")
        dere_avg = ext.get("dere")
        dere_eff = float(dere_min) if dere_min is not None else (float(dere_avg) if dere_avg is not None else None)
        risk_v = float(ext["risk"]) if ext.get("risk") is not None else None
        egim_v = z.get("egim") if z.get("egim") is not None else ext.get("egim")
        yg_v = z.get("yg")
        hw_v = z.get("hw_ratio")
        dead_v = z.get("cikmaz_sokak_orani")
        kisi_don = z.get("kisi_basi_donati_m2")
        don_dist = z.get("donati_mesafe_m")
        kotu_v = _zone_kotu_share(z)
        ent_v = z.get("karma_entropi")
        bos_v = float(z.get("bos_arazi_orani") or 0.0)

        tarim_sh = float(pay.get("tarim", 0.0))
        san_sh = float(pay.get("sanayi", 0.0))
        kon_sh = float(pay.get("konut", 0.0))
        sit_sh = max(float(pay.get("sit", 0.0)), float(ext.get("sit") or 0.0), float(ext.get("sit2") or 0.0))
        eco_sh = float(ext.get("ekoloji") or 0.0)

        v_gen = str(vuln.get("genel_kirilganlik") or "")
        if v_gen in _VULN_HIGH_TIERS:
            high_vuln_codes.append(kod)

        # ---- BUILT-ONLY STRENGTHS & WEAKNESSES (Rule 1 strictly blocks unbuilt zones) ----
        if is_built:
            if kisi_don is not None:
                don_vals.append((float(kisi_don), max(1.0, nufus)))
                if float(kisi_don) >= 10.0:
                    s_donati.append((float(kisi_don), f"[{kod}: {float(kisi_don):.1f} {T['tok_per_cap']}]"))
                elif nufus >= 15.0:
                    w_donati_cap.append((10.0 - float(kisi_don), f"[{kod}: {float(kisi_don):.1f} {T['tok_per_cap']}]"))
            elif don_dist is not None and float(don_dist) > 500.0 and nufus >= 15.0:
                w_donati_dist.append((float(don_dist), f"[{kod}: {float(don_dist):.0f} m]"))

            if hw_v is not None:
                hw_vals.append((float(hw_v), max(1.0, area)))
                if float(hw_v) >= 1.4:
                    w_hw.append((float(hw_v), f"[{kod}: H/W={float(hw_v):.2f}]"))

            if yg_v is not None and float(yg_v) >= 10.0 and (hw_v is None or float(hw_v) < 1.0):
                hw_lbl = f", H/W={float(hw_v):.2f}" if hw_v is not None else ""
                s_evac.append((float(yg_v), f"[{kod}: yg={float(yg_v):.1f} m{hw_lbl}]"))
            elif (taks >= 0.45) or (yg_v is not None and float(yg_v) < 7.0):
                parts = []
                if taks >= 0.45:
                    parts.append(f"TAKS {taks * 100:.0f}%")
                if yg_v is not None and float(yg_v) < 7.0:
                    parts.append(f"yg={float(yg_v):.1f} m")
                w_tight.append((taks, f"[{kod}: {', '.join(parts)}]"))

            if kotu_v is not None:
                if kotu_v < 0.05:
                    s_bldg_ok.append((1.0 - kotu_v, f"[{kod}: {kotu_v * 100:.1f}%]"))
                elif kotu_v >= 0.20:
                    w_kotu.append((kotu_v, f"[{kod}: {kotu_v * 100:.0f}%]"))

            if dead_v is not None and float(dead_v) >= 0.20:
                w_dead.append((float(dead_v), f"[{kod}: {float(dead_v) * 100:.0f}%]"))

            if ent_v is not None and float(ent_v) >= 0.55:
                s_mix.append((float(ent_v), f"[{kod}: H={float(ent_v):.2f}]"))
        else:
            # Unbuilt open / agricultural / ecological continuity
            perm_pct = max(0.0, (1.0 - taks) * 100.0)
            if tarim_sh >= 0.55 or eco_sh >= 0.25 or perm_pct >= 90.0:
                dominant_open = max(tarim_sh, eco_sh) * 100.0
                if dominant_open > 0:
                    s_open_eco.append((dominant_open, f"[{kod}: {dominant_open:.0f}% {T['tok_open_agri']}, {T['tok_zero_bldg']}]"))
                else:
                    s_open_eco.append((perm_pct, f"[{kod}: {perm_pct:.0f}% {T['tok_permeable']}, {T['tok_zero_bldg']}]"))

        # Low vulnerability strength only if at least one hazard input was measured
        if (has_fay or has_risk or dere_eff is not None) and v_gen in ("Çok Düşük", "Düşük"):
            s_low_vuln.append((1.0, f"[{kod}: {_localize_vuln_tier(v_gen, loc)}]"))

        # ---- OPPORTUNITIES (strictly non-hallucinated) ----
        is_low_hazard = (fay_eff is None or fay_eff > 350.0) and (risk_v is None or risk_v < 0.10)
        if bos_v >= 0.30 and tarim_sh < 0.70 and is_low_hazard:
            o_reserve.append((bos_v, f"[{kod}: {bos_v * 100:.0f}% {T['tok_vacant']}]"))
        if sit_sh >= 0.15:
            o_heritage.append((sit_sh, f"[{kod}: {sit_sh * 100:.0f}% {T['tok_sit']}]"))
        if yg_v is not None and float(yg_v) >= 12.0:
            o_corridor.append((float(yg_v), f"[{kod}: {float(yg_v):.1f} m]"))
        if eco_sh >= 0.20 or tarim_sh >= 0.55 or (dere_eff is not None and dere_eff <= 300.0 and not is_built):
            metric_s = (
                f"{max(eco_sh, tarim_sh) * 100:.0f}%"
                if max(eco_sh, tarim_sh) > 0
                else f"{dere_eff:.0f} m {T['tok_stream']}"
            )
            o_eco.append((max(eco_sh, tarim_sh), f"[{kod}: {metric_s}]"))
        hub_cnt = ext.get("donati")
        if hub_cnt is not None and float(hub_cnt) >= 2.0:
            o_hubs.append((float(hub_cnt), f"[{kod}: {int(round(hub_cnt))} {T['tok_facilities']}]"))

        # ---- THREATS ----
        if fay_eff is not None and (fay_eff <= 350.0 or (fay_min is not None and float(fay_min) <= 50.0)):
            tag_f = (
                f"{T['tok_min']} {float(fay_min):.0f} m"
                if fay_min is not None and float(fay_min) <= 50.0
                else f"{fay_eff:.0f} m"
            )
            t_fault.append((-fay_eff, f"[{kod}: {tag_f}]"))

        if (risk_v is not None and risk_v >= 0.10) or (dere_eff is not None and dere_eff <= 200.0):
            r_parts = []
            if risk_v is not None and risk_v >= 0.10:
                r_parts.append(f"{T['tok_risk']} {risk_v * 100:.0f}%")
            if dere_eff is not None and dere_eff <= 200.0:
                r_parts.append(f"{T['tok_stream']} {dere_eff:.0f} m")
            t_flood.append((risk_v or 0.2, f"[{kod}: {', '.join(r_parts)}]"))

        if egim_v is not None and float(egim_v) >= 15.0:
            t_slope.append((float(egim_v), f"[{kod}: {float(egim_v):.1f}%]"))

        if san_sh >= 0.20 and kon_sh >= 0.15:
            t_ind_res.append((san_sh + kon_sh, f"[{kod}: {san_sh * 100:.0f}% {T['tok_ind']} / {kon_sh * 100:.0f}% {T['tok_res']}]"))

        lst_v = ext.get("lst") if ext.get("lst") is not None else ext.get("isi_adasi")
        if lst_v is not None and (float(lst_v) >= 32.0 or (0.50 <= float(lst_v) <= 1.0)):
            unit = "°C" if float(lst_v) >= 15.0 else T["tok_idx"]
            t_lst.append((float(lst_v), f"[{kod}: {float(lst_v):.1f}{unit}]"))

        if v_gen in _VULN_HIGH_TIERS:
            t_vuln.append((1.0 if v_gen == "Yüksek" else 2.0, f"[{kod}: {_localize_vuln_tier(v_gen, loc)}]"))

    def _emit(items: List[Tuple[float, str]], key: str, limit: int = 5) -> Optional[str]:
        if not items:
            return None
        ordered = sorted(items, key=lambda pair: pair[0], reverse=True)
        tags = ", ".join(tag for _, tag in ordered[:limit])
        if len(ordered) > limit:
            tags += f" (+{len(ordered) - limit})"
        return T[key].format(tags=tags)

    strengths = [
        line for line in (
            _emit(s_donati, "s_donati"),
            _emit(s_evac, "s_evac"),
            _emit(s_bldg_ok, "s_bldg_ok"),
            _emit(s_mix, "s_mix"),
            _emit(s_open_eco, "s_open_eco"),
            _emit(s_low_vuln, "s_low_vuln"),
        ) if line
    ] or [T["no_s"]]

    weaknesses = [
        line for line in (
            _emit(w_donati_cap, "w_donati_cap"),
            _emit(w_hw, "w_hw"),
            _emit(w_kotu, "w_kotu"),
            _emit(w_dead, "w_dead"),
            _emit(w_tight, "w_tight"),
            _emit(w_donati_dist, "w_donati_dist"),
        ) if line
    ] or [T["no_w"]]

    opportunities = [
        line for line in (
            _emit(o_reserve, "o_reserve"),
            _emit(o_heritage, "o_heritage"),
            _emit(o_corridor, "o_corridor"),
            _emit(o_eco, "o_eco"),
            _emit(o_hubs, "o_hubs"),
        ) if line
    ] or [T["no_o"]]

    threats = [
        line for line in (
            _emit(t_fault, "t_fault"),
            _emit(t_flood, "t_flood"),
            _emit(t_vuln, "t_vuln"),
            _emit(t_ind_res, "t_ind_res"),
            _emit(t_slope, "t_slope"),
            _emit(t_lst, "t_lst"),
        ) if line
    ] or [T["no_t"]]

    metrics_snapshot: Dict[str, Any] = {
        "zone_count": len(zlist),
        "built_zone_count": built_count,
        "unbuilt_zone_count": len(zlist) - built_count,
        "total_area_ha": round(total_area_m2 / 10000.0, 2),
        "total_population": int(round(total_pop)),
        "total_buildings": total_bldg,
        "mean_taks_pct": round((taks_w_sum / total_area_m2) * 100.0, 1) if total_area_m2 > 0 else None,
        "mean_hw_ratio": (
            round(sum(v * w for v, w in hw_vals) / sum(w for _, w in hw_vals), 2)
            if hw_vals else None
        ),
        "mean_facility_m2_per_cap": (
            round(sum(v * w for v, w in don_vals) / sum(w for _, w in don_vals), 1)
            if don_vals else None
        ),
        "min_fault_m": round(min(fault_mins), 1) if fault_mins else None,
        "high_vuln_zones": high_vuln_codes,
        "missing_inputs": missing_codes,
    }

    summary_lines = [
        f"=== {T['h_s']} ===",
        *[f"  • {b}" for b in strengths],
        f"\n=== {T['h_w']} ===",
        *[f"  • {b}" for b in weaknesses],
        f"\n=== {T['h_o']} ===",
        *[f"  • {b}" for b in opportunities],
        f"\n=== {T['h_t']} ===",
        *[f"  • {b}" for b in threats],
        f"\n=== {T['h_g']} ===",
        *([f"  • {b}" for b in data_gaps] if data_gaps else [f"  • {T['no_g']}"]),
    ]

    return {
        "strengths": strengths,
        "weaknesses": weaknesses,
        "opportunities": opportunities,
        "threats": threats,
        "data_gaps": data_gaps,
        "summary_text": "\n".join(summary_lines),
        "metrics_snapshot": metrics_snapshot,
    }


# ---------------------------------------------------------------------------
# 2. Semantic 3-Language Zone Symbology & Callouts
# ---------------------------------------------------------------------------
def _extract_zone_profile(feat: Any, z_dict: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Read domain shares & priority markers from zone dict or layer feature attributes."""
    if z_dict is not None:
        pay = z_dict.get("pay") or {}
        sub_p = z_dict.get("sub_lu_pay") or {}
        ext = z_dict.get("ext") or {}
        ext_min = z_dict.get("ext_min") or {}
        vuln = _get_zone_vuln(z_dict)
        return {
            "kod": str(z_dict.get("kod") or ""),
            "karakter": str(z_dict.get("karakter") or ""),
            "mudahale": str(z_dict.get("mudahale_karari") or ""),
            "v_gen": str(vuln.get("genel_kirilganlik") or ""),
            "sit": max(float(pay.get("sit", 0.0)), float(ext.get("sit") or 0.0), float(ext.get("sit2") or 0.0)),
            "sanayi": float(pay.get("sanayi", 0.0)),
            "tarim": float(pay.get("tarim", 0.0)),
            "donati": float(pay.get("donati", 0.0)),
            "ticaret": float(pay.get("ticaret", 0.0)),
            "konut": float(pay.get("konut", 0.0)),
            "ekoloji": max(float(ext.get("ekoloji") or 0.0), float(sub_p.get("mezarlik", 0.0))),
            "fay": ext_min.get("fay") if ext_min.get("fay") is not None else ext.get("fay"),
            "risk": ext.get("risk"),
            "built": _is_built_zone(z_dict),
        }

    def _fnum(attr: str, default: float = 0.0) -> float:
        try:
            v = feat[attr]
            return float(v) / 100.0 if v is not None else default
        except (KeyError, IndexError, TypeError, ValueError):
            return default

    def _fraw(attr: str) -> Optional[float]:
        try:
            v = feat[attr]
            return float(v) if v is not None else None
        except (KeyError, IndexError, TypeError, ValueError):
            return None

    def _fstr(attr: str) -> str:
        try:
            v = feat[attr]
            return str(v or "")
        except (KeyError, IndexError, TypeError):
            return ""

    taks_pct = _fraw("Taban_Alani_Orani_TAKS_Yuzde") or 0.0
    n_bldg = _fraw("Toplam_Bina_Sayisi") or 0.0
    return {
        "kod": _fstr("Bolge_Kodu"),
        "karakter": _fstr("Baskin_Karakter"),
        "mudahale": _fstr("Mudahale_Karari"),
        "v_gen": _fstr("Genel_Kirilganlik_Sinifi"),
        "sit": max(_fnum("Sit_Alani_Orani_Yuzde"), _fnum("Tescilli_Alan_Orani_sit2_Yuzde")),
        "sanayi": _fnum("Sanayi_Depolama_Orani_Yuzde"),
        "tarim": _fnum("Tarim_Acik_Alan_Orani_Yuzde"),
        "donati": _fnum("Donati_Alani_Orani_Yuzde"),
        "ticaret": _fnum("Ticaret_Kullanim_Orani_Yuzde"),
        "konut": _fnum("Konut_Kullanim_Orani_Yuzde"),
        "ekoloji": 0.0,
        "fay": _fraw("Fay_Hattina_Uzaklik_m"),
        "risk": _fnum("Taskin_Risk_Alani_Orani_Yuzde") if _fraw("Taskin_Risk_Alani_Orani_Yuzde") is not None else None,
        "built": (n_bldg > 0 and taks_pct >= 1.5),
    }


def _classify_zone_domain(prof: Dict[str, Any], focus_axis: str) -> Dict[str, Any]:
    kar_l = prof["karakter"].lower()
    mud_l = prof["mudahale"].lower()
    sit_v = prof["sit"]
    san_v = prof["sanayi"]
    tar_v = prof["tarim"]
    don_v = prof["donati"]
    tic_v = prof["ticaret"]
    eco_v = prof["ekoloji"]

    if sit_v >= 0.30 or any(k in kar_l for k in ("sit", "tarih", "miras")):
        domain = "heritage"
    elif don_v >= 0.35 or any(k in kar_l for k in ("donatı", "eğitim", "kamusal", "okul")):
        domain = "education"
    elif san_v >= 0.35 or any(k in kar_l for k in ("sanayi", "imalat", "depolama")):
        domain = "industry_energy"
    elif eco_v >= 0.25 or any(k in kar_l for k in ("mezarlık", "ekoloj", "orman", "sulak")):
        domain = "ecology"
    elif tar_v >= 0.50 or (not prof["built"] and prof["konut"] < 0.20) or any(k in kar_l for k in ("tarım", "açık alan", "kırsal")):
        domain = "agriculture"
    elif tic_v >= 0.30 or any(k in kar_l for k in ("ticaret", "karma")):
        domain = "commercial"
    else:
        domain = "residential"

    fay_v = prof["fay"]
    risk_v = prof["risk"]
    high_risk = (
        prof["v_gen"] in _VULN_HIGH_TIERS
        or (fay_v is not None and fay_v <= 350.0)
        or (risk_v is not None and risk_v >= 0.20)
    )
    is_priority = (
        high_risk
        or sit_v >= 0.30
        or (san_v >= 0.40 and prof["konut"] >= 0.20)
        or any(k in mud_l for k in ("acil", "yasak", "dönüşüm", "koruma"))
    )

    axis = focus_axis if focus_axis in _FOCUS_AXIS_CODES else "balanced"
    aligned = (
        (axis == "balanced" and is_priority)
        or (axis == "resilience" and high_risk)
        or (axis == "ecology" and domain in ("ecology", "agriculture"))
        or (axis == "facility" and (domain == "education" or "donatı" in kar_l))
        or (axis == "tourism_culture" and domain in ("heritage", "commercial"))
        or (axis == "production" and domain in ("industry_energy", "agriculture"))
    )

    return {
        "domain": domain,
        "hex": SYNTHESIS_PALETTE[domain],
        "is_priority": is_priority,
        "aligned": aligned,
        "has_agri_hatch": tar_v >= 0.40 or domain == "agriculture",
        "has_ind_hatch": san_v >= 0.30 or domain == "industry_energy",
        "has_sit_hatch": sit_v >= 0.20 or domain == "heritage",
        "has_eco_hatch": eco_v >= 0.20 or domain == "ecology",
    }


def _make_line_hatch_layer(angle_deg: float, distance_mm: float, width_mm: float, hex_color: str, alpha: int = 160):
    pat = QgsLinePatternFillSymbolLayer()
    pat.setLineAngle(float(angle_deg))
    pat.setDistance(float(distance_mm))
    line_sym = QgsLineSymbol.createSimple(
        {
            "color": _hex_rgba(hex_color, alpha),
            "width": str(width_mm),
            "line_style": "solid",
        }
    )
    pat.setSubSymbol(line_sym)
    return pat


def _make_point_hatch_layer(dist_mm: float, size_mm: float, hex_color: str, alpha: int = 165):
    pat = QgsPointPatternFillSymbolLayer()
    pat.setDistanceX(float(dist_mm))
    pat.setDistanceY(float(dist_mm))
    pt_sym = QgsMarkerSymbol.createSimple(
        {
            "name": "circle",
            "color": _hex_rgba(hex_color, alpha),
            "outline_style": "no",
            "size": str(size_mm),
        }
    )
    pat.setSubSymbol(pt_sym)
    return pat


def _apply_zone_labeling(layer: QgsVectorLayer, use_callouts: bool = True) -> None:
    """Apply collision-free sans-serif labeling with optional callouts on priority zones."""
    base_tf = QgsTextFormat()
    base_font = QFont("Segoe UI", 10)
    base_font.setBold(True)
    base_tf.setFont(base_font)
    base_tf.setSize(10.5)
    base_tf.setColor(_qcolor(SYNTHESIS_PALETTE["strategy"]))
    buf = QgsTextBufferSettings()
    buf.setEnabled(True)
    buf.setSize(1.4)
    buf.setColor(QColor("#ffffff"))
    base_tf.setBuffer(buf)

    if use_callouts and hasattr(QgsRuleBasedLabeling, "Rule"):
        try:
            root_rule = QgsRuleBasedLabeling.Rule(None)

            # Rule 1: Flagged high-risk / heritage / priority zones with leader-line callout cards
            p_ls = QgsPalLayerSettings()
            p_ls.fieldName = (
                "\"Bolge_Kodu\" || char(10) || "
                "if(length(coalesce(\"Baskin_Karakter\", '')) <= 42, coalesce(\"Baskin_Karakter\", ''), "
                "regexp_replace(left(coalesce(\"Baskin_Karakter\", ''), 42), ' [^ ]*$', '') || '...') "
                "|| if(length(coalesce(\"Pafta_Lejant_Sentez_Metni\", '')) > 0, "
                "char(10) || if(length(\"Pafta_Lejant_Sentez_Metni\") <= 64, \"Pafta_Lejant_Sentez_Metni\", "
                "regexp_replace(left(\"Pafta_Lejant_Sentez_Metni\", 64), ' [^ ]*$', '') || '...'), '')"
            )
            p_ls.isExpression = True
            p_ls.placement = _PLACE_AROUND
            p_ls.dist = 4.0
            p_ls.priority = 8
            p_tf = QgsTextFormat()
            p_font = QFont("Segoe UI", 7)
            p_font.setBold(True)
            p_tf.setFont(p_font)
            p_tf.setSize(7.0)
            p_tf.setColor(_qcolor(SYNTHESIS_PALETTE["strategy"]))
            p_buf = QgsTextBufferSettings()
            p_buf.setEnabled(True)
            p_buf.setSize(0.8)
            p_buf.setColor(QColor("#ffffff"))
            p_tf.setBuffer(p_buf)
            p_ls.setFormat(p_tf)

            callout = None
            try:
                co = QgsBalloonCallout()
                co.setEnabled(True)
                co.setAnchorPoint(_CALLOUT_ANCHOR_POS)
                co.setCornerRadius(1.2)
                co.setWedgeWidth(2.0)
                fill_sym = QgsFillSymbol.createSimple(
                    {
                        "color": "255,255,255,235",
                        "outline_color": SYNTHESIS_PALETTE["vulnerability"],
                        "outline_width": "0.35",
                        "outline_style": "dash",
                    }
                )
                co.setFillSymbol(fill_sym)
                callout = co
            except Exception:
                try:
                    mco = QgsManhattanLineCallout()
                    mco.setEnabled(True)
                    mco.setLineSymbol(
                        QgsLineSymbol.createSimple(
                            {"color": SYNTHESIS_PALETTE["strategy"], "width": "0.3", "line_style": "solid"}
                        )
                    )
                    callout = mco
                except Exception:
                    callout = None
            if callout is not None:
                p_ls.setCallout(callout)

            field_names = {f.name() for f in layer.fields()}
            conds = []
            if "Genel_Kirilganlik_Sinifi" in field_names:
                conds.append("\"Genel_Kirilganlik_Sinifi\" IN ('Yüksek', 'Çok Yüksek')")
            if "Sit_Alani_Orani_Yuzde" in field_names:
                conds.append("coalesce(\"Sit_Alani_Orani_Yuzde\", 0) >= 30")
            if "Fay_Hattina_Uzaklik_m" in field_names:
                conds.append("coalesce(\"Fay_Hattina_Uzaklik_m\", 9999) <= 250")

            if conds:
                r_prio = QgsRuleBasedLabeling.Rule(p_ls)
                r_prio.setDescription("Priority Callouts")
                r_prio.setFilterExpression(f"coalesce(@map_id, '') <> 'inset_map' AND ({' OR '.join(conds)})")
                root_rule.appendChild(r_prio)

            # Rule 2: Standard zone code labels
            s_ls = QgsPalLayerSettings()
            s_ls.fieldName = "Bolge_Kodu"
            s_ls.isExpression = False
            s_ls.setFormat(base_tf)
            r_std = QgsRuleBasedLabeling.Rule(s_ls)
            r_std.setDescription("Zone Codes")
            r_std.setIsElse(True)
            root_rule.appendChild(r_std)

            layer.setLabelsEnabled(True)
            layer.setLabeling(QgsRuleBasedLabeling(root_rule))
            return
        except Exception:
            pass

    ls = QgsPalLayerSettings()
    ls.fieldName = "Bolge_Kodu"
    ls.isExpression = False
    ls.setFormat(base_tf)
    layer.setLabelsEnabled(True)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(ls))


def apply_synthesis_zone_style(
    layer: Optional[QgsVectorLayer],
    zones: Optional[Sequence[Dict[str, Any]]] = None,
    focus_axis: str = "balanced",
    semantic_mode: bool = True,
    use_callouts: bool = True,
) -> None:
    """Style zone polygon layer using either classic HSV or 3-Language Semantic Cartography."""
    if layer is None or not isinstance(layer, QgsVectorLayer) or not layer.isValid():
        return

    feats = list(layer.getFeatures())
    if not semantic_mode:
        cats = []
        for i, feat in enumerate(feats):
            kod = feat["Bolge_Kodu"]
            h = (i * 0.618033988) % 1.0
            rr, gg, bb = [int(255 * c) for c in colorsys.hsv_to_rgb(h, 0.45, 0.95)]
            sym = QgsFillSymbol.createSimple(
                {
                    "color": f"{rr},{gg},{bb},110",
                    "outline_color": "#0f172a",
                    "outline_width": "0.85",
                    "outline_style": "solid",
                }
            )
            cats.append(QgsRendererCategory(kod, sym, str(kod)))
        layer.setRenderer(QgsCategorizedSymbolRenderer("Bolge_Kodu", cats))
        _apply_zone_labeling(layer, use_callouts=False)
        layer.triggerRepaint()
        return

    zone_by_kod = {str(z.get("kod") or ""): z for z in (zones or []) if z.get("kod")}
    domain_counts: Dict[str, int] = defaultdict(int)
    cats = []

    for feat in feats:
        kod = str(feat["Bolge_Kodu"] or "")
        prof = _extract_zone_profile(feat, zone_by_kod.get(kod))
        cls = _classify_zone_domain(prof, focus_axis)
        dom = cls["domain"]
        idx_dom = domain_counts[dom]
        domain_counts[dom] += 1
        shift = ((idx_dom % 5) - 2) * 0.35

        if focus_axis != "balanced":
            alpha = 165 if cls["aligned"] else 92
        else:
            alpha = 145 if cls["is_priority"] else 115

        outline_col = SYNTHESIS_PALETTE["strategy"] if cls["is_priority"] else "#334155"
        outline_w = "0.85" if cls["is_priority"] else "0.42"
        sym = QgsFillSymbol.createSimple(
            {
                "color": _hex_rgba(cls["hex"], alpha=alpha, tint_shift=shift),
                "outline_color": outline_col,
                "outline_width": outline_w,
                "outline_style": "solid",
            }
        )

        # Layer 2 semantic texture overlays (non-occluding)
        if cls["has_ind_hatch"]:
            sym.appendSymbolLayer(_make_line_hatch_layer(135.0, 2.8, 0.30, SYNTHESIS_PALETTE["industry_energy"], 165))
        elif cls["has_agri_hatch"]:
            sym.appendSymbolLayer(_make_line_hatch_layer(45.0, 3.4, 0.24, "#4D7C0F", 150))

        if cls["has_sit_hatch"]:
            sym.appendSymbolLayer(_make_point_hatch_layer(3.2, 0.85, SYNTHESIS_PALETTE["heritage"], 175))
        elif cls["has_eco_hatch"]:
            sym.appendSymbolLayer(_make_point_hatch_layer(3.6, 0.85, SYNTHESIS_PALETTE["ecology"], 170))

        # Re-add top crisp strategic outline on priority zones so hatching stays inside
        if cls["is_priority"]:
            top_border = QgsSimpleLineSymbolLayer()
            top_border.setColor(_qcolor(SYNTHESIS_PALETTE["strategy"]))
            top_border.setWidth(0.85)
            sym.appendSymbolLayer(top_border)

        kar_short = _clip_words(prof["karakter"] or dom, 44)
        label_txt = f"{kod} — {kar_short}" if kar_short else kod
        cats.append(QgsRendererCategory(feat["Bolge_Kodu"], sym, label_txt))

    layer.setRenderer(QgsCategorizedSymbolRenderer("Bolge_Kodu", cats))
    _apply_zone_labeling(layer, use_callouts=use_callouts)
    layer.triggerRepaint()


# ---------------------------------------------------------------------------
# 3. Multi-Layer Strategic Overlays (Strictly Real Geometry & Attributes)
# ---------------------------------------------------------------------------
def _make_memory_layer(geom_type: str, name: str, crs: QgsCoordinateReferenceSystem, fields: List[QgsField]) -> QgsVectorLayer:
    uri = f"{geom_type}?crs={crs.authid()}" if crs and crs.isValid() else geom_type
    lyr = QgsVectorLayer(uri, name, "memory")
    if crs and crs.isValid():
        lyr.setCrs(crs)
    pr = lyr.dataProvider()
    if fields:
        pr.addAttributes(fields)
        lyr.updateFields()
    return lyr


def _build_exterior_mask_layer(study: Optional[QgsGeometry], work_crs: QgsCoordinateReferenceSystem) -> Optional[QgsVectorLayer]:
    if study is None or study.isEmpty():
        return None
    lyr = _make_memory_layer(
        "MultiPolygon",
        "Calisma_Alani_Maskesi",
        work_crs,
        [_qfield("Kapsam", "string"), _qfield("Alan_Ha", "double")],
    )
    feat = QgsFeature(lyr.fields())
    feat.setGeometry(study)
    feat.setAttributes(["Study Boundary", round(study.area() / 10000.0, 2)])
    lyr.dataProvider().addFeatures([feat])
    lyr.updateExtents()

    fill_sym = QgsFillSymbol.createSimple(
        {
            "color": "226,232,240,175",
            "outline_color": SYNTHESIS_PALETTE["strategy"],
            "outline_width": "0.95",
            "outline_style": "dash",
        }
    )
    lyr.setRenderer(QgsInvertedPolygonRenderer(QgsSingleSymbolRenderer(fill_sym)))
    lyr.triggerRepaint()
    return lyr


def _build_vulnerability_hatch_layer(
    zones: Sequence[Dict[str, Any]], work_crs: QgsCoordinateReferenceSystem
) -> Optional[QgsVectorLayer]:
    if not zones:
        return None
    lyr = _make_memory_layer(
        "MultiPolygon",
        "Afet_Kirilganlik_Tarama",
        work_crs,
        [
            _qfield("Bolge_Kodu", "string"),
            _qfield("Genel_Kirilganlik_Sinifi", "string"),
            _qfield("Deprem_Kirilganlik_Sinifi", "string"),
            _qfield("Sel_Kirilganlik_Sinifi", "string"),
        ],
    )
    feats = []
    for idx, z in enumerate(zones, 1):
        geom = z.get("geom")
        if geom is None or geom.isEmpty():
            continue
        vuln = _get_zone_vuln(z)
        g_sin = str(vuln.get("genel_kirilganlik") or "Düşük")
        d_sin = str(vuln.get("deprem_kirilganlik") or "Düşük")
        s_sin = str(vuln.get("sel_kirilganlik") or "Düşük")
        f = QgsFeature(lyr.fields())
        f.setGeometry(geom)
        f.setAttributes([str(z.get("kod") or f"Z{idx}"), g_sin, d_sin, s_sin])
        feats.append(f)
    if not feats:
        return None
    lyr.dataProvider().addFeatures(feats)
    lyr.updateExtents()

    root = QgsRuleBasedRenderer.Rule(None)
    hatch_specs = [
        ("Very High Vulnerability (Cross Hatch)", "\"Genel_Kirilganlik_Sinifi\" = 'Çok Yüksek'", 2.5, 0.42, "#991B1B", True),
        ("High Vulnerability (Dense Hatch)", "\"Genel_Kirilganlik_Sinifi\" = 'Yüksek'", 3.3, 0.34, SYNTHESIS_PALETTE["vulnerability"], False),
        ("Moderate Vulnerability (Light Hatch)", "\"Genel_Kirilganlik_Sinifi\" = 'Orta'", 5.2, 0.22, "#F87171", False),
    ]
    for label, expr, dist_mm, w_mm, hex_c, cross in hatch_specs:
        sym = QgsFillSymbol()
        # Replace default SimpleFill with transparent outline-only layer + line hatch(es)
        base_sf = QgsSimpleFillSymbolLayer()
        base_sf.setBrushStyle(_BRUSH_NO)
        base_sf.setStrokeStyle(_PEN_NO)
        sym.changeSymbolLayer(0, base_sf)
        sym.appendSymbolLayer(_make_line_hatch_layer(45.0, dist_mm, w_mm, hex_c, 190))
        if cross:
            sym.appendSymbolLayer(_make_line_hatch_layer(135.0, dist_mm, w_mm, hex_c, 190))
        rule = QgsRuleBasedRenderer.Rule(sym)
        rule.setLabel(label)
        rule.setFilterExpression(expr)
        root.appendChild(rule)

    lyr.setRenderer(QgsRuleBasedRenderer(root))
    lyr.triggerRepaint()
    return lyr


def _build_critical_breaches_layer(
    zones: Sequence[Dict[str, Any]], work_crs: QgsCoordinateReferenceSystem
) -> Optional[QgsVectorLayer]:
    feats_data: List[Tuple[QgsPointXY, str, str, str]] = []
    for idx, z in enumerate(zones, 1):
        geom = z.get("geom")
        pt = _safe_point_on_surface(geom)
        if pt is None:
            continue
        kod = str(z.get("kod") or f"Z{idx}")
        ext = z.get("ext") or {}
        ext_min = z.get("ext_min") or {}
        is_built = _is_built_zone(z)

        breaches: List[str] = []
        vals_str: List[str] = []

        fay_min = ext_min.get("fay") if ext_min.get("fay") is not None else ext.get("fay")
        if fay_min is not None and float(fay_min) <= 50.0:
            breaches.append("Fault <= 50m")
            vals_str.append(f"fay={float(fay_min):.0f}m")

        risk_v = ext.get("risk")
        if risk_v is not None and float(risk_v) >= 0.25:
            breaches.append("Flood Risk >= 25%")
            vals_str.append(f"risk={float(risk_v) * 100:.0f}%")

        if is_built:
            hw_v = z.get("hw_ratio")
            if hw_v is not None and float(hw_v) >= 1.5:
                breaches.append("Canyon H/W >= 1.5")
                vals_str.append(f"H/W={float(hw_v):.2f}")
            kotu_v = _zone_kotu_share(z)
            if kotu_v is not None and float(kotu_v) >= 0.25:
                breaches.append("Poor Stock >= 25%")
                vals_str.append(f"kotu={float(kotu_v) * 100:.0f}%")

        if breaches:
            feats_data.append((pt, kod, "; ".join(breaches), ", ".join(vals_str)))

    if not feats_data:
        return None

    lyr = _make_memory_layer(
        "Point",
        "Kritik_Esik_Uyarilari",
        work_crs,
        [
            _qfield("Bolge_Kodu", "string"),
            _qfield("Esik_Tipi", "string"),
            _qfield("Olculen_Deger", "string"),
        ],
    )
    feats = []
    for pt, kod, b_str, v_str in feats_data:
        f = QgsFeature(lyr.fields())
        f.setGeometry(QgsGeometry.fromPointXY(pt))
        f.setAttributes([kod, b_str, v_str])
        feats.append(f)
    lyr.dataProvider().addFeatures(feats)
    lyr.updateExtents()

    sym = QgsMarkerSymbol.createSimple(
        {
            "name": "cross2",
            "color": SYNTHESIS_PALETTE["vulnerability"],
            "outline_color": "#7F1D1D",
            "outline_width": "0.65",
            "size": "4.6",
        }
    )
    if _MARKER_CROSS2 is not None and sym.symbolLayerCount() > 0:
        sl = sym.symbolLayer(0)
        if hasattr(sl, "setShape"):
            sl.setShape(_MARKER_CROSS2)
    lyr.setRenderer(QgsSingleSymbolRenderer(sym))

    ls = QgsPalLayerSettings()
    ls.fieldName = "\"Bolge_Kodu\" || ': ' || \"Esik_Tipi\""
    ls.isExpression = True
    tf = QgsTextFormat()
    fnt = QFont("Segoe UI", 7)
    fnt.setBold(True)
    tf.setFont(fnt)
    tf.setSize(7.5)
    tf.setColor(_qcolor("#991B1B"))
    buf = QgsTextBufferSettings()
    buf.setEnabled(True)
    buf.setSize(1.0)
    buf.setColor(QColor("#ffffff"))
    tf.setBuffer(buf)
    ls.setFormat(tf)
    lyr.setLabelsEnabled(True)
    lyr.setLabeling(QgsVectorLayerSimpleLabeling(ls))
    lyr.triggerRepaint()
    return lyr


_FOCUS_ROLES = ("donati", "saglik", "toplanma", "odak", "ulasim_odak")
_RANK_FIELD_CANDIDATES = ("kademe", "tier", "rank", "onem", "kapasite", "puan", "score", "weight", "agirlik")
_NAME_FIELD_CANDIDATES = ("ad", "adi", "name", "isim", "title", "label", "tesis_adi", "odak_adi", "tur")


def _extract_attr_str(feat: Any, candidates: Tuple[str, ...]) -> Optional[str]:
    fnames = [f.name() for f in feat.fields()]
    lower_map = {fn.lower(): fn for fn in fnames}
    for cand in candidates:
        real_fn = lower_map.get(cand)
        if real_fn:
            v = feat[real_fn]
            if v is not None and str(v).strip() and str(v).strip().upper() != "NULL":
                return str(v).strip()
    return None


def _extract_attr_num(feat: Any, candidates: Tuple[str, ...]) -> Optional[float]:
    fnames = [f.name() for f in feat.fields()]
    lower_map = {fn.lower(): fn for fn in fnames}
    for cand in candidates:
        real_fn = lower_map.get(cand)
        if real_fn:
            try:
                v = feat[real_fn]
                if v is not None:
                    return float(v)
            except (TypeError, ValueError):
                pass
    return None


def _build_focus_and_catchment_layers(
    extras: Sequence[Dict[str, Any]],
    study: Optional[QgsGeometry],
    work_crs: QgsCoordinateReferenceSystem,
    focus_axis: str,
) -> Tuple[Optional[QgsVectorLayer], Optional[QgsVectorLayer], Optional[QgsVectorLayer]]:
    """Build real EPSG:5253 catchments (250/500/1000m), intersection hotspots, and 150m focus clusters."""
    items: List[Dict[str, Any]] = []
    for ex in extras:
        role = str(ex.get("role") or "").lower()
        if role not in _FOCUS_ROLES:
            continue
        lyr = ex.get("layer")
        src_name = str(ex.get("name") or role)
        for feat, geom in _read_layer_geoms(lyr, work_crs):
            pt = _safe_point_on_surface(geom)
            if pt is None:
                continue
            # Skip points > 5km outside study boundary to keep catchments relevant to study area
            if study is not None and not study.isEmpty() and study.distance(QgsGeometry.fromPointXY(pt)) > 5000.0:
                continue
            items.append(
                {
                    "geom": geom,
                    "pt": pt,
                    "role": role,
                    "src_name": src_name,
                    "feat_name": _extract_attr_str(feat, _NAME_FIELD_CANDIDATES) or src_name,
                    "rank_val": _extract_attr_num(feat, _RANK_FIELD_CANDIDATES),
                }
            )

    if not items:
        return None, None, None

    # 1. 150m metric spatial clustering -> Tier 1..4 Focus Layer (Odak_Kademeleri)
    n_pts = len(items)
    pt_geoms = [QgsGeometry.fromPointXY(it["pt"]) for it in items]
    pt_idx = QgsSpatialIndex()
    for i, pg in enumerate(pt_geoms):
        f_tmp = QgsFeature(i)
        f_tmp.setGeometry(pg)
        pt_idx.addFeature(f_tmp)

    visited = [False] * n_pts
    clusters: List[List[int]] = []
    for i in range(n_pts):
        if visited[i]:
            continue
        comp = []
        stack = [i]
        visited[i] = True
        while stack:
            curr = stack.pop()
            comp.append(curr)
            p = items[curr]["pt"]
            rect = QgsRectangle(p.x() - 150.0, p.y() - 150.0, p.x() + 150.0, p.y() + 150.0)
            for nb in pt_idx.intersects(rect):
                if not visited[nb]:
                    p2 = items[nb]["pt"]
                    if math.hypot(p.x() - p2.x(), p.y() - p2.y()) <= 150.0:
                        visited[nb] = True
                        stack.append(nb)
        clusters.append(comp)

    # Determine tiers from real numeric attributes or real cluster cardinality
    has_numeric_rank = any(it["rank_val"] is not None for it in items)
    focus_lyr = _make_memory_layer(
        "Point",
        "Odak_Kademeleri",
        work_crs,
        [
            _qfield("Odak_Kodu", "string"),
            _qfield("Kademe", "int"),
            _qfield("Kume_Sayisi", "int"),
            _qfield("Rol", "string"),
            _qfield("Odak_Etiketi", "string"),
        ],
    )
    cluster_feats: List[QgsFeature] = []
    cluster_rep_geoms: List[QgsGeometry] = []
    for c_idx, comp in enumerate(clusters, 1):
        cx = sum(items[k]["pt"].x() for k in comp) / len(comp)
        cy = sum(items[k]["pt"].y() for k in comp) / len(comp)
        c_pt = QgsPointXY(cx, cy)
        c_cnt = len(comp)
        roles_in = sorted({items[k]["role"] for k in comp})
        dom_role = roles_in[0]
        first_name = items[comp[0]]["feat_name"]
        max_rank = max((items[k]["rank_val"] for k in comp if items[k]["rank_val"] is not None), default=None)

        if has_numeric_rank and max_rank is not None:
            if max_rank >= 4 or c_cnt >= 4:
                tier = 1
            elif max_rank >= 3 or c_cnt >= 2:
                tier = 2
            elif max_rank >= 2:
                tier = 3
            else:
                tier = 4
        else:
            if c_cnt >= 4:
                tier = 1
            elif c_cnt >= 2:
                tier = 2
            elif dom_role in ("odak", "ulasim_odak"):
                tier = 3
            else:
                tier = 4

        code = f"O{c_idx}"
        badge = f"[{code} | n={c_cnt}] {first_name[:28]}"
        f = QgsFeature(focus_lyr.fields())
        f.setGeometry(QgsGeometry.fromPointXY(c_pt))
        f.setAttributes([code, tier, c_cnt, ",".join(roles_in), badge])
        cluster_feats.append(f)
        cluster_rep_geoms.append(QgsGeometry.unaryUnion([items[k]["geom"] for k in comp]))

    focus_lyr.dataProvider().addFeatures(cluster_feats)
    focus_lyr.updateExtents()

    focus_color = (
        SYNTHESIS_PALETTE["tourism_focus"]
        if focus_axis in ("tourism_culture", "balanced")
        else (SYNTHESIS_PALETTE["education"] if focus_axis == "facility" else SYNTHESIS_PALETTE["ecology"])
    )
    tier_cats = []
    tier_specs = [
        (1, "Tier 1 (Regional / Cluster >=4)", "7.2", "1.1", "solid", True),
        (2, "Tier 2 (District / Cluster >=2)", "5.4", "0.8", "solid", False),
        (3, "Tier 3 (Local Focus)", "4.0", "0.55", "dash", False),
        (4, "Tier 4 (Single Point)", "2.8", "0.35", "solid", False),
    ]
    for t_val, t_lbl, sz, ow, ostyle, has_halo in tier_specs:
        msym = QgsMarkerSymbol.createSimple(
            {
                "name": "circle",
                "color": _hex_rgba(focus_color, 210),
                "outline_color": SYNTHESIS_PALETTE["strategy"],
                "outline_width": ow,
                "outline_style": ostyle,
                "size": sz,
            }
        )
        if has_halo:
            halo = QgsSimpleMarkerSymbolLayer()
            halo.setColor(_qcolor(focus_color, 55))
            halo.setStrokeColor(_qcolor(focus_color, 180))
            halo.setStrokeWidth(0.55)
            halo.setSize(9.8)
            msym.insertSymbolLayer(0, halo)
        tier_cats.append(QgsRendererCategory(t_val, msym, t_lbl))
    focus_lyr.setRenderer(QgsCategorizedSymbolRenderer("Kademe", tier_cats))

    f_ls = QgsPalLayerSettings()
    f_ls.fieldName = "Odak_Etiketi"
    f_ls.isExpression = False
    f_tf = QgsTextFormat()
    f_font = QFont("Segoe UI", 8)
    f_font.setBold(True)
    f_tf.setFont(f_font)
    f_tf.setSize(8.0)
    f_tf.setColor(_qcolor(SYNTHESIS_PALETTE["strategy"]))
    f_buf = QgsTextBufferSettings()
    f_buf.setEnabled(True)
    f_buf.setSize(1.1)
    f_buf.setColor(QColor("#ffffff"))
    f_tf.setBuffer(f_buf)
    f_ls.setFormat(f_tf)
    focus_lyr.setLabelsEnabled(True)
    focus_lyr.setLabeling(QgsVectorLayerSimpleLabeling(f_ls))
    focus_lyr.triggerRepaint()

    # 2. Stepped Metric Catchment Bands (250m / 500m / 1000m) -> Odak_Cekim_Alanlari
    clip_geom = study.buffer(1000.0, 8) if (study is not None and not study.isEmpty()) else None
    catch_lyr = _make_memory_layer(
        "MultiPolygon",
        "Odak_Cekim_Alanlari",
        work_crs,
        [_qfield("Band_m", "int"), _qfield("Band_Etiketi", "string")],
    )
    band_geoms: Dict[int, List[QgsGeometry]] = {250: [], 500: [], 1000: []}
    buf500_per_cluster: List[QgsGeometry] = []
    for cg in cluster_rep_geoms:
        b250 = cg.buffer(250.0, 12)
        b500 = cg.buffer(500.0, 12)
        b1000 = cg.buffer(1000.0, 12)
        if clip_geom is not None:
            b250 = b250.intersection(clip_geom)
            b500 = b500.intersection(clip_geom)
            b1000 = b1000.intersection(clip_geom)
        if b500 and not b500.isEmpty() and b500.area() > 10.0:
            buf500_per_cluster.append(b500)
        if b250 and not b250.isEmpty():
            band_geoms[250].append(b250)
        if b500 and not b500.isEmpty():
            band_geoms[500].append(b500)
        if b1000 and not b1000.isEmpty():
            band_geoms[1000].append(b1000)

    u250 = QgsGeometry.unaryUnion(band_geoms[250]) if band_geoms[250] else QgsGeometry()
    u500 = QgsGeometry.unaryUnion(band_geoms[500]) if band_geoms[500] else QgsGeometry()
    u1000 = QgsGeometry.unaryUnion(band_geoms[1000]) if band_geoms[1000] else QgsGeometry()

    donut500 = u500.difference(u250) if (u500 and not u500.isEmpty() and u250 and not u250.isEmpty()) else u500
    donut1000 = u1000.difference(u500) if (u1000 and not u1000.isEmpty() and u500 and not u500.isEmpty()) else u1000

    catch_feats = []
    for band_m, g_band, lbl in (
        (1000, donut1000, "1000 m Catchment"),
        (500, donut500, "500 m Catchment"),
        (250, u250, "250 m Core Catchment"),
    ):
        if g_band and not g_band.isEmpty() and g_band.area() > 1.0:
            cf = QgsFeature(catch_lyr.fields())
            cf.setGeometry(g_band)
            cf.setAttributes([band_m, lbl])
            catch_feats.append(cf)

    if catch_feats:
        catch_lyr.dataProvider().addFeatures(catch_feats)
        catch_lyr.updateExtents()
        c_root = QgsRuleBasedRenderer.Rule(None)
        for band_m, c_alpha, c_lbl in (
            (1000, 26, "1000 m Outer Reach"),
            (500, 48, "500 m Mid Reach"),
            (250, 78, "250 m Core Reach"),
        ):
            csym = QgsFillSymbol.createSimple(
                {
                    "color": _hex_rgba(focus_color, c_alpha),
                    "outline_color": _hex_rgba(focus_color, 175),
                    "outline_width": "0.3",
                    "outline_style": "dash" if band_m > 250 else "solid",
                }
            )
            cr = QgsRuleBasedRenderer.Rule(csym)
            cr.setFilterExpression(f"\"Band_m\" = {band_m}")
            cr.setLabel(c_lbl)
            c_root.appendChild(cr)
        catch_lyr.setRenderer(QgsRuleBasedRenderer(c_root))
        catch_lyr.triggerRepaint()
    else:
        catch_lyr = None

    # 3. Exact Geometric Intersection Hotspots (k >= 2) -> Odak_Cekim_Cakisma_Alanlari
    hotspot_lyr: Optional[QgsVectorLayer] = None
    m_buf = len(buf500_per_cluster)
    if m_buf >= 2:
        b_idx = QgsSpatialIndex()
        for bi, bg in enumerate(buf500_per_cluster):
            ft = QgsFeature(bi)
            ft.setGeometry(bg)
            b_idx.addFeature(ft)
        pair_inters: List[Tuple[int, int, QgsGeometry]] = []
        for i in range(m_buf):
            gi = buf500_per_cluster[i]
            for j in b_idx.intersects(gi.boundingBox()):
                if j <= i:
                    continue
                inter = gi.intersection(buf500_per_cluster[j])
                if inter and not inter.isEmpty() and inter.area() > 25.0:
                    pair_inters.append((i, j, inter))

        if pair_inters:
            k2_union = QgsGeometry.unaryUnion([g for _, _, g in pair_inters])
            triple_inters: List[QgsGeometry] = []
            for i, j, inter_ij in pair_inters:
                for k in b_idx.intersects(inter_ij.boundingBox()):
                    if k <= j:
                        continue
                    g3 = inter_ij.intersection(buf500_per_cluster[k])
                    if g3 and not g3.isEmpty() and g3.area() > 25.0:
                        triple_inters.append(g3)
            k3_union = QgsGeometry.unaryUnion(triple_inters) if triple_inters else QgsGeometry()
            k2_only = (
                k2_union.difference(k3_union)
                if (k3_union and not k3_union.isEmpty() and k2_union and not k2_union.isEmpty())
                else k2_union
            )

            hotspot_lyr = _make_memory_layer(
                "MultiPolygon",
                "Odak_Cekim_Cakisma_Alanlari",
                work_crs,
                [_qfield("Cakisma_Sayisi", "int"), _qfield("Yogunluk_Sinifi", "string")],
            )
            h_feats = []
            if k2_only and not k2_only.isEmpty() and k2_only.area() > 25.0:
                hf2 = QgsFeature(hotspot_lyr.fields())
                hf2.setGeometry(k2_only)
                hf2.setAttributes([2, "Overlap Hotspot (k=2)"])
                h_feats.append(hf2)
            if k3_union and not k3_union.isEmpty() and k3_union.area() > 25.0:
                hf3 = QgsFeature(hotspot_lyr.fields())
                hf3.setGeometry(k3_union)
                hf3.setAttributes([3, "High Overlap Hotspot (k>=3)"])
                h_feats.append(hf3)

            if h_feats:
                hotspot_lyr.dataProvider().addFeatures(h_feats)
                hotspot_lyr.updateExtents()
                h_root = QgsRuleBasedRenderer.Rule(None)
                for cnt_expr, h_lbl, h_hex, h_alpha, ow in (
                    ("\"Cakisma_Sayisi\" >= 3", "High Hotspot (k>=3)", "#9A3412", 125, "0.65"),
                    ("\"Cakisma_Sayisi\" = 2", "Overlap Hotspot (k=2)", "#EA580C", 85, "0.45"),
                ):
                    hsym = QgsFillSymbol.createSimple(
                        {
                            "color": _hex_rgba(h_hex, h_alpha),
                            "outline_color": "#7C2D12",
                            "outline_width": ow,
                            "outline_style": "solid",
                        }
                    )
                    hr = QgsRuleBasedRenderer.Rule(hsym)
                    hr.setFilterExpression(cnt_expr)
                    hr.setLabel(h_lbl)
                    h_root.appendChild(hr)
                hotspot_lyr.setRenderer(QgsRuleBasedRenderer(h_root))
                hotspot_lyr.triggerRepaint()
            else:
                hotspot_lyr = None

    return catch_lyr, hotspot_lyr, focus_lyr


def _line_parts(geom: QgsGeometry) -> List[QgsGeometry]:
    if geom is None or geom.isEmpty():
        return []
    if geom.isMultipart():
        return [p for p in geom.asGeometryCollection() if p.type() == _GEOM_LINE and not p.isEmpty()]
    if geom.type() == _GEOM_LINE:
        return [geom]
    return []


def _build_road_graph(roads_fg: Sequence[Tuple[Any, QgsGeometry]]):
    """Build snapped undirected polyline graph from real road geometries."""
    # Quantize coordinates at 1.0 m precision to unify road junction nodes cleanly
    def _nkey(pt: QgsPointXY) -> Tuple[int, int]:
        return (int(round(pt.x())), int(round(pt.y())))

    node_pts: Dict[Tuple[int, int], QgsPointXY] = {}
    adj: Dict[Tuple[int, int], List[Tuple[Tuple[int, int], float, List[QgsPointXY]]]] = defaultdict(list)

    for _, rg in roads_fg:
        for lp in _line_parts(rg):
            verts = [QgsPointXY(v.x(), v.y()) for v in lp.vertices()]
            if len(verts) < 2:
                continue
            for idx in range(len(verts) - 1):
                p0, p1 = verts[idx], verts[idx + 1]
                k0, k1 = _nkey(p0), _nkey(p1)
                if k0 == k1:
                    continue
                seg_len = math.hypot(p1.x() - p0.x(), p1.y() - p0.y())
                if seg_len <= 0.01:
                    continue
                node_pts.setdefault(k0, p0)
                node_pts.setdefault(k1, p1)
                adj[k0].append((k1, seg_len, [p0, p1]))
                adj[k1].append((k0, seg_len, [p1, p0]))

    return node_pts, adj


def _dijkstra_shortest_path(adj, src_node, targets_set):
    """Run Dijkstra from src_node and return shortest distances & parent edge map."""
    dist: Dict[Tuple[int, int], float] = {src_node: 0.0}
    parent: Dict[Tuple[int, int], Tuple[Tuple[int, int], List[QgsPointXY]]] = {}
    pq: List[Tuple[float, Tuple[int, int]]] = [(0.0, src_node)]
    remaining = set(targets_set) - {src_node}

    while pq and remaining:
        d, u = heapq.heappop(pq)
        if d > dist.get(u, math.inf):
            continue
        if u in remaining:
            remaining.remove(u)
            if not remaining:
                break
        for v, w, seg_pts in adj.get(u, ()):
            nd = d + w
            if nd < dist.get(v, math.inf):
                dist[v] = nd
                parent[v] = (u, seg_pts)
                heapq.heappush(pq, (nd, v))
    return dist, parent


def _reconstruct_path(src_node, dst_node, parent) -> List[QgsPointXY]:
    chunks: List[List[QgsPointXY]] = []
    cur = dst_node
    while cur != src_node:
        if cur not in parent:
            return []
        prev_node, seg_pts = parent[cur]
        chunks.append(seg_pts)
        cur = prev_node
    chunks.reverse()
    poly: List[QgsPointXY] = []
    for seg in chunks:
        if not poly:
            poly.extend(seg)
        else:
            poly.extend(seg[1:])
    return poly


def _build_network_corridors_layer(
    res: Dict[str, Any],
    P: Dict[str, Any],
    zones: Sequence[Dict[str, Any]],
    focus_tiers_lyr: Optional[QgsVectorLayer],
    work_crs: QgsCoordinateReferenceSystem,
    focus_axis: str,
) -> Optional[QgsVectorLayer]:
    """Compute MST corridors strictly along real road_layer edges; never draw fake straight lines."""
    roads_fg = res.get("roads_fg")
    if not roads_fg and P.get("road_layer") is not None:
        roads_fg = _read_layer_geoms(P["road_layer"], work_crs)
    if not roads_fg:
        return None

    node_pts, adj = _build_road_graph(roads_fg)
    if not node_pts or not adj:
        return None

    # Build spatial index over graph nodes for snapping hubs within 300 m
    node_keys = list(node_pts.keys())
    node_idx = QgsSpatialIndex()
    for ni, nk in enumerate(node_keys):
        ft = QgsFeature(ni)
        ft.setGeometry(QgsGeometry.fromPointXY(node_pts[nk]))
        node_idx.addFeature(ft)

    # Collect hub candidates (from focus_tiers if present, plus top prioritized zones)
    hubs: List[Tuple[str, QgsPointXY]] = []
    if focus_tiers_lyr is not None and focus_tiers_lyr.featureCount() > 0:
        tier_feats = sorted(focus_tiers_lyr.getFeatures(), key=lambda f: (int(f["Kademe"] or 4), -int(f["Kume_Sayisi"] or 1)))
        for tf in tier_feats[:8]:
            pt = _safe_point_on_surface(tf.geometry())
            if pt is not None:
                hubs.append((str(tf["Odak_Kodu"] or "O"), pt))

    # Add top zone centroids (prioritized by focus_axis / population / area)
    def _zone_rank(z_item: Dict[str, Any]) -> float:
        pay = z_item.get("pay") or {}
        vuln = _get_zone_vuln(z_item)
        base = float(z_item.get("nufus") or 0.0) + float(z_item.get("area") or 0.0) / 10000.0
        if focus_axis == "resilience":
            base += 5000.0 if vuln.get("genel_kirilganlik") in _VULN_HIGH_TIERS else 0.0
        elif focus_axis == "ecology":
            base += 3000.0 * (float(pay.get("tarim", 0.0)) + float((z_item.get("ext") or {}).get("ekoloji") or 0.0))
        elif focus_axis == "tourism_culture":
            base += 4000.0 * max(float(pay.get("sit", 0.0)), float(pay.get("ticaret", 0.0)))
        elif focus_axis == "facility":
            base += 3500.0 * float(pay.get("donati", 0.0))
        elif focus_axis == "production":
            base += 3500.0 * (float(pay.get("sanayi", 0.0)) + float(pay.get("tarim", 0.0)))
        return base

    for idx_z, z in enumerate(sorted(zones, key=_zone_rank, reverse=True)[:8], 1):
        pt = _safe_point_on_surface(z.get("geom"))
        if pt is not None:
            hubs.append((str(z.get("kod") or f"Z{idx_z}"), pt))
        if len(hubs) >= 12:
            break

    # Snap hubs strictly to nearest graph node within 300 m
    snapped_hubs: List[Tuple[str, Tuple[int, int]]] = []
    seen_nodes = set()
    for label, pt in hubs:
        nn = node_idx.nearestNeighbor(pt, 1)
        if not nn:
            continue
        nk = node_keys[nn[0]]
        npt = node_pts[nk]
        if math.hypot(pt.x() - npt.x(), pt.y() - npt.y()) <= 300.0 and nk not in seen_nodes:
            seen_nodes.add(nk)
            snapped_hubs.append((label, nk))

    if len(snapped_hubs) < 2:
        return None

    # All-pairs shortest road-network paths (disconnected pairs skipped cleanly)
    target_set = {nk for _, nk in snapped_hubs}
    pair_edges: List[Tuple[float, int, int, List[QgsPointXY]]] = []
    for i, (_, src_nk) in enumerate(snapped_hubs):
        dist_map, parent_map = _dijkstra_shortest_path(adj, src_nk, target_set)
        for j in range(i + 1, len(snapped_hubs)):
            dst_nk = snapped_hubs[j][1]
            if dst_nk not in dist_map:
                continue  # disconnected component -> never fake straight line!
            pts_path = _reconstruct_path(src_nk, dst_nk, parent_map)
            if len(pts_path) >= 2:
                pair_edges.append((dist_map[dst_nk], i, j, pts_path))

    if not pair_edges:
        return None

    # Kruskal MST over connected road shortest paths
    pair_edges.sort(key=lambda e: e[0])
    uf_parent = list(range(len(snapped_hubs)))

    def _find(x: int) -> int:
        while uf_parent[x] != x:
            uf_parent[x] = uf_parent[uf_parent[x]]
            x = uf_parent[x]
        return x

    mst_edges: List[Tuple[float, int, int, List[QgsPointXY]]] = []
    deg = defaultdict(int)
    for d_m, u, v, pts_path in pair_edges:
        ru, rv = _find(u), _find(v)
        if ru != rv:
            uf_parent[ru] = rv
            mst_edges.append((d_m, u, v, pts_path))
            deg[u] += 1
            deg[v] += 1

    if not mst_edges:
        return None

    lyr = _make_memory_layer(
        "LineString",
        "Stratejik_Koridorlar",
        work_crs,
        [
            _qfield("Baglanti", "string"),
            _qfield("Koridor_Kademe", "int"),
            _qfield("Uzunluk_m", "double"),
            _qfield("Mesafe_Etiketi", "string"),
        ],
    )
    feats = []
    max_len = max(e[0] for e in mst_edges) or 1.0
    for d_m, u, v, pts_path in mst_edges:
        u_lbl, v_lbl = snapped_hubs[u][0], snapped_hubs[v][0]
        if deg[u] >= 2 and deg[v] >= 2:
            c_tier = 1
        elif d_m >= 0.45 * max_len or deg[u] >= 2 or deg[v] >= 2:
            c_tier = 2
        else:
            c_tier = 3
        dist_lbl = f"{d_m / 1000.0:.2f} km" if d_m >= 1000.0 else f"{d_m:.0f} m"
        f = QgsFeature(lyr.fields())
        f.setGeometry(QgsGeometry.fromPolylineXY(pts_path))
        f.setAttributes([f"{u_lbl} <-> {v_lbl}", c_tier, round(d_m, 1), dist_lbl])
        feats.append(f)

    lyr.dataProvider().addFeatures(feats)
    lyr.updateExtents()

    corridor_hex = (
        SYNTHESIS_PALETTE["tourism_focus"]
        if focus_axis == "tourism_culture"
        else (SYNTHESIS_PALETTE["ecology"] if focus_axis == "ecology" else SYNTHESIS_PALETTE["transport"])
    )
    c_cats = []
    for c_tier, lbl, col_hex, width, lstyle, has_halo in (
        (1, "Tier 1 Spine Corridor", corridor_hex, "1.35", "solid", True),
        (2, "Tier 2 Connector Corridor", "#0284C7", "0.90", "solid", False),
        (3, "Tier 3 Local Network Link", "#475569", "0.55", "dash", False),
    ):
        lsym = QgsLineSymbol.createSimple(
            {"color": col_hex, "width": width, "line_style": lstyle, "capstyle": "round"}
        )
        if has_halo:
            halo_sl = QgsSimpleLineSymbolLayer()
            halo_sl.setColor(QColor(255, 255, 255, 210))
            halo_sl.setWidth(2.3)
            lsym.insertSymbolLayer(0, halo_sl)
        c_cats.append(QgsRendererCategory(c_tier, lsym, lbl))
    lyr.setRenderer(QgsCategorizedSymbolRenderer("Koridor_Kademe", c_cats))

    c_ls = QgsPalLayerSettings()
    c_ls.fieldName = "Mesafe_Etiketi"
    c_ls.isExpression = False
    c_tf = QgsTextFormat()
    c_fnt = QFont("Segoe UI", 8)
    c_fnt.setBold(True)
    c_tf.setFont(c_fnt)
    c_tf.setSize(8.0)
    c_tf.setColor(_qcolor(SYNTHESIS_PALETTE["strategy"]))
    c_buf = QgsTextBufferSettings()
    c_buf.setEnabled(True)
    c_buf.setSize(1.1)
    c_buf.setColor(QColor("#ffffff"))
    c_tf.setBuffer(c_buf)
    c_ls.setFormat(c_tf)
    lyr.setLabelsEnabled(True)
    lyr.setLabeling(QgsVectorLayerSimpleLabeling(c_ls))
    lyr.triggerRepaint()
    return lyr


def _build_external_gateways_layer(
    extras: Sequence[Dict[str, Any]],
    study: Optional[QgsGeometry],
    work_crs: QgsCoordinateReferenceSystem,
) -> Optional[QgsVectorLayer]:
    """Emit external transport gateways ONLY for user-supplied `ulasim_odak` points outside `study`."""
    if study is None or study.isEmpty():
        return None
    gateways: List[Tuple[QgsPointXY, str, float, str]] = []
    for ex in extras:
        if str(ex.get("role") or "").lower() != "ulasim_odak":
            continue
        lyr = ex.get("layer")
        src_name = str(ex.get("name") or "Transport Gateway")
        for idx_f, (feat, geom) in enumerate(_read_layer_geoms(lyr, work_crs), 1):
            dist_m = study.distance(geom)
            if dist_m <= 5.0:
                continue  # Inside study boundary -> handled by focus tiers, not external gateway
            near_bnd_g = study.nearestPoint(geom)
            bnd_pt = _safe_point_on_surface(near_bnd_g)
            ext_pt = _safe_point_on_surface(geom)
            if bnd_pt is None or ext_pt is None:
                continue
            fname = _extract_attr_str(feat, _NAME_FIELD_CANDIDATES) or f"{src_name} #{idx_f}"
            d_lbl = f"{dist_m / 1000.0:.1f} km" if dist_m >= 1000.0 else f"{dist_m:.0f} m"
            gateways.append((bnd_pt, fname, round(dist_m, 1), f"{fname} -> {d_lbl}"))

    if not gateways:
        return None

    lyr = _make_memory_layer(
        "Point",
        "Dis_Ulasim_Akslari",
        work_crs,
        [
            _qfield("Ad", "string"),
            _qfield("Mesafe_m", "double"),
            _qfield("Mesafe_Etiketi", "string"),
        ],
    )
    feats = []
    for pt, ad, d_m, d_lbl in gateways:
        f = QgsFeature(lyr.fields())
        f.setGeometry(QgsGeometry.fromPointXY(pt))
        f.setAttributes([ad, d_m, d_lbl])
        feats.append(f)
    lyr.dataProvider().addFeatures(feats)
    lyr.updateExtents()

    gsym = QgsMarkerSymbol.createSimple(
        {
            "name": "diamond",
            "color": SYNTHESIS_PALETTE["transport"],
            "outline_color": "#ffffff",
            "outline_width": "0.6",
            "size": "5.0",
        }
    )
    lyr.setRenderer(QgsSingleSymbolRenderer(gsym))
    g_ls = QgsPalLayerSettings()
    g_ls.fieldName = "Mesafe_Etiketi"
    g_ls.isExpression = False
    g_tf = QgsTextFormat()
    g_fnt = QFont("Segoe UI", 8)
    g_fnt.setBold(True)
    g_tf.setFont(g_fnt)
    g_tf.setSize(8.0)
    g_tf.setColor(_qcolor(SYNTHESIS_PALETTE["transport"]))
    g_buf = QgsTextBufferSettings()
    g_buf.setEnabled(True)
    g_buf.setSize(1.1)
    g_buf.setColor(QColor("#ffffff"))
    g_tf.setBuffer(g_buf)
    g_ls.setFormat(g_tf)
    lyr.setLabelsEnabled(True)
    lyr.setLabeling(QgsVectorLayerSimpleLabeling(g_ls))
    lyr.triggerRepaint()
    return lyr


def build_synthesis_overlay_layers(
    res: Optional[Dict[str, Any]],
    P: Optional[Dict[str, Any]],
    opts: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Generate real metric strategic synthesis overlays strictly from res & user P layers."""
    res_d = res or {}
    p_d = P or {}
    opt = opts or {}

    zones = res_d.get("zones") or []
    work_crs = res_d.get("work_crs") or p_d.get("work_crs")
    study = res_d.get("study")
    if (study is None or study.isEmpty()) and zones:
        valid_g = [z["geom"] for z in zones if z.get("geom") and not z["geom"].isEmpty()]
        if valid_g:
            study = QgsGeometry.unaryUnion(valid_g)

    extras = p_d.get("extras") or []
    focus_axis = str(opt.get("focus_axis") or p_d.get("focus_axis") or "balanced")

    want_mask = opt.get("exterior_mask", opt.get("enable_exterior_mask", True))
    want_vuln = opt.get("vuln_hatch", opt.get("enable_vulnerability", True))
    want_breach = opt.get("critical_breaches", opt.get("vuln_hatch", opt.get("enable_vulnerability", True)))
    want_catch = opt.get("catchments", opt.get("enable_catchments", True))
    want_hotspots = opt.get("hotspots", opt.get("catchments", opt.get("enable_catchments", True)))
    want_tiers = opt.get("focus_tiers", opt.get("catchments", opt.get("enable_catchments", True)))
    want_corridors = opt.get("corridors", opt.get("enable_corridors", True))
    want_gateways = opt.get("external_gateways", opt.get("corridors", opt.get("enable_corridors", True)))

    out: Dict[str, Any] = {
        "exterior_mask": None,
        "vuln_hatch": None,
        "critical_breaches": None,
        "catchments": None,
        "hotspots": None,
        "focus_tiers": None,
        "corridors": None,
        "external_gateways": None,
        "layers_meta": [],
    }
    meta: List[Dict[str, Any]] = []

    def _rec(key: str, lyr_name: str, lyr_obj: Optional[QgsVectorLayer], role_desc: str, reason: str) -> None:
        out[key] = lyr_obj
        cnt = int(lyr_obj.featureCount()) if lyr_obj is not None else 0
        meta.append(
            {
                "key": key,
                "layer_name": lyr_name,
                "status": "Generated" if (lyr_obj is not None and cnt > 0) else "Skipped",
                "feature_count": cnt,
                "role": role_desc,
                "reason": reason,
            }
        )

    if work_crs is None or not work_crs.isValid() or work_crs.isGeographic():
        for k, nm in (
            ("exterior_mask", "Calisma_Alani_Maskesi"),
            ("vuln_hatch", "Afet_Kirilganlik_Tarama"),
            ("critical_breaches", "Kritik_Esik_Uyarilari"),
            ("catchments", "Odak_Cekim_Alanlari"),
            ("hotspots", "Odak_Cekim_Cakisma_Alanlari"),
            ("focus_tiers", "Odak_Kademeleri"),
            ("corridors", "Stratejik_Koridorlar"),
            ("external_gateways", "Dis_Ulasim_Akslari"),
        ):
            _rec(k, nm, None, "Strategic Overlay", "Requires projected metric CRS (EPSG:5253).")
        out["layers_meta"] = meta
        return out

    # 1. Exterior Mask
    if want_mask:
        mask_lyr = _build_exterior_mask_layer(study, work_crs)
        _rec("exterior_mask", "Calisma_Alani_Maskesi", mask_lyr, "Exterior Focus Mask", "Inverted mask around study boundary." if mask_lyr else "No study boundary geometry.")
    else:
        _rec("exterior_mask", "Calisma_Alani_Maskesi", None, "Exterior Focus Mask", "Disabled by user option.")

    # 2. Vulnerability Hatch
    if want_vuln:
        vh_lyr = _build_vulnerability_hatch_layer(zones, work_crs)
        _rec("vuln_hatch", "Afet_Kirilganlik_Tarama", vh_lyr, "Multi-Hazard Hatch Overlay", "Non-occluding E-S/AC vulnerability hatch." if vh_lyr else "No zones supplied.")
    else:
        _rec("vuln_hatch", "Afet_Kirilganlik_Tarama", None, "Multi-Hazard Hatch Overlay", "Disabled by user option.")

    # 3. Critical Breaches
    if want_breach:
        cb_lyr = _build_critical_breaches_layer(zones, work_crs)
        _rec("critical_breaches", "Kritik_Esik_Uyarilari", cb_lyr, "Threshold Breach Markers", "Real measured statutory/hazard exceedances." if cb_lyr else "No zone breached critical thresholds.")
    else:
        _rec("critical_breaches", "Kritik_Esik_Uyarilari", None, "Threshold Breach Markers", "Disabled by user option.")

    # 4. Focus Tiers, Catchments & Overlap Hotspots (strictly only when focus/facility extras exist)
    if want_catch or want_hotspots or want_tiers:
        c_lyr, h_lyr, f_lyr = _build_focus_and_catchment_layers(extras, study, work_crs, focus_axis)
        _rec("catchments", "Odak_Cekim_Alanlari", c_lyr if want_catch else None, "250/500/1000m Catchments", "Metric catchments from supplied focus/facility layers." if (c_lyr and want_catch) else "No facility/focus extras supplied or disabled.")
        _rec("hotspots", "Odak_Cekim_Cakisma_Alanlari", h_lyr if want_hotspots else None, "Catchment Overlap Hotspots", "Exact GEOS intersection hotspots (k>=2)." if (h_lyr and want_hotspots) else "No overlapping 500m catchments or disabled.")
        _rec("focus_tiers", "Odak_Kademeleri", f_lyr if want_tiers else None, "4-Tier Focus Clusters", "150m metric point clustering into Tier 1..4." if (f_lyr and want_tiers) else "No facility/focus extras supplied or disabled.")
    else:
        _rec("catchments", "Odak_Cekim_Alanlari", None, "250/500/1000m Catchments", "Disabled by user option.")
        _rec("hotspots", "Odak_Cekim_Cakisma_Alanlari", None, "Catchment Overlap Hotspots", "Disabled by user option.")
        _rec("focus_tiers", "Odak_Kademeleri", None, "4-Tier Focus Clusters", "Disabled by user option.")

    # 5. Network-Grounded Road Corridors
    if want_corridors:
        cor_lyr = _build_network_corridors_layer(res_d, p_d, zones, out["focus_tiers"], work_crs, focus_axis)
        _rec("corridors", "Stratejik_Koridorlar", cor_lyr, "Road-Network MST Corridors", "Shortest-path MST along real road_layer edges." if cor_lyr else "No connected road_layer edges between hubs.")
    else:
        _rec("corridors", "Stratejik_Koridorlar", None, "Road-Network MST Corridors", "Disabled by user option.")

    # 6. External Transport Gateways (strictly only when user supplies external ulasim_odak outside study)
    if want_gateways:
        gw_lyr = _build_external_gateways_layer(extras, study, work_crs)
        _rec("external_gateways", "Dis_Ulasim_Akslari", gw_lyr, "External Transport Gateways", "Real external ulasim_odak points outside study boundary." if gw_lyr else "No external ulasim_odak features outside study.")
    else:
        _rec("external_gateways", "Dis_Ulasim_Akslari", None, "External Transport Gateways", "Disabled by user option.")

    out["layers_meta"] = meta
    return out


# ---------------------------------------------------------------------------
# 4. Grouped LayerTree Registration (Preserves mapLayers().values())
# ---------------------------------------------------------------------------
def add_layers_to_project_grouped(
    proj: Optional[QgsProject],
    ordered_layers: Sequence[Optional[QgsMapLayer]],
    group_name: str = "Spatial Strategy Synthesis",
    replace_group: bool = True,
):
    """Register layers into a top-level QgsLayerTreeGroup while keeping proj.mapLayers() populated."""
    project = proj or QgsProject.instance()
    root = project.layerTreeRoot()
    valid_layers = [lyr for lyr in (ordered_layers or []) if lyr is not None]
    keep_ids = {lyr.id() for lyr in valid_layers}

    existing = root.findGroup(group_name)
    if replace_group and existing is not None:
        stale_ids = [
            node.layerId()
            for node in existing.findLayers()
            if node.layerId() and node.layerId() not in keep_ids
        ]
        if stale_ids:
            project.removeMapLayers(stale_ids)
        root.removeChildNode(existing)
        existing = None

    group = existing if existing is not None else root.insertGroup(0, group_name)
    for lyr in valid_layers:
        if project.mapLayer(lyr.id()) is None:
            project.addMapLayer(lyr, False)
        if group.findLayer(lyr.id()) is None:
            group.addLayer(lyr)
    return group


# ---------------------------------------------------------------------------
# 5. QGIS Print Layout (`QgsPrintLayout`) & High-Res Export
# ---------------------------------------------------------------------------
_LAYOUT_LABELS: Dict[str, Dict[str, str]] = {
    "en": {
        "default_title": "REGIONAL / URBAN SPATIAL STRATEGY SYNTHESIS PLATE",
        "inset_title": "ANALYTICAL INSET: PRIORITY / HIGH-RISK FOCUS",
        "legend_title": "CARTOGRAPHIC LEGEND",
        "kunye_title": "PLATE METADATA (KÜNYE)",
        "axis": "Focus Axis",
        "scale": "Map Scale",
        "crs": "CRS Standard",
        "date": "Date",
        "zones": "Zones",
        "built_lbl": "built",
        "area": "Total Area",
        "pop": "Population",
        "bldg": "Buildings",
        "swot_title": "DATA-DRIVEN SWOT SYNTHESIS",
        "gaps_prefix": "DATA GAPS",
        "none_lbl": "None",
        "table_title": "ZONE SYNTHESIS MATRIX (1-TO-1 SYNCED)",
        "col_code": "Code",
        "col_char": "Dominant Character & Strategy",
        "col_vuln": "Seismic / Flood",
        "more_zones": "... +{n} additional zones documented in Attribute Table & Excel Workbook.",
    },
    "tr": {
        "default_title": "MEKÂNSAL STRATEJİ VE BÖLGELEME SENTEZ PAFTASI",
        "inset_title": "ANALİTİK DETAY: ÖNCELİKLİ / YÜKSEK RİSK ODAĞI",
        "legend_title": "KARTOGRAFİK LEJANT",
        "kunye_title": "PAFTA KÜNYESİ",
        "axis": "Odak Ekseni",
        "scale": "Harita Ölçeği",
        "crs": "CRS Standardı",
        "date": "Tarih",
        "zones": "Alt Bölge",
        "built_lbl": "yapılı",
        "area": "Toplam Alan",
        "pop": "Nüfus",
        "bldg": "Yapı Sayısı",
        "swot_title": "VERİYE DAYALI GZFT / SWOT SENTEZİ",
        "gaps_prefix": "VERİ BOŞLUKLARI",
        "none_lbl": "Yok",
        "table_title": "BÖLGE SENTEZ TABLOSU (1-1 EŞLEŞMELİ)",
        "col_code": "Kod",
        "col_char": "Baskın Karakter ve Strateji",
        "col_vuln": "Deprem / Sel",
        "more_zones": "... +{n} ilave bölge Öznitelik Tablosu ve Excel Çalışma Kitabındadır.",
    },
    "zh": {
        "default_title": "区域与城市空间战略综合图版",
        "inset_title": "分析放大图：高风险/重点片区",
        "legend_title": "制图图例",
        "kunye_title": "图幅信息",
        "axis": "战略主轴",
        "scale": "比例尺",
        "crs": "坐标标准",
        "date": "日期",
        "zones": "分区数",
        "built_lbl": "已建",
        "area": "总面积",
        "pop": "人口",
        "bldg": "建筑数",
        "swot_title": "数据驱动 SWOT 综合研判",
        "gaps_prefix": "数据缺口",
        "none_lbl": "无",
        "table_title": "分区战略矩阵（一对一同步）",
        "col_code": "编码",
        "col_char": "主导特征与战略决策",
        "col_vuln": "地震 / 洪涝",
        "more_zones": "... 其余 {n} 个分区详见属性表与 Excel 报告。",
    },
    "es": {
        "default_title": "LÁMINA DE SÍNTESIS ESTRATÉGICA ESPACIAL Y ZONIFICACIÓN",
        "inset_title": "DETALLE ANALÍTICO: FOCO PRIORITARIO / ALTO RIESGO",
        "legend_title": "LEYENDA CARTOGRÁFICA",
        "kunye_title": "CUADRO DE ROTULACIÓN",
        "axis": "Eje Focal",
        "scale": "Escala",
        "crs": "SRC Estándar",
        "date": "Fecha",
        "zones": "Zonas",
        "built_lbl": "edificadas",
        "area": "Área Total",
        "pop": "Población",
        "bldg": "Edificios",
        "swot_title": "SÍNTESIS DAFO BASADA EN DATOS",
        "gaps_prefix": "BRECHAS DE DATOS",
        "none_lbl": "Ninguna",
        "table_title": "MATRIZ DE SÍNTESIS POR ZONA (SINCRONIZADA 1:1)",
        "col_code": "Cód.",
        "col_char": "Carácter Dominante y Estrategia",
        "col_vuln": "Sismo / Inund.",
        "more_zones": "... +{n} zonas adicionales en Tabla de Atributos y libro Excel.",
    },
}


def _choose_nice_scalebar_segment_m(extent_width_m: float) -> float:
    if extent_width_m <= 0:
        return 100.0
    target = extent_width_m * 0.08
    steps = (10, 25, 50, 100, 200, 250, 500, 1000, 2000, 2500, 5000, 10000, 25000, 50000)
    return float(min(steps, key=lambda s: abs(s - target)))


def _is_duplicate_quick_layer(lyr: QgsMapLayer, has_full_zone: bool) -> bool:
    nm = lyr.name()
    return bool(has_full_zone and (nm.startswith("Alt_Bolgeler_Hizli_Ozet") or nm.startswith("Hazir_Bolgeler_Hizli_Ozet") or "Hizli_Ozet" in nm))


def _resolve_map_layers(proj: QgsProject, layer_ids_for_map: Optional[Sequence[Any]]) -> List[QgsMapLayer]:
    if layer_ids_for_map:
        out = []
        for item in layer_ids_for_map:
            if isinstance(item, QgsMapLayer):
                out.append(item)
            elif isinstance(item, str):
                lyr = proj.mapLayer(item)
                if lyr is not None:
                    out.append(lyr)
        if out:
            has_full = any(
                (l.name().startswith("Alt_Bolgeler_") or l.name().startswith("Hazir_Bolgeler_Analizi_"))
                and "Hizli_Ozet" not in l.name()
                for l in out
            )
            return [l for l in out if not _is_duplicate_quick_layer(l, has_full)]

    # Auto-resolve project layers in clean cartographic priority order
    priority_prefixes = [
        "Kritik_Esik_Uyarilari",
        "Odak_Kademeleri",
        "Dis_Ulasim_Akslari",
        "Stratejik_Koridorlar",
        "Odak_Cekim_Cakisma_Alanlari",
        "Afet_Kirilganlik_Tarama",
        "Odak_Cekim_Alanlari",
        "Alt_Bolgeler_",
        "Hazir_Bolgeler_Analizi_",
        "Imar_Adasi_Hucreleri",
        "Calisma_Alani_Maskesi",
    ]
    all_lyrs = list(proj.mapLayers().values())
    has_full_zone = any(
        (l.name().startswith("Alt_Bolgeler_") or l.name().startswith("Hazir_Bolgeler_Analizi_"))
        and "Hizli_Ozet" not in l.name()
        for l in all_lyrs
    )

    def _sort_key(lyr: QgsMapLayer) -> Tuple[int, str]:
        nm = lyr.name()
        for idx, pref in enumerate(priority_prefixes):
            if nm.startswith(pref):
                return (idx, nm)
        return (len(priority_prefixes) + (1 if lyr.type() == _LAYER_TYPE_RASTER else 0), nm)

    return [lyr for lyr in sorted(all_lyrs, key=_sort_key) if not _is_duplicate_quick_layer(lyr, has_full_zone)]


def _compute_zones_extent(
    zones: Sequence[Dict[str, Any]],
    res: Optional[Dict[str, Any]],
    map_layers: Sequence[QgsMapLayer],
) -> QgsRectangle:
    rect = QgsRectangle()
    rect.setNull()
    for z in zones:
        g = z.get("geom")
        if g and not g.isEmpty():
            rect.combineExtentWith(g.boundingBox())
    if rect.isNull() and res and res.get("study") and not res["study"].isEmpty():
        rect = QgsRectangle(res["study"].boundingBox())
    if rect.isNull():
        for lyr in map_layers:
            if not lyr.extent().isNull():
                rect.combineExtentWith(lyr.extent())
    if rect.isNull() or rect.width() <= 0 or rect.height() <= 0:
        rect = QgsRectangle(500000.0, 4200000.0, 501000.0, 4201000.0)
    rect.scale(1.10)
    return rect


def _compute_inset_extent(zones: Sequence[Dict[str, Any]], main_rect: QgsRectangle) -> QgsRectangle:
    if not zones:
        r_def = QgsRectangle(main_rect)
        r_def.scale(0.38)
        return r_def

    def _priority_score(z: Dict[str, Any]) -> Tuple[int, float]:
        vuln = _get_zone_vuln(z)
        vg = str(vuln.get("genel_kirilganlik") or "")
        ext = z.get("ext") or {}
        ext_min = z.get("ext_min") or {}
        fay_v = ext_min.get("fay") if ext_min.get("fay") is not None else ext.get("fay")
        tier_rank = 3 if vg == "Çok Yüksek" else (2 if vg == "Yüksek" else (1 if vg == "Orta" else 0))
        if fay_v is not None and float(fay_v) <= 100.0:
            tier_rank += 2
        return (tier_rank, float(z.get("nufus") or 0.0))

    top_z = max(zones, key=_priority_score)
    g = top_z.get("geom")
    if g is None or g.isEmpty():
        r_def = QgsRectangle(main_rect)
        r_def.scale(0.38)
        return r_def
    inset_r = QgsRectangle(g.boundingBox())
    inset_r.scale(1.38)
    return inset_r


def _make_text_format(size_pt: float, hex_color: str = "#0F172A", bold: bool = False) -> QgsTextFormat:
    tf = QgsTextFormat()
    fnt = QFont("Segoe UI", max(5, int(round(size_pt))))
    fnt.setBold(bool(bold))
    tf.setFont(fnt)
    tf.setSize(float(size_pt))
    tf.setColor(_qcolor(hex_color))
    return tf


def _add_font_box(
    layout: QgsPrintLayout,
    x_mm: float,
    y_mm: float,
    w_mm: float,
    h_mm: float,
    text: str,
    size_pt: float = 7.5,
    bold: bool = False,
    text_hex: str = "#0F172A",
    border_hex: Optional[str] = "#CBD5E1",
    bg_hex: Optional[str] = "#FFFFFF",
    margin_x: float = 2.0,
    margin_y: float = 1.6,
    h_align: Any = _ALIGN_LEFT,
    v_align: Any = _ALIGN_TOP,
) -> QgsLayoutItemLabel:
    lbl = QgsLayoutItemLabel(layout)
    lbl.setMode(_LABEL_MODE_FONT)
    lbl.setTextFormat(_make_text_format(size_pt, text_hex, bold=bold))
    lbl.setText(text)
    lbl.attemptMove(QgsLayoutPoint(x_mm, y_mm, _LAYOUT_MM))
    lbl.attemptResize(QgsLayoutSize(w_mm, h_mm, _LAYOUT_MM))
    if bg_hex is not None:
        lbl.setBackgroundEnabled(True)
        lbl.setBackgroundColor(QColor(bg_hex))
    else:
        lbl.setBackgroundEnabled(False)
    if border_hex is not None:
        lbl.setFrameEnabled(True)
        lbl.setFrameStrokeColor(_qcolor(border_hex))
        lbl.setFrameStrokeWidth(QgsLayoutMeasurement(0.3, _LAYOUT_MM))
    else:
        lbl.setFrameEnabled(False)
    lbl.setMarginX(margin_x)
    lbl.setMarginY(margin_y)
    lbl.setHAlign(h_align)
    lbl.setVAlign(v_align)
    layout.addLayoutItem(lbl)
    return lbl


def _add_swot_panel(
    layout: QgsPrintLayout,
    x_mm: float,
    y_mm: float,
    w_mm: float,
    h_mm: float,
    swot: Dict[str, Any],
    L: Dict[str, str],
    compact: bool = False,
) -> None:
    """Render crisp vector SWOT / GZFT panel using QgsTextFormat (zero HTML font glitches)."""
    # Container card
    card = QgsLayoutItemShape(layout)
    card.setShapeType(_SHAPE_RECT)
    card.attemptMove(QgsLayoutPoint(x_mm, y_mm, _LAYOUT_MM))
    card.attemptResize(QgsLayoutSize(w_mm, h_mm, _LAYOUT_MM))
    card.setSymbol(QgsFillSymbol.createSimple({"color": "#FFFFFF", "outline_color": "#CBD5E1", "outline_width": "0.3"}))
    layout.addLayoutItem(card)

    hdr_h = 6.0 if compact else 8.0
    _add_font_box(
        layout, x_mm, y_mm, w_mm, hdr_h,
        L["swot_title"], size_pt=7.5 if compact else 9.5, bold=True,
        text_hex="#FFFFFF", border_hex="#0F172A", bg_hex="#0F172A",
        margin_x=2.2, margin_y=1.1, v_align=_ALIGN_VCENTER,
    )

    cap = 2 if compact else 3
    quads = [
        ("S", "#15803D", "#F0FDF4", swot.get("strengths") or []),
        ("W", "#D97706", "#FFFBEB", swot.get("weaknesses") or []),
        ("O", "#0284C7", "#F0F9FF", swot.get("opportunities") or []),
        ("T", "#DC2626", "#FEF2F2", swot.get("threats") or []),
    ]
    gap_h = 10.0 if compact else 14.5
    body_h = max(20.0, h_mm - hdr_h - gap_h - 2.4)
    q_h = body_h / 4.0
    cur_y = y_mm + hdr_h + 1.2
    max_chars = 170 if compact else 245

    for badge, col_hex, tint_hex, items in quads:
        # Left color badge strip
        badge_w = 6.0 if compact else 8.0
        _add_font_box(
            layout, x_mm + 1.5, cur_y + 0.6, badge_w, q_h - 1.2,
            badge, size_pt=8.0 if compact else 10.5, bold=True,
            text_hex="#FFFFFF", border_hex=col_hex, bg_hex=col_hex,
            margin_x=0.5, margin_y=0.5, h_align=_ALIGN_CENTER, v_align=_ALIGN_VCENTER,
        )
        lines = [f"• {_clip_words(it, max_chars)}" for it in list(items)[:cap]]
        _add_font_box(
            layout, x_mm + 1.5 + badge_w + 0.8, cur_y + 0.6, w_mm - badge_w - 3.8, q_h - 1.2,
            "\n".join(lines), size_pt=5.5 if compact else 7.4, bold=False,
            text_hex="#0F172A", border_hex=None, bg_hex=tint_hex,
            margin_x=1.6, margin_y=0.9,
        )
        cur_y += q_h

    gap_txt = "; ".join(swot.get("data_gaps") or []) or L["none_lbl"]
    max_g = 230 if compact else 330
    gap_txt = _clip_words(gap_txt, max_g)
    _add_font_box(
        layout, x_mm + 1.4, y_mm + h_mm - gap_h, w_mm - 2.8, gap_h - 1.0,
        f"{L['gaps_prefix']}: {gap_txt}", size_pt=5.4 if compact else 6.8, bold=False,
        text_hex="#475569", border_hex="#E2E8F0", bg_hex="#F8FAFC",
        margin_x=1.5, margin_y=0.8,
    )


def _add_zone_table_panel(
    layout: QgsPrintLayout,
    x_mm: float,
    y_mm: float,
    w_mm: float,
    h_mm: float,
    zones: Sequence[Dict[str, Any]],
    L: Dict[str, str],
    lang: str = "en",
    max_rows: int = 7,
    compact: bool = False,
) -> None:
    """Render 1-to-1 Zone Synthesis Matrix using native QgsLayoutItemTextTable + QgsTextFormat."""
    card = QgsLayoutItemShape(layout)
    card.setShapeType(_SHAPE_RECT)
    card.attemptMove(QgsLayoutPoint(x_mm, y_mm, _LAYOUT_MM))
    card.attemptResize(QgsLayoutSize(w_mm, h_mm, _LAYOUT_MM))
    card.setSymbol(QgsFillSymbol.createSimple({"color": "#FFFFFF", "outline_color": "#CBD5E1", "outline_width": "0.3"}))
    layout.addLayoutItem(card)

    hdr_h = 6.0 if compact else 8.0
    _add_font_box(
        layout, x_mm, y_mm, w_mm, hdr_h,
        L["table_title"], size_pt=7.5 if compact else 9.5, bold=True,
        text_hex="#FFFFFF", border_hex="#0F172A", bg_hex="#0F172A",
        margin_x=2.2, margin_y=1.1, v_align=_ALIGN_VCENTER,
    )

    foot_h = 6.0 if len(zones) > max_rows else 0.0
    tbl_y = y_mm + hdr_h + 1.2
    tbl_h = max(20.0, h_mm - hdr_h - foot_h - 2.4)

    tbl = QgsLayoutItemTextTable(layout)
    cols = []
    c1 = QgsLayoutTableColumn(L["col_code"])
    c1.setWidth(w_mm * 0.11)
    c2 = QgsLayoutTableColumn(L["col_char"])
    c2.setWidth(w_mm * 0.65)
    c3 = QgsLayoutTableColumn(L["col_vuln"])
    c3.setWidth(w_mm * 0.21)
    cols.extend([c1, c2, c3])
    tbl.setColumns(cols)

    rows = []
    for idx, z in enumerate(zones[:max_rows]):
        kod = str(z.get("kod") or f"Z{idx + 1}")
        kar = _clip_words(z.get("karakter") or "-", 42 if compact else 60)
        sent = _clip_words(z.get("pafta_lejant") or z.get("kisa_ozet") or "", 68 if compact else 102)
        vuln = _get_zone_vuln(z)
        d_tr = _localize_vuln_tier(str(vuln.get("deprem_kirilganlik") or "-"), lang)
        s_tr = _localize_vuln_tier(str(vuln.get("sel_kirilganlik") or "-"), lang)
        rows.append([kod, f"{kar} — {sent}", f"{d_tr} / {s_tr}"])

    tbl.setContents(rows)
    tbl.setHeaderMode(_TBL_HEADER_FIRST)
    tbl.setWrapBehavior(_TBL_WRAP_TEXT)
    tbl.setResizeMode(_TBL_RESIZE_EXIST)
    tbl.setHeaderTextFormat(_make_text_format(6.0 if compact else 7.6, "#0F172A", bold=True))
    tbl.setContentTextFormat(_make_text_format(5.5 if compact else 7.0, "#1E293B", bold=False))
    tbl.setCellMargin(0.9)
    tbl.setShowGrid(True)
    tbl.setGridColor(_qcolor("#CBD5E1"))
    tbl.setGridStrokeWidth(0.2)
    tbl.setBackgroundColor(QColor("#F8FAFC"))

    frame = QgsLayoutFrame(layout, tbl)
    frame.attemptMove(QgsLayoutPoint(x_mm + 1.2, tbl_y, _LAYOUT_MM))
    frame.attemptResize(QgsLayoutSize(w_mm - 2.4, tbl_h, _LAYOUT_MM))
    tbl.addFrame(frame)
    layout.addMultiFrame(tbl)

    if foot_h > 0:
        _add_font_box(
            layout, x_mm + 1.2, y_mm + h_mm - foot_h, w_mm - 2.4, foot_h - 0.5,
            L["more_zones"].format(n=len(zones) - max_rows),
            size_pt=5.4 if compact else 6.8, bold=False,
            text_hex="#475569", border_hex=None, bg_hex="#F8FAFC",
            margin_x=1.2, margin_y=0.6,
        )


def create_synthesis_print_layout(
    proj: Optional[QgsProject],
    zones: Optional[Sequence[Dict[str, Any]]],
    res: Optional[Dict[str, Any]] = None,
    P: Optional[Dict[str, Any]] = None,
    paper_format: str = "A3_LANDSCAPE",
    title: str = "",
    focus_axis: str = "balanced",
    lang: str = "en",
    export_pdf_path: Optional[str] = None,
    export_png_path: Optional[str] = None,
    export_qpt_path: Optional[str] = None,
    layer_ids_for_map: Optional[Sequence[Any]] = None,
) -> Dict[str, Any]:
    """Assemble a publication-grade A3 Landscape or A1 Portrait QGIS Print Layout & optionally export."""
    _ensure_offscreen_fonts()
    project = proj or QgsProject.instance()
    zlist = list(zones or [])
    res_d = res or {}
    p_d = P or {}
    loc = lang if lang in _LAYOUT_LABELS else "en"
    L = _LAYOUT_LABELS[loc]

    fmt_u = str(paper_format or "A3_LANDSCAPE").upper().strip()
    is_a1 = "A1" in fmt_u or "PORTRAIT" in fmt_u
    fmt_norm = "A1_PORTRAIT" if is_a1 else "A3_LANDSCAPE"
    page_w, page_h = (594.0, 841.0) if is_a1 else (420.0, 297.0)
    orient = _ORIENT_PORTRAIT if is_a1 else _ORIENT_LANDSCAPE

    work_crs = res_d.get("work_crs") or p_d.get("work_crs")
    if work_crs is None or not work_crs.isValid():
        work_crs = QgsCoordinateReferenceSystem("EPSG:5253")

    swot = build_swot_synthesis(zlist, P=p_d, lang=loc)
    snap = swot["metrics_snapshot"]

    mgr = project.layoutManager()
    layout_name = f"AkilliBolgeleme_Synthesis_{fmt_norm}"
    old_lay = mgr.layoutByName(layout_name)
    if old_lay is not None:
        mgr.removeLayout(old_lay)

    layout = QgsPrintLayout(project)
    layout.initializeDefaults()
    layout.setName(layout_name)
    page = layout.pageCollection().page(0)
    page.setPageSize(QgsLayoutSize(page_w, page_h, _LAYOUT_MM))
    # Verify orientation explicitly when supported
    if hasattr(page, "orientation") and page.orientation() != orient:
        page.setPageSize(QgsLayoutSize(page_w, page_h, _LAYOUT_MM))

    map_layers = _resolve_map_layers(project, layer_ids_for_map)
    main_rect = _compute_zones_extent(zlist, res_d, map_layers)
    inset_rect = _compute_inset_extent(zlist, main_rect)

    plate_title = (title or "").strip() or L["default_title"]
    axis_text = _focus_label(focus_axis, loc)
    crs_label = work_crs.authid() if work_crs and work_crs.isValid() else "EPSG:5253"
    date_str = datetime.date.today().isoformat()

    # Geometry blueprint per paper preset (zero overlap guarantees)
    if not is_a1:
        # A3 Landscape (420 x 297 mm)
        hdr_box = (8.0, 7.0, 404.0, 14.0)
        map_box = (8.0, 23.0, 254.0, 198.0)
        inset_box = (8.0, 223.0, 82.0, 66.0)
        legend_box = (92.0, 223.0, 170.0, 66.0)
        kunye_box = (266.0, 23.0, 146.0, 36.0)
        swot_box = (266.0, 61.0, 146.0, 108.0)
        table_box = (266.0, 171.0, 146.0, 118.0)
        max_table_rows = 7
        compact_cards = True
    else:
        # A1 Portrait (594 x 841 mm)
        hdr_box = (12.0, 12.0, 570.0, 22.0)
        map_box = (12.0, 38.0, 570.0, 456.0)
        inset_box = (12.0, 500.0, 146.0, 138.0)
        legend_box = (162.0, 500.0, 244.0, 138.0)
        kunye_box = (410.0, 500.0, 172.0, 138.0)
        swot_box = (12.0, 644.0, 244.0, 185.0)
        table_box = (260.0, 644.0, 322.0, 185.0)
        max_table_rows = 12
        compact_cards = False

    # 1. Outer neatline border
    outer_frame = QgsLayoutItemShape(layout)
    outer_frame.setShapeType(_SHAPE_RECT)
    outer_frame.attemptMove(QgsLayoutPoint(4.0, 4.0, _LAYOUT_MM))
    outer_frame.attemptResize(QgsLayoutSize(page_w - 8.0, page_h - 8.0, _LAYOUT_MM))
    frame_sym = QgsFillSymbol.createSimple({"color": "0,0,0,0", "outline_color": "#0F172A", "outline_width": "0.5"})
    outer_frame.setSymbol(frame_sym)
    layout.addLayoutItem(outer_frame)

    # 2. Header Banner
    hx, hy, hw, hh = hdr_box
    hdr_txt = f"{plate_title}\n{L['axis']}: {axis_text}  |  {L['crs']}: {crs_label}  |  {date_str}"
    _add_font_box(
        layout, hx, hy, hw, hh, hdr_txt,
        size_pt=10.5 if not is_a1 else 15.0, bold=True,
        text_hex="#FFFFFF", border_hex="#0F172A", bg_hex="#0F172A",
        margin_x=3.0, margin_y=1.4, v_align=_ALIGN_VCENTER,
    )

    # 3. Main Map Item
    mx, my, mw, mh = map_box
    map_main = QgsLayoutItemMap(layout)
    map_main.setId("main_map")
    map_main.attemptMove(QgsLayoutPoint(mx, my, _LAYOUT_MM))
    map_main.attemptResize(QgsLayoutSize(mw, mh, _LAYOUT_MM))
    map_main.setCrs(work_crs)
    if map_layers:
        map_main.setLayers(map_layers)
        map_main.setKeepLayerSet(True)
    map_main.zoomToExtent(main_rect)
    map_main.setFrameEnabled(True)
    map_main.setFrameStrokeColor(_qcolor("#0F172A"))
    map_main.setFrameStrokeWidth(QgsLayoutMeasurement(0.45, _LAYOUT_MM))
    layout.addLayoutItem(map_main)

    # 4. North Arrow Picture inside top-right of main map
    na_svg = Path(__file__).resolve().parent / "north_arrow.svg"
    if na_svg.exists():
        na_sz = 14.0 if not is_a1 else 22.0
        pic = QgsLayoutItemPicture(layout)
        pic.setMode(_PIC_FORMAT_SVG)
        pic.setPicturePath(str(na_svg))
        pic.setResizeMode(_PIC_RESIZE_ZOOM)
        pic.attemptMove(QgsLayoutPoint(mx + mw - na_sz - 4.0, my + 4.0, _LAYOUT_MM))
        pic.attemptResize(QgsLayoutSize(na_sz, na_sz, _LAYOUT_MM))
        layout.addLayoutItem(pic)

    # 5. Metric Scale Bar inside bottom-left of main map
    sb = QgsLayoutItemScaleBar(layout)
    sb.setLinkedMap(map_main)
    sb.setStyle("Double Box")
    sb.setUnits(_DIST_METERS)
    sb.setUnitLabel("m")
    sb.setMapUnitsPerScaleBarUnit(1.0)
    sb.setUnitsPerSegment(_choose_nice_scalebar_segment_m(main_rect.width()))
    sb.setNumberOfSegments(3)
    sb.setNumberOfSegmentsLeft(0)
    sb_w = 56.0 if not is_a1 else 84.0
    sb_h = 11.0 if not is_a1 else 15.0
    sb.attemptMove(QgsLayoutPoint(mx + 4.0, my + mh - sb_h - 3.0, _LAYOUT_MM))
    sb.attemptResize(QgsLayoutSize(sb_w, sb_h, _LAYOUT_MM))
    sb.setBackgroundEnabled(True)
    sb.setBackgroundColor(QColor(255, 255, 255, 225))
    sb.setFrameEnabled(True)
    sb.setFrameStrokeColor(_qcolor("#CBD5E1"))
    sb.setFrameStrokeWidth(QgsLayoutMeasurement(0.25, _LAYOUT_MM))
    layout.addLayoutItem(sb)

    # 6. Analytical Inset Map
    ix, iy, iw, ih = inset_box
    map_inset = QgsLayoutItemMap(layout)
    map_inset.setId("inset_map")
    map_inset.attemptMove(QgsLayoutPoint(ix, iy, _LAYOUT_MM))
    map_inset.attemptResize(QgsLayoutSize(iw, ih, _LAYOUT_MM))
    map_inset.setCrs(work_crs)
    if map_layers:
        map_inset.setLayers(map_layers)
        map_inset.setKeepLayerSet(True)
    map_inset.zoomToExtent(inset_rect)
    map_inset.setFrameEnabled(True)
    map_inset.setFrameStrokeColor(_qcolor(SYNTHESIS_PALETTE["vulnerability"]))
    map_inset.setFrameStrokeWidth(QgsLayoutMeasurement(0.45, _LAYOUT_MM))
    layout.addLayoutItem(map_inset)

    inset_hdr_lbl = _add_font_box(
        layout,
        ix + 1.0,
        iy + 1.0,
        iw - 2.0,
        5.5,
        L["inset_title"],
        size_pt=5.8 if not is_a1 else 7.2,
        bold=True,
        text_hex="#991B1B",
        border_hex="#FCA5A5",
        bg_hex="#FEF2F2",
        margin_x=1.4,
        margin_y=0.7,
        v_align=_ALIGN_VCENTER,
    )
    if hasattr(map_inset, "addLabelBlockingItem"):
        map_inset.addLabelBlockingItem(inset_hdr_lbl)

    # 7. Categorized Legend (cleaned single rows, auto-pruned, bounded inside box)
    lx, ly, lw, lh = legend_box
    legend = QgsLayoutItemLegend(layout)
    legend.setLinkedMap(map_main)
    legend.setTitle(L["legend_title"])
    legend.setAutoUpdateModel(False)
    leg_root = legend.model().rootGroup()
    has_full_leg = any(
        (l.name().startswith("Alt_Bolgeler_") or l.name().startswith("Hazir_Bolgeler_Analizi_"))
        and "Hizli_Ozet" not in l.name()
        for l in map_layers
    )
    keep_ids = {
        lyr.id()
        for lyr in map_layers
        if lyr.name() not in ("Yol_Agi", "Imar_Adasi_Hucreleri") and not _is_duplicate_quick_layer(lyr, has_full_leg)
    }
    if not keep_ids:
        keep_ids = {lyr.id() for lyr in map_layers}
    for node in list(leg_root.findLayers()):
        if node.layerId() not in keep_ids:
            parent_g = node.parent()
            if parent_g is not None:
                parent_g.removeChildNode(node)

    # Compact typography and symbol sizes so multi-layer legends fit cleanly without clipping
    t_fnt = QFont("Segoe UI", 7 if not is_a1 else 9)
    t_fnt.setBold(True)
    g_fnt = QFont("Segoe UI", 6 if not is_a1 else 7)
    g_fnt.setBold(True)
    i_fnt = QFont("Segoe UI", 5 if not is_a1 else 6)
    legend.setStyleFont(_LEG_STYLE_TITLE, t_fnt)
    legend.setStyleFont(_LEG_STYLE_GROUP, g_fnt)
    legend.setStyleFont(_LEG_STYLE_SUBGROUP, g_fnt)
    legend.setStyleFont(_LEG_STYLE_LABEL, i_fnt)
    legend.setSymbolWidth(4.0 if not is_a1 else 5.5)
    legend.setSymbolHeight(2.2 if not is_a1 else 3.0)
    legend.setBoxSpace(1.6)
    legend.setColumnSpace(2.4)
    legend.setSplitLayer(False)
    legend.setColumnCount(3 if not is_a1 else 2)
    legend.setEqualColumnWidth(True)
    legend.setBackgroundEnabled(True)
    legend.setBackgroundColor(QColor("#FFFFFF"))
    legend.setFrameEnabled(True)
    legend.setFrameStrokeColor(_qcolor("#CBD5E1"))
    legend.setFrameStrokeWidth(QgsLayoutMeasurement(0.3, _LAYOUT_MM))
    legend.setResizeToContents(False)
    legend.attemptMove(QgsLayoutPoint(lx, ly, _LAYOUT_MM))
    legend.attemptResize(QgsLayoutSize(lw, lh, _LAYOUT_MM))
    layout.addLayoutItem(legend)

    # 8. Formal Title Block (Pafta Künyesi)
    kx, ky, kw, kh = kunye_box
    scale_denom = int(round(map_main.scale())) if map_main.scale() > 0 else 5000
    k_hdr_h = 6.0 if not is_a1 else 8.0
    _add_font_box(
        layout, kx, ky, kw, k_hdr_h, L["kunye_title"],
        size_pt=7.5 if not is_a1 else 9.5, bold=True,
        text_hex="#FFFFFF", border_hex="#0F172A", bg_hex="#0F172A",
        margin_x=2.2, margin_y=1.1, v_align=_ALIGN_VCENTER,
    )
    kunye_body = (
        f"{L['scale']}: 1 : {scale_denom:,}   |   {L['crs']}: {crs_label}\n"
        f"{L['zones']}: {snap['zone_count']} ({snap['built_zone_count']} {L['built_lbl']})   |   {L['area']}: {snap['total_area_ha']:.2f} ha\n"
        f"{L['pop']}: {snap['total_population']:,}   |   {L['bldg']}: {snap['total_buildings']:,}\n"
        f"{L['axis']}: {axis_text}   |   {L['date']}: {date_str}"
    )
    _add_font_box(
        layout, kx, ky + k_hdr_h, kw, kh - k_hdr_h, kunye_body,
        size_pt=6.8 if not is_a1 else 8.6, bold=False,
        text_hex="#0F172A", border_hex="#0F172A", bg_hex="#F8FAFC",
        margin_x=2.4, margin_y=2.2, v_align=_ALIGN_TOP if is_a1 else _ALIGN_VCENTER,
    )

    # 9. Data-Driven SWOT Card
    sx, sy, sw, sh = swot_box
    _add_swot_panel(layout, sx, sy, sw, sh, swot, L, compact=compact_cards)

    # 10. 1-to-1 Zone Legend & Narrative Synthesis Table
    tx, ty, tw, th = table_box
    _add_zone_table_panel(layout, tx, ty, tw, th, zlist, L, lang=loc, max_rows=max_table_rows, compact=compact_cards)

    mgr.addLayout(layout)

    # Optional Exports
    exporter = QgsLayoutExporter(layout)
    pdf_ok = False
    png_ok = False
    qpt_ok = False
    export_errors: List[str] = []

    if export_pdf_path:
        try:
            Path(export_pdf_path).parent.mkdir(parents=True, exist_ok=True)
            pdf_settings = QgsLayoutExporter.PdfExportSettings()
            pdf_settings.dpi = 300.0
            res_pdf = exporter.exportToPdf(str(export_pdf_path), pdf_settings)
            pdf_ok = (res_pdf == _EXPORT_SUCCESS)
            if not pdf_ok:
                export_errors.append(f"PDF export returned status {res_pdf}")
        except Exception as exc:
            export_errors.append(f"PDF export error: {exc}")

    if export_png_path:
        try:
            Path(export_png_path).parent.mkdir(parents=True, exist_ok=True)
            img_settings = QgsLayoutExporter.ImageExportSettings()
            img_settings.dpi = 200.0 if is_a1 else 250.0
            res_png = exporter.exportToImage(str(export_png_path), img_settings)
            png_ok = (res_png == _EXPORT_SUCCESS)
            if not png_ok:
                export_errors.append(f"PNG export returned status {res_png}")
        except Exception as exc:
            export_errors.append(f"PNG export error: {exc}")

    if export_qpt_path:
        try:
            Path(export_qpt_path).parent.mkdir(parents=True, exist_ok=True)
            qpt_ok = bool(layout.saveAsTemplate(str(export_qpt_path), QgsReadWriteContext()))
            if not qpt_ok:
                export_errors.append("QPT template save returned False")
        except Exception as exc:
            export_errors.append(f"QPT save error: {exc}")

    return {
        "layout": layout,
        "layout_name": layout_name,
        "paper_format": fmt_norm,
        "page_width_mm": page_w,
        "page_height_mm": page_h,
        "swot": swot,
        "pdf_exported": pdf_ok,
        "png_exported": png_ok,
        "qpt_exported": qpt_ok,
        "pdf_path": str(export_pdf_path) if pdf_ok else None,
        "png_path": str(export_png_path) if png_ok else None,
        "qpt_path": str(export_qpt_path) if qpt_ok else None,
        "errors": export_errors,
    }
