# LinuxBenchmark

Dell PowerEdge R740 ve Linux/Proxmox VE hostları için donanım envanteri, sağlık incelemesi ve kontrollü performans/kabul testleri. Mevcut `r740-health.sh` çalışmasının 2.0 sürümüdür.

Yeni alınan veya donanımı değişen bir sunucuda şu sorulara kanıt toplar:

- Beklenen CPU, DIMM, disk, RAID denetleyicisi ve ağ kartı gerçekten takılı mı?
- SMART, PERC, ECC, sensör veya kernel kayıtlarında incelenmesi gereken bir durum var mı?
- Seçilen yük ve süre altında CPU/RAM testi hata bildiriyor mu?
- Seçilen dosya sistemi ne kadar bant genişliği, IOPS ve gecikme sağlıyor?
- İkinci bir makineye TCP aktarımında iki yönde ne ölçülüyor?
- Test öncesinden sonrasına ECC, ağ hata sayaçları ve SEL kayıtları değişiyor mu?

**Varsayılan çalıştırma yük testi yapmaz ve paket kurmaz.** Sağlık modu da SMART, IPMI ve envanter sorguları nedeniyle az miktarda I/O/CPU kullanır; SMART sorgusu uyuyan diskleri uyandırabilir. Araç otomatik kabul sertifikası üretmez.

## Hızlı başlangıç

Hedef host üzerinde Bash, Git ve Python **3.9+** bulunmalıdır. Paket otomasyonu Debian/Ubuntu/Proxmox içindir; başka Linux dağıtımlarında araçları kendiniz kurup `--install-deps` olmadan çalıştırabilirsiniz. Gerçek toplama ve yük testi root gerektirir. PyPI paketi gerekmez.

```bash
git clone https://github.com/aga-b/LinuxBenchmark.git
cd LinuxBenchmark
chmod +x r740-health.sh

# Root gerektirmez; dosya oluşturmaz, harici komut çalıştırmaz.
./r740-health.sh --dry-run

# Salt sağlık/envanter toplama. Root shell üzerinde çalıştırın.
./r740-health.sh

# Gerekli Debian paketlerini açıkça kur ve sağlık kontrolünü çalıştır.
./r740-health.sh --install-deps --no-stress
```

`r740-health.sh`, Python motorunun uyumluluk girişidir. **Yalnızca .sh dosyasını kopyalamak yeterli değildir:** `linuxbenchmark.py` aynı dizinde olmalıdır. Depoyu klonlayabilir veya bu iki dosyayı birlikte taşıyabilirsiniz.

Komutun `1` koduyla dönmesi mutlaka bozuk donanım anlamına gelmez. Uyarılar ve ölçülemeyen kontroller de bu kodu üretir; `REPORT.txt` ve `report.json` ayrıntıyı açıklar.

## Çalışma modları

Her gerçek mod önce envanter ve sağlık kontrolü toplar. Yük aşamasından önce güvenlik kontrolleri yapılır.

| Komut / mod | CPU + RAM yükü | Geçici disk dosyası | Ağ throughput |
|---|---:|---:|---:|
| Varsayılan / `--mode health` / `--no-stress` | Hayır | Hayır | Hayır |
| `--quick` | Test başına 20 sn | Hayır | Hayır |
| `--stress-only` | Test başına 60 sn | Hayır | Hayır |
| `--mode full --fio-dir /HEDEF` | Test başına 60 sn | Evet | Hayır |
| `--mode disk-only --fio-dir /HEDEF` | Hayır | Evet | Hayır |
| `--mode network --iperf-server ADRES` | Hayır | Hayır | Tek TCP akışı, ileri + geri |

**v1 davranış değişikliği:** parametresiz çalıştırma artık CPU/RAM/fio başlatmaz. `--quick` de disk yazmaz. Disk için `full` veya `disk-only` ve açık hedef dizini gerekir. Ayrıntılar: [Sürüm değişiklikleri](CHANGELOG.md).

## R740 kabul akışı örneği

Önce sağlık raporunu ve iDRAC/PERC kayıtlarını inceleyin. Yük örneklerini boş veya bakımda olan host üzerinde uygulayın. `/var/lib/vz` yalnızca bir **dosya sistemi örneğidir**; asıl storage'ınızın mount noktası farklı olabilir.

