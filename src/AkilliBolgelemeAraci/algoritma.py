# -*- coding: utf-8 -*-
"""QGIS'ten bağımsız saf-Python algoritma çekirdeği.

1) Mekansal Planlar Yapım Yönetmeliği (MPYY Madde 5) esaslarına göre arazi kullanımı ve donatı sınıflandırma
2) Mekânsal kısıtlı Ward birleştirme (yalnız KOMŞU hücreler birleşir)
3) Macar algoritması (parça <-> Excel gerekçe satırı eşleştirme)
4) Excel 'Aşama 1' gerekçe satırlarının sayısal profilleri
"""
import math
import re
import heapq

_TR = str.maketrans({"İ": "i", "I": "i", "ı": "i", "Ş": "s", "ş": "s", "Ğ": "g", "ğ": "g",
                     "Ü": "u", "ü": "u", "Ö": "o", "ö": "o", "Ç": "c", "ç": "c"})


def norm_tr(s):
    return str(s).translate(_TR).lower().strip()


LU_ORDER = ["sit", "sanayi", "tarim", "ticaret", "donati", "konut"]
LU_KEYS = {
    "sit": ("sit", "tescil", "tarihi", "anit", "koruma", "arkeolojik", "kentselsit", "dogalsit", "arkeolojiksit"),
    "sanayi": (
        "sanayi", "imalat", "fabrika", "depo", "atolye", "uretim", "lojistik", "osb",
        "kucuk sanayi", "kucuksanayi", "organizesanayi", "endustri", "antrepo", "toplu isyer",
        "toptanci", "ambar", "hurda", "marangoz", "oto tamir", "kdkca", "calisma alani", "kss"
    ),
    "tarim": (
        "tarim", "tarla", "bag", "bahce", "zeytin", "bos", "arsa", "ciftlik",
        "sera", "ziraat", "ahir", "mera", "ham", "ovasi", "cayir", "fidanlik",
        "mutlaktarim", "dikilitarim", "marjinaltarim", "bagbahce", "tarisal"
    ),
    "ticaret": (
        "ticar", "dukkan", "magaza", "carsi", "market", "ofis", "banka", "otel", "lokanta",
        "restoran", "kafe", "cafe", "pazar", "is merkezi", "ismerkezi", "buro", "firin", "turizm", "konaklama",
        "alisveris", "avm", "oto galeri", "hizmet", "merkezi is", "mia", "tick", "t+k", "k+t"
    ),
    "donati": (
        "okul", "ilkokul", "ortaokul", "lise", "anaokul", "egitim", "kolej", "universite", "kampus", "kurs", "yurt",
        "saglik", "hastane", "poliklinik", "dispanser", "asm", "aile saglik", "ailesaglik", "rehabilitasyon",
        "cami", "mescit", "ibadet", "dini", "kilise", "havra", "cemevi", "kulliye",
        "kultur", "kutuphane", "halk egitim", "sergi", "galeri", "muze", "konser", "konferans", "kongre", "sinema", "tiyatro", "opera",
        "sosyal", "kres", "cocuk yuvasi", "yetistirme", "bakimevi", "huzurevi", "sefkat", "toplum merkezi",
        "resmi", "idari", "kamu", "belediye", "hukumet", "kaymakamlik", "valilik", "muhtarlik", "karakol", "emniyet", "jandarma", "adliye",
        "itfaiye", "acil yardim", "kurtarma", "zabita", "mezbaha", "pazar yeri", "pazaryeri",
        "park", "cocuk bahcesi", "cocukbahcesi", "oyun alani", "oyunalani", "meydan", "rekreasyon", "yesil", "pasifyesil", "aktifyesil",
        "spor", "stadyum", "halisaha", "kapali spor", "mezarlik", "kabristan", "gomutluk", "agaclandirilacak", "mesire",
        "teknik altyapi", "teknikaltyapi", "trafo", "aritma", "atik", "otopark", "garaj", "otogar", "terminal", "gar", "istasyon", "su deposu", "enerji", "donati"
    ),
    "konut": (
        "konut", "mesken", "apart", "villa", "ikamet", "yasam", "bitisik", "ev",
        "rezidans", "site", "lojm", "karma", "yerlesim", "yerlesik", "t+k", "k+t", "tick",
        "dusukkonut", "seyrekkonut", "ortakonut", "yuksekkonut", "gelismekonut", "kirsalkonut", "mevcutkonut"
    ),
}

ROAD_MEDIAN_WORDS = ("orta refuj", "refuj", "kavsak adasi", "trafik adasi", "donel kavsak", "kaldirim")
REAL_USE_WORDS = (
    "konut", "ticaret", "ticari", "karma", "sanayi", "tarim", "donati", "okul", "cami",
    "park", "saglik", "sit", "mesken", "mezar", "kabristan", "yesil", "egitim", "resmi", "belediye"
)


def is_road_island_text(text):
    if not text:
        return False
    t = norm_tr(text)
    if any(u in t for u in REAL_USE_WORDS):
        return False
    return any(w in t for w in ROAD_MEDIAN_WORDS)


def classify_landuse_subtypes(text):
    """
    Mevcut imar adalarındaki (mevcut_ada) ince ayrımları ve bitişik/farklı yazımları yakalar:
    - 'dusukkonut', 'seyrekkonut', 'düşük yoğunluklu konut', 'gelişme konut', 'kırsal konut' -> konut_dusuk_seyrek
    - 'ortakonut', 'yuksekkonut', 'orta/yüksek yoğunluklu konut', 'yerleşik konut' -> konut_orta_yuksek
    - 'mezarlık alanı', 'mezarlik', 'kabristan' -> mezarlik (gerçek mezarlık alanı olarak ayrılır)
    - 'okul', 'ilkokul', 'lise', 'sağlık', 'asm', 'hastane', 'cami', 'resmi' -> donati_aktif_hizmet
    - 'park', 'yeşil alan', 'çocuk bahçesi', 'pasif yeşil', 'rekreasyon' -> donati_yesil
    - 'boş', 'arsa', 'ham toprak', 'rezerv', 'yapılaşmamış' -> bos_arazi
    """
    out = {
        "konut_dusuk_seyrek": 0.0,
        "konut_orta_yuksek": 0.0,
        "karma_ticaret_konut": 0.0,
        "mezarlik": 0.0,
        "donati_aktif_hizmet": 0.0,
        "donati_yesil": 0.0,
        "bos_arazi": 0.0,
    }
    if text is None:
        return out
    t = norm_tr(text)
    if not t:
        return out
    t_compact = re.sub(r"[\s_\-]+", "", t)

    # 1) Mezarlık kontrolü
    if any(w in t or w in t_compact for w in ("mezarlik", "mezar", "kabristan", "gomutluk", "asrimezar")):
        out["mezarlik"] = 1.0
        return out

    # 2) Boş / Arsa / Rezerv kontrolü
    toks = re.findall(r"[a-z0-9]+", t)
    if any(w in toks for w in ("bos", "arsa", "ham", "rezerv")) or any(
        w in t_compact for w in ("bosada", "bosarazi", "bosparsel", "hamtoprak", "yapilasmamis", "rezervalan")
    ):
        out["bos_arazi"] = 1.0

    # 3) Konut yoğunluk ve seyrek/düşük vs orta/yüksek ayrımı
    has_konut = ("konut" in t or "konut" in t_compact or "mesken" in t or "villa" in t or "apart" in t or "yerlesik" in t or "yerlesim" in t)
    has_ticaret = ("ticar" in t or "ticar" in t_compact or "karma" in t or "tick" in toks or "t+k" in t or "k+t" in t)
    if has_konut and has_ticaret:
        out["karma_ticaret_konut"] = 1.0
    if has_konut:
        is_low_sparse = any(
            w in t or w in t_compact
            for w in (
                "dusuk", "seyrek", "az", "kirsal", "gelisme", "villa", "bagevi",
                "dusukkonut", "seyrekkonut", "azyogun", "kirsalkonut", "gelismekonut", "bahceli"
            )
        )
        if is_low_sparse:
            out["konut_dusuk_seyrek"] = 1.0
        else:
            out["konut_orta_yuksek"] = 1.0

    # 4) Donatı alt türleri (Okul/Sağlık/Sosyal vs Yeşil/Park)
    if any(
        w in t or w in t_compact
        for w in (
            "okul", "ilkokul", "ortaokul", "lise", "anaokul", "egitim", "kolej", "universite", "kampus", "kres",
            "saglik", "hastane", "asm", "ailesaglik", "poliklinik", "dispanser",
            "cami", "mescit", "ibadet", "dini", "kultur", "sosyal", "resmi", "idari", "belediye", "kamu", "hukumet", "karakol", "itfaiye"
        )
    ):
        out["donati_aktif_hizmet"] = 1.0

    if any(
        w in t or w in t_compact
        for w in ("park", "yesil", "cocukbahce", "oyunalan", "rekreasyon", "mesire", "spor", "agaclandir", "kentorman")
    ):
        out["donati_yesil"] = 1.0

    return out


