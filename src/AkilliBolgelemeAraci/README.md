# Urban Zoning and Vulnerability Analysis Tool (v1.9.1)
### Akıllı Bölgeleme ve Afet Kırılganlık Analiz Aracı

**Mekânsal Planlar Yapım Yönetmeliği (MPYY) Esaslarına Dayalı Çok Kriterli Mekânsal Ward Kümelemesi, 3B Kırılganlık Sentezi ve İmar Planı Karar Destek Sistemi**

- **Geliştirici / Yazar:** [Baran Adsuna](https://github.com/baranadsuna) (Dokuz Eylül Üniversitesi, Şehir ve Bölge Planlama Bölümü)
- **Zorunlu Projeksiyon / CRS Standardı:** `EPSG:5253` (TUREF / TM30 — 30°D Dilim Orta Meridyeni)
- **QGIS & Qt Uyumluluğu:** QGIS 3.22 – 4.99+ (Tam Qt5 ve Qt6 Desteği, `supportsQt6=True`)
- **Lisans:** GNU General Public License v2.0 or later (GPL-2.0-or-later)
- **Çok Dilli Arayüz:** İngilizce (Varsayılan), Türkçe, Çince, İspanyolca (1 Tıkla Anında Geçiş)

---

## 1. Genel Bakış ve Temel Amaç

Bu eklenti; şehir ve bölge planlama ofisleri, belediyeler, araştırmacılar ve planlama stüdyosu öğrencileri için çalışma alanını morfolojik, işlevsel, yapısal ve afet kırılganlığı göstergelerine göre kompakt ve topolojik açıdan temiz alt planlama bölgelerine (`M1..MK` veya `A1..AK`) ayıran, sıfır sentetik veri prensibiyle çalışan kapsamlı bir karar destek paketidir.

### v1.9.1 ile Gelen Başlıca Yenilikler:
1. **QGIS Plugin Hub Django ConfigParser Ayrıştırma Zırhı:**
   - Resmi QGIS Eklenti Havuzu (`plugins.qgis.org`) yükleme motorunda meydana gelen `InterpolationSyntaxError: '%' must be followed by '%' or '('` hatası giderildi.
   - `metadata.txt` içerisindeki tüm serbest yüzde işaretleri standart Django parser uyumlu hâle getirildi; eklentinin eklenti yöneticisi ve web arayüzünde eksiksiz ve hatasız listelenmesi sağlandı.
2. **Yepyeni Yüksek Estetikli Vektör Marka Kimliği (icon.svg & icon.png):**
   - Eklenti logosu modern kentsel planlama ve morfolojik bölgeleme prensipleriyle baştan tasarlandı.
   - 4 ana kentsel fonksiyon karesi (MİA / Ticaret mercanı, Konut kehribarı, Donatı/Ekoloji zümrüdü, Akıllı Kent camgöbeği), 3 boyutlu izometrik kot katmanları, parlayan yol ağı omurgası ve karar destek ağırlık merkezi düğümleriyle zenginleştirildi.
   - QGIS araç çubuğunda (16px, 24px, 32px, 64px) ve web portalında ultra net görünüm için raster `icon.png` eşliği eklendi.

### v1.9.0 ile Gelen Başlıca Yenilikler:
1. **Pedagojik ve Etkileşimli Ağırlık Seçim Mekanizması:**
   - Sekme 3'teki tüm ağırlık katsayıları çift-yönlü senkronize yatay kaydırıcı (`QSlider`) ve hassas sayısal kutu (`QDoubleSpinBox`) ile donatılmıştır.
   - Gerçek zamanlı dinamik etki rozetleri (`⚪ Etkisiz (%0)`, `🔵 Düşük Etki`, `🟢 Dengeli / Standart`, `🟠 Yüksek / Baskın Kriter`) ile katsayının kümeleme üzerindeki belirleyiciliği anında görselleştirilir.
   - Her ağırlık kartının altında yalın ve anlaşılır dille **Çalışma Mantığı**, **Min (0.0) ve Maks (5.0) Seçilirse Sonuç** ve **Önerilen Aralık** bilgileri sunulur.
2. **3 Kademeli Morfolojik Kompaktlık Modu:**
   - `🌿 Morfolojik / Doğal Eksen (Vadi & Koridor Serbestliği)`: Dere yatakları, diri fay hatları ve ana ulaşım omurgaları boyunca uzanan doğrusal planlama alanlarında geometrik dairesellik zorlamasını kaldırır; vadilerin doğal akışına izin verir.
   - `⚖️ Dengeli Standart (Planlama Normu)`: Hem kentsel morfolojiyi korur hem de derli toplu bölgeler oluşturur.
   - `🎯 Yüksek Kompaktlık (Dairesel / Dörtgen Süperbloklar)`: Şerit ve ince uzantıları kesinlikle engeller, yuvarlak süperbloklar üretir.
3. **9 Hazır Bölgeleme Stratejisi (Preset 7 Eklendi):**
   - *Morfolojik / Doğal Eksen ve Vadi Koridoru (Organik Akış)* hazır stratejisi eklenerek 3x3 simetrik hızlı seçim düğmesi olarak arayüze entegre edilmiştir.
4. **Masaüstü Sıfır Ayak İzi Garantisi:**
   - Eklenti güncelleme, derleme ve paketleme süreçlerinin hiçbir aşamasında kullanıcının Masaüstü (`Desktop`) dizininde geçici dosya veya klasör oluşturulmaz.

---

## 2. Matematiksel ve Algoritmik Metodoloji

### A) Mekânsal Kısıtlı Ward Kümeleme ve Kompaktlık Maliyet Fonksiyonu
Kümeleme işleminde iki komşu hücre kümesi $A$ ve $B$ birleşirken toplam hata kareleri toplamındaki artış ($\Delta \text{ESS}$) hesaplanır:

$$\Delta \text{ESS}(A, B) = \frac{W_A W_B}{W_A + W_B} \left( \|\mathbf{z}_A - \mathbf{z}_B\|_2^2 + \varepsilon \right) \cdot \Phi_{\text{affinity}}(A, B) \cdot \left[ 1 + \kappa(A, B) \cdot \left( \frac{\text{Area}_A + \text{Area}_B}{C_{\text{area}}} \right)^p \right]$$

Burada:
- $\mathbf{z}_A, \mathbf{z}_B$: Çok kriterli standartlaştırılmış Z-skoru öznitelik vektörleridir.
- $\Phi_{\text{affinity}}(A, B)$: Sanayi bütünlüğü, tarım ovası sürekliliği ve mekânsal şekil kompaktlığını denetleyen ceza/ödül çarpanıdır.
- $\kappa(A, B)$: Dinamik alan tavanı faktörüdür:
  - Sanayi veya Tarım birleşmelerinde: $\kappa = 0.0$ (Alan tavanı muafiyeti; devasa makro alanlar bölünmez).
  - Donatı açığı yüksek konut dokularında: $\kappa = 2.4$ (Alan tavanı erken devreye girer; küçük ve odaklı mahalleler oluşur).
  - Standart durumlarda: $\kappa = 1.0$.

### B) Geometrik Şekil ve Kompaktlık Denetimi
İki kümenin ortak temas kenarı uzunluğu $L_{\text{shared}}$ ve ağırlık merkezleri arası Öklid mesafesi $D_{\text{cent}}$ üzerinden şekil kompaktlığı şu şekilde zorlanır:

$$\Phi_{\text{geo}} = \begin{cases} 1 + 3.5 \cdot w_{\text{geo}}, & L_{\text{shared}} < 10\text{ m} \quad (\text{Noktasal / Dar Boğaz Teması Cezası}) \\ 1 + 1.2 \cdot w_{\text{geo}} \left(\frac{D_{\text{cent}}}{R_A + R_B} - 1.0\right), & D_{\text{cent}} > 1.6 \cdot (R_A + R_B) \quad (\text{Aşırı Uzama / Koridor Cezası}) \\ 0.70, & L_{\text{shared}} > 0.40 \cdot \min(\sqrt{A_A}, \sqrt{A_B}) \quad (\text{Geniş Yüzeyli Temas Ödülü}) \end{cases}$$

### C) 3 Boyutlu Afet Kırılganlığı Modeli (Turner et al., 2003)
Her alt bölgenin afet kırılganlık indeksi $V$, Maruziyet ($E$), Duyarlılık ($S$) ve Uyum Kapasitesi ($AC$) bileşenlerinin geometrik ortalamasıyla hesaplanır:

$$V = \frac{E \cdot S}{AC}$$

- **Maruziyet ($E$):** Diri fay mesafesi, dere taşkın koridoru, DEM eğim derecesi.
- **Duyarlılık ($S$):** TAKS yoğunluğu, ortalama kat yüksekliği, kötü yapı oranı, tescilli sit hassasiyeti.
- **Uyum Kapasitesi ($AC$):** Yol genişliği, donatı erişilebilirliği, kişi başına açık/yeşil alan miktarı.

---

## 3. Katman ve Sütun Gereksinimleri

| Katman Türü | Geometri | Önerilen Sütunlar / Nitelikler | Otomatik Algılama |
| :--- | :--- | :--- | :--- |
| **Planlama Sınırı** | MultiPolygon | Sınır adı | Otomatik algılanır |
| **Yol Ağı** | LineString | `genislik`, `kaplama`, `kademe` | Refüj ve ada içi yollar süzülür |
| **İmar Adaları** | Polygon | `kullanim`, `kat`, `yapi_nizami`, `durum` | Konut, Ticaret, Sanayi, Tarım, Mezarlık |
| **Tekil Yapı Stoku** (Opsiyonel) | Polygon | `kullanim`, `kat`, `durum` | Taban alanı ve gerçek kat hesabı |
| **Doğal Eşikler** | Line / Poly | Dere yatakları, diri fay, sit, taşkın | Salt doğal/afet eşikleri |
| **Sayısal Yükselti Modeli** | Raster (DEM) | 30m / 10m GeoTIFF | Hücresel eğim (%) ve kot hesabı |

---

## 4. Doğrulanmış Akademik Kaynaklar ve Literatür Dayanağı

Tüm algoritmik metodoloji Crossref ve DOI.org üzerinden doğrulanmış 5 temel akademik yayına dayanmaktadır:

1. **J. H. Ward Jr.** (1963). *Hierarchical Grouping to Optimize an Objective Function*. Journal of the American Statistical Association, 58(301), 236–244.  
   DOI: [`10.1080/01621459.1963.10500845`](https://doi.org/10.1080/01621459.1963.10500845)
2. **H. W. Kuhn** (1955). *The Hungarian Method for the Assignment Problem*. Naval Research Logistics Quarterly, 2(1-2), 83–97.  
   DOI: [`10.1002/nav.3800020109`](https://doi.org/10.1002/nav.3800020109)
3. **B. L. Turner et al.** (2003). *A Framework for Vulnerability Analysis in Sustainability Science*. Proceedings of the National Academy of Sciences (PNAS), 100(14), 8074–8079.  
   DOI: [`10.1073/pnas.1231335100`](https://doi.org/10.1073/pnas.1231335100)
4. **W. Luo & F. Wang** (2003). *Measures of Spatial Accessibility to Health Care in a GIS Environment: Synthesis and a Case Study in the Chicago Region*. Environment and Planning B: Planning and Design, 30(6), 865–884.  
   DOI: [`10.1068/b29120`](https://doi.org/10.1068/b29120)
5. **B. Hillier et al.** (1976). *Space Syntax*. Environment and Planning B: Planning and Design, 3(2), 147–185.  
   DOI: [`10.1068/b030147`](https://doi.org/10.1068/b030147)

---

## 5. Sürüm Geçmişi (Changelog)

- **v1.8.0:**
  - Doğal Eşikler sekmesinden sosyal/teknik donatılar (okul, park, sağlık) tamamen çıkarıldı; sekme salt jeolojik/hidrolojik eşiklere odaklandı.
  - İnce uzun koridorları ve asimetrik kuyrukları (M4 gibi) önleyen Gelişmiş Mekânsal Kompaktlık ve Şekil Kontrolü motoru eklendi.
  - Sanayi (OSB) ve geniş tarım ovaları için Alan Tavanı Muafiyeti (`cap_factor = 0.0`) getirildi; büyük makro alanlar bölünmeden tek parça korundu.
  - Konut başına düşen donatı açığına göre dinamik mahalle ölçeklendirmesi (donatısız yerlerin küçük/odaklı tutulması) uygulandı.
  - Donatı Alanlarına Erişim parametresi sadeleştirildi.
- **v1.7.0:**
  - Profesyonel strateji adlandırmaları ve kanonik A1..A28 imar planı tipolojisi (karakter, anlatı, müdahale kararı, 1/5000 ve 1/1000 karşılığı).
- **v1.6.0:**
  - 8 Hazır Bölgeleme Stratejisi; `dusukkonut`/`seyrekkonut`, `mezarlık` ve `boş arazi` için derin anlamsal arazi kullanımı tanıma motoru.
- **v1.5.0:**
  - Akıllı konut ve karma ada nüfus dağıtım motoru; sadeleştirilmiş toplam nüfus arayüzü; sıfır hatalı nüfus dağılımı.
- **v1.4.0:**
  - Çok dilli arayüz ve evrensel İngilizce varsayılan; çok parçalı adacık ve iç siyah çizgilerin elenmesi algoritması.
- **v1.3.0:**
  - Atlamasız ardışık alt bölge numaralandırma ($K$ adedi kadar eksiksiz M1..MK); formatlı Excel (`.xlsx`) aktarımı.
- **v1.0.0 – v1.2.0:**
  - İlk sürüm, MPYY uyumlu Ward kümeleme, 3B afet kırılganlığı ve çift kademeli sınır ayrım gerekçeleri.