```bash
# 1. Sağlık raporu
./r740-health.sh --no-stress

# 2. Kısa CPU/RAM denemesi; disk yazmaz
./r740-health.sh --quick

# 3. Seçilen yerel dosya sisteminde özel test dizini
install -d -m 0700 /var/lib/vz/linuxbenchmark-test
findmnt -T /var/lib/vz/linuxbenchmark-test

# 4. Önce planı gözden geçir
./r740-health.sh --mode full \
  --fio-dir /var/lib/vz/linuxbenchmark-test --fio-size 2G --dry-run

# 5. CPU/RAM + disk testi
./r740-health.sh --mode full \
  --fio-dir /var/lib/vz/linuxbenchmark-test --fio-size 2G
```

Varsayılan CPU testi en fazla iki mantıksal worker ve worker başına %75 yük kullanır. Bu bir tüm çekirdek burn-in testi değildir. Ayrılmış bakım hostunda daha kapsamlı CPU/RAM denemesi:

```bash
./r740-health.sh --stress-only --duration 900 \
  --cpu-workers "$(nproc)" --cpu-load 100 \
  --memory-percent 50 --memory-mib 16384 --reserve-mib 8192
```

Bu örnek RAM için **16 GiB** ister. Çalıştırma anındaki `MemAvailable` değerinin %50'si ve 8 GiB rezerv buna izin vermelidir; aksi halde yük başlamaz veya sonraki aşama durur. DIMM kapasitenize göre değiştirin. Varsayılan tahsis `min(MemAvailable × %25, MemAvailable − 4 GiB, 8 GiB)` değeridir. Ayrıntılı parametreler ve senaryolar: [Kullanım kılavuzu](docs/KULLANIM.md).

## Güvenlik sınırları

- Ham aygıta (`/dev/sda`, NVMe namespace, LVM LV, zvol vb.) yazılmaz; mevcut disk dosyası hedef olarak alınmaz.
- fio hedefi mevcut, yerel `ext4/xfs/zfs/btrfs` dizini olmalıdır. Üst dizinler dahil root sahipliği ve grup/diğer yazma yasağı aranır. NFS/CIFS/tmpfs/overlay ve `/dev /proc /sys /run` reddedilir.
- Özel ve rastgele adlı `0700` dizinde yalnızca `test.bin` oluşturulur. Boş alan rezervi `max(2 GiB, dosya sistemi kapasitesinin %10'u)` değeridir.
- Sıralı yazma dosyayı doldurur, ardından okuma ve 4K rastgele testler gelir. `direct=1` başarısızsa otomatik buffered fallback yapılmaz.
- Sıcaklık, bellek rezervi, fio boş alanı ve yeni EDAC UE hatası yük sırasında yaklaşık iki saniyede bir izlenir. Eşik aşılırsa süreç grubu durdurulur; kalan yük aşamaları başlatılmaz.
- CPU sıcaklık sensörü yoksa uyarı üretilir; otomatik termal izleme garantisi verilemez. Varsayılan 90°C bir yazılım durdurma eşiğidir, Dell'e özel donanım limiti değildir.
- Proxmox üzerindeki yerel VM/CT durumu belirsizse veya guest aktifse yük engellenir. Açık istisna: `--allow-active-workloads`. Docker/libvirt ve Proxmox dışı iş yükleri otomatik tespit edilmez.
- Firmware güncellemesi, reboot, RAID ayarı, scrub/resilver, SMART self-test, SEL temizleme veya ağ/firewall değişikliği yapılmaz.
- SIGINT/SIGTERM sonrasında alt süreçler durdurulur, kendi dosyası temizlenir ve mümkünse kısmi rapor yazılır. SIGKILL, elektrik kesintisi ve kernel seviyesinde takılı I/O için temizlik garantisi yoktur.

Bu önlemler üretim performansına etkisiz çalışma garantisi vermez. Yük testleri bilinçli olarak kaynak tüketir. [Test metodolojisi ve kabul ölçütleri](docs/METODOLOJI.md).

## Raporlar

Varsayılan ana dizin `/root/linuxbenchmark/` olur. Her çalışma hostname, yerel zaman damgası ve rastgele sonek ile ayrılır. Rapor içindeki zamanlar UTC ve açık timezone içerir.