def classify_landuse(text):
    if text is None:
        return {}
    t = norm_tr(text)
    if not t:
        return {}
    t_compact = re.sub(r"[\s_\-]+", "", t)
    toks = re.findall(r"[a-z0-9]+", t)
    hit = []
    for cls in LU_ORDER:
        for key in LU_KEYS[cls]:
            if " " in key or "+" in key:
                ok = (key in t) or (key.replace(" ", "") in t_compact)
            elif key in ("ev", "bag", "bos", "ham", "gar", "asm", "mia", "avm", "osb", "kss"):
                ok = key in toks
            elif key == "sit":
                # "site", "sitesi", "siteler" yapı/sanayi yerleşkesi kelimelerini koruma sit alanı sayma
                ok = any(tok in ("sit", "siti", "sitler", "kentselsit", "dogalsit", "arkeolojiksit") or tok.startswith("sit-") for tok in toks)
            elif len(key) >= 4:
                # 'dusukkonut', 'seyrekkonut', 'ortakonut', 'yuksekkonut', 'mezarlikalani', 'mutlaktarim' gibi bitişik yazımları da yakala
                ok = any((key in tok) for tok in toks) or (key in t_compact)
            else:
                ok = any(tok.startswith(key) for tok in toks)
            if ok:
                hit.append(cls)
                break
    if ("karma" in t or "tick" in toks) and "ticaret" not in hit:
        hit.append("ticaret")
    if ("karma" in t or "tick" in toks) and "konut" not in hit:
        hit.append("konut")
    if not hit:
        return {"diger": 1.0}
    if "sanayi" in hit and "konut" not in hit:
        return {"sanayi": 1.0}
    if "sit" in hit and "konut" not in hit and "ticaret" not in hit:
        return {"sit": 1.0}
    w = 1.0 / len(hit)
    return {c: w for c in hit}


def median(v):
    s = sorted(v)
    n = len(s)
    if n == 0:
        return 0.0
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def zscore_columns(cols, clip=3.0):
    out, dropped = {}, []
    for k, v in cols.items():
        n = len(v)
        if n == 0:
            dropped.append(k)
            continue
        m = sum(v) / n
        sd = math.sqrt(sum((x - m) ** 2 for x in v) / n)
        if sd < 1e-9:
            dropped.append(k)
            continue
        out[k] = [max(-clip, min(clip, (x - m) / sd)) for x in v]
    return out, dropped


def percentile_rank(values):
    n = len(values)
    if n <= 1:
        return [0.5] * n
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        r = (i + j) / 2.0 / (n - 1)
        for k in range(i, j + 1):
            ranks[order[k]] = r
        i = j + 1
    return ranks


def connect_components(adj, pts):
    n = len(pts)
    while True:
        comp = [-1] * n
        comps = []
        for s in range(n):
            if comp[s] != -1:
                continue
            cid = len(comps)
            stack, members = [s], []
            comp[s] = cid
            while stack:
                u = stack.pop()
                members.append(u)
                for v in adj[u]:
                    if comp[v] == -1:
                        comp[v] = cid
                        stack.append(v)
            comps.append(members)
        if len(comps) <= 1:
            return len(comps)
        small = min(comps, key=len)
        sc = comp[small[0]]
        best = None
        for u in small:
            for v in range(n):
                if comp[v] == sc:
                    continue
                d = (pts[u][0] - pts[v][0]) ** 2 + (pts[u][1] - pts[v][1]) ** 2
                if best is None or d < best[0]:
                    best = (d, u, v)
        adj[best[1]].add(best[2])
        adj[best[2]].add(best[1])


def ward_merge(vecs, node_w, areas, adj, target_k, area_cap=None, cap_pow=2.0, eps=0.05, affinity_fn=None):
    n = len(vecs)
    dim = len(vecs[0]) if n else 0
    W = list(node_w)
    A = list(areas)
    V = [list(v) for v in vecs]
    members = {i: [i] for i in range(n)}
    nb = {i: set(adj[i]) for i in range(n)}
    ver = [0] * n
    alive = set(range(n))

    def cost(a, b):
        d2 = 0.0
        va, vb = V[a], V[b]
        for k in range(dim):
            d = va[k] - vb[k]
            d2 += d * d
        c = W[a] * W[b] / (W[a] + W[b]) * (d2 + eps)
        # Kucuk hucrelerin / tekil adalarin erken asamada komsusuna kaynasmasini tesvik et (M9 gibi tek ada bolge kalmasini onler)
        if len(members[a]) <= 1 or len(members[b]) <= 1:
            c *= 0.35
        elif A[a] < 20000.0 or A[b] < 20000.0:
            c *= 0.60
        cap_factor = 1.0
        if affinity_fn is not None:
            aff = affinity_fn(members[a], members[b])
            if isinstance(aff, (tuple, list)):
                c *= aff[0]
                cap_factor = aff[1] if len(aff) > 1 else 1.0
            else:
                c *= aff
        if area_cap and cap_factor > 0.0:
            c *= 1.0 + cap_factor * (((A[a] + A[b]) / area_cap) ** cap_pow)
        return c

    heap = []
    for a in range(n):
        for b in nb[a]:
            if a < b:
                heapq.heappush(heap, (cost(a, b), a, b, 0, 0))

    while len(alive) > target_k and heap:
        c, a, b, va, vb = heapq.heappop(heap)
        if a not in alive or b not in alive or ver[a] != va or ver[b] != vb:
            continue
        wa, wb = W[a], W[b]
        V[a] = [(wa * x + wb * y) / (wa + wb) for x, y in zip(V[a], V[b])]
        W[a] = wa + wb
        A[a] += A[b]
        members[a].extend(members.pop(b))
        alive.discard(b)
        nb[a] |= nb[b]
        nb[a].discard(a)
        nb[a].discard(b)
        for x in nb[b]:
            nb[x].discard(b)
            if x != a:
                nb[x].add(a)
        ver[a] += 1
        for x in nb[a]:
            heapq.heappush(heap, (cost(a, x), min(a, x), max(a, x), ver[min(a, x)], ver[max(a, x)]))

    labels = [0] * n
    for lab, root in enumerate(sorted(alive)):
        for m in members[root]:
            labels[m] = lab
    return labels


