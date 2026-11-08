# -*- coding: utf-8 -*-
"""QGIS tarafı: yol ağından hücre üretimi, refüj/kavşak elemesi, imar adası + opsiyonel tekil yapı
stoku + manuel/otomatik nüfus hesabı, her girdinin Z-skoru kümelemesine gerçek katılımı ve
'Neden birleşti / Neden komşu bölgeden ayrıldı' sınır ayrım gerekçesi üretimi."""
import math
import re
import csv
import colorsys
from collections import Counter, defaultdict

from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor, QFont
from qgis.PyQt.QtWidgets import QApplication

_QVAR_INT = getattr(QVariant, "Int", 2)
_QVAR_DOUBLE = getattr(QVariant, "Double", 6)
_QVAR_STRING = getattr(QVariant, "String", 10)
from qgis.core import (
    QgsGeometry, QgsPointXY, QgsSpatialIndex, QgsFeature, QgsWkbTypes, QgsRectangle,
    QgsCoordinateTransform, QgsProject, QgsVectorLayer, QgsRasterLayer, QgsField, NULL,
    QgsCategorizedSymbolRenderer, QgsRendererCategory, QgsFillSymbol,
    QgsPalLayerSettings, QgsVectorLayerSimpleLabeling, QgsTextFormat, QgsTextBufferSettings,
    QgsCsException
)

from . import algoritma as alg

ROLES = [
    ("Dere / Akarsu Yatağı (Uzaklık - m)", "dere", "dist"),
    ("Sit / Koruma Alanı (Alan Oranı - %)", "sit", "share"),
    ("Diri Fay Hattı (Uzaklık - m)", "fay", "dist"),
    ("Taşkın / Afet Risk Alanı (Alan Oranı - %)", "risk", "share"),
    ("Sosyal ve Teknik Altyapı / Donatı (Adet)", "donati", "count"),
    ("Afet Toplanma Alanı (Uzaklık - m)", "toplanma", "dist"),
    ("Sağlık Tesisi / Hastane (Uzaklık - m)", "saglik", "dist"),
    ("Tarım / Mera / Boş Alan (Alan Oranı - %)", "tarim", "share"),
    ("Sanayi / OSB / Depolama (Alan Oranı - %)", "sanayi", "share"),
    ("Diğer Katman (Otomatik Algıla)", "genel", "auto"),
]
DIR_NAMES = ["Doğu", "Kuzeydoğu", "Kuzey", "Kuzeybatı", "Batı", "Güneybatı", "Güney", "Güneydoğu"]


# ------------------------------------------------------------------ yardımcılar
def val(f, name):
    if not name:
        return None
    try:
        v = f[name]
    except (KeyError, IndexError, TypeError):
        return None
    if v is None:
        return None
    if str(v) == "NULL":
        return None
    try:
        if v == NULL:
            return None
    except (TypeError, ValueError, AttributeError):
        return None
    if isinstance(v, QVariant) and (v.isNull() or not v.isValid()):
        return None
    if isinstance(v, str) and v.strip() == "":
        return None
    return v


def to_float(v):
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        m = re.search(r"-?\d+(?:[.,]\d+)?", str(v))
        if m:
            try:
                return float(m.group(0).replace(",", "."))
            except (ValueError, TypeError):
                return None
        return None


def read_geoms(layer, work_crs):
    xf = None
    if layer.crs() != work_crs:
        xf = QgsCoordinateTransform(layer.crs(), work_crs, QgsProject.instance())
    out = []
    for f in layer.getFeatures():
        if not f.hasGeometry():
            continue
        g = QgsGeometry(f.geometry())
        if g.isEmpty():
            continue
        if xf is not None:
            try:
                status = g.transform(xf)
                if status != 0:
                    continue
            except (QgsCsException, RuntimeError):
                continue
        if g.type() == QgsWkbTypes.GeometryType.PolygonGeometry and not g.isGeosValid():
            g2 = g.makeValid()
            if g2 and not g2.isEmpty():
                g = g2
        out.append((f, g))
    return out


def line_parts(g):
    if g is None or g.isEmpty():
        return []
    if g.isMultipart():
        return [p for p in g.asGeometryCollection() if p.type() == QgsWkbTypes.GeometryType.LineGeometry and not p.isEmpty()]
    if g.type() == QgsWkbTypes.GeometryType.LineGeometry:
        return [g]
    out = []
    try:
        parts = g.asGeometryCollection()
    except (TypeError, ValueError, AttributeError):
        parts = []
    for p in parts:
        if p.type() == QgsWkbTypes.GeometryType.LineGeometry and not p.isEmpty():
            out.append(p)
    return out


def poly_parts(g):
    if g is None or g.isEmpty():
        return []
    if g.isMultipart():
        return [p for p in g.asGeometryCollection() if p.type() == QgsWkbTypes.GeometryType.PolygonGeometry and not p.isEmpty()]
    if g.type() == QgsWkbTypes.GeometryType.PolygonGeometry:
        return [g]
    out = []
    try:
        parts = g.asGeometryCollection()
    except (TypeError, ValueError, AttributeError):
        parts = []
    for p in parts:
        if p.type() == QgsWkbTypes.GeometryType.PolygonGeometry and not p.isEmpty():
            out.append(p)
    return out


def build_index(geoms):
    idx = QgsSpatialIndex()
    for i, g in enumerate(geoms):
        f = QgsFeature(i)
        f.setGeometry(g)
        idx.addFeature(f)
    return idx


def tick(progress, v, msg=None, log=None):
    progress(v)
    if msg and log:
        log(msg)
    QApplication.processEvents()


# ------------------------------------------------------------------ hücre üretimi ve refüj/kavşak/yol koridoru elemesi
def strip_polygon_holes(geom):
    """Poligonların içindeki tüm iç halkaları (delikleri / alakasız iç siyah çizgileri) temizler, yalnızca dış sınırı korur."""
    if geom is None or geom.isEmpty():
        return geom
    ext_parts = []
    for part in poly_parts(geom):
        if part.isEmpty():
            continue
        poly = part.asPolygon()
        if poly and len(poly[0]) >= 4:
            ext_parts.append(QgsGeometry.fromPolygonXY([poly[0]]))
    if not ext_parts:
        return geom
    u = QgsGeometry.unaryUnion(ext_parts) if len(ext_parts) > 1 else ext_parts[0]
    if u and not u.isEmpty() and not u.isGeosValid():
        u = u.makeValid()
    return u


def is_sliver_or_median_cell(poly, has_real_block=False, min_width_m=14.0, strict_corridor=False):
    area = poly.area()
    perim = poly.length()
    if perim <= 0.0:
        return True
    pp = (4.0 * math.pi * area) / (perim * perim)
    thickness = (2.0 * area) / perim

    if not has_real_block:
        eff_min_w = 22.0 if strict_corridor else min_width_m
        eff_min_pp = 0.16 if strict_corridor else 0.12
        min_area = 650.0 if strict_corridor else 450.0
        if area < min_area:
            return True
        if pp < eff_min_pp or thickness < eff_min_w:
            return True
        eroded = poly.buffer(-eff_min_w * 0.48, 4)
        if eroded is None or eroded.isEmpty():
            return True
    else:
        if pp < 0.085 and thickness < 11.5:
            return True

    return False


def build_cells_from_roads(study, road_geoms, real_block_geoms=None, filter_medians=True):
    lines = []
    bl = study.convertToType(QgsWkbTypes.GeometryType.LineGeometry, True)
    if bl is not None and not bl.isEmpty():
        lines.append(bl)
    sb = study.boundingBox()
    for g in road_geoms:
        if not g.boundingBox().intersects(sb):
            continue
        lines.extend(line_parts(g.intersection(study)))
    noded = QgsGeometry.unaryUnion(lines)
    faces = QgsGeometry.polygonize([noded])
    raw_cells = []
    for p in faces.asGeometryCollection():
        if p.isEmpty() or p.area() < 1.0:
            continue
        if study.contains(p.pointOnSurface()):
            raw_cells.append(strip_polygon_holes(p))

    if not filter_medians or len(raw_cells) <= 2:
        return raw_cells, 0

    strict_corridor = bool(real_block_geoms)
    blk_idx = build_index(real_block_geoms) if real_block_geoms else None
    has_blk = [False] * len(raw_cells)
    if blk_idx and real_block_geoms:
        for i, cg in enumerate(raw_cells):
            c_area = max(1.0, cg.area())
            ov_sum = 0.0
            for bid in blk_idx.intersects(cg.boundingBox()):
                bg = real_block_geoms[bid]
                p = bg.centroid().asPoint()
                pg = QgsGeometry.fromPointXY(p)
                if not bg.contains(pg):
                    pg = QgsGeometry.fromPointXY(bg.pointOnSurface().asPoint())
                if cg.contains(pg):
                    has_blk[i] = True
                    break
                inter = cg.intersection(bg)
                if inter and not inter.isEmpty():
                    ov_sum += inter.area()
                    if ov_sum / c_area >= 0.15 or ov_sum >= 250.0:
                        has_blk[i] = True
                        break

    is_median = [
        is_sliver_or_median_cell(raw_cells[i], has_blk[i], min_width_m=14.0, strict_corridor=strict_corridor)
        for i in range(len(raw_cells))
    ]
    if all(is_median) or not any(is_median):
        return raw_cells, 0

    work_cells = list(raw_cells)
    c_idx = build_index(work_cells)
    parent = list(range(len(work_cells)))

    def find_root(u):
        while parent[u] != u:
            parent[u] = parent[parent[u]]
            u = parent[u]
        return u

    for _pass in range(6):
        changed = False
        for i in range(len(work_cells)):
            ri = find_root(i)
            if not is_median[ri]:
                continue
            cg = work_cells[i]
            best_nb = -1
            best_shared = -1.0
            for j in c_idx.intersects(cg.boundingBox()):
                rj = find_root(j)
                if rj == ri:
                    continue
                if is_median[rj] and _pass < 4:
                    continue
                inter = cg.intersection(work_cells[j])
                sh_len = inter.length() if inter and not inter.isEmpty() else 0.0
                if sh_len > best_shared:
                    best_shared = sh_len
                    best_nb = rj
            if best_nb >= 0 and best_shared > 0.05:
                parent[ri] = best_nb
                changed = True
        if not changed:
            break

    grouped = defaultdict(list)
    for i in range(len(work_cells)):
        grouped[find_root(i)].append(work_cells[i])

    merged_cells = []
    absorbed_count = sum(1 for m in is_median if m)
    for root_id, glist in grouped.items():
        if len(glist) == 1:
            merged_cells.append(strip_polygon_holes(glist[0]))
        else:
            u = strip_polygon_holes(QgsGeometry.unaryUnion(glist))
            for part in poly_parts(u):
                if part.area() > 1.0:
                    merged_cells.append(strip_polygon_holes(part))

    return merged_cells, max(0, absorbed_count)


def build_cells_grid(study, size):
    bb = study.boundingBox()
    cells = []
    x = bb.xMinimum()
    while x < bb.xMaximum():
        y = bb.yMinimum()
        while y < bb.yMaximum():
            sq = QgsGeometry.fromRect(QgsRectangle(x, y, x + size, y + size))
            for p in poly_parts(sq.intersection(study)):
                if p.area() > 1.0:
                    cells.append(p)
            y += size
        x += size
    return cells


def build_adjacency(cells):
    idx = build_index(cells)
    adj = {i: set() for i in range(len(cells))}
    for i, g in enumerate(cells):
        bb = g.boundingBox()
        for j in idx.intersects(bb):
            if j <= i:
                continue
            gj = cells[j]
            if not g.intersects(gj):
                continue
            inter = g.intersection(gj)
            if inter.isEmpty():
                continue
            if inter.length() > 1.0:
                adj[i].add(j)
                adj[j].add(i)
    return adj, idx


# ------------------------------------------------------------------ hücre ölçümleri
def new_stat(area):
    return {
        "area": area, "n": 0, "barea": 0.0, "kat_w": 0.0, "kat_a": 0.0,
        "lu": defaultdict(float), "sub_lu": defaultdict(float), "lu_a": 0.0,
        "bit": 0.0, "bit_a": 0.0, "kotu": 0.0, "kotu_a": 0.0,
        "nufus": 0.0, "konut_insaat_m2": 0.0,
        "yd": Counter(), "ext": {}, "egim": None, "yg_w": 0.0, "yg_l": 0.0,
        "road_kap": Counter(), "road_tur": Counter(), "road_len": 0.0,
        "donati_mesafe_m": None, "bos_arazi_orani": 1.0,
    }


BAD_WORDS = ("kotu", "harap", "yikik", "terk", "bakimsiz", "riskli", "hasarli", "metruk", "orta-kotu")


def filter_real_blocks(blocks, f_kul, filter_medians=True):
    if not filter_medians:
        return blocks, 0
    real_blocks = []
    skipped = 0
    for f, g in blocks:
        kul = val(f, f_kul)
        if kul is not None and alg.is_road_island_text(kul):
            skipped += 1
            continue
        area = g.area()
        perim = g.length()
        if perim > 0:
            pp = (4.0 * math.pi * area) / (perim * perim)
            thickness = (2.0 * area) / perim
            if pp < 0.065 and thickness < 6.0:
                skipped += 1
                continue
        real_blocks.append((f, g))
    return real_blocks, skipped


def find_cell_index(g, cells, cidx):
    p = g.centroid().asPoint()
    pg = QgsGeometry.fromPointXY(p)
    if g.type() == QgsWkbTypes.GeometryType.PolygonGeometry and not g.contains(pg):
        p = g.pointOnSurface().asPoint()
        pg = QgsGeometry.fromPointXY(p)
    for c in cidx.intersects(QgsRectangle(p.x() - 0.01, p.y() - 0.01, p.x() + 0.01, p.y() + 0.01)):
        if cells[c].contains(pg):
            return c
    # Nokta tam yol sınırına denk geldiyse en yüksek kesişim alanına veya en yakın mesafeye sahip hücreyi seç
    cands = cidx.intersects(g.boundingBox())
    if cands:
        best_c = -1
        best_a = 0.0
        for c in cands:
            if cells[c].intersects(g):
                ia = cells[c].intersection(g).area() if g.type() == QgsWkbTypes.GeometryType.PolygonGeometry else 1.0
                if ia > best_a:
                    best_a = ia
                    best_c = c
        if best_c >= 0:
            return best_c
        return min(cands, key=lambda c: cells[c].distance(pg))
    return -1


def is_residential_or_mixed_use(kul_val, lu_dict=None):
    """
    Bir imar adasının 'Konut' veya 'Karma (Konut + Ticaret)' adası olup olmadığını tespit eder.
    Döndürür: (is_res_or_mixed: bool, res_weight_factor: float)
    - Düşük / Seyrek / Gelişme Konut (dusukkonut, seyrekkonut vb.) -> (True, 0.65)
    - Orta Yoğunluklu Konut -> (True, 1.0)
    - Yüksek Yoğunluklu Konut -> (True, 1.20)
    - Karma (Konut + Ticari) ada -> (True, 0.80)
    - Mezarlık, Sanayi, Tarım, Donatı vb. konut dışı ada -> (False, 0.0)
    """
    if kul_val is None and not lu_dict:
        return False, 0.0
    t = alg.norm_tr(kul_val) if kul_val is not None else ""
    t_compact = re.sub(r"[\s_\-]+", "", t)
    lu = lu_dict if lu_dict is not None else alg.classify_landuse(kul_val)

    # Mezarlık alanı kesinlikle konut değildir ve 0 nüfus alır
    if any(w in t or w in t_compact for w in ("mezarlik", "mezar", "kabristan", "gomutluk")):
        return False, 0.0

    # Açıkça sanayi, tarım veya kamu donatısı olup içinde konut/karma ibaresi geçmeyenler 0 alır
    has_konut_word = any(
        w in t or w in t_compact for w in (
            "konut", "mesken", "apart", "villa", "ikamet", "yasam",
            "rezidans", "lojm", "karma", "yerlesim", "yerlesik", "t+k", "k+t", "tick",
            "ticaret+konut", "ticaret-konut", "dusukkonut", "seyrekkonut", "ortakonut", "yuksekkonut"
        )
    )
    w_kon = lu.get("konut", 0.0)
    w_tic = lu.get("ticaret", 0.0)
    w_san = lu.get("sanayi", 0.0)
    w_tar = lu.get("tarim", 0.0)

    if not has_konut_word and w_kon <= 0.0:
        return False, 0.0
    if w_san >= 0.5 and not has_konut_word:
        return False, 0.0
    if w_tar >= 0.7 and not has_konut_word:
        return False, 0.0

    is_mixed = ("karma" in t or "ticar" in t or "t+k" in t or "k+t" in t or "tick" in t or w_tic > 0.0)
    if is_mixed:
        return True, 0.80
    if any(w in t or w in t_compact for w in ("dusuk", "seyrek", "kirsal", "gelisme", "villa", "bagevi", "azyogun")):
        return True, 0.65
    if any(w in t or w in t_compact for w in ("yuksek", "yogun", "cokkat")):
        return True, 1.20
    return True, 1.0