| Dosya / dizin | İçerik |
|---|---|
| `REPORT.txt` | Öncelikli bulgular, metrikler, kapsam sınırları |
| `REPORT.html` | Harici servis/JS gerektirmeyen HTML; göreli ham log bağlantıları |
| `report.json` | Şema v1: metadata, checks, commands, metrics, summary |
| `inventory/` | CPU, NUMA, DMI/DIMM, PCI/NIC/disk, Proxmox sürüm/depolama |
| `logs/` | SMART/PERC/IPMI/kernel/servis çıktıları ve `console.log` |
| `logs/telemetry.json` | Yük sırasında CPU sıcaklığı, RAM ve hata sayaçları |
| `benchmarks/` | stress-ng/fio/iperf3 ham sonuçları ve `metrics.csv` |

HTML raporunun log bağlantıları için tüm çalışma klasörünü birlikte taşıyın. Raporlar izinleri kısıtlı oluşturulur; seri numarası, IP ve sistem bilgileri içerebilir. Ham loglar repoya eklenmemelidir (`reports/` zaten ignore edilir).

`PASS` yalnızca ilgili kontrol/test içindir. `INFO` envanter veya komut yürütme bilgisidir; donanımın sağlıklı olduğunu söylemez. `WARN` inceleme, `FAIL` hata/koruma durdurması, `SKIP` ise ölçülemeyen kapsam anlamına gelir.

| Süreç çıkış kodu | Anlam |
|---:|---|
| `0` | Uyarı/hata/atlanan kontrol yok; manuel kabul incelemesi yine gerekir |
| `1` | Uyarı veya eksik kapsam var; raporu inceleyin |
| `2` | FAIL bulgusu / yük testi hatası / iç hata |
| `3` | Parametre, bağımlılık, izin, güvenlik önkoşulu veya rapor yazma sorunu |
| `130` / `143` | SIGINT / SIGTERM ile kesildi |

JSON `summary.exit_code` bulgu kodudur (0/1/2); `metadata.process_exit_code` gerçek çalışma kodudur ve önkoşul/kesinti halinde farklı olabilir. [Rapor okuma ve şema](docs/RAPORLAMA.md).

## Ağ testi

İkinci, kontrolünüzdeki makinede `iperf3 -s` çalıştırın; test portunu yalnızca gerekli kaynak için erişilebilir yapın. Host üzerinde:

```bash
./r740-health.sh --mode network --iperf-server 192.168.100.20 \
  --iperf-port 5201 --iperf-seconds 30
```

Adres örnektir; kendi izinli test ucunuzu yazın. Araç ağ ayarlarını değiştirmez ve kendiliğinden iperf server başlatmaz. NIC bağlantı hızı ile uygulama throughput'u farklı ölçümlerdir; VLAN, switch, MTU, TCP ve karşı uç sonucu etkiler.

## Proje yapısı ve geliştirme

- `r740-health.sh`: Eski komut adıyla Bash giriş noktası.
- `linuxbenchmark.py`: Python standart kütüphanesiyle toplama, güvenlik ve raporlama motoru.
- `docs/`: Türkçe kullanım, test metodolojisi, PERC rehberi, rapor şeması ve sorun giderme.
- `tests/`: Donanımdan bağımsız parser, güvenlik ve akış regresyon testleri.
- `.github/workflows/ci.yml`: `self-hosted, linux, x64, ci-linux` etiketli runner üzerinde sözdizimi ve birim testleri. CI donanım benchmark'ı çalıştırmaz.

```bash
bash -n r740-health.sh
python3 -m py_compile linuxbenchmark.py
python3 -m unittest discover -s tests -v
```

Geliştirme ortamında gerçek R740, iDRAC/PERC veya Proxmox host erişimi bulunmadığından donanım uyumluluğu uçtan uca doğrulanmış sayılmaz. `tests/` çıktıları yazılım davranışının kanıtıdır. İlk hedef-host raporu [R740 kontrol listesi](docs/R740-PERC.md) ile değerlendirilmelidir.

## Dokümantasyon

- [Ayrıntılı kullanım ve tüm seçenekler](docs/KULLANIM.md)
- [Metodoloji, ölçüm sınırları ve kabul kontrolü](docs/METODOLOJI.md)
- [R740, PERC, iDRAC kontrol listesi](docs/R740-PERC.md)
- [Raporlama ve JSON şeması](docs/RAPORLAMA.md)
- [Sorun giderme](docs/SORUN-GIDERME.md)
- [Geliştirme/test notları](docs/GELISTIRME.md)
- [Resmî teknik kaynaklar](docs/KAYNAKLAR.md)
