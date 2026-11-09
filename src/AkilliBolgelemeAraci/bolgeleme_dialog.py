# -*- coding: utf-8 -*-
import os
import csv
import traceback
from collections import Counter

from qgis.PyQt.QtCore import Qt, QTimer, QSize, QPoint
from qgis.PyQt.QtGui import QIcon, QPixmap, QPainter, QColor, QPolygon, QPen
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QTabWidget, QWidget, QLabel, QPushButton, QSpinBox,
    QDoubleSpinBox, QCheckBox, QGroupBox, QFormLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QProgressBar, QTextEdit, QMessageBox, QAbstractItemView, QFileDialog,
    QComboBox, QApplication, QFrame, QScrollArea, QRadioButton, QButtonGroup, QSizePolicy, QLineEdit,
    QSlider
)
from qgis.gui import QgsMapLayerComboBox, QgsFieldComboBox
from qgis.core import (
    QgsProject, QgsMapLayerProxyModel, QgsFeatureRequest,
    QgsVectorLayer, QgsRasterLayer, QgsWkbTypes
)

from . import analiz
from . import algoritma as alg

# PyQt5 / PyQt6 uyumluluk köprüsü
ScrollBarAsNeeded = getattr(Qt.ScrollBarPolicy, "ScrollBarAsNeeded", getattr(Qt, "ScrollBarAsNeeded", None))
WindowMinimizeButtonHint = getattr(Qt.WindowType, "WindowMinimizeButtonHint", getattr(Qt, "WindowMinimizeButtonHint", 0))
WindowMaximizeButtonHint = getattr(Qt.WindowType, "WindowMaximizeButtonHint", getattr(Qt, "WindowMaximizeButtonHint", 0))
PointingHandCursor = getattr(Qt.CursorShape, "PointingHandCursor", getattr(Qt, "PointingHandCursor", None))
AlignLeft = getattr(Qt.AlignmentFlag, "AlignLeft", getattr(Qt, "AlignLeft", 1))
AlignVCenter = getattr(Qt.AlignmentFlag, "AlignVCenter", getattr(Qt, "AlignVCenter", 128))
WaitCursor = getattr(Qt.CursorShape, "WaitCursor", getattr(Qt, "WaitCursor", None))
OrientationHorizontal = getattr(Qt.Orientation, "Horizontal", getattr(Qt, "Horizontal", 1))

_Policy = getattr(QSizePolicy, "Policy", QSizePolicy)
PolicyExpanding = getattr(_Policy, "Expanding", getattr(QSizePolicy, "Expanding", 7))
PolicyFixed = getattr(_Policy, "Fixed", getattr(QSizePolicy, "Fixed", 0))

_ResizeMode = getattr(QHeaderView, "ResizeMode", QHeaderView)
HeaderStretch = getattr(_ResizeMode, "Stretch", getattr(QHeaderView, "Stretch", 1))

_SelectionBehavior = getattr(QAbstractItemView, "SelectionBehavior", QAbstractItemView)
SelectRows = getattr(_SelectionBehavior, "SelectRows", getattr(QAbstractItemView, "SelectRows", 1))

STYLE = """
QDialog {
    background-color: #f1f5f9;
    color: #0f172a;
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, Arial, sans-serif;
    font-size: 12px;
}
QScrollArea {
    border: none;
    background-color: transparent;
}
QWidget#scrollContent {
    background-color: transparent;
}
QLabel {
    color: #1e293b;
    font-size: 12px;
}
QLabel#fieldTitle {
    color: #0f172a;
    font-weight: 600;
    font-size: 12px;
}
QLabel#badgeInfo {
    background-color: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 4px;
    padding: 2px 6px;
    font-size: 11px;
    color: #475569;
}
/* Modern Kart Görünümlü QGroupBox */
QGroupBox {
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    margin-top: 12px;
    padding: 14px 12px 10px 12px;
    background-color: #ffffff;
    font-weight: 700;
    font-size: 12px;
    color: #0f172a;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 2px 8px;
    background-color: #e0f2fe;
    color: #0369a1;
    border: 1px solid #bae6fd;
    border-radius: 4px;
}
/* Sekme (Tab) Tasarımı */
QTabWidget::pane {
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    background-color: #f8fafc;
    top: -1px;
}
QTabBar::tab {
    background-color: #e2e8f0;
    color: #475569;
    border: 1px solid #cbd5e1;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 8px 14px;
    margin-right: 4px;
    font-weight: 600;
    font-size: 12px;
}
QTabBar::tab:selected {
    background-color: #0284c7;
    color: #ffffff;
    border-color: #0369a1;
}
QTabBar::tab:hover:!selected {
    background-color: #ffffff;
    color: #0284c7;
}
/* 3B Dokunsal (Tactile) Butonlar */
QPushButton {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:1 #f1f5f9);
    color: #0f172a;
    border: 1px solid #94a3b8;
    border-bottom: 2px solid #64748b;
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 600;
    font-size: 12px;
    min-height: 22px;
}
QPushButton:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f0f9ff, stop:1 #e0f2fe);
    border-color: #0284c7;
    border-bottom: 2px solid #0369a1;
    color: #0369a1;
}
QPushButton:pressed {
    background-color: #cbd5e1;
    border: 1px solid #64748b;
    padding-top: 8px;
    padding-bottom: 4px;
}
/* Ana Çalıştır Düğmesi (Zümrüt Yeşili 3D) */
QPushButton#runBtn {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #22c55e, stop:1 #16a34a);
    border: 1px solid #15803d;
    border-bottom: 3px solid #14532d;
    border-radius: 7px;
    color: #ffffff;
    font-size: 13px;
    font-weight: bold;
    padding: 7px 20px;
    min-height: 24px;
}
QPushButton#runBtn:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #4ade80, stop:1 #16a34a);
    border-color: #166534;
    border-bottom: 3px solid #052e16;
}
QPushButton#runBtn:pressed {
    background-color: #15803d;
    border-bottom: 1px solid #14532d;
    padding-top: 9px;
    padding-bottom: 5px;
}
QPushButton#runBtn:disabled {
    background-color: #94a3b8;
    border-color: #64748b;
    color: #e2e8f0;
}
/* CSV Dışa Aktar Düğmesi (Kurumsal Mavi 3D) */
QPushButton#exportBtn {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0284c7, stop:1 #0369a1);
    border: 1px solid #075985;
    border-bottom: 3px solid #0c4a6e;
    border-radius: 7px;
    color: #ffffff;
    font-size: 12px;
    font-weight: bold;
    padding: 7px 16px;
    min-height: 24px;
}
QPushButton#exportBtn:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #38bdf8, stop:1 #0284c7);
}
QPushButton#exportBtn:pressed {
    background-color: #075985;
    border-bottom: 1px solid #0c4a6e;
    padding-top: 9px;
    padding-bottom: 5px;
}
QPushButton#exportBtn:disabled {
    background-color: #e2e8f0;
    border-color: #cbd5e1;
    color: #94a3b8;
}
/* Analiz İzleme Matrisi Düğmesi (Teal / Zümrüt Yeşili 3D) */
QPushButton#matrixBtn {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0f766e, stop:1 #115e59);
    border: 1px solid #14b8a6;
    border-bottom: 3px solid #134e4a;
    border-radius: 7px;
    color: #ffffff;
    font-weight: 700;
    font-size: 12px;
    padding: 8px 16px;
    min-height: 24px;
}
QPushButton#matrixBtn:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #14b8a6, stop:1 #0f766e);
}
QPushButton#matrixBtn:pressed {
    background-color: #134e4a;
    border-bottom: 1px solid #134e4a;
    padding-top: 9px;
    padding-bottom: 5px;
}
QPushButton#matrixBtn:disabled {
    background-color: #e2e8f0;
    border-color: #cbd5e1;
    color: #94a3b8;
}
/* Metodoloji ve Kullanım El Kitabı Düğmesi (Cyan / Gökyüzü Mavisi 3D) */
QPushButton#helpBtn {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0284c7, stop:1 #0369a1);
    border: 1px solid #38bdf8;
    border-bottom: 2px solid #075985;
    border-radius: 6px;
    color: #ffffff;
    font-weight: 700;
    font-size: 12px;
    padding: 6px 14px;
    min-height: 22px;
}
QPushButton#helpBtn:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #38bdf8, stop:1 #0284c7);
    border-color: #7dd3fc;
    color: #ffffff;
}
QPushButton#helpBtn:pressed {
    background-color: #075985;
    border-bottom: 1px solid #075985;
    padding-top: 7px;
    padding-bottom: 5px;
}
/* Girdi Kutuları (Basıklığı önleyen ferah min-height) */
QComboBox, QSpinBox, QDoubleSpinBox {
    background-color: #ffffff;
    color: #0f172a;
    border: 1px solid #94a3b8;
    border-radius: 5px;
    padding: 4px 8px;
    min-height: 24px;
    font-size: 12px;
    selection-background-color: #0284c7;
    selection-color: #ffffff;
}
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {
    border-color: #0284c7;
    background-color: #f8fafc;
}
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1.5px solid #0284c7;
    background-color: #ffffff;
}
QComboBox QAbstractItemView {
    background-color: #ffffff;
    color: #0f172a;
    border: 1px solid #0284c7;
    selection-background-color: #0284c7;
    selection-color: #ffffff;
    outline: 0px;
}
/* Tablo Tasarımı */
QTableWidget {
    background-color: #ffffff;
    alternate-background-color: #f8fafc;
    color: #0f172a;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    gridline-color: #e2e8f0;
    selection-background-color: #e0f2fe;
    selection-color: #0369a1;
}
QHeaderView::section {
    background-color: #f1f5f9;
    color: #0f172a;
    padding: 6px 8px;
    border: none;
    border-right: 1px solid #cbd5e1;
    border-bottom: 1px solid #cbd5e1;
    font-weight: 700;
}
QCheckBox, QRadioButton {
    color: #1e293b;
    font-weight: 500;
    spacing: 8px;
    padding: 2px 0px;
}
QProgressBar {
    border: 1px solid #94a3b8;
    border-radius: 6px;
    background-color: #e2e8f0;
    text-align: center;
    color: #0f172a;
    font-weight: bold;
    min-height: 24px;
    max-height: 24px;
}
QProgressBar::chunk {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #22c55e);
    border-radius: 5px;
}
QTextEdit {
    background-color: #ffffff;
    color: #0f172a;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 6px;
    font-family: 'Segoe UI', Consolas, monospace;
    font-size: 12px;
}
"""

FIELD_DEFS = [
    ("kullanim", "Arazi / Yapı Kullanımı", ("kullanim", "fonksiyon", "landuse", "arazi", "amac", "sinif", "tur", "cins", "nitelik", "islev", "mk"), False),
    ("kat", "Kat Adedi / Yüksekliği", ("kat", "floor", "yukseklik", "height", "ks", "kat_adedi", "katsayisi"), True),
    ("yd", "Yapı Nizamı (Bitişik/Ayrık)", ("nizam", "duzen", "yd", "yapilasma", "terti"), False),
    ("durum", "Yapı Fiziksel Durumu", ("durum", "kalite", "fiziksel", "yf", "hasar", "yapi_durum"), False),
]

BLDG_FIELD_DEFS = [
    ("kullanim", "Yapı Fonksiyonu / Türü", ("kullanim", "fonksiyon", "tur", "cins", "nitelik", "islev", "sinif"), False),
    ("kat", "Yapı Kat Adedi", ("kat", "floor", "yukseklik", "height", "ks", "kat_adedi", "katsayisi"), True),
    ("yd", "Yapı Nizamı (Bitişik/Ayrık)", ("nizam", "duzen", "yd", "yapilasma"), False),
    ("durum", "Yapı Fiziksel Durumu", ("durum", "kalite", "fiziksel", "yf", "hasar"), False),
]

ROAD_FIELD_DEFS = [
    ("r_genislik", "Yol Genişliği (Metre)", ("genislik", "width", "yg", "en", "cap", "serit"), True),
    ("r_kaplama", "Üstyapı / Kaplama Türü", ("kaplama", "yuzey", "zemin", "surface", "malzeme", "cins"), False),
    ("r_tur", "Yol Kademelenmesi", ("kademe", "tur", "sinif", "type", "class", "statu", "nitelik", "yol_turu"), False),
]

NATURAL_LAYER_RULES = [
    ("dere", "Dere / Akarsu Yatağı", ("dere", "akarsu", "nehir", "cay", "su_yolu", "kanal", "vadisi", "hidroloji")),
    ("fay", "Diri Fay Hattı", ("diri_fay", "fay_hatti", "faylar", "fault", "seismic_fault", "aktif_fay", "fay_")),
    ("sit", "Sit / Koruma Alanı", ("sit_alan", "tescilli_alan", "kentsel_sit", "dogal_sit", "arkeolojik_sit", "sit", "tescil", "koruma")),
    ("risk", "Taşkın / Afet Risk Alanı", ("taskin", "sel_riski", "heyelan", "afete_maruz", "sakincali", "jeoloji")),
    ("lst", "Kentsel Isı Adası / LST", ("lst", "isi_adasi", "thermal", "sicaklik", "termal", "heat")),
    ("tarim", "Tarım / Ova Alanı", ("tarim", "ova", "buyukova", "mera", "ziraat")),
    ("sanayi", "Sanayi / OSB Çevre Kuşağı", ("sanayi", "osb", "endustri", "depolama", "kss")),
]


