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
from qgis.core import (
    QgsGeometry, QgsPointXY, QgsSpatialIndex, QgsFeature, QgsWkbTypes, QgsRectangle,
    QgsCoordinateTransform, QgsProject, QgsVectorLayer, QgsRasterLayer, QgsField, NULL,
    QgsCategorizedSymbolRenderer, QgsRendererCategory, QgsFillSymbol,
    QgsPalLayerSettings, QgsVectorLayerSimpleLabeling, QgsTextFormat, QgsTextBufferSettings,
    QgsCsException
)

from . import algoritma as alg

_QVAR_INT = getattr(QVariant, "Int", 2)
_QVAR_DOUBLE = getattr(QVariant, "Double", 6)
_QVAR_STRING = getattr(QVariant, "String", 10)

ROLES = [
    ("Dere / Akarsu Yatağı (Uzaklık - m)", "dere", "dist"),
    ("Sit / Koruma Alanı (Alan Oranı - %)", "sit", "share"),
    ("Diri Fay Hattı (Uzaklık - m)", "fay", "dist"),
    ("Taşkın / Afet Risk Alanı (Alan Oranı - %)", "risk", "share"),
    ("Tarım / Mera / Çevre Koruma (Alan Oranı - %)", "tarim", "share"),
    ("Sanayi / OSB Çevre Kuşağı (Alan Oranı - %)", "sanayi", "share"),
    ("Diğer Doğal Eşik Katmanı (Otomatik Algıla)", "genel", "auto"),
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


def _poly_rings_list(g, min_area=0.01, _depth=0):
    """Her türlü poligon / çoklu poligon / GeometryCollection yapısından tek-parça halka listelerini güvenli çıkarır."""
    if g is None or g.isEmpty() or _depth > 8:
        return []
    if g.isMultipart():
        try:
            coll = g.asGeometryCollection()
        except (TypeError, ValueError, AttributeError):
            coll = []
        if coll:
            out = []
            for sub in coll:
                out.extend(_poly_rings_list(sub, min_area=min_area, _depth=_depth + 1))
            return out
        try:
            mp = g.asMultiPolygon()
            out = []
            for pr in mp:
                if pr and len(pr[0]) >= 4:
                    pg = QgsGeometry.fromPolygonXY(pr)
                    if pg and not pg.isEmpty() and pg.area() >= min_area:
                        out.append(pr)
            return out
        except (TypeError, ValueError, AttributeError):
            return []
    if g.type() == QgsWkbTypes.GeometryType.PolygonGeometry:
        try:
            rings = g.asPolygon()
            if rings and len(rings[0]) >= 4 and g.area() >= min_area:
                return [rings]
            return []
        except (TypeError, ValueError, AttributeError):
            pass
        try:
            mp = g.asMultiPolygon()
            out = []
            for pr in mp:
                if pr and len(pr[0]) >= 4:
                    pg = QgsGeometry.fromPolygonXY(pr)
                    if pg and not pg.isEmpty() and pg.area() >= min_area:
                        out.append(pr)
            return out
        except (TypeError, ValueError, AttributeError):
            pass
    try:
        coll = g.asGeometryCollection()
        out = []
        for sub in coll:
            if sub is not None and not sub.isEmpty() and not sub.equals(g):
                out.extend(_poly_rings_list(sub, min_area=min_area, _depth=_depth + 1))
        return out
    except (TypeError, ValueError, AttributeError):
        return []


def poly_parts(g, min_area=0.01):
    """GeometryCollection ve karma tiplere dayanıklı şekilde yalnızca tek-parça Polygon nesneleri döndürür."""
    rings_list = _poly_rings_list(g, min_area=min_area)
    return [QgsGeometry.fromPolygonXY(pr) for pr in rings_list]


def _to_clean_multipolygon(geom, min_area=0.01):
    """GeometryCollection artıkları (0D/1D nokta/çizgi) ayıklayıp geçerli bir MultiPolygon döndürür."""
    if geom is None or geom.isEmpty():
        return geom
    rings_list = _poly_rings_list(geom, min_area=min_area)
    if not rings_list:
        return QgsGeometry()
    out = QgsGeometry.fromMultiPolygonXY(rings_list)
    if not out.isGeosValid():
        out = out.makeValid()
        rings_list2 = _poly_rings_list(out, min_area=min_area)
        if rings_list2:
            out = QgsGeometry.fromMultiPolygonXY(rings_list2)
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
    for rings in _poly_rings_list(geom, min_area=0.01):
        if rings and len(rings[0]) >= 4:
            ext_parts.append(QgsGeometry.fromPolygonXY([rings[0]]))
    if not ext_parts:
        return _to_clean_multipolygon(geom)
    u = QgsGeometry.unaryUnion(ext_parts) if len(ext_parts) > 1 else ext_parts[0]
    return _to_clean_multipolygon(u)


def _strip_empty_holes_only(poly_list):
    """
    Yalnızca içinde BAŞKA BİR hücre/bölge bulunmayan boş delikleri doldurur.
    Eğer deliğin içinde başka bir hücre oturuyorsa o deliği korur ki iki poligon üst üste binmesin!
    """
    if not poly_list:
        return poly_list
    pts = [g.pointOnSurface() for g in poly_list]
    pt_idx = build_index(pts)
    out = []
    for idx_i, g in enumerate(poly_list):
        if g is None or g.isEmpty():
            out.append(g)
            continue
        new_parts = []
        changed = False
        for rings in _poly_rings_list(g, min_area=0.01):
            if not rings:
                continue
            if len(rings) <= 1:
                new_parts.append(QgsGeometry.fromPolygonXY(rings))
                continue
            kept_rings = [rings[0]]
            for inner in rings[1:]:
                if len(inner) < 4:
                    continue
                inner_poly = QgsGeometry.fromPolygonXY([inner])
                inner_bb = inner_poly.boundingBox()
                has_occupant = False
                for j in pt_idx.intersects(inner_bb):
                    if j != idx_i and inner_poly.contains(pts[j]):
                        has_occupant = True
                        break
                if has_occupant:
                    kept_rings.append(inner)
                else:
                    changed = True
            new_parts.append(QgsGeometry.fromPolygonXY(kept_rings))
        if changed and new_parts:
            ug = QgsGeometry.unaryUnion(new_parts) if len(new_parts) > 1 else new_parts[0]
            ug = _to_clean_multipolygon(ug)
            out.append(ug if ug and not ug.isEmpty() else _to_clean_multipolygon(g))
        else:
            out.append(_to_clean_multipolygon(g))
    return out


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
    study_eng = QgsGeometry.createGeometryEngine(study.constGet())
    study_eng.prepareGeometry()
    raw_cells = []
    for p in faces.asGeometryCollection():
        if p.isEmpty() or p.area() < 1.0:
            continue
        pos = p.pointOnSurface()
        if study_eng.contains(pos.constGet()):
            raw_cells.append(p)

    raw_cells = _strip_empty_holes_only(raw_cells)

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
    work_boxes = [g.boundingBox() for g in work_cells]
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
            bb_i = work_boxes[i]
            best_nb = -1
            best_shared = -1.0
            for j in c_idx.intersects(bb_i):
                rj = find_root(j)
                if rj == ri:
                    continue
                if is_median[rj] and _pass < 4:
                    continue
                if not bb_i.intersects(work_boxes[j]):
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
            merged_cells.append(glist[0])
        else:
            u = QgsGeometry.unaryUnion(glist)
            for part in poly_parts(u):
                if part.area() > 1.0:
                    merged_cells.append(part)

    merged_cells = _strip_empty_holes_only(merged_cells)
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
    boxes = [g.boundingBox() for g in cells]
    adj = {i: set() for i in range(len(cells))}
    for i, g in enumerate(cells):
        bb = boxes[i]
        for j in idx.intersects(bb):
            if j <= i or not bb.intersects(boxes[j]):
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
        "yd": Counter(), "ext": {}, "ext_min": {}, "egim": None, "yg_w": 0.0, "yg_l": 0.0,
        "road_kap": Counter(), "road_tur": Counter(), "road_len": 0.0,
        "road_nodes": 0, "road_dead_ends": 0,
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
        for rc in res_block_pops:
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


def assign_zone_populations_from_blocks(zones, res_block_pops, assign_orphans=True):
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
        elif assign_orphans:
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

    node_deg = Counter()
    node_coords = {}
    node_road_ids = defaultdict(set)

    for r_i, (rf, rg) in enumerate(roads_fg):
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
        # Yol ağı topolojisinden gerçek düğüm/çıkmaz sokak tespiti
        for lp in line_parts(rg):
            vtx = list(lp.vertices())
            if len(vtx) >= 2:
                p0 = (float(vtx[0].x()), float(vtx[0].y()))
                p1 = (float(vtx[-1].x()), float(vtx[-1].y()))
                k0 = (round(p0[0] * 2.0), round(p0[1] * 2.0))
                k1 = (round(p1[0] * 2.0), round(p1[1] * 2.0))
                if k0 != k1:
                    node_deg[k0] += 1
                    node_deg[k1] += 1
                    node_coords[k0] = p0
                    node_coords[k1] = p1
                    node_road_ids[k0].add(r_i)
                    node_road_ids[k1].add(r_i)

    dead_count = 0
    if node_deg:
        r_idx = build_index([rg for _, rg in roads_fg])
        for k_node, deg in node_deg.items():
            px, py = node_coords[k_node]
            pt_g = QgsGeometry.fromPointXY(QgsPointXY(px, py))
            is_dead = False
            if deg == 1:
                is_dead = True
                own_ids = node_road_ids[k_node]
                near_roads = r_idx.intersects(QgsRectangle(px - 2.5, py - 2.5, px + 2.5, py + 2.5))
                for rj in near_roads:
                    if rj not in own_ids and roads_fg[rj][1].distance(pt_g) <= 2.5:
                        is_dead = False
                        break
            if is_dead:
                dead_count += 1
            for c in cidx.intersects(QgsRectangle(px - 12.0, py - 12.0, px + 12.0, py + 12.0)):
                if cells[c].distance(pt_g) <= 12.0:
                    S[c]["road_nodes"] += 1
                    if is_dead:
                        S[c]["road_dead_ends"] += 1

    log(f"• [Ulaşım Ağı] {matched_r}/{len(roads_fg)} yol segmenti, {len(node_deg)} ağ düğümü ({dead_count} çıkmaz uç) hücrelerle ilişkilendirildi.")


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
            cand_ids = set(idx.intersects(cg.boundingBox()))
            cand_ids.update(idx.nearestNeighbor(cg.centroid().asPoint(), 6))
            d = min((cg.distance(geoms[j]) for j in cand_ids), default=None)
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
    n = 3
    eng = QgsGeometry.createGeometryEngine(cg.constGet())
    eng.prepareGeometry()
    pts = []
    for i in range(n):
        for j in range(n):
            x = bb.xMinimum() + (i + 0.5) * bb.width() / n
            y = bb.yMinimum() + (j + 0.5) * bb.height() / n
            pt_g = QgsGeometry.fromPointXY(QgsPointXY(x, y))
            if eng.contains(pt_g.constGet()):
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


def _compute_sampled_dist(cells, geoms, grid_n=4):
    """Büyük poligonlarda (hazır bölgelerde) iç nokta örneklemesi ile ortalama ve tam en kısa mesafe hesaplar."""
    if not geoms:
        return [None] * len(cells), [None] * len(cells)
    idx = build_index(geoms)
    means, mins = [], []
    for cg in cells:
        cand_ids = set(idx.intersects(cg.boundingBox()))
        cand_ids.update(idx.nearestNeighbor(cg.centroid().asPoint(), 6))
        d_min = min((cg.distance(geoms[j]) for j in cand_ids), default=None)
        mins.append(d_min)
        bb = cg.boundingBox()
        eng = QgsGeometry.createGeometryEngine(cg.constGet())
        eng.prepareGeometry()
        s_pts = []
        for ii in range(grid_n):
            for jj in range(grid_n):
                x = bb.xMinimum() + (ii + 0.5) * bb.width() / grid_n
                y = bb.yMinimum() + (jj + 0.5) * bb.height() / grid_n
                pg = QgsGeometry.fromPointXY(QgsPointXY(x, y))
                if eng.contains(pg.constGet()):
                    s_pts.append((pg, QgsPointXY(x, y)))
        if not s_pts:
            c = cg.pointOnSurface().asPoint()
            s_pts = [(QgsGeometry.fromPointXY(c), c)]
        ds = []
        for pg, pt in s_pts:
            nn = set(idx.nearestNeighbor(pt, 4))
            nn.update(idx.intersects(QgsRectangle(pt.x() - 2500.0, pt.y() - 2500.0, pt.x() + 2500.0, pt.y() + 2500.0)))
            if not nn:
                nn = cand_ids
            d_pt = min((pg.distance(geoms[j]) for j in nn), default=None)
            if d_pt is not None:
                ds.append(d_pt)
        means.append((sum(ds) / len(ds)) if ds else d_min)
    return means, mins


def _load_context_layers(P, log, fallback_study_geoms=None):
    """Temel ada, yapı, yol ve çalışma sınırı katmanlarını work_crs projeksiyonunda yükler."""
    work_crs = P["work_crs"]
    filter_medians = P.get("filter_medians", True)

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
    elif fallback_study_geoms:
        study = QgsGeometry.unaryUnion(fallback_study_geoms)
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
    return blocks, bldgs, roads_fg, study


def _measure_cells_and_zscores(
    cells, P, blocks, bldgs, roads_fg, adj, cidx, pts, areas, work_crs, log, progress, is_custom_zones=False
):
    """Hücre veya hazır bölge poligonları üzerinde tüm mekânsal ölçümleri ve Z-skoru matrisini üretir."""
    n = len(cells)
    S = [new_stat(a) for a in areas]

    tick(progress, 32, "3/7 Ada, Tekil Yapı, Nüfus, Yol ve Doğal Eşik verileri işleniyor...", log)
    if blocks and bldgs:
        accumulate_polygons(blocks, cells, cidx, S, P["fields"], log, label_name="İmar Adaları", count_footprint=False)
        accumulate_polygons(bldgs, cells, cidx, S, P.get("bfields", {}), log, label_name="Tekil Yapı Stoku", count_footprint=True)
    elif bldgs:
        accumulate_polygons(bldgs, cells, cidx, S, P.get("bfields", {}), log, label_name="Tekil Yapı Stoku", count_footprint=True)
    elif blocks:
        accumulate_polygons(blocks, cells, cidx, S, P["fields"], log, label_name="İmar Adaları / Yapılar", count_footprint=True)

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
        log(f"• [Doğal/Ek Katman] {ex['name']} → '{key}' kriteri hesaplandı ve analiz matrisine eklendi.")
        if is_custom_zones and kind == "dist":
            mean_vals, min_vals = _compute_sampled_dist(cells, geoms)
            for i, (mv, mn) in enumerate(zip(mean_vals, min_vals)):
                S[i]["ext"][key] = mv
                if mn is not None:
                    S[i]["ext_min"][key] = mn
        else:
            vals = compute_extra(cells, geoms, kind)
            for i, v in enumerate(vals):
                S[i]["ext"][key] = v
                if kind == "dist" and v is not None:
                    S[i]["ext_min"][key] = v
        ext_kinds[key] = kind
        QApplication.processEvents()

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
        if is_custom_zones:
            d_means, _ = _compute_sampled_dist(cells, donati_ref_geoms)
            for i, d_min in enumerate(d_means):
                S[i]["donati_mesafe_m"] = d_min
        else:
            d_idx = build_index(donati_ref_geoms)
            for i, cg in enumerate(cells):
                nn_ids = d_idx.nearestNeighbor(cg.centroid().asPoint(), 4)
                d_min = min((cg.distance(donati_ref_geoms[j]) for j in nn_ids), default=None)
                S[i]["donati_mesafe_m"] = d_min
        log(f"• [Donatı & Okul Erişimi] {len(donati_ref_geoms)} donatı/okul/park birimine göre erişim mesafesi (500m / 1000m bantları) hesaplandı.")
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
            log("• [Topoğrafya] DEM/Eğim katmanından her alanın gerçek eğimi (%) ve ortalama rakımı (m) hesaplandı.")

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
    top = [i for i in order[:max(1, min(len(order), max(3, n // 10)))] if S[i]["n"] > 0] or order[:max(1, min(len(order), 3))]
    wsum = sum(max(1, S[i]["n"]) for i in top)
    center = (sum(pts[i][0] * max(1, S[i]["n"]) for i in top) / wsum,
              sum(pts[i][1] * max(1, S[i]["n"]) for i in top) / wsum)

    tick(progress, 58, "4/7 Tüm girdiler Z-skoru matrisine dönüştürülüyor...", log)

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
            groups["yapi"]["kat"] = [
                (s["kat_w"] / s["kat_a"]) if (s["kat_a"] > 0 and (s["barea"] / s["area"]) >= 0.05) else 0.0
                for s in S
            ]
        if have["bit"]:
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
    c_mode = str(P.get("compactness_mode", "balanced") or "balanced").lower()
    w_bos = float(P.get("w_bos", 1.8) or 1.0)
    w_erisim = float(P.get("w_erisim", 1.8) or 1.0)
    w_yol = float(P.get("w_yol", 1.5) or 1.0)
    w_odak = float(P.get("w_odak", 1.8) or 1.0)

    geo_scale = 0.75 if c_mode == "organic" else (1.8 if c_mode == "strict" else 1.2)
    gw = {"lu": P["w_lu"], "yapi": P["w_yapi"], "dogal": P["w_dogal"], "geo": max(0.0, P["w_geo"]) * geo_scale}
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

    log(f"• Aktif analiz değişken sayısı: {len(allcols)} (Strateji: {preset_mode})")
    names = sorted(allcols)
    vecs = [[allcols[k][i] * colw[k] for k in names] for i in range(n)]
    if not names:
        vecs = [[0.0] for _ in range(n)]

    return S, ext_kinds, have, center, res_block_pops, dens_c, allcols, colw, names, vecs


def _finalize_zone_narratives(zones, P, have, ext_kinds, adj, labels, allcols, mode, connect_isolated=False):
    """Alt bölgeler için sıfır halüsinasyonlu planlama kimliği, E/S/AC kırılganlık ve ΔZ ayrım raporlarını üretir."""
    match_feats(zones, have, ext_kinds)
    target_rows = alg.ADVANCED_PROFILES if mode == "advanced" else alg.EXCEL_ROWS
    assign_truthful_planning_identities(zones, P, target_rows, mode=mode, preserve_codes=connect_isolated)

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

    for z in zones:
        act_don = z.get("active_donati_m2", 0.0)
        z["kisi_basi_donati_m2"] = (act_don / z["nufus"]) if z.get("nufus", 0.0) >= 10.0 else None
        z["vuln"] = compute_vulnerability(z)

    zone_adj = build_zone_neighbors_from_geoms(zones, adj, labels)
    if connect_isolated and len(zones) >= 2:
        for i in range(len(zones)):
            if zone_adj.get(i):
                continue
            gi = zones[i].get("geom")
            if not gi or gi.isEmpty():
                continue
            nearest = sorted(
                ((gi.distance(zones[j]["geom"]), j) for j in range(len(zones)) if j != i and zones[j].get("geom")),
                key=lambda x: x[0],
            )[:2]
            for _, j in nearest:
                zone_adj[i].add(j)
                zone_adj[j].add(i)

    for idx_z, z in enumerate(zones):
        z["olculen"] = describe_concise(z)
        z["ayrim_nedeni"] = build_contrast_explanation(z, zones, zone_adj.get(idx_z, []), allcols=allcols)
        z["gerekce"] = build_concise_rationale(z, z["ayrim_nedeni"])
        z["kisa_ozet"] = describe_quick_summary(z)
        z["kisa_ayrim_nedeni"] = build_quick_contrast(z, zones, zone_adj.get(idx_z, []), allcols=allcols)
        z["kisa_gerekce"] = build_quick_rationale(z, z["kisa_ayrim_nedeni"])

    if not connect_isolated:
        zones.sort(key=lambda z: int(re.sub(r"\D", "", z["kod"]) or 0))
    return zones


# ------------------------------------------------------------------ ana boru hattı
def run_pipeline(P, log, progress):
    work_crs = P["work_crs"]
    K = P["K"]
    filter_medians = P.get("filter_medians", True)
    mode = P.get("mode", "advanced")
    prefix = "M" if mode == "advanced" else "A"

    if work_crs.isGeographic():
        raise RuntimeError("Katmanlar coğrafi (derece) CRS'te. Lütfen metrik bir CRS'e çevirin "
                           "(ör. EPSG:5253 [İzmir / TUREF] veya EPSG:32635) ve tekrar deneyin.")

    tick(progress, 5, "1/7 Çalışma alanı, imar adaları ve opsiyonel yapı stoku okunuyor...", log)
    blocks, bldgs, roads_fg, study = _load_context_layers(P, log)

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

    S, ext_kinds, have, center, res_block_pops, dens_c, allcols, colw, names, vecs = _measure_cells_and_zscores(
        cells, P, blocks, bldgs, roads_fg, adj, cidx, pts, areas, work_crs, log, progress, is_custom_zones=False
    )
    preset_mode = P.get("preset_mode", "integrated_synthesis")
    c_mode = str(P.get("compactness_mode", "balanced") or "balanced").lower()
    w_bos = float(P.get("w_bos", 1.8) or 1.0)
    w_erisim = float(P.get("w_erisim", 1.8) or 1.0)
    w_yol = float(P.get("w_yol", 1.5) or 1.0)
    w_odak = float(P.get("w_odak", 1.8) or 1.0)
    requested_K = K

    # Sanayi bütünlüğü, büyük alan muafiyeti (baba alanlar), konut/donatı ölçeklendirmesi ve mekânsal kompaktlık
    cell_san = [(S[i]["lu"].get("sanayi", 0.0) / S[i]["lu_a"]) if S[i]["lu_a"] > 0 else 0.0 for i in range(n)]
    cell_tar = [(S[i]["lu"].get("tarim", 0.0) / S[i]["lu_a"]) if S[i]["lu_a"] > 0 else 0.0 for i in range(n)]
    cell_kon = [(S[i]["lu"].get("konut", 0.0) / S[i]["lu_a"]) if S[i]["lu_a"] > 0 else 0.0 for i in range(n)]
    cell_don = [(S[i]["lu"].get("donati", 0.0) / S[i]["lu_a"]) if S[i]["lu_a"] > 0 else 0.0 for i in range(n)]
    cell_mez = [(S[i]["sub_lu"].get("mezarlik", 0.0) / S[i]["lu_a"]) if S[i]["lu_a"] > 0 else 0.0 for i in range(n)]
    cell_bos = [S[i]["bos_arazi_orani"] for i in range(n)]
    cell_don_m = [S[i].get("donati_mesafe_m") for i in range(n)]

    cell_areas = [areas[i] for i in range(n)]
    cell_perims = [max(1.0, cells[i].length()) for i in range(n)]
    cell_cx = [pts[i][0] for i in range(n)]
    cell_cy = [pts[i][1] for i in range(n)]
    w_geo_mult = float(P.get("w_geo", 2.5) or 2.5)

    # Hücreler arası ortak kenar uzunluklarını (shared_len) Bounding Box ön elemesiyle hızlı hesapla
    c_boxes = [g.boundingBox() for g in cells]
    shared_len = defaultdict(float)
    for i_node, nbs_node in adj.items():
        bi = c_boxes[i_node]
        for j_node in nbs_node:
            if j_node > i_node and bi.intersects(c_boxes[j_node]):
                inter_geom = cells[i_node].intersection(cells[j_node])
                slen = inter_geom.length() if inter_geom and not inter_geom.isEmpty() else 0.0
                if slen > 0.01:
                    shared_len[(i_node, j_node)] = slen
                    shared_len[(j_node, i_node)] = slen

    # O(1) Artımlı Küme İstatistikleri (Ward kümelemesini 20x-50x hızlandırır + anlık Polsby-Popper kompaktlığı izler)
    c_san_s = list(cell_san)
    c_tar_s = list(cell_tar)
    c_kon_s = list(cell_kon)
    c_don_s = list(cell_don)
    c_mez_s = list(cell_mez)
    c_bos_s = list(cell_bos)
    c_cx_w = [cell_cx[i] * cell_areas[i] for i in range(n)]
    c_cy_w = [cell_cy[i] * cell_areas[i] for i in range(n)]
    c_dm_s = [(cell_don_m[i] if cell_don_m[i] is not None else 0.0) for i in range(n)]
    c_dm_n = [(1 if cell_don_m[i] is not None else 0) for i in range(n)]
    c_perim = list(cell_perims)
    edge_sh = {}
    for (u_n, v_n), sv in shared_len.items():
        if u_n < v_n:
            edge_sh[(u_n, v_n)] = sv
    # Kopuk bileşen köprüleri için adj içindeki tüm kenarları güvenceye al
    cluster_nbs = {i: set(adj[i]) for i in range(n)}

    def on_cluster_merge(keep_a, drop_b):
        key_ab = (keep_a, drop_b) if keep_a < drop_b else (drop_b, keep_a)
        sh_ab = edge_sh.pop(key_ab, 0.0)
        c_san_s[keep_a] += c_san_s[drop_b]
        c_tar_s[keep_a] += c_tar_s[drop_b]
        c_kon_s[keep_a] += c_kon_s[drop_b]
        c_don_s[keep_a] += c_don_s[drop_b]
        c_mez_s[keep_a] += c_mez_s[drop_b]
        c_bos_s[keep_a] += c_bos_s[drop_b]
        c_cx_w[keep_a] += c_cx_w[drop_b]
        c_cy_w[keep_a] += c_cy_w[drop_b]
        c_dm_s[keep_a] += c_dm_s[drop_b]
        c_dm_n[keep_a] += c_dm_n[drop_b]
        c_perim[keep_a] = max(4.0, c_perim[keep_a] + c_perim[drop_b] - 2.0 * sh_ab)
        for x in list(cluster_nbs[drop_b]):
            cluster_nbs[x].discard(drop_b)
            kb = (drop_b, x) if drop_b < x else (x, drop_b)
            sv = edge_sh.pop(kb, 0.0)
            if x != keep_a:
                cluster_nbs[x].add(keep_a)
                cluster_nbs[keep_a].add(x)
                ka = (keep_a, x) if keep_a < x else (x, keep_a)
                if sv > 0.0:
                    edge_sh[ka] = edge_sh.get(ka, 0.0) + sv
        cluster_nbs[keep_a].discard(keep_a)
        cluster_nbs[keep_a].discard(drop_b)

    def synthesis_affinity_fast(a, b, len_a, len_b, area_a, area_b):
        factor = 1.0
        cap_factor = 1.0

        san_a = c_san_s[a] / len_a
        san_b = c_san_s[b] / len_b
        tar_a = c_tar_s[a] / len_a
        tar_b = c_tar_s[b] / len_b
        kon_a = c_kon_s[a] / len_a
        kon_b = c_kon_s[b] / len_b

        # 1. SANAYİ (OSB) BÜTÜNLÜĞÜ VE KESİN İZOLASYONU
        if san_a >= 0.35 and san_b >= 0.35:
            factor *= 0.04
            cap_factor = 0.0
        elif (san_a >= 0.30 and kon_b >= 0.20) or (san_b >= 0.30 and kon_a >= 0.20):
            factor *= 45.0
        elif (san_a >= 0.50 and san_b < 0.10) or (san_b >= 0.50 and san_a < 0.10):
            factor *= 8.0

        # 2. BÜYÜK TARIM OVASI BÜTÜNLÜĞÜ
        if tar_a >= 0.60 and tar_b >= 0.60:
            factor *= 0.08
            cap_factor = 0.0
        elif (tar_a >= 0.50 and san_b >= 0.30) or (tar_b >= 0.50 and san_a >= 0.30):
            factor *= 25.0

        # 3. KONUT BAŞINA DÜŞEN DONATI ORANINA GÖRE ÖLÇEKLENDİRME
        if kon_a >= 0.35 and kon_b >= 0.35:
            don_share = (c_don_s[a] + c_don_s[b]) / (len_a + len_b)
            if don_share < 0.06:
                cap_factor = 2.4
            elif don_share >= 0.14:
                cap_factor = 1.0

        # 4. O(1) MEKÂNSAL KOMPAKTILIK, ENCLAVE & ŞERİT ÖNLEYİCİ
        kab = (a, b) if a < b else (b, a)
        sh_len = edge_sh.get(kab, 0.0)
        pa = c_perim[a]
        pb = c_perim[b]
        min_p = min(pa, pb)
        # Biri diğerinin içine hapsolmuşsa veya >%55 sınırı tek komşudaysa derhal birleştir (Enclave önleme!)
        if min_p > 1.0 and sh_len >= 0.55 * min_p:
            factor *= 0.18

        if w_geo_mult > 0.01:
            min_dim = min(math.sqrt(max(1.0, area_a)), math.sqrt(max(1.0, area_b)))
            p_merged = max(4.0, pa + pb - 2.0 * sh_len)
            pp_a = (4.0 * math.pi * area_a) / max(1.0, pa * pa)
            pp_b = (4.0 * math.pi * area_b) / max(1.0, pb * pb)
            pp_merged = (4.0 * math.pi * (area_a + area_b)) / (p_merged * p_merged)

            if c_mode == "organic":
                if sh_len < 3.0:
                    factor *= (1.0 + 0.6 * w_geo_mult)
                elif sh_len > 0.20 * min_dim:
                    factor *= 0.82
            elif c_mode == "strict":
                if sh_len < 15.0:
                    factor *= (1.0 + 4.5 * w_geo_mult)
                elif sh_len > 0.45 * min_dim:
                    factor *= 0.55
                if pp_merged < 0.24 and min(pp_a, pp_b) > 0.28 and sh_len < 0.15 * min_p:
                    factor *= 3.5
                elif pp_merged > max(pp_a, pp_b) * 1.05:
                    factor *= 0.65
            else:
                if sh_len < 8.0:
                    factor *= (1.0 + 2.0 * w_geo_mult)
                elif sh_len > 0.35 * min_dim:
                    factor *= 0.68
                if pp_merged < 0.20 and min(pp_a, pp_b) > 0.26 and sh_len < 0.12 * min_p:
                    factor *= 2.8
                elif pp_merged > max(pp_a, pp_b) * 1.06:
                    factor *= 0.72

            cxa = c_cx_w[a] / max(1.0, area_a)
            cya = c_cy_w[a] / max(1.0, area_a)
            cxb = c_cx_w[b] / max(1.0, area_b)
            cyb = c_cy_w[b] / max(1.0, area_b)
            dist_cent = math.hypot(cxa - cxb, cya - cyb)
            req = math.sqrt(area_a / math.pi) + math.sqrt(area_b / math.pi)

            if c_mode == "organic":
                if dist_cent > 3.2 * req:
                    factor *= (1.0 + 0.35 * w_geo_mult * (dist_cent / max(1.0, req) - 2.5))
            elif c_mode == "strict":
                if dist_cent > 1.35 * req:
                    factor *= (1.0 + 1.8 * w_geo_mult * (dist_cent / max(1.0, req) - 1.0))
            else:
                if dist_cent > 1.85 * req:
                    factor *= (1.0 + 0.95 * w_geo_mult * (dist_cent / max(1.0, req) - 1.0))

        # 5. MEZARLIK VE BOŞ ARAZİ AYRIMI
        mez_a = c_mez_s[a] / len_a
        mez_b = c_mez_s[b] / len_b
        if mez_a >= 0.35 and mez_b >= 0.35:
            factor *= 0.20
        elif (mez_a >= 0.40 and mez_b < 0.05) or (mez_b >= 0.40 and mez_a < 0.05):
            factor *= 5.0

        if w_bos >= 1.4 or preset_mode in ("integrated_synthesis", "vacant_plan"):
            bos_a = c_bos_s[a] / len_a
            bos_b = c_bos_s[b] / len_b
            if abs(bos_a - bos_b) >= 0.42:
                factor *= (1.0 + 0.45 * min(2.5, w_bos))
            elif (bos_a >= 0.72 and bos_b >= 0.72) or (bos_a <= 0.28 and bos_b <= 0.28):
                factor *= 0.75

        # 6. DONATI ALANLARINA ERİŞİM
        if have.get("donati_erisim") and (w_erisim >= 1.4 or preset_mode in ("integrated_synthesis", "access_school")):
            if c_dm_n[a] > 0 and c_dm_n[b] > 0:
                da = c_dm_s[a] / c_dm_n[a]
                db = c_dm_s[b] / c_dm_n[b]
                if (da <= 500.0 and db >= 850.0) or (db <= 500.0 and da >= 850.0):
                    factor *= 1.85

        return factor, cap_factor

    tick(progress, 70)
    requested_K = int(K)
    node_w = [math.sqrt(a) for a in areas]
    cap = sum(areas) / max(1, requested_K) * P["cap_mult"]
    labels = alg.ward_merge(
        vecs, node_w, areas, adj, requested_K, area_cap=cap,
        cluster_affinity_fn=synthesis_affinity_fast,
        on_merge_fn=on_cluster_merge,
    )
    total_cells_area = max(1.0, sum(areas))
    dyn_mean_zone_area = total_cells_area / max(1, requested_K)
    if filter_medians:
        labels = refine_zone_compactness(
            cells, adj, labels, S, shared_len=shared_len,
            min_keep_area=max(8000.0, 0.42 * dyn_mean_zone_area),
        )
    K = len(set(labels))
    members = defaultdict(list)
    for i, lbl in enumerate(labels):
        members[lbl].append(i)

    tick(progress, 82, "5/7 Alt bölge kimlikleri ve Z-skoru tabanlı dinamik sınır ayrım gerekçeleri hesaplanıyor...", log)
    raw_geoms = []
    zone_ids_list = []
    zone_lbls = sorted(members)
    for lbl in zone_lbls:
        ids = members[lbl]
        u = QgsGeometry.unaryUnion([cells[i] for i in ids])
        if u and not u.isEmpty() and not u.isGeosValid():
            u = u.makeValid()
        raw_geoms.append(u)
        zone_ids_list.append(ids)
    # İlk aşamada yalnızca içinde başka bölge olmayan boş delikleri kapat (enclave'i yutma!)
    clean_geoms = _strip_empty_holes_only(raw_geoms)
    zones = []
    for lbl, ids, geom in zip(zone_lbls, zone_ids_list, clean_geoms):
        if geom and not geom.isEmpty():
            geom = _to_clean_multipolygon(geom)
        zones.append(zone_stats(lbl, ids, geom, S, areas, ext_kinds, allcols=allcols))

    if len(zones) >= 2:
        dyn_tiny_area = min(25000.0, max(5000.0, 0.22 * dyn_mean_zone_area))
        zones = absorb_tiny_residual_zones(
            zones, min_cells=2, min_area=dyn_tiny_area, target_k=requested_K,
            S=S, areas=areas, ext_kinds=ext_kinds, allcols=allcols, prefix=prefix
        )
        # SIFIR ENCLAVE: İç içe veya >= %62 sarılmış tüm ada bölgeleri çevreleyen bölgeye katılır
        zones = eliminate_zone_enclaves_and_nesting(zones, S=S, areas=areas, ext_kinds=ext_kinds, allcols=allcols)
        # SIFIR İNCE UZUN KORİDOR: Şerit ve ince koridor bölgeleri hücre-hücre komşulara dağıtılır
        zones = dissolve_elongated_corridor_zones(zones, cells, adj, labels, S=S, areas=areas, ext_kinds=ext_kinds, allcols=allcols)
        # ÇIKINTI KOL BUDAMA: Sağlam gövdelerden uzanan ince kolları hücre bazında komşulara aktar
        zones = prune_zone_protruding_arms_by_cells(zones, cells, adj, shared_len, S=S, areas=areas, ext_kinds=ext_kinds, allcols=allcols)
        # DAR BOĞAZ BUDAMA: < 36m dar boyun ve kıstırmaları dış sınırları bozmadan kes
        zones = sever_narrow_bottlenecks_and_pinches(zones, cells=cells, min_neck_width=36.0)
        # Yol kuyruğu & yarık temizliği + tek parça garantisi
        prune_zone_road_tails(zones, filter_medians=filter_medians)
        enforce_single_part_contiguous_zones(zones)
        # Enclave ve küçülmüş artıkları son kez temizle
        zones = eliminate_zone_enclaves_and_nesting(zones, S=S, areas=areas, ext_kinds=ext_kinds, allcols=allcols)
        zones = absorb_tiny_residual_zones(
            zones, min_cells=2, min_area=min(18000.0, max(4000.0, 0.18 * dyn_mean_zone_area)),
            target_k=requested_K, S=S, areas=areas, ext_kinds=ext_kinds, allcols=allcols, prefix=prefix
        )

    # NİHAİ SENKRONİZASYON (Ön Geçiş): Bölünme dengesi öncesi ids-geom eşlemesi
    labels = resync_zone_stats_and_labels(
        zones, cells, S, areas, ext_kinds, allcols, res_block_pops, center, prefix
    )

    # HEDEF K SADAKATİ: Temizlik sırasında sayı hedef K'nın altına düştüyse büyük kompakt bölgeleri dengeli böl
    if len(zones) < requested_K and len(cells) >= requested_K:
        before_k = len(zones)
        zones = rebalance_to_target_k(
            zones, requested_K, cells, adj, shared_len, vecs, S, areas, ext_kinds,
            allcols=allcols, prefix=prefix
        )
        if len(zones) > before_k:
            enforce_single_part_contiguous_zones(zones)
            labels = resync_zone_stats_and_labels(
                zones, cells, S, areas, ext_kinds, allcols, res_block_pops, center, prefix
            )
            if log:
                log(f"• Hedef bölge sayısı dengelendi: istenen K={requested_K}, kompakt ve enclavesiz üretilen={len(zones)}")

    _finalize_zone_narratives(zones, P, have, ext_kinds, adj, labels, allcols, mode, connect_isolated=False)

    return {"zones": zones, "cells": cells, "labels": labels, "S": S, "have": have, "center": center,
            "study": study, "work_crs": work_crs, "mode": mode}


def run_custom_zones_pipeline(P, zone_layer, code_field="", log=None, progress=None):
    """
    Kullanıcının halihazırda kendi çizdiği veya sahip olduğu alt bölge poligonlarını (değiştirmeden/bölmeden)
    akıllı bölgeleme sırasında uygulanan tüm mekânsal, morfolojik (Spacematrix, H/W, çıkmaz sokak),
    E×S/AC kırılganlık, sıfır-halüsinasyon kimlik ve ΔZ komşuluk analizleriyle değerlendirir.
    """
    log = log or (lambda *_args, **_kw: None)
    progress = progress or (lambda *_args, **_kw: None)
    work_crs = P["work_crs"]
    mode = P.get("mode", "advanced")

    if work_crs.isGeographic():
        raise RuntimeError("Katmanlar coğrafi (derece) CRS'te. Lütfen metrik bir CRS'e çevirin "
                           "(ör. EPSG:5253 [İzmir / TUREF] veya EPSG:32635) ve tekrar deneyin.")
    if zone_layer is None:
        raise RuntimeError("Hazır bölge poligon katmanı seçilmedi.")

    tick(progress, 5, "1/6 Kullanıcı tarafından sağlanan bölge poligonları ve mevcut durum katmanları okunuyor...", log)
    raw_custom = read_geoms(zone_layer, work_crs)
    if not raw_custom:
        raise RuntimeError("Seçilen hazır bölge katmanında geçerli poligon bulunamadı.")

    cells = []
    zone_codes = []
    seen_codes = Counter()
    for idx_z, (feat, geom) in enumerate(raw_custom):
        if geom.type() != QgsWkbTypes.GeometryType.PolygonGeometry:
            continue
        if not geom.isGeosValid():
            geom = geom.makeValid()
        clean_g = _to_clean_multipolygon(geom)
        if not clean_g or clean_g.isEmpty() or clean_g.area() <= 1.0:
            continue
        raw_code = val(feat, code_field) if code_field else None
        base_code = str(raw_code).strip() if (raw_code is not None and str(raw_code).strip()) else f"B{len(cells) + 1}"
        seen_codes[base_code] += 1
        kod = base_code if seen_codes[base_code] == 1 else f"{base_code}_{seen_codes[base_code]}"
        cells.append(clean_g)
        zone_codes.append(kod)

    n = len(cells)
    if n == 0:
        raise RuntimeError("Hazır bölge katmanından analiz edilebilir poligon çıkarılamadı.")
    log(f"• {n} adet kullanıcı tanımlı bölge poligonu (sınırlar korunarak) analize alındı.")

    blocks, bldgs, roads_fg, study = _load_context_layers(P, log, fallback_study_geoms=cells)
    tick(progress, 20, "2/6 Sağlanan bölge poligonlarının komşuluk ve alan grafı kuruluyor...", log)
    adj, cidx = build_adjacency(cells)
    ccent = [g.centroid().asPoint() for g in cells]
    pts = [(p.x(), p.y()) for p in ccent]
    areas = [g.area() for g in cells]
    labels = list(range(n))

    S, ext_kinds, have, center, res_block_pops, _dens_c, allcols, _colw, _names, _vecs = _measure_cells_and_zscores(
        cells, P, blocks, bldgs, roads_fg, adj, cidx, pts, areas, work_crs, log, progress, is_custom_zones=True
    )

    tick(progress, 75, "5/6 Sağlanan bölgeler için Spacematrix, H/W, Kırılganlık (E×S/AC) ve kimlikler hesaplanıyor...", log)
    zones = []
    for i in range(n):
        z = zone_stats(i, [i], cells[i], S, areas, ext_kinds, allcols=allcols)
        z["kod"] = zone_codes[i]
        zones.append(z)
    if res_block_pops:
        assign_zone_populations_from_blocks(zones, res_block_pops, assign_orphans=False)
        for zi, z in enumerate(zones):
            S[zi]["nufus"] = z["nufus"]

    _assign_zone_spatial_orientation(zones, center)

    _finalize_zone_narratives(zones, P, have, ext_kinds, adj, labels, allcols, mode, connect_isolated=True)
    tick(progress, 95, "6/6 Hazır bölge analiz ve sentez tabloları tamamlandı.", log)

    return {
        "zones": zones,
        "cells": cells,
        "labels": labels,
        "S": S,
        "have": have,
        "center": center,
        "study": study,
        "work_crs": work_crs,
        "mode": mode,
        "is_custom_zones": True,
    }


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


def eliminate_graph_enclaves(cells, adj, labels, shared_len):
    """
    Hücre grafı seviyesinde hiçbir alt bölgenin başka bir bölgenin içinde
    enclave (bir bölgenin içinde bölge) veya derin cep olarak kalmamasını sağlar.
    Dış çalışma sınırı üzerindeki geçerli 3-tarafı açık kenar bölgelerini korumak için
    komşu sınırı oranını yalnızca iç komşulara değil, bileşenin TOPLAM dış geometrik
    çevresine oranlar (%62+ sarılma durumunda komşuya katar).
    """
    labels = list(labels)
    n = len(cells)
    if n <= 3:
        return labels

    cell_perims = [max(1.0, float(g.length())) for g in cells]

    for _round in range(5):
        changed = False
        by_label = defaultdict(list)
        for i, lbl in enumerate(labels):
            by_label[lbl].append(i)

        if len(by_label) <= 2:
            break

        for lbl, node_list in list(by_label.items()):
            node_set = set(node_list)
            visited = set()
            components = []
            for start in node_list:
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
                components.append(comp)

            for comp in components:
                comp_set = set(comp)
                ext_boundary_by_label = defaultdict(float)
                total_ext_contact = 0.0
                internal_shared = 0.0
                comp_perim_sum = 0.0

                for c in comp:
                    comp_perim_sum += cell_perims[c]
                    for nb in adj.get(c, ()):
                        sl = shared_len.get((c, nb), 0.0)
                        if sl <= 0.0:
                            continue
                        if nb in comp_set:
                            if nb > c:
                                internal_shared += sl
                        else:
                            ext_boundary_by_label[labels[nb]] += sl
                            total_ext_contact += sl

                if not ext_boundary_by_label:
                    continue

                comp_ext_perim = max(total_ext_contact, comp_perim_sum - 2.0 * internal_shared, 1.0)
                best_target_lbl, best_len = max(ext_boundary_by_label.items(), key=lambda kv: kv[1])
                enclosure_ratio = best_len / comp_ext_perim

                # Gerçek iç enclave (çevresinin >=%62'si tek komşuyla sarılı) veya çoklu tamamen sarılı mini cep
                is_single_enclave = (enclosure_ratio >= 0.62)
                is_tiny_surrounded = (len(comp) <= 2 and total_ext_contact >= 0.85 * comp_ext_perim and best_len >= 0.48 * comp_ext_perim)

                if is_single_enclave or is_tiny_surrounded:
                    for c in comp:
                        labels[c] = best_target_lbl
                    changed = True

        if not changed:
            break

    return labels


def _removing_cell_keeps_zone_connected(cell_idx, cur_lbl, labels, adj, label_counts):
    """Bir hücreyi kendi bölgesinden çıkarmanın kalan hücrelerin graf bağlantısını bozup bozmadığını O(k) hızlı BFS ile kontrol eder."""
    rem_count = label_counts.get(cur_lbl, 0) - 1
    if rem_count <= 1:
        return True
    cur_nbs = [nb for nb in adj.get(cell_idx, ()) if nb != cell_idx and labels[nb] == cur_lbl]
    if len(cur_nbs) <= 1:
        return True
    start = cur_nbs[0]
    targets = set(cur_nbs[1:])
    visited = {cell_idx, start}
    q = [start]
    while q and targets:
        curr = q.pop()
        for nb in adj.get(curr, ()):
            if nb not in visited and labels[nb] == cur_lbl:
                visited.add(nb)
                targets.discard(nb)
                if not targets:
                    return True
                q.append(nb)
    return len(targets) == 0


def refine_zone_compactness(cells, adj, labels, S, shared_len=None, min_keep_area=18000.0):
    """
    İnce uzun yol şeritlerinin, kopuk adacıkların, çıkıntılı parmak uzantılarının veya dar boğazla bağlı
    hücrelerin bölge bütünlüğünü bozmasını önler; bağlantıyı bozmadan sınır pürüzlülüğünü azaltır.
    Büyük ve kompakt 1-hücreli makro adaları (areas >= min_keep_area) gereksiz yere eritmez.
    """
    n = len(cells)
    if n <= 3:
        return labels
    labels = list(labels)
    perims = [max(1.0, float(g.length())) for g in cells]
    areas = [max(1.0, float(g.area())) for g in cells]
    pps = [(4.0 * math.pi * areas[i]) / (perims[i] * perims[i]) for i in range(n)]
    thicks = [(2.0 * areas[i]) / perims[i] for i in range(n)]

    if shared_len is None:
        c_boxes = [g.boundingBox() for g in cells]
        shared_len = defaultdict(float)
        for i, nbs in adj.items():
            box_i = c_boxes[i]
            for j in nbs:
                if j > i and box_i.intersects(c_boxes[j]):
                    inter = cells[i].intersection(cells[j])
                    slen = inter.length() if inter and not inter.isEmpty() else 0.0
                    if slen > 0.01:
                        shared_len[(i, j)] = slen
                        shared_len[(j, i)] = slen

    labels = _enforce_connected_zone_labels(cells, adj, labels, shared_len)
    labels = eliminate_graph_enclaves(cells, adj, labels, shared_len)

    for _pass in range(5):
        changed = False
        lbl_counts = Counter(labels)
        for i in range(n):
            cur = labels[i]
            by_lbl = defaultdict(float)
            for j in adj.get(i, ()):
                by_lbl[labels[j]] += shared_len.get((i, j), 0.0)
            same_l = by_lbl.get(cur, 0.0)
            other_items = [(lbl, lval) for lbl, lval in by_lbl.items() if lbl != cur and lval > 0.5]
            if not other_items:
                continue
            best_lbl, best_l = max(other_items, key=lambda kv: kv[1])

            if lbl_counts[cur] <= 1:
                # Büyük, yapılaşmış ve kompakt tek-hücreli makro adaları koru; yalnızca küçük/boş/ince olanları em
                if areas[i] < min_keep_area or S[i]["n"] == 0 or pps[i] < 0.24 or thicks[i] < 36.0:
                    labels[i] = best_lbl
                    lbl_counts[cur] -= 1
                    lbl_counts[best_lbl] += 1
                    changed = True
                continue

            is_strip_or_empty = (pps[i] < 0.34 or thicks[i] < 38.0 or S[i]["n"] == 0)
            is_disconnected = (same_l < 0.5 and best_l > 2.0)
            is_narrow_throat = (
                is_strip_or_empty
                and (same_l < 48.0 or same_l < 0.24 * perims[i])
                and best_l > max(same_l * 1.25, 14.0)
            )
            is_surrounded = (best_l > 0.48 * perims[i] and same_l < 0.25 * perims[i])
            is_protruding_tip = (
                same_l < 0.18 * perims[i]
                and best_l > max(same_l * 1.65, 0.30 * perims[i])
                and _removing_cell_keeps_zone_connected(i, cur, labels, adj, lbl_counts)
            )

            if is_disconnected or is_narrow_throat or is_surrounded or is_protruding_tip:
                if not is_disconnected and not _removing_cell_keeps_zone_connected(i, cur, labels, adj, lbl_counts):
                    if not (is_surrounded and lbl_counts[cur] <= 3):
                        continue
                labels[i] = best_lbl
                lbl_counts[cur] -= 1
                lbl_counts[best_lbl] += 1
                changed = True
        if not changed:
            break

    labels = _enforce_connected_zone_labels(cells, adj, labels, shared_len)
    labels = eliminate_graph_enclaves(cells, adj, labels, shared_len)
    labels = _enforce_connected_zone_labels(cells, adj, labels, shared_len)
    return labels


def _strip_vacant_zone_holes(geom, self_idx, zones):
    """
    Yalnızca hiçbir komşu alt bölge tarafından işgal edilmemiş gerçek boş iç delikleri temizler.
    İçinde başka bir alt bölge (enclave) bulunan delikleri korur ki dış bölge iç bölgeyi yutmasın.
    GeometryCollection ve geçersiz poligon türevlerine karşı tamamen dayanıklıdır.
    """
    if geom is None or geom.isEmpty():
        return geom
    other_polys = []
    g_box = geom.boundingBox()
    for j, oz in enumerate(zones):
        if j == self_idx:
            continue
        og = oz.get("geom")
        if og and not og.isEmpty() and og.boundingBox().intersects(g_box):
            other_polys.append(og)
    if not other_polys:
        return _to_clean_multipolygon(strip_polygon_holes(geom))

    parts = _poly_rings_list(geom, min_area=0.01)
    if not parts:
        return _to_clean_multipolygon(geom)
    cleaned = []
    for p in parts:
        if not p or len(p[0]) < 4:
            continue
        kept_rings = [p[0]]
        for ring in p[1:]:
            if len(ring) < 4:
                continue
            hole_poly = QgsGeometry.fromPolygonXY([ring])
            if hole_poly and not hole_poly.isEmpty():
                h_box = hole_poly.boundingBox()
                h_area = max(1.0, hole_poly.area())
                occupied = False
                for og in other_polys:
                    if og.boundingBox().intersects(h_box):
                        inter = hole_poly.intersection(og)
                        if inter and not inter.isEmpty() and inter.area() > 0.05 * h_area:
                            occupied = True
                            break
                if occupied:
                    kept_rings.append(ring)
        cleaned.append(kept_rings)
    if not cleaned:
        return _to_clean_multipolygon(geom)
    out = QgsGeometry.fromMultiPolygonXY(cleaned)
    return _to_clean_multipolygon(out)


def _shared_border_length(g_a, g_b, tol=1.5):
    """İki poligon arasındaki yaklaşık ortak sınır uzunluğunu (m) güvenli hesaplar."""
    if g_a is None or g_b is None or g_a.isEmpty() or g_b.isEmpty():
        return 0.0
    ba = g_a.boundingBox()
    ba.grow(tol + 0.5)
    if not ba.intersects(g_b.boundingBox()):
        return 0.0
    inter = g_a.intersection(g_b)
    if inter and not inter.isEmpty():
        il = inter.length()
        if il > 0.1:
            return float(il)
    b_inter = g_a.buffer(tol, 3).intersection(g_b)
    if b_inter and not b_inter.isEmpty():
        return float(b_inter.area() / max(0.5, tol))
    return 0.0


def enforce_single_part_contiguous_zones(zones, max_passes=5):
    """
    Her alt bolgenin KESINLIKLE tek parca (single contiguous polygon) olmasini garantiler.
    Hicbir bolgenin baska bir yerde ikinci bir kopuk parcasi kalamaz.
    Icindeki dolu enclave deliklerini ise kesinlikle ezmez.
    """
    if len(zones) < 2:
        return
    for _p in range(max_passes):
        any_multi = False
        for i, z in enumerate(zones):
            raw_parts = [p for p in poly_parts(z["geom"]) if p and not p.isEmpty() and p.area() > 5.0]
            parts = [_strip_vacant_zone_holes(p, i, zones) for p in raw_parts]
            parts = [p for p in parts if p and not p.isEmpty() and p.area() > 5.0]
            if len(parts) <= 1:
                if parts:
                    g0 = _to_clean_multipolygon(parts[0])
                    if g0 and not g0.isEmpty():
                        z["geom"] = g0
                        z["area"] = g0.area()
                continue
            any_multi = True
            parts.sort(key=lambda p: p.area(), reverse=True)
            main_part = _to_clean_multipolygon(parts[0])
            if main_part and not main_part.isEmpty():
                z["geom"] = main_part
                z["area"] = main_part.area()

            for extra in parts[1:]:
                best_j = -1
                best_score = -1.0
                for j, oz in enumerate(zones):
                    if j == i:
                        continue
                    score = _shared_border_length(extra, oz["geom"], tol=3.0)
                    if score > best_score and score > 0.1:
                        best_score = score
                        best_j = j
                if best_j < 0:
                    min_dist = float("inf")
                    for j, oz in enumerate(zones):
                        if j == i:
                            continue
                        d = extra.distance(oz["geom"])
                        if d < min_dist:
                            min_dist = d
                            best_j = j
                if best_j >= 0:
                    ug = QgsGeometry.unaryUnion([zones[best_j]["geom"], extra])
                    if ug and not ug.isEmpty():
                        ug = _to_clean_multipolygon(_strip_vacant_zone_holes(ug, best_j, zones))
                        if ug and not ug.isEmpty():
                            zones[best_j]["geom"] = ug
                            zones[best_j]["area"] = ug.area()
        if not any_multi:
            break


def _reassign_minor_disconnected_parts(zones):
    """Geriye donuk uyumluluk shimi: enforce_single_part_contiguous_zones cagirir."""
    enforce_single_part_contiguous_zones(zones)


def _heal_inward_slits_and_holes(zones, close_m=8.0):
    """
    Bolge poligonlarinin icine dogru saplanan bos yariklari (slit/crack) ve bos delikleri
    komsu bolgelere tasmadan doldurur. Dolu komsu/enclave alanlarini kesinlikle ezmez.
    """
    for i, z in enumerate(zones):
        g = _strip_vacant_zone_holes(z["geom"], i, zones)
        if g is None or g.isEmpty():
            continue
        closed = g.buffer(close_m, 6).buffer(-close_m, 6)
        if closed is not None and not closed.isEmpty():
            closed = _strip_vacant_zone_holes(closed, i, zones)
            diff = closed.difference(g)
            if diff is not None and not diff.isEmpty():
                slits = []
                for sp in poly_parts(diff):
                    sa = sp.area()
                    slen = sp.length()
                    if sa <= 0.5 or slen <= 0.0:
                        continue
                    s_thick = (2.0 * sa) / slen
                    if s_thick < (close_m * 2.1):
                        slits.append(sp)
                if slits:
                    slit_u = QgsGeometry.unaryUnion(slits)
                    s_box = slit_u.boundingBox()
                    others = [
                        oz["geom"] for j, oz in enumerate(zones)
                        if j != i and oz["geom"] and oz["geom"].boundingBox().intersects(s_box)
                    ]
                    if others:
                        slit_u = slit_u.difference(QgsGeometry.unaryUnion(others))
                    if slit_u and not slit_u.isEmpty() and slit_u.area() > 0.5:
                        g = QgsGeometry.unaryUnion([g, slit_u])
        if g and not g.isEmpty():
            g = _to_clean_multipolygon(_strip_vacant_zone_holes(g, i, zones))
            if g and not g.isEmpty():
                z["geom"] = g
                z["area"] = g.area()


def prune_zone_road_tails(zones, filter_medians=True):
    """
    Alt bolge poligonlarinda:
    1) Bos ic delikleri ve kopuk adaciklari temizler,
    2) Disariya dogru uzanan ince yol koridoru kuyruklarini / sivri burunlari budar;
       bunu yaparken duzgun dis kose pahlarini kesmez (kesim boynundan daha uzun
       komsu ortak siniri olan gercek cıkıntıları komsuya devreder),
    3) Bos ince yariklari kapatir.
    """
    for i, z in enumerate(zones):
        g = _to_clean_multipolygon(_strip_vacant_zone_holes(z["geom"], i, zones))
        if g and not g.isEmpty():
            z["geom"] = g
            z["area"] = g.area()

    enforce_single_part_contiguous_zones(zones)

    if filter_medians:
        for i, z in enumerate(zones):
            g = _to_clean_multipolygon(_strip_vacant_zone_holes(z["geom"], i, zones))
            if g is None or g.isEmpty():
                continue
            z_area = g.area()
            if z_area < 15000.0:
                continue
            opened = g.buffer(-18.0, 6).buffer(20.0, 6)
            if opened is None or opened.isEmpty() or opened.area() < 0.35 * z_area:
                continue
            diff = g.difference(opened)
            if diff is None or diff.isEmpty():
                continue
            tails_to_remove = []
            for part in poly_parts(diff):
                pa = part.area()
                plen = part.length()
                if pa < 40.0 or plen <= 0.0 or pa > 0.35 * z_area:
                    continue
                p_thick = (2.0 * pa) / plen
                p_pp = (4.0 * math.pi * pa) / (plen * plen)
                if p_thick >= 34.0 or (p_pp >= 0.42 and p_thick >= 22.0):
                    continue
                cut_len = _shared_border_length(part, opened, tol=1.0)
                best_j = -1
                best_nb_len = 0.0
                for j, oz in enumerate(zones):
                    if j == i:
                        continue
                    nb_len = _shared_border_length(part, oz["geom"], tol=2.0)
                    if nb_len > best_nb_len:
                        best_nb_len = nb_len
                        best_j = j
                # Yalnızca kesim boynundan belirgin şekilde uzun bir kenarıyla komşuya yaslanan gerçek çıkıntıları buda (dış köşeleri kesme)
                if best_j >= 0 and best_nb_len >= max(20.0, 1.25 * cut_len):
                    tails_to_remove.append((part, best_j))
            if tails_to_remove:
                rem_union = QgsGeometry.unaryUnion([t[0] for t in tails_to_remove])
                new_g = g.difference(rem_union)
                if new_g and not new_g.isEmpty() and new_g.area() > 0.45 * z_area:
                    new_g = _to_clean_multipolygon(_strip_vacant_zone_holes(new_g, i, zones))
                    if new_g and not new_g.isEmpty():
                        z["geom"] = new_g
                        z["area"] = new_g.area()
                    for part, best_j in tails_to_remove:
                        ug = QgsGeometry.unaryUnion([zones[best_j]["geom"], part])
                        if ug and not ug.isEmpty():
                            ug = _to_clean_multipolygon(_strip_vacant_zone_holes(ug, best_j, zones))
                            if ug and not ug.isEmpty():
                                zones[best_j]["geom"] = ug
                                zones[best_j]["area"] = ug.area()

    _heal_inward_slits_and_holes(zones, close_m=8.0)
    enforce_single_part_contiguous_zones(zones)
    for i, z in enumerate(zones):
        g = _to_clean_multipolygon(_strip_vacant_zone_holes(z["geom"], i, zones))
        if g and not g.isEmpty():
            z["geom"] = g
            z["area"] = g.area()


def absorb_tiny_residual_zones(zones, min_cells=2, min_area=20000.0, target_k=None, S=None, areas=None, ext_kinds=None, allcols=None, prefix="M"):
    """
    1 hücrelik veya aşırı küçük kalmış mikroskobik artık bölgeleri en uzun sınır paylaştığı
    baskın komşu bölgeye katar ve bölgeleri ardışık (M1..MK / A1..AK) yeniden numaralandırır.
    Yüksek hedef K veya büyük makro adalar söz konusu olduğunda büyük 1-2 hücreli bölgeleri korur.
    """
    if len(zones) <= 2:
        return zones

    eff_k = max(len(zones), int(target_k or len(zones)))
    total_area = sum(z["area"] for z in zones)
    mean_area = total_area / max(1, len(zones))
    target_mean = total_area / max(1, eff_k)
    area_thresh = min(min_area, 0.24 * target_mean)

    absorbed_any = True
    while absorbed_any and len(zones) > 2:
        absorbed_any = False
        for i, z in enumerate(zones):
            n_cells = len(z.get("ids", []))
            z_area = z.get("area", 0.0)
            # Büyük çok-hektarlı tek/çift adaları sadece cell sayısı az diye yok etme; yalnızca alanı küçük artıkları em
            is_micro = (
                z_area < area_thresh
                or (n_cells < min_cells and z_area < max(area_thresh * 1.4, 0.35 * target_mean))
            )
            if not is_micro:
                continue

            best_j = -1
            best_sh = -1.0
            for j, oz in enumerate(zones):
                if j == i:
                    continue
                sh = _shared_border_length(z["geom"], oz["geom"], tol=3.0)
                if sh > best_sh and sh > 0.1:
                    best_sh = sh
                    best_j = j
            if best_j < 0:
                min_d = float("inf")
                for j, oz in enumerate(zones):
                    if j == i:
                        continue
                    d = z["geom"].distance(oz["geom"])
                    if d < min_d:
                        min_d = d
                        best_j = j

            if best_j >= 0:
                target_z = zones[best_j]
                target_z["ids"] = sorted(set(target_z["ids"] + z.get("ids", [])))
                merged_geom = QgsGeometry.unaryUnion([target_z["geom"], z["geom"]])
                if merged_geom and not merged_geom.isEmpty():
                    merged_geom = _to_clean_multipolygon(_strip_vacant_zone_holes(merged_geom, best_j, zones))
                    if merged_geom and not merged_geom.isEmpty():
                        target_z["geom"] = merged_geom
                        target_z["area"] = merged_geom.area()
                target_z["pop"] = target_z.get("pop", 0) + z.get("pop", 0)
                if S is not None and areas is not None and ext_kinds is not None:
                    new_st = zone_stats(target_z["l"], target_z["ids"], target_z["geom"], S, areas, ext_kinds, allcols=allcols)
                    target_z.update(new_st)
                zones.pop(i)
                absorbed_any = True
                break

    for idx, z in enumerate(zones):
        new_kodu = f"{prefix}{idx + 1}"
        z["l"] = idx
        z["kod"] = new_kodu
        z["name"] = new_kodu

    return zones


def eliminate_zone_enclaves_and_nesting(zones, S=None, areas=None, ext_kinds=None, allcols=None):
    """
    Geometrik seviyede hiçbir alt bölgenin başka bir bölgenin içinde ada (enclave / donut hole)
    olarak kalmamasını kesinleştirir (Görsel 1'deki M11'in M12 içinde kalması hatasını önler).
    Dış çalışma sınırındaki 3-tarafı açık geçerli kenar bölgelerini korur: sadece dış halka içine
    hapsedilmiş bölgeleri veya kendi çevresinin >=%62'si tek komşuyla temas eden iç/cep bölgelerini birleştirir.
    """
    if len(zones) <= 2:
        return zones

    absorbed_any = True
    while absorbed_any and len(zones) > 2:
        absorbed_any = False
        for i in range(len(zones)):
            zi = zones[i]
            gi = zi["geom"]
            if gi is None or gi.isEmpty():
                continue
            gi_perim = max(1.0, float(gi.length()))
            gi_area = max(1.0, float(gi.area()))
            try:
                pt_i = gi.pointOnSurface()
            except Exception:
                pt_i = gi.centroid()

            for j in range(len(zones)):
                if i == j:
                    continue
                zj = zones[j]
                gj = zj["geom"]
                if gj is None or gj.isEmpty():
                    continue

                b_j = gj.boundingBox()
                b_j.grow(4.0)
                if not b_j.intersects(gi.boundingBox()):
                    continue

                # Kontrol 1: gi merkezi gj'nin dış halka poligonlarından birinin içinde kalıyor mu? (Enclave / İç Cep)
                is_nested = False
                try:
                    for rings in _poly_rings_list(gj):
                        if rings:
                            outer_poly_j = QgsGeometry.fromPolygonXY([rings[0]])
                            if outer_poly_j and not outer_poly_j.isEmpty() and outer_poly_j.area() > gi_area:
                                if pt_i and outer_poly_j.contains(pt_i):
                                    is_nested = True
                                    break
                except Exception:
                    pass

                # Kontrol 2: gi'nin KENDİ toplam çevresinin >=%62'si tek komşu gj ile sarılı mı?
                # (Geçerli 3-tarafı çalışma dışı kenar bölgelerinde bu oran ~0.20-0.45 kalır ve korunur!)
                sh_len = _shared_border_length(gi, gj, tol=3.0)
                enclosure_ratio = sh_len / gi_perim

                if is_nested or enclosure_ratio >= 0.62:
                    merged_raw = QgsGeometry.unaryUnion([gj, gi])
                    zj["ids"] = sorted(set(zj.get("ids", []) + zi.get("ids", [])))
                    zj["pop"] = zj.get("pop", 0) + zi.get("pop", 0)
                    zones.pop(i)
                    target_idx = j - 1 if j > i else j
                    if merged_raw and not merged_raw.isEmpty():
                        merged_g = _to_clean_multipolygon(_strip_vacant_zone_holes(merged_raw, target_idx, zones))
                        if merged_g and not merged_g.isEmpty():
                            zj["geom"] = merged_g
                            zj["area"] = merged_g.area()
                    if S is not None and areas is not None and ext_kinds is not None:
                        new_st = zone_stats(zj["l"], zj["ids"], zj["geom"], S, areas, ext_kinds, allcols=allcols)
                        zj.update(new_st)
                        zj["area"] = zj["geom"].area()
                    absorbed_any = True
                    break
            if absorbed_any:
                break

    return zones


def _zone_geometry_elongation_metrics(g):
    """
    Döndürmeden bağımsız kompaktlık ve uzunluk/incelik metrikleri üretir:
    - Oriented Minimum Bounding Box (OMBB) ile diyagonal şeritleri yakalar (Görsel 2 M13)
    - Pole of Inaccessibility ile L/C kıvrımlı kenar koridorlarını yakalar (Görsel 2 batı koridoru)
    """
    z_area = max(1.0, float(g.area()))
    z_perim = max(1.0, float(g.length()))
    pp = (4.0 * math.pi * z_area) / (z_perim * z_perim)
    thickness = (2.0 * z_area) / z_perim

    rot_aspect = 1.0
    rot_w = thickness
    rect_fill = 1.0
    try:
        obb = g.orientedMinimumBoundingBox()
        if obb and len(obb) >= 5:
            obb_area = max(1.0, float(obb[1]))
            w_dim = max(1.0, float(obb[3]))
            h_dim = max(1.0, float(obb[4]))
            rot_w = min(w_dim, h_dim)
            rot_l = max(w_dim, h_dim)
            rot_aspect = rot_l / max(1.0, rot_w)
            rect_fill = z_area / obb_area
    except Exception:
        bbox = g.boundingBox()
        rot_w = max(1.0, min(bbox.width(), bbox.height()))
        rot_l = max(1.0, max(bbox.width(), bbox.height()))
        rot_aspect = rot_l / rot_w
        rect_fill = z_area / max(1.0, bbox.width() * bbox.height())

    max_inscribed_r = thickness * 0.5
    try:
        pole_res = g.poleOfInaccessibility(2.5)
        if pole_res and len(pole_res) >= 2 and pole_res[1] > 0:
            max_inscribed_r = float(pole_res[1])
    except Exception:
        pass
    core_width = 2.0 * max_inscribed_r
    skel_elong = z_perim / max(1.0, 4.0 * max_inscribed_r)

    return {
        "area": z_area,
        "perim": z_perim,
        "pp": pp,
        "thickness": thickness,
        "rot_w": rot_w,
        "rot_aspect": rot_aspect,
        "rect_fill": rect_fill,
        "core_width": core_width,
        "skel_elong": skel_elong,
    }


def dissolve_elongated_corridor_zones(zones, cells, adj, labels, S=None, areas=None, ext_kinds=None, allcols=None):
    """
    Görsel 2'deki hem eğik/diyagonal koridorları (M13 gibi) hem kıvrımlı kenar şeritlerini (batı şeridi)
    OMBB + Pole of Inaccessibility ile yakalar ve wavefront komşu yayılımıyla hücre-hücre dağıtarak eritir.
    """
    if len(zones) <= 2:
        return zones

    mean_area = sum(z["area"] for z in zones) / max(1, len(zones))

    dissolved_any = True
    while dissolved_any and len(zones) > 2:
        dissolved_any = False
        for i, z in enumerate(zones):
            g = z["geom"]
            if g is None or g.isEmpty():
                continue

            m = _zone_geometry_elongation_metrics(g)
            z_area = m["area"]

            is_elongated = (
                (m["thickness"] < 55.0 and m["pp"] < 0.26)
                or (m["rot_aspect"] > 3.1 and m["rot_w"] < 95.0 and m["pp"] < 0.31)
                or (m["core_width"] < 68.0 and m["skel_elong"] > 4.2)
                or (m["pp"] < 0.24 and m["rect_fill"] < 0.44 and m["core_width"] < 85.0)
                or (m["pp"] < 0.16 and z_area < 0.65 * mean_area)
            )

            if not is_elongated:
                continue

            z_cells = list(z.get("ids", []))
            if not z_cells:
                continue

            # Komşu bölge haritası
            owner_by_cid = {}
            neighbor_indices = set()
            g_box = g.boundingBox()
            g_box.grow(8.0)
            for j, oz in enumerate(zones):
                if j == i:
                    continue
                for c in oz.get("ids", []):
                    owner_by_cid[c] = j
                if oz["geom"] and oz["geom"].boundingBox().intersects(g_box):
                    if _shared_border_length(g, oz["geom"], tol=3.0) > 1.0:
                        neighbor_indices.add(j)

            if not neighbor_indices:
                neighbor_indices = set(j for j in range(len(zones)) if j != i)
            if not neighbor_indices:
                continue

            # Wavefront (dıştan içe) bitişik hücre devri: bölge parçalanmasını önler
            remaining = set(z_cells)
            reassigned = defaultdict(list)
            while remaining:
                progressed = False
                best_moves = []
                for cid in list(remaining):
                    nb_scores = defaultdict(float)
                    for nb in adj.get(cid, ()):
                        oj = owner_by_cid.get(nb)
                        if oj is not None and oj != i:
                            inter = cells[cid].intersection(cells[nb])
                            nb_scores[oj] += max(0.5, inter.length() if inter and not inter.isEmpty() else 0.5)
                    if nb_scores:
                        best_j = max(nb_scores.items(), key=lambda kv: kv[1])[0]
                        best_moves.append((cid, best_j, nb_scores[best_j]))
                if best_moves:
                    # En güçlü sınır temasına sahip cepheyi önce aktar
                    best_moves.sort(key=lambda x: x[2], reverse=True)
                    for cid, best_j, _ in best_moves:
                        remaining.discard(cid)
                        owner_by_cid[cid] = best_j
                        reassigned[best_j].append(cid)
                    progressed = True
                if not progressed:
                    # Graf kopuksa doğrudan geometri sınır uzunluğu / en yakın mesafeyle kalanları aktar
                    for cid in list(remaining):
                        cg = cells[cid]
                        best_j = -1
                        best_len = -1.0
                        for j in neighbor_indices:
                            sh_l = _shared_border_length(cg, zones[j]["geom"], tol=2.0)
                            if sh_l > best_len:
                                best_len = sh_l
                                best_j = j
                        if best_j < 0 or best_len <= 0.1:
                            best_j = min(neighbor_indices, key=lambda j: cg.distance(zones[j]["geom"]))
                        remaining.discard(cid)
                        reassigned[best_j].append(cid)
                    break

            target_zones = []
            for j, cids in reassigned.items():
                if not cids:
                    continue
                target_z = zones[j]
                target_z["ids"] = sorted(set(target_z.get("ids", []) + cids))
                added_u = QgsGeometry.unaryUnion([cells[c] for c in cids])
                new_g = QgsGeometry.unaryUnion([target_z["geom"], added_u])
                target_zones.append((j, target_z, new_g))

            zones.pop(i)
            for orig_j, target_z, new_g in target_zones:
                adj_j = orig_j - 1 if orig_j > i else orig_j
                if new_g and not new_g.isEmpty():
                    new_g = _to_clean_multipolygon(_strip_vacant_zone_holes(new_g, adj_j, zones))
                    if new_g and not new_g.isEmpty():
                        target_z["geom"] = new_g
                        target_z["area"] = new_g.area()
                if S is not None and areas is not None and ext_kinds is not None:
                    new_st = zone_stats(target_z["l"], target_z["ids"], target_z["geom"], S, areas, ext_kinds, allcols=allcols)
                    target_z.update(new_st)
                    target_z["area"] = target_z["geom"].area()

            dissolved_any = True
            break

    return zones


def _zone_ids_stay_connected_after_drop(drop_cid, z_id_set, adj):
    """drop_cid çıkarıldığında kalan z_id_set hücrelerinin graf üzerinde bağlantılı kalıp kalmadığını kontrol eder."""
    rem = z_id_set - {drop_cid}
    if len(rem) <= 1:
        return True
    cur_nbs = [nb for nb in adj.get(drop_cid, ()) if nb in rem]
    if len(cur_nbs) <= 1:
        return len(cur_nbs) == 1
    start = cur_nbs[0]
    targets = set(cur_nbs[1:])
    visited = {start}
    q = [start]
    while q and targets:
        curr = q.pop()
        for nb in adj.get(curr, ()):
            if nb in rem and nb not in visited:
                visited.add(nb)
                targets.discard(nb)
                if not targets:
                    return True
                q.append(nb)
    return len(targets) == 0


def prune_zone_protruding_arms_by_cells(zones, cells, adj, shared_len, S=None, areas=None, ext_kinds=None, allcols=None):
    """
    Kompakt gövdelerden dışarı uzanan ince parmak/çıkıntı kolları hücre bazında bağlantıyı bozmadan
    en uzun sınır paylaştığı komşuya devreder.
    """
    if len(zones) < 2 or not cells:
        return zones

    n_cells = len(cells)
    cell_perims = [max(1.0, float(g.length())) for g in cells]
    cell_areas = [max(1.0, float(g.area())) for g in cells]
    cell_thicks = [(2.0 * cell_areas[i]) / cell_perims[i] for i in range(n_cells)]
    cell_pps = [(4.0 * math.pi * cell_areas[i]) / (cell_perims[i] * cell_perims[i]) for i in range(n_cells)]

    cell_owner = {}
    for idx_z, z in enumerate(zones):
        for cid in z.get("ids", []):
            cell_owner[cid] = idx_z

    changed_zones = set()
    for _pass in range(3):
        moved_any = False
        for idx_z, z in enumerate(zones):
            z_ids = set(z.get("ids", []))
            if len(z_ids) < 4 or z.get("area", 0.0) < 25000.0:
                continue
            max_transfers = max(1, int(0.20 * len(z_ids)))
            transfers = 0
            for cid in list(z_ids):
                if cid not in z_ids or transfers >= max_transfers or len(z_ids) < 4:
                    break
                same_l = 0.0
                nb_l_by_z = defaultdict(float)
                for nb in adj.get(cid, ()):
                    sl = shared_len.get((cid, nb), 0.0)
                    if sl <= 0.0:
                        continue
                    oz_idx = cell_owner.get(nb)
                    if oz_idx == idx_z:
                        same_l += sl
                    elif oz_idx is not None:
                        nb_l_by_z[oz_idx] += sl
                if not nb_l_by_z:
                    continue
                best_oz, best_nb_l = max(nb_l_by_z.items(), key=lambda kv: kv[1])
                c_p = cell_perims[cid]

                is_arm_tip = (same_l <= 0.24 * c_p and best_nb_l >= max(same_l * 1.45, 0.28 * c_p))
                is_thin_finger = (
                    (cell_thicks[cid] < 42.0 and cell_pps[cid] < 0.36)
                    and best_nb_l > max(same_l * 1.25, 0.20 * c_p)
                )
                if not (is_arm_tip or is_thin_finger):
                    continue
                if not _zone_ids_stay_connected_after_drop(cid, z_ids, adj):
                    continue

                z_ids.remove(cid)
                cell_owner[cid] = best_oz
                zones[idx_z]["ids"] = sorted(z_ids)
                zones[best_oz]["ids"] = sorted(set(zones[best_oz].get("ids", [])) | {cid})
                changed_zones.add(idx_z)
                changed_zones.add(best_oz)
                transfers += 1
                moved_any = True
        if not moved_any:
            break

    for idx_z in sorted(changed_zones):
        z = zones[idx_z]
        if not z.get("ids"):
            continue
        u = QgsGeometry.unaryUnion([cells[c] for c in z["ids"]])
        if u and not u.isEmpty():
            u = _to_clean_multipolygon(_strip_vacant_zone_holes(u, idx_z, zones))
            if u and not u.isEmpty():
                z["geom"] = u
                z["area"] = u.area()
        if S is not None and areas is not None and ext_kinds is not None:
            new_st = zone_stats(z["l"], z["ids"], z["geom"], S, areas, ext_kinds, allcols=allcols)
            z.update(new_st)
            z["area"] = z["geom"].area()

    return zones


def sever_narrow_bottlenecks_and_pinches(zones, cells=None, min_neck_width=36.0):
    """
    Görsel 3'teki gibi başka bir bölgeyi (ör. M7) saran dar boğazları (narrow neck / pinch)
    ve 36 metreden ince bağlantı köprülerini tespit eder; dış köşeleri veya kenarları YUVARLAMADAN
    ve boşluk BIRAKMADAN g üzerinde kesin partition kesimi yaparak kopan kolu komşuya devreder.
    """
    if len(zones) < 2:
        return zones

    r = min_neck_width / 2.0
    for _pass in range(2):
        severed_any = False
        for i, z in enumerate(zones):
            g = z["geom"]
            if g is None or g.isEmpty() or z["area"] < 4000.0:
                continue

            eroded = g.buffer(-r, 6)
            if eroded is None or eroded.isEmpty():
                continue

            cores = [p for p in poly_parts(eroded) if p and not p.isEmpty() and p.area() > 400.0]
            if len(cores) <= 1:
                continue

            cores.sort(key=lambda p: p.area(), reverse=True)
            main_core = cores[0]
            sev_cores = cores[1:]
            main_guard = main_core.buffer(r * 1.02, 6)

            work_g = g
            transferred = []
            for s_core in sev_cores:
                reach = s_core.buffer(r * 2.2, 6).intersection(work_g)
                if reach is None or reach.isEmpty():
                    continue
                cand = reach.difference(main_guard)
                if cand is None or cand.isEmpty():
                    continue
                s_core_buf = s_core.buffer(2.0, 3)
                kept_parts = [
                    pp for pp in poly_parts(cand)
                    if pp and not pp.isEmpty() and pp.area() > 50.0 and pp.intersects(s_core_buf)
                ]
                if not kept_parts:
                    continue
                sev_exact = QgsGeometry.unaryUnion(kept_parts)
                if sev_exact is None or sev_exact.isEmpty():
                    continue

                best_j = -1
                best_sh = 0.0
                for j, oz in enumerate(zones):
                    if j == i:
                        continue
                    sh = _shared_border_length(sev_exact, oz["geom"], tol=3.0)
                    if sh > best_sh:
                        best_sh = sh
                        best_j = j

                if best_j >= 0 and best_sh >= 15.0:
                    rem = work_g.difference(sev_exact)
                    if rem and not rem.isEmpty() and rem.area() > 0.35 * g.area():
                        # Ana çekirdeğe bağlı tek parça bırak; boyundan kopan mini artık varsa sev_exact'e ekle
                        rem_parts = [pp for pp in poly_parts(rem) if pp and not pp.isEmpty() and pp.area() > 2.0]
                        main_kept = [pp for pp in rem_parts if pp.intersects(main_core)]
                        stray_parts = [pp for pp in rem_parts if not pp.intersects(main_core)]
                        if main_kept:
                            work_g = QgsGeometry.unaryUnion(main_kept)
                            for sp in stray_parts:
                                if _shared_border_length(sp, sev_exact, tol=2.0) > 1.0:
                                    sev_exact = QgsGeometry.unaryUnion([sev_exact, sp])
                                else:
                                    work_g = QgsGeometry.unaryUnion([work_g, sp])
                            transferred.append((sev_exact, best_j))

            if transferred:
                work_g = _to_clean_multipolygon(_strip_vacant_zone_holes(work_g, i, zones))
                if work_g and not work_g.isEmpty():
                    z["geom"] = work_g
                    z["area"] = work_g.area()
                for sev_exact, best_j in transferred:
                    ug = QgsGeometry.unaryUnion([zones[best_j]["geom"], sev_exact])
                    if ug and not ug.isEmpty():
                        ug = _to_clean_multipolygon(_strip_vacant_zone_holes(ug, best_j, zones))
                        if ug and not ug.isEmpty():
                            zones[best_j]["geom"] = ug
                            zones[best_j]["area"] = ug.area()
                severed_any = True
        if not severed_any:
            break

    return zones


def _assign_zone_spatial_orientation(zones, center):
    """Her alt bölgeye kent merkezine göre yön, mesafe ve merkezilik skoru atar."""
    max_dist = 1.0
    coords = []
    for z in zones:
        g = z["geom"]
        try:
            pt = g.pointOnSurface().asPoint()
        except Exception:
            pt = g.centroid().asPoint()
        cx, cy = pt.x(), pt.y()
        dist_c = math.hypot(cx - center[0], cy - center[1])
        if dist_c > max_dist:
            max_dist = dist_c
        coords.append((cx, cy, dist_c))

    for idx, z in enumerate(zones):
        cx, cy, dist_c = coords[idx]
        z["cx"], z["cy"], z["dist_c"] = cx, cy, dist_c
        ang = math.degrees(math.atan2(cy - center[1], cx - center[0])) % 360.0
        dir_idx = int((ang + 22.5) // 45.0) % 8
        z["dir"] = dir_idx
        z["dir_name"] = "Merkez" if dist_c < 0.18 * max_dist else DIR_NAMES[dir_idx]
        z["merkez"] = max(0.0, 1.0 - dist_c / max(1.0, max_dist))
        z["pop"] = z.get("nufus", 0.0)


def resync_zone_stats_and_labels(zones, cells, S, areas, ext_kinds, allcols, res_block_pops, center, prefix):
    """
    Tüm geometrik temizliklerden (enclave, koridor, boğaz kesimi) sonra her hücreyi kesin geometrik
    sahibine bağlar; z['ids'], z['area'], z['taks'], z['ndens'], z['nufus'], konum/yön ve labels
    listesini %100 senkronize eder.
    """
    zones[:] = [z for z in zones if z.get("geom") is not None and not z["geom"].isEmpty() and z["geom"].area() > 10.0]
    if not zones:
        return [0] * len(cells)

    z_boxes = [z["geom"].boundingBox() for z in zones]
    z_engines = []
    for z in zones:
        eng = QgsGeometry.createGeometryEngine(z["geom"].constGet())
        eng.prepareGeometry()
        z_engines.append(eng)

    new_zone_ids = [[] for _ in range(len(zones))]
    raw_labels = [0] * len(cells)

    for cid, cg in enumerate(cells):
        c_box = cg.boundingBox()
        cands = [zi for zi, zb in enumerate(z_boxes) if zb.intersects(c_box)]
        if not cands:
            best_zi = min(range(len(zones)), key=lambda zi: cg.distance(zones[zi]["geom"]))
        elif len(cands) == 1:
            best_zi = cands[0]
        else:
            best_zi = -1
            try:
                pt = cg.pointOnSurface()
            except Exception:
                pt = cg.centroid()
            if pt and not pt.isEmpty():
                for zi in cands:
                    if z_engines[zi].contains(pt.constGet()):
                        best_zi = zi
                        break
            if best_zi < 0:
                best_area = -1.0
                for zi in cands:
                    inter = cg.intersection(zones[zi]["geom"])
                    ia = inter.area() if inter and not inter.isEmpty() else 0.0
                    if ia > best_area:
                        best_area = ia
                        best_zi = zi
            if best_zi < 0:
                best_zi = min(cands, key=lambda zi: cg.distance(zones[zi]["geom"]))

        new_zone_ids[best_zi].append(cid)
        raw_labels[cid] = best_zi

    # Hücresiz kalan hayalet/ince şerit bölge oluştuysa birleştir
    kept_zones = []
    old_to_new = {}
    for zi, z in enumerate(zones):
        if new_zone_ids[zi]:
            old_to_new[zi] = len(kept_zones)
            z["ids"] = sorted(new_zone_ids[zi])
            kept_zones.append(z)
        else:
            if zones:
                other_idxs = [k for k in range(len(zones)) if k != zi and new_zone_ids[k]]
                if other_idxs:
                    best_k = max(other_idxs, key=lambda k: _shared_border_length(z["geom"], zones[k]["geom"], tol=3.0))
                    ug = QgsGeometry.unaryUnion([zones[best_k]["geom"], z["geom"]])
                    ug = _to_clean_multipolygon(ug)
                    if ug and not ug.isEmpty():
                        zones[best_k]["geom"] = ug
                        zones[best_k]["area"] = ug.area()

    zones[:] = kept_zones
    labels = [old_to_new.get(raw_labels[cid], 0) for cid in range(len(cells))]

    for idx, z in enumerate(zones):
        saved_geom = z["geom"]
        st = zone_stats(idx, z["ids"], saved_geom, S, areas, ext_kinds, allcols=allcols)
        z.update(st)
        z["geom"] = saved_geom
        geom_area = float(saved_geom.area())
        z["area"] = geom_area
        if geom_area > 0.0:
            z["taks"] = min(1.0, z["barea"] / geom_area)
            z["ndens"] = z["n"] / (geom_area / 10000.0)
        z["l"] = idx
        z["kod"] = f"{prefix}{idx + 1}"
        z["name"] = z["kod"]

    _assign_zone_spatial_orientation(zones, center)
    assign_zone_populations_from_blocks(zones, res_block_pops)
    for z in zones:
        z["pop"] = z.get("nufus", 0.0)
        act_don = z.get("active_donati_m2", 0.0)
        z["kisi_basi_donati_m2"] = (act_don / z["nufus"]) if z.get("nufus", 0.0) >= 10.0 else None
        z["vuln"] = compute_vulnerability(z)

    return labels


def _is_induced_connected(id_set, adj):
    """id_set düğümlerinin adj üzerinde tek bir bağlantılı bileşen oluşturup oluşturmadığını kontrol eder."""
    if len(id_set) <= 1:
        return True
    start = next(iter(id_set))
    visited = {start}
    stack = [start]
    while stack:
        curr = stack.pop()
        for nb in adj.get(curr, ()):
            if nb in id_set and nb not in visited:
                visited.add(nb)
                stack.append(nb)
    return len(visited) == len(id_set)


def _repair_bipartition_connectivity(A_init, B_init, z_ids, adj, areas, shared_len):
    """İki parçalı hücre ayrımında kopuk alt bileşen kalırsa komşuluk üzerinden ana çekirdeklere bağlar."""
    z_set = set(z_ids)

    def _largest_comp(subset):
        if not subset:
            return set()
        seen = set()
        best_c = set()
        best_area = -1.0
        for s in subset:
            if s in seen:
                continue
            comp = {s}
            seen.add(s)
            q = [s]
            c_area = areas[s]
            while q:
                u = q.pop()
                for nb in adj.get(u, ()):
                    if nb in subset and nb not in seen:
                        seen.add(nb)
                        comp.add(nb)
                        c_area += areas[nb]
                        q.append(nb)
            if c_area > best_area:
                best_area = c_area
                best_c = comp
        return best_c

    core_A = _largest_comp(set(A_init) & z_set)
    core_B = _largest_comp((set(B_init) & z_set) - core_A)
    if not core_A or not core_B:
        return None, None

    rem = z_set - core_A - core_B
    while rem:
        progressed = False
        for cid in list(rem):
            sh_a = sum(shared_len.get((cid, nb), 0.1) for nb in adj.get(cid, ()) if nb in core_A)
            sh_b = sum(shared_len.get((cid, nb), 0.1) for nb in adj.get(cid, ()) if nb in core_B)
            touches_a = any(nb in core_A for nb in adj.get(cid, ()))
            touches_b = any(nb in core_B for nb in adj.get(cid, ()))
            if not touches_a and not touches_b:
                continue
            if touches_a and not touches_b:
                core_A.add(cid)
            elif touches_b and not touches_a:
                core_B.add(cid)
            else:
                if sh_a >= sh_b:
                    core_A.add(cid)
                else:
                    core_B.add(cid)
            rem.remove(cid)
            progressed = True
        if not progressed:
            break

    if rem or not _is_induced_connected(core_A, adj) or not _is_induced_connected(core_B, adj):
        return None, None
    return sorted(core_A), sorted(core_B)


def _cluster_sse(ids, vecs):
    """Bir hücre kümesinin öznitelik vektörlerindeki toplam karesel sapmayı (Ward SSE) hesaplar."""
    k = len(ids)
    if k <= 1 or not vecs:
        return 0.0
    dim = len(vecs[ids[0]])
    mean_v = [0.0] * dim
    for cid in ids:
        row = vecs[cid]
        for d in range(dim):
            mean_v[d] += row[d]
    inv = 1.0 / k
    for d in range(dim):
        mean_v[d] *= inv
    sse = 0.0
    for cid in ids:
        row = vecs[cid]
        for d in range(dim):
            diff = row[d] - mean_v[d]
            sse += diff * diff
    return sse


def _is_compact_split_half(g, m, min_pp=0.22):
    """Bölünme sonrası oluşan alt parçanın kompaktlık ve şerit önleme eşiklerini karşılayıp karşılamadığını sınar."""
    if g is None or g.isEmpty():
        return False
    if m["pp"] < min_pp or m["thickness"] < 34.0 or m["core_width"] < 50.0:
        return False
    if m["rot_aspect"] > 3.05 and m["rot_w"] < 88.0 and m["pp"] < 0.30:
        return False
    if m["core_width"] < 66.0 and m["skel_elong"] > 4.1:
        return False
    if m["pp"] < 0.24 and m["rect_fill"] < 0.42:
        return False
    return True


def _would_be_enclosed(g_cand, other_geoms):
    """Bölünmüş parçanın diğer parçanın veya komşu bölgenin içinde enclave/cep oluşturup oluşturmadığını kontrol eder."""
    if g_cand is None or g_cand.isEmpty():
        return True
    perim = max(1.0, float(g_cand.length()))
    area_c = max(1.0, float(g_cand.area()))
    try:
        pt_c = g_cand.pointOnSurface()
    except Exception:
        pt_c = g_cand.centroid()
    box_c = g_cand.boundingBox()
    box_c.grow(4.0)
    for og in other_geoms:
        if og is None or og.isEmpty():
            continue
        if not box_c.intersects(og.boundingBox()):
            continue
        sh = _shared_border_length(g_cand, og, tol=3.0)
        if sh / perim >= 0.56:
            return True
        if og.area() > area_c and pt_c and not pt_c.isEmpty():
            try:
                for rings in _poly_rings_list(og):
                    if rings:
                        outer = QgsGeometry.fromPolygonXY([rings[0]])
                        if outer and not outer.isEmpty() and outer.contains(pt_c):
                            return True
            except Exception:
                pass
    return False


def _find_best_compact_split(
    z_idx, zones, cells, cell_centroids, adj, shared_len, vecs, areas,
    min_half_area, min_cells_half=2, min_pp=0.22
):
    """
    Seçili büyük bölgeyi graf-bağlantılı, kompakt, tek-parça ve enclavesiz iki alt bölgeye ayıracak
    en dengeli ve homojen bölme adayını bulur.
    """
    z = zones[z_idx]
    z_ids = [cid for cid in z.get("ids", []) if 0 <= cid < len(cells)]
    if len(z_ids) < 2 * min_cells_half or not _is_induced_connected(set(z_ids), adj):
        return None

    other_geoms = [oz["geom"] for k, oz in enumerate(zones) if k != z_idx and oz.get("geom")]
    other_zone_dicts = [{"geom": og} for og in other_geoms]

    # Ana eksen açısı (PCA kovaryans majör vektörü) + 4 sabit açı
    mx = sum(cell_centroids[c][0] * areas[c] for c in z_ids) / max(1.0, sum(areas[c] for c in z_ids))
    my = sum(cell_centroids[c][1] * areas[c] for c in z_ids) / max(1.0, sum(areas[c] for c in z_ids))
    cxx = sum(areas[c] * (cell_centroids[c][0] - mx) ** 2 for c in z_ids)
    cyy = sum(areas[c] * (cell_centroids[c][1] - my) ** 2 for c in z_ids)
    cxy = sum(areas[c] * (cell_centroids[c][0] - mx) * (cell_centroids[c][1] - my) for c in z_ids)
    pca_ang = 0.5 * math.atan2(2.0 * cxy, cxx - cyy) if (abs(cxx - cyy) > 1e-6 or abs(cxy) > 1e-6) else 0.0
    angles = [pca_ang, pca_ang + math.pi * 0.5, 0.0, math.pi * 0.25, math.pi * 0.5, math.pi * 0.75]

    total_z_area = sum(areas[c] for c in z_ids)
    raw_partitions = []

    for ang in angles:
        ca, sa = math.cos(ang), math.sin(ang)
        ordered = sorted(z_ids, key=lambda c: cell_centroids[c][0] * ca + cell_centroids[c][1] * sa)
        for frac in (0.44, 0.50, 0.56):
            target_a = total_z_area * frac
            cum = 0.0
            cut = 0
            for idx_o, cid in enumerate(ordered):
                cum += areas[cid]
                cut = idx_o + 1
                if cum >= target_a:
                    break
            cut = max(min_cells_half, min(len(ordered) - min_cells_half, cut))
            A_raw, B_raw = ordered[:cut], ordered[cut:]
            A_rep, B_rep = _repair_bipartition_connectivity(A_raw, B_raw, z_ids, adj, areas, shared_len)
            if A_rep and B_rep:
                raw_partitions.append((A_rep, B_rep))

    # Çift uçlu tohumdan graf büyüme (uzun kenar uçlarından iki dengeli çekirdek)
    sample_ids = z_ids if len(z_ids) <= 36 else z_ids[:: max(1, len(z_ids) // 30)]
    best_pair = None
    best_dist = -1.0
    for i1 in range(len(sample_ids)):
        u = sample_ids[i1]
        ux, uy = cell_centroids[u]
        for i2 in range(i1 + 1, len(sample_ids)):
            v = sample_ids[i2]
            vx, vy = cell_centroids[v]
            d = math.hypot(ux - vx, uy - vy)
            if d > best_dist:
                best_dist = d
                best_pair = (u, v)
    if best_pair is not None:
        u0, v0 = best_pair
        A_g, B_g = {u0}, {v0}
        a_area, b_area = areas[u0], areas[v0]
        assigned = {u0, v0}
        ux, uy = cell_centroids[u0]
        vx, vy = cell_centroids[v0]
        while len(assigned) < len(z_ids):
            cand_a = [nb for c in A_g for nb in adj.get(c, ()) if nb in z_ids and nb not in assigned]
            cand_b = [nb for c in B_g for nb in adj.get(c, ()) if nb in z_ids and nb not in assigned]
            grow_a = (a_area <= b_area and bool(cand_a)) or (not cand_b and bool(cand_a))
            if grow_a:
                best_nb = min(set(cand_a), key=lambda nb: math.hypot(cell_centroids[nb][0] - ux, cell_centroids[nb][1] - uy))
                A_g.add(best_nb)
                assigned.add(best_nb)
                a_area += areas[best_nb]
            elif cand_b:
                best_nb = min(set(cand_b), key=lambda nb: math.hypot(cell_centroids[nb][0] - vx, cell_centroids[nb][1] - vy))
                B_g.add(best_nb)
                assigned.add(best_nb)
                b_area += areas[best_nb]
            else:
                break
        if len(assigned) == len(z_ids) and _is_induced_connected(A_g, adj) and _is_induced_connected(B_g, adj):
            raw_partitions.append((sorted(A_g), sorted(B_g)))

    seen_keys = set()
    sse_parent = _cluster_sse(z_ids, vecs)
    best_split = None
    best_score = -1.0

    for A_ids, B_ids in raw_partitions:
        if len(A_ids) < min_cells_half or len(B_ids) < min_cells_half:
            continue
        fa = frozenset(A_ids)
        fb = frozenset(B_ids)
        pkey = (fa, fb) if min(fa) < min(fb) else (fb, fa)
        if pkey in seen_keys:
            continue
        seen_keys.add(pkey)

        area_A = sum(areas[c] for c in A_ids)
        area_B = sum(areas[c] for c in B_ids)
        if area_A < min_half_area or area_B < min_half_area:
            continue

        gA_raw = QgsGeometry.unaryUnion([cells[c] for c in A_ids])
        gB_raw = QgsGeometry.unaryUnion([cells[c] for c in B_ids])
        if not gA_raw or gA_raw.isEmpty() or not gB_raw or gB_raw.isEmpty():
            continue
        gA = _to_clean_multipolygon(_strip_vacant_zone_holes(gA_raw, -1, other_zone_dicts + [{"geom": gB_raw}]))
        gB = _to_clean_multipolygon(_strip_vacant_zone_holes(gB_raw, -1, other_zone_dicts + [{"geom": gA_raw}]))
        if not gA or gA.isEmpty() or not gB or gB.isEmpty():
            continue

        if len(poly_parts(gA, min_area=10.0)) != 1 or len(poly_parts(gB, min_area=10.0)) != 1:
            continue

        mA = _zone_geometry_elongation_metrics(gA)
        mB = _zone_geometry_elongation_metrics(gB)
        if not (_is_compact_split_half(gA, mA, min_pp=min_pp) and _is_compact_split_half(gB, mB, min_pp=min_pp)):
            continue

        if _would_be_enclosed(gA, other_geoms + [gB]) or _would_be_enclosed(gB, other_geoms + [gA]):
            continue

        sse_gain = max(0.0, sse_parent - (_cluster_sse(A_ids, vecs) + _cluster_sse(B_ids, vecs)))
        bal = min(area_A, area_B) / max(1.0, max(area_A, area_B))
        comp = min(mA["pp"], mB["pp"])
        score = (sse_gain + 1.0) * (0.35 + 0.65 * comp) * (0.45 + 0.55 * bal)
        if score > best_score:
            best_score = score
            best_split = (A_ids, gA, B_ids, gB)

    return best_split


def rebalance_to_target_k(
    zones, target_k, cells, adj, shared_len, vecs, S, areas, ext_kinds,
    allcols=None, prefix="M"
):
    """
    Geometrik temizlik (şerit/enclave/sliver eritme) sonrası alt bölge sayısı kullanıcının istediği K
    değerinin altına düştüyse, büyük ve yüksek varyanslı çok-hücreli kompakt bölgeleri yalnızca
    kompaktlık, tek-parça ve sıfır-enclave şartlarını bozmayan iki parçaya bölerek hedef K'ya yaklaştırır.
    """
    if not zones or len(zones) >= target_k or len(cells) < 2:
        return zones

    cell_centroids = {}
    for cid, cg in enumerate(cells):
        try:
            pt = cg.pointOnSurface().asPoint()
        except Exception:
            pt = cg.centroid().asPoint()
        cell_centroids[cid] = (pt.x(), pt.y())

    total_area = max(1.0, sum(z.get("area", 0.0) for z in zones))
    target_mean = total_area / max(1, target_k)
    unsplitable_ids = set()

    for min_cells_half, min_pp_req, area_mult in ((2, 0.22, 0.24), (1, 0.27, 0.28)):
        min_half_area = max(8000.0, area_mult * target_mean)
        min_parent_area = max(min_half_area * 2.0, 0.55 * target_mean)
        guard = 0
        while len(zones) < target_k and guard < max(8, 3 * target_k):
            guard += 1
            mean_cells = max(2.0, sum(len(z.get("ids", [])) for z in zones) / max(1, len(zones)))
            cands = []
            for idx_z, z in enumerate(zones):
                z_ids = z.get("ids", [])
                z_area = z.get("area", 0.0)
                key = (min_cells_half, tuple(z_ids))
                if key in unsplitable_ids:
                    continue
                if len(z_ids) < 2 * min_cells_half or z_area < min_parent_area:
                    continue
                prio = z_area * (1.0 + 0.18 * (len(z_ids) / mean_cells))
                cands.append((prio, idx_z))
            if not cands:
                break
            cands.sort(reverse=True)
            did_split = False
            for _, idx_z in cands[:6]:
                split_res = _find_best_compact_split(
                    idx_z, zones, cells, cell_centroids, adj, shared_len, vecs, areas,
                    min_half_area=min_half_area, min_cells_half=min_cells_half, min_pp=min_pp_req
                )
                if split_res is None:
                    unsplitable_ids.add((min_cells_half, tuple(zones[idx_z].get("ids", []))))
                    continue
                A_ids, gA, B_ids, gB = split_res
                st_A = zone_stats(idx_z, A_ids, gA, S, areas, ext_kinds, allcols=allcols)
                st_A["geom"] = gA
                st_A["area"] = gA.area()
                st_B = zone_stats(len(zones), B_ids, gB, S, areas, ext_kinds, allcols=allcols)
                st_B["geom"] = gB
                st_B["area"] = gB.area()
                zones[idx_z] = st_A
                zones.append(st_B)
                did_split = True
                break
            if not did_split:
                break

    for idx, z in enumerate(zones):
        new_kod = f"{prefix}{idx + 1}"
        z["l"] = idx
        z["kod"] = new_kod
        z["name"] = new_kod

    return zones


def build_zone_neighbors_from_geoms(zones, cell_adj, cell_labels):
    """Hem hücre grafını hem de budama sonrası nihai bölge poligon temaslarını birleştirir."""
    z_adj = build_zone_neighbors(zones, cell_adj, cell_labels)
    n_z = len(zones)
    z_boxes = [z["geom"].boundingBox() for z in zones]
    for b in z_boxes:
        b.grow(4.0)
    for i in range(n_z):
        gi = zones[i]["geom"]
        if not gi or gi.isEmpty():
            continue
        for j in range(i + 1, n_z):
            if j in z_adj[i]:
                continue
            if not z_boxes[i].intersects(z_boxes[j]):
                continue
            gj = zones[j]["geom"]
            if gj and not gj.isEmpty() and _shared_border_length(gi, gj, tol=3.0) > 1.0:
                z_adj[i].add(j)
                z_adj[j].add(i)
    return z_adj


def generate_truthful_zone_identity(z, zone_seq_idx):
    """
    SIFIR HALÜSİNASYON VE GERÇEK MEKÂNSAL VERİ İLKESİ (Değişmez Akademik Kural 1):
    Bölge kimliğini, gerekçesini, müdahale kararını ve plan karşılığını
    KAFADAN ATILMIŞ ŞABLONLAR yerine BÖLGENİN BİREBİR GERÇEK MEKÂNSAL VERİLERİNDEN üretir.
    %100 Konut olan, ticaret ve donatısı bulunmayan bir bölgeye ASLA 'Toptancı Hali,
    Semt Pazarı' veya 'Lojistik Merkez' gibi uydurma etiketler verilemez.
    """
    p = z.get("pay") or {}
    konut = p.get("konut", 0.0)
    ticaret = p.get("ticaret", 0.0)
    sanayi = p.get("sanayi", 0.0)
    tarim = p.get("tarim", 0.0)
    donati_pay = p.get("donati", 0.0)
    sit = p.get("sit", 0.0)
    sub_p = z.get("sub_lu_pay") or {}
    mezarlik = sub_p.get("mezarlik", 0.0)
    bos_arazi = z.get("bos_arazi_orani", 0.0)

    ext = z.get("ext") or {}
    fay = ext.get("fay")
    dere = ext.get("dere")
    donati_cnt = ext.get("donati")
    donati_dist = z.get("donati_mesafe_m")
    sit_ext = ext.get("sit") or 0.0
    taks = z.get("taks", 0.0) or 0.0
    kat = z.get("kat", 1.0) or 1.0
    yd = z.get("yd_dom") or "Ayrık"
    egim = z.get("egim", 0.0) or 0.0
    kotu_pay = z.get("kotu_pay") or 0.0
    n_bina = z.get("n", 0) or 0
    nufus = z.get("nufus", 0.0) or 0.0

    has_donati_in_zone = (
        (donati_cnt is not None and donati_cnt > 0)
        or (donati_pay >= 0.03)
        or (sub_p.get("donati_aktif_hizmet", 0.0) >= 0.03)
        or (sub_p.get("donati_yesil", 0.0) >= 0.05)
    )
    poor_donati_access = (not has_donati_in_zone) and (donati_dist is None or donati_dist > 350.0)

    # 1. Kentsel Mezarlık
    if mezarlik >= 0.25:
        karakter = "Kentsel Mezarlık ve Çevre Koruma Yeşil Tampon Kuşağı"
        gerekce = "Mezarlık alanı varlığı, çevresindeki açık yeşil doku sürekliliği ve koruma tamponu ihtiyacı."
        kombinasyon = "Mezarlık Alanı + Yeşil Tampon + Düşük Yapılaşma"
        mudahale = "Mezarlık çevresinde koruyucu yeşil tampon oluşturulması, yapılaşma yasağı uygulanması"
        plan = "1/5000 NİP: Mezarlık ve Ağaçlandırılacak Alan; 1/1000 UİP: Mezarlık Kuşağı ve Yeşil Park"
        return karakter, gerekce, kombinasyon, mudahale, plan

    # 2. Sosyal Donatı / Eğitim / Sağlık / Aktif Yeşil Odak Alanı
    if donati_pay >= 0.35:
        karakter = "Eğitim, Sosyal Donatı ve Kamusal Hizmet Odak Alanı"
        gerekce = f"Bölgenin %{donati_pay*100:.0f} oranında kamusal donatı/okul/park alanlarından oluşması."
        kombinasyon = f"Kamusal Donatı (%{donati_pay*100:.0f}) + Konut (%{konut*100:.0f})"
        mudahale = "Kamusal donatı ve açık yeşil sürekliliğinin korunması, yaya erişim bağlantılarının güçlendirilmesi"
        plan = "1/5000 NİP: Sosyal Altyapı ve Eğitim/Park Alanı; 1/1000 UİP: Okul / Park / Sağlık Tesis Alanı"
        return karakter, gerekce, kombinasyon, mudahale, plan

    # 3. Sanayi / İmalat / Depolama
    if sanayi >= 0.40:
        if konut >= 0.20:
            karakter = "Sanayi - Konut Hassas Tampon ve Çevresel Etkileşim Arayüzü"
            gerekce = f"Sanayi (%{sanayi*100:.0f}) ve konut (%{konut*100:.0f}) kullanımlarının sınır temasında yer alan çevresel baskı kuşağı."
            kombinasyon = "Sanayi Kullanımı + Konut Komşuluğu + Tampon İhtiyacı"
            mudahale = "Ağır vasıta güzergâhının konut dokusundan ayrılması ve 30-50m yeşil koruma tamponu oluşturulması"
            plan = "1/5000 NİP: Sanayi Koruma Tamponu; 1/1000 UİP: Koruyucu Yeşil Kuşak ve Lojistik Servis Yolu"
        else:
            karakter = "Sanayi, İmalat ve Depolama Sahası"
            gerekce = f"Ağırlıklı sanayi ve imalat fonksiyonları (%{sanayi*100:.0f}), düşük konut payı (%{konut*100:.0f}) ve geniş tabanlı yapı dokusu."
            kombinasyon = f"Sanayi ve Depolama (%{sanayi*100:.0f}) + TAKS %{taks*100:.1f}"
            mudahale = "Lojistik altyapı standartlarının güçlendirilmesi, arıtma ve çevresel atık yönetimi denetimi"
            plan = "1/5000 NİP: Kentsel Servis ve Sanayi Alanı; 1/1000 UİP: KSS / Sanayi Tesis Alanı"
        return karakter, gerekce, kombinasyon, mudahale, plan

    # 4. Tarım / Yapısız Açık Alan / Kırsal Çeper
    if tarim >= 0.55 or (n_bina == 0 and taks < 0.015 and konut < 0.20):
        if konut >= 0.15:
            karakter = "Kırsal Nitelikli Seyrek Konut ve Tarımsal Üretim Çeperi"
            gerekce = f"Tarımsal/açık alanlar (%{tarim*100:.0f}) ile seyrek konutların (%{konut*100:.0f}) bir arada bulunduğu geçiş zonu."
            kombinasyon = "Tarım/Açık Alan + Seyrek Yerleşim"
            mudahale = "Tarımsal niteliğin korunması, düşük emsalli kırsal yapılaşma koşulu ve tarım arazisi bölünmelerinin önlenmesi"
            plan = "1/5000 NİP: Kırsal Nitelikli Yerleşme Alanı; 1/1000 UİP: Düşük Yoğunluklu Kırsal Konut"
        else:
            karakter = "Tarımsal Üretim ve Yapısız Açık Alan Kuşağı"
            gerekce = f"Tarımsal/açık alan varlığı (%{max(tarim, bos_arazi)*100:.0f}), {n_bina} yapı ve kentsel yapılaşma baskısından korunması gereken doku."
            kombinasyon = f"Tarım/Açık Doku + Boş Arazi %{bos_arazi*100:.0f} + {n_bina} Yapı"
            mudahale = "Tarım toprağı bütünlüğünün ve ekolojik açık alan sürekliliğinin korunması, plansız yayılmanın önlenmesi"
            plan = "1/5000 NİP: Tarımsal Niteliği Korunacak Alan; 1/1000 UİP: Tarım / Açık Alan"
        return karakter, gerekce, kombinasyon, mudahale, plan

    # 5. Tarihi Sit ve Kültürel Miras
    if max(sit, sit_ext) >= 0.30:
        sit_pct = max(sit, sit_ext) * 100.0
        karakter = "Tarihi Sit Alanı ve Geleneksel Doku Koruma Odağı"
        gerekce = f"Tescilli sit/kültür varlığı yoğunluğu (%{sit_pct:.0f}), mevcut sokak dokusu ve tarihi kentsel kimlik sürekliliği."
        kombinasyon = f"Kentsel Sit (%{sit_pct:.0f}) + Koruma Eşiği"
        mudahale = "Koruma amaçlı imar planı kararları, cephe sağlıklaştırma ve geleneksel doku koruma esasları"
        plan = "1/5000 NİP: Tarihi Kentsel Sit Alanı; 1/1000 KAUİP: Koruma Amaçlı Uygulama İmar Planı"
        return karakter, gerekce, kombinasyon, mudahale, plan

    # 6. Gerçek Ticaret / Karma Kullanım (Yalnızca veri ticaret >= %30 ise!)
    if ticaret >= 0.30:
        if konut >= 0.25:
            karakter = "Ticaret ve Konut Karma Gelişme Alanı"
            gerekce = f"Ticaret (%{ticaret*100:.0f}) ve konut (%{konut*100:.0f}) kullanımlarının birlikte yer aldığı kentsel karma doku."
            kombinasyon = f"Ticaret (%{ticaret*100:.0f}) + Konut (%{konut*100:.0f}) + TAKS %{taks*100:.1f}"
            mudahale = "Yaya-taşıt ayrımının düzenlenmesi, otopark kapasitesi ve karma kullanım dengeleme kararları"
            plan = "1/5000 NİP: Ticaret-Konut Karma Alanı (TİCK); 1/1000 UİP: Karma Kullanım Adaları"
        else:
            karakter = "Ticaret ve Kentsel Hizmet Çekirdeği"
            gerekce = f"Ölçülen ticari kullanım yoğunluğu (%{ticaret*100:.0f}) ve hizmet birimleri ağırlığı."
            kombinasyon = f"Ticaret (%{ticaret*100:.0f}) + Hizmet Dokusu + TAKS %{taks*100:.1f}"
            mudahale = "Yaya öncelikli düzenlemeler, servis/otopark yönetimi ve ticari doku iyileştirmesi"
            plan = "1/5000 NİP: Merkezi/Bölgesel Ticaret Alanı; 1/1000 UİP: Ticaret Alanı (T)"
        return karakter, gerekce, kombinasyon, mudahale, plan

    # 7. KONUT DOKUSU (%100 veya Ağırlıklı Konut - Sıfır Halüsinasyon)
    if taks < 0.20 and kat <= 2.2:
        density_label = "Düşük Yoğunluklu Seyrek Konut Dokusu"
        nip_code = "Düşük Yoğunluklu Konut Alanı (E=0.40)"
        uip_code = f"{yd} Nizam Konut (Az Katlı, ~{max(1, round(kat))} Kat)"
    elif taks >= 0.40 or (taks >= 0.28 and kat >= 3.2):
        density_label = "Yüksek Yoğunluklu Sıkı Konut Dokusu"
        nip_code = "Yüksek Yoğunluklu Yerleşik Konut Alanı"
        uip_code = f"{yd} Nizam Çok Katlı Konut (TAKS %{taks*100:.0f})"
    elif taks >= 0.28 or kat >= 4.0:
        density_label = "Yüksek Yoğunluklu Çok Katlı Konut Dokusu"
        nip_code = "Yüksek Yoğunluklu Konut Alanı"
        uip_code = f"{yd} Nizam Çok Katlı Konut"
    else:
        density_label = "Orta Yoğunluklu Düzenli Konut Yerleşimi"
        nip_code = "Orta Yoğunluklu Konut Alanı"
        uip_code = f"{yd} Nizam Konut"

    no_tic_txt = "ticaret alanı bulunmayan, " if ticaret < 0.02 else ""
    don_dist_txt = f" (en yakın donatı {donati_dist:.0f}m)" if donati_dist is not None else ""

    if fay is not None and fay < 350.0:
        issue_label = "ve Diri Fay Hattı Afet Hassasiyet Kuşağı"
        extra_don = " Donatı/park eksikliği de gözlenmektedir." if poor_donati_access else ""
        gerekce = f"Diri fay hattına {fay:.0f}m mesafede, %{konut*100:.0f} konut dokusu (TAKS %{taks*100:.1f}, {kat:.1f} kat) barındıran deprem hassasiyet alanı.{extra_don}"
        mudahale = "Yapılaşma yoğunluğunun artırılmaması, mikro-bölgeleme ve zemin etüdü tabanlı kentsel dönüşüm + açık toplanma alanı sağlanması"
        plan = f"1/5000 NİP: Afet Önlemli Konut Alanı; 1/1000 UİP: {uip_code} ve Afet Toplanma Alanı"
        kombinasyon = f"Konut (%{konut*100:.0f}) + Diri Fay ({fay:.0f}m) + TAKS %{taks*100:.1f}"
    elif dere is not None and dere < 250.0:
        issue_label = "ve Dere Yatağı Taşkın Koruma Çeperi"
        gerekce = f"Dere koridoruna {dere:.0f}m mesafede konumlanan %{konut*100:.0f} konut dokusu ve taşkın koruma gereksinimi."
        mudahale = "Dere koruma bandında yapılaşma yasağı ve su kenarı yeşil koridor oluşturulması"
        plan = f"1/5000 NİP: Taşkın Önlemli Konut Alanı; 1/1000 UİP: {uip_code} ve Dere Koruma Bandı"
        kombinasyon = f"Konut (%{konut*100:.0f}) + Dere Yakınlığı ({dere:.0f}m)"
    elif kotu_pay >= 0.25:
        issue_label = "ve Yapı Stoğu Yenileme / Sağlıklaştırma Alanı"
        gerekce = f"%{konut*100:.0f} konut dokusunda %{kotu_pay*100:.1f} oranında kötü/yıpranmış yapı ve {yd} nizam yapılaşma."
        mudahale = "Yıpranmış yapı stoğunun güçlendirilmesi veya ada bazlı kentsel sağlıklaştırma uygulanması"
        plan = f"1/5000 NİP: Kentsel Yenileme ve Konut Alanı; 1/1000 UİP: {uip_code} Yenileme Adaları"
        kombinasyon = f"Konut (%{konut*100:.0f}) + Kötü Yapı (%{kotu_pay*100:.1f}) + TAKS %{taks*100:.1f}"
    elif poor_donati_access:
        issue_label = "ve Sosyal Donatı / Okul Yetersizliği Alanı"
        gerekce = (
            f"%{konut*100:.0f} saf konut dokusu ({nufus:.0f} kişi, TAKS %{taks*100:.1f}, Ort. {kat:.1f} kat) olup "
            f"{no_tic_txt}bölge içinde okul, park veya sosyal donatı alanı bulunmamaktadır{don_dist_txt}."
        )
        mudahale = "Mevcut konut dokusunun iyileştirilmesi; erişim yarıçapı içinde mahalle parkı, çocuk oyun alanı ve temel okul/donatı rezervi üretilmesi"
        plan = f"1/5000 NİP: {nip_code} ve Sosyal Donatı Rezervi; 1/1000 UİP: {uip_code} + Park/Okul Donatısı"
        kombinasyon = f"Konut (%{konut*100:.0f}) + Donatı Eksikliği + {yd} Nizam"
    elif bos_arazi >= 0.45:
        issue_label = "ve Boş İmar Parseli Rezerv Gelişme Alanı"
        gerekce = f"%{bos_arazi*100:.0f} boş arsa oranı ve %{konut*100:.0f} konut dokusu ile planlı gelişme kapasitesi yüksek alan."
        mudahale = "Etaplı altyapı hazırlığı ile donatı dengesi gözetilerek planlı konut gelişimi"
        plan = f"1/5000 NİP: Rezerv Gelişme Konut Alanı; 1/1000 UİP: {uip_code}"
        kombinasyon = f"Konut (%{konut*100:.0f}) + Boş Arsa (%{bos_arazi*100:.0f})"
    elif egim >= 12.0:
        issue_label = "ve Eğimli Yamaç Konut Morfolojisi"
        gerekce = f"Ortalama %{egim:.1f} eğim üzerinde yer alan %{konut*100:.0f} konut yerleşimi (TAKS %{taks*100:.1f})."
        mudahale = "Eğime uyumlu kademeli yapılaşma, drenaj ve zemin stabilizasyonu"
        plan = f"1/5000 NİP: Eğimli Konut Alanı; 1/1000 UİP: Kademeli {uip_code}"
        kombinasyon = f"Konut (%{konut*100:.0f}) + Eğim %{egim:.1f}"
    elif has_donati_in_zone:
        issue_label = "ve Donatı Erişimi Güçlü Konut Alanı"
        gerekce = f"%{konut*100:.0f} konut dokusu içinde %{donati_pay*100:.1f} donatı payı{don_dist_txt}, TAKS %{taks*100:.1f} ve {kat:.1f} kat düzeni."
        mudahale = "Mevcut konut-donatı dengesinin ve yürünebilir yeşil/sosyal altyapı ağının korunması"
        plan = f"1/5000 NİP: {nip_code}; 1/1000 UİP: {uip_code}"
        kombinasyon = f"Konut (%{konut*100:.0f}) + Donatı Mevcut + {yd} Nizam"
    else:
        issue_label = f"({yd} Nizam Yerleşik Konut)"
        gerekce = f"%{konut*100:.0f} konut ağırlıklı yerleşik doku, TAKS %{taks*100:.1f}, ortalama {kat:.1f} kat ve {yd} yapılaşma düzeni."
        mudahale = "Mevcut morfolojik nizamın ve sokak altyapısının korunarak iyileştirilmesi"
        plan = f"1/5000 NİP: {nip_code}; 1/1000 UİP: {uip_code}"
        kombinasyon = f"Konut (%{konut*100:.0f}) + TAKS %{taks*100:.1f} + {yd} Nizam"

    karakter = f"{density_label} {issue_label}"
    return karakter, gerekce, kombinasyon, mudahale, plan


def assign_truthful_planning_identities(zones, P, target_rows, mode="advanced", preserve_codes=False):
    """
    SIFIR HALÜSİNASYON VE GERÇEK MEKÂNSAL VERİ İLKESİ (Değişmez Akademik Kural 1):
    Bölgelerin karakter, gerekçe, müdahale kararı ve plan karşılıklarını
    BÖLGENİN BİREBİR GERÇEK MEKÂNSAL VERİLERİNDEN üretir.
    %100 Konut olan, ticaret ve donatısı bulunmayan bir bölgeye ASLA 'Toptancı Hali,
    Semt Pazarı' veya 'Lojistik Merkez' gibi uydurma etiketler verilemez.
    """
    prefix = "M" if mode == "advanced" else "A"
    for seq_idx, z in enumerate(zones, 1):
        if not preserve_codes or not z.get("kod"):
            z["kod"] = f"{prefix}{seq_idx}"
        karakter, gerekce, komb, mudahale, plan = generate_truthful_zone_identity(z, seq_idx)
        z["karakter"] = karakter
        z["excel_gerekce"] = gerekce
        z["baskin_kombinasyon"] = komb
        z["mudahale_karari"] = mudahale
        z["plan_karsiligi"] = plan
        z["uyum"] = 95.0


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
        return f"TAKS yoğunluk farkı (%{z['taks'] * 100:.1f} vs {nb_kod}'de %{nb['taks'] * 100:.1f})"
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
    z["road_nodes"] = sum(S[i].get("road_nodes", 0) for i in ids)
    z["road_dead_ends"] = sum(S[i].get("road_dead_ends", 0) for i in ids)
    z["cikmaz_sokak_orani"] = (z["road_dead_ends"] / z["road_nodes"]) if z["road_nodes"] > 0 else None
    z["rkap_dom"] = rkap.most_common(1)[0][0] if rkap else None
    z["rtur_dom"] = rtur.most_common(1)[0][0] if rtur else None
    z["kotu_pay"] = z["kotu"] / z["kotu_a"] if z["kotu_a"] > 0 else None
    ev = [(S[i]["egim"], areas[i]) for i in ids if S[i]["egim"] is not None]
    z["egim"] = sum(v * a for v, a in ev) / sum(a for _, a in ev) if ev else None
    rv = [(S[i].get("rakim"), areas[i]) for i in ids if S[i].get("rakim") is not None]
    z["rakim"] = sum(v * a for v, a in rv) / sum(a for _, a in rv) if rv else None

    ext = {}
    ext_min = {}
    for key, kind in ext_kinds.items():
        if kind == "count":
            ext[key] = sum((S[i]["ext"].get(key) or 0.0) for i in ids)
        else:
            vv = [(S[i]["ext"].get(key), areas[i]) for i in ids if S[i]["ext"].get(key) is not None]
            ext[key] = sum(v * a for v, a in vv) / sum(a for _, a in vv) if vv else None
            if kind == "dist":
                mins = []
                for idx_cell in ids:
                    mv = S[idx_cell].get("ext_min", {}).get(key)
                    if mv is None:
                        mv = S[idx_cell]["ext"].get(key)
                    if mv is not None:
                        mins.append(mv)
                if mins:
                    ext_min[key] = min(mins)
    z["ext"] = ext
    z["ext_min"] = ext_min

    # Clean-Room PlanX-İlhamlı Morfoloji & Afet Metrikleri: Spacematrix (FSI/OSR), Sokak Kanyonu (H/W),
    # MPYY Kişi Başı Aktif Donatı (m²/kişi) ve Karma Kullanım Shannon Entropisi
    kat_eff = float(z["kat"]) if (z.get("kat") is not None and z["n"] > 0 and z["taks"] >= 0.015) else 0.0
    fsi = min(8.0, z["taks"] * kat_eff) if (z["n"] > 0 and z["taks"] >= 0.015) else 0.0
    z["fsi"] = fsi
    z["osr"] = ((1.0 - z["taks"]) / fsi) if fsi > 0.01 else None
    if z["n"] == 0 or z["taks"] < 0.015:
        z["spacematrix_tip"] = "Açık Alan / Tarım-Doğa (Yapısız)"
    elif kat_eff <= 2.2:
        z["spacematrix_tip"] = "Alçak Sıkı Doku" if z["taks"] >= 0.25 else "Alçak Seyrek Doku"
    elif kat_eff <= 5.5:
        if z["taks"] >= 0.36:
            z["spacematrix_tip"] = "Orta Katlı Bitişik Yoğun"
        elif z["taks"] >= 0.22:
            z["spacematrix_tip"] = "Orta Katlı Blok / Karma"
        else:
            z["spacematrix_tip"] = "Orta Katlı Seyrek / Bahçeli"
    else:
        z["spacematrix_tip"] = "Yüksek Yoğun Blok" if z["taks"] >= 0.25 else "Yüksek Katlı Açık / Kule"

    if z["yg"] and z["yg"] > 0 and z["n"] > 0 and kat_eff > 0:
        hw_val = (kat_eff * 3.0) / max(1.0, z["yg"])
        z["hw_ratio"] = hw_val
        if hw_val >= 1.5:
            z["hw_sinif"] = "Kritik Enkaz Darboğazı (H/W ≥ 1.5)"
        elif hw_val >= 1.0:
            z["hw_sinif"] = "Orta Enkaz Riski (1.0 ≤ H/W < 1.5)"
        else:
            z["hw_sinif"] = "Açık Tahliye Koridoru (H/W < 1.0)"
    else:
        z["hw_ratio"] = None
        z["hw_sinif"] = None

    active_donati_m2 = sub_lu.get("donati_aktif_hizmet", 0.0) + sub_lu.get("donati_yesil", 0.0)
    if active_donati_m2 <= 0.0 and lu.get("donati", 0.0) > 0.0:
        active_donati_m2 = max(0.0, lu.get("donati", 0.0) - sub_lu.get("mezarlik", 0.0))
    z["active_donati_m2"] = active_donati_m2
    z["kisi_basi_donati_m2"] = (active_donati_m2 / z["nufus"]) if z["nufus"] >= 10.0 else None

    if z["pay"]:
        mix_vals = [max(0.0, z["pay"].get(c, 0.0)) for c in ("konut", "ticaret", "sanayi", "tarim", "donati")]
        msum = sum(mix_vals)
        if msum > 0.0:
            ent = -sum((v / msum) * math.log(v / msum) for v in mix_vals if v > 1e-9)
            z["karma_entropi"] = min(1.0, max(0.0, ent / math.log(5.0)))
        else:
            z["karma_entropi"] = 0.0
    else:
        z["karma_entropi"] = None

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
    details.append(f"%{z['taks'] * 100:.1f} TAKS yoğunluğu")
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
    ("FSI_Emsal_Tahmini", _QVAR_DOUBLE),
    ("OSR_Acik_Alan_Orani", _QVAR_DOUBLE),
    ("Spacematrix_Tipolojisi", _QVAR_STRING),
    ("Sokak_Enkaz_Orani_H_W", _QVAR_DOUBLE),
    ("Sokak_Tahliye_Riski_Sinifi", _QVAR_STRING),
    ("Cikmaz_Sokak_Orani_Yuzde", _QVAR_DOUBLE),
    ("Kisi_Basi_Donati_m2", _QVAR_DOUBLE),
    ("Karma_Kullanim_Entropi", _QVAR_DOUBLE),
    ("Deprem_Kirilganlik_Sinifi", _QVAR_STRING),
    ("Sel_Kirilganlik_Sinifi", _QVAR_STRING),
    ("Genel_Kirilganlik_Sinifi", _QVAR_STRING),
    ("Maruz_Kalma_Derecesi", _QVAR_STRING),
    ("Hassasiyet_Derecesi", _QVAR_STRING),
    ("Uyum_Kapasitesi_Derecesi", _QVAR_STRING),
    ("Deprem_Kirilganlik_Gerekcesi", _QVAR_STRING),
    ("Sel_Kirilganlik_Gerekcesi", _QVAR_STRING),
    ("Maruz_Kalma_Aciklamasi", _QVAR_STRING),
    ("Hassasiyet_Aciklamasi", _QVAR_STRING),
    ("Uyum_Kapasitesi_Aciklamasi", _QVAR_STRING),
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
    "FSI_Emsal_Tahmini",
    "OSR_Acik_Alan_Orani",
    "Spacematrix_Tipolojisi",
    "Ortalama_Kat_Sayisi",
    "Baskin_Yapi_Nizami",
    "Sokak_Enkaz_Orani_H_W",
    "Cikmaz_Sokak_Orani_Yuzde",
    "Kisi_Basi_Donati_m2",
    "Toplam_Nufus_Kisi",
    "Deprem_Kirilganlik_Sinifi",
    "Sel_Kirilganlik_Sinifi",
    "Genel_Kirilganlik_Sinifi",
    "Maruz_Kalma_Derecesi",
    "Hassasiyet_Derecesi",
    "Uyum_Kapasitesi_Derecesi",
    "Deprem_Kirilganlik_Gerekcesi",
    "Sel_Kirilganlik_Gerekcesi",
    "Maruz_Kalma_Aciklamasi",
    "Hassasiyet_Aciklamasi",
    "Uyum_Kapasitesi_Aciklamasi",
    "Mudahale_Karari",
    "Plan_Karsiligi",
]


def r(v, d=1):
    return None if v is None else round(float(v), d)


def compute_vulnerability(z):
    area_m2 = max(1.0, float(z.get("area") or 10000.0))
    ha = area_m2 / 10000.0
    n_bldg = int(z.get("n") or 0)
    nufus = float(z.get("nufus") or 0.0)
    taks = float(z.get("taks") or 0.0)
    has_built = (
        (n_bldg > 0 and (taks >= 0.015 or (n_bldg / max(1.0, ha)) >= 0.35 or nufus >= 15.0))
        or taks >= 0.015
        or nufus >= 15.0
    )
    kat_raw = z.get("kat")
    kat = float(kat_raw) if (kat_raw is not None and has_built) else (0.0 if not has_built else 1.5)
    ext = z.get("ext") or {}
    ext_min = z.get("ext_min") or {}
    kotu = float(z.get("kotu_pay") if z.get("kotu_pay") is not None else (ext.get("kotu_yapi") or 0.0))
    bitisik = float(z.get("bitisik") or 0.0)
    dens = nufus / ha

    fay_m = ext.get("fay")
    fay_min = ext_min.get("fay")
    fay_eff = (
        min(float(fay_m), 0.60 * float(fay_min) + 0.40 * float(fay_m))
        if (fay_m is not None and fay_min is not None)
        else (float(fay_min) if fay_min is not None else (float(fay_m) if fay_m is not None else None))
    )
    dere_m = ext.get("dere")
    dere_min = ext_min.get("dere")
    dere_eff = (
        min(float(dere_m), 0.65 * float(dere_min) + 0.35 * float(dere_m))
        if (dere_m is not None and dere_min is not None)
        else (float(dere_min) if dere_min is not None else (float(dere_m) if dere_m is not None else None))
    )
    donati_n = ext.get("donati")
    toplanma_m = ext.get("toplanma")
    saglik_m = ext.get("saglik")
    risk_share = float(ext.get("risk") or 0.0)
    sit_share = float(ext.get("sit") if ext.get("sit") is not None else ((z.get("pay") or {}).get("sit") or ext.get("sit2") or 0.0))

    yg = z.get("yg")
    egim = z.get("egim") if z.get("egim") is not None else ext.get("egim")
    rakim = z.get("rakim") if z.get("rakim") is not None else ext.get("rakim")
    hw_ratio = z.get("hw_ratio")
    if hw_ratio is None and yg and float(yg) > 0 and kat > 0 and n_bldg > 0:
        hw_ratio = (kat * 3.0) / max(1.0, float(yg))
    dead_ratio = z.get("cikmaz_sokak_orani")
    osr = z.get("osr")
    fsi = float(z.get("fsi") if z.get("fsi") is not None else (taks * kat))
    gecirimli = max(0.0, 1.0 - taks)
    donati_dist = z.get("donati_mesafe_m")
    kisi_don = z.get("kisi_basi_donati_m2")

    # 1) MARUZ KALMA (EXPOSURE — E): Tehlikeye açık nüfus/yapı stoğu + yakın-fay/dere kesimi
    e_dens = min(5.0, max(1.0, 1.0 + (dens / 130.0) * 4.0))
    e_bldg = min(5.0, max(1.0, 1.0 + ((n_bldg / ha) / 16.0) * 4.0))
    e_cov = min(5.0, max(1.0, 1.0 + (taks / 0.55) * 4.0))
    e_assets = 0.58 * e_dens + 0.42 * e_bldg
    e_assets_dep = max(e_assets, 0.44 * e_dens + 0.28 * e_bldg + 0.28 * e_cov)

    if fay_eff is not None:
        fe = float(fay_eff)
        if fe <= 50.0:
            hz_fay = 5.0
        elif fe <= 250.0:
            hz_fay = 4.95 - ((fe - 50.0) / 200.0) * 0.45
        elif fe <= 750.0:
            hz_fay = 4.50 - ((fe - 250.0) / 500.0) * 1.10
        else:
            hz_fay = max(1.0, 3.40 - ((fe - 750.0) / 1750.0) * 2.40)
    else:
        hz_fay = None
    hz_dere = min(5.0, max(1.0, 5.0 - (float(dere_eff) / 900.0) * 4.0)) if dere_eff is not None else None
    hz_flood_poly = min(5.0, 1.0 + risk_share * 4.0) if ext.get("risk") is not None else None
    if hz_dere is not None and hz_flood_poly is not None:
        hz_sel = max(hz_dere, 0.55 * hz_dere + 0.45 * hz_flood_poly)
    elif hz_dere is not None:
        hz_sel = hz_dere
    elif hz_flood_poly is not None:
        hz_sel = hz_flood_poly
    else:
        hz_sel = None

    if not has_built:
        E_deprem = 1.0 + (0.28 * (hz_fay - 1.0) if hz_fay is not None else 0.0)
        E_sel = 1.0 + (0.45 * (hz_sel - 1.0) if hz_sel is not None else 0.0)
    else:
        if hz_fay is not None:
            if hz_fay >= 4.45:
                E_deprem = max(0.50 * e_assets_dep + 0.50 * hz_fay, 0.36 * e_assets_dep + 0.64 * hz_fay)
            else:
                E_deprem = 0.55 * e_assets_dep + 0.45 * hz_fay
        else:
            E_deprem = e_assets_dep
        E_sel = (0.48 * e_assets + 0.52 * hz_sel) if hz_sel is not None else e_assets

    E_score = 0.55 * E_deprem + 0.45 * E_sel

    # 2) HASSASİYET (SENSITIVITY — S): Fiziksel yapı kırılganlığı, doku sıkışıklığı ve eğim
    if not has_built:
        S_deprem = 1.0
        s_egim_val = min(5.0, max(1.0, 1.0 + (float(egim or 0.0) / 30.0) * 4.0))
        S_sel = 1.0 + 0.15 * (s_egim_val - 1.0)
    else:
        s_taks = min(5.0, max(1.0, 1.0 + (taks / 0.50) * 4.0))
        s_kat = min(5.0, max(1.0, 1.0 + (max(0.0, kat - 1.0) / 5.0) * 4.0))
        s_kotu = min(5.0, max(1.0, 1.0 + kotu * 7.5))
        s_bit = min(5.0, max(1.0, 1.0 + (bitisik / 0.85) * 4.0))
        S_deprem = (
            0.30 * s_kotu + 0.24 * s_bit + 0.24 * s_taks + 0.22 * s_kat
            if kotu > 0.0 else
            0.32 * s_bit + 0.34 * s_taks + 0.34 * s_kat
        )
        if sit_share >= 0.05:
            S_deprem = min(5.0, S_deprem + 0.40 * sit_share)
        if kotu >= 0.20 and bitisik >= 0.45:
            S_deprem = min(5.0, S_deprem + 0.35)
        s_egim_val = min(5.0, max(1.0, 1.0 + (float(egim or 0.0) / 25.0) * 2.5))
        S_sel = 0.40 * s_taks + 0.28 * s_kotu + 0.17 * s_bit + 0.15 * s_egim_val

    S_score = 0.55 * S_deprem + 0.45 * S_sel

    # 3) UYUM KAPASİTESİ (ADAPTIVE CAPACITY — AC): Yol genişliği, H/W enkaz açıklığı, çıkmaz sokak azlığı, donatı & açık alan
    ac_yg = min(5.0, max(1.0, 1.0 + ((float(yg) - 4.0) / 14.0) * 4.0)) if yg is not None else 2.8
    if hw_ratio is not None:
        ac_hw = min(5.0, max(1.0, 5.0 - (min(2.0, float(hw_ratio)) / 1.8) * 4.0))
    else:
        ac_hw = 4.2 if not has_built else 3.0
    ac_dead = (
        min(5.0, max(1.0, 5.0 - float(dead_ratio) * 4.0))
        if dead_ratio is not None
        else (4.2 if not has_built else min(3.2, ac_yg + 0.8))
    )
    ac_gec = min(5.0, max(1.0, 1.0 + max(0.0, gecirimli - 0.20) * 5.0))
    ac_rakim = min(5.0, max(1.0, 1.0 + ((float(rakim) - 40.0) / 220.0) * 4.0)) if rakim is not None else 3.0

    emerg_terms = []
    if toplanma_m is not None:
        emerg_terms.append(min(5.0, max(1.0, 5.0 - (float(toplanma_m) / 1000.0) * 4.0)))
    if saglik_m is not None:
        emerg_terms.append(min(5.0, max(1.0, 5.0 - (float(saglik_m) / 2000.0) * 4.0)))
    if donati_dist is not None:
        emerg_terms.append(min(5.0, max(1.0, 5.0 - (float(donati_dist) / 1200.0) * 4.0)))
    if donati_n is not None:
        emerg_terms.append(min(5.0, max(1.0, 1.5 + (float(donati_n) / 4.0) * 3.5)))
    ac_emerg = (sum(emerg_terms) / len(emerg_terms)) if emerg_terms else 2.8

    AC_deprem = 0.34 * ac_yg + 0.24 * ac_hw + 0.14 * ac_dead + 0.14 * ac_emerg + 0.14 * ac_gec
    if has_built and yg is not None and float(yg) < 6.5 and taks >= 0.45:
        AC_deprem = min(AC_deprem, 2.45)
    AC_sel = 0.38 * ac_gec + 0.30 * ac_rakim + 0.20 * ac_yg + 0.12 * ac_emerg
    AC_score = 0.55 * AC_deprem + 0.45 * AC_sel

    V_deprem = min(5.0, max(1.0, 0.90 + 2.10 * (((E_deprem * S_deprem) / max(1.0, AC_deprem)) / 3.0) ** 0.55))
    V_sel = min(5.0, max(1.0, 0.90 + 2.10 * (((E_sel * S_sel) / max(1.0, AC_sel)) / 3.0) ** 0.55))
    V_genel = 0.60 * V_deprem + 0.40 * V_sel

    def tier(score):
        if score < 1.8:
            return "Çok Düşük"
        if score < 2.6:
            return "Düşük"
        if score < 3.45:
            return "Orta"
        if score < 4.30:
            return "Yüksek"
        return "Çok Yüksek"

    t_e = tier(E_score)
    t_s = tier(S_score)
    t_ac = tier(AC_score)
    t_dep = tier(V_deprem)
    t_sel = tier(V_sel)
    t_gen = tier(V_genel)

    # Açıklayıcı sade Türkçe gerekçe cümleleri
    e_facts = [
        f"nüfus {int(round(nufus))} kişi ({dens:.0f} kişi/ha)" if has_built else "yerleşik nüfus yok (0 kişi)",
        f"{n_bldg} bina (TAKS %{taks * 100:.0f})" if n_bldg > 0 else "yapı yok (0 bina)",
    ]
    if fay_min is not None and float(fay_min) <= 35.0 and fay_m is not None:
        e_facts.append(f"diri fay bölge içinden geçiyor (min. {float(fay_min):.0f} m, ort. {float(fay_m):.0f} m)")
    elif fay_m is not None:
        e_facts.append(f"diri faya {float(fay_m):.0f} m")
    if dere_m is not None:
        e_facts.append(f"akarsuya {float(dere_m):.0f} m")
    if risk_share > 0.01:
        e_facts.append(f"taşkın alanı %{risk_share * 100:.0f}")
    E_aciklama = (
        f"MARUZ KALMA [{t_e} ({E_score:.1f}/5)]: Afete açık insan/yapı yoğunluğu ve tehlikeye yakınlığı ifade eder. "
        + "Ölçülen: " + ", ".join(e_facts) + "."
    )

    if not has_built:
        s_fact_str = "Yapısız/açık arazi olduğu için yapısal hasar hassasiyeti minimumdadır"
    else:
        s_facts = [
            f"TAKS %{taks * 100:.0f}",
            f"ort. {kat:.1f} kat (FSI={fsi:.2f})",
        ]
        if kotu > 0.0:
            s_facts.append(f"kötü yapı %{kotu * 100:.0f}")
        if bitisik > 0.0:
            s_facts.append(f"bitişik nizam %{bitisik * 100:.0f}")
        if egim is not None:
            s_facts.append(f"eğim %{float(egim):.1f}")
        if sit_share >= 0.05:
            s_facts.append(f"sit alanı %{sit_share * 100:.0f}")
        s_fact_str = "Ölçülen: " + ", ".join(s_facts)
    S_aciklama = (
        f"HASSASİYET [{t_s} ({S_score:.1f}/5)]: Afet anında doku ve binaların fiziksel hasar görebilirliğini ölçer. "
        + s_fact_str + "."
    )

    ac_facts = []
    if yg is not None:
        ac_facts.append(f"ort. yol {float(yg):.1f} m")
    if hw_ratio is not None:
        ac_facts.append(f"sokak enkaz H/W={hw_ratio:.2f}")
    if dead_ratio is not None:
        ac_facts.append(f"çıkmaz sokak %{dead_ratio * 100:.0f}")
    if toplanma_m is not None:
        ac_facts.append(f"toplanmaya {float(toplanma_m):.0f} m")
    elif donati_dist is not None:
        ac_facts.append(f"donatı erişimi {float(donati_dist):.0f} m")
    if kisi_don is not None:
        ac_facts.append(f"kişi başı donatı {kisi_don:.1f} m²")
    ac_facts.append(
        f"geçirimli açık alan %{gecirimli * 100:.0f}" + (f" (OSR={osr:.2f})" if osr is not None else "")
    )
    if rakim is not None:
        ac_facts.append(f"rakım {float(rakim):.0f} m")
    AC_aciklama = (
        f"UYUM KAPASİTESİ [{t_ac} ({AC_score:.1f}/5)]: Yol tahliyesi, enkaz açıklığı ve acil müdahale gücünü ölçer "
        + "(AC arttıkça kırılganlık azalır). Ölçülen: " + ", ".join(ac_facts) + "."
    )

    # Deprem neden yüksek/düşük gerekçesi
    if not has_built:
        deprem_gerekce = (
            f"{t_dep} Deprem Kırılganlığı (V={V_deprem:.1f}/5): Bölgede yerleşik yapı ve nüfus bulunmadığı için "
            f"({n_bldg} bina, {int(round(nufus))} kişi) doğrudan yapısal yıkım ve can kaybı riski düşüktür"
            + (f" (diri fay mesafesi {float(fay_m):.0f} m)." if fay_m is not None else ".")
        )
    else:
        dep_drivers = []
        if fay_min is not None and float(fay_min) <= 35.0 and fay_m is not None:
            dep_drivers.append(f"diri fay hattı bölgeden doğrudan geçmektedir (min. {float(fay_min):.0f} m, ort. {float(fay_m):.0f} m)")
        elif fay_m is not None and float(fay_m) <= 600.0:
            dep_drivers.append(f"diri faya çok yakın konum ({float(fay_m):.0f} m)")
        elif fay_m is not None and float(fay_m) <= 1300.0:
            dep_drivers.append(f"fay etki kuşağına yakınlık ({float(fay_m):.0f} m)")
        if kotu >= 0.18:
            dep_drivers.append(f"kötü durumdaki yapı oranı yüksek (%{kotu * 100:.0f})")
        if bitisik >= 0.40:
            dep_drivers.append(f"bitişik nizam çekiçleme/çarpışma riski (%{bitisik * 100:.0f})")
        if taks >= 0.45:
            dep_drivers.append(f"yoğun taban alanı sıkışıklığı (TAKS %{taks * 100:.0f})")
        if kat >= 3.5:
            dep_drivers.append(f"yüksek kat yoğunluğu (ort. {kat:.1f} kat)")
        if hw_ratio is not None and hw_ratio >= 1.4:
            dep_drivers.append(f"sokak enkaz kapanma riski yüksek (H/W={hw_ratio:.2f})")
        if dead_ratio is not None and dead_ratio >= 0.25:
            dep_drivers.append(f"çıkmaz sokak oranı (%{dead_ratio * 100:.0f}) tahliyeyi zorlaştırır")
        if dens >= 75.0:
            dep_drivers.append(f"yüksek yerleşik nüfus ({int(round(nufus))} kişi, {dens:.0f} kişi/ha)")
        if yg is not None and float(yg) < 8.5:
            dep_drivers.append(f"dar tahliye yolları (ort. {float(yg):.1f} m)")
        if toplanma_m is not None and float(toplanma_m) > 650.0:
            dep_drivers.append(f"toplanma alanına uzaklık ({float(toplanma_m):.0f} m)")
        if not dep_drivers:
            prot = []
            if fay_m is not None and float(fay_m) >= 1200.0:
                prot.append(f"güvenli fay uzaklığı ({float(fay_m):.0f} m)")
            if taks < 0.20:
                prot.append(f"seyrek yapılaşma (TAKS %{taks * 100:.0f})")
            if yg is not None and float(yg) >= 10.0:
                prot.append(f"geniş tahliye aksları (ort. {float(yg):.1f} m)")
            if hw_ratio is not None and hw_ratio < 1.0:
                prot.append(f"düşük enkaz tıkanma riski (H/W={hw_ratio:.2f})")
            dep_drivers = prot or [f"{int(round(nufus))} nüfuslu {kat:.1f} katlı mevcut doku dengesi"]
        deprem_gerekce = (
            f"{t_dep} Deprem Kırılganlığı (V={V_deprem:.1f}/5 = [E:{E_deprem:.1f} × S:{S_deprem:.1f}] / AC:{AC_deprem:.1f}): "
            + "Belirleyici nedenler -> " + ", ".join(dep_drivers[:8]) + "."
        )

    # Sel/Taşkın neden yüksek/düşük gerekçesi
    sel_drivers = []
    if dere_min is not None and float(dere_min) <= 35.0 and dere_m is not None:
        sel_drivers.append(f"akarsu yatağı bölgeden geçiyor (min. {float(dere_min):.0f} m, ort. {float(dere_m):.0f} m)")
    elif dere_m is not None and float(dere_m) <= 250.0:
        sel_drivers.append(f"akarsu/dere yatağına çok yakın ({float(dere_m):.0f} m)")
    elif dere_m is not None and float(dere_m) <= 600.0:
        sel_drivers.append(f"dere taşkın tamponuna yakın ({float(dere_m):.0f} m)")
    if risk_share >= 0.10:
        sel_drivers.append(f"taşkın risk alanı örtüşmesi (%{risk_share * 100:.0f})")
    if taks >= 0.35:
        sel_drivers.append(f"yüksek geçirimsiz zemin (TAKS %{taks * 100:.0f})")
    if rakim is not None and float(rakim) <= 65.0:
        sel_drivers.append(f"düşük kot / çukur zemin ({float(rakim):.0f} m rakım)")
    if not sel_drivers:
        if not has_built:
            sel_drivers.append(f"yüksek toprak geçirgenliği (%{gecirimli * 100:.0f}) ve yapı bulunmaması")
        else:
            if dere_m is not None:
                sel_drivers.append(f"akarsuya güvenli mesafe ({float(dere_m):.0f} m)")
            sel_drivers.append(f"geçirimli açık yüzey %{gecirimli * 100:.0f}")
    sel_gerekce = (
        f"{t_sel} Sel Kırılganlığı (V={V_sel:.1f}/5 = [E:{E_sel:.1f} × S:{S_sel:.1f}] / AC:{AC_sel:.1f}): "
        + "Belirleyici nedenler -> " + ", ".join(sel_drivers[:4]) + "."
    )

    return {
        "E_tier": t_e,
        "S_tier": t_s,
        "AC_tier": t_ac,
        "E_score": r(E_score, 2),
        "S_score": r(S_score, 2),
        "AC_score": r(AC_score, 2),
        "deprem_kirilganlik": t_dep,
        "sel_kirilganlik": t_sel,
        "genel_kirilganlik": t_gen,
        "E_aciklama": E_aciklama,
        "S_aciklama": S_aciklama,
        "AC_aciklama": AC_aciklama,
        "maruziyet_nedeni": E_aciklama,
        "hassasiyet_nedeni": S_aciklama,
        "uyum_nedeni": AC_aciklama,
        "deprem_gerekce": deprem_gerekce,
        "sel_gerekce": sel_gerekce,
    }


def zone_record(z):
    p = z.get("pay") or {}

    def pc(k):
        return r(p[k] * 100, 1) if k in p else None

    e = z.get("ext") or {}
    ha = z["area"] / 10000.0 if z["area"] > 0 else 1.0
    kotu_pct, sit2_pct, sit3_pct = get_extra_Sit_params(z)
    vuln = compute_vulnerability(z)
    z["vuln"] = vuln
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
        "Bitisik_Nizam_Orani_Yuzde": r(z["bitisik"] * 100, 1) if z.get("bitisik") is not None else None,
        "Kotu_Durumdaki_Yapi_Orani_Yuzde": r(kotu_pct, 1),
        "Tescilli_Alan_Orani_sit2_Yuzde": r(sit2_pct, 1),
        "Afet_Risk_Donusum_sit3_Yuzde": r(sit3_pct, 1),
        "Toplam_Nufus_Kisi": r(z["nufus"], 0),
        "Nufus_Yogunlugu_Kisi_Ha": r(z["nufus"] / ha, 1),
        "Ortalama_Yol_Genisligi_m": r(z.get("yg"), 1),
        "Baskin_Yol_Kaplamasi": z.get("rkap_dom"),
        "Baskin_Yol_Kademesi": z.get("rtur_dom"),
        "Ortalama_Egim_Yuzde": r(z.get("egim"), 1),
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
        "FSI_Emsal_Tahmini": r(z.get("fsi"), 2),
        "OSR_Acik_Alan_Orani": r(z.get("osr"), 2),
        "Spacematrix_Tipolojisi": z.get("spacematrix_tip"),
        "Sokak_Enkaz_Orani_H_W": r(z.get("hw_ratio"), 2),
        "Sokak_Tahliye_Riski_Sinifi": z.get("hw_sinif"),
        "Cikmaz_Sokak_Orani_Yuzde": r(z["cikmaz_sokak_orani"] * 100, 1) if z.get("cikmaz_sokak_orani") is not None else None,
        "Kisi_Basi_Donati_m2": r(z.get("kisi_basi_donati_m2"), 1),
        "Karma_Kullanim_Entropi": r(z.get("karma_entropi"), 2),
        "Deprem_Kirilganlik_Sinifi": vuln["deprem_kirilganlik"],
        "Sel_Kirilganlik_Sinifi": vuln["sel_kirilganlik"],
        "Genel_Kirilganlik_Sinifi": vuln["genel_kirilganlik"],
        "Maruz_Kalma_Derecesi": vuln["E_tier"],
        "Hassasiyet_Derecesi": vuln["S_tier"],
        "Uyum_Kapasitesi_Derecesi": vuln["AC_tier"],
        "Deprem_Kirilganlik_Gerekcesi": vuln["deprem_gerekce"],
        "Sel_Kirilganlik_Gerekcesi": vuln["sel_gerekce"],
        "Maruz_Kalma_Aciklamasi": vuln["E_aciklama"],
        "Hassasiyet_Aciklamasi": vuln["S_aciklama"],
        "Uyum_Kapasitesi_Aciklamasi": vuln["AC_aciklama"],
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

    is_custom = bool(res.get("is_custom_zones", False))
    mode = res.get("mode", "advanced")
    prefix = "M" if mode == "advanced" else "A"
    n_z = max(1, len(res.get("zones", [])))
    uri = f"MultiPolygon?crs={crs.authid()}" if crs and crs.isValid() else "MultiPolygon"
    if is_custom:
        layer_name = f"Hazir_Bolgeler_Hizli_Ozet_{n_z}" if quick_only else f"Hazir_Bolgeler_Analizi_{n_z}"
    else:
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

    # SIFIR ÖRTÜŞME / DÜZLEMSEL BÖLÜNTÜ GÜVENCESİ (Sadece eklenti tarafından üretilen bölgelerde)
    zones = res.get("zones", [])
    if not is_custom:
        for i in range(len(zones)):
            gi = zones[i]["geom"]
            if gi is None or gi.isEmpty():
                continue
            for j in range(i + 1, len(zones)):
                gj = zones[j]["geom"]
                if gj is None or gj.isEmpty():
                    continue
                if gi.boundingBox().intersects(gj.boundingBox()):
                    inter = gi.intersection(gj)
                    if inter and not inter.isEmpty() and inter.area() > 1.0:
                        if zones[i]["area"] >= zones[j]["area"]:
                            diff_g = gj.difference(gi)
                            parts_j = [p for p in poly_parts(diff_g) if p and not p.isEmpty() and p.area() > 1.0]
                            if parts_j:
                                new_gj = _to_clean_multipolygon(QgsGeometry.unaryUnion(parts_j) if len(parts_j) > 1 else parts_j[0])
                                if new_gj and not new_gj.isEmpty():
                                    zones[j]["geom"] = new_gj
                                    zones[j]["area"] = new_gj.area()
                        else:
                            diff_g = gi.difference(gj)
                            parts_i = [p for p in poly_parts(diff_g) if p and not p.isEmpty() and p.area() > 1.0]
                            if parts_i:
                                new_gi = _to_clean_multipolygon(QgsGeometry.unaryUnion(parts_i) if len(parts_i) > 1 else parts_i[0])
                                if new_gi and not new_gi.isEmpty():
                                    zones[i]["geom"] = new_gi
                                    zones[i]["area"] = new_gi.area()
                                    gi = new_gi

    feats, clean_records = [], []
    for z, raw_rec in zip(res["zones"], raw_records):
        filtered_rec = {n: raw_rec[n] for n, _ in active_fields}
        if "Bolge_Alani_m2" in filtered_rec:
            filtered_rec["Bolge_Alani_m2"] = r(z["area"], 0)
        if "Bolge_Alani_Ha" in filtered_rec:
            filtered_rec["Bolge_Alani_Ha"] = r(z["area"] / 10000.0, 2)
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
    "FSI_Emsal_Tahmini": "Emsal / FSI (Brüt Yapı Yoğunluğu)",
    "OSR_Acik_Alan_Orani": "OSR Açık Alan Oranı [(1-TAKS)/FSI]",
    "Spacematrix_Tipolojisi": "Spacematrix Doku Tipolojisi (GSI-FSI-L)",
    "Sokak_Enkaz_Orani_H_W": "Sokak Enkaz Riski (H/W = 3m·Kat/Yol)",
    "Sokak_Tahliye_Riski_Sinifi": "Sokak Kanyonu Tahliye Riski",
    "Cikmaz_Sokak_Orani_Yuzde": "Çıkmaz Sokak Oranı (%)",
    "Kisi_Basi_Donati_m2": "Kişi Başı Aktif Donatı (m²/kişi — MPYY)",
    "Karma_Kullanim_Entropi": "Karma Kullanım Çeşitliliği (Shannon H 0-1)",
    "Deprem_Kirilganlik_Sinifi": "Deprem Kırılganlık Sınıfı",
    "Sel_Kirilganlik_Sinifi": "Sel Kırılganlık Sınıfı",
    "Genel_Kirilganlik_Sinifi": "Genel Kırılganlık Sınıfı",
    "Maruz_Kalma_Derecesi": "Maruz Kalma (E)",
    "Hassasiyet_Derecesi": "Hassasiyet (S)",
    "Uyum_Kapasitesi_Derecesi": "Uyum Kapasitesi (AC)",
    "Maruz_Kalma_Aciklamasi": "Maruz Kalma (E) Tanımı ve Nedeni",
    "Hassasiyet_Aciklamasi": "Hassasiyet (S) Tanımı ve Nedeni",
    "Uyum_Kapasitesi_Aciklamasi": "Uyum Kapasitesi (AC) Tanımı ve Nedeni",
    "Deprem_Kirilganlik_Gerekcesi": "Deprem Kırılganlığı Gerekçesi (Neden Yüksek/Düşük?)",
    "Sel_Kirilganlik_Gerekcesi": "Sel/Taşkın Kırılganlığı Gerekçesi",
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
            if k in (
                "Bolgeleme_ve_Ayrim_Gerekcesi", "Komsu_Bolgelerden_Ayrim_Nedeni",
                "Kisa_Birlestirme_ve_Ayrim_Ozeti", "Kisa_Metrik_Ozeti", "Olculen_Ozet",
                "Maruz_Kalma_Aciklamasi", "Hassasiyet_Aciklamasi", "Uyum_Kapasitesi_Aciklamasi",
                "Deprem_Kirilganlik_Gerekcesi", "Sel_Kirilganlik_Gerekcesi"
            ):
                ws.column_dimensions[col_letter].width = 56
            elif k in ("Baskin_Karakter", "Mudahale_Karari", "Plan_Karsiligi", "Kisa_Komsu_Ayrim_Nedeni", "Spacematrix_Tipolojisi", "Sokak_Tahliye_Riski_Sinifi"):
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
        "Deprem_Kirilganlik_Sinifi", "Deprem_Kirilganlik_Gerekcesi",
        "Sel_Kirilganlik_Sinifi", "Sel_Kirilganlik_Gerekcesi",
        "Genel_Kirilganlik_Sinifi", "Maruz_Kalma_Derecesi", "Maruz_Kalma_Aciklamasi",
        "Hassasiyet_Derecesi", "Hassasiyet_Aciklamasi",
        "Uyum_Kapasitesi_Derecesi", "Uyum_Kapasitesi_Aciklamasi",
        "Mudahale_Karari", "Plan_Karsiligi"
    ]
    _populate_sheet(ws1, q_recs, col_keys=quick_Sheet_cols, freeze_cell="D2")

    # Sayfa 2: Temel Sayısal Metrikler Tablosu (Sayısal analiz / grafik için)
    ws2 = wb.create_sheet(title="2_Sayisal_Planlama_Tablosu")
    num_cols = [
        "Bolge_Kodu", "Bolge_No", "Baskin_Karakter", "Bolge_Alani_Ha", "Bolge_Alani_m2",
        "Ada_Hucre_Sayisi", "Toplam_Bina_Sayisi", "Toplam_Nufus_Kisi", "Nufus_Yogunlugu_Kisi_Ha",
        "Taban_Alani_Orani_TAKS_Yuzde", "FSI_Emsal_Tahmini", "OSR_Acik_Alan_Orani",
        "Spacematrix_Tipolojisi", "Ortalama_Kat_Sayisi", "Baskin_Yapi_Nizami",
        "Ortalama_Yol_Genisligi_m", "Sokak_Enkaz_Orani_H_W", "Cikmaz_Sokak_Orani_Yuzde",
        "Kisi_Basi_Donati_m2", "Karma_Kullanim_Entropi",
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