def accumulate_polygons(items, cells, cidx, S, fields, log, label_name="Ada/Yapı", count_footprint=True):
    """
    İmar adalarını veya opsiyonel tekil yapı stokunu hücrelere yerleştirir.
    - İmar adaları birden fazla hücreyle kesişiyorsa kesişim alanı oranında hücrelere dağıtılır (hiçbir konut adası kaybolmaz).
    - Kat sayısı hesabı taban alanı ağırlıklı ortalama (area-weighted mean) olarak hesaplanır.
    """
    f_kat, f_kul, f_yd, f_dur, f_nuf = (fields.get(k) for k in ("kat", "kullanim", "yd", "durum", "nufus"))
    placed = 0
    for idx_b, (f, g) in enumerate(items):
        if idx_b % 1000 == 0:
            QApplication.processEvents()
        total_a = g.area() if g.type() == QgsWkbTypes.GeometryType.PolygonGeometry else 100.0
        if total_a <= 0.0:
            continue

        # İmar adası modunda (count_footprint=False) kesişen tüm hücrelere alan oranında dağıt; bina modunda merkez hücreye ata
        target_cells = []
        if not count_footprint and g.type() == QgsWkbTypes.GeometryType.PolygonGeometry:
            for c in cidx.intersects(g.boundingBox()):
                if cells[c].intersects(g):
                    ia = cells[c].intersection(g).area()
                    if ia > 0.5:
                        target_cells.append((c, ia))
        if not target_cells:
            ci = find_cell_index(g, cells, cidx)
            if ci < 0:
                continue
            target_cells = [(ci, total_a)]

        placed += 1
        kul = val(f, f_kul)
        lu = alg.classify_landuse(kul) if kul is not None else {}
        sub_lu = alg.classify_landuse_subtypes(kul) if kul is not None else {}
        is_res_blk, res_fac = is_residential_or_mixed_use(kul, lu)
        is_non_building_open = (
            bool(lu)
            and (lu.get("tarim", 0.0) >= 0.7 or sub_lu.get("mezarlik", 0.0) >= 0.5)
            and not is_res_blk
            and lu.get("ticaret", 0.0) == 0.0
        )

        kat = to_float(val(f, f_kat))
        eff_kat = kat if (kat is not None and 0 < kat <= 60 and not is_non_building_open) else 1.0
        yd = val(f, f_yd)
        dur = val(f, f_dur)
        nuf = to_float(val(f, f_nuf))
        sum_ia = sum(ia for _, ia in target_cells) or total_a

        for ci, ia in target_cells:
            s = S[ci]
            share_ratio = ia / sum_ia
            a = ia if not count_footprint else (total_a * share_ratio)

            if lu:
                for cls, w in lu.items():
                    s["lu"][cls] += a * w
                for sub_k, sub_v in sub_lu.items():
                    if sub_v > 0.0:
                        s["sub_lu"][sub_k] += a * sub_v
                s["lu_a"] += a

            if count_footprint and not is_non_building_open:
                s["n"] += (1 if len(target_cells) == 1 else share_ratio)
                s["barea"] += a

            if kat is not None and 0 < kat <= 60 and not is_non_building_open:
                w_area = a if count_footprint else min(a, 2500.0)
                s["kat_w"] += kat * w_area
                s["kat_a"] += w_area

            if lu:
                konut_weight = res_fac if is_res_blk else 0.0
            else:
                konut_weight = 0.5 if count_footprint else 0.0

            if count_footprint and konut_weight > 0.0 and not is_non_building_open:
                s["konut_insaat_m2"] += a * eff_kat * konut_weight

            if yd is not None and not is_non_building_open:
                t = alg.norm_tr(yd)
                s["yd"][str(yd).strip()] += a
                s["bit_a"] += a
                if "bitisik" in t:
                    s["bit"] += a

            if dur is not None and not is_non_building_open:
                s["kotu_a"] += a
                fl = to_float(dur)
                t = alg.norm_tr(dur)
                if any(w in t for w in BAD_WORDS) or (fl is not None and re.fullmatch(r"\s*\d+(?:[.,]0+)?\s*", str(dur)) and fl >= 3):
                    s["kotu"] += a

            if nuf is not None and nuf > 0 and konut_weight > 0.0:
                s["nufus"] += nuf * share_ratio

    log(f"• [{label_name}] {placed}/{len(items)} birim alan ağırlıklı kat ve konut/karma nüfus kurallarıyla işlendi.")


def estimate_residential_block_populations(blocks, bldgs, fields, bfields, total_population, log):
    """
    KULLANICI ALGORİTMASI (Tahmini Nüfus Dağıtımı):
    - Yalnızca 'Konut' ve 'Karma (Konut + Ticari)' olarak tanımlı imar adalarını seçer (Sanayi/Tarım/Donatı = 0).
    - Her konut/karma adasının:
      1) İçindeki tekil bina sayısını (bina_sayisi) ve bina taban alanını,
      2) Adanın kendi geometrik büyüklüğünü (ada_alani_m2),
      3) Varsa kat adedini (kat)
      birlikte ağırlıklandıran bileşik bir kapasite skoru (W_ada) kurar.
    - Girilen toplam nüfusu (ör. 65.000 kişi) bu konut/karma adalarına dağıtarak her adanın tahmini nüfusunu üretir.
    """
    if total_population <= 0 or not blocks:
        return []

    f_kul = fields.get("kullanim") if fields else None
    f_kat = fields.get("kat") if fields else None
    bf_kat = bfields.get("kat") if bfields else None

    bldg_geoms = [g for _, g in bldgs] if bldgs else []
    bldg_idx = build_index(bldg_geoms) if bldg_geoms else None

    res_Candidates = []
    for f_blk, g_blk in blocks:
        kul_val = val(f_blk, f_kul)
        lu = alg.classify_landuse(kul_val) if kul_val is not None else {}
        is_res, res_fac = is_residential_or_mixed_use(kul_val, lu)
        # Eğer kullanım sütunu seçilmemişse tüm gerçek adaları aday kabul et
        if f_kul is None and not lu:
            is_res, res_fac = True, 1.0
        if not is_res or res_fac <= 0.0:
            continue

        ada_area = max(1.0, g_blk.area())
        blk_kat = to_float(val(f_blk, f_kat))

        b_cnt = 0
        b_area_sum = 0.0
        b_kat_w = 0.0
        if bldg_idx and bldg_geoms:
            for bid in bldg_idx.intersects(g_blk.boundingBox()):
                bg = bldg_geoms[bid]
                bp = bg.centroid().asPoint()
                bpg = QgsGeometry.fromPointXY(bp)
                inside = g_blk.contains(bpg)
                if not inside and g_blk.intersects(bg):
                    inter_a = g_blk.intersection(bg).area()
                    inside = (inter_a >= 0.25 * max(1.0, bg.area()))
                if inside:
                    b_cnt += 1
                    ba = max(10.0, bg.area())
                    b_area_sum += ba
                    if bf_kat:
                        bk = to_float(val(bldgs[bid][0], bf_kat))
                        if bk is not None and 0 < bk <= 60:
                            b_kat_w += bk * ba

        if blk_kat is not None and 0 < blk_kat <= 60:
            eff_kat = blk_kat
        elif b_kat_w > 0 and b_area_sum > 0:
            eff_kat = b_kat_w / b_area_sum
        else:
            eff_kat = 2.5

        res_Candidates.append({
            "geom": g_blk,
            "res_fac": res_fac,
            "ada_area": ada_area,
            "b_cnt": b_cnt,
            "b_area": b_area_sum,
            "kat": eff_kat,
        })

    if not res_Candidates:
        return []

    non_zero_b = [c["b_cnt"] for c in res_Candidates if c["b_cnt"] > 0]
    avg_b_cnt = (sum(non_zero_b) / len(non_zero_b)) if non_zero_b else 1.0
    avg_ada_area = sum(c["ada_area"] for c in res_Candidates) / len(res_Candidates)
    avg_kat = sum(c["kat"] for c in res_Candidates) / len(res_Candidates)
    has_any_bldg = bool(non_zero_b)

    tot_w = 0.0
    for c in res_Candidates:
        kat_mult = 0.65 + 0.35 * (c["kat"] / max(1.0, avg_kat))
        norm_area = min(6.0, c["ada_area"] / max(1.0, avg_ada_area))
        if has_any_bldg:
            if c["b_cnt"] > 0:
                norm_bldg = c["b_cnt"] / max(1.0, avg_b_cnt)
                # Bina sayısı (%65) + Ada büyüklüğü (%35) + Kat çarpanı
                w = c["res_fac"] * kat_mult * (0.65 * norm_bldg + 0.35 * norm_area)
            else:
                # Konut adası olup içinde tekil bina çizilmemişse ada büyüklüğüne göre düşük taban ağırlık (%20) al
                w = c["res_fac"] * kat_mult * (0.20 * norm_area)
        else:
            w = c["res_fac"] * kat_mult * norm_area
        c["weight"] = max(0.0, w)
        tot_w += c["weight"]

    if tot_w <= 0.0:
        return []

    for c in res_Candidates:
        c["pop"] = total_population * (c["weight"] / tot_w)

    total_b_in_res = sum(c["b_cnt"] for c in res_Candidates)
    log(
        f"• [Tahmini Nüfus Algoritması] Toplam {int(round(total_population)):,} kişi; "
        f"{len(res_Candidates)} adet Konut / Karma (Konut+Ticaret) adasına, adaların içindeki "
        f"bina sayısı ({total_b_in_res} bina), ada büyüklüğü (m²) ve kat adedine göre tahmini olarak dağıtıldı."
    )
    return res_Candidates


def cell_residential_weight(s):
    """
    KURAL 1: Bir hücrenin nüfus alma ağırlığını hesaplar.
    'lu_sanayi' (Sanayi/Depolama) ve 'lu_tarim' (Açık/Tarım) alanlarının nüfus ağırlık katsayısı KESİNLİKLE 0'dır.
    Sadece 'lu_konut' ve konut içeren karma kullanım ('lu_ticaret' + 'lu_konut') nüfus alır.
    """
    taks = min(1.0, s["barea"] / s["area"]) if s["area"] > 0 else 0.0
    if s["lu_a"] > 0:
        sh_san = s["lu"].get("sanayi", 0.0) / s["lu_a"]
        sh_tar = s["lu"].get("tarim", 0.0) / s["lu_a"]
        sh_kon = s["lu"].get("konut", 0.0) / s["lu_a"]
        sh_tic = s["lu"].get("ticaret", 0.0) / s["lu_a"]

        # Sadece hiç konut yoksa sıfırla; hücrede konut adası varsa (sh_kon > 0) kesinlikle koru!
        if sh_kon <= 0.005 and (sh_san >= 0.45 or sh_tar >= 0.75 or sh_tic <= 0.05):
            return 0.0

        res_factor = max(0.05, sh_kon + (0.40 * sh_tic if sh_kon > 0.0 else 0.0))
        avg_kat = (s["kat_w"] / s["kat_a"]) if s["kat_a"] > 0 else 2.0
        bldg_term = max(1.0, s["n"]) * 120.0
        area_term = s["lu"].get("konut", 0.0) + 0.5 * s["lu"].get("ticaret", 0.0)
        base_m2 = 0.65 * bldg_term + 0.35 * max(100.0, area_term * 0.25)
        return base_m2 * max(1.0, avg_kat) * res_factor
    else:
        if taks < 0.02 and s["n"] == 0:
            return 0.0
        return (s["n"] * 120.0 + s["area"] * 0.10) if s["n"] > 0 else 0.0


def apply_population_settings(S, pop_cfg, log, cells=None, cidx=None, res_block_pops=None):
    """
    KURAL 1 & TAHMİNİ NÜFUS ALGORİTMASI:
    - Konut ve Karma (Konut+Ticaret) adaları üzerinden hesaplanan tahmini nüfusları (`res_block_pops`)
      hücrelerle kesişim alanına göre dağıtır.
    - Eğer ada katmanı yoksa hücre ağırlıklarına (`cell_residential_weight`) göre dağıtır.
    """
    mode = pop_cfg.get("mode", "manual_total")
    manual_total = float(pop_cfg.get("manual_total", 0) or 0)
    per_bldg = float(pop_cfg.get("per_bldg", 0) or 0)

    if res_block_pops and cells and cidx and manual_total > 0:
        for s in S:
            s["nufus"] = 0.0
        for rc in res_Candidates if False else res_block_pops:
            g_blk = rc["geom"]
            pop_val = rc["pop"]
            if pop_val <= 0.0:
                continue
            hits = []
            for c in cidx.intersects(g_blk.boundingBox()):
                if cells[c].intersects(g_blk):
                    ia = cells[c].intersection(g_blk).area()
                    if ia > 0.1:
                        hits.append((c, ia))
            if hits:
                tot_ia = sum(ia for _, ia in hits)
                for c, ia in hits:
                    S[c]["nufus"] += pop_val * (ia / tot_ia)
            else:
                ci = find_cell_index(g_blk, cells, cidx)
                if ci >= 0:
                    S[ci]["nufus"] += pop_val
        return

    for s in S:
        if cell_residential_weight(s) <= 0.0:
            s["nufus"] = 0.0

    col_sum = sum(s["nufus"] for s in S)

    if manual_total > 0 and (mode in ("manual_total", "auto") and col_sum <= 0 or mode == "manual_total"):
        weights = [cell_residential_weight(s) for s in S]
        tot_w = sum(weights)
        for s, w in zip(S, weights):
            s["nufus"] = manual_total * (w / tot_w) if tot_w > 0 and w > 0 else 0.0
        log(f"• [Tahmini Nüfus Dağıtımı] Girilen toplam {int(manual_total):,} kişi; bina sayısı ve konut alanı ağırlıklarına göre dağıtıldı.")
    elif mode == "per_building" and per_bldg > 0:
        for s in S:
            w = cell_residential_weight(s)
            if w <= 0.0 or s["n"] <= 0:
                s["nufus"] = 0.0
                continue
            avg_k = (s["kat_w"] / s["kat_a"]) if s["kat_a"] > 0 else 1.0
            sh_kon = (s["lu"].get("konut", 0.0) / s["lu_a"]) if s["lu_a"] > 0 else 0.70
            sh_tic = (s["lu"].get("ticaret", 0.0) / s["lu_a"]) if s["lu_a"] > 0 else 0.0
            res_ratio = min(1.0, sh_kon + (0.35 * sh_tic if sh_kon >= 0.10 else 0.0))
            s["nufus"] = s["n"] * max(1.0, avg_k) * per_bldg * res_ratio
        tot_calc = sum(s["nufus"] for s in S)
        log(f"• [Tahmini Nüfus Dağıtımı] Konut ve karma kullanım hücreleri için toplam {int(round(tot_calc)):,} kişi nüfus hesaplandı.")
    elif col_sum > 0:
        log(f"• [Nüfus Dağıtımı] Katman sütunundan toplam {int(round(col_sum)):,} kişi yerleşik nüfus okundu.")


def assign_zone_populations_from_blocks(zones, res_block_pops):
    """
    Nihai alt bölge poligonları (`z['geom']`) oluştuktan sonra, her bir Konut / Karma kullanım adasının
    tahmini nüfusunu doğrudan kesiştiği alt bölgeye atar.
    Böylece içinde konut adası bulunan hiçbir alt bölgede (ör. M12) nüfus 0 kalmaz ve
    alt bölgelerin tahmini nüfus toplamı girilen toplam nüfusa %100 eşit olur.
    """
    if not zones or not res_block_pops:
        return
    z_geoms = [z["geom"] for z in zones]
    z_idx = build_index(z_geoms)
    for z in zones:
        z["nufus"] = 0.0
        z["konut_ada_sayisi"] = 0

    for rc in res_block_pops:
        g_blk = rc["geom"]
        pop_val = rc["pop"]
        if pop_val <= 0.0:
            continue
        hits = []
        for zi in z_idx.intersects(g_blk.boundingBox()):
            if z_geoms[zi].intersects(g_blk):
                ia = z_geoms[zi].intersection(g_blk).area()
                if ia > 0.1:
                    hits.append((zi, ia))
        if hits:
            tot_ia = sum(ia for _, ia in hits)
            for zi, ia in hits:
                zones[zi]["nufus"] += pop_val * (ia / tot_ia)
                if ia >= 0.20 * rc["ada_area"]:
                    zones[zi]["konut_ada_sayisi"] = zones[zi].get("konut_ada_sayisi", 0) + 1
        else:
            p = g_blk.centroid().asPoint()
            pg = QgsGeometry.fromPointXY(p)
            best_zi = min(range(len(zones)), key=lambda zi: z_geoms[zi].distance(pg))
            zones[best_zi]["nufus"] += pop_val
            zones[best_zi]["konut_ada_sayisi"] = zones[best_zi].get("konut_ada_sayisi", 0) + 1


def accumulate_roads(roads_fg, cells, cidx, S, rfields, log):
    if not roads_fg:
        return
    f_gen = rfields.get("r_genislik")
    f_kap = rfields.get("r_kaplama")
    f_tur = rfields.get("r_tur")
    matched_r = 0
    for rf, rg in roads_fg:
        bb = rg.boundingBox()
        bb_buf = QgsRectangle(bb.xMinimum() - 8.0, bb.yMinimum() - 8.0, bb.xMaximum() + 8.0, bb.yMaximum() + 8.0)
        cands = cidx.intersects(bb_buf)
        if not cands:
            continue
        rlen = max(1.0, rg.length())
        gen_v = to_float(val(rf, f_gen))
        kap_v = val(rf, f_kap)
        tur_v = val(rf, f_tur)
        hit_any = False
        for c in cands:
            if cells[c].distance(rg) <= 12.0:
                hit_any = True
                s = S[c]
                s["road_len"] += rlen
                if gen_v is not None and 1.0 <= gen_v <= 100.0:
                    s["yg_w"] += gen_v * rlen
                    s["yg_l"] += rlen
                if kap_v is not None:
                    s["road_kap"][str(kap_v).strip()] += rlen
                if tur_v is not None:
                    s["road_tur"][str(tur_v).strip()] += rlen
        if hit_any:
            matched_r += 1
    log(f"• [Ulaşım Ağı] {matched_r}/{len(roads_fg)} yol segmenti (genişlik, kaplama, kademe) hücrelerle ilişkilendirildi.")


def compute_extra(cells, geoms, kind):
    idx = build_index(geoms)
    out = []
    for cg in cells:
        if kind in ("share", "count"):
            a, cnt = 0.0, 0
            for j in idx.intersects(cg.boundingBox()):
                gj = geoms[j]
                if not cg.intersects(gj):
                    continue
                cnt += 1
                if gj.type() == QgsWkbTypes.GeometryType.PolygonGeometry:
                    a += cg.intersection(gj).area()
                else:
                    a += cg.area()
            out.append(float(cnt) if kind == "count" else min(1.0, a / cg.area()))
        else:
            ids = idx.nearestNeighbor(cg.centroid().asPoint(), 3)
            d = min((cg.distance(geoms[j]) for j in ids), default=None)
            out.append(d)
    return out


def make_sampler(dem, work_crs):
    prov = dem.dataProvider()
    xf = None
    if dem.crs() != work_crs:
        xf = QgsCoordinateTransform(work_crs, dem.crs(), QgsProject.instance())

    def sample(x, y):
        p = QgsPointXY(x, y)
        if xf is not None:
            try:
                p = xf.transform(p)
            except Exception:
                return None
        v, ok = prov.sample(p, 1)
        if not ok or v is None:
            return None
        v = float(v)
        if math.isnan(v) or v < -500:
            return None
        return v
    return sample


def cell_slope_and_elev(cg, sample, is_slope, step):
    bb = cg.boundingBox()
    n = 4
    pts = []
    for i in range(n):
        for j in range(n):
            x = bb.xMinimum() + (i + 0.5) * bb.width() / n
            y = bb.yMinimum() + (j + 0.5) * bb.height() / n
            if cg.contains(QgsGeometry.fromPointXY(QgsPointXY(x, y))):
                pts.append((x, y))
    if not pts:
        c = cg.pointOnSurface().asPoint()
        pts = [(c.x(), c.y())]
    vals, elevs = [], []
    for x, y in pts:
        if is_slope:
            v = sample(x, y)
            if v is not None:
                vals.append(v)
            continue
        zc = sample(x, y)
        if zc is not None:
            elevs.append(zc)
        ze, zw = sample(x + step, y), sample(x - step, y)
        zn, zs = sample(x, y + step), sample(x, y - step)
        if None in (ze, zw, zn, zs):
            continue
        gx, gy = (ze - zw) / (2 * step), (zn - zs) / (2 * step)
        vals.append(100.0 * math.hypot(gx, gy))
    avg_slope = (sum(vals) / len(vals)) if vals else None
    avg_elev = (sum(elevs) / len(elevs)) if elevs else None
    return avg_slope, avg_elev


def cell_slope(cg, sample, is_slope, step):
    return cell_slope_and_elev(cg, sample, is_slope, step)[0]


