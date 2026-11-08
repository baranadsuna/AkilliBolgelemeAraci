# Kentsel Bölgeleme ve Kırılganlık Analiz Aracı (v1.1.0)

**Mekânsal Planlar Yapım Yönetmeliği (MPYY) Esaslarına Dayalı Çok Kriterli Mekânsal Ward Kümelemesi ve Sınır Ayrım Karar Destek Aracı**

Geliştirici: **Baran Adsuna** · Kurum: Dokuz Eylül Üniversitesi, Şehir ve Bölge Planlama Bölümü  
Uyumlu QGIS Sürümleri: **QGIS 3.28 – 3.40+ (LTR ve Güncel Qt5 / Qt6)**

---

## 1. Genel Bakış ve Amaç

Bu eklenti; şehir ve bölge planlama çalışmalarında (özellikle 1/5000 NİP ve 1/1000 UİP alt bölgeleme ve etaplama kararlarında) çalışma alanının homojen morfolojik, işlevsel ve risk karakterli alt bölgelere ayrılmasını sağlar.

Piyasadaki geleneksel ızgara veya sentetik kümeleme araçlarından farklı olarak **sıfır sentetik veri** ilkesiyle çalışır:
- Çalışma alanındaki **imar adaları**, **opsiyonel tekil yapılar**, **yol ağı** ve **doğal/afet eşikleri** hücre bazında gerçek kesişim ve mesafe ölçümleriyle Z-skoru matrisine dahil edilir.
- Birleştirme adımlarında **mekânsal kısıtlı Ward algoritması** kullanılarak yalnızca birbirine fiziksel olarak komşu olan hücreler birleştirilir.
- **Açıklanabilir CBS (Explainable Spatial AI):** Her alt bölgenin yalnızca kendi içinde neden birleştiği değil; sınır komşusu olan diğer bölgelerden hangi somut farkla ayrıldığı Z-skoru matrisindeki en yüksek 3 fark (|ΔZ|) hesaplanarak otomatik raporlanır.

---

## 2. 5 Temel Metodolojik Kural (Kural 1 – 5 Mimarisi)

1. **Nüfus Dağıtımında Sıfır Sentetik Veri & Sektörel Ayıklama:**
   - Sanayi/OSB (`lu_sanayi`) ve Tarım/Açık Alan (`lu_tarim`) hücrelerinin yerleşik nüfus ağırlık katsayısı **kesinlikle 0'dır**.
   - Manuel veya sütun bazlı nüfus yalnızca konut (`lu_konut`) ve konut içeren karma (`lu_ticaret` + `lu_konut`) alanlara taban alanı ve kat adedi ağırlığıyla dağıtılır. Sanayi ve tarım alt bölgelerinde yerleşik nüfus daima 0 kişi çıkar.
2. **Yapı Nizamı ve Açık Alan Ayrımı:**
   - Taban Alanı Kat Sayısı (TAKS) < %5 veya Tarım/Açık Alan oranı > %70 olan seyrek alanlara asla varsayılan olarak "Bitişik Nizam" atanmaz; "Yapısız / Açık Alan" veya "Seyrek Kırsal Doku" olarak etiketlenir.
3. **Kat Sayısında Alan Ağırlıklı Ortalama:**
   - Geniş tarım parselleri içindeki tekil yapay outlier binaların kat ortalamasını saptırmasını önlemek amacıyla kat adedi, taban alanı ağırlıklı ortalama (`kat_w / kat_a`) olarak hesaplanır.
4. **Kötü Yapı ve Sit2/Sit3 Kentsel Dönüşüm Göstergeleri:**
   - Kötü durumdaki yapı oranı (`yapi:kotu_yapi`), tescilli alan (`sit2`) ve afet risk / kentsel dönüşüm sınırı (`sit3`) parametreleri doğrudan öznitelik tablosuna ve metin raporlarına işlenir.
5. **Dinamik ve Çeşitlendirilmiş Sınır Ayrım Gerekçesi:**
   - Yalnızca dere ve fay uzaklığına odaklanmak yerine; Z-skoru matrisindeki tüm aktif değişkenler taranarak iki komşu bölge arasında **en yüksek mutlak Z farkı oluşturan ilk 3 değişken** (TAKS, eğim, kat, nizam, kötü yapı, nüfus yoğunluğu, fonksiyon) dinamik olarak gerekçe metnine yazdırılır.

---

## 3. Katman ve Çıktı Mimarisi

### Girdi Katmanları:
- **Planlama Sınırı (Opsiyonel / Otomatik):** Çalışma alanı poligonu.
- **Yol Ağı (Çizgi):** Genişlik, kaplama (asfalt/parke/toprak), kademe (bulvar/cadde/sokak). Refüj ve kavşak adacıkları otomatik süzülür.
- **İmar Adaları / Parseller (Poligon):** Arazi kullanımı, kat, yapı nizamı, yapı durumu, nüfus.
- **Tekil Yapı Stoku (Opsiyonel Poligon):** Varsa tekil binalar üzerinden doğrudan gerçek TAKS ve kat hesabı.
- **Doğal Eşikler & Koruma:** Dere yatakları, diri fay hatları, sit alanları, taşkın risk bölgeleri, donatılar.
- **Sayısal Yükselti Modeli (DEM / Eğim):** GeoTIFF rasterından hücresel eğim (%) hesaplama.

### Üretilen Katmanlar ve Tablolar:
- **`Alt_Bolgeler_A1_A28` (MultiPolygon):** Ayrılmış alt bölgeler, Z-skoru profilleri, gerekçe ve ayrım metinleri, kategorize kurumsal semboloji ve etiketleme.
- **`Imar_Adasi_Hucreleri` (Opsiyonel Polygon):** Yol ağından üretilen net imar adası hücreleri.
- **CSV Dışa Aktarımı (UTF-8-SIG):** Boş sütunlardan arındırılmış, Excel'de doğrudan Türkçe karakterlerle açılan resmi karar destek tablosu.

---

## 4. Test Kılavuzu (E2E & Birim Testleri)

Tüm testler yerel projeksiyon **EPSG:5253** (TUREF / GK Zone 27 / İzmir) üzerinde sentetik CBS verileri ve gerçek QGIS başsız (headless) ortamında çalışır.

### A) Saf Python Birim Testleri (QGIS Bağımsız):
```bash
C:\OSGeo4W\bin\python-qgis.bat tests\test_core.py
# veya
C:\OSGeo4W\bin\python-qgis.bat -m unittest discover -s tests
```
*18 birim test: Macar algoritması, Ward kümeleme, Z-skoru normalizasyonu, MPYY arazi kullanımı sınıflaması, yön maliyeti ve bileşen bağlantıları doğrulanır.*

### B) Gerçek QGIS Uçtan Uca Duman Testi (Headless E2E Smoke Test):
```bash
C:\OSGeo4W\bin\python-qgis.bat -u tests\qgis_smoke.py
```
*Tüm boru hattı, vektör ve raster geometrileri, Kural 1-5 algoritmaları, BolgelemeDialog arayüzü, CSV aktarımı ve eklenti yaşam döngüsü (FakeIface) uçtan uca test edilir.*
