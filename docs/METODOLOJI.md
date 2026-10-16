# Test metodolojisi ve kabul değerlendirmesi

## Amaç ve kapsam

Donanım kabulü, tek bir başarılı benchmark komutundan daha geniştir. Bu proje işletim sisteminden erişilebilen envanteri, hata göstergelerini ve seçilen yüklerdeki davranışı aynı çalışma klasöründe toplar. Fiziksel muayene, satın alma konfigürasyonu kontrolü ve üretici offline tanılaması ayrı kabul adımlarıdır.

Hedef platform Linux fiziksel hosttur. Python 3.9+ standart kütüphanesi kullanılır. Debian/Ubuntu/Proxmox araç kurulumu desteklenir. R740/PERC ve Proxmox'a özel alanlar mevcuttur; araç genel Linux üzerinde de erişebildiği kapsamı toplar. Container içinden çalıştırma fiziksel donanımı eksik gösterebilir ve önerilmez.

## İşlem sırası

1. Parametre doğrulama; gerçek çalışmada root ve Linux kontrolü.
2. Host genelinde tek çalışma kilidi; private rapor klasörü.
3. İstenmişse apt paket kurulumu.
4. Donanım, işletim sistemi, araç sürümleri ve Proxmox envanteri.
5. Kernel, servis, sensör/IPMI, SMART, ZFS/mdraid ve PERC bilgileri.
6. Önceki durum: MemAvailable, CPU sıcaklıkları, EDAC ve NIC sayaçları.
7. Disk modu seçilmişse mount/yol/kapasite önkoşulları; ardından ilgili yük aşamaları.
8. Her yük aşamasından önce VM/CT, sıcaklık, RAM rezervi ve mevcut FAIL kontrolü.
9. Yük sırasında yaklaşık iki saniyede bir izleme; eşik aşımında süreç grubunu sonlandırma.
10. Son sayaçlar, çalışma zaman aralığındaki kernel kayıtları, SEL; disk modunda tekrar storage sağlığı.
11. Geçici dosya temizliği ve TXT/HTML/JSON/CSV raporlama.

Sağlık modu yük aşamalarını atlar. `full` ağ throughput testi içermez; ağ ayrı uç gerektirdiği için ayrıca seçilir.

## CPU

`stress-ng --cpu N --cpu-load Y --cpu-method matrixprod --verify` kullanılır. Varsayılan iki worker ve %75 hedef yük, kısa ve kontrollü bir başlangıçtır. Tüm çekirdekleri yüklemek için açık `--cpu-workers` ve `--cpu-load 100` gerekir.

Metrics satırından bogo ops, gerçek/user/system süreleri ve bogo ops/s çıkarılır. Bu değerler standart bir üretici performans puanı değildir; aynı stress-ng sürümü, metot, worker, süre ve güç profiliyle karşılaştırılmalıdır. Tablonun formatı tanınmazsa uyarı verilir; ham çıktı korunur.

OS görebildiği coretemp/k10temp/zenpower/cpu_thermal sensörleri, bellek rezervi ve EDAC UE artışı izlenir. Thermal throttle sayaçları varsa öncesi/sonrası farkları raporlanır. Bunlar CPU frekansının her an tam olduğunu veya BIOS güç ayarlarının doğru olduğunu kanıtlamaz.

## RAM

Tek `stress-ng --vm 1 --vm-bytes MUTLAK_BYTE --vm-method all --verify` worker kullanılır. Bu tahsis yöntemi toplam RAM'in yüzdesini doğrudan stress-ng'ye vermek yerine güncel MemAvailable ve rezervle sınırlandırılır. Tüm fiziksel adreslerin/DIMM'lerin test edilmesi garanti edilemez; Linux allocator, kernel ve diğer uygulamalar bellek kullanır.

- Bellek testinden önce ve yük boyunca kullanılabilir bellek kontrol edilir.
- EDAC `ce_count` ve `ue_count` görünüyorsa toplanır; yoksa SKIP olur.
- Başlangıç UE veya `HardwareCorrupted > 0` FAIL; CE birikimi inceleme uyarısıdır.
- Yeni UE yükü durdurur. CE artışı test sonunda uyarıdır; sayaçların kaybolması/reseti ayrıca incelenir.
- EDAC sayacı görünmemesi ECC olmadığı veya ECC'nin sorunsuz olduğu anlamına gelmez.

R740 DIMM kabulü için iDRAC/Dell offline bellek testi ve DIMM slot/kapasite/hız/kanal yerleşimi ayrıca doğrulanmalıdır.

## Disk benchmark profili

| Aşama | İş yükü | Blok | Queue depth | Bitiş koşulu |
|---|---|---|---:|---|
| seq-write | Sıralı yazma | 1 MiB | 16 | Dosyanın tamamı; dış timeout 300 sn |
| seq-read | Sıralı okuma | 1 MiB | 16 | Aynı dolu dosyanın tamamı; dış timeout 300 sn |
| randread-4k | Rastgele okuma | 4 KiB | 32 | Varsayılan 30 sn; dış timeout +30 sn |
| randwrite-4k | Rastgele yazma | 4 KiB | 32 | Varsayılan 30 sn; dış timeout +30 sn |

