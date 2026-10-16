# Değişiklik geçmişi

## 2.0.0 — 2026-10-16

İlk `r740-health.sh` sürümünü kapsamlı LinuxBenchmark projesine dönüştürür.

### Davranış değişiklikleri

- Varsayılan `full` yerine `health`; yük ve otomatik apt kurulumu kapalı.
- `--quick` yalnızca kısa CPU/RAM testi; eski 512 MiB disk yazması kaldırıldı.
- Disk için `--mode full/disk-only` ve açık `--fio-dir` zorunlu.
- Yeni varsayılan rapor kökü `/root/linuxbenchmark`; `--out` desteklenir.
- Eski `.sh` adı korunur; yanında `linuxbenchmark.py` gerekir. Python3 standart kütüphanesi kullanılır.
- `--no-stress`, `--stress-only`, `--fio-size` ve `--out` korunur. Boyutlar doğrulanır; boyut seçimi tek başına disk testi açmaz.
- Çıkış kodları anlamlıdır; eksik kapsam sessiz başarı sayılmaz.

### Güvenlik ve testler

- Açık paket kurulumu; apt sources/firmware/ağ yapılandırması değiştirilmez.
- Sınırlı CPU worker/yük; MemAvailable/rezerv/yüzdeye dayalı mutlak RAM tahsisi.
- Yerel VM/CT guard, sıcaklık/RAM/ECC/boş alan izleme ve host genelinde çalışma kilidi.
- Yalnızca private normal test dosyası; root sahipli yerel dizin; kapasite rezervi; readonly okuma işleri.
- Süre sınırları, süreç grubu temizliği ve SIGINT/SIGTERM sonrası kısmi rapor.
- SMART JSON/bitmask; PERC JSON, NVMe, ZFS/mdraid, IPMI/SEL ve öncesi/sonrası hata farkları.
- İzinli ikinci uçla iki yönlü TCP iperf testi.

### Raporlama ve proje

- TXT, HTML, JSON şema v1 ve seyrek metrik CSV.
- CPU/RAM bogo ops; fio MiB/s/IOPS/ortalama+p99 completion latency; iperf Gbit/s.
- Komut argümanları, dönüş kodları, süreleri, kanıt dosyaları ve telemetri.
- Türkçe kurulum/kullanım, metodoloji, R740/PERC, raporlama ve sorun giderme kılavuzları.
- Donanımsız regresyon testleri ve self-hosted CI.

Fiziksel R740 test sonucu bu sürüme dahil değildir; hedef host doğrulaması gerekir.