def wrap_in_scroll(widget):
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    if ScrollBarAsNeeded is not None:
        scroll.setHorizontalScrollBarPolicy(ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(ScrollBarAsNeeded)
    widget.setObjectName("scrollContent")
    scroll.setWidget(widget)
    return scroll


def create_flag_icon(lang_code):
    pix = QPixmap(24, 16)
    pix.fill(QColor(0, 0, 0, 0))
    p = QPainter(pix)
    aa_hint = getattr(getattr(QPainter, "RenderHint", QPainter), "Antialiasing", 1)
    p.setRenderHint(aa_hint)
    no_pen = getattr(getattr(Qt, "PenStyle", Qt), "NoPen", 0)
    p.setPen(no_pen)
    if lang_code == "tr":
        p.setBrush(QColor("#E30A17"))
        p.drawRoundedRect(0, 0, 24, 16, 2, 2)
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(6, 4, 8, 8)
        p.setBrush(QColor("#E30A17"))
        p.drawEllipse(8, 5, 6, 6)
        p.setBrush(QColor("#FFFFFF"))
        p.drawPolygon(QPolygon([QPoint(14, 8), QPoint(17, 6), QPoint(16, 9), QPoint(18, 9), QPoint(15, 10)]))
    elif lang_code == "en":
        # UK Union Jack (🇬🇧) - Çapraz beyaz/kırmızı St. Andrew/Patrick haçı (X) + Merkez St. George haçı (+)
        p.setBrush(QColor("#012169"))
        p.drawRoundedRect(0, 0, 24, 16, 2, 2)
        p.setPen(QPen(QColor("#FFFFFF"), 3.6))
        p.drawLine(0, 0, 24, 16)
        p.drawLine(0, 16, 24, 0)
        p.setPen(QPen(QColor("#C8102E"), 1.6))
        p.drawLine(0, 0, 24, 16)
        p.drawLine(0, 16, 24, 0)
        p.setPen(no_pen)
        p.setBrush(QColor("#FFFFFF"))
        p.drawRect(9, 0, 6, 16)
        p.drawRect(0, 5, 24, 6)
        p.setBrush(QColor("#C8102E"))
        p.drawRect(10, 0, 4, 16)
        p.drawRect(0, 6, 24, 4)
    elif lang_code == "zh":
        p.setBrush(QColor("#EE1C25"))
        p.drawRoundedRect(0, 0, 24, 16, 2, 2)
        p.setBrush(QColor("#FFFF00"))
        p.drawEllipse(3, 3, 5, 5)
        for sx, sy in [(9, 2), (11, 4), (11, 7), (9, 9)]:
            p.drawEllipse(sx, sy, 2, 2)
    elif lang_code == "es":
        p.setBrush(QColor("#AA151B"))
        p.drawRoundedRect(0, 0, 24, 16, 2, 2)
        p.setBrush(QColor("#F1BF00"))
        p.drawRect(0, 4, 24, 8)
    p.end()
    return QIcon(pix)


UI_TRANSLATIONS = {
    "en": {
        "win_title": "Urban Zoning & Vulnerability Analyzer — Baran Adsuna",
        "hdr_title": "Urban Zoning & Vulnerability Analysis Tool",
        "hdr_sub": "⚡ Author / Developer: Baran Adsuna  •  MPYY Morphological Zoning, Multi-Criteria Synthesis & Decision Support",
        "lbl_mode": "Analysis Depth / Mode:",
        "mode_std": "🌱 Standard Zoning Mode (MPYY Morphological Sub-Zones - Fast & Practical)",
        "mode_adv": "🔬 Advanced Synthesis & Intervention Atlas Mode (Vulnerability [E/S/AC], Elevation, Decisions & Plan Map)",
        "badge_adv": "🔬 <b>Advanced Synthesis & Intervention Atlas Active:</b> Generates M1..MK sequential codes, 3D Vulnerability (E·S/AC), DEM Elevation (Z), Intervention Decisions, 1/5000 & 1/1000 Plan Rules, and Tracking Matrix.",
        "badge_std": "🌱 <b>Standard Zoning Mode Active:</b> Generates A1..AK sequential morphological profile matching, fabric homogeneity, and boundary separation rationales.",
        "btn_help": "📖 Methodology & User Guide (HTML)",
        "btn_top_adv": "▶ Run Synthesis",
        "btn_top_std": "▶ Run Standard",
        "tab_1": "1. Layers, Buildings & Pop.",
        "tab_2": "2. Natural Thresholds & DEM",
        "tab_3": "3. Weights & Settings",
        "tab_4": "4. Boundary Rationales Report",
        "tab_5": "5. Methodology & MPYY Guide",
        "btn_quick_csv": "⚡ Quick Summary (Excel / CSV)",
        "btn_csv": "📊 Full Table (Excel / CSV)",
        "btn_matrix": "📋 Tracking Matrix (Excel / CSV)",
        "btn_run_adv": "▶ RUN SYNTHESIS",
        "btn_run_std": "▶ RUN ZONING",
        "view_lbl": "View Mode:",
        "rb_quick": "⚡ Quick & Plain Summary (Fast Read)",
        "rb_both": "📋 Combined (Quick + Detailed)",
        "rb_detailed": "🔬 Detailed Technical Only (ΔZ & Codes)",
        "filter_ph": "🔍 Filter by zone code or keyword (e.g. M12, Konut, Fay, Donatı, Sit)...",
        "chk_quick_layer": "Also add simplified 'Alt_Bolgeler_Hizli_Ozet' layer to map (Quick-reading columns only)",
        "grp_a": "A. Core Planning Layers (EPSG:5253)",
        "lbl_bnd": "<b>1) Plan / Study Boundary (Polygon):</b>",
        "lbl_road": "<b>2) Road / Street Network (Line):</b>",
        "lbl_block": "<b>3) Urban Blocks / Land Use (Polygon):</b>",
        "btn_auto_main": "⚡ Auto-Match All Project Layers, Buildings & Natural Thresholds",
        "grp_b": "B. Optional Individual Buildings Layer",
        "chk_use_bldg": "Use a separate 'Buildings / Footprints' layer for TAKS, floors, building order, structural condition & population",
        "lbl_bldg_lyr": "<b>Individual Buildings Layer:</b>",
        "grp_c": "C. Estimated Population Distribution (Residential & Mixed Blocks by Building Count & Block Area)",
        "rb_pop_1": "1) Auto from Attribute Column (Use population column; fallback to manual total below if empty)",
        "rb_pop_2": "2) Enter Total Study Area Population Manually (Distributed only to residential & mixed blocks; Industry/Agri = 0)",
        "rb_pop_3": "3) Estimate by Average Persons per Floor (Building count × floor count × persons/floor)",
        "lbl_man_pop": "<b>Manual Total Population:</b>",
        "lbl_pop_algo_info": "⚡ <b>Estimated Population Algorithm:</b> Distributes the total population exclusively to <b>Residential</b> and <b>Mixed (Residential + Commercial)</b> urban blocks according to each block's <b>building count</b>, <b>block area (m²)</b>, and <b>floor count</b> (Industry, Agriculture & Facility = 0).",
        "lbl_per_bldg": "<b>Persons per Floor:</b>",
        "grp_d1": "D1. Urban Block Attributes (Auto-Matched)",
        "grp_d2": "D2. Road Network Attributes (Auto-Matched)",
        "grp_e": "E. Natural Thresholds & Protected Areas",
        "btn_auto_nat": "⚡ Auto-Scan Natural Thresholds (Stream, Fault, Sit, DEM...)",
        "btn_add_row": "➕ Add Row",
        "btn_del_row": "🗑️ Remove Selected",
        "tbl_col_0": "Threshold / Layer Name",
        "tbl_col_1": "Analysis Role (Auto-Selected)",
        "tbl_col_2": "Map Layer",
        "grp_f": "F. Digital Elevation Model (DEM) / Slope Layer",
        "lbl_dem": "<b>DEM or Slope Raster:</b>",
        "chk_slope": "Selected raster directly contains percentage slope (%) values",
        "lbl_step": "<b>Slope Sampling Step:</b>",
        "grp_preset": "Zoning Strategy Presets (Select a Preset or Fine-Tune the Weights Manually Below)",
        "lbl_preset_sel": "<b>Select Zoning Strategy Preset:</b>",
        "grp_g": "G. Manual Zoning Parameters & Fine-Tuning Weight Coefficients",
        "p_k_t": "1) Target Sub-Zone Count (K)",
        "p_k_d": "Exact number of sequential sub-zones to create (e.g., 25 -> M1..M25, 28 -> M1..M28 without gaps).",
        "p_lu_t": "2) Land Use & Sub-Type Weight",
        "p_lu_d": "Separates residential (low/sparse vs high density), commercial, industrial, agricultural, cemetery, and facility blocks.",
        "p_yapi_t": "3) Building / Floor / Density Weight",
        "p_yapi_d": "Separates blocks differing in TAKS, floor count, building order, poor structural condition, and population density.",
        "p_dogal_t": "4) Natural Threshold & Protection Weight",
        "p_dogal_d": "Isolates stream buffers, steep DEM slopes, active fault lines, and heritage (Sit) / flood risk areas.",
        "p_geo_t": "5) Spatial Compactness & Cohesive Form Weight",
        "p_geo_d": "Enforces cohesive, rounded/orthogonal zone shapes and strictly prevents long winding corridors or road strips.",
        "p_cap_t": "6) Macro-Zone Cohesion & Area Cap",
        "p_cap_d": "Prevents artificial splitting of massive industrial zones (OIZ) or continuous agricultural plains, keeping large functional areas unified.",
        "p_bos_t": "7) Vacant Land & New Plan Potential Weight",
        "p_bos_d": "Separates high-vacant-land reserve blocks (for drawing new plans) from fully built-up urban fabric.",
        "p_erisim_t": "8) Facility Accessibility Weight",
        "p_erisim_d": "Groups adjacent blocks sharing similar walking access to social and public facilities.",
        "p_yol_t": "9) Road Network Similarity Weight",
        "p_yol_d": "Groups neighboring blocks with similar road width, surface pavement, and street hierarchy.",
        "p_odak_t": "10) Industrial (OIZ) Cohesion & Isolation",
        "p_odak_d": "Keeps industrial estates unified into massive, compact blocks and strictly isolates industry from encroaching into residential areas.",
        "p_grid_t": "11) Fallback Grid Size",
        "p_grid_d": "Default grid cell width used only when no road network layer is provided.",
        "grp_h": "H. Compact Geometry, Quick Summary Layer & Matching Options",
        "chk_medians": "Eliminate road corridors, medians & junction slivers (Roads only form boundaries, never long zone tails)",
        "chk_excel": "Match sub-zones with canonical MPYY character & intervention profiles",
        "chk_cells": "Also add intermediate urban block cells layer ('Imar_Adasi_Hucreleri') to map",
        "grp_i": "I. Sub-Zoning Summary, Internal Cohesion & Neighbor Separation Rationales",
        "lbl_about_top": "<b>Spatial Analysis Methodology, MAUP Solution & Comprehensive User Guide:</b>",
        "btn_browser": "🌐 Open Full Methodology Guide in Browser (HTML)",
        "grp_j": "J. Comprehensive Methodology, MAUP Solution & Step-by-Step User Manual",
        "fld_kullanim": "Land / Building Use",
        "fld_kat": "Floor Count / Height",
        "fld_yd": "Building Order (Attached/Detached)",
        "fld_durum": "Structural Condition",
        "fld_nufus": "Population / Resident Column",
        "rfld_gen": "Road Width (Meters)",
        "rfld_kap": "Road Surface / Pavement",
        "rfld_tur": "Road Hierarchy / Class",
    },
    "tr": {
        "win_title": "Kentsel Bölgeleme ve Kırılganlık Analiz Aracı — Baran Adsuna",
        "hdr_title": "Kentsel Bölgeleme ve Kırılganlık Analiz Aracı",
        "hdr_sub": "⚡ Geliştirici / Yazar: Baran Adsuna  •  MPYY Uyumlu Morfolojik Bölgeleme, Çok Kriterli Sentez ve Karar Destek Sistemi",
        "lbl_mode": "Analiz Derinliği & Mod:",
        "mode_std": "🌱 Standart Bölgeleme Modu (MPYY Morfolojik Alt Bölgeler - Hızlı & Pratik)",
        "mode_adv": "🔬 İleri Sentez & Müdahale Atlası Modu (Kırılganlık [E/S/AC], Rakım, Müdahale Kararları & Plan Karşılığı)",
        "badge_adv": "🔬 <b>İleri Sentez & Müdahale Atlası Aktif:</b> M1..MK ardışık kodları, 3B Kırılganlık (E·S/AC), DEM Rakım (Z), Müdahale Kararları, 1/5000 & 1/1000 Plan Karşılıkları ve Analiz İzleme Matrisi üretilir.",
        "badge_std": "🌱 <b>Standart Bölgeleme Modu Aktif:</b> A1..AK ardışık morfolojik profil eşleşmesi, doku homojenliği ve sınır ayrım gerekçeleri üretilir (Hızlı ön bölgeleme).",
        "btn_help": "📖 Metodoloji ve Kullanım El Kitabı (HTML)",
        "btn_top_adv": "▶ İleri Sentez Başlat",
        "btn_top_std": "▶ Standart Bölgele",
        "tab_1": "1. Katmanlar, Yapılar ve Nüfus",
        "tab_2": "2. Doğal Eşikler ve DEM",
        "tab_3": "3. Ağırlıklar ve Ayarlar",
        "tab_4": "4. Sınır Ayrım Gerekçeleri Raporu",
        "tab_5": "5. Metodoloji ve MPYY Kılavuzu",
        "btn_quick_csv": "⚡ Hızlı Özet (Excel / CSV)",
        "btn_csv": "📊 Detaylı Tablo (Excel / CSV)",
        "btn_matrix": "📋 İzleme Matrisi (Excel / CSV)",
        "btn_run_adv": "▶ İLERİ SENTEZ ÇALIŞTIR",
        "btn_run_std": "▶ STANDART BÖLGELE",
        "view_lbl": "Görünüm Modu:",
        "rb_quick": "⚡ Hızlı ve Sade Özet (Hızlı Okuma)",
        "rb_both": "📋 İkisi Bir Arada (Özet + Detay)",
        "rb_detailed": "🔬 Sadece Detaylı Teknik (ΔZ & Kodlar)",
        "filter_ph": "🔍 Bölge kodu veya anahtar kelime filtrele (ör: M12, Konut, Fay, Donatı, Sit)...",
        "chk_quick_layer": "Haritaya ayrıca sadeleştirilmiş 'Alt_Bolgeler_Hizli_Ozet' katmanı ekle (Sadece hızlı okuma sütunları)",
        "grp_a": "A. Ana Planlama Katmanları (EPSG:5253)",
        "lbl_bnd": "<b>1) Plan / Onama Sınırı (Poligon):</b>",
        "lbl_road": "<b>2) Ulaşım / Yol Ağı (Çizgi):</b>",
        "lbl_block": "<b>3) İmar Adaları / Arazi Kullanımı (Poligon):</b>",
        "btn_auto_main": "⚡ Projedeki Tüm Katmanları, Yapıları ve Doğal Eşikleri Otomatik Eşleştir",
        "grp_b": "B. Opsiyonel Tekil Yapılar / Binalar Katmanı",
        "chk_use_bldg": "Ayrı bir 'Yapılar / Binalar' katmanım var ve analizlerde (TAKS, kat, yapı nizamı, yapı durumu, nüfus) kullanılmasını istiyorum",
        "lbl_bldg_lyr": "<b>Tekil Yapılar / Binalar Katmanı:</b>",
        "grp_c": "C. Tahmini Nüfus Dağıtımı (Konut ve Karma Adalara Bina Sayısı + Ada Alanı Ağırlıklı)",
        "rb_pop_1": "1) Otomatik Sütundan Al (Katmandaki nüfus sütununu kullan; boşsa alttaki manuel değeri dağıt)",
        "rb_pop_2": "2) Toplam Çalışma Alanı Nüfusunu Elle Gir (Sadece konut ve karma kullanım adalarına ağırlıklı dağıtılır; Sanayi/Tarım = 0)",
        "rb_pop_3": "3) Kat / Daire Başına Ortalama Kişi Sayısı İle Hesapla (Yapı sayısı × kat adedi × kat başına kişi)",
        "lbl_man_pop": "<b>Elle Toplam Nüfus:</b>",
        "lbl_pop_algo_info": "⚡ <b>Tahmini Nüfus Algoritması:</b> Girilen toplam nüfus yalnızca <b>Konut</b> ve <b>Karma (Ticaret + Konut)</b> imar adalarına, her adanın içindeki <b>bina sayısı</b>, <b>ada büyüklüğü (m²)</b> ve <b>kat adedi</b> ağırlığına göre tahmini olarak dağıtılır (Sanayi, Tarım ve Donatı = 0).",
        "lbl_per_bldg": "<b>Kat Başına Ortalama Kişi:</b>",
        "grp_d1": "D1. İmar Adası Öznitelikleri (Otomatik Eşleşir)",
        "grp_d2": "D2. Yol Ağı Öznitelikleri (Otomatik Eşleşir)",
        "grp_e": "E. Doğal Eşikler ve Koruma Alanları",
        "btn_auto_nat": "⚡ Projedeki Doğal Eşikleri (Dere, Fay, Sit, DEM...) Otomatik Tara",
        "btn_add_row": "➕ Manuel Satır Ekle",
        "btn_del_row": "🗑️ Seçili Satırı Kaldır",
        "tbl_col_0": "Eşik / Katman Adı",
        "tbl_col_1": "Analiz Rolü (Otomatik Seçilir)",
        "tbl_col_2": "Harita Katmanı",
        "grp_f": "F. Sayısal Yükselti Modeli (DEM) / Eğim Katmanı",
        "lbl_dem": "<b>DEM veya Eğim Rasterı:</b>",
        "chk_slope": "Seçilen raster doğrudan yüzde eğim (%) değerlerini içermektedir",
        "lbl_step": "<b>Eğim Çözünürlük Adımı:</b>",
        "grp_preset": "Hazır Bölgeleme Stratejileri (Tek Tıkla Seçin veya Aşağıdan Ağırlıkları Elle Ayarlayın)",
        "lbl_preset_sel": "<b>Bölgeleme Stratejisi Seçin:</b>",
        "grp_g": "G. Bölgeleme Parametreleri ve Manuel Ağırlık Katsayıları (Elle İnce Ayar)",
        "p_k_t": "1) Hedef Alt Bölge Sayısı (K)",
        "p_k_d": "Üretilecek tam ardışık alt bölge adedi (Ör: 25 seçilirse M1..M25, 28 seçilirse M1..M28 eksiksiz üretilir).",
        "p_lu_t": "2) Arazi Kullanımı ve Alt Tür Ağırlığı",
        "p_lu_d": "Konut (düşük/seyrek vs orta/yüksek), ticaret, sanayi, tarım, mezarlık ve donatı adalarını birbirinden ayırır.",
        "p_yapi_t": "3) Yapı / Kat / Yoğunluk Ağırlığı",
        "p_yapi_d": "TAKS, kat adedi, yapı nizamı, kötü yapı oranı ve nüfus yoğunluğu farklı adaları ayırır.",
        "p_dogal_t": "4) Doğal Eşik ve Koruma Ağırlığı",
        "p_dogal_d": "Dere yatağı, eğimli topoğrafya, diri fay ve sit/risk alanlarını bağımsız bölge yapar.",
        "p_geo_t": "5) Mekânsal Kompaktlık & Derli Toplu Form Ağırlığı",
        "p_geo_d": "Artırıldığında bölgeleri yuvarlak/kare ve derli toplu tutar; ince uzun yol şeritleri veya yılan gibi uzayan koridorları kesinlikle engeller.",
        "p_cap_t": "6) Büyük Alan Bütünlüğü & Alan Tavanı",
        "p_cap_d": "Sanayi (OSB) ve geniş ova tarım alanlarının suni bölünmesini önler; büyük makro alanların tek parça ('baba') kalmasını sağlar.",
        "p_bos_t": "7) Boş Arazi & Yeni Plan Potansiyeli Ağırlığı",
        "p_bos_d": "Üzerine yeni plan çizilecek boş arazisi çok olan rezerv alanlar ile dolu/yapılaşmış adaları net ayırır.",
        "p_erisim_t": "8) Donatı Alanlarına Erişim Ağırlığı",
        "p_erisim_d": "Donatı alanlarına (okul, sağlık, park vb.) erişim durumu benzer olan komşu adaları bir arada gruplar.",
        "p_yol_t": "9) Yol Ağı Benzerliği (Genişlik/Kaplama) Ağırlığı",
        "p_yol_d": "Birbirine yakın ve yol genişliği, kaplama türü ile yol kademesi benzer olan adaları birleştirir.",
        "p_odak_t": "10) Sanayi (OSB) Bütünlüğü ve İzolasyonu",
        "p_odak_d": "Sanayi alanlarını parçalamadan tek parça ve son derece kompakt tutar; sanayinin konutla karışmasını ve araya sızmasını engeller.",
        "p_grid_t": "11) Yedek Izgara Boyutu",
        "p_grid_d": "Yol ağı katmanı verilmediğinde kullanılacak varsayılan ızgara hücre genişliği.",
        "grp_h": "H. Kompakt Geometri, Hızlı Özet Katmanı ve Eşleştirme Seçenekleri",
        "chk_medians": "Yol koridorlarını, refüj ve kavşak şeritlerini süz (Yollar yalnızca sınır oluşturur, ince uzun kuyruk olamaz)",
        "chk_excel": "Alt bölgeleri MPYY karakter ve müdahale profilleriyle eşleştir",
        "chk_cells": "Ara işlem katmanı olan imar adası hücrelerini ('Imar_Adasi_Hucreleri') haritaya ekle",
        "grp_i": "I. Alt Bölgeleme Özeti, İç Bütünlük ve Komşu Bölgelerden Ayrım Gerekçeleri",
        "lbl_about_top": "<b>Mekânsal Analiz Metodolojisi, MAUP Çözümü ve Kapsamlı Kullanım El Kitabı:</b>",
        "btn_browser": "🌐 Bu El Kitabını Tam Sayfa Tarayıcıda Aç (HTML)",
        "grp_j": "J. Kapsamlı Metodoloji, MAUP Çözümü ve Adım Adım Kullanım Kılavuzu",
        "fld_kullanim": "Arazi / Yapı Kullanımı",
        "fld_kat": "Kat Adedi / Yüksekliği",
        "fld_yd": "Yapı Nizamı (Bitişik/Ayrık)",
        "fld_durum": "Yapı Fiziksel Durumu",
        "fld_nufus": "Nüfus / Kişi Sayısı Sütunu",
        "rfld_gen": "Yol Genişliği (Metre)",
        "rfld_kap": "Üstyapı / Kaplama Türü",
        "rfld_tur": "Yol Kademelenmesi",
    },
    "zh": {
        "win_title": "城市分区与脆弱性分析工具 — Baran Adsuna",
        "hdr_title": "城市形态分区与多准则脆弱性分析系统",
        "hdr_sub": "⚡ 开发者 / 作者: Baran Adsuna  •  MPYY 形态分区、多准则综合与空间决策支持系统",
        "lbl_mode": "分析深度与模式:",
        "mode_std": "🌱 标准分区模式 (MPYY 形态子分区 - 快速实用)",
        "mode_adv": "🔬 高级综合与干预图集模式 (脆弱性 [E/S/AC]、高程、干预决策与规划对应)",
        "badge_adv": "🔬 <b>高级综合与干预图集已启用:</b> 生成 M1..MK 连续编码、三维脆弱性 (E·S/AC)、DEM高程、干预决策与分析追踪矩阵。",
        "badge_std": "🌱 <b>标准分区模式已启用:</b> 生成 A1..AK 连续形态轮廓匹配、肌理同质性与边界划分依据。",
        "btn_help": "📖 方法论与用户手册 (HTML)",
        "btn_top_adv": "▶ 启动高级综合",
        "btn_top_std": "▶ 启动标准分区",
        "tab_1": "1. 图层、建筑与人口",
        "tab_2": "2. 自然阈值与 DEM",
        "tab_3": "3. 权重与参数设置",
        "tab_4": "4. 边界划分依据与报告",
        "tab_5": "5. 方法论与 MPYY 指南",
        "btn_quick_csv": "⚡ 快速摘要表 (Excel / CSV)",
        "btn_csv": "📊 完整分区表 (Excel / CSV)",
        "btn_matrix": "📋 分析追踪矩阵 (Excel / CSV)",
        "btn_run_adv": "▶ 运行 — 高级综合与干预图集",
        "btn_run_std": "▶ 运行 — 标准形态分区",
        "view_lbl": "视图模式:",
        "rb_quick": "⚡ 快速简明摘要 (快速阅读)",
        "rb_both": "📋 双重对照 (快速摘要 + 详细数据)",
        "rb_detailed": "🔬 仅详细技术验证 (ΔZ 与代码)",
        "filter_ph": "🔍 按分区代码或关键词筛选 (例如: M12, Konut, Fay)...",
        "chk_quick_layer": "同时在地图中添加精简版 'Alt_Bolgeler_Hizli_Ozet' 图层 (仅包含快速阅读列)",
    },
    "es": {
        "win_title": "Herramienta de Zonificación Urbana y Vulnerabilidad — Baran Adsuna",
        "hdr_title": "Analizador de Zonificación Morfológica y Vulnerabilidad Urbana",
        "hdr_sub": "⚡ Desarrollador / Autor: Baran Adsuna  •  Zonificación Morfológica MPYY y Soporte de Decisiones",
        "lbl_mode": "Modo y Profundidad:",
        "mode_std": "🌱 Modo de Zonificación Estándar (Subzonas Morfológicas MPYY - Rápido y Práctico)",
        "mode_adv": "🔬 Modo de Síntesis Avanzada y Atlas de Intervención (Vulnerabilidad [E/S/AC], Elevación y Plan)",
        "badge_adv": "🔬 <b>Síntesis Avanzada Activa:</b> Genera códigos secuenciales M1..MK, Vulnerabilidad 3D (E·S/AC), Elevación DEM, Decisiones y Matriz.",
        "badge_std": "🌱 <b>Modo Estándar Activo:</b> Genera perfiles secuenciales A1..AK, homogeneidad morfológica y justificación de límites.",
        "btn_help": "📖 Metodología y Manual (HTML)",
        "btn_top_adv": "▶ Iniciar Síntesis",
        "btn_top_std": "▶ Zonificar",
        "tab_1": "1. Capas, Edificios y Pob.",
        "tab_2": "2. Umbrales Naturales y DEM",
        "tab_3": "3. Pesos y Ajustes",
        "tab_4": "4. Justificación de Límites y Reporte",
        "tab_5": "5. Metodología y Guía MPYY",
        "btn_quick_csv": "⚡ Resumen Rápido (Excel / CSV)",
        "btn_csv": "📊 Tabla Completa (Excel / CSV)",
        "btn_matrix": "📋 Matriz de Seguimiento (Excel / CSV)",
        "btn_run_adv": "▶ EJECUTAR — SÍNTESIS AVANZADA",
        "btn_run_std": "▶ EJECUTAR — ZONIFICACIÓN ESTÁNDAR",
        "view_lbl": "Vista:",
        "rb_quick": "⚡ Resumen Rápido (Lectura Simple)",
        "rb_both": "📋 Vista Combinada (Resumen + Detalle)",
        "rb_detailed": "🔬 Solo Técnico Detallado (ΔZ y Códigos)",
        "filter_ph": "🔍 Filtrar por código de zona o palabra clave (ej: M12, Konut, Fay)...",
        "chk_quick_layer": "Añadir también capa simplificada 'Alt_Bolgeler_Hizli_Ozet' al mapa (Solo columnas rápidas)",
    },
}


ZONING_PRESETS = [
    {
        "code": "integrated_synthesis",
        "title_en": "1) Integrated Planning & Vulnerability Synthesis (Recommended: Vacant Land + Facility Access + Roads + Industrial Cohesion)",
        "title_tr": "1) Bütünleşik Planlama ve Kırılganlık Sentezi (Önerilen: Boş Arazi + Donatı Erişimi + Yol + Sanayi Bütünlüğü)",
        "short_en": "1) Integrated Synthesis (Recommended)",
        "short_tr": "1) Bütünleşik Sentez (Önerilen)",
        "desc_en": (
            "<b>Integrated Planning & Vulnerability Synthesis:</b> The default multi-criteria strategy for master-plan design and vulnerability assessment. "
            "<b>(1) Vacant vs. Built-Up Separation:</b> separates unbuilt / high-vacancy reserve blocks (candidates for new plans) from consolidated built-up blocks. "
            "<b>(2) Facility Accessibility:</b> groups blocks with similar walking distance to schools, health and green facilities. "
            "<b>(3) Road & Land-Use Nuances:</b> matches road width, surface and hierarchy; distinguishes low / sparse residential from medium / high-density residential and cemeteries; "
            "<b>keeps industrial blocks unified</b> while capturing industry-residential and industry-agriculture transition interfaces."
        ),
        "desc_tr": (
            "<b>Bütünleşik Planlama ve Kırılganlık Sentezi:</b> İmar planı tasarımı ve kırılganlık değerlendirmesi için varsayılan çok kriterli stratejidir. "
            "<b>(1) Boş Arazi - Yapılı Doku Ayrımı:</b> yeni plan yapılabilecek boş / seyrek rezerv adaları ile yapılaşmasını tamamlamış adaları ayırır. "
            "<b>(2) Donatı Alanlarına Erişim:</b> okul, sağlık ve yeşil alanlara yürüme mesafesi benzer olan adaları gruplar. "
            "<b>(3) Yol ve Arazi Kullanımı Ayrıntıları:</b> yol genişliği, kaplama ve kademelenmesi benzer adaları eşleştirir; düşük / seyrek konutu orta-yüksek yoğunluklu konuttan ve mezarlıktan ayırır; "
            "<b>sanayi alanlarını bütün tutar</b>, sanayi-konut ve sanayi-tarım geçiş yüzeylerini belirler."
        ),
        "weights": (2.2, 2.4, 1.6, 2.5, 4.0, 2.8, 2.4, 2.2, 2.5),
    },
    {
        "code": "vacant_plan",
        "title_en": "2) Vacant Land & New Development Potential (Reserve Blocks vs. Built-Up Fabric)",
        "title_tr": "2) Boş Arazi ve Yeni Gelişme Potansiyeli (Rezerv Adalar - Yapılı Doku Ayrımı)",
        "short_en": "2) Vacant Land & Development",
        "short_tr": "2) Boş Arazi ve Gelişme",
        "desc_en": (
            "<b>Vacant Land & New Development Potential:</b> Maximizes the contrast between unbuilt / sparse blocks (candidate areas for new housing, centers and social facilities) "
            "and consolidated neighborhoods that require vulnerability mitigation."
        ),
        "desc_tr": (
            "<b>Boş Arazi ve Yeni Gelişme Potansiyeli:</b> Yeni konut, merkez ve sosyal donatı planlanabilecek boş / seyrek adalar ile "
            "kırılganlık azaltımı gerektiren yapılı mahalleleri en yüksek duyarlılıkla birbirinden ayırır."
        ),
        "weights": (2.0, 2.6, 1.4, 2.4, 4.0, 3.8, 1.8, 1.6, 1.8),
    },
    {
        "code": "access_school",
        "title_en": "3) Facility Accessibility & Service Balance",
        "title_tr": "3) Donatı Alanlarına Erişim ve Donatı Dengesi",
        "short_en": "3) Facility Accessibility",
        "short_tr": "3) Donatı Alanlarına Erişim",
        "desc_en": (
            "<b>Facility & School Accessibility:</b> Clusters neighborhoods by walking distance to schools, primary health care and parks, "
            "separating well-served (&lt;500 m), moderately served (500-1000 m) and under-served (&gt;1000 m) zones."
        ),
        "desc_tr": (
            "<b>Donatı ve Okul Erişilebilirliği:</b> Okul, aile sağlığı merkezi ve parklara yürüme mesafesine göre mahalleleri kümeler; "
            "iyi (&lt;500 m), orta (500-1000 m) ve yetersiz (&gt;1000 m) erişimli bölgeleri ayırır."
        ),
        "weights": (1.8, 2.5, 1.3, 2.3, 4.0, 1.8, 3.8, 2.2, 1.6),
    },
    {
        "code": "agri_protect",
        "title_en": "4) Agricultural Land & Rural Fringe Protection",
        "title_tr": "4) Tarım Arazisi ve Kırsal Çeper Koruma",
        "short_en": "4) Agriculture & Rural Fringe",
        "short_tr": "4) Tarım ve Kırsal Çeper",
        "desc_en": (
            "<b>Agricultural Land & Rural Fringe Protection:</b> Isolates agricultural land, olive groves, orchards, vineyards and pastures from urban residential and commercial blocks, "
            "and highlights agriculture-industry and agriculture-residential edges."
        ),
        "desc_tr": (
            "<b>Tarım Arazisi ve Kırsal Çeper Koruma:</b> Tarım arazilerini, zeytinlikleri, bağ-bahçe ve meraları kentsel konut ve ticaret adalarından ayırır; "
            "tarım-sanayi ve tarım-konut geçiş sınırlarını belirginleştirir."
        ),
        "weights": (3.2, 1.6, 2.2, 2.3, 4.5, 2.2, 1.4, 1.4, 3.5),
    },
    {
        "code": "commercial_focus",
        "title_en": "5) Commercial Core & Mixed-Use Corridors",
        "title_tr": "5) Ticaret Çekirdeği ve Karma Kullanım Akslar",
        "short_en": "5) Commercial & Mixed-Use",
        "short_tr": "5) Ticaret ve Karma Kullanım",
        "desc_en": (
            "<b>Commercial Core & Mixed-Use Corridors:</b> Groups adjacent commercial blocks, traditional bazaar streets and residential + commercial corridors "
            "along primary roads into coherent central-business sub-zones."
        ),
        "desc_tr": (
            "<b>Ticaret Çekirdeği ve Karma Kullanım Akslar:</b> Birbirine komşu ticaret adalarını, geleneksel çarşı sokaklarını ve ana yollar boyunca uzanan "
            "konut + ticaret (karma) akslarını bütünlüklü merkez alt bölgeleri olarak kümeler."
        ),
        "weights": (3.0, 2.2, 1.2, 2.2, 3.8, 1.6, 1.8, 2.6, 3.4),
    },
    {
        "code": "industrial_cluster",
        "title_en": "6) Industrial Cohesion & Transition Interfaces (Industry-Residential / Industry-Agriculture)",
        "title_tr": "6) Sanayi Bütünlüğü ve Geçiş Yüzeyleri (Sanayi-Konut / Sanayi-Tarım)",
        "short_en": "6) Industrial Cohesion",
        "short_tr": "6) Sanayi Bütünlüğü",
        "desc_en": (
            "<b>Industrial Cohesion & Transition Interfaces:</b> Prevents industrial and storage blocks from fragmenting, keeping industrial estates unified, "
            "and delineates buffer zones where industry borders residential or agricultural land."
        ),
        "desc_tr": (
            "<b>Sanayi Bütünlüğü ve Geçiş Yüzeyleri:</b> Sanayi ve depolama adalarının parçalanmasını önleyerek sanayi bölgelerini bütün tutar; "
            "sanayinin konut veya tarım alanlarıyla komşu olduğu tampon yüzeyleri ayrı bölge olarak belirler."
        ),
        "weights": (3.0, 2.0, 1.6, 2.2, 4.2, 2.0, 1.5, 2.0, 3.6),
    },
    {
        "code": "organic_corridor",
        "title_en": "7) Morphological / Natural Corridor & Valley Orientation (Organic Flow)",
        "title_tr": "7) Morfolojik / Doğal Eksen ve Vadi Koridoru (Organik Akış)",
        "short_en": "7) Natural Corridor (Organic)",
        "short_tr": "7) Doğal Eksen (Organik)",
        "desc_en": (
            "<b>Morphological & Natural Corridor:</b> Ideal for study areas along creek/river valleys, fault lines, or linear transport axes. "
            "Sets compactness to <i>Organic</i> mode, allowing zones to stretch naturally along topography and road spines without forcing artificial circularity."
        ),
        "desc_tr": (
            "<b>Morfolojik ve Doğal Eksen:</b> Dere vadileri, fay hatları veya doğrusal ulaşım omurgaları boyunca uzanan alanlar için idealdir. "
            "Kompaktlığı <i>Organik</i> moda alarak bölgelerin yapay daireselliğe zorlanmadan vadi ve cadde boyunca doğal olarak uzamasına izin verir."
        ),
        "weights": (2.2, 2.2, 3.2, 0.8, 4.5, 2.4, 2.0, 2.2, 2.2),
        "compactness_mode": "organic",
    },
    {
        "code": "disaster_vuln",
        "title_en": "8) Seismic / Flood Vulnerability & Natural Thresholds (Fault, Stream, Slope, Building Condition)",
        "title_tr": "8) Deprem / Taşkın Kırılganlığı ve Doğal Eşikler (Fay, Dere, Eğim, Yapı Durumu)",
        "short_en": "8) Disaster Vulnerability",
        "short_tr": "8) Afet Kırılganlığı",
        "desc_en": (
            "<b>Seismic / Flood Vulnerability & Natural Thresholds:</b> Prioritizes active-fault proximity, stream and flood corridors, DEM slope, "
            "heritage (Sit) sensitivity and building condition for the Exposure-Sensitivity-Adaptive Capacity (E, S, AC) synthesis."
        ),
        "desc_tr": (
            "<b>Deprem / Taşkın Kırılganlığı ve Doğal Eşikler:</b> Diri fay yakınlığını, dere ve taşkın koridorlarını, DEM eğimini, "
            "sit duyarlılığını ve yapı durumunu öne çıkararak Maruziyet-Duyarlılık-Uyum Kapasitesi (E, S, AC) ayrımını güçlendirir."
        ),
        "weights": (1.8, 2.6, 3.5, 2.2, 4.0, 1.8, 2.0, 1.6, 2.0),
        "compactness_mode": "organic",
    },
    {
        "code": "manual_custom",
        "title_en": "9) Balanced Standard / Custom Weights",
        "title_tr": "9) Dengeli Standart / Özel Ağırlıklar",
        "short_en": "9) Balanced / Custom",
        "short_tr": "9) Dengeli / Özel",
        "desc_en": (
            "<b>Balanced Standard / Custom Weights:</b> Starts from balanced weights for all criteria. "
            "Every weight below can be adjusted manually at any time."
        ),
        "desc_tr": (
            "<b>Dengeli Standart / Özel Ağırlıklar:</b> Tüm kriterleri dengeli başlangıç ağırlıklarıyla başlatır. "
            "Aşağıdaki her ağırlık istenildiği zaman elle değiştirilebilir."
        ),
        "weights": (1.5, 1.5, 1.5, 2.0, 4.0, 1.5, 1.5, 1.5, 1.5),
        "compactness_mode": "balanced",
    },
]


WEIGHT_DETAILS = {
    "p_k": {
        "tr": {
            "title": "1) Hedef Alt Bölge Sayısı (K)",
            "mech": "Çalışma alanının bölüneceği nihai homojen bölge adedidir. Hiyerarşik Ward kümeleme bu sayıya ulaşana kadar en yakın ve morfolojik olarak uyumlu komşu hücreleri birleştirir.",
            "min_val": "2",
            "min_txt": "Tüm alanı yalnızca 2 dev makro-bölgeye ayırır (ör. Doğu-Batı); yerel doku ve morfoloji farkları silinir.",
            "max_val": "60",
            "max_txt": "Alanı çok küçük mikro ada kümelerine böler; sentez yerine parsel bazlı parçalanma oluşur.",
            "rec": "15 – 35 (1/5000 NİP stüdyosu ve master plan için 20–30 arası idealdir)",
        },
        "en": {
            "title": "1) Target Sub-Zone Count (K)",
            "mech": "The target number of distinct planning sub-zones to be produced. Hierarchical Ward clustering merges adjacent cells until exactly K zones remain.",
            "min_val": "2",
            "min_txt": "Coarsely splits area into 2 macro-zones, losing localized fabric and density nuances.",
            "max_val": "60",
            "max_txt": "Creates 60 micro-clusters, approaching individual block-level fragmentation.",
            "rec": "15 – 35 (Recommended 20–30 for master plans & studio work)",
        },
    },
    "p_lu": {
        "tr": {
            "title": "2) Arazi Kullanımı & Alt Tür Ağırlığı",
            "mech": "Konut (seyrek/düşük/orta/yüksek), ticaret, sanayi, tarım, donatı ve mezarlık adalarını kullanım profiline göre ayrıştırır.",
            "min_val": "0.0",
            "min_txt": "Arazi kullanımı görmezden gelinir; sanayi, ticaret ve konut rastgele aynı bölgede birleşebilir.",
            "max_val": "5.0",
            "max_txt": "Fonksiyon sınırları mutlak bariyer olur; farklı kullanım türleri asla aynı bölgeye dahil edilmez.",
            "rec": "1.8 – 3.0 (Varsayılan: 2.2)",
        },
        "en": {
            "title": "2) Land Use & Sub-Type Weight",
            "mech": "Separates residential (sparse/low/medium/high), commercial, industrial, agricultural, cemetery, and facility blocks.",
            "min_val": "0.0",
            "min_txt": "Land uses ignored; industrial, residential, and agricultural lands may merge freely.",
            "max_val": "5.0",
            "max_txt": "Function boundaries become strict barriers; differing uses are strictly isolated.",
            "rec": "1.8 – 3.0 (Default: 2.2)",
        },
    },
    "p_yapi": {
        "tr": {
            "title": "3) Yapı Düzeni / Kat / Yoğunluk Ağırlığı",
            "mech": "Ortalama kat adedi, taban alanı katsayısı (TAKS), yapı nizamı (ayrık/bitişik) ve kötü yapı oranını homojenleştirir.",
            "min_val": "0.0",
            "min_txt": "Kat ve nizam farkı önemsenmez; 8 katlı bitişik bloklar ile 1 katlı ayrık villalar birleşebilir.",
            "max_val": "5.0",
            "max_txt": "Morfolojik ayrım en üst düzeye çıkar; kat veya nizam farkı olan sokaklar hemen farklı alt bölgelere ayrılır.",
            "rec": "2.0 – 3.2 (Varsayılan: 2.4)",
        },
        "en": {
            "title": "3) Building Typology, TAKS & Density Weight",
            "mech": "Separates blocks differing in story count, TAKS footprint, building order (detached/attached), and structural condition.",
            "min_val": "0.0",
            "min_txt": "Building heights and order ignored; 8-story row apartments and 1-story cottages merge.",
            "max_val": "5.0",
            "max_txt": "Maximum morphological purity; minor height or footprint differences split zones.",
            "rec": "2.0 – 3.2 (Default: 2.4)",
        },
    },
    "p_dogal": {
        "tr": {
            "title": "4) Doğal Eşikler & Koruma Ağırlığı",
            "mech": "DEM eğim sınıfları, dere taşkın koridorları, diri fay hatları ve sit/arkeolojik koruma alanlarını doğal sınır olarak işler.",
            "min_val": "0.0",
            "min_txt": "Doğal eşikler dikkate alınmaz; vadi tabanı ile dik yamaç aynı bölge olarak birleşebilir.",
            "max_val": "5.0",
            "max_txt": "Dere, fay ve sit sınırları aşılamaz birer planlama sınırı oluşturur; riskli alanlar derhal izole edilir.",
            "rec": "1.5 – 3.5 (Varsayılan: 1.6)",
        },
        "en": {
            "title": "4) Natural Thresholds & Protection Weight",
            "mech": "Isolates stream buffers, steep DEM slopes, active fault lines, and heritage (Sit) / flood risk areas.",
            "min_val": "0.0",
            "min_txt": "Topography and natural hazards ignored; steep slopes and valley floors merge together.",
            "max_val": "5.0",
            "max_txt": "Natural constraints become hard boundaries; hazard corridors are strictly segregated.",
            "rec": "1.5 – 3.5 (Default: 1.6)",
        },
    },
    "p_geo": {
        "tr": {
            "title": "5) Mekânsal Kompaktlık & Biçimsel Geometri Ağırlığı",
            "mech": "Komşu hücrelerin yakınlığını ve ortak sınır payını denetler. Bölgelerin haritada derli toplu ve birleşik kalmasını sağlar.",
            "min_val": "0.0",
            "min_txt": "Kompaktlık cezası tamamen kapanır; vadi veya yol boyunca uzayan doğal koridorlar serbestçe oluşur.",
            "max_val": "5.0",
            "max_txt": "Bölgeler aşırı yuvarlak/kare süperbloklara zorlanır; ince uzun doğal koridorlar bile zorla kırpılır.",
            "rec": "1.5 – 3.0 (Varsayılan: 2.5)",
        },
        "en": {
            "title": "5) Spatial Compactness & Form Weight",
            "mech": "Controls spatial contiguity, shared perimeter ratios, and geometric compactness to prevent erratic shapes.",
            "min_val": "0.0",
            "min_txt": "Compactness penalty disabled; elongated organic corridors form freely along terrain or roads.",
            "max_val": "5.0",
            "max_txt": "Zones are forcefully rounded into convex superblocks; linear corridors are broken down.",
            "rec": "1.5 – 3.0 (Default: 2.5)",
        },
    },
    "p_cap": {
        "tr": {
            "title": "6) Makro-Bölge Bütünlüğü & Alan Tavanı Çarpanı",
            "mech": "Bir alt bölgenin ortalama bölge alanına kıyasla ne kadar büyüyebileceğini sınırlar. Büyük sanayi (OSB) ve ovaları bütün tutar.",
            "min_val": "1.5",
            "min_txt": "Tüm bölgeleri neredeyse eşit metrekareye zorlar; geniş organize sanayi siteleri yapay olarak bölünür.",
            "max_val": "20.0",
            "max_txt": "Alan tavanı esnetilir; kesintisiz tarım kuşakları veya dev sanayi alanları tek parça dev bölge olarak kalır.",
            "rec": "3.5 – 5.5 (Varsayılan: 4.0)",
        },
        "en": {
            "title": "6) Macro-Zone Area Cap & Cohesion Multiplier",
            "mech": "Limits maximum sub-zone size relative to mean sub-zone area. Prevents artificial splitting of massive industrial zones.",
            "min_val": "1.5",
            "min_txt": "Forces near-equal zone areas; massive industrial districts or plains are artificially fractured.",
            "max_val": "20.0",
            "max_txt": "Cohesion cap relaxed; continuous agricultural or industrial districts remain single massive entities.",
            "rec": "3.5 – 5.5 (Default: 4.0)",
        },
    },
    "p_bos": {
        "tr": {
            "title": "7) Boş Arazi & Yeni Planlama Potansiyeli Ağırlığı",
            "mech": "İmar adalarındaki boş/yapılaşmamış parsel oranını analiz eder. Yeni plan yapılabilecek rezerv alanlar ile yerleşik dokuyu ayırır.",
            "min_val": "0.0",
            "min_txt": "Parsel doluluk/boşluk oranları dikkate alınmaz; tamamen dolu ada ile bomboş tarla birleşebilir.",
            "max_val": "5.0",
            "max_txt": "Boş rezerv alanlar ile yapılı mahalleler arasında en keskin sınır ayrımı elde edilir.",
            "rec": "2.0 – 3.5 (Varsayılan: 2.8)",
        },
        "en": {
            "title": "7) Vacant Land & New Plan Potential Weight",
            "mech": "Measures vacant parcel ratios within blocks, isolating strategic development reserves from mature urban fabric.",
            "min_val": "0.0",
            "min_txt": "Vacant ratios ignored; fully developed dense quarters merge freely with empty reserve land.",
            "max_val": "5.0",
            "max_txt": "Sharpest possible segregation between unbuilt development reserves and consolidated neighborhoods.",
            "rec": "2.0 – 3.5 (Default: 2.8)",
        },
    },
    "p_erisim": {
        "tr": {
            "title": "8) Donatı Alanlarına Erişim Ağırlığı",
            "mech": "Okul, park ve sağlık ocaklarına olan yürüme mesafelerini (MPYY 500m/1000m hizmet yarıçapı) değerlendirir.",
            "min_val": "0.0",
            "min_txt": "Donatı mesafesi önemsenmez; donatısı zengin mahalle ile donatı yoksunu mahalle birleşebilir.",
            "max_val": "5.0",
            "max_txt": "Donatı erişim mesafeleri birincil eşik olur; hizmet alanlar ile hizmet açığı olanlar kesin ayrılır.",
            "rec": "1.8 – 3.0 (Varsayılan: 2.4)",
        },
        "en": {
            "title": "8) Facility Accessibility Weight",
            "mech": "Evaluates walking distance to schools, parks, and healthcare based on MPYY 500m/1000m service radii.",
            "min_val": "0.0",
            "min_txt": "Walking access ignored; well-served quarters and facility deserts merge indiscriminately.",
            "max_val": "5.0",
            "max_txt": "Service radii strictly dictate boundaries, cleanly separating well-served from underserved zones.",
            "rec": "1.8 – 3.0 (Default: 2.4)",
        },
    },
    "p_yol": {
        "tr": {
            "title": "9) Yol Ağı Benzerliği & Hiyerarşisi Ağırlığı",
            "mech": "Yol genişliği, kaplama cinsi (asfalt, parke vb.) ve sokak kademelenmesi benzer olan adaları bir araya getirir.",
            "min_val": "0.0",
            "min_txt": "Yol genişliği ve kaplama cinsi sınır ayrımında hiçbir etki yapmaz.",
            "max_val": "5.0",
            "max_txt": "Geniş bulvarlar ve kaplama değişimleri anında bölge sınırına dönüşür; ulaşım dokuları ayrışır.",
            "rec": "1.5 – 3.0 (Varsayılan: 2.2)",
        },
        "en": {
            "title": "9) Road Hierarchy & Network Similarity Weight",
            "mech": "Groups neighboring blocks with similar road width, surface pavement (asphalt, stone), and street hierarchy.",
            "min_val": "0.0",
            "min_txt": "Road widths and surface types have zero influence on zone clustering.",
            "max_val": "5.0",
            "max_txt": "Broad avenues and pavement changes immediately trigger zone boundaries.",
            "rec": "1.5 – 3.0 (Default: 2.2)",
        },
    },
    "p_odak": {
        "tr": {
            "title": "10) Sanayi (OSB) Bütünlüğü ve İzolasyonu",
            "mech": "Sanayi ve depolama alanlarının konut içine karışmasını engeller; sanayiyi tek parça ve kompakt tutar.",
            "min_val": "0.0",
            "min_txt": "Sanayi adaları çevredeki konut veya tarım dokusunun içine dağılarak eriyebilir.",
            "max_val": "5.0",
            "max_txt": "Sanayi alanları katı bir blok halinde kenetlenir ve çevresindeki konuttan tamamen izole edilir.",
            "rec": "2.0 – 3.5 (Varsayılan: 2.5)",
        },
        "en": {
            "title": "10) Industrial (OIZ) Cohesion & Isolation",
            "mech": "Prevents industrial/storage intrusion into residential zones, enforcing cohesive industrial clusters.",
            "min_val": "0.0",
            "min_txt": "Industrial blocks may be dissolved into surrounding residential or agricultural zones.",
            "max_val": "5.0",
            "max_txt": "Industrial zones are locked into impenetrable clusters strictly isolated from housing.",
            "rec": "2.0 – 3.5 (Default: 2.5)",
        },
    },
    "p_grid": {
        "tr": {
            "title": "11) Yedek Izgara Boyutu (m)",
            "mech": "Yol ağı katmanı verilmediğinde veya grid analizi seçildiğinde kullanılacak varsayılan ızgara hücre genişliğidir.",
            "min_val": "50m",
            "min_txt": "Çok ince taneli mikro-hücreler üretir; analiz süresi uzar ancak detay artar.",
            "max_val": "2000m",
            "max_txt": "Çok kaba 2 kilometrelik makro-hücreler üretir; hızlıdır fakat detaylar kaybolur.",
            "rec": "100m – 300m (Varsayılan: 200 m)",
        },
        "en": {
            "title": "11) Fallback Grid Size (m)",
            "mech": "Default grid cell width in meters used only when no road network vector layer is provided.",
            "min_val": "50m",
            "min_txt": "Generates very fine micro-cells; high detail but increases processing time.",
            "max_val": "2000m",
            "max_txt": "Produces coarse 2 km macro-cells; very fast but details are smoothed out.",
            "rec": "100m – 300m (Default: 200 m)",
        },
    },
}


class BolgelemeDialog(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        icon_path = os.path.join(self.plugin_dir, "icon.svg")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.setWindowTitle("Urban Zoning & Vulnerability Analyzer — Baran Adsuna")
        flags = self.windowFlags()
        if WindowMinimizeButtonHint:
            flags |= WindowMinimizeButtonHint
        if WindowMaximizeButtonHint:
            flags |= WindowMaximizeButtonHint
        self.setWindowFlags(flags)
        self.setMinimumSize(780, 500)
        self.setStyleSheet(STYLE)
        self.records = []
        self.quick_records = []
        self._pipeline_logs = []
        self.last_zones = []
        self.current_lang = "en"
        self._sample_cache = {}
        self.build_ui()
        self.set_language("en")
        self.fit_to_screen()

    def fit_to_screen(self):
        try:
            screen = QApplication.primaryScreen()
            if self.iface and hasattr(self.iface, "mainWindow") and self.iface.mainWindow() and hasattr(self.iface.mainWindow(), "screen") and self.iface.mainWindow().screen():
                screen = self.iface.mainWindow().screen()
            if screen:
                avail = screen.availableGeometry()
                w = min(920, int(avail.width() * 0.78))
                h = min(680, int(avail.height() * 0.78))
                self.resize(max(780, w), max(500, h))
                x = avail.x() + (avail.width() - self.width()) // 2
                y = avail.y() + (avail.height() - self.height()) // 2
                self.move(max(avail.x(), x), max(avail.y() + 10, y))
            else:
                self.resize(880, 620)
        except (AttributeError, RuntimeError):
            self.resize(880, 620)

    # ------------------------------------------------------------ arayüz
    def build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        # Üst Başlık Kartı (3D İkon + Başlık + Hızlı Çalıştır Düğmesi)
        hdr = QFrame()
        hdr.setStyleSheet(
            "QFrame { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0f172a, stop:0.6 #1e293b, stop:1 #0f172a); "
            "border: 1px solid #334155; border-radius: 8px; padding: 6px 12px; }"
        )
        h_lay = QHBoxLayout(hdr)
        h_lay.setContentsMargins(8, 6, 8, 6)
        h_lay.setSpacing(12)

        # 3D İkon Gösterimi
        icon_lbl = QLabel()
        icon_path = os.path.join(self.plugin_dir, "icon.svg")
        if os.path.exists(icon_path):
            pix = QIcon(icon_path).pixmap(QSize(50, 50))
            icon_lbl.setPixmap(pix)
        icon_lbl.setFixedSize(52, 52)
        icon_lbl.setStyleSheet("border: none; background: transparent;")
        h_lay.addWidget(icon_lbl)

        t_box = QVBoxLayout()
        t_box.setSpacing(4)
        self.lbl_hdr_title = QLabel("Kentsel Bölgeleme ve Kırılganlık Analiz Aracı")
        self.lbl_hdr_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #f8fafc; border: none; background: transparent; padding: 1px 0px;")
        self.lbl_hdr_sub = QLabel("⚡ Geliştirici / Yazar: Baran Adsuna  •  MPYY Uyumlu Morfolojik Bölgeleme, Çok Kriterli Sentez ve Karar Destek Sistemi")
        self.lbl_hdr_sub.setWordWrap(True)
        self.lbl_hdr_sub.setMinimumHeight(20)
        self.lbl_hdr_sub.setStyleSheet("color: #38bdf8; font-size: 11px; font-weight: 600; border: none; background: transparent; padding: 1px 0px;")
        t_box.addWidget(self.lbl_hdr_title)
        t_box.addWidget(self.lbl_hdr_sub)

        mode_box = QHBoxLayout()
        mode_box.setSpacing(8)
        self.lbl_mode_title = QLabel("Analiz Derinliği & Mod:")
        self.lbl_mode_title.setStyleSheet("color: #38bdf8; font-weight: bold; font-size: 11px; border: none; background: transparent;")
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItem("🌱 Standart Bölgeleme Modu (MPYY Morfolojik Alt Bölgeler - Hızlı & Pratik)", "standard")
        self.cmb_mode.addItem("🔬 İleri Sentez & Müdahale Atlası Modu (Kırılganlık [E/S/AC], Rakım, Müdahale Kararları & Plan Karşılığı)", "advanced")
        self.cmb_mode.setCurrentIndex(1)
        self.cmb_mode.setStyleSheet("QComboBox { background-color: #1e293b; color: #f8fafc; border: 1px solid #475569; border-radius: 4px; padding: 2px 8px; font-size: 11px; font-weight: 600; }")
        mode_box.addWidget(self.lbl_mode_title)
        mode_box.addWidget(self.cmb_mode, 1)
        t_box.addLayout(mode_box)

        self.lbl_mode_badge = QLabel()
        self.lbl_mode_badge.setWordWrap(True)
        self.lbl_mode_badge.setMinimumHeight(38)
        t_box.addWidget(self.lbl_mode_badge)

        # Dil Seçici (Varsayılan: English [EN], Türkçe [TR], 中文 [ZH], Español [ES])
        self.cmb_lang = QComboBox()
        self.cmb_lang.setIconSize(QSize(20, 14))
        self.cmb_lang.addItem(create_flag_icon("en"), "English (EN)", "en")
        self.cmb_lang.addItem(create_flag_icon("tr"), "Türkçe (TR)", "tr")
        self.cmb_lang.addItem(create_flag_icon("zh"), "中文 (ZH)", "zh")
        self.cmb_lang.addItem(create_flag_icon("es"), "Español (ES)", "es")
        self.cmb_lang.setMinimumWidth(135)
        self.cmb_lang.setStyleSheet(
            "QComboBox { background-color: #1e293b; color: #f8fafc; border: 1px solid #38bdf8; "
            "border-radius: 6px; padding: 4px 8px; font-weight: bold; font-size: 11px; }"
        )
        self.cmb_lang.currentIndexChanged.connect(lambda _: self.set_language(self.cmb_lang.currentData()))

        self.btn_help = QPushButton("📖 Metodoloji ve Kullanım El Kitabı (HTML)")
        self.btn_help.setObjectName("helpBtn")
        if PointingHandCursor is not None:
            self.btn_help.setCursor(PointingHandCursor)
        self.btn_help.clicked.connect(self.open_html_guide)

        self.btn_top_run = QPushButton("▶ Hemen Çalıştır")
        self.btn_top_run.setObjectName("runBtn")
        if PointingHandCursor is not None:
            self.btn_top_run.setCursor(PointingHandCursor)
        self.btn_top_run.clicked.connect(self.run)

        right_hdr_col = QVBoxLayout()
        right_hdr_col.setSpacing(6)
        top_btn_row = QHBoxLayout()
        top_btn_row.setSpacing(6)
        top_btn_row.addWidget(self.cmb_lang)
        top_btn_row.addWidget(self.btn_help)
        right_hdr_col.addLayout(top_btn_row)
        right_hdr_col.addWidget(self.btn_top_run)

        h_lay.addLayout(t_box, 1)
        h_lay.addLayout(right_hdr_col)
        root.addWidget(hdr)

        # Sekmeler
        self.tabs = QTabWidget()
        self.tabs.addTab(wrap_in_scroll(self.page_layers()), "1. Katmanlar, Yapılar ve Nüfus")
        self.tabs.addTab(wrap_in_scroll(self.page_extra()), "2. Doğal Eşikler ve DEM")
        self.tabs.addTab(wrap_in_scroll(self.page_settings()), "3. Ağırlıklar ve Ayarlar")
        self.tabs.addTab(self.page_results(), "4. Sınır Ayrım Gerekçeleri Raporu")
        self.tabs.addTab(self.page_about(), "5. Metodoloji ve MPYY Kılavuzu")
        root.addWidget(self.tabs, 1)

        # Sabit Alt Çalıştırma Çubuğu
        bot_frame = QFrame()
        bot_frame.setStyleSheet(
            "QFrame { background-color: #ffffff; border: 1px solid #cbd5e1; border-radius: 8px; padding: 4px; }"
        )
        bot = QHBoxLayout(bot_frame)
        bot.setContentsMargins(10, 6, 10, 6)
        bot.setSpacing(8)

        self.progress = QProgressBar()
        self.progress.setValue(0)

        self.btn_quick_csv = QPushButton("⚡ Hızlı Özet (Sade CSV)")
        self.btn_quick_csv.setObjectName("exportBtn")
        if PointingHandCursor is not None:
            self.btn_quick_csv.setCursor(PointingHandCursor)
        self.btn_quick_csv.setEnabled(False)
        self.btn_quick_csv.clicked.connect(self.export_quick_csv)

        self.btn_csv = QPushButton("📊 Detaylı Tablo (CSV)")
        self.btn_csv.setObjectName("exportBtn")
        if PointingHandCursor is not None:
            self.btn_csv.setCursor(PointingHandCursor)
        self.btn_csv.setEnabled(False)
        self.btn_csv.clicked.connect(self.export_csv)

        self.btn_matrix = QPushButton("📋 İzleme Matrisi (CSV)")
        self.btn_matrix.setObjectName("matrixBtn")
        if PointingHandCursor is not None:
            self.btn_matrix.setCursor(PointingHandCursor)
        self.btn_matrix.setEnabled(False)
        self.btn_matrix.clicked.connect(self.export_analysis_matrix)

        self.btn_run = QPushButton("▶ ÇALIŞTIR — İLERİ SENTEZ (M1..M28)")
        self.btn_run.setObjectName("runBtn")
        if PointingHandCursor is not None:
            self.btn_run.setCursor(PointingHandCursor)
        self.btn_run.clicked.connect(self.run)

        bot.addWidget(self.progress, 1)
        bot.addWidget(self.btn_quick_csv)
        bot.addWidget(self.btn_csv)
        bot.addWidget(self.btn_matrix)
        bot.addWidget(self.btn_run)
        root.addWidget(bot_frame)

        self.cmb_mode.currentIndexChanged.connect(self._on_mode_changed)
        self._on_mode_changed()

    def set_language(self, lang_code):
        if lang_code not in UI_TRANSLATIONS:
            lang_code = "en"
        self.current_lang = lang_code
        if hasattr(self, "cmb_lang") and self.cmb_lang.currentData() != lang_code:
            idx = self.cmb_lang.findData(lang_code)
            if idx >= 0:
                self.cmb_lang.blockSignals(True)
                self.cmb_lang.setCurrentIndex(idx)
                self.cmb_lang.blockSignals(False)
        tr = UI_TRANSLATIONS[lang_code]
        fb = UI_TRANSLATIONS["en"]

        def g(k):
            return tr.get(k, fb.get(k, ""))

        self.setWindowTitle(g("win_title"))
        if hasattr(self, "lbl_hdr_title"):
            self.lbl_hdr_title.setText(g("hdr_title"))
        if hasattr(self, "lbl_hdr_sub"):
            self.lbl_hdr_sub.setText(g("hdr_sub"))
        if hasattr(self, "lbl_mode_title"):
            self.lbl_mode_title.setText(g("lbl_mode"))
        if hasattr(self, "cmb_mode"):
            self.cmb_mode.blockSignals(True)
            self.cmb_mode.setItemText(0, g("mode_std"))
            self.cmb_mode.setItemText(1, g("mode_adv"))
            self.cmb_mode.blockSignals(False)
        if hasattr(self, "btn_help"):
            self.btn_help.setText(g("btn_help"))
        if hasattr(self, "tabs"):
            for idx, key in enumerate(("tab_1", "tab_2", "tab_3", "tab_4", "tab_5")):
                self.tabs.setTabText(idx, g(key))
        if hasattr(self, "btn_quick_csv"):
            self.btn_quick_csv.setText(g("btn_quick_csv"))
        if hasattr(self, "btn_csv"):
            self.btn_csv.setText(g("btn_csv"))
        if hasattr(self, "btn_matrix"):
            self.btn_matrix.setText(g("btn_matrix"))
        if hasattr(self, "lbl_view_mode"):
            self.lbl_view_mode.setText(f"<b>{g('view_lbl')}</b>")
        if hasattr(self, "rb_view_quick"):
            self.rb_view_quick.setText(g("rb_quick"))
        if hasattr(self, "rb_view_both"):
            self.rb_view_both.setText(g("rb_both"))
        if hasattr(self, "rb_view_detailed"):
            self.rb_view_detailed.setText(g("rb_detailed"))
        if hasattr(self, "txt_filter"):
            self.txt_filter.setPlaceholderText(g("filter_ph"))
        if hasattr(self, "chk_quick_layer"):
            self.chk_quick_layer.setText(g("chk_quick_layer"))

        # Sekme 1, 2, 3, 4, 5 iç grup kutuları, etiketler ve parametre kartları
        for attr_name, key in (
            ("grp_a", "grp_a"), ("lbl_bnd", "lbl_bnd"), ("lbl_road", "lbl_road"), ("lbl_block", "lbl_block"),
            ("btn_auto_main", "btn_auto_main"), ("grp_b", "grp_b"), ("chk_use_bldg", "chk_use_bldg"),
            ("lbl_bldg_lyr", "lbl_bldg_lyr"), ("grp_c", "grp_c"), ("rb_pop_col", "rb_pop_1"),
            ("rb_pop_manual", "rb_pop_2"), ("rb_pop_perbldg", "rb_pop_3"), ("lbl_man_pop", "lbl_man_pop"),
            ("lbl_pop_algo_info", "lbl_pop_algo_info"),
            ("lbl_per_bldg", "lbl_per_bldg"), ("grp_d1", "grp_d1"), ("grp_d2", "grp_d2"),
            ("grp_e", "grp_e"), ("btn_auto_nat", "btn_auto_nat"), ("btn_add_row", "btn_add_row"),
            ("btn_del_row", "btn_del_row"), ("grp_f", "grp_f"), ("lbl_dem", "lbl_dem"),
            ("chk_slope", "chk_slope"), ("lbl_step", "lbl_step"),
            ("grp_preset", "grp_preset"), ("lbl_preset_sel", "lbl_preset_sel"),
            ("grp_g", "grp_g"),
            ("grp_h", "grp_h"), ("chk_filter_medians", "chk_medians"), ("chk_excel", "chk_excel"),
            ("chk_cells", "chk_cells"), ("grp_i", "grp_i"), ("lbl_about_top", "lbl_about_top"),
            ("btn_browser", "btn_browser"), ("grp_j", "grp_j"),
        ):
            w_obj = getattr(self, attr_name, None)
            if w_obj is not None and g(key):
                if isinstance(w_obj, QGroupBox):
                    w_obj.setTitle(g(key))
                else:
                    w_obj.setText(g(key))

        if hasattr(self, "cmb_preset"):
            is_tr = (lang_code == "tr")
            self.cmb_preset.blockSignals(True)
            for idx_p, pr in enumerate(ZONING_PRESETS):
                self.cmb_preset.setItemText(idx_p, pr["title_tr"] if is_tr else pr["title_en"])
            self.cmb_preset.blockSignals(False)
            if hasattr(self, "_preset_quick_btns"):
                for btn_p, pr in self._preset_quick_btns:
                    btn_p.setText(pr["short_tr"] if is_tr else pr["short_en"])
            self._update_preset_description_only()

        if hasattr(self, "cmb_compactness_mode"):
            cur_cm = self.cmb_compactness_mode.currentData() or "balanced"
            self.cmb_compactness_mode.blockSignals(True)
            self.cmb_compactness_mode.clear()
            if is_tr:
                self.cmb_compactness_mode.addItem("🌿 Morfolojik / Doğal Eksen (Vadi & Koridor Serbestliği)", "organic")
                self.cmb_compactness_mode.addItem("⚖️ Dengeli Standart (Planlama Normu)", "balanced")
                self.cmb_compactness_mode.addItem("🎯 Yüksek Kompaktlık (Dairesel / Dörtgen Süperbloklar)", "strict")
            else:
                self.cmb_compactness_mode.addItem("🌿 Morphological / Natural Axis (Organic Valley Flow)", "organic")
                self.cmb_compactness_mode.addItem("⚖️ Balanced Standard (Planning Norm)", "balanced")
                self.cmb_compactness_mode.addItem("🎯 High Compactness (Convex / Circular Superblocks)", "strict")
            idx_cm = self.cmb_compactness_mode.findData(cur_cm)
            if idx_cm >= 0:
                self.cmb_compactness_mode.setCurrentIndex(idx_cm)
            else:
                self.cmb_compactness_mode.setCurrentIndex(1)
            self.cmb_compactness_mode.blockSignals(False)

        if hasattr(self, "_advanced_cards"):
            for k_prefix, c_data in self._advanced_cards.items():
                det = c_data["details"]
                d_lang = det["tr"] if is_tr else det["en"]
                c_data["title_label"].setText(f"<b>{d_lang['title']}</b>")
                how_txt = f"<b>{('Çalışma Mantığı:' if is_tr else 'How it Works:')}</b> {d_lang['mech']}"
                ext_txt = (
                    f"<b>Min ({d_lang['min_val']}):</b> {d_lang['min_txt']}  •  "
                    f"<b>Maks ({d_lang['max_val']}):</b> {d_lang['max_txt']}<br/>"
                    f"<b>{('Önerilen:' if is_tr else 'Recommended:')}</b> <span style='color: #0369a1;'>{d_lang['rec']}</span>"
                )
                c_data["how_label"].setText(how_txt)
                c_data["extremes_label"].setText(ext_txt)
                if "update_badge" in c_data:
                    c_data["update_badge"]()

        if hasattr(self, "tbl"):
            self.tbl.setHorizontalHeaderLabels([g("tbl_col_0"), g("tbl_col_1"), g("tbl_col_2")])

        if hasattr(self, "_param_card_labels"):
            for k_prefix, (lbl_t, lbl_d) in self._param_card_labels.items():
                lbl_t.setText(f"<b>{g(k_prefix + '_t')}</b>")
                lbl_d.setText(g(k_prefix + "_d"))

        if hasattr(self, "_fld_row_labels"):
            fld_map = {
                "kullanim": "fld_kullanim", "kat": "fld_kat", "yd": "fld_yd",
                "durum": "fld_durum", "nufus": "fld_nufus",
                "r_genislik": "rfld_gen", "r_kaplama": "rfld_kap", "r_tur": "rfld_tur",
            }
            for k, lbl_list in self._fld_row_labels.items():
                tk = fld_map.get(k)
                if tk and g(tk):
                    for l_w in lbl_list:
                        l_w.setText(f"<b>{g(tk)}:</b>")

        self._on_mode_changed()
        if getattr(self, "last_zones", None):
            self.refresh_report_view()

    def _on_mode_changed(self):
        """Kullanıcı analiz modunu değiştirdiğinde arayüzü, rozeti ve butonları dinamik günceller."""
        tr = UI_TRANSLATIONS.get(getattr(self, "current_lang", "en"), UI_TRANSLATIONS["en"])
        is_adv = (self.cmb_mode.currentData() == "advanced") if hasattr(self, "cmb_mode") else True
        k_val = self.spn_k.value() if hasattr(self, "spn_k") else 28
        if is_adv:
            if hasattr(self, "lbl_mode_badge"):
                self.lbl_mode_badge.setText(tr["badge_adv"].replace("MK", f"M{k_val}"))
                self.lbl_mode_badge.setStyleSheet(
                    "color: #bae6fd; font-size: 11px; background: rgba(56, 189, 248, 0.12); "
                    "padding: 5px 8px; border-radius: 4px; border: 1px solid rgba(56, 189, 248, 0.4);"
                )
            if hasattr(self, "btn_run"):
                self.btn_run.setText(f"{tr['btn_run_adv']} (M1..M{k_val})")
            if hasattr(self, "btn_top_run"):
                self.btn_top_run.setText(tr["btn_top_adv"])
            if hasattr(self, "btn_matrix"):
                self.btn_matrix.setVisible(True)
        else:
            if hasattr(self, "lbl_mode_badge"):
                self.lbl_mode_badge.setText(tr["badge_std"].replace("AK", f"A{k_val}"))
                self.lbl_mode_badge.setStyleSheet(
                    "color: #bbf7d0; font-size: 11px; background: rgba(34, 197, 94, 0.12); "
                    "padding: 5px 8px; border-radius: 4px; border: 1px solid rgba(34, 197, 94, 0.4);"
                )
            if hasattr(self, "btn_run"):
                self.btn_run.setText(f"{tr['btn_run_std']} (A1..A{k_val})")
            if hasattr(self, "btn_top_run"):
                self.btn_top_run.setText(tr["btn_top_std"])
            if hasattr(self, "btn_matrix"):
                self.btn_matrix.setVisible(False)

    def _make_field_row_widget(self, combo, info_label):
        """Açılır kutu ve önizleme rozetini sıkışmadan ferah biçimde hizalayan yardımcı kapsayıcı."""
        row_w = QWidget()
        row_l = QVBoxLayout(row_w)
        row_l.setContentsMargins(0, 2, 0, 4)
        row_l.setSpacing(4)
        combo.setSizePolicy(PolicyExpanding, PolicyFixed)
        info_label.setObjectName("badgeInfo")
        info_label.setWordWrap(True)
        row_l.addWidget(combo)
        row_l.addWidget(info_label)
        return row_w

    # ------------------------------------------------------------ 1. Sekme: Ana Katmanlar + Opsiyonel Yapılar + Nüfus
    def page_layers(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(10)
        self._fld_row_labels = {}

        # A. Ana Katmanlar
        self.grp_a = QGroupBox("A. Core Planning Layers (EPSG:5253)")
        f = QFormLayout(self.grp_a)
        f.setContentsMargins(12, 10, 12, 10)
        f.setHorizontalSpacing(14)
        f.setVerticalSpacing(8)
        f.setLabelAlignment(AlignLeft | AlignVCenter)

        self.cmb_boundary = QgsMapLayerComboBox()
        self.cmb_boundary.setAllowEmptyLayer(True)
        self.cmb_boundary.setFilters(QgsMapLayerProxyModel.Filter.PolygonLayer)

        self.cmb_road = QgsMapLayerComboBox()
        self.cmb_road.setAllowEmptyLayer(True)
        self.cmb_road.setFilters(QgsMapLayerProxyModel.Filter.LineLayer)

        self.cmb_block = QgsMapLayerComboBox()
        self.cmb_block.setAllowEmptyLayer(True)
        self.cmb_block.setFilters(QgsMapLayerProxyModel.Filter.PolygonLayer)

        self.btn_auto_main = QPushButton("⚡ Auto-Match All Project Layers, Buildings & Natural Thresholds")
        if PointingHandCursor is not None:
            self.btn_auto_main.setCursor(PointingHandCursor)
        self.btn_auto_main.clicked.connect(self.auto_populate_all_layers)

        self.lbl_bnd = QLabel("<b>1) Plan / Study Boundary (Polygon):</b>")
        self.lbl_road = QLabel("<b>2) Road / Street Network (Line):</b>")
        self.lbl_block = QLabel("<b>3) Urban Blocks / Land Use (Polygon):</b>")
        f.addRow(self.lbl_bnd, self.cmb_boundary)
        f.addRow(self.lbl_road, self.cmb_road)
        f.addRow(self.lbl_block, self.cmb_block)
        f.addRow("", self.btn_auto_main)
        lay.addWidget(self.grp_a)

        # B. Opsiyonel Tekil Yapılar (Binalar) Katmanı Bölümü
        self.grp_b = QGroupBox("B. Optional Individual Buildings Layer")
        v_bldg = QVBoxLayout(self.grp_b)
        v_bldg.setContentsMargins(12, 10, 12, 10)
        v_bldg.setSpacing(8)

        self.chk_use_bldg = QCheckBox("Use a separate 'Buildings / Footprints' layer for TAKS, floors, building order, structural condition & population")
        self.chk_use_bldg.setChecked(False)
        v_bldg.addWidget(self.chk_use_bldg)

        self.bldg_panel = QFrame()
        self.bldg_panel.setStyleSheet("QFrame { background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; }")
        f_bldg = QFormLayout(self.bldg_panel)
        f_bldg.setContentsMargins(12, 10, 12, 10)
        f_bldg.setHorizontalSpacing(14)
        f_bldg.setVerticalSpacing(6)

        self.cmb_bldg = QgsMapLayerComboBox()
        self.cmb_bldg.setAllowEmptyLayer(True)
        self.cmb_bldg.setFilters(QgsMapLayerProxyModel.Filter.PolygonLayer)
        self.lbl_bldg_lyr = QLabel("<b>Individual Buildings Layer:</b>")
        f_bldg.addRow(self.lbl_bldg_lyr, self.cmb_bldg)

        self.bfld = {}
        self.bfld_info = {}
        for key, label, _, _ in BLDG_FIELD_DEFS:
            c = QgsFieldComboBox()
            c.setAllowEmptyFieldName(True)
            info_lbl = QLabel("<i>Waiting for building layer...</i>")
            c.fieldChanged.connect(lambda fname, k=key: self.update_single_field_preview(self.cmb_bldg.currentLayer(), k, fname, mode="bldg"))
            self.bfld[key] = c
            self.bfld_info[key] = info_lbl
            row_lbl = QLabel(f"<b>{label}:</b>")
            self._fld_row_labels.setdefault(key, []).append(row_lbl)
            f_bldg.addRow(row_lbl, self._make_field_row_widget(c, info_lbl))

        self.bldg_panel.setVisible(False)
        self.chk_use_bldg.toggled.connect(self.bldg_panel.setVisible)
        v_bldg.addWidget(self.bldg_panel)
        lay.addWidget(self.grp_b)

        # C. Nüfus Verisi Giriş Bölümü (Sadece Elle Toplam Nüfus & Konut/Karma Ada + Bina Sayısı + Ada Büyüklüğü Algoritması)
        self.grp_c = QGroupBox("C. Estimated Population Distribution (Residential & Mixed Blocks by Building Count & Block Area)")
        v_pop = QVBoxLayout(self.grp_c)
        v_pop.setContentsMargins(12, 10, 12, 10)
        v_pop.setSpacing(6)

        self.pop_btn_group = QButtonGroup(self)
        self.rb_pop_col = QRadioButton("1) Auto from Attribute Column (Use population column; fallback to manual total below if empty)")
        self.rb_pop_manual = QRadioButton("2) Enter Total Study Area Population Manually (Distributed only to residential & mixed blocks; Industry/Agri = 0)")
        self.rb_pop_perbldg = QRadioButton("3) Estimate by Average Persons per Floor (Building count × floor count × persons/floor)")
        self.rb_pop_manual.setChecked(True)
        self.rb_pop_col.setVisible(False)
        self.rb_pop_manual.setVisible(False)
        self.rb_pop_perbldg.setVisible(False)

        self.pop_btn_group.addButton(self.rb_pop_col, 1)
        self.pop_btn_group.addButton(self.rb_pop_manual, 2)
        self.pop_btn_group.addButton(self.rb_pop_perbldg, 3)

        pop_box = QFrame()
        pop_box.setStyleSheet("QFrame { background-color: #f0f9ff; border: 1px solid #bae6fd; border-radius: 6px; padding: 6px; }")
        pop_inputs_lay = QHBoxLayout(pop_box)
        pop_inputs_lay.setContentsMargins(10, 6, 10, 6)
        pop_inputs_lay.setSpacing(14)

        self.lbl_man_pop = QLabel("<b>Manual Total Population:</b>")
        self.lbl_man_pop.setStyleSheet("border: none; background: transparent; color: #0f172a;")
        pop_inputs_lay.addWidget(self.lbl_man_pop)
        self.spn_manual_pop = QSpinBox()
        self.spn_manual_pop.setRange(0, 10000000)
        self.spn_manual_pop.setSingleStep(500)
        self.spn_manual_pop.setValue(65000)
        self.spn_manual_pop.setMinimumWidth(145)
        pop_inputs_lay.addWidget(self.spn_manual_pop)

        self.lbl_pop_algo_info = QLabel(
            "⚡ <b>Estimated Population Algorithm:</b> Distributes the total population exclusively to <b>Residential</b> and "
            "<b>Mixed (Residential + Commercial)</b> urban blocks according to each block's <b>building count</b>, "
            "<b>block area (m²)</b>, and <b>floor count</b> (Industry, Agriculture & Facility = 0)."
        )
        self.lbl_pop_algo_info.setWordWrap(True)
        self.lbl_pop_algo_info.setStyleSheet("border: none; background: transparent; color: #0369a1; font-size: 11px;")
        pop_inputs_lay.addWidget(self.lbl_pop_algo_info, 1)

        self.lbl_per_bldg = QLabel("<b>Persons per Floor:</b>")
        self.lbl_per_bldg.setVisible(False)
        self.spn_per_bldg = QDoubleSpinBox()
        self.spn_per_bldg.setRange(0.0, 100.0)
        self.spn_per_bldg.setSingleStep(0.5)
        self.spn_per_bldg.setValue(2.85)
        self.spn_per_bldg.setVisible(False)

        v_pop.addWidget(pop_box)
        self.rb_pop_col.toggled.connect(self._update_pop_mode_ui)
        self.rb_pop_manual.toggled.connect(self._update_pop_mode_ui)
        self.rb_pop_perbldg.toggled.connect(self._update_pop_mode_ui)
        self._update_pop_mode_ui()
        lay.addWidget(self.grp_c)

        # D. İmar Adası ve Yol Ağı Sütun Eşleştirmesi (Ferah Yan Yana Kartlar)
        mid_lay = QHBoxLayout()
        mid_lay.setSpacing(10)

        self.grp_d1 = QGroupBox("D1. Urban Block Attributes (Auto-Matched)")
        f_blk = QFormLayout(self.grp_d1)
        f_blk.setContentsMargins(12, 10, 12, 10)
        f_blk.setHorizontalSpacing(12)
        f_blk.setVerticalSpacing(6)

        self.fld = {}
        self.fld_info = {}
        for key, label, _, _ in FIELD_DEFS:
            c = QgsFieldComboBox()
            c.setAllowEmptyFieldName(True)
            info_lbl = QLabel("<i>Waiting...</i>")
            c.fieldChanged.connect(lambda fname, k=key: self.update_single_field_preview(self.cmb_block.currentLayer(), k, fname, mode="block"))
            self.fld[key] = c
            self.fld_info[key] = info_lbl
            row_lbl = QLabel(f"<b>{label}:</b>")
            self._fld_row_labels.setdefault(key, []).append(row_lbl)
            f_blk.addRow(row_lbl, self._make_field_row_widget(c, info_lbl))
        mid_lay.addWidget(self.grp_d1, 3)

        self.grp_d2 = QGroupBox("D2. Road Network Attributes (Auto-Matched)")
        f_rd = QFormLayout(self.grp_d2)
        f_rd.setContentsMargins(12, 10, 12, 10)
        f_rd.setHorizontalSpacing(12)
        f_rd.setVerticalSpacing(6)

        self.rfld = {}
        self.rfld_info = {}
        for key, label, _, _ in ROAD_FIELD_DEFS:
            c = QgsFieldComboBox()
            c.setAllowEmptyFieldName(True)
            info_lbl = QLabel("<i>Waiting...</i>")
            c.fieldChanged.connect(lambda fname, k=key: self.update_single_field_preview(self.cmb_road.currentLayer(), k, fname, mode="road"))
            self.rfld[key] = c
            self.rfld_info[key] = info_lbl
            row_lbl = QLabel(f"<b>{label}:</b>")
            self._fld_row_labels.setdefault(key, []).append(row_lbl)
            f_rd.addRow(row_lbl, self._make_field_row_widget(c, info_lbl))
        mid_lay.addWidget(self.grp_d2, 2)

        lay.addLayout(mid_lay)
        lay.addStretch()

        self.cmb_block.layerChanged.connect(self.on_block_changed)
        self.cmb_bldg.layerChanged.connect(self.on_bldg_changed)
        self.cmb_road.layerChanged.connect(self.on_road_changed)
        QTimer.singleShot(100, self.auto_populate_all_layers)
        return w

    # ------------------------------------------------------------ 2. Sekme: Doğal Eşikler
    def page_extra(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(10)

        self.grp_e = QGroupBox("E. Natural Thresholds & Protected Areas")
        v = QVBoxLayout(self.grp_e)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(8)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.btn_auto_nat = QPushButton("⚡ Auto-Scan Natural Thresholds (Stream, Fault, Sit, DEM...)")
        if PointingHandCursor is not None:
            self.btn_auto_nat.setCursor(PointingHandCursor)
        self.btn_auto_nat.clicked.connect(self.auto_scan_natural_layers)
        self.btn_add_row = QPushButton("➕ Add Row")
        if PointingHandCursor is not None:
            self.btn_add_row.setCursor(PointingHandCursor)
        self.btn_del_row = QPushButton("🗑️ Remove Selected")
        if PointingHandCursor is not None:
            self.btn_del_row.setCursor(PointingHandCursor)
        self.btn_add_row.clicked.connect(self.add_extra)
        self.btn_del_row.clicked.connect(self.del_extra)
        bar.addWidget(self.btn_auto_nat)
        bar.addWidget(self.btn_add_row)
        bar.addWidget(self.btn_del_row)
        bar.addStretch()
        v.addLayout(bar)

        self.tbl = QTableWidget(0, 3)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.setMinimumHeight(170)
        self.tbl.verticalHeader().setDefaultSectionSize(32)
        self.tbl.setHorizontalHeaderLabels(["Threshold / Layer Name", "Analysis Role (Auto-Selected)", "Map Layer"])
        self.tbl.horizontalHeader().setSectionResizeMode(HeaderStretch)
        self.tbl.setSelectionBehavior(SelectRows)
        v.addWidget(self.tbl)
        lay.addWidget(self.grp_e, 1)

        self.grp_f = QGroupBox("F. Digital Elevation Model (DEM) / Slope Layer")
        f2 = QFormLayout(self.grp_f)
        f2.setContentsMargins(12, 10, 12, 10)
        f2.setHorizontalSpacing(14)
        f2.setVerticalSpacing(8)

        self.cmb_dem = QgsMapLayerComboBox()
        self.cmb_dem.setAllowEmptyLayer(True)
        self.cmb_dem.setFilters(QgsMapLayerProxyModel.Filter.RasterLayer)
        self.chk_slope = QCheckBox("Selected raster directly contains percentage slope (%) values")
        self.spn_step = QSpinBox()
        self.spn_step.setRange(5, 200)
        self.spn_step.setValue(30)
        self.spn_step.setSuffix(" m")
        self.spn_step.setMaximumWidth(140)
        self.lbl_dem = QLabel("<b>DEM or Slope Raster:</b>")
        self.lbl_step = QLabel("<b>Slope Sampling Step:</b>")
        f2.addRow(self.lbl_dem, self.cmb_dem)
        f2.addRow("", self.chk_slope)
        f2.addRow(self.lbl_step, self.spn_step)
        lay.addWidget(self.grp_f)
        return w

    def add_extra(self, name_text=None, role_code=None, layer_obj=None):
        row = self.tbl.rowCount()
        self.tbl.insertRow(row)
        role = QComboBox()
        for label, code, _ in analiz.ROLES:
            role.addItem(label, code)
        if role_code:
            idx = role.findData(role_code)
            if idx >= 0:
                role.setCurrentIndex(idx)
        self.tbl.setItem(row, 0, QTableWidgetItem(name_text or f"Katman_{row + 1}"))
        self.tbl.setCellWidget(row, 1, role)
        cmb = QgsMapLayerComboBox()
        cmb.setFilters(QgsMapLayerProxyModel.Filter.VectorLayer)
        if layer_obj:
            cmb.setLayer(layer_obj)
        self.tbl.setCellWidget(row, 2, cmb)

    def del_extra(self):
        for r in sorted({i.row() for i in self.tbl.selectedIndexes()}, reverse=True):
            self.tbl.removeRow(r)

    # ------------------------------------------------------------ Hızlı Otomatik Katman ve Doğal Eşik Tarayıcı
    def auto_populate_all_layers(self):
        proj_layers = list(QgsProject.instance().mapLayers().values())
        if not proj_layers:
            return

        bnd_cand, road_cand, blk_cand, bldg_cand = None, None, None, None
        for lyr in proj_layers:
            nm = alg.norm_tr(lyr.name())
            # Donatıları, yapıları, adaları, yolları, itfaiyeyi ve kırılganlık parçalarını doğal eşiklerden kesinlikle hariç tut
            if any(x in nm for x in (
                "alt_bolge", "hucre", "imar_adasi_hucre", "itfaye", "itfaiye",
                "kirilganlik_parca", "kirilganlik", "yapi", "bina", "ada", "yol",
                "park", "asm", "saglik", "okul", "egitim", "cami", "donati"
            )):
                continue
            if isinstance(lyr, QgsVectorLayer):
                gtype = lyr.geometryType()
                if gtype == QgsWkbTypes.GeometryType.PolygonGeometry:
                    if any(w in nm for w in ("onama", "sinir", "plan_sinir", "calisma_alani", "etap")):
                        bnd_cand = bnd_cand or lyr
                    elif any(w in nm for w in ("bina", "yapi", "building", "tekil")):
                        bldg_cand = bldg_cand or lyr
                    elif any(w in nm for w in ("mevcut", "ada", "parsel", "konut", "nip", "uip")):
                        blk_cand = blk_cand or lyr
                elif gtype == QgsWkbTypes.GeometryType.LineGeometry:
                    if any(w in nm for w in ("yol", "halihazir", "ulası", "ulasi", "sokak", "cadde", "street", "road")):
                        road_cand = road_cand or lyr

        if not blk_cand and bldg_cand:
            blk_cand, bldg_cand = bldg_cand, None

        if bnd_cand:
            self.cmb_boundary.setLayer(bnd_cand)
        if road_cand:
            self.cmb_road.setLayer(road_cand)
        if blk_cand:
            self.cmb_block.setLayer(blk_cand)
        if bldg_cand and bldg_cand != blk_cand:
            self.cmb_bldg.setLayer(bldg_cand)
            self.chk_use_bldg.setChecked(True)

        self.on_block_changed(self.cmb_block.currentLayer())
        self.on_bldg_changed(self.cmb_bldg.currentLayer())
        self.on_road_changed(self.cmb_road.currentLayer())
        self.auto_scan_natural_layers()

    def auto_scan_natural_layers(self):
        proj_layers = list(QgsProject.instance().mapLayers().values())
        used_main = {
            self.cmb_boundary.currentLayer(),
            self.cmb_road.currentLayer(),
            self.cmb_block.currentLayer(),
            self.cmb_bldg.currentLayer() if self.chk_use_bldg.isChecked() else None
        }
        existing_layers = set()
        for r in range(self.tbl.rowCount()):
            w = self.tbl.cellWidget(r, 2)
            if w and w.currentLayer():
                existing_layers.add(w.currentLayer().id())

        for lyr in proj_layers:
            if lyr in used_main or lyr is None:
                continue
            nm = alg.norm_tr(lyr.name())
            if any(x in nm for x in ("alt_bolge", "hucre", "imar_adasi_hucre")):
                continue

            if isinstance(lyr, QgsRasterLayer):
                if any(w in nm for w in ("dem", "srtm", "egim", "slope", "yukseklik", "aster", "alaska", "dsm", "dtm")) or not self.cmb_dem.currentLayer():
                    self.cmb_dem.setLayer(lyr)
                    if "egim" in nm or "slope" in nm:
                        self.chk_slope.setChecked(True)
                continue

            if isinstance(lyr, QgsVectorLayer) and lyr.id() not in existing_layers:
                for role_code, role_title, kws in NATURAL_LAYER_RULES:
                    if any(kw in nm for kw in kws):
                        self.add_extra(name_text=f"{role_title} ({lyr.name()})", role_code=role_code, layer_obj=lyr)
                        existing_layers.add(lyr.id())
                        break

    # ------------------------------------------------------------ Sütun Önizleme Motoru
    def sample_column_values(self, layer, fname, max_rows=80):
        if not layer or not fname:
            return []
        cache_key = (layer.id(), fname, max_rows)
        if cache_key in self._sample_cache:
            return self._sample_cache[cache_key]
        vals = []
        req = QgsFeatureRequest().setFlags(QgsFeatureRequest.Flag.NoGeometry).setSubsetOfAttributes([fname], layer.fields()).setLimit(max_rows)
        for f in layer.getFeatures(req):
            v = analiz.val(f, fname)
            if v is not None:
                vals.append(v)
        self._sample_cache[cache_key] = vals
        return vals

    def smart_match_field(self, layer, kws, want_numeric, exclude_cols=None):
        if not layer:
            return ""
        excl = exclude_cols or set()
        best_col = ""
        best_score = -1
        for fl in layer.fields():
            fname = fl.name()
            if fname in excl:
                continue
            nm = alg.norm_tr(fname)
            if nm in ("id", "fid", "gid", "objectid", "shape_leng", "shape_area"):
                continue
            score = 0
            for kw in kws:
                if nm == kw:
                    score += 50
                elif kw in nm:
                    score += 25
            samples = self.sample_column_values(layer, fname, 50)
            if not samples:
                continue
            if want_numeric:
                num_ok = sum(1 for x in samples if analiz.to_float(x) is not None)
                if num_ok > len(samples) * 0.6:
                    score += 10
                else:
                    score -= 15
            else:
                joined = " ".join(alg.norm_tr(x) for x in samples[:25])
                if any(w in joined for w in ("konut", "ticaret", "tarim", "sanayi", "bitisik", "ayrik", "asfalt", "parke", "sokak", "bulvar", "iyi", "orta", "kotu")):
                    score += 12
            if score > best_score and score >= 15:
                best_score = score
                best_col = fname
        return best_col

    def update_single_field_preview(self, layer, key, fname, mode="block"):
        if mode == "road":
            lbl = self.rfld_info[key]
        elif mode == "bldg":
            lbl = self.bfld_info[key]
        else:
            lbl = self.fld_info[key]

        if not layer:
            lbl.setText("<i>Katman seçilmedi</i>")
            return
        if not fname:
            lbl.setText("<span style='color:#64748b;'>Kullanılmıyor</span>")
            return
        samples = self.sample_column_values(layer, fname, 80)
        if not samples:
            lbl.setText(f"<span style='color:#d97706;'>Boş sütun ({fname})</span>")
            return
        str_counts = Counter(str(x).strip() for x in samples).most_common(3)
        preview_str = ", ".join(f"{val} ({cnt})" for val, cnt in str_counts)
        if len(preview_str) > 54:
            preview_str = preview_str[:51] + "..."
        lbl.setText(f"<span style='color:#15803d;'>✔ <b>{fname}:</b> {preview_str}</span>")

    def on_block_changed(self, layer):
        self._sample_cache.clear()
        used = set()
        for key, _, kws, want_num in FIELD_DEFS:
            c = self.fld[key]
            c.blockSignals(True)
            c.setLayer(layer)
            matched = self.smart_match_field(layer, kws, want_num, exclude_cols=used)
            if matched:
                used.add(matched)
            c.setField(matched)
            c.blockSignals(False)
            self.update_single_field_preview(layer, key, matched, mode="block")

    def on_bldg_changed(self, layer):
        self._sample_cache.clear()
        used = set()
        for key, _, kws, want_num in BLDG_FIELD_DEFS:
            c = self.bfld[key]
            c.blockSignals(True)
            c.setLayer(layer)
            matched = self.smart_match_field(layer, kws, want_num, exclude_cols=used)
            if matched:
                used.add(matched)
            c.setField(matched)
            c.blockSignals(False)
            self.update_single_field_preview(layer, key, matched, mode="bldg")

    def on_road_changed(self, layer):
        self._sample_cache.clear()
        used = set()
        for key, _, kws, want_num in ROAD_FIELD_DEFS:
            c = self.rfld[key]
            c.blockSignals(True)
            c.setLayer(layer)
            matched = self.smart_match_field(layer, kws, want_num, exclude_cols=used)
            if matched:
                used.add(matched)
            c.setField(matched)
            c.blockSignals(False)
            self.update_single_field_preview(layer, key, matched, mode="road")

    def _update_pop_mode_ui(self):
        mode_id = self.pop_btn_group.checkedId()
        self.spn_manual_pop.setEnabled(mode_id in (1, 2))
        self.spn_per_bldg.setEnabled(mode_id == 3)
        if mode_id == 2:
            self.spn_manual_pop.setStyleSheet("border: 1.5px solid #0284c7; background-color: #f0f9ff;")
            self.spn_per_bldg.setStyleSheet("")
        elif mode_id == 3:
            self.spn_per_bldg.setStyleSheet("border: 1.5px solid #0284c7; background-color: #f0f9ff;")
            self.spn_manual_pop.setStyleSheet("")
        else:
            self.spn_manual_pop.setStyleSheet("")
            self.spn_per_bldg.setStyleSheet("")

    def _apply_preset_by_index(self, idx):
        if idx < 0 or idx >= len(ZONING_PRESETS):
            return
        pr = ZONING_PRESETS[idx]
        w_lu, w_yapi, w_dogal, w_geo, cap_m, w_bos, w_erisim, w_yol, w_odak = pr["weights"]
        for spn, val_w in (
            (self.w_lu, w_lu),
            (self.w_yapi, w_yapi),
            (self.w_dogal, w_dogal),
            (self.w_geo, w_geo),
            (self.cap, cap_m),
            (self.w_bos, w_bos),
            (self.w_erisim, w_erisim),
            (self.w_yol, w_yol),
            (self.w_odak, w_odak),
        ):
            spn.blockSignals(True)
            spn.setValue(val_w)
            spn.blockSignals(False)
            if hasattr(spn, "_sync_slider") and spn._sync_slider is not None:
                spn._sync_slider.blockSignals(True)
                scale = getattr(spn, "_slider_scale", 10)
                spn._sync_slider.setValue(int(round(float(val_w) * scale)))
                spn._sync_slider.blockSignals(False)
            if hasattr(spn, "_update_badge") and spn._update_badge is not None:
                spn._update_badge()

        # Kompaktlık Modu (compactness_mode)
        c_mode = pr.get("compactness_mode", "balanced")
        if hasattr(self, "cmb_compactness_mode"):
            idx_cm = self.cmb_compactness_mode.findData(c_mode)
            if idx_cm >= 0:
                self.cmb_compactness_mode.blockSignals(True)
                self.cmb_compactness_mode.setCurrentIndex(idx_cm)
                self.cmb_compactness_mode.blockSignals(False)

        self._update_preset_description_only()

    def _select_preset_code(self, code):
        if not hasattr(self, "cmb_preset"):
            return
        idx = self.cmb_preset.findData(code)
        if idx >= 0:
            self.cmb_preset.setCurrentIndex(idx)

    def _update_preset_description_only(self):
        if not hasattr(self, "cmb_preset") or not hasattr(self, "lbl_preset_desc"):
            return
        idx = max(0, self.cmb_preset.currentIndex())
        pr = ZONING_PRESETS[idx]
        is_tr = (getattr(self, "current_lang", "en") == "tr")
        self.lbl_preset_desc.setText(pr["desc_tr"] if is_tr else pr["desc_en"])
        active_code = pr["code"]
        if hasattr(self, "_preset_quick_btns"):
            for btn_p, pr_item in self._preset_quick_btns:
                if pr_item["code"] == active_code:
                    btn_p.setStyleSheet(
                        "QPushButton { background-color: #0284c7; color: #ffffff; border: 1.5px solid #0369a1; "
                        "border-radius: 5px; padding: 5px 10px; font-weight: bold; font-size: 11px; }"
                    )
                else:
                    btn_p.setStyleSheet(
                        "QPushButton { background-color: #ffffff; color: #0f172a; border: 1px solid #cbd5e1; "
                        "border-radius: 5px; padding: 5px 10px; font-weight: 600; font-size: 11px; } "
                        "QPushButton:hover { background-color: #e0f2fe; border-color: #0284c7; color: #0369a1; }"
                    )

    # ------------------------------------------------------------ 3. Sekme: Hazır Stratejiler + Manuel Ağırlıklar
    def page_settings(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(10)

        # G0. Bölgeleme Stratejisi Seçici
        self.grp_preset = QGroupBox("Zoning Strategy Presets (Select a Preset or Fine-Tune the Weights Manually Below)")
        v_pr = QVBoxLayout(self.grp_preset)
        v_pr.setContentsMargins(12, 10, 12, 10)
        v_pr.setSpacing(8)

        pr_top = QHBoxLayout()
        pr_top.setSpacing(10)
        self.lbl_preset_sel = QLabel("<b>Select Zoning Strategy Preset:</b>")
        self.cmb_preset = QComboBox()
        for pr in ZONING_PRESETS:
            self.cmb_preset.addItem(pr["title_en"], pr["code"])
        self.cmb_preset.setCurrentIndex(0)
        pr_top.addWidget(self.lbl_preset_sel)
        pr_top.addWidget(self.cmb_preset, 1)
        v_pr.addLayout(pr_top)

        # Tek Tıkla Hızlı Seçim Butonları (9 Strateji - 3x3 Grid)
        btn_grid = QGridLayout()
        btn_grid.setHorizontalSpacing(8)
        btn_grid.setVerticalSpacing(6)
        self._preset_quick_btns = []
        for idx_b, pr in enumerate(ZONING_PRESETS):
            b_quick = QPushButton(pr["short_en"])
            if PointingHandCursor is not None:
                b_quick.setCursor(PointingHandCursor)
            b_quick.clicked.connect(lambda _, c_code=pr["code"]: self._select_preset_code(c_code))
            self._preset_quick_btns.append((b_quick, pr))
            btn_grid.addWidget(b_quick, idx_b // 3, idx_b % 3)
        v_pr.addLayout(btn_grid)

        self.lbl_preset_desc = QLabel(ZONING_PRESETS[0]["desc_en"])
        self.lbl_preset_desc.setWordWrap(True)
        self.lbl_preset_desc.setStyleSheet(
            "QLabel { background-color: #f0f9ff; color: #0c4a6e; border: 1px solid #7dd3fc; "
            "border-radius: 6px; padding: 8px 10px; font-size: 11px; }"
        )
        v_pr.addWidget(self.lbl_preset_desc)
        lay.addWidget(self.grp_preset)

        self.grp_g = QGroupBox("G. Manual Zoning Parameters & Fine-Tuning Weight Coefficients")
        grid = QGridLayout(self.grp_g)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(12)
        self._param_card_labels = {}
        self._advanced_cards = {}

        # Spinboxlar
        self.spn_k = QSpinBox()
        self.spn_k.setRange(2, 60)
        self.spn_k.setValue(25)
        self.spn_k.valueChanged.connect(lambda _: self._on_mode_changed())

        def dsp(v, lo=0.0, hi=5.0, step=0.1):
            d = QDoubleSpinBox()
            d.setRange(lo, hi)
            d.setSingleStep(step)
            d.setValue(v)
            return d

        self.w_lu = dsp(2.2)
        self.w_yapi = dsp(2.4)
        self.w_dogal = dsp(1.6)
        self.w_geo = dsp(2.5)
        self.cap = dsp(4.0, 1.5, 20.0, 0.5)
        self.w_bos = dsp(2.8)
        self.w_erisim = dsp(2.4)
        self.w_yol = dsp(2.2)
        self.w_odak = dsp(2.5)

        self.grid = QSpinBox()
        self.grid.setRange(50, 2000)
        self.grid.setValue(200)
        self.grid.setSuffix(" m")

        # Sliderlar
        def make_slider(min_val, max_val, val, step=1):
            s = QSlider(OrientationHorizontal)
            s.setRange(min_val, max_val)
            s.setSingleStep(step)
            s.setValue(val)
            s.setStyleSheet(
                "QSlider::groove:horizontal { height: 6px; background: #e2e8f0; border-radius: 3px; } "
                "QSlider::sub-page:horizontal { background: #0284c7; border-radius: 3px; } "
                "QSlider::handle:horizontal { background: #0369a1; border: 2px solid #ffffff; width: 16px; margin: -5px 0; border-radius: 8px; }"
            )
            return s

        sld_k = make_slider(2, 60, 25)
        sld_lu = make_slider(0, 50, 22)
        sld_yapi = make_slider(0, 50, 24)
        sld_dogal = make_slider(0, 50, 16)
        sld_geo = make_slider(0, 50, 25)
        sld_cap = make_slider(15, 200, 40, step=5)
        sld_bos = make_slider(0, 50, 28)
        sld_erisim = make_slider(0, 50, 24)
        sld_yol = make_slider(0, 50, 22)
        sld_odak = make_slider(0, 50, 25)
        sld_grid = make_slider(50, 2000, 200, step=10)

        # Kompaktlık Modu Açılır Kutusu
        self.cmb_compactness_mode = QComboBox()
        self.cmb_compactness_mode.addItem("🌿 Morphological / Natural Axis (Organic Valley Flow)", "organic")
        self.cmb_compactness_mode.addItem("⚖️ Balanced Standard (Planning Norm)", "balanced")
        self.cmb_compactness_mode.addItem("🎯 High Compactness (Convex / Circular Superblocks)", "strict")
        self.cmb_compactness_mode.setCurrentIndex(1)
        self.cmb_compactness_mode.setToolTip(
            "Organic mode allows zones along stream/river valleys and transport axes to stretch naturally without penalty."
        )

        def make_advanced_weight_card(key_prefix, spinbox, slider, is_int=False, scale=10, cmb_extra=None):
            card = QFrame()
            card.setStyleSheet(
                "QFrame { background-color: #ffffff; border: 1px solid #cbd5e1; border-radius: 8px; padding: 2px; } "
                "QFrame:hover { border-color: #94a3b8; }"
            )
            cl = QVBoxLayout(card)
            cl.setContentsMargins(12, 10, 12, 10)
            cl.setSpacing(6)

            det = WEIGHT_DETAILS[key_prefix]
            is_tr = (getattr(self, "current_lang", "en") == "tr")
            d_lang = det["tr"] if is_tr else det["en"]

            # Header: Title + Dynamic Badge
            top_row = QHBoxLayout()
            lbl_title = QLabel(f"<b>{d_lang['title']}</b>")
            lbl_title.setStyleSheet("border: none; background: transparent; color: #0f172a; font-size: 12px;")

            lbl_badge = QLabel()
            lbl_badge.setStyleSheet(
                "border-radius: 4px; padding: 2px 8px; font-size: 10px; font-weight: 700; border: 1px solid #cbd5e1;"
            )
            top_row.addWidget(lbl_title, 1)
            top_row.addWidget(lbl_badge)
            cl.addLayout(top_row)

            # Control Row: Slider + Spinbox
            ctrl_row = QHBoxLayout()
            ctrl_row.setSpacing(10)
            ctrl_row.addWidget(slider, 1)
            spinbox.setMinimumWidth(85)
            ctrl_row.addWidget(spinbox)
            cl.addLayout(ctrl_row)

            if cmb_extra is not None:
                cl.addWidget(cmb_extra)

            def update_badge():
                is_tr_cur = (getattr(self, "current_lang", "en") == "tr")
                v = float(spinbox.value())
                if is_int:
                    if key_prefix == "p_k":
                        if v <= 8:
                            txt = "🔵 Makro Bölge (Kaba)" if is_tr_cur else "🔵 Macro Zones (Coarse)"
                            bg, fg, bc = "#e0f2fe", "#0369a1", "#7dd3fc"
                        elif v <= 25:
                            txt = "🟢 Semt / Doku (Önerilen)" if is_tr_cur else "🟢 District Level (Optimal)"
                            bg, fg, bc = "#dcfce7", "#15803d", "#86efac"
                        elif v <= 40:
                            txt = "🟠 Mahalle / Detay" if is_tr_cur else "🟠 Neighborhood (Fine)"
                            bg, fg, bc = "#ffedd5", "#c2410c", "#fdba74"
                        else:
                            txt = "🔴 Mikro-Ada (Aşırı Detay)" if is_tr_cur else "🔴 Micro-Block (Very Fine)"
                            bg, fg, bc = "#fee2e2", "#b91c1c", "#fca5a5"
                    elif key_prefix == "p_grid":
                        txt = f"{int(v)} m"
                        bg, fg, bc = "#f1f5f9", "#334155", "#cbd5e1"
                    else:
                        txt = f"{int(v)}"
                        bg, fg, bc = "#f1f5f9", "#334155", "#cbd5e1"
                else:
                    if key_prefix == "p_cap":
                        if v <= 2.0:
                            txt = "🔵 Katı Eşit Alan (Bölünme Riski)" if is_tr_cur else "🔵 Strict Equal Area"
                            bg, fg, bc = "#e0f2fe", "#0369a1", "#7dd3fc"
                        elif v <= 5.0:
                            txt = "🟢 Dengeli Tavan (Önerilen)" if is_tr_cur else "🟢 Balanced Cap (Optimal)"
                            bg, fg, bc = "#dcfce7", "#15803d", "#86efac"
                        else:
                            txt = "🟠 Geniş / Serbest Makro-Bölge" if is_tr_cur else "🟠 Open Macro-Zone"
                            bg, fg, bc = "#ffedd5", "#c2410c", "#fdba74"
                    else:
                        if v <= 0.05:
                            txt = "⚪ Etkisiz (%0)" if is_tr_cur else "⚪ Inactive (0%)"
                            bg, fg, bc = "#f1f5f9", "#64748b", "#cbd5e1"
                        elif v <= 1.5:
                            txt = f"🔵 Düşük Etki ({v:.1f})" if is_tr_cur else f"🔵 Low Impact ({v:.1f})"
                            bg, fg, bc = "#e0f2fe", "#0369a1", "#7dd3fc"
                        elif v <= 3.2:
                            txt = f"🟢 Dengeli / Standart ({v:.1f})" if is_tr_cur else f"🟢 Balanced ({v:.1f})"
                            bg, fg, bc = "#dcfce7", "#15803d", "#86efac"
                        else:
                            txt = f"🟠 Yüksek / Baskın ({v:.1f})" if is_tr_cur else f"🟠 Dominant ({v:.1f})"
                            bg, fg, bc = "#ffedd5", "#c2410c", "#fdba74"

                lbl_badge.setText(txt)
                lbl_badge.setStyleSheet(
                    f"background-color: {bg}; color: {fg}; border: 1px solid {bc}; "
                    "border-radius: 4px; padding: 2px 8px; font-size: 10px; font-weight: 700;"
                )

            def on_slider(val):
                spinbox.blockSignals(True)
                if is_int:
                    spinbox.setValue(val)
                else:
                    spinbox.setValue(val / float(scale))
                spinbox.blockSignals(False)
                update_badge()

            def on_spinbox(val):
                slider.blockSignals(True)
                if is_int:
                    slider.setValue(int(val))
                else:
                    slider.setValue(int(round(float(val) * scale)))
                slider.blockSignals(False)
                update_badge()

            slider.valueChanged.connect(on_slider)
            spinbox.valueChanged.connect(on_spinbox)
            spinbox._sync_slider = slider
            spinbox._slider_scale = scale
            spinbox._update_badge = update_badge

            # Pedagogical Explanation Box
            info_frame = QFrame()
            info_frame.setStyleSheet(
                "QFrame { background-color: #f8fafc; border: 1px solid #e2e8f0; "
                "border-left: 3px solid #0284c7; border-radius: 5px; padding: 6px; }"
            )
            v_info = QVBoxLayout(info_frame)
            v_info.setContentsMargins(6, 4, 6, 4)
            v_info.setSpacing(3)

            lbl_how = QLabel(f"<b>{('Çalışma Mantığı:' if is_tr else 'How it Works:')}</b> {d_lang['mech']}")
            lbl_how.setWordWrap(True)
            lbl_how.setStyleSheet("border: none; background: transparent; color: #334155; font-size: 11px;")

            ext_str = (
                f"<b>Min ({d_lang['min_val']}):</b> {d_lang['min_txt']}  •  "
                f"<b>Maks ({d_lang['max_val']}):</b> {d_lang['max_txt']}<br/>"
                f"<b>{('Önerilen:' if is_tr else 'Recommended:')}</b> <span style='color: #0369a1;'>{d_lang['rec']}</span>"
            )
            lbl_extremes = QLabel(ext_str)
            lbl_extremes.setWordWrap(True)
            lbl_extremes.setStyleSheet("border: none; background: transparent; color: #475569; font-size: 10.5px;")

            v_info.addWidget(lbl_how)
            v_info.addWidget(lbl_extremes)
            cl.addWidget(info_frame)

            update_badge()
            self._advanced_cards[key_prefix] = {
                "title_label": lbl_title,
                "badge_label": lbl_badge,
                "how_label": lbl_how,
                "extremes_label": lbl_extremes,
                "details": det,
                "spinbox": spinbox,
                "update_badge": update_badge,
            }
            self._param_card_labels[key_prefix] = (lbl_title, lbl_how)
            return card

        grid.addWidget(make_advanced_weight_card("p_k", self.spn_k, sld_k, is_int=True), 0, 0)
        grid.addWidget(make_advanced_weight_card("p_lu", self.w_lu, sld_lu), 0, 1)
        grid.addWidget(make_advanced_weight_card("p_yapi", self.w_yapi, sld_yapi), 1, 0)
        grid.addWidget(make_advanced_weight_card("p_dogal", self.w_dogal, sld_dogal), 1, 1)
        grid.addWidget(make_advanced_weight_card("p_geo", self.w_geo, sld_geo, cmb_extra=self.cmb_compactness_mode), 2, 0)
        grid.addWidget(make_advanced_weight_card("p_cap", self.cap, sld_cap, scale=10), 2, 1)
        grid.addWidget(make_advanced_weight_card("p_bos", self.w_bos, sld_bos), 3, 0)
        grid.addWidget(make_advanced_weight_card("p_erisim", self.w_erisim, sld_erisim), 3, 1)
        grid.addWidget(make_advanced_weight_card("p_yol", self.w_yol, sld_yol), 4, 0)
        grid.addWidget(make_advanced_weight_card("p_odak", self.w_odak, sld_odak), 4, 1)
        grid.addWidget(make_advanced_weight_card("p_grid", self.grid, sld_grid, is_int=True), 5, 0, 1, 2)

        self.cmb_preset.currentIndexChanged.connect(self._apply_preset_by_index)
        self._update_preset_description_only()

        lay.addWidget(self.grp_g)

        self.grp_h = QGroupBox("H. Compact Geometry, Quick Summary Layer & Matching Options")
        v_opts = QVBoxLayout(self.grp_h)
        v_opts.setContentsMargins(12, 10, 12, 10)
        v_opts.setSpacing(6)

        self.chk_filter_medians = QCheckBox("Eliminate road corridors, medians & junction slivers (Roads only form boundaries, never long zone tails)")
        self.chk_filter_medians.setChecked(True)
        self.chk_excel = QCheckBox("Match sub-zones with canonical MPYY character & intervention profiles")
        self.chk_excel.setChecked(True)
        self.chk_quick_layer = QCheckBox("Also add simplified 'Alt_Bolgeler_Hizli_Ozet' layer to map (Quick-reading columns only)")
        self.chk_quick_layer.setChecked(False)
        self.chk_cells = QCheckBox("Also add intermediate urban block cells layer ('Imar_Adasi_Hucreleri') to map")

        v_opts.addWidget(self.chk_filter_medians)
        v_opts.addWidget(self.chk_excel)
        v_opts.addWidget(self.chk_quick_layer)
        v_opts.addWidget(self.chk_cells)

        lay.addWidget(self.grp_h)
        lay.addStretch()
        return w

    # ------------------------------------------------------------ 4. Sekme: Sınır Ayrım Gerekçeleri & Rapor
    def page_results(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 8, 10, 10)
        self.grp_i = QGroupBox("I. Sub-Zoning Summary, Internal Cohesion & Neighbor Separation Rationales")
        v = QVBoxLayout(self.grp_i)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(8)

        # Üst Görünüm Modu Seçici (Hızlı Özet vs. Detaylı Teknik Doğrulama)
        ctrl_frame = QFrame()
        ctrl_frame.setStyleSheet(
            "QFrame { background-color: #f0f9ff; border: 1px solid #bae6fd; border-radius: 6px; padding: 6px; }"
        )
        ctrl_lay = QVBoxLayout(ctrl_frame)
        ctrl_lay.setContentsMargins(8, 6, 8, 6)
        ctrl_lay.setSpacing(6)

        row_modes = QHBoxLayout()
        row_modes.setSpacing(10)
        self.lbl_view_mode = QLabel("<b>View Mode:</b>")
        self.lbl_view_mode.setStyleSheet("color: #0369a1; border: none; background: transparent;")
        row_modes.addWidget(self.lbl_view_mode)

        self.view_btn_group = QButtonGroup(self)
        self.rb_view_quick = QRadioButton("⚡ Quick & Plain Summary (Fast Read)")
        self.rb_view_quick.setToolTip("Hides technical variable codes; shows only % Land Use, Fault, Stream, Slope, Facility, TAKS, Floors, and 1-sentence separation reason.")
        self.rb_view_both = QRadioButton("📋 Combined (Quick + Detailed)")
        self.rb_view_both.setToolTip("Shows both the quick plain summary and the full Z-score technical verification side by side.")
        self.rb_view_detailed = QRadioButton("🔬 Detailed Technical Only (ΔZ & Codes)")
        self.rb_view_detailed.setToolTip("Shows full academic parameter codes ([yapi:kotu_yapi], [sit2], [sit3]) and ΔZ matrix differences.")
        self.rb_view_both.setChecked(True)

        for idx_rb, rb in enumerate((self.rb_view_quick, self.rb_view_both, self.rb_view_detailed), 1):
            rb.setStyleSheet("font-weight: 600; color: #0f172a; border: none; background: transparent;")
            self.view_btn_group.addButton(rb, idx_rb)
            row_modes.addWidget(rb)
            rb.toggled.connect(self.refresh_report_view)
        row_modes.addStretch()
        ctrl_lay.addLayout(row_modes)

        row_filter = QHBoxLayout()
        row_filter.setSpacing(8)
        self.txt_filter = QLineEdit()
        self.txt_filter.setPlaceholderText("🔍 Filter by zone code or keyword (e.g. M12, Konut, Fay, Donatı, Sit)...")
        self.txt_filter.setStyleSheet(
            "QLineEdit { background-color: #ffffff; border: 1px solid #94a3b8; border-radius: 5px; padding: 4px 8px; }"
        )
        self.txt_filter.textChanged.connect(self.refresh_report_view)
        row_filter.addWidget(self.txt_filter, 1)
        ctrl_lay.addLayout(row_filter)
        v.addWidget(ctrl_frame)

        self.txt = QTextEdit()
        self.txt.setReadOnly(True)
        self.txt.setPlaceholderText(
            "▶ Press 'RUN' to generate sequential sub-zones (e.g. M1..M25 or M1..M28):\n"
            "• ⚡ QUICK & PLAIN SUMMARY (% Residential/Commercial/Agri, Distance to Fault & Stream, Slope %, Facility Count, TAKS, Floors & 1-sentence reason),\n"
            "• 🔬 DETAILED TECHNICAL VERIFICATION (Z-Score matrix [ΔZ], yapi:kotu_yapi, sit2, sit3 & internal cohesion metrics)."
        )
        v.addWidget(self.txt)
        lay.addWidget(self.grp_i, 1)
        return w

    # ------------------------------------------------------------ 5. Sekme: MPYY & Metodoloji El Kitabı
    def page_about(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(8)

        # Üst Rehber Çubuğu
        top_box = QHBoxLayout()
        self.lbl_about_top = QLabel("<b>Spatial Analysis Methodology, MAUP Solution & Comprehensive User Guide:</b>")
        self.lbl_about_top.setStyleSheet("color: #0f172a; font-size: 12px;")
        self.btn_browser = QPushButton("🌐 Open Full Methodology Guide in Browser (HTML)")
        self.btn_browser.setObjectName("helpBtn")
        if PointingHandCursor is not None:
            self.btn_browser.setCursor(PointingHandCursor)
        self.btn_browser.clicked.connect(self.open_html_guide)
        top_box.addWidget(self.lbl_about_top, 1)
        top_box.addWidget(self.btn_browser)
        lay.addLayout(top_box)

        self.grp_j = QGroupBox("J. Comprehensive Methodology, MAUP Solution & Step-by-Step User Manual")
        v = QVBoxLayout(self.grp_j)
        v.setContentsMargins(8, 8, 8, 8)
        about_txt = QTextEdit()
        about_txt.setReadOnly(True)
        guide_path = os.path.join(self.plugin_dir, "KULLANIM_KILAVUZU.html")
        if os.path.exists(guide_path):
            try:
                with open(guide_path, "r", encoding="utf-8") as f:
                    about_txt.setHtml(f.read())
            except (OSError, UnicodeDecodeError):
                about_txt.setPlainText("Error loading guide.")
        v.addWidget(about_txt)
        lay.addWidget(self.grp_j, 1)
        return w

    def open_html_guide(self):
        guide_path = os.path.join(self.plugin_dir, "KULLANIM_KILAVUZU.html")
        if os.path.exists(guide_path):
            import webbrowser
            webbrowser.open(f"file:///{os.path.abspath(guide_path).replace(os.sep, '/')}")
        else:
            QMessageBox.information(self, "Guide / Kılavuz", "KULLANIM_KILAVUZU.html not found.")

    # ------------------------------------------------------------ çalıştırma ve görünüm yenileme
    def log(self, m):
        self._pipeline_logs.append(m)
        self.txt.append(m)
        QApplication.processEvents()

    def refresh_report_view(self):
        """Kullanıcı Hızlı Özet / İkisi Bir Arada / Detaylı Teknik modunu değiştirdiğinde veya filtre yazdığında raporu anında günceller."""
        if not getattr(self, "last_zones", None):
            return
        view_id = self.view_btn_group.checkedId() if hasattr(self, "view_btn_group") else 2
        q_filter = (self.txt_filter.text().strip().lower() if hasattr(self, "txt_filter") else "")

        lines = []
        for msg in getattr(self, "_pipeline_logs", []):
            lines.append(msg)

        if view_id == 1:
            lines.append("=" * 84)
            lines.append("⚡ QUICK SUMMARY VIEW / HIZLI VE SADE ÖZET GÖRÜNÜMÜ (% Land Use | Fault | Slope | Facility | TAKS | Floors)")
            lines.append("=" * 84)
        elif view_id == 2:
            lines.append("=" * 84)
            lines.append("📋 COMBINED VIEW / İKİSİ BİR ARADA GÖRÜNÜM (Quick Summary + Detailed Technical & ΔZ Verification)")
            lines.append("=" * 84)
        else:
            lines.append("=" * 84)
            lines.append("🔬 DETAILED TECHNICAL VIEW / DETAYLI TEKNİK & Z-SKORU DOĞRULAMA GÖRÜNÜMÜ (Codes & ΔZ Matrix)")
            lines.append("=" * 84)

        shown = 0
        for z in self.last_zones:
            ha = z["area"] / 10000.0
            kisa_ozet = z.get("kisa_ozet") or analiz.describe_quick_summary(z)
            kisa_ayrim = z.get("kisa_ayrim_nedeni") or ""
            excel_ger = z.get("excel_gerekce") or ""
            searchable = f"{z['kod']} {z['karakter']} {kisa_ozet} {kisa_ayrim} {z['olculen']} {z['gerekce']}".lower()
            if q_filter and q_filter not in searchable:
                continue
            shown += 1

            if view_id == 1:
                block_str = f"■ {z['kod']} — {z['karakter']} ({ha:.1f} ha)"
                if excel_ger:
                    block_str += f"\n   Zone Profile / Bölge Tanımı        : {excel_ger}"
                if z.get("mudahale_karari"):
                    block_str += f"\n   Planning Decision / Planlama Kararı: {z['mudahale_karari']}"
                block_str += f"\n   Key Metrics / Temel Göstergeler    : {kisa_ozet}"
                if kisa_ayrim:
                    block_str += f"\n   Why Separated / Ayrım Gerekçesi    : {kisa_ayrim}"
                lines.append(block_str + "\n" + "-" * 84)
            elif view_id == 2:
                block_str = f"■ {z['kod']} — {z['karakter']} ({ha:.1f} ha | {z['olculen']})"
                if excel_ger:
                    block_str += f"\n   Zone Profile / Bölge Tanımı        : {excel_ger}"
                if z.get("baskin_kombinasyon"):
                    block_str += f"\n   Dominant Combination / Baskın Doku : {z['baskin_kombinasyon']}"
                if z.get("mudahale_karari"):
                    block_str += f"\n   Planning Decision / Planlama Kararı: {z['mudahale_karari']}"
                if z.get("plan_karsiligi"):
                    block_str += f"\n   Plan Equivalent / Plan Karşılığı   : {z['plan_karsiligi']}"
                block_str += f"\n   Key Metrics / Temel Göstergeler    : {kisa_ozet}"
                if kisa_ayrim:
                    block_str += f"\n   Why Separated / Ayrım Gerekçesi    : {kisa_ayrim}"
                block_str += f"\n   Technical Detail / Teknik Ayrıntı  : {z['gerekce']}"
                lines.append(block_str + "\n" + "-" * 84)
            else:
                lines.append(
                    f"■ {z['kod']} — {z['karakter']} ({ha:.1f} ha | {z['olculen']})\n"
                    f"   • Detailed Rationale: {z['gerekce']}\n" + "-" * 84
                )

        lines.append(f"✔ Analiz tamamlandı / Analysis completed ({len(self.last_zones)} sub-zones added to map / alt bölge haritaya eklendi, {shown} shown).")
        self.txt.setPlainText("\n".join(lines))

    def run(self, interactive=True):
        bnd = self.cmb_boundary.currentLayer()
        road = self.cmb_road.currentLayer()
        blk = self.cmb_block.currentLayer()
        bldg = self.cmb_bldg.currentLayer() if self.chk_use_bldg.isChecked() else None

        if not bnd and not blk and not bldg and not road:
            msg = "Lütfen en azından Plan Sınırı, Yol Ağı, İmar Adası veya Yapı katmanlarından birini seçiniz."
            if interactive:
                QMessageBox.warning(self, "Eksik Katman", msg)
            else:
                self.log("✖ UYARI: " + msg)
            return False

        extras = []
        for r in range(self.tbl.rowCount()):
            lyr = self.tbl.cellWidget(r, 2).currentLayer()
            if lyr is None:
                continue
            combo = self.tbl.cellWidget(r, 1)
            extras.append({
                "name": self.tbl.item(r, 0).text().strip() or f"Katman_{r + 1}",
                "role": combo.currentData(),
                "layer": lyr
            })

        pop_mode_id = self.pop_btn_group.checkedId()
        pop_mode = "auto" if pop_mode_id == 1 else ("manual_total" if pop_mode_id == 2 else "per_building")
        pop_cfg = {
            "mode": pop_mode,
            "manual_total": self.spn_manual_pop.value(),
            "per_bldg": self.spn_per_bldg.value()
        }

        base_lyr = bnd or blk or bldg or road
        P = {
            "mode": self.cmb_mode.currentData() if hasattr(self, "cmb_mode") else "advanced",
            "work_crs": base_lyr.crs(),
            "boundary_layer": bnd,
            "road_layer": road,
            "block_layer": blk,
            "bldg_layer": bldg,
            "fields": {k: (c.currentField() or None) for k, c in self.fld.items()},
            "bfields": {k: (c.currentField() or None) for k, c in self.bfld.items()},
            "rfields": {k: (c.currentField() or None) for k, c in self.rfld.items()},
            "pop_cfg": pop_cfg,
            "extras": extras,
            "dem": self.cmb_dem.currentLayer(),
            "dem_is_slope": self.chk_slope.isChecked(),
            "dem_step": float(self.spn_step.value()),
            "K": self.spn_k.value(),
            "preset_mode": self.cmb_preset.currentData() if hasattr(self, "cmb_preset") else "integrated_synthesis",
            "compactness_mode": self.cmb_compactness_mode.currentData() if hasattr(self, "cmb_compactness_mode") else "balanced",
            "w_lu": self.w_lu.value(),
            "w_yapi": self.w_yapi.value(),
            "w_dogal": self.w_dogal.value(),
            "w_geo": self.w_geo.value(),
            "cap_mult": self.cap.value(),
            "w_bos": self.w_bos.value() if hasattr(self, "w_bos") else 2.8,
            "w_erisim": self.w_erisim.value() if hasattr(self, "w_erisim") else 2.4,
            "w_yol": self.w_yol.value() if hasattr(self, "w_yol") else 2.2,
            "w_odak": self.w_odak.value() if hasattr(self, "w_odak") else 2.5,
            "grid_size": float(self.grid.value()),
            "filter_medians": self.chk_filter_medians.isChecked(),
            "use_excel": self.chk_excel.isChecked(),
        }
        self.last_P = P
        self._pipeline_logs = []
        self.txt.clear()
        self.tabs.setCurrentIndex(3)
        self.btn_run.setEnabled(False)
        self.btn_top_run.setEnabled(False)
        if WaitCursor is not None:
            QApplication.setOverrideCursor(WaitCursor)
        try:
            res = analiz.run_pipeline(P, self.log, self.progress.setValue)
            lyr, self.records = analiz.make_zone_layer(res, quick_only=False)
            lyr_quick, self.quick_records = analiz.make_zone_layer(res, quick_only=True)
            # Eski bolgeleme katmanlarini projeden temizle (tek cikti garantisi)
            proj = QgsProject.instance()
            old_ids = [
                lid for lid, l in proj.mapLayers().items()
                if l.name().startswith("Alt_Bolgeler") or l.name().startswith("Alt_Bölgeler")
            ]
            if old_ids:
                proj.removeMapLayers(old_ids)

            if self.chk_cells.isChecked():
                QgsProject.instance().addMapLayer(analiz.make_cell_layer(res))
            if hasattr(self, "chk_quick_layer") and self.chk_quick_layer.isChecked():
                QgsProject.instance().addMapLayer(lyr_quick)
            QgsProject.instance().addMapLayer(lyr)
            if self.iface and hasattr(self.iface, "mapCanvas") and self.iface.mapCanvas():
                self.iface.mapCanvas().refresh()

            active_col_names = ", ".join(self.records[0].keys()) if self.records else ""
            self._pipeline_logs.append(f"✔ Boş (NULL) sütunlar temizlendi. Aktif dolu sütunlar:\n   [{active_col_names}]")

            self.last_zones = res["zones"]
            self.refresh_report_view()
            self.btn_quick_csv.setEnabled(True)
            self.btn_csv.setEnabled(True)
            self.btn_matrix.setEnabled(True)
            self.progress.setValue(100)
            return True
        except Exception as e:
            self.log("✖ HATA: " + str(e) + "\n" + traceback.format_exc())
            if interactive:
                QMessageBox.critical(self, "Analiz Hatası", str(e))
            raise
        finally:
            if WaitCursor is not None:
                QApplication.restoreOverrideCursor()
            self.btn_run.setEnabled(True)
            self.btn_top_run.setEnabled(True)

    def export_quick_csv(self, target_path=None):
        """Hızlı okuma metriklerini ve sade ayrım gerekçesini içeren özet tabloyu düzenli Excel (.xlsx) veya CSV olarak dışa aktarır."""
        recs = getattr(self, "quick_records", None) or self.records
        if not recs:
            return None
        if target_path:
            path = target_path
        else:
            n_z = len(recs)
            default_fname = f"Alt_Bolgeler_1_{n_z}_Hizli_Ozet_Tablo.xlsx"
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Save Quick Summary Table (Excel / CSV)",
                default_fname,
                "Excel Workbook (*.xlsx);;CSV Table (*.csv)"
            )
            if not path:
                return None
        if path.lower().endswith(".xlsx"):
            analiz.export_excel_workbook(
                path,
                self.records or recs,
                quick_records=recs,
                P=getattr(self, "last_P", None),
                zones=getattr(self, "last_zones", None)
            )
        else:
            keys = list(recs[0].keys())
            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.DictWriter(fh, fieldnames=keys, delimiter=";")
                w.writeheader()
                w.writerows(recs)
        if not target_path:
            QMessageBox.information(self, "Saved / Kaydedildi", f"Quick Summary table saved:\n{path}")
        return path

    def export_csv(self, target_path=None):
        if not self.records:
            return None
        if target_path:
            path = target_path
        else:
            is_adv = (self.cmb_mode.currentData() == "advanced") if hasattr(self, "cmb_mode") else True
            prefix = "M" if is_adv else "A"
            n_z = len(self.records)
            default_fname = f"Alt_Bolgeler_{prefix}1_{prefix}{n_z}_Tam_Tablo.xlsx"
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Save Full Sub-Zone Table (Excel / CSV)",
                default_fname,
                "Excel Workbook (*.xlsx);;CSV Table (*.csv)"
            )
            if not path:
                return None
        if path.lower().endswith(".xlsx"):
            analiz.export_excel_workbook(
                path,
                self.records,
                quick_records=getattr(self, "quick_records", None),
                P=getattr(self, "last_P", None),
                zones=getattr(self, "last_zones", None)
            )
        else:
            keys = list(self.records[0].keys())
            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.DictWriter(fh, fieldnames=keys, delimiter=";")
                w.writeheader()
                w.writerows(self.records)
        if not target_path:
            QMessageBox.information(self, "Saved / Kaydedildi", f"Full Sub-Zone table saved:\n{path}")
        return path

    def export_analysis_matrix(self, target_path=None):
        if not hasattr(self, "last_P") or not self.last_P:
            return None
        if target_path:
            path = target_path
        else:
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Save Analysis Tracking Matrix (Excel / CSV)",
                "Analiz_Izleme_Matrisi.xlsx",
                "Excel Workbook (*.xlsx);;CSV Table (*.csv)"
            )
            if not path:
                return None
        analiz.export_analysis_tracking_matrix(self.last_P, getattr(self, "last_zones", None), path)
        if not target_path:
            QMessageBox.information(self, "Saved / Kaydedildi", f"Analysis Tracking Matrix saved:\n{path}")
        return path