Hepsi tek job ve `libaio`, `direct=1` kullanır. Okuma işlerinde `--readonly`, yazma işlerinde `end_fsync=1` vardır. `refill_buffers`/`scramble_buffers` veri tekdüzeliğini azaltmak için seçilir; gerçek uygulama veri yapısını simüle etmez. Test fio CRC veri bütünlüğü doğrulaması içermez; burada ölçülen performans ve komut hatalarıdır.

JSON'dan her yön için MiB/s, IOPS, ortalama completion latency ve p99 completion latency (ms) çıkarılır. Completion latency, uygulama uçtan uca yanıt süresiyle aynı değildir. Eksik/başarısız job JSON'u PASS sayılmaz.

`direct=1` dosya sistemi cache etkisini sınırlamayı hedefler; PERC cache, disk cache veya ZFS ARC'nin tamamen devre dışı olduğunu kanıtlamaz. ZFS direct I/O davranışı sürüm/ayar bağımlıdır. Test boyutu cache'den küçükse sonuç kısa süreli burst performansını yansıtabilir. Araç cache flush/drop, ZFS property değişimi veya RAID cache ayarı yapmaz.

Dosya sistemi boş alanı kontrolü underlying thin pool'u bütünüyle doğrulamaz. Üretime ayrılmış LVM-thin, zvol veya ham aygıta test amacıyla doğrudan yazmak bu projenin kapsamı dışındadır.

## SMART ve RAID

SMART genel sağlık bilgisi tek başına tüm disk sorunlarını dışlamaz. `smartctl` dönüş değeri normal tek hata kodu değil bitmask olarak işlenir:

| Bitler | Yorum |
|---|---|
| 0–2 | Erişim/argüman/SMART komut hatası → WARN |
| 3–4 | Genel sağlık veya mevcut prefail eşiği → FAIL |
| 5–7 | Geçmiş eşik/hata/self-test kaydı → WARN |

NVMe critical warning ve SMART `passed=false` ayrıca FAIL üretir. NVMe media_errors ve ATA 5/197/198 ham değerleri >0 ise uyarı üretilir; neden ve model bazında değerlendirme gerekir. Komut timeout'u SMART bitmask'i gibi yorumlanmaz.

`smartctl --scan-open -j` tarafından raporlanan aygıt/adaptör tipleri ayrı ayrı sorgulanır; insan çıktısındaki `# comment` parçaları komut argümanı olarak geçirilmez. Tarama bütün PERC fiziksel disklerini bulmayı garanti etmez. Slot/disk envanterini PERC/iDRAC ile eşleştirin.

ZFS pool state, bilinen READ/WRITE/CKSUM sayaçları ve hata özeti; mdraid `[UU]` üyelik ve recovery işaretleri incelenir. PERC JSON parser'ı bilinen Controller Status, State ve hata sayaçlarını yorumlar. Bilinmeyen şemalar veya eksik cache ayrıntıları manuel incelemeye bırakılır.

## Ağ

Fiziksel NIC driver/firmware ve ethtool sayaçları; tüm görünen interface'lerin Linux hata/drop sayaçları toplanır. Yük öncesi/sonrası farklar hangi testin ağ hatası ürettiğini tek başına kanıtlamaz; eşzamanlı trafik de etkiler.

`iperf3` yalnızca TCP, tek paralel akış, ileri ve ters yön kullanır. Client'ın TX/RX değeri fiziksel link hızının birebir eşiti değildir. Karşı uç, RTT, MTU, switch ve CPU sınırları incelenmelidir. UDP kayıp/jitter ve çoklu akış bu sürümde otomatik test edilmez.

## Önerilen kabul kaydı

| Başlık | İncelenecek kanıt | Karar |
|---|---|---|
| Donanım eşleşmesi | DMI, PCI, disk/NIC listesi, satın alma konfigürasyonu | Beklenen adet/model/kapasite eşleşmeli |
| CPU | Seçilen tüm worker'lar, süre, hata ve throttling/ısı kayıtları | Konfigürasyona uygun süre ve izleme kapsamı onaylanmalı |
| RAM | DIMM yerleşimi, CE/UE farkları, offline tanılama | UE olmamalı; CE/eksik sayaçlar açıklanmalı |
| PERC | Controller, VD, PD, rebuild, BBU/CacheVault | Fiziksel yapı ve cache koruması elle doğrulanmalı |
| Diskler | SMART, hata sayaçları, NVMe wear/media bilgileri | Mevcut/geçmiş hatalar yorumlanmalı |
| Storage | Mount kaynağı, kapasite, ZFS/mdraid, fio p99/IOPS/BW | Aynı profilli referans veya iş gereksinimiyle karşılaştırılmalı |
| NIC | Bağlantı/driver, hata farkları, iki yön iperf | Hedef throughput ve ağ koşullarıyla karşılaştırılmalı |
| Güç/termal | PSU/fan/IPMI/iDRAC kayıtları | Redundancy, normal sensörler ve test altındaki davranış doğrulanmalı |
| Son karar | TXT/JSON + iDRAC + offline tanılama | Sorumlu kişi ve tarih ile kabul/koşullu kabul/ret |

Proje sabit bir “R740 en az X IOPS” veya “Y puan üstü geçer” eşiği içermez. RAID seviyesi, disk tipi/adedi, cache, CPU SKU ve ağ yapısı bilinmeden bu tür eşikler yanıltıcı olur. İlk temiz kurulum sonuçlarını aynı test profiliyle referans olarak saklayın.
