# Rapor okuma ve veri şeması

## Önce hangi dosya okunmalı?

`REPORT.txt` bulguları FAIL → WARN → SKIP → PASS → INFO sırasıyla listeler. Her satırın kanıt dosyası varsa yolu yazılır. `REPORT.html` aynı bulguları tabloda ve metrikleri JSON olarak gösterir. HTML harici JavaScript, CSS, font veya servis çağırmaz; özel karakterler escape edilir.

`report.json` otomasyon içindir. `logs/console.log` kullanıcıya gösterilen olayları saklar; her komutun stdout/stderr'i kendi kanıt dosyasındadır. `commands` dizisi argümanları shell string yerine JSON listesi olarak kaydeder; metin shell üzerinden yeniden değerlendirilmez.

## Durumlar

| Durum | Anlam | Örnek |
|---|---|---|
| PASS | İlgili sınırlı test/sağlık kontrolü başarı bildirdi | SMART genel sonucu passed=true |
| INFO | Toplanan bilgi veya komutun normal tamamlanması | lscpu çıktı verdi |
| WARN | İnceleme gerektiren belirti veya komut erişim hatası | SMART geçmiş self-test kaydı, IPMI timeout |
| FAIL | Sağlık hatası, başarısız yük veya koruma durdurması | Yeni ECC UE, SMART failing, sıcaklık eşiği |
| SKIP | Araç/veri/yöntem yok; kontrol ölçülemedi | PERC aracı yok, EDAC görünmüyor |

Başarılı bir `ipmitool sel elist` komutu, SEL'de hata olmadığı anlamına gelmez. Geçmiş kayıtlar ham logdan değerlendirilir. Başarılı fio komutu da fiziksel disklerin tamamının kabul edildiği anlamına gelmez.

## Genel sonuç ve iki çıkış alanı

Öncelik: FAIL → REVIEW_REQUIRED (WARN) → INCOMPLETE (SKIP) → NO_ISSUES_DETECTED.

- `summary.exit_code`: bulguların 0/1/2 kodu.
- `metadata.process_exit_code`: gerçek çalışmanın çıkış kodu. Başlatma/önkoşul sorunu `3`, SIGINT `130`, SIGTERM `143` olabilir.
- `summary.acceptance`: her zaman `MANUAL_REVIEW_REQUIRED`.

Sağlık modunda iperf throughput kapsamı atlandığı için SKIP/INCOMPLETE normaldir. Bu durum sahte bir kabul “PASS” üretmemek içindir. PERC veya IPMI aracı yoksa ek SKIP/WARN da beklenebilir.

## JSON şema v1

| Alan | Tip / içerik |
|---|---|
| `schema_version` | `1`; tüketiciler bunu doğrulamalı |
| `metadata.version` | Aracın semantik sürümü |
| `metadata.host`, `mode` | Host ve çalışma modu |
| `metadata.started`, `finished` | Timezone içeren UTC ISO8601 |
| `metadata.options` | Etkili CLI seçenekleri; Path değerleri string |
| `metadata.output` | Host üzerindeki rapor klasörü |
| `metadata.process_exit_code` | Gerçek süreç çıkış kodu |
| `metadata.before`, `after` | Bellek, CPU sıcaklıkları, EDAC, NIC ve throttling sayaçları |
| `metadata.memory_test_bytes` | RAM testi başlarsa gerçek tahsis |
| `metadata.fio_filesystem` | Disk modunda findmnt kaynak/hedef/fstype/options |
| `summary` | Genel sonuç, sayaçlar, bulgu kodu ve manuel kabul şartı |
| `checks[]` | `name`, `status`, `message`, nullable `evidence` |
| `commands[]` | `name`, `argv[]`, `exit_code`, `duration_seconds`, `evidence`, `reason` |
| `metrics[]` | İş türüne göre seyrek metrik satırları |
| `limitations[]` | Kapsam ve yorum sınırları |

Eksik araç için gerçek komut yürütülmediğinden `commands` kaydı oluşmaz; `checks` içinde SKIP bulunur. Komut çıktısının `.log` uzantılı olması metin anlamına gelmez; fio/SMART/PERC/iperf çıktısı JSON olabilir. Timeout ile kesilmiş JSON tamamlanmamış olabilir.

## Metrikler

| İş türü | Alanlar |
|---|---|
| `stress-cpu`, `stress-vm` | bogo_ops, real/user/system_seconds, bogo_ops_per_real_second, bogo_ops_per_cpu_second |
| fio | job, direction, mib_s, iops, clat_mean_ms, clat_p99_ms |
| iperf | job, received_gbit_s, sent_gbit_s, retransmits |

`metrics.csv` bütün alanların birleşimini başlık yapar; bir işte olmayan sütun boştur. `logs/telemetry.json`, test adı ve timestamp ile ham sensör/sayaç örneklerini içerir. Sağlık modunda yük olmadığı için bu dizi boş olabilir.

Bogo ops/s farklı stress-ng sürümleri/metotları arasında kıyaslanmamalı. Fio MiB/s ikilik, iperf Gbit/s ondalık birimdir. Completion latency değerleri nanosaniyeden milisaniyeye çevrilir.

## Otomasyon örneği

```bash
python3 - /root/linuxbenchmark/CALISMA/report.json <<'PY'
import json, sys
with open(sys.argv[1]) as f:
    data = json.load(f)
if data['schema_version'] != 1:
    raise SystemExit('Desteklenmeyen şema')
print(data['summary'])
for check in data['checks']:
    if check['status'] in ('FAIL', 'WARN', 'SKIP'):
        print(check['status'], check['name'], check['message'], check['evidence'])
PY
```

Örnekteki `CALISMA` gerçek çalışma klasörüyle değiştirilmelidir. Kabul otomasyonunda yalnızca süreç kodu veya tek PASS satırı kullanılmamalı; beklenen donanım kapsamı, uyarılar ve dış tanılama kanıtları birlikte değerlendirilmelidir.
