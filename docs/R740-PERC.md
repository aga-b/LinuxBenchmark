# Dell R740 / PERC / iDRAC kontrol listesi

## Envanter ve fiziksel kabul

- Service Tag, model, BIOS/iDRAC sürümü ve satın alınan konfigürasyonu karşılaştırın.
- İki CPU bekleniyorsa socket/core/thread ve NUMA görünürlüğünü doğrulayın.
- DMI çıktısında takılı DIMM sayısı, kapasite, hız ve slotları kontrol edin; kanal yerleşimini Dell dokümanıyla eşleştirin.
- NIC/RAID modelini PCI listesiyle ve fiziksel etiketlerle karşılaştırın.
- Beklenen disk adedi ve seri numaralarını PERC/iDRAC slot envanteriyle eşleştirin.

Script `dmidecode`, `lscpu`, `numactl`, `lspci`, `lsblk`, `ethtool -i` ve yerel IPMI bilgilerini toplar. Eksik erişim varsa rapor bunu sağlıklı varsaymaz.

## PERC komutunun bulunması

PATH üzerinde şu adlar aranır: `perccli64`, `perccli`, `storcli64`, `storcli`. Ayrıca:

```text
/opt/MegaRAID/perccli/perccli64
/opt/MegaRAID/storcli/storcli64
```

Araç yoksa üreticinin **kendi denetleyicinize ve işletim sisteminize uygun** sürümünü edinip yönergesine göre kurun. Bu proje rastgele binary, RPM/DEB veya firmware indirmez. Storcli alternatifi her PERC modelinde birebir uyumluluk garantisi değildir.

Toplanan salt sorgu komutları:

```bash
perccli64 /call show all J
perccli64 /call/eall/sall show all J
```

Bazı sürümler farklı JSON alanları döndürebilir. Komut hata verirse ham log ve dönüş kodu saklanır. Parser şemayı tanımazsa manuel inceleme uyarısı verir. Hiçbir `set`, `delete`, `start rebuild`, `initialize`, `download` veya firmware işlemi çalıştırılmaz.

## İncelenecek durumlar

| Alan | Beklenen / yorum |
|---|---|
| Controller Status | `Optimal`; farklı değerler inceleme, `Failed/Offline` FAIL |
| Virtual Disk State | `Optl`; degrade/offline durumları açıklanmalı |
| Fiziksel disk | RAID üyesi `Onln`; `GHS/DHS` hot spare veya `JBOD` tasarıma göre beklenebilir |
| UGood / UBad / Offln / Msng | UGood yapılandırılmamış disk olabilir; UBad/Offln/Msng hata göstergesidir |
| Media / Other Error Count | Artış veya sıfır dışı değerler disk/bağlantı geçmişiyle incelenmeli |
| Predictive Failure Count | Sıfır dışı değer disk değişimi değerlendirmesi gerektirir |
| BBU / CacheVault | Koruma çalışır mı, learn cycle/charging/replace uyarısı var mı? |
| Cache policy | Requested/current write policy neden farklı? Write-back koruması var mı? |
| Arka plan işlemleri | Rebuild, initialization, consistency check aktif mi? Benchmark etkilenir |
| Patrol read / battery learn | Zamanlama ve son durum işletim prosedürüyle doğrulanmalı |

Parser tüm cache/BBU/CacheVault alanlarını ve üretici sürümlerini kapsamaz. “Komut tamamlandı” satırı bu tablonun tamamının geçmesi anlamına gelmez. Ham JSON'u ve iDRAC storage ekranını inceleyin.

## SMART erişimi

PERC virtual disk SMART sonucu, bütün fiziksel disklerin sağlıklı olduğuna kanıt değildir. `smartctl --scan-open -j` bazı sistemlerde `megaraid,N` aygıtlarını bulabilir; bazılarında fiziksel diskler eksik kalır. Script taramanın döndürdüğü `name` ve `type` değerlerini `smartctl -x -j -d TYPE DEVICE` ile sorgular.

Gerekirse üretici çıktısındaki denetleyici/disk eşlemesini bilen bir yönetici manuel sorgular. `megaraid,N` numarasını disk bay/slot numarası varsaymayın. Sonuçları PERC device ID ve slot bilgisiyle eşleştirin.

## iDRAC ve offline tanılama

Script yerel `ipmitool` arayüzünü kullanır; iDRAC IP, kullanıcı adı veya parola istemez/saklamaz. Erişilemiyorsa bunun nedenini raporlar; otomatik `modprobe` veya uzak bağlantı denemesi yapmaz.

1. Lifecycle Log ve SEL içindeki aktif/geçmiş hataları inceleyin.
2. PSU adedi, redundancy, AC girişleri, fanlar ve sıcaklıkları kontrol edin.
3. Testten önce kayıtları dışa aktarın; eski hataları yeni hatadan ayırın. Kayıtları script silmez.
4. Dell'in cihaz/firmware için sunduğu offline embedded diagnostics/Lifecycle Controller testlerini planlayın. Menü adları/sunulan testler firmware'e göre değişebilir.
5. Bellek veya storage için üreticinin kapsamlı tanılamasını bakım penceresinde yürütün.
6. Test sonrası Lifecycle/SEL ve PERC durumunu yeniden kontrol edip kabul kaydına ekleyin.

EDAC görünmüyorsa iDRAC/offline bellek sonuçları özellikle önemlidir. Bu aracın CPU sıcaklık durdurma eşiği, Dell termal limitlerinin yerine geçmez.