def hungarian(cost):
    n = len(cost)
    m = len(cost[0]) if n else 0
    if n > m:
        raise ValueError("satır sayısı sütun sayısını aşamaz")
    INF = float("inf")
    u = [0.0] * (n + 1)
    v = [0.0] * (m + 1)
    p = [0] * (m + 1)
    way = [0] * (m + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = INF
            j1 = 0
            for j in range(1, m + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j] = cur
                        way[j] = j0
                    if minv[j] < delta:
                        delta = minv[j]
                        j1 = j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    res = [-1] * n
    for j in range(1, m + 1):
        if p[j]:
            res[p[j] - 1] = j - 1
    return res


_D = {"E": (1, 0), "W": (-1, 0), "N": (0, 1), "S": (0, -1),
      "NE": (0.707, 0.707), "NW": (-0.707, 0.707), "SE": (0.707, -0.707), "SW": (-0.707, -0.707)}

EXCEL_ROWS = [
    # (code, character, narrative, feature targets, direction hint,
    #  dominant combination, planning intervention, plan equivalent)
    ("A1", "Kentsel Gelişme Alanı (Boş Arazi + Yeni Yapılaşma)",
     "Kentsel gelişimin yöneldiği; geniş boş arazilerin ve yeni yapılaşmaların birlikte görüldüğü gelişme bölgesi.",
     {"bos_arazi": .8, "konut": .5, "dens": .2, "merkez": .3}, "W",
     "Yüksek boş arazi oranı + yeni ve seyrek yapılaşma + düşük TAKS + altyapı bekleyen adalar",
     "Etaplı gelişme, altyapı ve donatı rezervi ayrılması, yeni yapılaşmada yoğunluk kontrolü",
     "1/5000 NİP: Kentsel Gelişme Alanı; 1/1000 UİP: Yeni konut adaları, donatı rezervi ve yol omurgası"),

    ("A2", "Sit Alanı ve Sağlık Kampüsü Çevresi (Gelişme ve Tampon Alanı)",
     "Sit alanı ile hastane (sağlık donatısı) çevresinde yeni yapılaşmaların ve boş arazilerin yer aldığı alan; sanayiye karşı yeşil tampon görevi görebilir.",
     {"sit": .6, "donati": .6, "bos_arazi": .6, "dens": .25, "sanayi": .2}, "N",
     "Sit alanı + büyük ölçekli sağlık donatısı + boş araziler + yeni yapılaşma + sanayi komşuluğu",
     "Sit koruma kararlarıyla uyumlu sınırlı yapılaşma; sanayi ile yerleşim arasında yeşil alan tamponu kurulması",
     "1/5000 NİP: Koruma-Gelişme Geçiş Alanı ve Yeşil Tampon; 1/1000 UİP: Sit koruma plan notları, tampon yeşil alan, sağlık tesisi alanı"),

    ("A3", "Düzenli Doku ve Dengeli Donatı Dağılımı (Ova Sınırı)",
     "Donatıların düzgün dağıldığı, düzenli parselasyonlu yerleşik doku; geniş ova/tarım alanıyla sınır oluşturan kuşak.",
     {"konut": .7, "donati": .7, "dens": .5, "merkez": .5, "tarim": .15}, None,
     "Düzenli ada formu + dengeli donatı dağılımı + orta yoğunluk + tarım alanı sınırı",
     "Donatı dengesinin korunması; tarım alanı sınırında yerleşme sınırı ve yeşil çeper tanımlanması",
     "1/5000 NİP: Yerleşik Konut ve Donatı Alanı; 1/1000 UİP: Donatı adaları ve yerleşme sınırı"),

    ("A4", "Kent Merkezi (Ticaret + Konut + Eğitim/Kamu Çekirdeği)",
     "Ticaret ve konutun iç içe geçtiği, yükseköğretim ve kamu hizmetlerinin yoğunlaştığı kentin kalbi.",
     {"ticaret": .6, "konut": .5, "donati": .6, "merkez": .95, "dens": .85}, None,
     "Karma ticaret-konut + eğitim/kamu donatıları + en yüksek merkezilik + yüksek yoğunluk",
     "Merkezi iş alanı kapasitesinin korunması, yaya/toplu taşıma önceliği, otopark ve kamusal alan düzenlemesi",
     "1/5000 NİP: Kent Merkezi (MİA) ve Eğitim-Kamu Alanı; 1/1000 UİP: Ticaret-Konut karma adaları ve yaya aksları"),

    ("A5", "Düzenli Yapı Alanı (Mevcut Yoğunluk Korunacak)",
     "Düzenli yapı adalarından oluşan; ileride plan kararlarında mevcut yoğunluğun aynı kalması öngörülen yerleşik alan.",
     {"konut": .8, "dens": .6, "merkez": .6, "bitisik": .5}, None,
     "Düzenli ada formu + standart TAKS/KAKS + dengeli yoğunluk",
     "Mevcut yoğunluğun dondurulması, yeni imar hakkı verilmemesi, donatı ve açık alanların korunması",
     "1/5000 NİP: Yerleşik Konut Alanı (yoğunluk korunur); 1/1000 UİP: Mevcut yapılaşma koşullarının devamı"),

    ("A6", "Ticaret ve Konut+Ticaret Yoğunlaşma Alanı (Depolar, Izgara Form)",
     "Ticaret ve konut+ticaret kullanımlarının yoğunlaştığı, depoların da bulunduğu ızgara formlu aks.",
     {"ticaret": .75, "karma": .7, "sanayi": .25, "dens": .6, "merkez": .65}, None,
     "Ticaret ve karma kullanım yoğunlaşması + depolama + düzenli ızgara yol dokusu",
     "Yükleme-boşaltma ve otopark düzenlemesi, depoların yerleşimle uyumlu hale getirilmesi, servis yolu organizasyonu",
     "1/5000 NİP: Ticaret-Konut Karma Alanı; 1/1000 UİP: Ticaret + depolama adaları ve servis yolları"),

    ("A7", "Kentsel Sit İçi Tarihi Doku ve Pazar Alanı (Kent Kalbi)",
     "Kentsel sit alanı içindeki tarihi doku; pazar alanı ve tescilli yapılarla kentin simgesel merkezi.",
     {"sit": .9, "merkez": .9, "ticaret": .5, "dens": .85}, None,
     "Kentsel sit sınırı + tescilli yapı yoğunluğu + pazar alanı + dar sokak dokusu + yüksek yaya akışı",
     "Koruma-kullanma dengesi, cephe sağlıklaştırma, yayalaştırma ve pazar alanının korunması",
     "1/5000 NİP: Kentsel Sit Alanı; 1/1000 UİP: Koruma Amaçlı İmar Planı (KAİP) hükümleri"),

    ("A8", "Merkezi Ticaret Dokusu",
     "Dar sokaklı, küçük dükkanların ve ticari yapıların bulunduğu merkez bölgesi.",
     {"ticaret": .6, "merkez": .9, "dens": .9}, None,
     "Küçük ölçekli zemin ticaret + dar sokaklar + yüksek yoğunluk + merkeze yakınlık",
     "Trafik sakinleştirme, yayalaştırma saatleri, cephe ve tabela düzenlemesi",
     "1/5000 NİP: Ticaret Alanı; 1/1000 UİP: Ticaret + konut karma adaları"),

    ("A9", "Konut (Mahalle Dokusu)",
     "Konut ağırlıklı olan, dışarıdaki boş alanlara açılan mahalle dokusu.",
     {"konut": .7, "dens": .4, "merkez": .4}, None,
     "Konut ağırlıklı ada + orta-düşük yoğunluk + çepere açılan mahalle yapısı",
     "Mahalle donatılarının tamamlanması, çeper ile geçişin yeşil kuşakla tanımlanması",
     "1/5000 NİP: Yerleşik Konut Alanı; 1/1000 UİP: Konut adaları ve mahalle donatıları"),

    ("A10", "Gelişme Konut Alanı",
     "Doğuya doğru yeni büyüyen, yeni evlerin yapılmaya başlandığı konut bölgesi.",
     {"konut": .6, "dens": .25, "merkez": .35}, "E",
     "Yeni konut yapılaşması + düşük TAKS + altyapının tamamlanmakta olduğu adalar",
     "Altyapı ve donatı programının yapılaşmayla eşgüdümü, yoğunluğun kademelendirilmesi",
     "1/5000 NİP: Gelişme Konut Alanı; 1/1000 UİP: Yeni konut adaları ve donatı rezervi"),

    ("A11", "Karma Kullanım Alanı",
     "Hem dükkanların hem evlerin olduğu, orta büyüklükteki adalardan oluşan ara bölge.",
     {"karma": .6, "dens": .6, "merkez": .6}, None,
     "Ticaret-konut karması + orta büyüklükte adalar + orta yoğunluk",
     "Zemin kat ticaret standartları, otopark cepleri, cephe tipolojisi",
     "1/5000 NİP: Karma Kullanım Alanı; 1/1000 UİP: Konut + ticaret karma adaları"),

    ("A12", "Konut (Geçiş Dokusu)",
     "Eski kent dokusu ile yeni binalar arasında kalan konut adaları.",
     {"konut": .7, "dens": .6, "merkez": .6}, None,
     "Eski ve yeni yapı stokunun karışımı + orta yoğunluk + konut ağırlığı",
     "Yapı stoku iyileştirme, kademeli yoğunluk geçişi, ortak donatı kullanımı",
     "1/5000 NİP: Yerleşik Konut Alanı; 1/1000 UİP: Geçiş dokusu konut adaları"),

    ("A13", "Konut / Seyrek Yapılaşma",
     "Doğu taraftaki, alçak katlı evlerin ve boş parsellerin olduğu alan.",
     {"konut": .6, "dens": .3, "kat": .2}, "E",
     "Alçak katlı evler + boş parseller + düşük yoğunluk",
     "Boş parsellerin dolgu planlaması, düşük yoğunluğun korunması veya kademeli artırımı",
     "1/5000 NİP: Düşük Yoğunluklu Konut Alanı; 1/1000 UİP: Ayrık nizam konut adaları"),

    ("A14", "Plana Uygun Yerleşik Alan (Donatı Kapasitesine Göre Yoğunluk Artırımı)",
     "İmar planına uyulmuş, donatı alanları yeterli olan düzenli yerleşim; donatı kapasitesi kontrol edilerek yoğunluk artırılabilecek, raylı sistem istasyonu komşuluğundaki alan.",
     {"konut": .8, "dens": .6, "merkez": .6, "donati": .5}, "W",
     "Planlı ada formu + yeterli donatı alanı + istasyon komşuluğu + orta yoğunluk",
     "Donatı kapasite analizi; kapasite elveriyorsa istasyon çevresinde yoğunluk artırımı (TOD)",
     "1/5000 NİP: Yoğunluk Artırım Potansiyelli Konut Alanı; 1/1000 UİP: TAKS/KAKS revizyonu ve donatı takviyesi"),

    ("A15", "Konut / Arsa (Giriş Çeperi)",
     "Güneybatı girişinde yer alan, düşük yoğunluklu evlerin ve arsaların bulunduğu çeper.",
     {"konut": .5, "dens": .2, "tarim": .2, "merkez": .4}, "SW",
     "Düşük yoğunluklu konut + boş arsa + kent girişi konumu",
     "Kent girişi kimliğinin tanımlanması, çeper yapılaşmasının düzenlenmesi",
     "1/5000 NİP: Kent Giriş Çeperi; 1/1000 UİP: Düşük yoğunluklu konut ve yeşil çeper"),

    ("A16", "Korunacak Tarım Arazileri",
     "Geniş tarım arazilerinin ve seyrek yapıların bulunduğu; özel olarak korunması gereken tarımsal alan.",
     {"tarim": .95, "dens": .03, "merkez": .1}, "E",
     "Mutlak/dikili tarım arazisi + çok düşük yapılaşma + merkezden uzaklık",
     "Tarım arazisi koruma, yapılaşma baskısının engellenmesi, tarımsal parçalanmanın önlenmesi",
     "1/5000 NİP: Tarımsal Koruma Alanı; 1/1000 UİP: Plan dışı tarım alanı notları"),

    ("A17", "Konut (Eğimli Topoğrafya)",
     "Güneydoğuda hafif eğimin başladığı, düşük yoğunluklu konut alanı.",
     {"konut": .5, "egim": .7, "dens": .25}, "SE",
     "Orta-yüksek eğim + düşük yoğunluklu konut",
     "Eğime uyumlu yol kesitleri, gabari sınırlaması, drenaj önlemleri",
     "1/5000 NİP: Düşük Yoğunluklu Konut Alanı; 1/1000 UİP: Kademeli nizam ve Hmax sınırı"),

    ("A18", "Kent Çeperi Kırsal Yerleşim (Donatı Yetersizliği, Destek Gerekli)",
     "Kentin çeperindeki civar köy yerleşimi; okul, sağlık ve diğer donatıların bulunmadığı, destek gerektiren alan.",
     {"konut": .4, "donati": .05, "dens": .2, "merkez": .1, "tarim": .3}, "SE",
     "Çeper konumu + donatı yokluğu + düşük yoğunluk + merkezden uzaklık",
     "Temel donatı (okul, sağlık, toplu taşıma) desteği, erişim iyileştirmesi, altyapı programı",
     "1/5000 NİP: Kırsal Yerleşik Alan ve Donatı Takviyesi; 1/1000 UİP: Donatı alanı rezervi"),

    ("A19", "Karma Kullanım / Sit Çeperi",
     "Tarihi merkezin güneyinde, sit alanına komşu olan karma kullanım bölgesi.",
     {"karma": .6, "sit": .4, "dens": .7}, "S",
     "Karma kullanım + sit komşuluğu + yüksek yoğunluk",
     "Sit uyumlu kat ve gabari kısıtları, ticaret-konut dengesinin korunması",
     "1/5000 NİP: Ticaret-Konut Karma Alanı; 1/1000 UİP: Sit komşuluğu plan notları"),

    ("A20", "Kentsel-Kırsal Geçiş (Ekoton)",
     "Güneybatı sınırında, tarla ve evlerin bir arada görüldüğü geçiş alanı.",
     {"tarim": .4, "konut": .3, "dens": .15, "merkez": .15}, "SW",
     "Tarla + dağınık konut + çok düşük yoğunluk",
     "Yerleşik alan sınırının korunması, tarımsal parçalanmanın önlenmesi",
     "1/5000 NİP: Kentsel-Kırsal Geçiş Alanı; 1/1000 UİP: Kırsal konut ve tarım notları"),

    ("A21", "Sanayi - Konut - Tarım Çakışma Bölgesi (Sit İçeren, İncelenecek Alan)",
     "Sanayi, konut ve tarım kullanımlarının çakıştığı; içinde sit alanı da bulunan, öncelikle ayrıntılı incelenmesi gereken sorunlu bölge.",
     {"sanayi": .5, "konut": .35, "tarim": .45, "sit": .35, "dens": .15}, "N",
     "Sanayi + konut + tarım çakışması + sit alanı varlığı + düzensiz yapılaşma",
     "Ayrıntılı alan etüdü, kullanım çatışmalarının çözümü, sanayi-konut tampon kuşağı ve sit koruma kararı",
     "1/5000 NİP: Çakışma Alanı - Ayrıntılı Planlama Gerektiren Alan; 1/1000 UİP: Tampon kuşak ve sit koruma notları"),

    ("A22", "Dere Çeperi Yerleşimi",
     "En güneyde dere kenarında ve topografyaya dayanan çeper yerleşimi.",
     {"dere": .9, "egim": .6, "dens": .4}, "S",
     "Dere yakınlığı + taşkın maruziyeti + eğimli topoğrafya",
     "Dere koruma bandı, taşkın önlemleri, riskli yapıların tasfiyesi",
     "1/5000 NİP: Taşkın Önlemli Yeşil Koridor; 1/1000 UİP: Dere koruma kuşağı ve rekreasyon"),

    ("A23", "Tarım - Konut Hassas Doku",
     "Güney sınır hattı boyunca uzanan, tarım ve konut dokusunun karıştığı hassas parsel yapısı.",
     {"tarim": .3, "konut": .5, "dens": .5}, "S",
     "Tarım-konut karışımı + parçalı parsel yapısı + orta yoğunluk",
     "Parçalanmanın önlenmesi, konut-tarım sınırının net tanımlanması",
     "1/5000 NİP: Tarım-Konut Geçiş Alanı; 1/1000 UİP: Parsel birleştirme ve yapılaşma koşulları"),

    ("A24", "Ticaret - Konut Yoğun Doku",
     "Güney merkezde ticaret ve konutun yoğun olarak iç içe geçtiği doku.",
     {"ticaret": .5, "konut": .5, "dens": .8, "merkez": .8}, "S",
     "Ticaret-konut karması + yüksek yoğunluk + merkeze yakınlık",
     "Otopark ve yaya düzenlemeleri, zemin kat ticaret standartları",
     "1/5000 NİP: Ticaret-Konut Karma Alanı; 1/1000 UİP: Karma kullanım adaları"),

    ("A25", "Kentsel Dönüşüm Alanı ve Benzer Komşu Dokular (Kısmi Sit İçerir)",
     "Kentsel dönüşüm alanı ile ona komşu, benzer özellikteki dokular; içinde az da olsa kentsel sit alanı bulunur.",
     {"konut": .6, "dens": .75, "sit": .25, "bitisik": .8, "donati": .25}, "SW",
     "Eskimiş bitişik nizam yapı stoku + yüksek yoğunluk + kısmi sit varlığı + donatı yetersizliği",
     "Sit koruma kararlarıyla uyumlu kentsel dönüşüm etaplaması, donatı ve açık alan kazandırma",
     "1/5000 NİP: Kentsel Dönüşüm ve Yenileme Alanı; 1/1000 UİP: Dönüşüm etap sınırları ve donatı rezervi"),

    ("A26", "Yetersiz Yapı Stoku - Yüksek Eğim ve Fay Tehlikesi (Öncelikli Risk Alanı)",
     "Gecekondu ve kötü yapılaşmış, dar sokaklı, yüksek eğimli; fay hattına çok yakın olduğundan deprem tehlikesi çok yüksek bölge.",
     {"fay": .85, "egim": .8, "bitisik": .8, "dens": .7, "donati": .2}, "S",
     "Yetersiz yapı kalitesi + dar sokaklar + yüksek eğim + fay hattı yakınlığı + donatı eksikliği",
     "Öncelikli afet riski azaltma: yapı stoku dönüşümü/yenilenmesi, seyreltme, acil toplanma ve tahliye yolları",
     "1/5000 NİP: Afet Riskli Alan; 1/1000 UİP: TAKS/KAKS düşürme, yapı yaklaşma sınırı, afet toplanma alanı"),

    ("A27", "Potansiyel Kentsel Sit Alanı (Sit Benzeri, Sit Dışı Doku)",
     "Kentsel sit alanına benzeyen ancak sit sınırı içinde olmayan; gelecekte kentsel sit alanı potansiyeli taşıyan doku.",
     {"sit": .2, "ticaret": .4, "dens": .85, "merkez": .75, "bitisik": .8}, None,
     "Sit benzeri tarihi doku + sit sınırı dışında kalma + dar sokak ve bitişik nizam + ticari yaşam",
     "Envanter ve tescil değerlendirmesi, geçici koruma ve yapılaşma kısıtı, tarihi dokunun belgelenmesi",
     "1/5000 NİP: Sit Etkileşim-Geçiş Sahası (Tescil Potansiyelli); 1/1000 UİP: Koruma geçiş plan notları"),

    ("A28", "Organize Sanayi Bölgesi (Salt Sanayi)",
     "Sanayi alanı, küçük sanayi siteleri ve depoların toplandığı; düz ve tek fonksiyonlu çalışma bölgesi.",
     {"sanayi": .97, "dens": .2}, "NW",
     "Sanayi + depolama + büyük parsel yapısı + konut yokluğu",
     "Arıtma ve çevre yönetimi, çevre yerleşimlere tampon yeşil kuşak, lojistik yol düzenlemesi",
     "1/5000 NİP: Organize Sanayi Bölgesi; 1/1000 UİP: Sanayi ve depolama alanı"),
]

FEATURE_W = {
    "sanayi": 2.5, "tarim": 1.8, "sit": 2.2, "dere": 1.5,
    "mezarlik": 3.5, "bos_arazi": 1.8, "dusuk_konut": 1.6,
}

ADVANCED_PROFILES = [
    ("M1", "Tarihi MİA ve Arasta Ticaret Çekirdeği",
     "Yoğun yaya akışı, tescilli kültürel miras ve zemin ticaretinin odaklandığı geleneksel merkez.",
     {"merkez": .9, "ticaret": .8, "sit": .5}, None,
     "Yüksek yaya akışı + yoğun zemin ticaret + tescilli kültür varlıkları + dar sokak profili + düşük yeşil alan",
     "Yayalaştırma ve trafik sakinleştirme, tarihi cephe sağlıklaştırma, meydan ve gölgeli dinlenme alanları oluşturma",
     "1/5000 NİP: Merkezi İş Alanı (MİA) ve Kentsel Sit Tamponu; 1/1000 UİP: Yaya yolları, zemin ticaret + üst kat konut karma kullanımı, koruma amaçlı imar planı notu"),

    ("M2", "Kuzey Fay Hattı ve Yüksek Yoğunluklu Afet Kuşağı",
     "Diri fay hattı tamponu, zemin sıvılaşma riski ve yüksek yoğunluklu yapı dokusunun kesiştiği tehlike eşiği.",
     {"fay": .9, "dens": .8, "kat": .8}, "N",
     "Diri fay hattı tamponu + zemin sıvılaşma riski + yüksek katlı yapı stoku + yetersiz açık toplanma alanı",
     "Yapılaşma yasağı ve seyreltme tamponu, acil afet toplanma ve çadır kent alanı tahsisi, tahliye koridoru açılması",
     "1/5000 NİP: Afet Tehlikeli Alan ve Açık Yeşil Alan Kuşağı; 1/1000 UİP: TAKS/KAKS düşürme, yapı yaklaşma sınırı, afet toplanma alanı lejantı"),

    ("M3", "Demiryolu İstasyonu ve Lojistik Geçiş Kuşağı",
     "Raylı sistem erişimi, transit aktarma potansiyeli ve konut-sanayi arayüzünün oluşturduğu kentsel koridor.",
     {"sanayi": .4, "merkez": .6, "dens": .5}, None,
     "Demiryolu hattı ve istasyon erişimi + lojistik depolama talebi + konut-sanayi geçiş arayüzü",
     "Transit Odaklı Gelişim (TOD), istasyon meydanı düzenlemesi, yaya/bisiklet üst geçitleri ve gürültü perdesi",
     "1/5000 NİP: Ulaşım ve Transfer Merkezi; 1/1000 UİP: İstasyon meydanı, otopark, lojistik servis yolu ve yeşil tampon"),

    ("M4", "Sanayi - Konut Hassas Tampon Arayüzü",
     "Sanayi çalışma alanları ile konut yerleşimlerinin sınır temasında yer alan çevresel baskı kuşağı.",
     {"sanayi": .7, "konut": .3, "dens": .4}, "NW",
     "Sanayi ve depolama kullanımı + konut yerleşimi komşuluğu + yetersiz koruma bandı + hava/gürültü emisyonu",
     "Kesintisiz koruyucu yeşil kuşak/tampon oluşturulması, ağır vasıta güzergâhının konut içinden arındırılması",
     "1/5000 NİP: Sanayi Koruma Tamponu; 1/1000 UİP: 25-50 metre genişliğinde ağaçlandırılacak alan ve lojistik çevre yolu"),

    ("M5", "Küçük Menderes Taşkın Yatağı ve Ekolojik Tarım Kuşağı",
     "Yüksek sel/taşkın riski, 1. sınıf mutlak tarım toprağı ve düşük topoğrafik rakımın belirlediği koruma alanı.",
     {"tarim": .9, "dere": .9, "dens": .05}, "E",
     "Taşkın risk alanı (HAND/TWI) + dere yatağı komşuluğu + mutlak tarım arazisi + düşük zemin kotu",
     "Kesin yapılaşma yasağı, doğal taşkın yatağı koruma ve ekolojik koridor düzenlemesi, tarımsal niteliğin korunması",
     "1/5000 NİP: Ekolojik Koridor ve Tarımsal Koruma Alanı; 1/1000 UİP: Yapı yapılamaz taşkın sınırı ve rekreasyon alanı"),

    ("M6", "Akçeşme Deresi Koridoru ve Yeşil Altyapı Omurgası",
     "Kentsel alan boyunca uzanan dere yatağı, taşkın kısıtı ve kesintisiz açık-yeşil alan potansiyeli.",
     {"dere": .95, "egim": .4, "dens": .3}, "S",
     "Dere koridoru + doğal drenaj hattı + kentsel gecekondulaşma/yapılaşma baskısı",
     "Dere yatağı ıslahı, kesintisiz yaya-bisiklet yeşil omurgası, dere koruma bandı çekme mesafesi uygulanması",
     "1/5000 NİP: Doğal Yeşil Koridor; 1/1000 UİP: Dere koruma kuşağı, aktif yeşil alan ve bisiklet yolu"),

    ("M7", "Eğimli Yamaç Kentsel Gelişme ve Manzara Dokusu",
     "Yüksek topoğrafik eğim, manzara ve siluet etkisi taşıyan düşük yoğunluklu yamaç konut yerleşimi.",
     {"egim": .8, "konut": .6, "dens": .3}, "SE",
     "Yüksek eğim (>%15) + yüksek rakım kotu + gevşek zemin yapısı + siluet etkisi",
     "Kademeli azalan yoğunluk, teraslama, jeolojik drenaj önlemleri, kentsel siluet koruma ilkeleri",
     "1/5000 NİP: Düşük Yoğunluklu Konut Gelişme Alanı; 1/1000 UİP: Gabari (Hmax) sınırlaması, eğimli yol kesitleri ve kademeli nizam"),

    ("M8", "Toplu Konut ve Donatı Yetersizliği Odak Alanı",
     "Hızlı nüfus yığılması, 2SFCA donatı erişim açığı ve ısı adası baskısının yoğunlaştığı konut bölgesi.",
     {"dens": .8, "kat": .8, "donati": .2}, None,
     "Yüksek kat ve nüfus yoğunluğu + okul/sağlık erişim açığı + yüksek LST yüzey sıcaklığı + otopark yetersizliği",
     "Yeni sosyal ve teknik donatı alanı tahsisi, mahalle parkı ve gölgelendirme, otopark cepleri organizasyonu",
     "1/5000 NİP: Sosyal Donatı ve Kentsel Servis Odakları; 1/1000 UİP: İlkokul, aile sağlığı merkezi, kreş ve otopark alanı"),

    ("M9", "Kentsel-Kırsal Geçiş ve Eko-Turizm Çeperi",
     "Kentsel saçaklanma sınırında yer alan, geleneksel bağ/bahçe ve tarımsal kimliğini koruyan ekoton alanı.",
     {"tarim": .6, "konut": .3, "dens": .15}, "SW",
     "Kentsel saçaklanma sınırı + kırsal yerleşim mirası + bahçe ve tarım parselleri",
     "Köy yerleşik alan sınırının korunması, tarımsal parçalanmanın önlenmesi, agro-turizm ve kırsal tesis desteği",
     "1/5000 NİP: Kentsel-Kırsal Geçiş (Ekoton) ve Eko-Turizm Kuşağı; 1/1000 UİP: Kırsal turizm ve tarımsal depo plan notu"),

    ("M10", "Arkeolojik ve Tarihi Sit Koruma Tamponu",
     "Tescilli anıt eserler, arkeolojik kalıntılar ve kentsel sit alanı koruma kuşağı.",
     {"sit": .95, "merkez": .8, "dens": .5}, None,
     "Arkeolojik/kentsel sit sınırları + tescilli yapı yoğunluğu + yapılaşma baskısı",
     "Kültürel miras koruma ve restorasyon programı, sit tampon bölgesi oluşturma, kültür rotası ve ziyaretçi yönetimi",
     "1/5000 NİP: Tarihi ve Arkeolojik Sit Alanı; 1/1000 UİP: Koruma Amaçlı İmar Planı (KAİP) hükümleri"),

    ("M11", "Sosyo-Mekânsal Kırılganlık ve Kentsel Yenileme Odak Alanı",
     "Kötü yapı kalitesi, dar sokak dokusu ve kentsel yoksunluk göstergelerinin birleştiği öncelikli dönüşüm alanı.",
     {"dens": .7, "bitisik": .8, "donati": .3}, None,
     "Kötü durumdaki yapı oranı >%40 + dar ve çıkmaz sokaklar + yüksek nüfus yoğunluğu + yetersiz altyapı",
     "Yerinde kentsel sağlıklaştırma ve dönüşüm, sokak genişletme, sosyal tesis ve yeşil donatı kazandırma",
     "1/5000 NİP: Kentsel Yenileme ve Sağlıklaştırma Alanı; 1/1000 UİP: Dönüşüm etaplama sınırı ve donatı rezervi"),

    ("M12", "Ulaşım Transfer Kavşağı ve Çevre Yolu Servis Aksı",
     "Bölgesel karayolu bağlantısı, otogar tesisi ve ağır transit trafiğin yarattığı parçalanma eşiği.",
     {"sanayi": .4, "merkez": .5, "dens": .4}, "W",
     "Çevre yolu ve kavşak omurgası + otogar/terminal tesisi + transit ticari depolama",
     "Katlı veya dönel kavşak geometrik düzenlemesi, lojistik park ve transfer alanı, gürültü perdesi ağaçlandırması",
     "1/5000 NİP: Bölgesel Ulaşım ve Lojistik Terminali; 1/1000 UİP: Kavşak koruma kuşağı ve otopark alanı"),

    ("M13", "Eğitim Kampüsü ve Gençlik Hareketlilik Çekirdeği",
     "Yükseköğretim ve ortaöğretim kümelenmesi, yaya/bisiklet hareketliliği ve genç nüfus odaklı hizmet aksı.",
     {"donati": .8, "merkez": .6, "dens": .6}, None,
     "Eğitim tesisleri yoğunluğu + yurt ve öğrenci konutu talebi + genç odaklı kafeterya ve ticaret",
     "Güvenli okul yolları, bisiklet şebekesi entegrasyonu, öğrenci barınma ve karma kullanım koridoru",
     "1/5000 NİP: Eğitim ve Üniversite Gelişme Alanı; 1/1000 UİP: Karma kullanım (öğrenci konutu + ticaret) ve bisiklet yolu"),

    ("M14", "Kentsel Mezarlık ve Açık Yeşil Tampon Kuşağı",
     "Kentsel mezarlık alanı, dini tesis ve çevresindeki yeşil koruma kuşağı.",
     {"mezarlik": .9, "tarim": .3, "donati": .6, "dens": .15}, "S",
     "Mezarlık alanı + çevresindeki kontrolsüz konut yapılaşması baskısı + yeşil doku sürekliliği",
     "Mezarlık koruma ve genişleme bandı oluşturulması, çevresinde yeşil tampon ağaçlandırması",
     "1/5000 NİP: Mezarlık ve Yeşil Tampon; 1/1000 UİP: Ağaçlandırılacak alan ve koruma kuşağı"),

    ("M15", "Yüksek Gerilim Altyapı Güvenlik ve Enerji Koridoru",
     "Yüksek gerilim enerji nakil hatları (ENH), trafo sahası ve manyetik alan güvenlik koridoru.",
     {"tarim": .5, "sanayi": .3, "dens": .1}, "NW",
     "Yüksek gerilim hattı koridoru + trafo sahası + altındaki kontrolsüz parselasyon",
     "Hat altı yapı yasağı uygulanması, pasif yeşil koridor ve tarımsal açık alan olarak sürekliliğin sağlanması",
     "1/5000 NİP: Teknik Altyapı Güvenlik Kuşağı; 1/1000 UİP: ENH koruma bandı ve pasif yeşil alan"),

    ("M16", "Toptancı Hal, Semt Pazarı ve Gıda Dağıtım Merkezi",
     "Kentsel gıda tedariki, semt pazarı sirkülasyonu ve servis trafiğinin yoğunlaştığı ticaret alanı.",
     {"ticaret": .7, "sanayi": .3, "dens": .5}, None,
     "Pazar yeri alanı + tarımsal üretim havzası girişi + kamyon-servis araç trafiği + atık baskısı",
     "Modern kapalı pazar yeri ve soğuk hava depolama lojistiği, yükleme-boşaltma cepleri, geri dönüşüm ve otopark",
     "1/5000 NİP: Kentsel Servis ve Toptan Ticaret Alanı; 1/1000 UİP: Kapalı pazar yeri, otopark ve altyapı tesisi"),

    ("M17", "Kırsal Bağ ve Gastronomi Turizm Güzergâhı",
     "Geleneksel tarımsal peyzaj, bağ rotaları ve yerel üretim odaklı kırsal turizm potansiyeli.",
     {"tarim": .7, "egim": .5, "dens": .1}, "SE",
     "Bağ ve bahçe parselleri + geleneksel taş yapı dokusu + manzara ve yürüyüş rotaları",
     "Kırsal peyzajın spekülasyondan korunması, butik bağ rotası, bisiklet ve yürüyüş patikaları düzenlemesi",
     "1/5000 NİP: Kırsal Turizm ve Doğal Karakteri Korunacak Alan; 1/1000 UİP: Agro-turizm ve kırsal pansiyon plan notu"),

    ("M18", "Kent Ormanı, Mesire ve Yangın Önleme Kuşağı",
     "Kentsel rekreasyon, yamaç orman varlığı ve orman yangını önleme tampon hattı.",
     {"egim": .8, "tarim": .4, "dens": .05}, "S",
     "Orman alanı + güney yamaç eğimi + kentli dinlenme talebi + orman yangını hassasiyeti",
     "Kontrollü mesire alanı yönetimi, orman-kent arayüzünde yangın emniyet şeridi ve su ikmal noktaları",
     "1/5000 NİP: Orman ve Bölgesel Park; 1/1000 UİP: Mesire yeri, yangın şeridi ve teknik altyapı"),

    ("M19", "Geleneksel Çarşı ve Karma Ticaret Omurgası",
     "Dar sokak dokusuna sahip zemin ticaret ve konut karma aksı.",
     {"ticaret": .8, "merkez": .8, "karma": .7}, None,
     "Tarihi ticaret aksı + yaya yoğunluğu + servis araçları çatışması",
     "Trafik sakinleştirme, yayalaştırma saatleri, kentsel mobilya ve cephe düzenlemesi",
     "1/5000 NİP: Ticaret-Konut Karma Alanı; 1/1000 UİP: TİCK ve yaya öncelikli yol"),

    ("M20", "Düzenli İmar Parselasyonlu Konut Dokusu",
     "Geniş yol profilleri ve ayrık nizamlı konut bloklarının bulunduğu düzenli gelişme dokusu.",
     {"konut": .8, "dens": .5, "merkez": .5}, "W",
     "Düzenli ada formu + standart TAKS/KAKS + orta yoğunluklu konut",
     "Mevcut morfolojik nizamın korunması, yeşil ada içi avluların güçlendirilmesi",
     "1/5000 NİP: Orta Yoğunluklu Yerleşik Konut; 1/1000 UİP: Ayrık nizam konut adaları"),

    ("M21", "Seyrek Dokulu Kırsal Yerleşim Çeperi",
     "Geniş bahçeli evler ve tarımsal üretim alanlarının iç içe geçtiği seyrek yerleşim.",
     {"tarim": .8, "dens": .1}, "E",
     "Seyrek yapı dokusu + tarımsal açık alanlar + düşük altyapı maliyeti",
     "Düşük emsalli kırsal konut koşulu, tarım arazilerinin korunması",
     "1/5000 NİP: Kırsal Nitelikli Konut Alanı; 1/1000 UİP: E=0.20 kırsal konut"),

    ("M22", "Dere Kenarı Kentsel Dönüşüm ve Park Alanı",
     "Dere yatağına komşu, taşkın hassasiyeti bulunan ve dönüşüm bekleyen yapı dokusu.",
     {"dere": .8, "dens": .5, "egim": .4}, "S",
     "Dere yakınlığı + taşkın maruziyeti + eski yapı stoku",
     "Dere cephesi yapıların tasfiyesi, taşkın koruma bendi ve lineer park yapımı",
     "1/5000 NİP: Taşkın Önlemli Kentsel Yeşil Koridor; 1/1000 UİP: Rekreasyon ve park"),

    ("M23", "Organize Sanayi Bölgesi (TOSB) Çekirdeği",
     "Büyük parselasyonlu imalat sanayisi ve lojistik tesislerin toplandığı üretim odağı.",
     {"sanayi": .95, "dens": .2}, "NW",
     "Ağır sanayi üretimi + tehlikeli madde depolama + demiryolu lojistiği",
     "Arıtma tesisi zorunluluğu, OSB içi itfaiye ve acil müdahale istasyonu tahsisi",
     "1/5000 NİP: Organize Sanayi Bölgesi; 1/1000 UİP: Sanayi ve depolama alanı"),

    ("M24", "Karma Kullanımlı Kentsel Sağlıklaştırma Kuşağı",
     "Konut ve küçük esnaf dükkanlarının iç içe girdiği geçiş dokusu.",
     {"karma": .7, "dens": .6, "merkez": .6}, None,
     "Karma fonksiyonlar + orta kat yüksekliği + otopark ihtiyacı",
     "Zemin kat ticari standartları, otopark cepleri, cephe tipolojisi",
     "1/5000 NİP: Karma Kullanım Alanı; 1/1000 UİP: Konut+Ticaret karma adaları"),

    ("M25", "Yeni Kentsel Gelişme ve Rezerv Konut Alanı",
     "Kentin büyüme aksında yer alan, planlı altyapı bekleyen boş imar adaları.",
     {"konut": .65, "bos_arazi": .75, "dusuk_konut": .65, "dens": .25}, "E",
     "Boş imar adaları + yeni konut talebi + altyapı koridoru",
     "Etaplı kentsel gelişme, enerji verimli bina tasarımı, bisiklet altyapısı",
     "1/5000 NİP: Kentsel Gelişme Alanı; 1/1000 UİP: Yeni konut yerleşimi"),

    ("M26", "Mahalle İçi Sosyal Altyapı ve Donatı Kümesi",
     "Eğitim, sağlık ve dini tesislerin çevrelediği sosyal odak noktası.",
     {"donati": .7, "konut": .6, "dens": .5}, "SW",
     "Kamu tesisleri varlığı + yaya erişimi + mahalle merkezi niteliği",
     "Yaya öncelikli çevre düzenlemesi, güvenli okul bölgesi, engelsiz erişim",
     "1/5000 NİP: Sosyal ve Kültürel Tesis Alanı; 1/1000 UİP: Donatı adaları"),

    ("M27", "Tarihi Doku - Sit Çeperi Tampon Arayüzü",
     "Tarihi sit sınırının hemen dışındaki geçiş bölgesi.",
     {"sit": .6, "karma": .5, "merkez": .7}, None,
     "Sit komşuluğu + siluet etkisi + turizm baskısı",
     "Sit uyumlu kat ve gabari kısıtlaması, geleneksel malzeme zorunluluğu",
     "1/5000 NİP: Sit Etkileşim-Geçiş Sahası; 1/1000 UİP: Koruma geçiş plan notu"),

    ("M28", "Topoğrafik Eşik ve Doğal Sınır Kuşağı",
     "Yerleşimin sonlandığı, yüksek eğimli ve kayalık doğal sınır.",
     {"egim": .7, "dens": .2}, "S",
     "Yüksek eğim (>%20) + kısıtlı ulaşım + kentsel eşik",
     "Yerleşme sınırı çekilmesi, erozyon kontrolü ve ağaçlandırma",
     "1/5000 NİP: Doğal Eşik / Ağaçlandırılacak Alan; 1/1000 UİP: İmar dışı doğal alan"),
]


def match_cost(zone, row):
    _, _, _, targets, direction = row[:5]
    num = den = 0.0
    for k, t in targets.items():
        z = zone.get(k)
        if z is None:
            continue
        w = FEATURE_W.get(k, 1.0)
        num += w * (z - t) ** 2
        den += w
    cost = num / den if den else 0.5
    if direction:
        zd = zone.get("dir")
        if zd is None:
            dterm = 0.25
        else:
            tx, ty = _D[direction]
            dterm = (1.0 - (zd[0] * tx + zd[1] * ty)) / 2.0
        cost += 0.35 * dterm
    return cost


def match_zones_to_rows(zone_feats, mode="standard"):
    n = len(zone_feats)
    rows = ADVANCED_PROFILES if mode == "advanced" else EXCEL_ROWS
    m = len(rows)
    if n > m:
        raise ValueError("parça sayısı profil satırlarından fazla")
    cost = [[match_cost(z, r) for r in rows] for z in zone_feats]
    assign = hungarian(cost)
    out = []
    for i, j in enumerate(assign):
        out.append((j, round(max(0.0, 100.0 * (1.0 - cost[i][j] / 0.6)), 1)))
    return out