# ------------------------------------------------------------------ ana boru hattı
def run_pipeline(P, log, progress):
    work_crs = P["work_crs"]
    K = P["K"]
    filter_medians = P.get("filter_medians", True)

    if work_crs.isGeographic():
        raise RuntimeError("Katmanlar coğrafi (derece) CRS'te. Lütfen metrik bir CRS'e çevirin "
                           "(ör. EPSG:5253 [İzmir / TUREF] veya EPSG:32635) ve tekrar deneyin.")

    tick(progress, 5, "1/7 Çalışma alanı, imar adaları ve opsiyonel yapı stoku okunuyor...", log)
    raw_blocks = read_geoms(P["block_layer"], work_crs) if P.get("block_layer") else []
    blocks, skipped_medians = filter_real_blocks(raw_blocks, P["fields"].get("kullanim"), filter_medians=filter_medians)
    if skipped_medians > 0:
        log(f"• Ada katmanındaki {skipped_medians} adet refüj/kavşak poligonu süzüldü.")

    raw_bldgs = read_geoms(P["bldg_layer"], work_crs) if P.get("bldg_layer") else []
    bldgs, _ = filter_real_blocks(raw_bldgs, P.get("bfields", {}).get("kullanim"), filter_medians=filter_medians)

    roads_fg = read_geoms(P["road_layer"], work_crs) if P.get("road_layer") else []
    if P.get("boundary_layer"):
        bg = [g for _, g in read_geoms(P["boundary_layer"], work_crs)]
        study = QgsGeometry.unaryUnion(bg)
    elif blocks or bldgs:
        base_g = [g for _, g in (blocks or bldgs)]
        study = QgsGeometry.unaryUnion(base_g).convexHull().buffer(150.0, 8)
    elif roads_fg:
        study = QgsGeometry.unaryUnion([g for _, g in roads_fg]).convexHull().buffer(80.0, 8)
    else:
        raise RuntimeError("Plan sınırı, yol ağı, ada veya yapı katmanından en az biri seçilmelidir.")
    if study.isEmpty():
        raise RuntimeError("Plan sınırı geometrisi boş.")
    if not study.isGeosValid():
        study = study.makeValid()

    tick(progress, 12, "2/7 Yol ağından imar adası hücreleri üretiliyor...", log)
    real_ref_geoms = [g for _, g in blocks] + [g for _, g in bldgs]
    if roads_fg:
        roads = [g for _, g in roads_fg]
        cells, absorbed = build_cells_from_roads(study, roads, real_block_geoms=real_ref_geoms, filter_medians=filter_medians)
        log(f"• {len(cells)} net imar adası hücresi üretildi ({absorbed} refüj/kavşak/yol şeridi komşu adalara katıldı).")
        if len(cells) < max(K * 2, 10):
            cells = build_cells_grid(study, P["grid_size"])
    else:
        cells = build_cells_grid(study, P["grid_size"])
    n = len(cells)
    if n < 2:
        raise RuntimeError("Yeterli hücre üretilemedi.")
    K = min(K, n)
    tick(progress, 22)
    adj, cidx = build_adjacency(cells)
    ccent = [g.centroid().asPoint() for g in cells]
    pts = [(p.x(), p.y()) for p in ccent]
    alg.connect_components(adj, pts)
    areas = [g.area() for g in cells]
    S = [new_stat(a) for a in areas]

    # 3) hücre ölçümleri
    tick(progress, 32, "3/7 Ada, Tekil Yapı, Nüfus, Yol ve Doğal Eşik verileri hücrelere işleniyor...", log)
    if blocks and bldgs:
        accumulate_polygons(blocks, cells, cidx, S, P["fields"], log, label_name="İmar Adaları", count_footprint=False)
        accumulate_polygons(bldgs, cells, cidx, S, P.get("bfields", {}), log, label_name="Tekil Yapı Stoku", count_footprint=True)
    elif bldgs:
        accumulate_polygons(bldgs, cells, cidx, S, P.get("bfields", {}), log, label_name="Tekil Yapı Stoku", count_footprint=True)
    elif blocks:
        accumulate_polygons(blocks, cells, cidx, S, P["fields"], log, label_name="İmar Adaları / Yapılar", count_footprint=True)

    # Tahmini Nüfus Hesabı (Konut ve Karma Adalar + Bina Sayısı + Ada Büyüklüğü Algoritması)
    pop_cfg = P.get("pop_cfg", {}) or {}
    manual_total = float(pop_cfg.get("manual_total", 0) or 0)
    res_block_pops = estimate_residential_block_populations(
        blocks, bldgs, P["fields"], P.get("bfields", {}), manual_total, log
    )
    apply_population_settings(S, pop_cfg, log, cells=cells, cidx=cidx, res_block_pops=res_block_pops)

    if roads_fg:
        accumulate_roads(roads_fg, cells, cidx, S, P.get("rfields", {}), log)

    ext_kinds = {}
    used_keys = Counter()
    extra_donati_geoms = []
    for ex in P["extras"]:
        role = ex["role"]
        base_kind = {r[1]: r[2] for r in ROLES}[role]
        geoms = [g for _, g in read_geoms(ex["layer"], work_crs)]
        if not geoms:
            continue
        if role in ("donati", "saglik", "toplanma"):
            extra_donati_geoms.extend(geoms)
        gtype = geoms[0].type()
        kind = base_kind
        if kind == "auto":
            kind = "share" if gtype == QgsWkbTypes.GeometryType.PolygonGeometry else "dist"
        used_keys[role] += 1
        key = role if role != "genel" else "x_" + re.sub(r"\W+", "_", alg.norm_tr(ex["name"]))[:12]
        if used_keys[role] > 1 and role != "genel":
            key = f"{role}{used_keys[role]}"
        log(f"• [Doğal/Ek Katman] {ex['name']} → '{key}' kriteri hesaplandı ve kümeleme matrisine eklendi.")
        vals = compute_extra(cells, geoms, kind)
        for i, v in enumerate(vals):
            S[i]["ext"][key] = v
        ext_kinds[key] = kind
        QApplication.processEvents()

    # Donatılara (Okul, Sağlık, Park, Sosyal Tesis) Gerçek Erişim Mesafesi (500 m / 1000 m Erişim Halkaları İçin)
    donati_ref_geoms = list(extra_donati_geoms)
    f_kul_blk = P["fields"].get("kullanim")
    for f_b, g_b in blocks:
        kv = val(f_b, f_kul_blk)
        if kv is None:
            continue
        sub_b = alg.classify_landuse_subtypes(kv)
        lu_b = alg.classify_landuse(kv)
        if sub_b.get("mezarlik", 0.0) <= 0.0 and (
            sub_b.get("donati_aktif_hizmet", 0.0) > 0.0
            or sub_b.get("donati_yesil", 0.0) > 0.0
            or lu_b.get("donati", 0.0) >= 0.45
        ):
            donati_ref_geoms.append(g_b)
    if donati_ref_geoms:
        d_idx = build_index(donati_ref_geoms)
        for i, cg in enumerate(cells):
            nn_ids = d_idx.nearestNeighbor(cg.centroid().asPoint(), 4)
            d_min = min((cg.distance(donati_ref_geoms[j]) for j in nn_ids), default=None)
            S[i]["donati_mesafe_m"] = d_min
        log(f"• [Donatı & Okul Erişimi] {len(donati_ref_geoms)} donatı/okul/park birimine göre her hücrenin erişim mesafesi (500m / 1000m bantları) hesaplandı.")
    tick(progress, 48)

    if P.get("dem"):
        if not work_crs.isGeographic() or P["dem_is_slope"]:
            sampler = make_sampler(P["dem"], work_crs)
            for i, cg in enumerate(cells):
                sl, el = cell_slope_and_elev(cg, sampler, P["dem_is_slope"], P["dem_step"])
                S[i]["egim"] = sl
                S[i]["rakim"] = el
                if i % 200 == 0:
                    QApplication.processEvents()
            log("• [Topoğrafya] DEM/Eğim katmanından her hücrenin gerçek eğimi (%) ve ortalama rakımı (m) hesaplandı.")

    have = {
        "lu": any(s["lu_a"] > 0 for s in S),
        "kat": any(s["kat_a"] > 0 for s in S),
        "bit": any(s["bit_a"] > 0 for s in S),
        "kotu": any(s["kotu_a"] > 0 for s in S),
        "nufus": any(s["nufus"] > 0 for s in S),
        "egim": any(s["egim"] is not None for s in S),
        "rakim": any(s.get("rakim") is not None for s in S),
        "yg": any(s["yg_l"] > 0 for s in S),
        "rkap": any(bool(s["road_kap"]) for s in S),
        "rtur": any(bool(s["road_tur"]) for s in S),
        "blocks": bool(blocks or bldgs),
        "donati_erisim": any(s.get("donati_mesafe_m") is not None for s in S),
    }

    dens_c = [S[i]["n"] / (areas[i] / 10000.0) for i in range(n)]
    order = sorted(range(n), key=lambda i: -dens_c[i])
    top = [i for i in order[:max(3, n // 10)] if S[i]["n"] > 0] or order[:3]
    wsum = sum(max(1, S[i]["n"]) for i in top)
    center = (sum(pts[i][0] * max(1, S[i]["n"]) for i in top) / wsum,
              sum(pts[i][1] * max(1, S[i]["n"]) for i in top) / wsum)

    # 4) ÖZNİTELİK MATRİSİ (Z-Skoru) & STRATEJİ AĞIRLIKLARI
    tick(progress, 58, "4/7 Tüm girdiler Z-skoru matrisine dönüştürülüyor ve komşu hücreler birleştiriliyor...", log)

    def bos_of(s):
        taks_v = min(1.0, s["barea"] / s["area"]) if s["area"] > 0 else 0.0
        unbuilt_ground = 1.0 - min(1.0, taks_v / 0.22)
        if s["lu_a"] > 0:
            sub_bos = s["sub_lu"].get("bos_arazi", 0.0) / s["lu_a"]
            sub_seyrek = s["sub_lu"].get("konut_dusuk_seyrek", 0.0) / s["lu_a"]
            sh_tar = s["lu"].get("tarim", 0.0) / s["lu_a"]
            val_b = max(unbuilt_ground, 0.85 * sub_bos + 0.55 * sub_seyrek + 0.75 * sh_tar)
            if s["n"] == 0 and s["barea"] <= 0.0:
                val_b = max(val_b, 0.92)
            return min(1.0, max(0.0, val_b))
        return unbuilt_ground

    for s in S:
        s["bos_arazi_orani"] = bos_of(s)

    groups = defaultdict(dict)
    if have["lu"]:
        for cls in ("konut", "ticaret", "sanayi", "tarim", "donati", "sit"):
            col = []
            for s in S:
                b = bos_of(s)
                sh = s["lu"][cls] / s["lu_a"] if s["lu_a"] > 0 else 0.0
                blk_cov = min(1.0, s["lu_a"] / max(1.0, s["area"] * 0.45))
                b_eff = b * (1.0 - blk_cov)
                col.append(b_eff + (1 - b_eff) * sh if cls == "tarim" else (1 - b_eff) * sh)
            groups["lu"]["lu_" + cls] = col

        # İnce Arazi Kullanımı Ayrımları: Düşük/Seyrek Konut vs Orta/Yüksek Konut, Mezarlık ve Boş Arazi Oranı
        groups["lu"]["bos_arazi_orani"] = [s["bos_arazi_orani"] for s in S]
        if any(s["sub_lu"].get("konut_dusuk_seyrek", 0.0) > 0 for s in S):
            groups["lu"]["lu_konut_dusuk_seyrek"] = [
                (s["sub_lu"].get("konut_dusuk_seyrek", 0.0) / s["lu_a"]) if s["lu_a"] > 0 else 0.0 for s in S
            ]
        if any(s["sub_lu"].get("konut_orta_yuksek", 0.0) > 0 for s in S):
            groups["lu"]["lu_konut_orta_yuksek"] = [
                (s["sub_lu"].get("konut_orta_yuksek", 0.0) / s["lu_a"]) if s["lu_a"] > 0 else 0.0 for s in S
            ]
        if any(s["sub_lu"].get("mezarlik", 0.0) > 0 for s in S):
            groups["lu"]["lu_mezarlik"] = [
                (s["sub_lu"].get("mezarlik", 0.0) / s["lu_a"]) if s["lu_a"] > 0 else 0.0 for s in S
            ]

        # Komşuluk Etkileşimleri: Sanayi Bütünlüğü, Sanayi-Konut Yakınlığı ve Sanayi-Tarım Yakınlığı
        if any(s["lu"].get("sanayi", 0.0) > 0 for s in S):
            san_sh = [(s["lu"].get("sanayi", 0.0) / s["lu_a"]) if s["lu_a"] > 0 else 0.0 for s in S]
            kon_sh = [(s["lu"].get("konut", 0.0) / s["lu_a"]) if s["lu_a"] > 0 else 0.0 for s in S]
            tar_sh = [(s["lu"].get("tarim", 0.0) / s["lu_a"]) if s["lu_a"] > 0 else s["bos_arazi_orani"] for s in S]
            san_butunluk = []
            san_kon_gecis = []
            san_tar_gecis = []
            for i in range(n):
                nbs = list(adj.get(i, ()))
                nb_san = (sum(san_sh[j] for j in nbs) / len(nbs)) if nbs else san_sh[i]
                nb_kon = (sum(kon_sh[j] for j in nbs) / len(nbs)) if nbs else kon_sh[i]
                nb_tar = (sum(tar_sh[j] for j in nbs) / len(nbs)) if nbs else tar_sh[i]
                san_butunluk.append(0.65 * san_sh[i] + 0.35 * nb_san)
                san_kon_gecis.append(min(max(san_sh[i], nb_san), max(kon_sh[i], nb_kon)))
                san_tar_gecis.append(min(max(san_sh[i], nb_san), max(tar_sh[i], nb_tar)))
            groups["lu"]["sanayi_butunluk"] = san_butunluk
            groups["lu"]["sanayi_konut_gecisi"] = san_kon_gecis
            groups["lu"]["sanayi_tarim_gecisi"] = san_tar_gecis
    else:
        groups["lu"]["bos_arazi_orani"] = [bos_of(s) for s in S]

    if have["blocks"]:
        groups["yapi"]["taks"] = [min(1.0, s["barea"] / s["area"]) for s in S]
        groups["yapi"]["doluluk_orani"] = [1.0 - s["bos_arazi_orani"] for s in S]
        groups["yapi"]["yog"] = [math.log1p(d) for d in dens_c]
        groups["yapi"]["tane"] = [math.log1p((s["barea"] / s["n"]) / 100.0) if s["n"] else 0.0 for s in S]
        if have["kat"]:
            # KURAL 2 & 3: TAKS < %5 olan açık/tarım hücrelerinde kat değerini 0 kabul et
            groups["yapi"]["kat"] = [
                (s["kat_w"] / s["kat_a"]) if (s["kat_a"] > 0 and (s["barea"] / s["area"]) >= 0.05) else 0.0
                for s in S
            ]
        if have["bit"]:
            # KURAL 2: TAKS < %5 veya Tarım > %70 ise bitişik nizam oranı 0 kabul edilir
            groups["yapi"]["bit"] = [
                (s["bit"] / s["bit_a"]) if (s["bit_a"] > 0 and (s["barea"] / s["area"]) >= 0.05) else 0.0
                for s in S
            ]
        if have["kotu"]:
            groups["yapi"]["kotu_yapi"] = [s["kotu"] / s["kotu_a"] if s["kotu_a"] > 0 else 0.0 for s in S]
        if have["nufus"]:
            groups["yapi"]["nufus_yog"] = [math.log1p(s["nufus"] / (s["area"] / 10000.0)) for s in S]

    if have["donati_erisim"]:
        groups["yapi"]["donati_erisim_m"] = [
            math.log1p((s["donati_mesafe_m"] if s.get("donati_mesafe_m") is not None else 1500.0) / 100.0)
            for s in S
        ]
        # 500 m ve 1000 m erişim kademesi (M1'de herkes ~500m'de erişiyor vs M2'de ~1000m'de erişiyor ayrımı için)
        groups["yapi"]["erisim_500m_bandi"] = [
            1.0 if (s.get("donati_mesafe_m") or 1500.0) <= 500.0
            else (0.5 if (s.get("donati_mesafe_m") or 1500.0) <= 1000.0 else 0.0)
            for s in S
        ]

    if have["yg"]:
        groups["yapi"]["yol_gen"] = [s["yg_w"] / s["yg_l"] if s["yg_l"] > 0 else 0.0 for s in S]
    if have["rkap"]:
        top_kaps = [k for k, _ in Counter(k for s in S for k in s["road_kap"]).most_common(3)]
        for tk in top_kaps:
            groups["yapi"][f"rkap_{alg.norm_tr(tk)[:8]}"] = [
                (s["road_kap"][tk] / s["road_len"]) if s["road_len"] > 0 else 0.0 for s in S
            ]
    if have["rtur"]:
        top_turs = [k for k, _ in Counter(k for s in S for k in s["road_tur"]).most_common(3)]
        for tt in top_turs:
            groups["yapi"][f"rtur_{alg.norm_tr(tt)[:8]}"] = [
                (s["road_tur"][tt] / s["road_len"]) if s["road_len"] > 0 else 0.0 for s in S
            ]

    if have["egim"]:
        groups["dogal"]["egim"] = [s["egim"] if s["egim"] is not None else 0.0 for s in S]

    for key, kind in ext_kinds.items():
        col = []
        for s in S:
            v = s["ext"].get(key)
            if kind == "dist":
                col.append(math.log1p((v if v is not None else 5000.0) / 100.0))
            elif kind == "count":
                col.append(math.log1p(v or 0.0))
            else:
                col.append(v or 0.0)
        groups["dogal"][key] = col

    groups["geo"]["gx"] = [p[0] for p in pts]
    groups["geo"]["gy"] = [p[1] for p in pts]

    preset_mode = P.get("preset_mode", "integrated_synthesis")
    w_bos = float(P.get("w_bos", 1.8) or 1.0)
    w_erisim = float(P.get("w_erisim", 1.8) or 1.0)
    w_yol = float(P.get("w_yol", 1.5) or 1.0)
    w_odak = float(P.get("w_odak", 1.8) or 1.0)

    gw = {"lu": P["w_lu"], "yapi": P["w_yapi"], "dogal": P["w_dogal"], "geo": P["w_geo"] * 2.2}
    allcols, colw = {}, {}
    for g, cols in groups.items():
        if gw.get(g, 0.0) <= 0.0:
            continue
        z, _ = alg.zscore_columns(cols)
        if not z:
            continue
        base_w = math.sqrt(gw[g] / len(z))
        for k, v in z.items():
            full_k = g + ":" + k
            mult = 1.0
            # Strateji alt ağırlık çarpanları (Boş arazi, Donatı 500m/1000m erişimi, Yol benzerliği, Sanayi/Ticaret/Tarım odakları)
            if k in ("bos_arazi_orani", "doluluk_orani", "taks"):
                mult *= math.sqrt(max(0.2, w_bos))
            elif k in ("donati_erisim_m", "erisim_500m_bandi", "lu_donati") or k.startswith("donati"):
                mult *= math.sqrt(max(0.2, w_erisim))
            elif k == "yol_gen" or k.startswith("rkap_") or k.startswith("rtur_"):
                mult *= math.sqrt(max(0.2, w_yol))
            elif k == "lu_mezarlik":
                mult *= 2.2
            elif k in ("lu_konut_dusuk_seyrek", "lu_konut_orta_yuksek"):
                mult *= 1.45

            if preset_mode == "agri_protect" and k == "lu_tarim":
                mult *= max(1.5, w_odak)
            elif preset_mode == "commercial_focus" and k in ("lu_ticaret", "yol_gen"):
                mult *= max(1.5, w_odak)
            elif preset_mode in ("industrial_cluster", "integrated_synthesis") and k in (
                "lu_sanayi", "sanayi_butunluk", "sanayi_konut_gecisi", "sanayi_tarim_gecisi"
            ):
                mult *= max(1.35, w_odak * 0.85)
            elif preset_mode == "vacant_plan" and k in ("bos_arazi_orani", "doluluk_orani", "taks", "lu_konut_dusuk_seyrek"):
                mult *= max(1.6, w_bos * 0.9)
            elif preset_mode == "access_school" and k in ("donati_erisim_m", "erisim_500m_bandi"):
                mult *= max(1.8, w_erisim * 0.95)

            allcols[full_k] = v
            colw[full_k] = base_w * mult

    log(f"• Kümeleme algoritmasına giren aktif değişken sayısı: {len(allcols)} (Strateji: {preset_mode})")
    names = sorted(allcols)
    vecs = [[allcols[k][i] * colw[k] for k in names] for i in range(n)]
    if not names:
        vecs = [[0.0] for _ in range(n)]

    # Sanayi bütünlüğü, mezarlık bütünlüğü, boş/dolu arazi ayrımı ve 500m/1000m donatı erişim uyumu için Ward komşuluk afinitesi
    cell_san = [(S[i]["lu"].get("sanayi", 0.0) / S[i]["lu_a"]) if S[i]["lu_a"] > 0 else 0.0 for i in range(n)]
    cell_mez = [(S[i]["sub_lu"].get("mezarlik", 0.0) / S[i]["lu_a"]) if S[i]["lu_a"] > 0 else 0.0 for i in range(n)]
    cell_bos = [S[i]["bos_arazi_orani"] for i in range(n)]
    cell_don_m = [S[i].get("donati_mesafe_m") for i in range(n)]

    def synthesis_affinity(mem_a, mem_b):
        factor = 1.0
        san_a = sum(cell_san[i] for i in mem_a) / len(mem_a)
        san_b = sum(cell_san[i] for i in mem_b) / len(mem_b)
        # Sanayi alanlarının birbirinden ayrılmaması, kendi içinde bütünleşmesi:
        if san_a >= 0.35 and san_b >= 0.35:
            factor *= 0.38
        elif (san_a >= 0.55 and san_b < 0.10) or (san_b >= 0.55 and san_a < 0.10):
            factor *= 1.65

        # Mezarlık adalarının konut/ticaret ile karışmaması:
        mez_a = sum(cell_mez[i] for i in mem_a) / len(mem_a)
        mez_b = sum(cell_mez[i] for i in mem_b) / len(mem_b)
        if mez_a >= 0.35 and mez_b >= 0.35:
            factor *= 0.30
        elif (mez_a >= 0.40 and mez_b < 0.05) or (mez_b >= 0.40 and mez_a < 0.05):
            factor *= 2.20

        # Boş arazisi çok olan (yeni plan çizilecek) alanlar ile dolu (yapılaşmış) alanların net ayrılması:
        if w_bos >= 1.4 or preset_mode in ("integrated_synthesis", "vacant_plan"):
            bos_a = sum(cell_bos[i] for i in mem_a) / len(mem_a)
            bos_b = sum(cell_bos[i] for i in mem_b) / len(mem_b)
            if abs(bos_a - bos_b) >= 0.42:
                factor *= (1.0 + 0.45 * min(2.5, w_bos))
            elif (bos_a >= 0.72 and bos_b >= 0.72) or (bos_a <= 0.28 and bos_b <= 0.28):
                factor *= 0.78

        # Donatı erişimi benzer olanların (~500m vs ~1000m) kendi içinde gruplanması:
        if have["donati_erisim"] and (w_erisim >= 1.4 or preset_mode in ("integrated_synthesis", "access_school")):
            da_list = [cell_don_m[i] for i in mem_a if cell_don_m[i] is not None]
            db_list = [cell_don_m[i] for i in mem_b if cell_don_m[i] is not None]
            if da_list and db_list:
                da = sum(da_list) / len(da_list)
                db = sum(db_list) / len(db_list)
                # Biri <=500m yürüme mesafesinde, diğeri >850m uzaklıktaysa birleşmeyi zorlaştır
                if (da <= 500.0 and db >= 850.0) or (db <= 500.0 and da >= 850.0):
                    factor *= 1.55
        return factor

    tick(progress, 70)
    node_w = [math.sqrt(a) for a in areas]
    cap = sum(areas) / K * P["cap_mult"]
    labels = alg.ward_merge(vecs, node_w, areas, adj, K, area_cap=cap, affinity_fn=synthesis_affinity)
    if filter_medians:
        labels = refine_zone_compactness(cells, adj, labels, S)
    K = len(set(labels))
    members = defaultdict(list)
    for i, lbl in enumerate(labels):
        members[lbl].append(i)

    tick(progress, 82, "5/7 Alt bölge kimlikleri ve Z-skoru tabanlı dinamik sınır ayrım gerekçeleri hesaplanıyor...", log)
    zones = []
    for lbl in sorted(members):
        ids = members[lbl]
        geom = strip_polygon_holes(QgsGeometry.unaryUnion([cells[i] for i in ids]))
        geom.convertToMultiType()
        zones.append(zone_stats(lbl, ids, geom, S, areas, ext_kinds, allcols=allcols))
    if len(zones) >= 2:
        prune_zone_road_tails(zones, filter_medians=filter_medians)
    if res_block_pops:
        assign_zone_populations_from_blocks(zones, res_block_pops)
    maxd = 1.0
    for z in zones:
        c = z["geom"].centroid().asPoint()
        z["cx"], z["cy"] = c.x(), c.y()
        z["dist_c"] = math.hypot(c.x() - center[0], c.y() - center[1])
        maxd = max(maxd, z["dist_c"])
    for z in zones:
        z["merkez"] = max(0.0, 1.0 - z["dist_c"] / maxd)
        if z["dist_c"] < 0.06 * maxd or z["geom"].contains(QgsGeometry.fromPointXY(QgsPointXY(*center))):
            z["dir"] = None
        else:
            dx, dy = z["cx"] - center[0], z["cy"] - center[1]
            L = math.hypot(dx, dy)
            z["dir"] = (dx / L, dy / L)
        if z["dir"]:
            ang = math.degrees(math.atan2(z["dir"][1], z["dir"][0])) % 360
            z["dir_name"] = DIR_NAMES[int(((ang + 22.5) % 360) // 45)]
        else:
            z["dir_name"] = "Merkez"
    match_feats(zones, have, ext_kinds)

    mode = P.get("mode", "advanced")
    prefix = "M" if mode == "advanced" else "A"
    target_rows = alg.ADVANCED_PROFILES if mode == "advanced" else alg.EXCEL_ROWS

    if P["use_excel"] and len(zones) <= len(target_rows):
        res_match = alg.match_zones_to_rows([z["m"] for z in zones], mode=mode)
        for z, (j, score) in zip(zones, res_match):
            row = target_rows[j]
            z["_matched_row_idx"] = j
            z["karakter"], z["excel_gerekce"] = row[1], row[2]
            z["uyum"] = score
            if len(row) >= 8:
                z["baskin_kombinasyon"] = row[5]
                z["mudahale_karari"] = row[6]
                z["plan_karsiligi"] = row[7]
            else:
                z["baskin_kombinasyon"] = None
                z["mudahale_karari"] = None
                z["plan_karsiligi"] = None
        # Kullanıcı K=25 istediyse M1..M25 (veya A1..A25) şeklinde HİÇ NUMARA ATLAMADAN ardışık numaralandır
        zones.sort(key=lambda z: (z.get("_matched_row_idx", 999), -round(z["cy"] / 200.0), z["cx"]))
        for seq_idx, z in enumerate(zones, 1):
            z["kod"] = f"{prefix}{seq_idx}"
    else:
        band = max(1.0, (study.boundingBox().height()) / 6.0)
        zones.sort(key=lambda z: (-round(z["cy"] / band), z["cx"]))
        for i, z in enumerate(zones, 1):
            z["kod"], z["karakter"], z["excel_gerekce"], z["uyum"] = f"{prefix}{i}", auto_label(z), "", None
            if mode == "advanced":
                z["baskin_kombinasyon"] = f"Baskın Doku: {z['karakter']} ({z.get('yd_dom', '')})"
                z["mudahale_karari"] = "Mevcut morfolojik dokunun korunması ve planlı donatı takviyesi"
                z["plan_karsiligi"] = "İlgili imar planı kullanım kararı ve yapılaşma nizamı"
            else:
                z["baskin_kombinasyon"] = None
                z["mudahale_karari"] = None
                z["plan_karsiligi"] = None

    # KURAL 1 (Post-Check): Yalnızca içinde HİÇ konut/karma adası bulunmayan salt Sanayi veya salt Tarım bölgelerinde nüfusu 0 yap!
    # İçinde konut veya karma kullanım adası bulunan hiçbir bölgenin (ör. M12) tahmini nüfusu sıfırlanmaz.
    for z in zones:
        if z.get("konut_ada_sayisi", 0) > 0 or z["lu"].get("konut", 0.0) > 0.0:
            continue
        p = z.get("pay") or {}
        if (
            "sanayi" in alg.norm_tr(z.get("karakter", ""))
            or "tarim" in alg.norm_tr(z.get("karakter", ""))
            or p.get("sanayi", 0.0) >= 0.45
            or p.get("tarim", 0.0) >= 0.75
            or (p.get("konut", 0.0) <= 0.01 and p.get("ticaret", 0.0) <= 0.03)
        ):
            z["nufus"] = 0.0

    # Alt bölgeler arası komşuluk grafını çıkar
    zone_adj = build_zone_neighbors(zones, adj, labels)

    for idx_z, z in enumerate(zones):
        z["olculen"] = describe_concise(z)
        z["ayrim_nedeni"] = build_contrast_explanation(z, zones, zone_adj.get(idx_z, []), allcols=allcols)
        z["gerekce"] = build_concise_rationale(z, z["ayrim_nedeni"])
        z["kisa_ozet"] = describe_quick_summary(z)
        z["kisa_ayrim_nedeni"] = build_quick_contrast(z, zones, zone_adj.get(idx_z, []), allcols=allcols)
        z["kisa_gerekce"] = build_quick_rationale(z, z["kisa_ayrim_nedeni"])

    zones.sort(key=lambda z: int(re.sub(r"\D", "", z["kod"]) or 0))

    return {"zones": zones, "cells": cells, "labels": labels, "S": S, "have": have, "center": center,
            "study": study, "work_crs": work_crs, "mode": mode}


def _enforce_connected_zone_labels(cells, adj, labels, shared_len):
    """Her alt bölgenin graf üzerinde tek parça (bağlantılı) olmasını sağlar; kopuk adacıkları komşu bölgeye katar."""
    labels = list(labels)
    for _round in range(3):
        changed_any = False
        by_lbl_nodes = defaultdict(list)
        for idx_c, lbl in enumerate(labels):
            by_lbl_nodes[lbl].append(idx_c)

        for lbl, nodes in list(by_lbl_nodes.items()):
            if len(nodes) <= 1:
                continue
            node_set = set(nodes)
            visited = set()
            comps = []
            for start in nodes:
                if start in visited:
                    continue
                comp = []
                q = [start]
                visited.add(start)
                while q:
                    curr = q.pop()
                    comp.append(curr)
                    for nb in adj.get(curr, ()):
                        if nb in node_set and nb not in visited:
                            visited.add(nb)
                            q.append(nb)
                comps.append(comp)
            if len(comps) <= 1:
                continue
            comps.sort(key=lambda c_list: sum(cells[c].area() for c_list_item in [c_list] for c in c_list_item), reverse=True)
            for small_comp in comps[1:]:
                small_set = set(small_comp)
                nb_scores = defaultdict(float)
                for u in small_comp:
                    for v in adj.get(u, ()):
                        if v not in small_set and labels[v] != lbl:
                            nb_scores[labels[v]] += max(shared_len.get((u, v), 0.0), 1.0)
                if nb_scores:
                    target_lbl = max(nb_scores.items(), key=lambda kv: kv[1])[0]
                    for u in small_comp:
                        labels[u] = target_lbl
                    changed_any = True
        if not changed_any:
            break
    return labels


def refine_zone_compactness(cells, adj, labels, S):
    """
    İnce uzun yol şeritlerinin, kopuk adacıkların veya dar boğazla (throat) bağlı hücrelerin bir bölgeden çıkıntı/kuyruk
    veya iç siyah çizgi oluşturmasını önler; komşu bölgeyle çok daha uzun sınır paylaşan hücreleri kompakt biçimde yeniden atar.
    """
    n = len(cells)
    if n <= 3:
        return labels
    labels = list(labels)
    perims = [max(1.0, g.length()) for g in cells]
    areas = [max(1.0, g.area()) for g in cells]
    pps = [(4.0 * math.pi * areas[i]) / (perims[i] * perims[i]) for i in range(n)]
    thicks = [(2.0 * areas[i]) / perims[i] for i in range(n)]

    # Önceden komşu hücreler arası ortak sınır uzunluklarını hesapla
    shared_len = defaultdict(float)
    for i, nbs in adj.items():
        for j in nbs:
            if j > i:
                inter = cells[i].intersection(cells[j])
                slen = inter.length() if inter and not inter.isEmpty() else 0.0
                shared_len[(i, j)] = slen
                shared_len[(j, i)] = slen

    labels = _enforce_connected_zone_labels(cells, adj, labels, shared_len)

    for _pass in range(4):
        changed = False
        lbl_counts = Counter(labels)
        for i in range(n):
            cur = labels[i]
            if lbl_counts[cur] <= 1:
                continue
            by_lbl = defaultdict(float)
            for j in adj.get(i, ()):
                by_lbl[labels[j]] += shared_len.get((i, j), 0.0)
            same_l = by_lbl.get(cur, 0.0)
            other_items = [(lbl, lval) for lbl, lval in by_lbl.items() if lbl != cur and lval > 0.5]
            if not other_items:
                continue
            best_lbl, best_l = max(other_items, key=lambda kv: kv[1])

            is_strip_or_empty = (pps[i] < 0.22 or thicks[i] < 26.0 or S[i]["n"] == 0)
            is_disconnected = (same_l < 0.5 and best_l > 2.0)
            is_narrow_throat = (is_strip_or_empty and (same_l < 38.0 or same_l < 0.16 * perims[i]) and best_l > max(same_l * 1.6, 18.0))
            is_surrounded = (best_l > 0.62 * perims[i] and same_l < 0.18 * perims[i])

            if is_disconnected or is_narrow_throat or is_surrounded:
                labels[i] = best_lbl
                lbl_counts[cur] -= 1
                lbl_counts[best_lbl] += 1
                changed = True
        if not changed:
            break

    labels = _enforce_connected_zone_labels(cells, adj, labels, shared_len)
    return labels


def _reassign_minor_disconnected_parts(zones):
    """Bir alt bölgenin ana poligonundan kopuk küçük poligon parçalarını (başka bölgenin içinde siyah çizgi oluşturan adacıkları) komşusuna katar."""
    if len(zones) < 2:
        return
    for i, z in enumerate(zones):
        parts = [strip_polygon_holes(p) for p in poly_parts(z["geom"]) if p and not p.isEmpty() and p.area() > 1.0]
        if len(parts) <= 1:
            if parts:
                g0 = parts[0]
                g0.convertToMultiType()
                z["geom"] = g0
                z["area"] = g0.area()
            continue
        parts.sort(key=lambda p: p.area(), reverse=True)
        main_part = parts[0]
        kept = [main_part]
        for extra in parts[1:]:
            best_j = -1
            best_sh = -1.0
            for j, oz in enumerate(zones):
                if j == i:
                    continue
                if not oz["geom"].boundingBox().intersects(extra.boundingBox()):
                    continue
                inter = extra.intersection(oz["geom"])
                sh = inter.length() if inter and not inter.isEmpty() else 0.0
                if sh > best_sh:
                    best_sh = sh
                    best_j = j
            if best_j >= 0 and best_sh > 0.5:
                ug = strip_polygon_holes(QgsGeometry.unaryUnion([zones[best_j]["geom"], extra]))
                if ug and not ug.isEmpty():
                    ug.convertToMultiType()
                    zones[best_j]["geom"] = ug
                    zones[best_j]["area"] = ug.area()
            elif extra.area() >= 0.35 * main_part.area():
                kept.append(extra)
        new_g = strip_polygon_holes(QgsGeometry.unaryUnion(kept) if len(kept) > 1 else kept[0])
        if new_g and not new_g.isEmpty():
            new_g.convertToMultiType()
            z["geom"] = new_g
            z["area"] = new_g.area()


def _heal_inward_slits_and_holes(zones, close_m=6.5):
    """
    Bölge poligonlarının içine doğru saplanan ince siyah yarıkları (slit/crack) ve iç boşlukları (interior holes)
    morfolojik kapama ile tespit edip tamamen doldurur; böylece bölge içlerinde alakasız siyah çizgiler oluşmaz.
    """
    for i, z in enumerate(zones):
        g = strip_polygon_holes(z["geom"])
        if g is None or g.isEmpty():
            continue
        closed = g.buffer(close_m, 8).buffer(-close_m, 8)
        if closed is not None and not closed.isEmpty():
            closed = strip_polygon_holes(closed)
            diff = closed.difference(g)
            if diff is not None and not diff.isEmpty():
                slits = []
                for sp in poly_parts(diff):
                    sa = sp.area()
                    slen = sp.length()
                    if sa <= 0.1 or slen <= 0.0:
                        continue
                    s_thick = (2.0 * sa) / slen
                    if s_thick < (close_m * 2.1):
                        slits.append(sp)
                if slits:
                    slit_u = QgsGeometry.unaryUnion(slits)
                    g = strip_polygon_holes(QgsGeometry.unaryUnion([g, slit_u]))
                    # Eğer bu yarık komşu bir bölgenin ince dikeni idiyse komşudan düş
                    for j, oz in enumerate(zones):
                        if j == i:
                            continue
                        if oz["geom"].boundingBox().intersects(slit_u.boundingBox()):
                            odiff = oz["geom"].difference(slit_u)
                            if odiff and not odiff.isEmpty() and odiff.area() > 0.5 * oz["geom"].area():
                                odiff = strip_polygon_holes(odiff)
                                odiff.convertToMultiType()
                                oz["geom"] = odiff
                                oz["area"] = odiff.area()
        if not g.isGeosValid():
            g = g.makeValid()
        g = strip_polygon_holes(g)
        g.convertToMultiType()
        z["geom"] = g
        z["area"] = g.area()


def prune_zone_road_tails(zones, filter_medians=True):
    """
    Alt bölge poligonlarında:
    1) İç delikleri (interior holes) ve kopuk adacıkları temizler,
    2) Dışarıya doğru uzanan ince uzun yol koridoru kuyruklarını (ör. M25) morfolojik açma ile budayıp komşu bölgeye katar,
    3) Bölge içine saplanan ince siyah yarıkları (slit/crack) kapatarak pürüzsüz, iç çizgisiz poligonlar üretir.
    """
    for z in zones:
        g = strip_polygon_holes(z["geom"])
        g.convertToMultiType()
        z["geom"] = g
        z["area"] = g.area()

    _reassign_minor_disconnected_parts(zones)

    if filter_medians:
        for i, z in enumerate(zones):
            g = strip_polygon_holes(z["geom"])
            z_area = g.area()
            if z_area < 20000.0:
                continue
            opened = g.buffer(-13.0, 8).buffer(14.5, 8)
            if opened is None or opened.isEmpty():
                continue
            diff = g.difference(opened)
            if diff is None or diff.isEmpty():
                continue
            tails_to_remove = []
            for part in poly_parts(diff):
                pa = part.area()
                plen = part.length()
                if pa < 25.0 or plen <= 0.0 or pa > 0.18 * z_area:
                    continue
                p_thick = (2.0 * pa) / plen
                p_pp = (4.0 * math.pi * pa) / (plen * plen)
                if p_thick < 26.0 and p_pp < 0.22:
                    best_j = -1
                    best_sh = 0.0
                    for j, oz in enumerate(zones):
                        if j == i:
                            continue
                        if not oz["geom"].boundingBox().intersects(part.boundingBox()):
                            continue
                        inter = part.intersection(oz["geom"])
                        sh = inter.length() if inter and not inter.isEmpty() else 0.0
                        if sh > best_sh:
                            best_sh = sh
                            best_j = j
                    if best_j >= 0 and best_sh > 5.0:
                        tails_to_remove.append((part, best_j))
            if tails_to_remove:
                rem_union = QgsGeometry.unaryUnion([t[0] for t in tails_to_remove])
                new_g = g.difference(rem_union)
                if new_g and not new_g.isEmpty() and new_g.area() > 0.5 * z_area:
                    if not new_g.isGeosValid():
                        new_g = new_g.makeValid()
                    new_g = strip_polygon_holes(new_g)
                    new_g.convertToMultiType()
                    z["geom"] = new_g
                    z["area"] = new_g.area()
                    for part, best_j in tails_to_remove:
                        ug = QgsGeometry.unaryUnion([zones[best_j]["geom"], part])
                        if ug and not ug.isEmpty():
                            if not ug.isGeosValid():
                                ug = ug.makeValid()
                            ug = strip_polygon_holes(ug)
                            ug.convertToMultiType()
                            zones[best_j]["geom"] = ug
                            zones[best_j]["area"] = ug.area()

    _heal_inward_slits_and_holes(zones, close_m=6.5)
    _reassign_minor_disconnected_parts(zones)
    for z in zones:
        g = strip_polygon_holes(z["geom"])
        g.convertToMultiType()
        z["geom"] = g
        z["area"] = g.area()


def build_zone_neighbors(zones, cell_adj, cell_labels):
    l_to_zidx = {z["l"]: idx for idx, z in enumerate(zones)}
    z_adj = defaultdict(set)
    for ci, nbs in cell_adj.items():
        zi = l_to_zidx.get(cell_labels[ci])
        if zi is None:
            continue
        for cj in nbs:
            zj = l_to_zidx.get(cell_labels[cj])
            if zj is not None and zj != zi:
                z_adj[zi].add(zj)
                z_adj[zj].add(zi)
    return z_adj


def format_z_feature_diff(col_key, z, nb, nb_kod, include_codes=True):
    """
    KURAL 5: Z-skoru matrisindeki herhangi bir aktif değişken için iki komşu bölge (z ve nb)
    arasındaki gerçek fiziksel/oransal farkı okunabilir metne dönüştürür.
    """
    short_key = col_key.split(":", 1)[-1] if ":" in col_key else col_key
    p_z = z.get("pay") or {}
    p_nb = nb.get("pay") or {}
    e_z = z.get("ext") or {}
    e_nb = nb.get("ext") or {}

    if short_key == "taks":
        return f"TAKS yoğunluk farkı (%{z['taks']*100:.1f} vs {nb_kod}'de %{nb['taks']*100:.1f})"
    if short_key == "yog":
        return f"yapı yoğunluğu farkı ({z['ndens']:.1f} bina/ha vs {nb_kod}'de {nb['ndens']:.1f} bina/ha)"
    if short_key == "tane":
        b1 = (z["barea"] / z["n"]) if z["n"] > 0 else 0.0
        b2 = (nb["barea"] / nb["n"]) if nb["n"] > 0 else 0.0
        return f"ortalama yapı taban büyüklüğü farkı ({b1:.0f} m² vs {nb_kod}'de {b2:.0f} m²)"
    if short_key == "kat":
        k1 = z["kat"] if z["kat"] is not None else 0.0
        k2 = nb["kat"] if nb["kat"] is not None else 0.0
        return f"alan ağırlıklı kat yüksekliği farkı ({k1:.1f} kat vs {nb_kod}'de {k2:.1f} kat)"
    if short_key == "bit":
        b1 = (z["bitisik"] or 0.0) * 100.0
        b2 = (nb["bitisik"] or 0.0) * 100.0
        return f"yapı nizamı / bitişik nizam farkı ('{z.get('yd_dom')}' [%{b1:.0f}] vs {nb_kod}'de '{nb.get('yd_dom')}' [%{b2:.0f}])"
    if short_key == "kotu_yapi":
        ky1 = (z.get("kotu_pay") or 0.0) * 100.0
        ky2 = (nb.get("kotu_pay") or 0.0) * 100.0
        tag = " [yapi:kotu_yapi]" if include_codes else ""
        return f"kötü durumdaki yapı oranı{tag} farkı (%{ky1:.1f} vs {nb_kod}'de %{ky2:.1f})"
    if short_key == "nufus_yog":
        d1 = z["nufus"] / (z["area"] / 10000.0) if z["area"] > 0 else 0.0
        d2 = nb["nufus"] / (nb["area"] / 10000.0) if nb["area"] > 0 else 0.0
        return f"nüfus yoğunluğu farkı ({d1:.0f} kişi/ha vs {nb_kod}'de {d2:.0f} kişi/ha)"
    if short_key == "yol_gen":
        y1 = z.get("yg") or 0.0
        y2 = nb.get("yg") or 0.0
        return f"ortalama yol genişliği farkı ({y1:.1f}m vs {nb_kod}'de {y2:.1f}m)"
    if short_key.startswith("rkap_"):
        return f"baskın yol kaplaması farkı ('{z.get('rkap_dom') or 'Belirsiz'}' vs {nb_kod}'de '{nb.get('rkap_dom') or 'Belirsiz'}')"
    if short_key.startswith("rtur_"):
        return f"yol kademelenmesi farkı ('{z.get('rtur_dom') or 'Standart'}' vs {nb_kod}'de '{nb.get('rtur_dom') or 'Standart'}')"
    if short_key == "egim":
        eg1 = z.get("egim") or 0.0
        eg2 = nb.get("egim") or 0.0
        return f"topoğrafik eğim farkı (%{eg1:.1f} vs {nb_kod}'de %{eg2:.1f})"
    if short_key in ("bos_arazi_orani", "bos"):
        b1 = (z.get("bos_arazi_orani") if z.get("bos_arazi_orani") is not None else z.get("bos", 0.0)) * 100.0
        b2 = (nb.get("bos_arazi_orani") if nb.get("bos_arazi_orani") is not None else nb.get("bos", 0.0)) * 100.0
        return f"boş arazi / yeni plan potansiyeli oranı farkı (%{b1:.0f} vs {nb_kod}'de %{b2:.0f})"
    if short_key == "doluluk_orani":
        d1 = (1.0 - (z.get("bos_arazi_orani") if z.get("bos_arazi_orani") is not None else z.get("bos", 0.0))) * 100.0
        d2 = (1.0 - (nb.get("bos_arazi_orani") if nb.get("bos_arazi_orani") is not None else nb.get("bos", 0.0))) * 100.0
        return f"yapılaşmış doluluk oranı farkı (%{d1:.0f} vs {nb_kod}'de %{d2:.0f})"
    if short_key in ("donati_erisim_m", "erisim_500m_bandi"):
        dm1 = z.get("donati_mesafe_m") or 0.0
        dm2 = nb.get("donati_mesafe_m") or 0.0
        return f"donatı/okul erişim mesafesi farkı (~{dm1:.0f}m vs {nb_kod}'de ~{dm2:.0f}m)"
    if short_key == "lu_konut_dusuk_seyrek":
        s1 = (z.get("sub_lu_pay", {}).get("konut_dusuk_seyrek", 0.0)) * 100.0
        s2 = (nb.get("sub_lu_pay", {}).get("konut_dusuk_seyrek", 0.0)) * 100.0
        return f"düşük/seyrek konut dokusu oranı farkı (%{s1:.0f} vs {nb_kod}'de %{s2:.0f})"
    if short_key == "lu_konut_orta_yuksek":
        s1 = (z.get("sub_lu_pay", {}).get("konut_orta_yuksek", 0.0)) * 100.0
        s2 = (nb.get("sub_lu_pay", {}).get("konut_orta_yuksek", 0.0)) * 100.0
        return f"orta/yüksek yoğunluklu konut oranı farkı (%{s1:.0f} vs {nb_kod}'de %{s2:.0f})"
    if short_key == "lu_mezarlik":
        s1 = (z.get("sub_lu_pay", {}).get("mezarlik", 0.0)) * 100.0
        s2 = (nb.get("sub_lu_pay", {}).get("mezarlik", 0.0)) * 100.0
        return f"mezarlık ve yeşil tampon oranı farkı (%{s1:.0f} vs {nb_kod}'de %{s2:.0f})"
    if short_key == "sanayi_butunluk":
        v1 = p_z.get("sanayi", 0.0) * 100.0
        v2 = p_nb.get("sanayi", 0.0) * 100.0
        return f"sanayi kümesi bütünlüğü farkı (%{v1:.0f} vs {nb_kod}'de %{v2:.0f})"
    if short_key == "sanayi_konut_gecisi":
        return f"sanayi-konut komşuluk geçişi farkı ({z['kod']} vs {nb_kod})"
    if short_key == "sanayi_tarim_gecisi":
        return f"sanayi-tarım komşuluk geçişi farkı ({z['kod']} vs {nb_kod})"
    if short_key.startswith("lu_"):
        cls = short_key.replace("lu_", "")
        v1 = p_z.get(cls, 0.0) * 100.0
        v2 = p_nb.get(cls, 0.0) * 100.0
        return f"{cls} kullanım oranı farkı (%{v1:.0f} vs {nb_kod}'de %{v2:.0f})"
    if short_key == "sit2":
        v1 = (e_z.get("sit2") or 0.0) * 100.0
        v2 = (e_nb.get("sit2") or 0.0) * 100.0
        tag = " [sit2]" if include_codes else ""
        return f"tescilli alan oranı{tag} farkı (%{v1:.1f} vs {nb_kod}'de %{v2:.1f})"
    if short_key == "sit3":
        v1 = (e_z.get("sit3") or 0.0) * 100.0
        v2 = (e_nb.get("sit3") or 0.0) * 100.0
        tag = " [sit3]" if include_codes else ""
        return f"afet risk / kentsel dönüşüm sınırı{tag} farkı (%{v1:.1f} vs {nb_kod}'de %{v2:.1f})"
    if short_key == "sit":
        v1 = (e_z.get("sit") if e_z.get("sit") is not None else p_z.get("sit", 0.0)) * 100.0
        v2 = (e_nb.get("sit") if e_nb.get("sit") is not None else p_nb.get("sit", 0.0)) * 100.0
        return f"sit alanı oranı farkı (%{v1:.1f} vs {nb_kod}'de %{v2:.1f})"
    if short_key == "risk":
        v1 = (e_z.get("risk") or 0.0) * 100.0
        v2 = (e_nb.get("risk") or 0.0) * 100.0
        return f"afet/taşkın risk alanı farkı (%{v1:.1f} vs {nb_kod}'de %{v2:.1f})"
    if short_key == "dere":
        v1 = e_z.get("dere") or 0.0
        v2 = e_nb.get("dere") or 0.0
        return f"dereye uzaklık farkı ({v1:.0f}m vs {nb_kod}'de {v2:.0f}m)"
    if short_key == "fay":
        v1 = e_z.get("fay") or 0.0
        v2 = e_nb.get("fay") or 0.0
        return f"diri fay hattına uzaklık farkı ({v1:.0f}m vs {nb_kod}'de {v2:.0f}m)"
    if short_key == "donati":
        v1 = int(e_z.get("donati") or 0)
        v2 = int(e_nb.get("donati") or 0)
        return f"sosyal/teknik donatı sayısı farkı ({v1} adet vs {nb_kod}'de {v2} adet)"

    # Diğer ek katmanlar
    if short_key in e_z or short_key in e_nb:
        v1 = e_z.get(short_key) or 0.0
        v2 = e_nb.get(short_key) or 0.0
        return f"{short_key} parametresi farkı ({v1:.1f} vs {nb_kod}'de {v2:.1f})"

    return f"{col_key} Z-skoru farkı"


def _select_distinct_neighbor_diffs(z, all_zones, nb_indices, include_codes=True):
    """Komşu bölgelerle en yüksek farkı oluşturan birbirinden FARKLI 3 değişken ailesini seçer."""
    z_means = z.get("z_means") or {}
    candidate_diffs = []
    active_keys = [k for k in (z_means.keys()) if not k.startswith("geo:")]

    for nb_i in nb_indices:
        nb = all_zones[nb_i]
        nb_kod = nb["kod"]
        nb_z_means = nb.get("z_means") or {}

        for col_key in active_keys:
            val_a = z_means.get(col_key, 0.0)
            val_b = nb_z_means.get(col_key, 0.0)
            abs_z_diff = abs(val_a - val_b)
            if abs_z_diff <= 0.05:
                continue
            short_k = col_key.split(":", 1)[-1] if ":" in col_key else col_key

            # Eğer rkap veya rtur baskın değerleri iki bölgede birebir aynıysa sahte fark olarak ekleme
            if short_k.startswith("rkap_") and (z.get("rkap_dom") or "") == (nb.get("rkap_dom") or ""):
                continue
            if short_k.startswith("rtur_") and (z.get("rtur_dom") or "") == (nb.get("rtur_dom") or ""):
                continue

            # Değişken ailesi anahtarı (Aynı yol kaplaması veya yol kademesi iki kez seçilmesin)
            if short_k.startswith("rkap_") or short_k.startswith("rtur_"):
                if (z.get("rkap_dom") or "") == (z.get("rtur_dom") or ""):
                    fam_key = "road_qual_family"
                else:
                    fam_key = "rkap_family" if short_k.startswith("rkap_") else "rtur_family"
            else:
                fam_key = short_k

            desc_str = format_z_feature_diff(col_key, z, nb, nb_kod, include_codes=include_codes)
            candidate_diffs.append((abs_z_diff, fam_key, nb_kod, desc_str))

    candidate_diffs.sort(key=lambda item: -item[0])

    selected_items = []
    seen_fams = set()
    seen_prefixes = set()
    for z_diff, fam_key, nb_kod, desc_str in candidate_diffs:
        prefix = desc_str.split("(", 1)[0].strip()
        if fam_key in seen_fams or prefix in seen_prefixes:
            continue
        seen_fams.add(fam_key)
        seen_prefixes.add(prefix)
        selected_items.append((z_diff, nb_kod, desc_str))
        if len(selected_items) == 3:
            break

    return selected_items


def build_contrast_explanation(z, all_zones, nb_indices, allcols=None):
    """
    KURAL 5 DÜZELTMESİ ("Neden Birleşti / Ayrıldı" Explainability Çeşitlendirmesi):
    - Z-Skoru matrisinde (allcols) bu bölge ile komşu bölgeler arasında EN YÜKSEK VARYANS / MUTLAK Z-SKORU FARKI
      (|Z_a - Z_b|) oluşturan ilk 3 aktif değişkeni dinamik olarak hesaplar ve cümleye bu 3 değişkeni yazdırır.
    """
    if not nb_indices:
        return "Çalışma alanı sınırında kendi içinde bütünleşik bağımsız doku."

    selected_items = _select_distinct_neighbor_diffs(z, all_zones, nb_indices, include_codes=True)
    selected_texts = [f"{desc_str} [ΔZ={z_diff:.2f}]" for z_diff, _, desc_str in selected_items]

    nb_list_str = ", ".join(sorted(all_zones[i]["kod"] for i in nb_indices))
    if not selected_texts:
        return f"Komşu bölgelerden ({nb_list_str}) ana ulaşım aksı ve mekânsal kompaktlık eşiği ile ayrılmıştır."

    return (
        f"Komşu bölgelerden ({nb_list_str}) Z-skoru matrisinde en yüksek farkı oluşturan ilk 3 aktif değişkene göre ayrılmıştır: "
        + "1) " + selected_texts[0]
        + (f"; 2) {selected_texts[1]}" if len(selected_texts) > 1 else "")
        + (f"; 3) {selected_texts[2]}" if len(selected_texts) > 2 else "")
        + "."
    )


def describe_quick_summary(z):
    """
    HIZLI VE SADE ÖZET (Tek Bakışta Okuma):
    Kod adları ([yapi:kotu_yapi], [sit2], [sit3], [ΔZ]) olmadan doğrudan plancının hızlıca kontrol edeceği
    anahtar metrikleri verir: % Arazi Kullanımı | Faya Uzaklık | Dereye Uzaklık | Eğim | Donatı Sayısı | TAKS | Kat & Nizam | Nüfus.
    """
    parts = []
    p = z.get("pay")
    lu_names = {
        "konut": "Konut", "ticaret": "Ticaret", "sanayi": "Sanayi",
        "tarim": "Tarım", "donati": "Donatı", "sit": "Sit"
    }
    if p:
        top = [(lu_names.get(k, k.capitalize()), int(round(v * 100)))
               for k, v in sorted(p.items(), key=lambda kv: -kv[1]) if v >= 0.05]
        if top:
            parts.append(" + ".join(f"%{val} {cls}" for cls, val in top[:3]))
        else:
            best_k, best_v = max(p.items(), key=lambda kv: kv[1])
            parts.append(f"%{max(1, int(round(best_v * 100)))} {lu_names.get(best_k, best_k.capitalize())}")
    else:
        bos_pct = int(round(z.get("bos", 1.0) * 100))
        parts.append(f"%{bos_pct} Açık/Tarım Alanı")
    e = z.get("ext") or {}
    if e.get("fay") is not None:
        parts.append(f"Faya {e['fay']:.0f}m")
    if e.get("dere") is not None:
        parts.append(f"Dereye {e['dere']:.0f}m")
    if z.get("egim") is not None:
        parts.append(f"Eğim %{z['egim']:.1f}")
    if z.get("rakim") is not None:
        parts.append(f"Rakım {z['rakim']:.0f}m")
    if e.get("donati") is not None:
        parts.append(f"Donatı: {int(e['donati'])} adet")
    if z.get("donati_mesafe_m") is not None:
        parts.append(f"Donatı Erişimi ~{z['donati_mesafe_m']:.0f}m")
    bos_arazi_pct = int(round((z.get("bos_arazi_orani") if z.get("bos_arazi_orani") is not None else z.get("bos", 0.0)) * 100))
    parts.append(f"Boş Arazi %{bos_arazi_pct}")
    parts.append(f"TAKS %{z['taks'] * 100:.1f}")
    if z.get("kat") is not None and z["kat"] > 0:
        nizam_str = f" ({z['yd_dom']})" if z.get("yd_dom") else ""
        parts.append(f"Ort. {z['kat']:.1f} Kat{nizam_str}")
    elif z.get("yd_dom"):
        parts.append(f"{z['yd_dom']}")
    parts.append(f"Nüfus: {int(round(z['nufus']))} kişi")

    kotu_pct, sit2_pct, sit3_pct = get_extra_Sit_params(z)
    if sit2_pct >= 1.0:
        parts.append(f"Sit Alanı %{sit2_pct:.0f}")
    if sit3_pct >= 1.0:
        parts.append(f"Risk/Dönüşüm %{sit3_pct:.0f}")
    if kotu_pct >= 5.0:
        parts.append(f"Kötü Yapı %{kotu_pct:.0f}")
    return " | ".join(parts)


def build_quick_contrast(z, all_zones, nb_indices, allcols=None):
    """
    HIZLI VE SADE KOMŞU AYRIM NEDENİ:
    Z-skoru ve değişken kodu karmaşası olmadan komşu bölgelerden hangi 3 somut fiziksel farkla ayrıldığını özetler.
    """
    if not nb_indices:
        return "Çalışma alanı sınırında bağımsız doku."
    selected_items = _select_distinct_neighbor_diffs(z, all_zones, nb_indices, include_codes=False)
    nb_list_str = ", ".join(sorted(all_zones[i]["kod"] for i in nb_indices))
    if not selected_items:
        return f"Komşulardan ({nb_list_str}) ana yol aksı ve ada bütünlüğü ile ayrılır."
    plain_texts = [desc_str for _, _, desc_str in selected_items]
    return (
        f"Komşulardan ({nb_list_str}) başlıca; "
        + "1) " + plain_texts[0]
        + (f", 2) {plain_texts[1]}" if len(plain_texts) > 1 else "")
        + (f", 3) {plain_texts[2]}" if len(plain_texts) > 2 else "")
        + " ile ayrılır."
    )


def build_quick_rationale(z, kisa_ayrim_nedeni=""):
    """
    HIZLI OKUMA GEREKÇESİ (Kisa_Birlestirme_ve_Ayrim_Ozeti):
    Plancının birkaç saniyede okuyup geçebileceği sadeleştirilmiş özet ve ayrım gerekçesi (gereksiz tekrar içermez).
    """
    base = z.get("excel_gerekce") or f"{z.get('dir_name', 'Merkez')} kesimde {z.get('karakter', 'kentsel doku').lower()}."
    if kisa_ayrim_nedeni:
        return f"{base} {kisa_ayrim_nedeni}"
    return base


def zone_stats(zone_label, ids, geom, S, areas, ext_kinds, allcols=None):
    """
    KURAL 2, 3, 4 & 5:
    - Kat sayısı alan ağırlıklı ortalama (z['kat_w'] / z['kat_a']) olarak hesaplanır; yapısız/tarım alanlarda
      tekil binaların ortalamayı saptırması engellenir.
    - TAKS < %5 veya Tarım/Açık Alan oranı > %70 ise baskın yapı nizamı (z['yd_dom']) kesinlikle 'Bitişik Nizam'
      atanmaz; 'Yapısız / Açık Alan' veya 'Seyrek Kırsal Doku' olarak etiketlenir.
    - Her alt bölgenin Z-skoru matrisindeki alan ağırlıklı ortalama Z-vektörü (z['z_means']) kaydedilir.
    """
    z = {"l": zone_label, "ids": ids, "geom": geom, "area": sum(areas[i] for i in ids), "ncell": len(ids)}
    for k in ("n", "barea", "kat_w", "kat_a", "lu_a", "bit", "bit_a", "kotu", "kotu_a", "nufus", "yg_w", "yg_l"):
        z[k] = sum(S[i][k] for i in ids)
    lu, sub_lu, yd, rkap, rtur = defaultdict(float), defaultdict(float), Counter(), Counter(), Counter()
    for i in ids:
        for c, a in S[i]["lu"].items():
            lu[c] += a
        for sc, sa in S[i].get("sub_lu", {}).items():
            sub_lu[sc] += sa
        yd.update(S[i]["yd"])
        rkap.update(S[i]["road_kap"])
        rtur.update(S[i]["road_tur"])
    z["lu"], z["sub_lu"], z["yd"], z["rkap"], z["rtur"] = lu, sub_lu, yd, rkap, rtur
    z["taks"] = min(1.0, z["barea"] / z["area"]) if z["area"] > 0 else 0.0
    z["ndens"] = z["n"] / (z["area"] / 10000.0) if z["area"] > 0 else 0.0
    z["bos_arazi_orani"] = (
        sum(S[i].get("bos_arazi_orani", 0.5) * areas[i] for i in ids) / z["area"]
    ) if z["area"] > 0 else 0.5
    dm_list = [(S[i]["donati_mesafe_m"], areas[i]) for i in ids if S[i].get("donati_mesafe_m") is not None]
    z["donati_mesafe_m"] = (sum(v * a for v, a in dm_list) / sum(a for _, a in dm_list)) if dm_list else None
    z["sub_lu_pay"] = {
        k: (sub_lu.get(k, 0.0) / z["lu_a"]) for k in (
            "konut_dusuk_seyrek", "konut_orta_yuksek", "karma_ticaret_konut",
            "mezarlik", "donati_aktif_hizmet", "donati_yesil", "bos_arazi"
        )
    } if z["lu_a"] > 0 else {}

    b = 1.0 - min(1.0, z["taks"] / 0.12)
    z["bos"] = b
    if z["lu_a"] > 0:
        sh = {c: z["lu"].get(c, 0.0) / z["lu_a"] for c in ("konut", "ticaret", "sanayi", "tarim", "donati", "sit")}
        blk_cov = min(1.0, z["lu_a"] / max(1.0, z["area"] * 0.45))
        b_eff = b * (1.0 - blk_cov)
        z["pay"] = {c: ((b_eff + (1.0 - b_eff) * v) if c == "tarim" else (1.0 - b_eff) * v) for c, v in sh.items()}
    else:
        z["pay"] = None

    tarim_orani = z["pay"]["tarim"] if z["pay"] else z["bos"]

    # KURAL 2: Yapı Nizamı ve Doku Etiketleme Mantığı (Post-Processing Rule)
    # TAKS < %5 veya Tarım/Açık Alan oranı > %70 ise varsayılan olarak "Bitişik Nizam" ATANMASIN!
    if z["taks"] < 0.05 or tarim_orani > 0.70:
        if z["taks"] < 0.015 or z["n"] == 0:
            z["yd_dom"] = "Yapısız / Açık Alan"
        else:
            z["yd_dom"] = "Seyrek Kırsal Doku"
        z["bitisik"] = 0.0
    else:
        raw_yd = yd.most_common(1)[0][0] if yd else None
        if raw_yd:
            z["yd_dom"] = raw_yd
        else:
            z["yd_dom"] = "Ayrık / Blok Nizam" if z["taks"] < 0.28 else "Bitişik / Yoğun Doku"
        z["bitisik"] = z["bit"] / z["bit_a"] if z["bit_a"] > 0 else None

    # KURAL 3: Outlier ve Kat Yüksekliği Hesabı Düzeltmesi (Alan Ağırlıklı Ortalama)
    if z["taks"] < 0.015 or z["n"] == 0:
        z["kat"] = 0.0
    elif z["taks"] < 0.05 or tarim_orani > 0.70:
        # Seyrek tarım/açık alanlarda tekil yüksek bina outlier'larını sönümleyen alan ağırlıklı ortalama
        raw_kat = (z["kat_w"] / z["kat_a"]) if z["kat_a"] > 0 else 1.0
        z["kat"] = min(2.0, raw_kat)
    else:
        z["kat"] = (z["kat_w"] / z["kat_a"]) if z["kat_a"] > 0 else None

    # KURAL 1 (Bölge Düzeyi Güvence): Sanayi veya Tarım baskın bölgede nüfus 0
    if z["pay"] and (z["pay"].get("sanayi", 0.0) >= 0.45 or z["pay"].get("tarim", 0.0) >= 0.70):
        z["nufus"] = 0.0

    z["yg"] = z["yg_w"] / z["yg_l"] if z["yg_l"] > 0 else None
    z["rkap_dom"] = rkap.most_common(1)[0][0] if rkap else None
    z["rtur_dom"] = rtur.most_common(1)[0][0] if rtur else None
    z["kotu_pay"] = z["kotu"] / z["kotu_a"] if z["kotu_a"] > 0 else None
    ev = [(S[i]["egim"], areas[i]) for i in ids if S[i]["egim"] is not None]
    z["egim"] = sum(v * a for v, a in ev) / sum(a for _, a in ev) if ev else None
    rv = [(S[i].get("rakim"), areas[i]) for i in ids if S[i].get("rakim") is not None]
    z["rakim"] = sum(v * a for v, a in rv) / sum(a for _, a in rv) if rv else None

    ext = {}
    for key, kind in ext_kinds.items():
        if kind == "count":
            ext[key] = sum((S[i]["ext"].get(key) or 0.0) for i in ids)
        else:
            vv = [(S[i]["ext"].get(key), areas[i]) for i in ids if S[i]["ext"].get(key) is not None]
            ext[key] = sum(v * a for v, a in vv) / sum(a for _, a in vv) if vv else None
    z["ext"] = ext

    # KURAL 5 İçin: Her aktif Z-skoru sütununun bu alt bölgedeki alan ağırlıklı ortalamasını sakla
    z_means = {}
    if allcols and z["area"] > 0:
        for col_key, col_vals in allcols.items():
            z_means[col_key] = sum(col_vals[i] * areas[i] for i in ids) / z["area"]
    z["z_means"] = z_means

    return z


def match_feats(zones, have, ext_kinds):
    n = len(zones)
    r_taks = alg.percentile_rank([z["taks"] for z in zones])
    r_nd = alg.percentile_rank([z["ndens"] for z in zones])
    dens = [0.5 * a + 0.5 * b for a, b in zip(r_taks, r_nd)]
    r_kat = alg.percentile_rank([z["kat"] or 0.0 for z in zones]) if have["kat"] else [None] * n
    r_egim = alg.percentile_rank([z["egim"] or 0.0 for z in zones]) if have["egim"] else [None] * n
    dkey = "donati" if "donati" in ext_kinds else None
    r_don = alg.percentile_rank([z["ext"][dkey] / (z["area"] / 10000.0) for z in zones]) if dkey else [None] * n
    for i, z in enumerate(zones):
        m = {"dens": dens[i], "kat": r_kat[i], "egim": r_egim[i], "donati": r_don[i],
             "merkez": z["merkez"], "dir": z["dir"]}
        pay = z["pay"]
        if pay:
            m.update({"konut": pay["konut"], "ticaret": pay["ticaret"], "sanayi": pay["sanayi"],
                      "tarim": pay["tarim"], "sit": pay["sit"]})
            m["karma"] = min(1.0, 2.0 * min(pay["konut"], pay["ticaret"]) + 0.3 * pay["ticaret"])
            if m["donati"] is None:
                m["donati"] = min(1.0, pay["donati"] * 3)
        else:
            m["tarim"] = z["bos"]
        if "sit" in z["ext"] and z["ext"]["sit"] is not None:
            m["sit"] = max(m.get("sit") or 0.0, min(1.0, z["ext"]["sit"] * 2))
        if "sanayi" in z["ext"] and z["ext"]["sanayi"] is not None:
            m["sanayi"] = max(m.get("sanayi") or 0.0, z["ext"]["sanayi"])
        if "tarim" in z["ext"] and z["ext"]["tarim"] is not None:
            m["tarim"] = max(m.get("tarim") or 0.0, z["ext"]["tarim"])
        if z["ext"].get("dere") is not None:
            m["dere"] = 1.0 / (1.0 + z["ext"]["dere"] / 150.0)
        if z["bitisik"] is not None:
            m["bitisik"] = z["bitisik"]
        m["bos_arazi"] = z.get("bos_arazi_orani", z.get("bos", 0.5))
        sub_p = z.get("sub_lu_pay") or {}
        m["mezarlik"] = sub_p.get("mezarlik", 0.0)
        m["dusuk_konut"] = sub_p.get("konut_dusuk_seyrek", 0.0)
        z["m"] = m


def auto_label(z):
    p = z["pay"]
    sub_p = z.get("sub_lu_pay") or {}
    if sub_p.get("mezarlik", 0.0) >= 0.25:
        return "Kentsel Mezarlık ve Açık Yeşil Tampon Kuşağı"
    if p is None:
        return "Yoğun Yapılaşma" if z["taks"] > 0.15 else "Seyrek / Tarım Çeperi"
    if p["sit"] > 0.3:
        return "Tarihi / Sit Alanı"
    if p["sanayi"] > 0.4:
        return "Sanayi / Depolama Alanı"
    if p["tarim"] > 0.55:
        return "Tarım / Çeper Doku"
    if p["konut"] > 0.25 and p["ticaret"] > 0.25:
        return "Karma Kullanım (Ticaret + Konut)"
    if p["ticaret"] > 0.35:
        return "Ticaret Ağırlıklı Merkez"
    if p["donati"] > 0.3:
        return "Sosyal / Teknik Altyapı (Donatı)"
    if sub_p.get("konut_dusuk_seyrek", 0.0) >= 0.35 or (p["konut"] > 0.25 and z.get("bos_arazi_orani", 0.0) >= 0.65):
        return "Konut (Düşük/Seyrek Yoğunluk & Yeni Gelişme Rezervi)"
    if p["konut"] > 0.3:
        return "Konut (Yüksek Yoğunluk)" if z["taks"] > 0.25 else "Konut (Orta Yoğunluk)"
    return "Karma Kentsel Doku"


def get_extra_Sit_params(z):
    """
    KURAL 4: 'yapi:kotu_yapi' (Kötü durumdaki yapı oranı %), 'sit2' (Tescilli alan %) ve
    'sit3' (Afet Risk / Kentsel Dönüşüm Sınırı %) değerlerini döndürür.
    """
    e = z.get("ext") or {}
    kotu_pct = (z["kotu_pay"] * 100.0) if z.get("kotu_pay") is not None else 0.0

    # sit2: Tescilli alan % (Eğer sit2 anahtarı varsa onu, yoksa sit anahtarını kullan)
    sit2_raw = e.get("sit2")
    if sit2_raw is None:
        sit2_raw = e.get("sit")
    sit2_pct = (sit2_raw * 100.0) if sit2_raw is not None else ((z["pay"].get("sit", 0.0) * 100.0) if z.get("pay") else 0.0)

    # sit3: Afet Risk / Kentsel Dönüşüm Sınırı % (Eğer sit3 anahtarı varsa onu, yoksa risk anahtarını kullan)
    sit3_raw = e.get("sit3")
    if sit3_raw is None:
        sit3_raw = e.get("risk")
    sit3_pct = (sit3_raw * 100.0) if sit3_raw is not None else 0.0

    return kotu_pct, sit2_pct, sit3_pct


def describe_concise(z):
    """
    KURAL 4 DÜZELTMESİ:
    Raporlanan 'Olculen_Ozet' metnine 'yapi:kotu_yapi' (Kötü durumdaki yapı oranı %),
    'sit2' (Tescilli alan %) ve 'sit3' (Afet Risk / Kentsel Dönüşüm Sınırı %) verilerini
    birer parametre olarak ekler ve metin çıktısına yazdırır.
    """
    parts = []
    p = z["pay"]
    if p:
        top = [(k.capitalize(), int(round(v * 100))) for k, v in sorted(p.items(), key=lambda kv: -kv[1]) if v >= 0.10]
        if top:
            parts.append(" + ".join(f"%{val} {cls}" for cls, val in top[:2]))
    parts.append(f"TAKS %{z['taks'] * 100:.1f}")
    if z["kat"] is not None:
        parts.append(f"Alan Ağ. Kat: {z['kat']:.1f}")
    if z["yd_dom"]:
        parts.append(f"Nizam: {z['yd_dom']}")
    parts.append(f"Nüfus: {int(round(z['nufus']))} kişi")

    kotu_pct, sit2_pct, sit3_pct = get_extra_Sit_params(z)
    parts.append(f"Kötü Yapı (yapi:kotu_yapi): %{kotu_pct:.1f}")
    parts.append(f"Tescilli Alan (sit2): %{sit2_pct:.1f}")
    parts.append(f"Afet Risk/Dönüşüm (sit3): %{sit3_pct:.1f}")

    if z["ext"].get("fay") is not None:
        parts.append(f"Faya {z['ext']['fay']:.0f}m")
    if z["ext"].get("dere") is not None:
        parts.append(f"Dereye {z['ext']['dere']:.0f}m")
    if z["ext"].get("donati") is not None:
        parts.append(f"Donatı: {int(z['ext']['donati'])} adet")
    if z["egim"] is not None:
        parts.append(f"Eğim %{z['egim']:.1f}")
    return " | ".join(parts)


def build_concise_rationale(z, ayrim_nedeni=""):
    """
    KURAL 2, 3, 4 & 5:
    Gerekçe metnine alan ağırlıklı kat sayısını, revize edilen yapı nizamı etiketini,
    'yapi:kotu_yapi', 'sit2' ve 'sit3' parametrelerini ve Z-skoru tabanlı 3'lü ayrışma gerekçesini dahil eder.
    """
    base = z.get("excel_gerekce") or f"{z['dir_name']} kesimde yer alan {z['karakter'].lower()} bölgesi."
    details = []
    p = z["pay"]
    if p:
        top = [(k, int(round(v * 100))) for k, v in sorted(p.items(), key=lambda kv: -kv[1]) if v >= 0.12]
        if top:
            details.append(", ".join(f"%{v} {k}" for k, v in top[:2]) + " kullanımı")
    details.append(f"%{z['taks']*100:.1f} TAKS yoğunluğu")
    if z["kat"] is not None:
        details.append(f"alan ağırlıklı ortalama {z['kat']:.1f} kat yüksekliği")
    if z["yd_dom"]:
        details.append(f"'{z['yd_dom']}' doku/nizam karakteri")
    details.append(f"{int(round(z['nufus']))} kişi yerleşik nüfus")

    kotu_pct, sit2_pct, sit3_pct = get_extra_Sit_params(z)
    details.append(f"kötü durumdaki yapı oranı [yapi:kotu_yapi] %{kotu_pct:.1f}")
    details.append(f"tescilli alan [sit2] %{sit2_pct:.1f}")
    details.append(f"afet risk/dönüşüm sınırı [sit3] %{sit3_pct:.1f}")

    inner_str = f"{base} İç bütünlük: {', '.join(details)} parametreleriyle bütünleştirilmiştir."
    if ayrim_nedeni:
        return f"{inner_str} {ayrim_nedeni}"
    return inner_str


# ------------------------------------------------------------------ AÇIK TÜRKÇE SÜTUNLAR
CANDIDATE_FIELDS = [
    ("Bolge_Kodu", _QVAR_STRING),
    ("Bolge_No", _QVAR_INT),
    ("Baskin_Karakter", _QVAR_STRING),
    ("Bolge_Alani_Ha", _QVAR_DOUBLE),
    ("Kisa_Metrik_Ozeti", _QVAR_STRING),
    ("Kisa_Birlestirme_ve_Ayrim_Ozeti", _QVAR_STRING),
    ("Kisa_Komsu_Ayrim_Nedeni", _QVAR_STRING),
    ("Bolgeleme_ve_Ayrim_Gerekcesi", _QVAR_STRING),
    ("Komsu_Bolgelerden_Ayrim_Nedeni", _QVAR_STRING),
    ("Olculen_Ozet", _QVAR_STRING),
    ("Ada_Hucre_Sayisi", _QVAR_INT),
    ("Toplam_Bina_Sayisi", _QVAR_INT),
    ("Bolge_Alani_m2", _QVAR_DOUBLE),
    ("Taban_Alani_Orani_TAKS_Yuzde", _QVAR_DOUBLE),
    ("Gecirimli_Yuzey_Orani_Yuzde", _QVAR_DOUBLE),
    ("Ortalama_Kat_Sayisi", _QVAR_DOUBLE),
    ("Baskin_Yapi_Nizami", _QVAR_STRING),
    ("Bitisik_Nizam_Orani_Yuzde", _QVAR_DOUBLE),
    ("Kotu_Durumdaki_Yapi_Orani_Yuzde", _QVAR_DOUBLE),
    ("Tescilli_Alan_Orani_sit2_Yuzde", _QVAR_DOUBLE),
    ("Afet_Risk_Donusum_sit3_Yuzde", _QVAR_DOUBLE),
    ("Toplam_Nufus_Kisi", _QVAR_DOUBLE),
    ("Nufus_Yogunlugu_Kisi_Ha", _QVAR_DOUBLE),
    ("Ortalama_Yol_Genisligi_m", _QVAR_DOUBLE),
    ("Baskin_Yol_Kaplamasi", _QVAR_STRING),
    ("Baskin_Yol_Kademesi", _QVAR_STRING),
    ("Ortalama_Egim_Yuzde", _QVAR_DOUBLE),
    ("Ortalama_Rakim_m", _QVAR_DOUBLE),
    ("Dereye_Uzaklik_m", _QVAR_DOUBLE),
    ("Fay_Hattina_Uzaklik_m", _QVAR_DOUBLE),
    ("Sit_Alani_Orani_Yuzde", _QVAR_DOUBLE),
    ("Taskin_Risk_Alani_Orani_Yuzde", _QVAR_DOUBLE),
    ("Sosyal_Teknik_Donati_Sayisi", _QVAR_INT),
    ("Toplanma_Alanina_Uzaklik_m", _QVAR_DOUBLE),
    ("Saglik_Tesisine_Uzaklik_m", _QVAR_DOUBLE),
    ("Konut_Kullanim_Orani_Yuzde", _QVAR_DOUBLE),
    ("Ticaret_Kullanim_Orani_Yuzde", _QVAR_DOUBLE),
    ("Sanayi_Depolama_Orani_Yuzde", _QVAR_DOUBLE),
    ("Tarim_Acik_Alan_Orani_Yuzde", _QVAR_DOUBLE),
    ("Donati_Alani_Orani_Yuzde", _QVAR_DOUBLE),
    ("Deprem_Kirilganlik_Sinifi", _QVAR_STRING),
    ("Sel_Kirilganlik_Sinifi", _QVAR_STRING),
    ("Genel_Kirilganlik_Sinifi", _QVAR_STRING),
    ("Maruz_Kalma_Derecesi", _QVAR_STRING),
    ("Hassasiyet_Derecesi", _QVAR_STRING),
    ("Uyum_Kapasitesi_Derecesi", _QVAR_STRING),
    ("Baskin_Kombinasyon", _QVAR_STRING),
    ("Mudahale_Karari", _QVAR_STRING),
    ("Plan_Karsiligi", _QVAR_STRING),
]

QUICK_SUMMARY_FIELD_NAMES = [
    "Bolge_Kodu",
    "Bolge_No",
    "Baskin_Karakter",
    "Bolge_Alani_Ha",
    "Kisa_Metrik_Ozeti",
    "Kisa_Birlestirme_ve_Ayrim_Ozeti",
    "Kisa_Komsu_Ayrim_Nedeni",
    "Bolge_Alani_m2",
    "Konut_Kullanim_Orani_Yuzde",
    "Ticaret_Kullanim_Orani_Yuzde",
    "Sanayi_Depolama_Orani_Yuzde",
    "Tarim_Acik_Alan_Orani_Yuzde",
    "Donati_Alani_Orani_Yuzde",
    "Fay_Hattina_Uzaklik_m",
    "Dereye_Uzaklik_m",
    "Ortalama_Egim_Yuzde",
    "Ortalama_Rakim_m",
    "Sosyal_Teknik_Donati_Sayisi",
    "Taban_Alani_Orani_TAKS_Yuzde",
    "Ortalama_Kat_Sayisi",
    "Baskin_Yapi_Nizami",
    "Toplam_Nufus_Kisi",
    "Genel_Kirilganlik_Sinifi",
    "Mudahale_Karari",
    "Plan_Karsiligi",
]


def r(v, d=1):
    return None if v is None else round(float(v), d)


def compute_vulnerability(z):
    ha = z["area"] / 10000.0 if z["area"] > 0 else 1.0
    dens = (z["nufus"] / ha) if ha > 0 else 0.0
    e_dens = min(5.0, max(1.0, 1.0 + (dens / 120.0) * 4.0))
    e_bldg = min(5.0, max(1.0, 1.0 + (z["n"] / 150.0) * 4.0))
    E_score = 0.6 * e_dens + 0.4 * e_bldg

    taks = z.get("taks") or 0.0
    kat = z.get("kat") or 1.0
    kotu = z.get("kotu_pay") or 0.0
    bitisik = z.get("bitisik") or 0.0
    s_taks = min(5.0, max(1.0, 1.0 + (taks / 0.6) * 4.0))
    s_kat = min(5.0, max(1.0, 1.0 + ((kat - 1.0) / 6.0) * 4.0))
    s_kotu = min(5.0, max(1.0, 1.0 + kotu * 4.0))
    s_bit = min(5.0, max(1.0, 1.0 + bitisik * 4.0))
    S_deprem = 0.35 * s_kotu + 0.25 * s_kat + 0.20 * s_bit + 0.20 * s_taks
    S_sel = 0.40 * s_taks + 0.30 * s_kotu + 0.30 * s_bit

    yg = z.get("yg") or 7.0
    ac_yg = min(5.0, max(1.0, 1.0 + ((yg - 5.0) / 15.0) * 4.0))
    gecirimli = max(0.0, 1.0 - taks)
    ac_gec = min(5.0, max(1.0, 1.0 + gecirimli * 4.0))

    ext = z.get("ext") or {}
    fay_m = ext.get("fay")
    dere_m = ext.get("dere")
    donati_n = ext.get("donati") or 0

    ac_fay = min(5.0, max(1.0, (fay_m / 1000.0) * 4.0 + 1.0)) if fay_m is not None else 3.0
    ac_dere = min(5.0, max(1.0, (dere_m / 800.0) * 4.0 + 1.0)) if dere_m is not None else 3.0
    ac_donati = min(5.0, max(1.0, 1.0 + (donati_n / 5.0) * 4.0))

    rakim = z.get("rakim")
    ac_rakim = min(5.0, max(1.0, 1.0 + ((rakim - 50.0) / 250.0) * 4.0)) if rakim is not None else 3.0

    AC_deprem = 0.40 * ac_fay + 0.30 * ac_yg + 0.30 * ac_donati
    AC_sel = 0.40 * ac_dere + 0.30 * ac_rakim + 0.30 * ac_gec

    V_deprem = (E_score * S_deprem) / max(1.0, AC_deprem)
    V_sel = (E_score * S_sel) / max(1.0, AC_sel)
    V_genel = 0.6 * V_deprem + 0.4 * V_sel

    def tier(score):
        if score < 1.8: return "Çok Düşük"
        if score < 2.6: return "Düşük"
        if score < 3.5: return "Orta"
        if score < 4.4: return "Yüksek"
        return "Çok Yüksek"

    return {
        "E_tier": tier(E_score),
        "S_tier": tier((S_deprem + S_sel) / 2.0),
        "AC_tier": tier((AC_deprem + AC_sel) / 2.0),
        "deprem_kirilganlik": tier(V_deprem),
        "sel_kirilganlik": tier(V_sel),
        "genel_kirilganlik": tier(V_genel),
    }


def zone_record(z):
    p = z["pay"] or {}

    def pc(k):
        return r(p[k] * 100, 1) if k in p else None

    e = z["ext"]
    ha = z["area"] / 10000.0 if z["area"] > 0 else 1.0
    kotu_pct, sit2_pct, sit3_pct = get_extra_Sit_params(z)
    vuln = compute_vulnerability(z)
    return {
        "Bolge_Kodu": z["kod"],
        "Bolge_No": int(re.sub(r"\D", "", z["kod"]) or 0),
        "Baskin_Karakter": z["karakter"],
        "Bolge_Alani_Ha": r(ha, 2),
        "Kisa_Metrik_Ozeti": z.get("kisa_ozet") or describe_quick_summary(z),
        "Kisa_Birlestirme_ve_Ayrim_Ozeti": z.get("kisa_gerekce") or build_quick_rationale(z, z.get("kisa_ayrim_nedeni", "")),
        "Kisa_Komsu_Ayrim_Nedeni": z.get("kisa_ayrim_nedeni", ""),
        "Bolgeleme_ve_Ayrim_Gerekcesi": z["gerekce"],
        "Komsu_Bolgelerden_Ayrim_Nedeni": z.get("ayrim_nedeni", ""),
        "Olculen_Ozet": z["olculen"],
        "Ada_Hucre_Sayisi": z["ncell"],
        "Toplam_Bina_Sayisi": z["n"],
        "Bolge_Alani_m2": r(z["area"], 0),
        "Taban_Alani_Orani_TAKS_Yuzde": r(z["taks"] * 100, 1),
        "Gecirimli_Yuzey_Orani_Yuzde": r((1.0 - z["taks"]) * 100, 1),
        "Ortalama_Kat_Sayisi": r(z["kat"], 2),
        "Baskin_Yapi_Nizami": z["yd_dom"],
        "Bitisik_Nizam_Orani_Yuzde": r(z["bitisik"] * 100, 1) if z["bitisik"] is not None else None,
        "Kotu_Durumdaki_Yapi_Orani_Yuzde": r(kotu_pct, 1),
        "Tescilli_Alan_Orani_sit2_Yuzde": r(sit2_pct, 1),
        "Afet_Risk_Donusum_sit3_Yuzde": r(sit3_pct, 1),
        "Toplam_Nufus_Kisi": r(z["nufus"], 0),
        "Nufus_Yogunlugu_Kisi_Ha": r(z["nufus"] / ha, 1),
        "Ortalama_Yol_Genisligi_m": r(z["yg"], 1),
        "Baskin_Yol_Kaplamasi": z["rkap_dom"],
        "Baskin_Yol_Kademesi": z["rtur_dom"],
        "Ortalama_Egim_Yuzde": r(z["egim"], 1),
        "Ortalama_Rakim_m": r(z.get("rakim"), 1),
        "Dereye_Uzaklik_m": r(e.get("dere"), 0),
        "Fay_Hattina_Uzaklik_m": r(e.get("fay"), 0),
        "Sit_Alani_Orani_Yuzde": r(e["sit"] * 100, 1) if e.get("sit") is not None else pc("sit"),
        "Taskin_Risk_Alani_Orani_Yuzde": r(e["risk"] * 100, 1) if e.get("risk") is not None else None,
        "Sosyal_Teknik_Donati_Sayisi": int(e["donati"]) if e.get("donati") is not None else None,
        "Toplanma_Alanina_Uzaklik_m": r(e.get("toplanma"), 0),
        "Saglik_Tesisine_Uzaklik_m": r(e.get("saglik"), 0),
        "Konut_Kullanim_Orani_Yuzde": pc("konut"),
        "Ticaret_Kullanim_Orani_Yuzde": pc("ticaret"),
        "Sanayi_Depolama_Orani_Yuzde": pc("sanayi"),
        "Tarim_Acik_Alan_Orani_Yuzde": pc("tarim"),
        "Donati_Alani_Orani_Yuzde": pc("donati"),
        "Deprem_Kirilganlik_Sinifi": vuln["deprem_kirilganlik"],
        "Sel_Kirilganlik_Sinifi": vuln["sel_kirilganlik"],
        "Genel_Kirilganlik_Sinifi": vuln["genel_kirilganlik"],
        "Maruz_Kalma_Derecesi": vuln["E_tier"],
        "Hassasiyet_Derecesi": vuln["S_tier"],
        "Uyum_Kapasitesi_Derecesi": vuln["AC_tier"],
        "Baskin_Kombinasyon": z.get("baskin_kombinasyon"),
        "Mudahale_Karari": z.get("mudahale_karari"),
        "Plan_Karsiligi": z.get("plan_karsiligi"),
    }


def make_zone_layer(res, quick_only=False):
    crs = res["work_crs"]
    raw_records = [zone_record(z) for z in res["zones"]]

    field_pool = (
        [(fn, ft) for fn, ft in CANDIDATE_FIELDS if fn in QUICK_SUMMARY_FIELD_NAMES]
        if quick_only else CANDIDATE_FIELDS
    )
    active_fields = []
    for fname, ftype in field_pool:
        has_any_value = any(rec.get(fname) is not None and str(rec.get(fname)).strip() != "" for rec in raw_records)
        if has_any_value:
            active_fields.append((fname, ftype))

    mode = res.get("mode", "advanced")
    prefix = "M" if mode == "advanced" else "A"
    n_z = max(1, len(res.get("zones", [])))
    uri = f"MultiPolygon?crs={crs.authid()}" if crs and crs.isValid() else "MultiPolygon"
    layer_name = (
        f"Alt_Bolgeler_Hizli_Ozet_{prefix}1_{prefix}{n_z}"
        if quick_only
        else f"Alt_Bolgeler_{prefix}1_{prefix}{n_z}"
    )
    lyr = QgsVectorLayer(uri, layer_name, "memory")
    if crs and crs.isValid():
        lyr.setCrs(crs)
    pr = lyr.dataProvider()
    pr.addAttributes([QgsField(n, t) for n, t in active_fields])
    lyr.updateFields()

    feats, clean_records = [], []
    for z, raw_rec in zip(res["zones"], raw_records):
        filtered_rec = {n: raw_rec[n] for n, _ in active_fields}
        clean_records.append(filtered_rec)
        f = QgsFeature(lyr.fields())
        f.setGeometry(z["geom"])
        f.setAttributes([filtered_rec[n] for n, _ in active_fields])
        feats.append(f)

    pr.addFeatures(feats)
    lyr.updateExtents()
    style_zone_layer(lyr)
    return lyr, clean_records


def make_cell_layer(res):
    crs = res["work_crs"]
    uri = f"Polygon?crs={crs.authid()}" if crs and crs.isValid() else "Polygon"
    lyr = QgsVectorLayer(uri, "Imar_Adasi_Hucreleri", "memory")
    if crs and crs.isValid():
        lyr.setCrs(crs)
    pr = lyr.dataProvider()
    pr.addAttributes([QgsField("Hucre_No", _QVAR_INT), QgsField("Bolge_Kodu", _QVAR_STRING)])
    lyr.updateFields()
    code = {z["l"]: z["kod"] for z in res["zones"]}
    feats = []
    for i, g in enumerate(res["cells"]):
        f = QgsFeature(lyr.fields())
        f.setGeometry(g)
        f.setAttributes([i, code[res["labels"][i]]])
        feats.append(f)
    pr.addFeatures(feats)
    lyr.updateExtents()
    return lyr


def style_zone_layer(layer):
    cats = []
    feats = list(layer.getFeatures())
    for i, f in enumerate(feats):
        h = (i * 0.618033988) % 1.0
        rr, gg, bb = [int(255 * c) for c in colorsys.hsv_to_rgb(h, 0.45, 0.95)]
        sym = QgsFillSymbol.createSimple({"color": f"{rr},{gg},{bb},110", "outline_color": "#0f172a",
                                          "outline_width": "0.85", "outline_style": "solid"})
        cats.append(QgsRendererCategory(f["Bolge_Kodu"], sym, str(f["Bolge_Kodu"])))
    layer.setRenderer(QgsCategorizedSymbolRenderer("Bolge_Kodu", cats))
    ls = QgsPalLayerSettings()
    ls.fieldName = "Bolge_Kodu"
    ls.isExpression = False
    tf = QgsTextFormat()
    fnt = QFont("Segoe UI", 10)
    fnt.setBold(True)
    tf.setFont(fnt)
    tf.setSize(11)
    tf.setColor(QColor("#0f172a"))
    buf = QgsTextBufferSettings()
    buf.setEnabled(True)
    buf.setSize(1.4)
    buf.setColor(QColor("#ffffff"))
    tf.setBuffer(buf)
    ls.setFormat(tf)
    layer.setLabelsEnabled(True)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(ls))
    layer.triggerRepaint()


def export_analysis_tracking_matrix(P, zones=None, target_path=None):
    """
    Kentsel Planlama Sentez ve Karar Destek Metodolojisi Uyarınca:
    'Öksüz Analiz Yok' İlkesine Dayalı Analiz İzleme ve Sentez Eşleştirme Matrisi (CSV).
    Her analizin adı, veri kaynağı, yöntemi, sentezdeki rolü ve girdiği müdahale kararını belgeler.
    """
    rows = []
    seq = 1

    def add_row(name, layer_obj, method, role, intervention, status, justification):
        nonlocal seq
        geo_type = "Yok"
        feat_count = 0
        crs_str = "Yok"
        if layer_obj is not None:
            if hasattr(layer_obj, "geometryType"):
                gt = layer_obj.geometryType()
                geo_type = "Poligon" if gt == 2 else ("Çizgi" if gt == 1 else "Nokta")
                try:
                    feat_count = layer_obj.featureCount()
                except Exception:
                    feat_count = 0
            elif isinstance(layer_obj, QgsRasterLayer):
                geo_type = f"Raster ({layer_obj.width()}x{layer_obj.height()})"
                feat_count = 1
            if hasattr(layer_obj, "crs") and layer_obj.crs().isValid():
                crs_str = layer_obj.crs().authid()
        rows.append({
            "Sira_No": seq,
            "Analiz_Katmani_Adi": name,
            "Veri_Tipi_ve_Geometri": geo_type,
            "Koordinat_Referans_Sistemi": crs_str,
            "Detay_Sayisi": feat_count,
            "Analiz_Yontemi": method,
            "Sentezdeki_Rolu": role,
            "Girdigi_Mudahale_Karari": intervention,
            "Kullanim_Durumu": status,
            "Gerekce_ve_Aciklama": justification
        })
        seq += 1

    bnd = P.get("boundary_layer")
    add_row("Plan / Onama Sınırı", bnd, "Vektör Sınır Maskesi", "Analiz Evreni ve Mekânsal Kapsam",
            "Müdahale Atlası Sınırı", "Kullanıldı" if bnd else "Otomatik",
            "Tüm hücreleme ve alt bölgeleme bu sınır içinde sınırlandırılmıştır.")

    road = P.get("road_layer")
    add_row("Ulaşım / Yol Ağı Deseni", road, "Ağ Çizgesi & Morfolojik Bölüntüleme", "Birincil Hücreleme (Street-Block)",
            "Ulaşım Hiyerarşisi, Yaya/Bisiklet Aksları", "Kullanıldı" if road else "İmar Adaları",
            "Fiziksel sokak ağı ile MAUP ölçek etkisini engelleyen doğal hücreler türetildi.")

    blk = P.get("block_layer")
    add_row("İmar Adaları / Parselasyon Dokusu", blk, "Morfometri & Fonksiyonel Dağılım", "Kentsel Doku Homojenliği",
            "Yapılaşma Nizamı, Emsal & Yoğunluk Kararları", "Kullanıldı",
            "Arazi kullanımı ve parsel morfolojisi çok kriterli Z-skoru matrisine girdi.")

    bldg = P.get("bldg_layer")
    add_row("Tekil Yapı Stoku ve Binalar", bldg, "Bina Ayak İzi & Kat Sayısı Kesişimi", "TAKS ve Kat Yüksekliği Ölçümü",
            "Kentsel Yenileme, Seyreltme, Sağlıklaştırma", "Kullanıldı" if bldg else "Ada Özniteliği",
            "Gerçek bina ayak izleri üzerinden ada bazında net TAKS ve kat ortalaması hesaplandı.")

    dem = P.get("dem")
    add_row("Sayısal Yükselti Modeli (DEM)", dem, "Horn Eğim Türevi & Ortalama Rakım (m)", "Topoğrafik Eşik & Sel/Deprem Uyum Kapasitesi",
            "Kademeli Yoğunluk, Manzara/Siluet Koruma, Drenaj", "Kullanıldı" if dem else "Dışlandı",
            "DEM piksel değerlerinden adaların ortalama rakım kotu ve eğim gradyanı ölçüldü.")

    for ext in P.get("extras", []):
        lyr = ext.get("layer")
        nm = ext.get("name", "Doğal Eşik")
        role = ext.get("role", "diger")
        if role == "dere":
            add_row(nm, lyr, "Spatial Index Euclidean Mesafe", "Hidrolojik Eşik & Sel Kırılganlığı",
                    "Doğal Yeşil Koridor, Taşkın Kuşağı, Çekme Mesafesi", "Kullanıldı",
                    "Dere yatağına en yakın mesafe ölçülerek sel uyum kapasitesine dahil edildi.")
        elif role == "fay":
            add_row(nm, lyr, "Spatial Index Euclidean Mesafe", "Sismik Tehlike & Deprem Kırılganlığı",
                    "Afet Tampon Kuşağı, Yapılaşma Yasağı, Toplanma Alanı", "Kullanıldı",
                    "Diri fay çizgisine en yakın mesafe ölçülerek deprem hassasiyetine bağlandı.")
        elif role == "sit":
            add_row(nm, lyr, "Poligon Alan Kesişim Payı", "Kültürel Miras & Koruma Statüsü",
                    "Sit Tamponu, Ziyaretçi Yönetimi, Koruma Amaçlı Plan", "Kullanıldı",
                    "Tescilli sit alanlarının ada üzerindeki yüzölçümü payı hesaplandı.")
        elif role == "risk":
            add_row(nm, lyr, "Poligon Kesişim & Risk Maskesi", "Taşkın/Afet Risk Maruziyeti",
                    "Yapı Yasağı, Taşkın Koruma Bendi, Ekolojik Alan", "Kullanıldı",
                    "Afet ve taşkın risk poligonları çok kriterli kümelemeye girdi.")
        elif role == "donati":
            add_row(nm, lyr, "Mekânsal Kümeleme & Nokta Sayımı", "Sosyal Donatı Yeterliliği / 2SFCA",
                    "Eğitim, Sağlık ve Sosyal Tesis Tahsisi", "Kullanıldı",
                    "Adalar içerisindeki donatı sayısı ve erişim düzeyi modellendi.")
        elif role in ("syntax", "nain", "nach"):
            add_row(nm, lyr, "Space Syntax Entegrasyon / Seçim Analizi", "Yaya ve Taşıt Hareketlilik Omurgası",
                    "MİA Yayalaştırma, Ulaşım Kademelenmesi", "Kullanıldı",
                    "Mekânsal dizim entegrasyon değerleri merkezilik skoruna yansıtıldı.")
        elif role in ("lst", "isi_adasi"):
            add_row(nm, lyr, "Yüzey Sıcaklığı (LST) Termal Analizi", "Kentsel Isı Adası & İklim Kırılganlığı",
                    "Yeşil Altyapı, Gölgelendirme, İklim Uyum Kararları", "Kullanıldı",
                    "Termal ısı adası odakları hassasiyet matrisinde değerlendirildi.")
        else:
            add_row(nm, lyr, "Mekânsal Kesişim & Mesafe Analizi", "Mekânsal Eşik Analizi",
                    "Genel İmar ve Müdahale Kararı", "Kullanıldı",
                    "Çalışma alanındaki mekânsal dağılım modele dahil edildi.")

    used_ids = {lyr.id() for lyr in [bnd, road, blk, bldg, dem] if lyr is not None}
    for ext in P.get("extras", []):
        if ext.get("layer") is not None:
            used_ids.add(ext["layer"].id())

    proj_layers = list(QgsProject.instance().mapLayers().values())
    for lyr in proj_layers:
        if lyr.id() not in used_ids:
            nm = lyr.name()
            if any(x in nm.lower() for x in ("alt_bolge", "hucre", "imar_adasi_hucre", "scratch", "temp")):
                continue
            add_row(nm, lyr, "Mekânsal Tarama", "Dışlama / Referans Altlık",
                    "Doğrudan Müdahale Üretmedi", "Dışlandı",
                    "Gerekçe: Çalışma sınırları dışı, mükerrer veri veya sentez ölçeğiyle uyumsuzluk nedeniyle dışlama raporlandı.")

    if target_path and rows:
        if target_path.lower().endswith(".xlsx"):
            export_excel_workbook(target_path, rows, is_matrix_only=True)
        else:
            with open(target_path, "w", newline="", encoding="utf-8-sig") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()), delimiter=";")
                writer.writeheader()
                writer.writerows(rows)

    return rows


FRIENDLY_COL_HEADERS = {
    "Bolge_Kodu": "Bölge Kodu / Zone Code",
    "Bolge_No": "Bölge No",
    "Baskin_Karakter": "Baskın Kentsel Karakter (Sub-Zone Identity)",
    "Bolge_Alani_Ha": "Alan (Hektar)",
    "Bolge_Alani_m2": "Alan (m²)",
    "Kisa_Metrik_Ozeti": "Hızlı Metrik Özeti (% Kullanım | Fay | Dere | Eğim | Donatı | TAKS | Kat | Nüfus)",
    "Kisa_Birlestirme_ve_Ayrim_Ozeti": "Hızlı Birleştirme ve Ayrım Özeti (Sade Gerekçe)",
    "Kisa_Komsu_Ayrim_Nedeni": "Komşulardan Ayrıldığı 3 Ana Fiziksel Fark",
    "Bolgeleme_ve_Ayrim_Gerekcesi": "Detaylı Teknik ve Akademik Gerekçe (İç Bütünlük + ΔZ)",
    "Komsu_Bolgelerden_Ayrim_Nedeni": "Z-Skoru Matrisi Komşu Ayrım Detayı (ΔZ)",
    "Olculen_Ozet": "Ölçülen Teknik Özet (Parametre Kodları ile)",
    "Ada_Hucre_Sayisi": "Ada / Hücre Sayısı",
    "Toplam_Bina_Sayisi": "Bina Sayısı",
    "Taban_Alani_Orani_TAKS_Yuzde": "TAKS (%)",
    "Gecirimli_Yuzey_Orani_Yuzde": "Geçirimli Yüzey (%)",
    "Ortalama_Kat_Sayisi": "Alan Ağ. Kat Sayısı",
    "Baskin_Yapi_Nizami": "Baskın Yapı Nizamı",
    "Bitisik_Nizam_Orani_Yuzde": "Bitişik Nizam (%)",
    "Kotu_Durumdaki_Yapi_Orani_Yuzde": "Kötü Yapı Oranı (%)",
    "Tescilli_Alan_Orani_sit2_Yuzde": "Tescilli Alan [sit2] (%)",
    "Afet_Risk_Donusum_sit3_Yuzde": "Afet Risk/Dönüşüm [sit3] (%)",
    "Toplam_Nufus_Kisi": "Toplam Nüfus (Kişi)",
    "Nufus_Yogunlugu_Kisi_Ha": "Nüfus Yoğunluğu (Kişi/Ha)",
    "Ortalama_Yol_Genisligi_m": "Ort. Yol Genişliği (m)",
    "Baskin_Yol_Kaplamasi": "Baskın Yol Kaplaması",
    "Baskin_Yol_Kademesi": "Baskın Yol Kademesi",
    "Ortalama_Egim_Yuzde": "Ortalama Eğim (%)",
    "Ortalama_Rakim_m": "Ortalama Rakım (m)",
    "Dereye_Uzaklik_m": "Dereye Uzaklık (m)",
    "Fay_Hattina_Uzaklik_m": "Diri Faya Uzaklık (m)",
    "Sit_Alani_Orani_Yuzde": "Sit Alanı Oranı (%)",
    "Taskin_Risk_Alani_Orani_Yuzde": "Taşkın Risk Oranı (%)",
    "Sosyal_Teknik_Donati_Sayisi": "Donatı Sayısı (Adet)",
    "Toplanma_Alanina_Uzaklik_m": "Toplanma Alanına Uzaklık (m)",
    "Saglik_Tesisine_Uzaklik_m": "Sağlık Tesisine Uzaklık (m)",
    "Konut_Kullanim_Orani_Yuzde": "Konut Oranı (%)",
    "Ticaret_Kullanim_Orani_Yuzde": "Ticaret Oranı (%)",
    "Sanayi_Depolama_Orani_Yuzde": "Sanayi Oranı (%)",
    "Tarim_Acik_Alan_Orani_Yuzde": "Tarım / Açık Alan (%)",
    "Donati_Alani_Orani_Yuzde": "Donatı Alanı Oranı (%)",
    "Deprem_Kirilganlik_Sinifi": "Deprem Kırılganlık Sınıfı",
    "Sel_Kirilganlik_Sinifi": "Sel Kırılganlık Sınıfı",
    "Genel_Kirilganlik_Sinifi": "Genel Kırılganlık Sınıfı",
    "Maruz_Kalma_Derecesi": "Maruz Kalma (E)",
    "Hassasiyet_Derecesi": "Hassasiyet (S)",
    "Uyum_Kapasitesi_Derecesi": "Uyum Kapasitesi (AC)",
    "Baskin_Kombinasyon": "Baskın Doku Kombinasyonu",
    "Mudahale_Karari": "Planlama Müdahale Kararı",
    "Plan_Karsiligi": "1/5000 & 1/1000 Plan Karşılığı",
}


def export_excel_workbook(target_path, records, quick_records=None, P=None, zones=None, is_matrix_only=False):
    """
    Okunabilirliği yüksek, renkli başlıklı, satır kaydırmalı (word-wrap), sütun genişlikleri
    otomatik ayarlanmış çok sayfalı (.xlsx) Excel çalışma kitabı üretir.
    """
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        # openpyxl yoksa güvenli CSV fallback
        if records:
            with open(target_path, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.DictWriter(fh, fieldnames=list(records[0].keys()), delimiter=";")
                w.writeheader()
                w.writerows(records)
        return target_path

    wb = openpyxl.Workbook()
    hdr_fill = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
    hdr_font = Font(name="Segoe UI", size=10, bold=True, color="FFFFFF")
    sub_fill = PatternFill(start_color="E0F2FE", end_color="E0F2FE", fill_type="solid")
    zebra_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    white_fill = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")
    code_font = Font(name="Segoe UI", size=10, bold=True, color="0369A1")
    body_font = Font(name="Segoe UI", size=10, color="0F172A")
    thin_side = Side(border_style="thin", color="CBD5E1")
    cell_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

    def _populate_sheet(ws, rows_data, col_keys=None, freeze_cell="D2"):
        if not rows_data:
            return
        keys = col_keys or list(rows_data[0].keys())
        keys = [k for k in keys if any(r.get(k) is not None and str(r.get(k)).strip() != "" for r in rows_data)]
        headers = [FRIENDLY_COL_HEADERS.get(k, k.replace("_", " ")) for k in keys]
        ws.append(headers)
        ws.row_dimensions[1].height = 30
        for col_idx, k in enumerate(keys, 1):
            c = ws.cell(row=1, column=col_idx)
            c.fill = hdr_fill
            c.font = hdr_font
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            c.border = cell_border

        for r_idx, row_dict in enumerate(rows_data, 2):
            vals = [row_dict.get(k) for k in keys]
            ws.append(vals)
            has_long_text = any(isinstance(v, str) and len(v) > 85 for v in vals)
            ws.row_dimensions[r_idx].height = 46 if has_long_text else 24
            r_fill = zebra_fill if (r_idx % 2 == 1) else white_fill
            for col_idx, k in enumerate(keys, 1):
                c = ws.cell(row=r_idx, column=col_idx)
                val = row_dict.get(k)
                c.border = cell_border
                if col_idx == 1:
                    c.fill = sub_fill
                    c.font = code_font
                    c.alignment = Alignment(horizontal="center", vertical="center")
                elif isinstance(val, (int, float)):
                    c.fill = r_fill
                    c.font = body_font
                    c.alignment = Alignment(horizontal="right", vertical="center")
                else:
                    c.fill = r_fill
                    c.font = body_font
                    c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)

        for col_idx, k in enumerate(keys, 1):
            col_letter = get_column_letter(col_idx)
            max_len = len(headers[col_idx - 1])
            for r_dict in rows_data:
                sval = str(r_dict.get(k) or "")
                max_len = max(max_len, min(62, len(sval)))
            if k in ("Bolgeleme_ve_Ayrim_Gerekcesi", "Komsu_Bolgelerden_Ayrim_Nedeni", "Kisa_Birlestirme_ve_Ayrim_Ozeti", "Kisa_Metrik_Ozeti", "Olculen_Ozet"):
                ws.column_dimensions[col_letter].width = 52
            elif k in ("Baskin_Karakter", "Mudahale_Karari", "Plan_Karsiligi", "Kisa_Komsu_Ayrim_Nedeni"):
                ws.column_dimensions[col_letter].width = 34
            elif k in ("Bolge_Kodu", "Bolge_No"):
                ws.column_dimensions[col_letter].width = 13
            else:
                ws.column_dimensions[col_letter].width = max(14, min(32, max_len + 4))

        ws.freeze_panes = freeze_cell
        ws.auto_filter.ref = ws.dimensions

    if is_matrix_only:
        ws0 = wb.active
        ws0.title = "Analiz_Izleme_Matrisi"
        _populate_sheet(ws0, records, freeze_cell="C2")
        wb.save(target_path)
        return target_path

    # Sayfa 1: Hızlı ve Sade Özet Tablosu (İlk bakışta okuma)
    ws1 = wb.active
    ws1.title = "1_Hizli_Ozet_Tablosu"
    q_recs = quick_records or records
    quick_Sheet_cols = [
        "Bolge_Kodu", "Bolge_No", "Baskin_Karakter", "Bolge_Alani_Ha",
        "Kisa_Metrik_Ozeti", "Kisa_Birlestirme_ve_Ayrim_Ozeti", "Kisa_Komsu_Ayrim_Nedeni",
        "Genel_Kirilganlik_Sinifi", "Mudahale_Karari", "Plan_Karsiligi"
    ]
    _populate_sheet(ws1, records, col_keys=quick_Sheet_cols, freeze_cell="D2")

    # Sayfa 2: Temel Sayısal Metrikler Tablosu (Sayısal analiz / grafik için)
    ws2 = wb.create_sheet(title="2_Sayisal_Planlama_Tablosu")
    num_cols = [
        "Bolge_Kodu", "Bolge_No", "Baskin_Karakter", "Bolge_Alani_Ha", "Bolge_Alani_m2",
        "Ada_Hucre_Sayisi", "Toplam_Bina_Sayisi", "Toplam_Nufus_Kisi", "Nufus_Yogunlugu_Kisi_Ha",
        "Taban_Alani_Orani_TAKS_Yuzde", "Ortalama_Kat_Sayisi", "Baskin_Yapi_Nizami",
        "Konut_Kullanim_Orani_Yuzde", "Ticaret_Kullanim_Orani_Yuzde", "Sanayi_Depolama_Orani_Yuzde",
        "Tarim_Acik_Alan_Orani_Yuzde", "Donati_Alani_Orani_Yuzde",
        "Fay_Hattina_Uzaklik_m", "Dereye_Uzaklik_m", "Ortalama_Egim_Yuzde", "Ortalama_Rakim_m",
        "Sosyal_Teknik_Donati_Sayisi", "Kotu_Durumdaki_Yapi_Orani_Yuzde",
        "Tescilli_Alan_Orani_sit2_Yuzde", "Afet_Risk_Donusum_sit3_Yuzde",
        "Deprem_Kirilganlik_Sinifi", "Sel_Kirilganlik_Sinifi", "Genel_Kirilganlik_Sinifi"
    ]
    _populate_sheet(ws2, records, col_keys=num_cols, freeze_cell="D2")

    # Sayfa 3: Detaylı Teknik & Akademik Kontrol Tablosu (Tüm ΔZ ve Parametre Kodları)
    ws3 = wb.create_sheet(title="3_Detayli_Teknik_Kontrol")
    _populate_sheet(ws3, records, col_keys=None, freeze_cell="D2")

    # Sayfa 4: Analiz İzleme Matrisi ("Öksüz Analiz Yok")
    if P:
        matrix_rows = export_analysis_tracking_matrix(P, zones=zones, target_path=None)
        if matrix_rows:
            ws4 = wb.create_sheet(title="4_Analiz_Izleme_Matrisi")
            _populate_sheet(ws4, matrix_rows, freeze_cell="C2")

    wb.save(target_path)
    return target_path
