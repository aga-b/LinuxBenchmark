# Kullanım kılavuzu

## 1. Host hazırlığı

1. Fiziksel donanımı ve beklenen DIMM/disk/NIC adetlerini satın alma listesiyle eşleştirin.
2. iDRAC'a erişin; Lifecycle Log, SEL, firmware ve PERC/cache korumasını inceleyin.
3. Proxmox kurulumunu, storage mount noktalarını ve zaman senkronizasyonunu tamamlayın.
4. İlk sağlık raporunu alın. Kaynak tüketen testler için bakım penceresi belirleyin.
5. Tam depo veya yan yana `r740-health.sh` + `linuxbenchmark.py` dosyalarını host'a aktarın.

```bash
# Yönetim makinesinde örnek aktarım
scp r740-health.sh linuxbenchmark.py root@SUNUCU:/root/

# Sunucuda root shell
cd /root
chmod +x r740-health.sh
./r740-health.sh --version
./r740-health.sh --dry-run
```

Script kendi kendini güncellemez veya internetten shell kodu çalıştırmaz. Paket kurulumu ayrı ve açık bir tercihtir.

## 2. Araç kurulumu

```bash
./r740-health.sh --install-deps --mode health
```

`apt-get update` ardından `install -y --no-install-recommends --no-remove --no-upgrade` kullanılır. Depo/lisans kaynakları değiştirilmez. Mevcut paketler bu komutla yükseltilmez; güvenlik güncellemesi ayrı işletim sürecidir. Paket bağımlılıkları gerektiğinde kurulur; dpkg kurulum scriptleri çalışabilir. iperf3 daemon tercihi debconf ile kapalı seçilir.

Paketler: `smartmontools lm-sensors ipmitool dmidecode pciutils usbutils lshw ethtool fio stress-ng sysstat numactl nvme-cli iperf3`. `sysstat` ileri manuel teşhis için hazır bulundurulur; CPU/RAM/disk/ağ testlerini motor ayrı yürütür. Python3 ve Git önkoşuldur; başlatıcı bunları kendisi kurmaz.

Kurulum yoksa eksik araç `SKIP` olur. PERC/storcli lisanslı/üretici dağıtımı otomatik indirilmez. IPMI kernel modülleri veya sensörler otomatik yapılandırılmaz.

## 3. Tüm seçenekler

| Seçenek | Varsayılan | Davranış |
|---|---|---|
| `--mode` | `health` | `health`, `quick`, `full`, `stress-only`, `disk-only`, `network` |
| `--quick` | — | `--mode quick` eşdeğeri; CPU + RAM, test başına 20 sn |
| `--no-stress` | — | `--mode health` eşdeğeri |
| `--stress-only` | — | `--mode stress-only` eşdeğeri; envanter/sağlık da toplanır |
| `--out PATH` | `/root/linuxbenchmark` | Rapor ana dizini; altında yeni çalışma klasörü |
| `--install-deps` | Kapalı | Açık apt paket kurulumu; seçilen mod sonra devam eder |
| `--dry-run` | Kapalı | Parametre planı; gerçek disk/mount/sensör doğrulaması yapmaz |
| `--duration SN` | `60`; quick `20` | Her CPU ve RAM aşaması için; 5–86400 sn |
| `--cpu-workers N` | `min(2, mantıksal CPU)` | 1–4096; kullanılabilir mantıksal CPU sayısını aşamaz |
| `--cpu-load N` | `75` | Worker başına hedef yük; 1–100 |
| `--memory-mib N` | Otomatik | Açık RAM tahsisi; MiB, 64–1048576; güvenli tavanla sınırlanır |
| `--memory-percent N` | `25` | O anki MemAvailable üzerinden tavan; 1–75 |
| `--reserve-mib N` | `4096` | Host için bırakılacak kullanılabilir bellek; en az 1024 MiB |
| `--max-temp C` | `90` | Desteklenen CPU hwmon sensöründe durdurma eşiği; 50–100°C |
| `--allow-active-workloads` | Kapalı | Aktif veya durumu okunamayan Proxmox VM/CT için bilinçli istisna |
| `--fio-dir PATH` | Yok | `full/disk-only` için zorunlu mevcut yerel dizin |
| `--fio-size BOYUT` | `1G` | 64M–64G, tam sayı M/G; ikilik MiB/GiB |
| `--fio-seconds SN` | `30` | Her 4K rastgele test süresi; 5–3600 sn |
| `--iperf-server HOST` | Yok | Yalnızca network; izinli ikinci uç |
| `--iperf-port PORT` | `5201` | 1–65535 |
| `--iperf-seconds SN` | `10` | Her ileri/geri ağ testi; 5–3600 sn |
| `--version`, `--help` | — | Sürüm / yardım; root gerekmez |

Mod seçenekleri birbirini dışlar. Örneğin `--quick --no-stress` kabul edilmez. `--fio-size` tek başına disk testini etkinleştirmez. `--duration` disk/ağ süresini değiştirmez.

## 4. RAM tahsisi nasıl hesaplanır?

