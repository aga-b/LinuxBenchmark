# Resmî teknik kaynaklar

Bu proje üretici/araç belgelerindeki komut semantiğini esas alır. Komut ve JSON alanları kurulu sürüme göre değişebilir; raporda araç sürümlerini saklayın.

- [fio resmî dokümantasyonu](https://fio.readthedocs.io/en/latest/fio_doc.html): `--readonly`, `allow_file_create`, `direct`, I/O engine, JSON çıktısı, latency ve test profilleri.
- [smartmontools smartctl kaynak/man belgesi](https://github.com/smartmontools/smartmontools/blob/main/src/smartctl.8.in): SMART tarama/JSON, denetleyici tipleri ve exit bitmask.
- [smartmontools smartctl bit tanımları](https://github.com/smartmontools/smartmontools/blob/main/src/smartctl.h): hata/sağlık/geçmiş kayıt bayrakları.
- [stress-ng resmî proje ve man sayfası](https://github.com/ColinIanKing/stress-ng): CPU/VM stressor, verify ve metrics seçenekleri.
- [iperf3 resmî kullanım kılavuzu](https://software.es.net/iperf/invoking.html): TCP client, reverse ve JSON sonuçları.
- [Dell PERC CLI referansı: drive show komutları](https://www.dell.com/support/manuals/en-id/poweredge-rc-h810/perc_cli_rg/drive-show-commands?guid=guid-19ed7cdf-32a5-41de-92c0-ea70a9d86cfe&lang=en-us): fiziksel disk/controller salt sorgu komutları. Kullanılan denetleyicinin güncel kılavuzu ayrıca seçilmelidir.
- [Dell PowerEdge R740 destek ve dokümanları](https://www.dell.com/support/product-details/en-us/product/poweredge-r740/resources/manuals): cihaz konfigürasyonu ve üretici tanılama kaynakları.
- [Proxmox VE dokümantasyonu](https://pve.proxmox.com/pve-docs/): node, storage, qm/pct yönetimi ve API referansı.

Kaynak linkleri genel komut davranışını açıklar; belirli bir R740 konfigürasyonunun performans garantisi değildir.
