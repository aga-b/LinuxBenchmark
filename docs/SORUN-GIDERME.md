# Sorun giderme

## Komut 1 döndü; test başarısız mı?

Önce `REPORT.txt` okuyun. `1`, WARN veya SKIP demektir. PERC/EDAC/IPMI görünürlüğü eksikse veya throughput istenmemişse bu beklenebilir. `PASS` satırları tek tek ilgili testlere aittir; eksik kapsamı kapatmaz.

`3` genellikle test önkoşuludur: root yok, hedef dizin yanlış, paket eksik, aktif guest veya kapasite yetersiz. Sağlık kontrolünde FAIL varsa yük engellenir ve `2` öncelik kazanır. JSON'da bulgu koduyla gerçek süreç kodu ayrı tutulur.

## Python motoru bulunamadı

Yalnızca `r740-health.sh` taşınmış olabilir. `linuxbenchmark.py` aynı dizinde olmalı. Bash başlatıcısını `bash r740-health.sh` ile de çalıştırabilirsiniz; Python 3.9+ yine gereklidir.

## Paket kurulumu / enterprise repository hatası

`logs/apt-update.log` ve `logs/apt-install.log` okuyun. Proxmox repository/lisans yapılandırmasını kendi yönetim prosedürünüzle düzeltin. Araç enterprise/no-subscription kaynaklarını değiştirmez ve paket yükseltmesini otomatik yapmaz. Paket kurulumu kısmi kalabilir; rapor her eksik aracı gösterir. Önceden mevcut iperf3 servisini otomatik durdurmaz.

## Aktif veya belirsiz VM/CT nedeniyle yük başlamadı

`logs/active-qemu.log` ve `logs/active-lxc.log` inceleyin. Araç node'un yerel `qm list` / `pct list` çıktısını kontrol eder. `running` dışındaki `paused` gibi durdurulmamış durumlar da aktif sayılır. Liste okunamazsa güvenli tarafta durur.

Bakım koşulunu siz sağladıysanız ve etkisini kabul ediyorsanız:

```bash
./r740-health.sh --quick --allow-active-workloads
```

Bu seçenek yalnızca VM/CT engelini aşar; sıcaklık/RAM/ECC/FAIL kontrollerini kaldırmaz. Docker/libvirt/uygulama yükü otomatik kapsanmaz. Araç guest'leri durdurmaz veya taşımaya çalışmaz.

## RAM isteği reddedildi

`free -h` ve `/proc/meminfo` içindeki MemAvailable değerini inceleyin. Toplam takılı RAM değil, o anki kullanılabilir bellek önemlidir. Tahsisi küçültün; daha kapsamlı test gerekiyorsa bakımda `--memory-percent` değerini ve açık `--memory-mib` isteğini planlayın. Rezerv en az 1 GiB olabilir; varsayılan 4 GiB'dir. Üretim hostunda sırf testi geçirmek için rezervi düşürmeyin.

## Sıcaklık eşiği veya ECC nedeniyle test durdu

`logs/telemetry.json`, `logs/kernel-since-start.log`, IPMI ve iDRAC kayıtlarını karşılaştırın. Fan, hava akışı, heatsink, güç profili veya DIMM hatalarını inceleyin. `--max-temp` artırmak bir donanım sorununun çözümü değildir. EDAC görünmüyorsa bu kontrol yapılamaz; üretici kayıtlarını kullanın.

## SMART görünmüyor / permission / bitmask

Root çalıştırdığınızı, smartmontools'un kurulu olduğunu ve denetleyici erişimini kontrol edin. PERC arkasında yalnızca virtual disk görülebilir. `smartctl` 64/128 gibi kodlar geçmiş hata kaydı bitleri olabilir; tek başına erişim hatası sanılmamalı. Araç bunları ayrı yorumlar. `logs/smart-scan.log` ve ilgili `smart-N.log` dosyasını iDRAC fiziksel disk listesiyle eşleştirin.

## PERC CLI yok / JSON formatı farklı

[Üretici kontrol listesine](R740-PERC.md) bakın. CLI otomatik indirilmez. PATH veya belirtilen `/opt/MegaRAID/...` yollarından bulunmalıdır. JSON şeması tanınmazsa raw logu inceleyin; PASS üretmek için parser'ı zorlamayın. Denetleyici modeli/CLI sürümü ve anonimleştirilmiş örnek, yeni parser desteği için gereklidir.

## IPMI veya CPU sensörü yok

Yerel IPMI aygıtı/driver, BIOS/iDRAC ayarı veya erişim izni eksik olabilir. Araç modül yüklemez, iDRAC parolası istemez. CPU thermal izlemesi yalnızca desteklenen hwmon isimleriyle yapılır. IPMI sıcaklık çıktısının bulunması, yük sırasındaki hwmon korumasının aktif olduğu anlamına gelmez. İzleme kapsamı uyarısını inceleyin.

## fio hedefi reddedildi

- `/dev/sda`, LV veya zvol yerine mevcut bir **yerel dosya sistemi dizini** seçin.
- `findmnt -T DIZIN` sonucunu kontrol edin. NFS/CIFS/tmpfs/overlay kullanılmaz.
- Dizin ve üstlerinin root sahipliği/grup-diğer yazma izinlerini kontrol edin. Proje var olan izinleri değiştirmez.
- Yol içinde `:` veya ters bölü bulunmamalı; fio bu karakterleri özel yorumlar.
- Dosya boyutu + `max(2 GiB, dosya sisteminin %10'u)` kadar boş alan bulunmalı.
- LVM-thin kapasitesi veya ZFS snapshot alanını ayrıca kontrol edin.

## fio binary yanlış / direct I/O desteklenmiyor

`fio --version` çıktısı `fio-...` olmalıdır. Aynı adı kullanan başka bir Python/CLI aracı yanlışlıkla bulunabilir; araç bunu reddeder. Hangi binary'nin PATH'te olduğunu `command -v fio` ile inceleyin.

Dosya sistemi/direct I/O destek hatasında raw çıktı saklanır; benchmark otomatik buffered teste çevrilmez. Fio sürümünü ve dosya sistemi/kernel özelliklerini kontrol edin. Direct I/O semantiği ZFS sürümüne göre değişebileceği için aynı raporları aynı yazılım koşullarında karşılaştırın.

## Ağ testi yavaş / bağlantı reddedildi

İkinci uçta `iperf3 -s` çalışmalı ve client'tan port erişilebilir olmalı. DNS, yönlendirme, MTU, NIC link hızı, switch portu, TCP pencere/RTT ve karşı uç kapasitesini inceleyin. Script firewall, MTU, bonding veya offload ayarı yapmaz. `--iperf-seconds` yalnızca her throughput aşamasını değiştirir.

## Çalışma kilidi

Host genelinde `/run/lock/linuxbenchmark.lock` üzerinde flock kullanılır. Dosyanın diskte kalması normaldir; kilit açık file descriptor ile yaşar ve süreç bitince serbest kalır. Canlı testi atlatmak için lock dosyasını silmeyin. Diğer çalışmanın bitmesini bekleyin.

## Kesintiden sonra dosya kaldı

SIGKILL, güç kaybı, disk hatası veya kernel seviyesinde takılı I/O temizliği engelleyebilir. Console logda tam geçici dosya yolunu bulun. Sadece o çalışmaya ait `test.bin` ve boş özel dizini kontrollü kaldırın. Script temizlikte recursive silme kullanmaz ve symlink'i takip etmez; beklenmeyen içerikte uyarı bırakır.
