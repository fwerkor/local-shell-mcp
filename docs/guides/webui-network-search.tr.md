<!-- i18n-source-sha256: 78ec7a5b5dc75473db69b12cf1626f81c3071f52661bf1023047af5d6d24e3ee -->
# WebUI içinde web araması ve belge okuma

WebUI sohbetinde web araması varsayılan
olarak açıktır. Mesaj kutusunun altındaki
anahtarla her sohbet için kapatılabilir;
seçim o sohbete kaydedilir. Sağlayıcı API
anahtarı veya Worker kabuk yetkisi gerekmez.

Agent yalnızca iki salt okunur araç alır.
`web_search(query)` herkese açık sonuçların
başlıklarını, URL adreslerini ve özetlerini
döndürür. Yüklüyse `ddgs` kullanır; değilse
anahtarsız Bing RSS dener. Genel hizmetler
istekleri kısıtlayabilir veya
erişilemeyebilir.

`web_fetch(url, query?, offset?, limit?)`
HTML, düz metin, JSON, XML, Markdown ve PDF
okur. Bir arXiv özetinde önce HTML tam metni,
ardından gerekirse PDF sürümünü dener. Ayrı
bir akademik arama API'si gerekmez.

İlk okumada tam metin, dizin yazılabiliyorsa
Controller'ın özel önbelleğine kaydedilir.
Önbellek kullanıcı bazında ayrıdır, 24 saat
sonra sona erer ve kişi başına en fazla 80
dosya içerir. Normal yanıt 8000 karakterle
sınırlıdır; arama, kaydırma ve uzunluk
kullanılarak çağrı başına 12000 karaktere
kadar devamı okunabilir.

İndirme sınırı 20 MiB, çıkarılan metin sınırı
3 MiB'dir. Özel ağlar, URL içindeki kimlik
bilgileri, standart dışı bağlantı noktaları
ve tehlikeli yönlendirmeler engellenir. DNS
rebinding saldırılarına karşı yalnızca
doğrulanmış genel IP adreslerine bağlanılır.

PDF dosyaları PyMuPDF veya yedek olarak
`pypdf` ile işlenir. Metin katmanı bulunmayan
taramalar OCR gerektirir ve açık bir hata
döner. HTML için belirtilen karakter
kodlaması kullanılır; desteklenmeyen biçimler
reddedilir.

Bağlantılar araç sonuç kartında gösterilir.
Yanıtlarda mümkün olduğunca özgün URL ve PDF
sayfa numaraları belirtilmelidir. Dışarıdan
gelen içerikler güvenilir değildir ve
kullanıcı talimatlarını ya da Agent
ayarlarını değiştiremez.
