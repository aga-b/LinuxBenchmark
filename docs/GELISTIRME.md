# Geliştirme ve doğrulama

## Tasarım

Shell dosyası eski kullanım adını korur. Python motoru process group yönetimi, JSON bitmask/şema ayrımı, güvenli dosya yaşam döngüsü ve farklı rapor biçimlerini standart kütüphaneyle sağlar. Modül import edilince host sorgusu veya test çalışmaz.

Harici komutlar argüman listeleriyle, shell kullanılmadan yürütülür. Her komut ayrı süreç grubunda, süre sınırıyla çalışır. stdout/stderr doğrudan kanıt dosyasına gider. SIGINT/SIGTERM ve timeout'ta grubun tamamına TERM, ardından gerekirse KILL gönderilir. Linux kernelinde kesilemeyen I/O'nun anında bitmesi garanti edilemez.

## Yerel kontroller

```bash
bash -n r740-health.sh
python3 -m py_compile linuxbenchmark.py
python3 -m unittest discover -s tests -v
./r740-health.sh --dry-run
./r740-health.sh --mode full --fio-dir /ORNEK --dry-run
```

Son komut yalnızca plan doğrular; `/ORNEK` dizininin varlığını veya mount güvenliğini onaylamaz. Testler apt, stress-ng, fio veya gerçek iperf yükü başlatmaz. Süreç sonlandırma testleri yalnızca kısa süreli Python sleep süreçlerini oluşturup sonlandırır.

## Regresyon kapsamı

- Varsayılan health ve geriye uyumlu modların davranışı.
- Çelişen modlar, bozuk/aşırı boyutlar, worker sınırı ve ağ hedefi doğrulaması.
- MemAvailable/rezerv/yüzde hesabı; aşırı RAM isteğinin CPU başlamadan reddi.
- Ham aygıt ve sanal/uzak/salt okunur dosya sistemi reddi.
- fio özel dosya yolu; okuma işlerinde `--readonly`, kapalı file create ve hedef dışı temizliğin engellenmesi.
- Root sahipliği/üst dizin yazma koşulları ve boş alan rezervi.
- Aktif/belirsiz Proxmox guest durumunun yükü engellemesi; açık istisna davranışı.
- SMART bitmask, NVMe warning, PERC offline/hot spare/bilinmeyen şema ayrımı.
- fio latency/BW dönüşümü, boş/başarısız job reddi; stress-ng metrics parser.
- Komut hatası, timeout'ta alt süreç grubu temizliği.
- Yük sırasında sıcaklık/RAM/ECC/boş alan güvenlik durdurması.
- TXT/JSON/HTML rapor üretimi ve HTML escape.
- Varsayılan akışta apt/yük komutu çalıştırılmaması (araç `--version` sorguları serbesttir).

## CI

Workflow `self-hosted, linux, x64, ci-linux` etiketleriyle çalışır. Python 3.9+ ve Bash runner'da kurulu olmalıdır. Hosted dakika kullanmaz; uygun runner yoksa job kuyrukta bekler. Workflow host donanım kabul testi veya apt kurulumunu çalıştırmaz.

Pull request kodu self-hosted runner üzerinde çalıştığından repository/runner erişimi yalnızca güvendiğiniz katkıcılara açık olmalıdır. Bu workflow dış PR'ları otomatik onaylamaz ve özel runner güvenlik politikanızın yerini almaz.

## Yeni donanım/parser desteği

1. Model ve araç sürümünü kaydedin.
2. Seri/IP/kurum bilgisini anonimleştirerek örnek JSON hazırlayın.
3. Geçerli, bozuk ve eksik alan senaryolarını test edin.
4. Tanınmayan durumu otomatik sağlıklı saymayın.
5. Gerçek host doğrulamasını birim test sonucu gibi sunmayın.
6. Şema değişikliği gerekiyorsa `schema_version` ve raporlama kılavuzunu güncelleyin.

## Doğrulama sınırı

Bu geliştirme sırasında fiziksel R740, PERC/iDRAC ve gerçek Proxmox yük testi yapılmadı. SMART/PERC/fio/stress çıktıları kontrollü sentetik test verileriyle doğrulandı. Hedef host üzerinde ilk sağlık raporu ve bakım penceresindeki gerçek testler ayrıca yürütülmelidir. Donanım kabul kararı kullanıcı/operasyon sorumlusundadır.