Her RAM testi başlamadan önce `/proc/meminfo` içindeki **MemAvailable** okunur; toplam RAM veya boş RAM yüzdesi kullanılmaz.

- Güvenli tavan = `min(MemAvailable × memory-percent / 100, MemAvailable − reserve)`; MiB'ye aşağı yuvarlanır.
- `--memory-mib` yoksa bu tavan ile **8 GiB** değerinin küçüğü seçilir.
- `--memory-mib` varsa açık değer kullanılır, fakat güvenli tavanı aşarsa test reddedilir. Açık değer 8 GiB üstüne çıkabilir.
- Tavan 64 MiB altındaysa test başlatılmaz.
- Yük boyunca MemAvailable rezervin altına düşerse test durdurulur.

CPU testi başlamadan da RAM isteği doğrulanır. Gerçek RAM aşamasında güncel bellekle yeniden doğrulanır. Örneğin VM'ler arada bellek tüketirse test daha düşük otomatik tahsis seçebilir veya durabilir. Rezerv/maksimum yüzdesi cgroup bellek limitlerinin yerine geçmez; araç fiziksel host için tasarlanmıştır.

Örnek: 128 GiB MemAvailable, `%50`, 16 GiB rezerv ve açık 32 GiB tahsis: tavan 64 GiB; 32 GiB test edilir. Varsayılan tahsiste aynı koşulda 8 GiB seçilirdi.

## 5. Doğru disk hedefi

Önce dosya sisteminin kaynağını görün:

```bash
findmnt -T /var/lib/vz
lsblk -o NAME,TYPE,SIZE,FSTYPE,MOUNTPOINTS,MODEL
pvesm status
```

`local-lvm` bir LVM-thin storage ise üzerinde host dosya sistemi dizini yoktur. `/var/lib/vz` çoğunlukla `local` storage/root dosya sistemi üzerindedir; onu test etmek `local-lvm` performansını ölçmez. Bu araç LV/zvol/ham disk için yazma benchmark'ı sunmaz. O storage için ayrı, gözden geçirilmiş VM/dosya sistemi test tasarımı gerekir.

Yerel dosya sisteminde:

```bash
install -d -m 0700 /MOUNT/linuxbenchmark-test
./r740-health.sh --mode disk-only \
  --fio-dir /MOUNT/linuxbenchmark-test --fio-size 4G --fio-seconds 60
```

`/MOUNT` gerçek mount noktasıyla değiştirilmelidir. Dizin ve tüm üstleri root sahipli olmalı; grup/diğer kullanıcıya yazma açık olmamalıdır. `/tmp` altında çalıştırılmaz. Script mevcut dosyaları silmez veya dizin izinlerini kendiliğinden düzeltmez.

Dosya alanı rezervi hedef dosya sistemi içindir. Thin pool fiziksel doluluğu, ZFS snapshot alanı ve başka katmanlardaki kapasite riskleri bununla tamamen doğrulanamaz. `pvesm`, `lvs` veya `zpool list` ile altyapı kapasitesini ayrıca inceleyin.

Fio test dosyası boyutu toplam yazma miktarı değildir: zaman temelli random-write aynı alanı tekrar yazar. 1 GiB dosyayla 30 saniyede çok daha fazla veri yazılabilir. Flash dayanımı ve PERC cache politikasını dikkate alın.

## 6. Süre ve durdurma

Quick/stress-only süresi yaklaşık `2 × duration + envanter/sağlık sorguları`dır. Full bunlara iki sıralı geçiş ve `2 × fio-seconds` ekler. Sıralı iş başına 300 sn, rastgele iş başına süre + 30 sn dış timeout vardır. SMART/PERC sorguları 90 sn, IPMI 60 sn sınırına sahiptir; disk/sensör sayısı toplam süreyi artırabilir.

Ctrl+C veya `kill -TERM PID` alt süreç grubunu durdurur. Çıkıştan önce post-check, cleanup ve raporlama yapıldığı için komut hemen kapanmayabilir. İkinci SIGINT/SIGTERM cleanup sırasında yok sayılır. Kasıtlı `kill -9` temizlik/raporlamayı engeller.

Elektrik kesintisi veya SIGKILL sonrasında `.linuxbenchmark-*/test.bin` kalmışsa `logs/console.log` içindeki tam hedefi doğrulayın ve yalnızca o çalışmaya ait dosyayı silin. Toplu `rm -rf` önerilmez.

## 7. Son raporu görüntüleme

```bash
python3 - <<'PY'
from pathlib import Path
files = list(Path('/root/linuxbenchmark').glob('*/REPORT.txt'))
if not files:
    raise SystemExit('Rapor bulunamadı')
latest = max(files, key=lambda p: p.stat().st_mtime)
print(latest)
print(latest.read_text())
PY
```

Çıktı dizinini değiştirdiyseniz örnekteki ana yolu da değiştirin. Raporu destek ekibine gönderecekseniz tüm çalışma klasörünü kopyalayın; önce gizli/kuruma özgü bilgileri inceleyin. Script raporu herhangi bir servise otomatik göndermez.
