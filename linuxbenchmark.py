#!/usr/bin/env python3
"""LinuxBenchmark: conservative host acceptance collection, explicit load tests.

Python standard library only. Importing this module never collects or changes a host.
"""
import argparse
import csv
import fcntl
import html
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone

VERSION = "2.0.0"
MIB = 1024 ** 2
GIB = 1024 ** 3
PACKAGES = ["smartmontools", "lm-sensors", "ipmitool", "dmidecode", "pciutils",
            "usbutils", "lshw", "ethtool", "fio", "stress-ng", "sysstat",
            "numactl", "nvme-cli", "iperf3"]
HARDWARE_PATTERN = re.compile(
    r"hardware error|machine check|uncorrect(?:ed|able)|I/O error|medium error|"
    r"out of memory:|oom-kill|critical temperature|thermal.*throttl|"
    r"(?:nvme|ata|scsi|pcie).*(?:fatal|timeout|reset|failed)", re.I)
LIMITATIONS = [
    "Bu rapor otomatik donanım kabul onayı değildir; INFO komutun çalıştığını gösterir.",
    "Linux bellek testi tüm fiziksel RAM hücrelerini veya ECC işlevini doğrulamaz; Dell offline tanılama gerekir.",
    "SMART/EDAC/IPMI/PERC görünürlüğü sürücü ve donanıma bağlıdır; SKIP sağlıklı demek değildir.",
    "fio yalnızca seçilen dosya sistemini ölçer; PERC cache, ZFS ARC, sıkıştırma ve boş alan sonucu etkiler.",
    "iDRAC Lifecycle/SEL, fiziksel diskler, cache koruması ve offline Dell tanılama ayrıca incelenmelidir.",
    "Raporlar seri numarası, IP ve sistem logları içerir; paylaşmadan önce gözden geçirin.",
]


class PreflightError(Exception):
    pass


class Interrupted(Exception):
    def __init__(self, signum):
        self.signum = signum


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_text(path):
    try:
        return Path(path).read_text(errors="replace")
    except OSError:
        return ""


def read_json(path):
    try:
        return json.loads(read_text(path))
    except (ValueError, TypeError):
        return None


def atomic_write(path, text):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def size_bytes(value):
    match = re.fullmatch(r"([1-9][0-9]{0,5})([MG])", value.upper())
    if not match:
        raise argparse.ArgumentTypeError("Boyut 64M..64G aralığında olmalı (ör. 1G).")
    result = int(match[1]) * {"M": MIB, "G": GIB}[match[2]]
    if not 64 * MIB <= result <= 64 * GIB:
        raise argparse.ArgumentTypeError("Boyut 64M..64G aralığında olmalı.")
    return result


def bounded_int(low, high):
    def parse(value):
        try:
            result = int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError("Tam sayı gerekli.") from exc
        if not low <= result <= high:
            raise argparse.ArgumentTypeError(f"{low}..{high} aralığında olmalı.")
        return result
    return parse


class ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(3, f"HATA: {message}\n")


def parser():
    p = ArgumentParser(description="Linux / Dell R740 donanım sağlık ve kabul testleri",
                                epilog="Varsayılan health modu yük testi ve paket kurulumu yapmaz.")
    modes = p.add_mutually_exclusive_group()
    modes.add_argument("--mode", choices=["health", "quick", "full", "stress-only", "disk-only", "network"], default="health")
    modes.add_argument("--quick", dest="mode", action="store_const", const="quick")
    modes.add_argument("--no-stress", dest="mode", action="store_const", const="health")
    modes.add_argument("--stress-only", dest="mode", action="store_const", const="stress-only")
    p.add_argument("--out", type=Path, default=Path("/root/linuxbenchmark"), help="Rapor ana dizini")
    p.add_argument("--install-deps", action="store_true", help="Debian/Ubuntu apt paketlerini açıkça kur")
    p.add_argument("--dry-run", action="store_true", help="Planı göster; komut çalıştırma veya dosya oluşturma")
    p.add_argument("--duration", type=bounded_int(5, 86400), help="Her CPU/RAM testi süresi; saniye")
    p.add_argument("--cpu-workers", type=bounded_int(1, 4096), default=min(2, os.cpu_count() or 1))
    p.add_argument("--cpu-load", type=bounded_int(1, 100), default=75)
    p.add_argument("--memory-mib", type=bounded_int(64, 1048576), help="RAM tahsisi; güvenli üst sınırı aşamaz")
    p.add_argument("--memory-percent", type=bounded_int(1, 75), default=25,
                   help="MemAvailable üzerinden RAM tahsis tavanı; varsayılan %%25, en fazla %%75")
    p.add_argument("--reserve-mib", type=bounded_int(1024, 1048576), default=4096)
    p.add_argument("--max-temp", type=bounded_int(50, 100), default=90, help="CPU sıcaklık durdurma eşiği, °C")
    p.add_argument("--allow-active-workloads", action="store_true", help="Aktif VM/CT varken yük testine izin ver")
    p.add_argument("--fio-dir", type=Path, help="Mevcut yerel ext4/xfs/zfs/btrfs dizini; ham aygıt kabul edilmez")
    p.add_argument("--fio-size", type=size_bytes, default=GIB)
    p.add_argument("--fio-seconds", type=bounded_int(5, 3600), default=30, help="Her rastgele I/O testi süresi")
    p.add_argument("--iperf-server", help="İzinli uzak iperf3 sunucusu; yalnızca network modunda")
    p.add_argument("--iperf-port", type=bounded_int(1, 65535), default=5201)
    p.add_argument("--iperf-seconds", type=bounded_int(5, 3600), default=10)
    p.add_argument("--version", action="version", version=VERSION)
    return p


def validate_args(args):
    disk = args.mode in ("full", "disk-only")
    if disk and args.fio_dir is None:
        raise PreflightError("full/disk-only için --fio-dir zorunlu; ölçülecek dosya sistemini seçin.")
    if not disk and args.fio_dir is not None:
        raise PreflightError("--fio-dir yalnızca full veya disk-only modunda kullanılabilir.")
    if args.mode == "network" and not args.iperf_server:
        raise PreflightError("network için --iperf-server gerekli.")
    if args.mode != "network" and args.iperf_server:
        raise PreflightError("--iperf-server yalnızca network modunda kullanılabilir.")
    if args.iperf_server and (args.iperf_server.startswith("-") or
                              any(c.isspace() for c in args.iperf_server) or
                              len(args.iperf_server) > 253):
        raise PreflightError("Geçersiz iperf sunucu adı/adresi.")
    if args.cpu_workers > (os.cpu_count() or 1):
        raise PreflightError("--cpu-workers kullanılabilir mantıksal CPU sayısını aşamaz.")
    if args.duration is None:
        args.duration = 20 if args.mode == "quick" else 60


def memory_info():
    result = {}
    for line in read_text("/proc/meminfo").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].isdigit():
            result[parts[0].rstrip(":")] = int(parts[1]) * 1024
    return result


def memory_budget(available, reserve, requested=None, percent=25):
    ceiling = min(available * percent // 100, available - reserve) // MIB * MIB
    if ceiling < 64 * MIB:
        raise PreflightError("RAM testi için yeterli MemAvailable / güvenli rezerv yok.")
    if requested is not None and requested > ceiling:
        raise PreflightError(f"İstenen RAM güvenli sınırı aşıyor: en fazla {ceiling // MIB} MiB.")
    return requested if requested is not None else min(ceiling, 8 * GIB)


def snapshot():
    temps = {}
    for hw in Path("/sys/class/hwmon").glob("hwmon*"):
        if read_text(hw / "name").strip() not in ("coretemp", "k10temp", "zenpower", "cpu_thermal"):
            continue
        for path in hw.glob("temp*_input"):
            try:
                temps[str(path)] = int(path.read_text()) / 1000
            except (OSError, ValueError):
                pass
    edac = {}
    for path in Path("/sys/devices/system/edac/mc").glob("mc*/[cu]e_count"):
        try:
            edac[str(path)] = int(path.read_text())
        except (OSError, ValueError):
            pass
    network = {}
    for nic in Path("/sys/class/net").glob("*"):
        if nic.name == "lo":
            continue
        for key in ("rx_errors", "tx_errors", "rx_dropped", "tx_dropped"):
            text = read_text(nic / "statistics" / key).strip()
            if text.isdigit():
                network[f"{nic.name}/{key}"] = int(text)
    throttling = {}
    for path in Path("/sys/devices/system/cpu").glob("cpu[0-9]*/thermal_throttle/*_throttle_count"):
        value = read_text(path).strip()
        if value.isdigit():
            throttling[str(path)] = int(value)
    return {"at": utcnow(), "memory": memory_info(), "cpu_temperatures": temps,
            "edac": edac, "network": network, "throttling": throttling}


def smart_findings(data, rc):
    """Decode smartctl's bitmask; never equate command success with drive health."""
    findings = []
    if rc & 7:
        findings.append(("WARN", f"SMART erişim/komut hatası, bitmask={rc}"))
    if rc & 24 or data.get("smart_status", {}).get("passed") is False:
        findings.append(("FAIL", f"SMART sağlık/eşik hatası, bitmask={rc}"))
    if rc & 224:
        findings.append(("WARN", f"SMART geçmiş eşik/hata/self-test kaydı, bitmask={rc}"))
    nvme = data.get("nvme_smart_health_information_log", {})
    if nvme.get("critical_warning", 0):
        findings.append(("FAIL", f"NVMe critical_warning={nvme['critical_warning']}"))
    if nvme.get("media_errors", 0):
        findings.append(("WARN", f"NVMe media_errors={nvme['media_errors']}"))
    for attr in data.get("ata_smart_attributes", {}).get("table", []):
        raw = attr.get("raw", {}).get("value", 0)
        if attr.get("id") in (5, 197, 198) and isinstance(raw, (int, float)) and raw > 0:
            findings.append(("WARN", f"SMART {attr.get('name', attr['id'])}={raw}"))
    if not findings:
        if data.get("smart_status", {}).get("passed") is True:
            findings.append(("PASS", "SMART genel sağlık sonucu başarılı; fiziksel kapsamı doğrulayın."))
        else:
            findings.append(("SKIP", "SMART sağlık sonucu mevcut değil; sağlıklı varsayılmadı."))
    return findings


def perc_findings(data):
    """Conservative parsing of known PERC JSON sections; raw JSON remains evidence."""
    findings = []
    controllers = data.get("Controllers", [])
    if not isinstance(controllers, list) or not controllers:
        return [("WARN", "PERC JSON içinde controller bulunamadı; elle inceleyin.")]
    for ctrl in controllers:
        status = ctrl.get("Command Status", {}).get("Status")
        if status != "Success":
            findings.append(("WARN", f"PERC komut durumu: {status!r}"))
        found = 0
        def walk(obj, trail=""):
            nonlocal found
            if isinstance(obj, dict):
                for key, value in obj.items():
                    path = f"{trail}/{key}"
                    if key == "Controller Status":
                        found += 1
                        health = "PASS" if value == "Optimal" else "FAIL" if str(value).lower() in ("failed", "offline") else "WARN"
                        findings.append((health, f"{path}: {value}"))
                    elif key == "State" and isinstance(value, str):
                        found += 1
                        if value in ("Optl", "Onln", "GHS", "DHS", "JBOD", "Optimal", "Online"):
                            findings.append(("PASS", f"{path}: {value}"))
                        else:
                            health = "FAIL" if value in ("Offln", "Offl", "Failed", "Msng", "UBad") else "WARN"
                            findings.append((health, f"{path}: {value}"))
                    elif key in ("Media Error Count", "Other Error Count", "Predictive Failure Count"):
                        if str(value).isdigit() and int(value) > 0:
                            findings.append(("WARN", f"{path}: {value}"))
                    elif key == "BBU Status":
                        found += 1
                        if str(value) not in ("0", "Optimal"):
                            findings.append(("WARN", f"{path}: {value}"))
                    walk(value, path)
            elif isinstance(obj, list):
                for index, value in enumerate(obj):
                    walk(value, f"{trail}/{index}")
        walk(ctrl.get("Response Data", {}))
        if not found:
            findings.append(("SKIP", "PERC durum alanları tanınmadı; raw JSON elle incelenmeli."))
    findings.append(("INFO", "PERC cache/BBU/CacheVault politikası ve rebuild ayrıntıları ham kayıttan ayrıca doğrulanmalı."))
    return findings


def fio_metrics(data):
    rows = []
    jobs = data.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        raise ValueError("fio jobs eksik")
    for job in jobs:
        if job.get("error", 0):
            raise ValueError(f"fio job error={job['error']}")
        for direction in ("read", "write"):
            io = job.get(direction, {})
            if io.get("io_bytes", io.get("io_kbytes", 0) * 1024) <= 0:
                continue
            clat = io.get("clat_ns", {})
            rows.append({"job": job.get("jobname"), "direction": direction,
                         "mib_s": io.get("bw_bytes", io.get("bw", 0) * 1024) / MIB,
                         "iops": io.get("iops", 0),
                         "clat_mean_ms": clat.get("mean", 0) / 1e6,
                         "clat_p99_ms": clat.get("percentile", {}).get("99.000000", 0) / 1e6})
    if not rows:
        raise ValueError("fio I/O sonucu boş")
    return rows



def stress_metrics(text, stressor):
    for line in text.splitlines():
        match = re.search(r"\]\s+" + re.escape(stressor) +
                          r"\s+(\d+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)", line)
        if match:
            fields = [float(value) for value in match.groups()]
            if all(math.isfinite(value) for value in fields) and fields[0] > 0:
                return {"job": "stress-" + stressor, "bogo_ops": int(fields[0]),
                        "real_seconds": fields[1], "user_seconds": fields[2],
                        "system_seconds": fields[3], "bogo_ops_per_real_second": fields[4],
                        "bogo_ops_per_cpu_second": fields[5]}
    return None

def stop_process(proc):
    if proc is None:
        return
    # The process group may contain workers even if the immediate parent exited.
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.wait()


class Runner:
    def __init__(self, args):
        self.args = args
        self.out = None
        self.records = []
        self.commands = []
        self.metrics = []
        self.samples = []
        self.meta = {"version": VERSION, "host": socket.gethostname(), "started": utcnow(),
                     "mode": args.mode, "options": {k: str(v) if isinstance(v, Path) else v
                                                  for k, v in vars(args).items()}}
        self.tempdir = None
        self.lock = None
        self.aborted = False
        self.io_target = None
        self.io_margin = 0
        self.ipmi_sel_before = None

    def add(self, name, status, message, evidence=None):
        item = {"name": name, "status": status, "message": message, "evidence": evidence}
        self.records.append(item)
        line = f"[{status}] {name}: {message}"
        print(line, flush=True)
        if self.out:
            with (self.out / "logs/console.log").open("a") as stream:
                stream.write(line + "\n")

    def setup(self):
        if os.geteuid() != 0:
            raise PreflightError("Gerçek toplama/test için root gerekli; --dry-run root gerektirmez.")
        if sys.platform != "linux":
            raise PreflightError("Yalnızca Linux desteklenir.")
        lock_path = Path("/run/lock/linuxbenchmark.lock")
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        self.lock = os.fdopen(fd, "w")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise PreflightError("Başka bir LinuxBenchmark çalışması devam ediyor.") from exc
        base = self.args.out.expanduser().resolve()
        base.mkdir(parents=True, exist_ok=True)
        host = re.sub(r"[^A-Za-z0-9_.-]", "_", self.meta["host"])
        self.out = Path(tempfile.mkdtemp(prefix=f"{host}-{datetime.now():%Y%m%d-%H%M%S}-", dir=base))
        for name in ("inventory", "logs", "benchmarks"):
            (self.out / name).mkdir()
        self.meta["output"] = str(self.out)
        self.add("run", "INFO", f"LinuxBenchmark {VERSION}; rapor: {self.out}")

    def run(self, name, argv, category="logs", timeout=45, load=False, accepted=(0,), input_text=None):
        relative = f"{category}/{name}.log"
        if not shutil.which(argv[0]):
            self.add(name, "SKIP", f"Araç bulunamadı: {argv[0]}")
            return 127, "", None
        target = self.out / relative
        proc = None
        rc = 125
        reason = ""
        start = time.monotonic()
        try:
            with target.open("w") as stream:
                proc = subprocess.Popen(argv, stdout=stream, stderr=subprocess.STDOUT,
                                        stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL, start_new_session=True,
                                        env={**os.environ, "LC_ALL": "C", "LANG": "C", "TZ": "UTC"})
                if input_text is not None:
                    proc.stdin.write(input_text.encode())
                    proc.stdin.close()
                while proc.poll() is None:
                    elapsed = time.monotonic() - start
                    if elapsed > timeout:
                        reason = f"Zaman aşımı ({timeout}s)"
                        break
                    if load:
                        sample = snapshot()
                        self.samples.append({"test": name, **sample})
                        if self.io_target is not None and shutil.disk_usage(self.io_target).free < self.io_margin:
                            reason = "fio boş alan rezervi test sırasında azaldı"
                            break
                        temperatures = sample["cpu_temperatures"].values()
                        if temperatures and max(temperatures) >= self.args.max_temp:
                            reason = f"CPU sıcaklık eşiği aşıldı ({self.args.max_temp}°C)"
                            break
                        if sample["memory"].get("MemAvailable", 0) < self.args.reserve_mib * MIB:
                            reason = "MemAvailable güvenli rezervin altına düştü"
                            break
                        baseline = self.meta.get("before", {}).get("edac", {})
                        if any(k.endswith("/ue_count") and v > baseline.get(k, v)
                               for k, v in sample["edac"].items()):
                            reason = "Yeni düzeltilemeyen ECC hatası"
                            break
                    try:
                        proc.wait(timeout=2 if load else 0.25)
                    except subprocess.TimeoutExpired:
                        pass
                if reason:
                    stop_process(proc)
                    rc = 124
                    if load:
                        self.aborted = True
                else:
                    rc = proc.returncode
        except Interrupted:
            reason = "Kullanıcı/sinyal ile kesildi"
            rc = 130
            raise
        finally:
            stop_process(proc)
            self.commands.append({"name": name, "argv": argv, "exit_code": rc,
                                  "duration_seconds": round(time.monotonic() - start, 3),
                                  "evidence": relative, "reason": reason})
        if reason or rc not in accepted:
            self.add(name, "FAIL" if load else "WARN", reason or f"Komut dönüş kodu: {rc}", relative)
        else:
            self.add(name, "INFO", "Komut tamamlandı; donanım sağlık onayı değildir.", relative)
        return rc, read_text(target), relative

    def install(self):
        if not self.args.install_deps:
            self.add("dependencies", "INFO", "Otomatik kurulum kapalı; eksik araçlar SKIP olarak raporlanır.")
            return
        if not shutil.which("apt-get"):
            raise PreflightError("--install-deps Debian/Ubuntu/Proxmox apt-get gerektirir.")
        rc, _, _ = self.run("apt-update", ["apt-get", "update"], timeout=300)
        if rc != 0:
            raise PreflightError("apt update başarısız; depo/lisans ayarlarını kontrol edin. Kaynaklar değiştirilmedi.")
        # Prevent a package post-install from starting an unsolicited iperf daemon.
        rc, _, _ = self.run("iperf-debconf", ["debconf-set-selections"], timeout=5,
                               input_text="iperf3 iperf3/start_daemon boolean false\n")
        if rc:
            raise PreflightError("iperf3 daemon tercihi ayarlanamadı; paket kurulumu durduruldu.")
        env = ["env", "DEBIAN_FRONTEND=noninteractive"]
        rc, _, _ = self.run("apt-install", env + ["apt-get", "install", "-y", "--no-install-recommends", "--no-remove", "--no-upgrade"] + PACKAGES,
                            timeout=900)
        if rc:
            raise PreflightError("Paket kurulumu başarısız/kısmi; apt logunu inceleyin. Firmware/PERC aracı kurulmadı.")

    def inventory(self):
        commands = {
            "os": ["cat", "/etc/os-release"], "kernel": ["uname", "-a"],
            "cpu": ["lscpu"], "numa": ["numactl", "--hardware"],
            "memory": ["lsmem"], "dmi": ["dmidecode"], "hardware": ["lshw", "-short"],
            "pci": ["lspci", "-nnk"], "usb": ["lsusb"],
            "disks": ["lsblk", "-J", "-e7", "-o", "NAME,PATH,TYPE,SIZE,ROTA,RO,TRAN,FSTYPE,MOUNTPOINTS,MODEL,SERIAL"],
            "mounts": ["findmnt", "-J"], "space": ["df", "-hT"],
            "ip": ["ip", "-j", "-s", "address"], "routes": ["ip", "-j", "route"],
            "proxmox": ["pveversion", "-v"], "pve-storage": ["pvesm", "status"],
            "nvme": ["nvme", "list", "-o", "json"],
            "stress-version": ["stress-ng", "--version"], "fio-version": ["fio", "--version"],
            "iperf-version": ["iperf3", "--version"],
            "idrac-info": ["ipmitool", "mc", "info"], "fru": ["ipmitool", "fru", "print"],
            "chassis": ["ipmitool", "chassis", "status"],
        }
        for name, cmd in commands.items():
            self.run(name, cmd, category="inventory")
        for nic in sorted(Path("/sys/class/net").glob("*")):
            if (nic / "device").exists():
                self.run(f"nic-{nic.name}", ["ethtool", nic.name])
                self.run(f"nic-driver-{nic.name}", ["ethtool", "-i", nic.name])
                self.run(f"nic-stats-{nic.name}", ["ethtool", "-S", nic.name])
        self.add("network-throughput", "SKIP" if self.args.mode != "network" else "INFO",
                 "Throughput yalnızca network modunda, izinli ikinci uç ile ölçülür.")

    def health(self):
        self.run("sensors", ["sensors", "-j"])
        self.run("ipmi-sensors", ["ipmitool", "sensor", "list"], timeout=60)
        rc, text, ev = self.run("ipmi-sdr", ["ipmitool", "sdr", "elist"], timeout=60)
        if rc == 0:
            bad = [line for line in text.splitlines() if re.search(r"\|\s*(?:cr|nr|nc)\s*\|", line, re.I)]
            self.add("ipmi-status", "WARN" if bad else "INFO",
                     f"{len(bad)} kritik/uyarı sensör satırı; bağlantısız/na sensörleri ayrıca inceleyin.", ev)
        rc, text, _ = self.run("ipmi-sel", ["ipmitool", "sel", "elist"], timeout=60)
        if rc == 0:
            self.ipmi_sel_before = set(text.splitlines())
        self.add("ipmi-sel-review", "INFO", "SEL geçmiş kayıtları ham logdan elle incelenmeli; kayıtlar silinmedi.")
        rc, text, ev = self.run("failed-services", ["systemctl", "--failed", "--no-legend", "--plain", "--no-pager"])
        if rc == 0:
            self.add("systemd-health", "WARN" if text.strip() else "PASS",
                     "Başarısız servis var." if text.strip() else "Başarısız systemd servisi yok.", ev)
        rc, text, ev = self.run("kernel-before", ["journalctl", "-k", "-b", "--no-pager", "-o", "short-iso"])
        if rc == 0:
            hits = [line for line in text.splitlines() if HARDWARE_PATTERN.search(line)]
            self.add("kernel-history", "WARN" if hits else "INFO",
                     f"Mevcut boot içinde {len(hits)} şüpheli satır; otomatik regex tanı koymaz.", ev)
        before = snapshot()
        self.meta["before"] = before
        if before["cpu_temperatures"]:
            peak = max(before["cpu_temperatures"].values())
            self.add("cpu-temperature-baseline", "WARN" if peak >= self.args.max_temp else "INFO",
                     f"Desteklenen hwmon sensörlerinde en yüksek CPU sıcaklığı: {peak}°C")
        if not before["edac"]:
            self.add("ecc", "SKIP", "EDAC sayaçları görünmüyor; ECC durumu doğrulanamadı.")
        for name, count in before["edac"].items():
            self.add("ecc-baseline", "FAIL" if count and name.endswith("/ue_count") else "WARN" if count else "PASS",
                     f"{name}={count}")
        corrupted = before["memory"].get("HardwareCorrupted", 0)
        if corrupted:
            self.add("memory-corrupted", "FAIL", f"HardwareCorrupted={corrupted} byte")
        self.storage_health()

    def storage_health(self, prefix=""):
        def run(name, argv, **kwargs):
            return self.run(prefix + name, argv, **kwargs)

        def add(name, status, message, evidence=None):
            self.add(prefix + name, status, message, evidence)

        rc, text, ev = run("smart-scan", ["smartctl", "--scan-open", "-j"])
        devices = None
        if rc == 0:
            try:
                devices = json.loads(text).get("devices", [])
            except (ValueError, AttributeError):
                add("smart-scan-json", "WARN", "SMART JSON çözümlenemedi.", ev)
        if not devices:
            add("smart-coverage", "SKIP", "Görünür SMART aygıtı yok; PERC fiziksel disk kapsamını kontrol edin.")
        for index, device in enumerate(devices or []):
            name, kind = device.get("name"), device.get("type")
            if not isinstance(name, str) or not name.startswith("/dev/") or not isinstance(kind, str):
                add("smart-device", "WARN", "Beklenmeyen SMART tarama alanı atlandı.", ev)
                continue
            rc, text, evidence = run(f"smart-{index}", ["smartctl", "-x", "-j", "-d", kind, name],
                                         timeout=90, accepted=tuple(range(256)))
            if self.commands and self.commands[-1].get("reason"):
                add(f"smart-health-{index}", "SKIP", "SMART komutu tamamlanmadı; bitmask sağlık olarak yorumlanmadı.", evidence)
                continue
            try:
                data = json.loads(text)
                if not isinstance(data, dict):
                    raise ValueError("object gerekli")
                for status, message in smart_findings(data, rc):
                    add(f"smart-health-{index}", status, f"{name} ({kind}): {message}", evidence)
            except (ValueError, TypeError, AttributeError):
                add(f"smart-health-{index}", "WARN", "SMART JSON/durum çözümlenemedi.", evidence)
        run("mdstat", ["cat", "/proc/mdstat"])
        mdstat = read_text("/proc/mdstat")
        if re.search(r"\[[U_]+\]", mdstat):
            add("mdraid", "WARN" if re.search(r"\[[U_]*_[U_]*\]", mdstat) else "PASS",
                     "mdraid üye durumları kontrol edildi.", f"logs/{prefix}mdstat.log")
        if re.search(r"(?:recovery|resync|reshape)\s*=", mdstat):
            add("mdraid-recovery", "WARN", "mdraid recovery/resync/reshape devam ediyor.", f"logs/{prefix}mdstat.log")
        rc, text, ev = run("zpool", ["zpool", "status", "-v"])
        if rc == 0 and "no pools available" not in text:
            states = re.findall(r"^\s*state:\s*(\S+)", text, re.M)
            counters = re.findall(r"^\s*\S+\s+(?:ONLINE|DEGRADED|FAULTED|UNAVAIL)\s+(\d+)\s+(\d+)\s+(\d+)\s*$", text, re.M)
            io_errors = any(int(v) > 0 for row in counters for v in row)
            add("zpool-health", "WARN" if not states or any(s != "ONLINE" for s in states) or io_errors or
                     "in progress" in text or re.search(r"errors: (?!No known data errors).+", text) else "PASS",
                     f"Pool durumları: {states}; scrub/READ/WRITE/CKSUM ayrıntıları ham kayıtta.", ev)
        cli = next((shutil.which(n) for n in ("perccli64", "perccli", "storcli64", "storcli") if shutil.which(n)), None)
        if cli is None:
            cli = next((str(p) for p in (Path("/opt/MegaRAID/perccli/perccli64"),
                                         Path("/opt/MegaRAID/storcli/storcli64")) if p.is_file() and os.access(p, os.X_OK)), None)
        if cli:
            for label, argv in (("perc-controller", ["/call", "show", "all", "J"]),
                                ("perc-drives", ["/call/eall/sall", "show", "all", "J"])):
                rc, text, ev = run(label, [cli] + argv, timeout=90)
                if rc == 0:
                    try:
                        for status, message in perc_findings(json.loads(text)):
                            add(label + "-health", status, message, ev)
                    except (ValueError, TypeError, AttributeError):
                        add(label, "WARN", "PERC JSON tanınmadı; ham kayıt elle incelenmeli.", ev)
        else:
            add("perc", "SKIP", "PERC/storcli yok; fiziksel disk, VD, BBU/cache sağlığı doğrulanamadı.")

    def workload_guard(self):
        if not shutil.which("pveversion"):
            self.add("active-workloads", "WARN", "Proxmox dışı host: Docker/libvirt/diğer uygulamalar otomatik tespit edilmez.")
            return
        active = []
        unknown = False
        for name, cmd in (("active-qemu", ["qm", "list"]), ("active-lxc", ["pct", "list"])):
            rc, text, ev = self.run(name, cmd)
            lines = [line.split() for line in text.splitlines() if line.strip()]
            # Known qm/pct list schemas include VMID + (NAME) + STATUS; reject unrecognized output.
            if rc or not lines or "STATUS" not in [x.upper() for x in lines[0]]:
                unknown = True
                continue
            index = [x.upper() for x in lines[0]].index("STATUS")
            for row in lines[1:]:
                if len(row) <= index or not row[0].isdigit():
                    unknown = True
                elif row[index].lower() != "stopped":
                    active.append(f"{name}:{row[0]}:{row[index]}")
        if (active or unknown) and not self.args.allow_active_workloads:
            raise PreflightError(f"Aktif/belirsiz VM/CT durumu: {active}, unknown={unknown}. Bakım penceresi seçin; bilinçli geçiş için --allow-active-workloads.")
        if active or unknown:
            self.add("active-workloads", "WARN", f"Açık kullanıcı tercihiyle yük testi: {active}; unknown={unknown}")

    def load_guard(self):
        if self.aborted:
            raise PreflightError("Önceki yük testi güvenlik eşiği nedeniyle durduruldu; diğer yük testleri çalıştırılmayacak.")
        self.workload_guard()
        current = snapshot()
        temps = current["cpu_temperatures"].values()
        if temps and max(temps) >= self.args.max_temp:
            raise PreflightError("Başlangıç CPU sıcaklığı eşiği aşıyor.")
        if not temps:
            self.add("temperature-coverage", "WARN", "Desteklenen CPU hwmon sensörü yok; otomatik termal koruma ölçülemiyor.")
        if current["memory"].get("MemAvailable", 0) < self.args.reserve_mib * MIB:
            raise PreflightError("Kullanılabilir bellek rezervin altında; yük testi başlamadı.")
        if any(v for k, v in current["edac"].items() if k.endswith("/ue_count")):
            raise PreflightError("Mevcut düzeltilemeyen ECC hatası nedeniyle yük testi engellendi.")
        if any(r["status"] == "FAIL" for r in self.records):
            raise PreflightError("Sağlık kontrolünde FAIL var; yük testi engellendi.")

    def stress(self):
        if not shutil.which("stress-ng"):
            raise PreflightError("stress-ng bulunamadı; --install-deps ile araçları kurun.")
        memory_budget(memory_info().get("MemAvailable", 0), self.args.reserve_mib * MIB,
                      None if self.args.memory_mib is None else self.args.memory_mib * MIB, self.args.memory_percent)
        self.load_guard()
        rc, text, ev = self.run("cpu-stress", ["stress-ng", "--cpu", str(self.args.cpu_workers),
            "--cpu-load", str(self.args.cpu_load), "--cpu-method", "matrixprod", "--verify",
            "--timeout", f"{self.args.duration}s", "--metrics-brief"], category="benchmarks",
            timeout=self.args.duration + 30, load=True)
        if rc == 0:
            row = stress_metrics(text, "cpu")
            if row:
                self.metrics.append(row)
            else:
                self.add("cpu-metrics", "WARN", "stress-ng performans satırı tanınmadı; ham kayıt incelenmeli.", ev)
            self.add("cpu-test", "PASS", "Seçilen worker/yük/süre için stress-ng hata bildirmedi.", ev)
        if rc:
            raise PreflightError("CPU testi tamamlanamadı; sonraki yük testleri durduruldu.")
        self.load_guard()
        amount = memory_budget(memory_info().get("MemAvailable", 0), self.args.reserve_mib * MIB,
                               None if self.args.memory_mib is None else self.args.memory_mib * MIB, self.args.memory_percent)
        self.meta["memory_test_bytes"] = amount
        rc, text, ev = self.run("memory-stress", ["stress-ng", "--vm", "1", "--vm-bytes", str(amount),
            "--vm-method", "all", "--verify", "--timeout", f"{self.args.duration}s", "--metrics-brief"],
            category="benchmarks", timeout=self.args.duration + 30, load=True)
        if rc == 0:
            row = stress_metrics(text, "vm")
            if row:
                self.metrics.append(row)
            else:
                self.add("memory-metrics", "WARN", "stress-ng performans satırı tanınmadı; ham kayıt incelenmeli.", ev)
            self.add("memory-test", "PASS", f"{amount // MIB} MiB seçilen sürede test edildi; tüm DIMM kapsamı değildir.", ev)
        else:
            raise PreflightError("RAM testi tamamlanamadı; sonraki yük testleri durduruldu.")

    def disk_preflight(self):
        target = validate_fio_directory(self.args.fio_dir)
        rc, text, ev = self.run("fio-filesystem", ["findmnt", "--json", "--target", str(target),
                                                   "--output", "TARGET,SOURCE,FSTYPE,OPTIONS"])
        try:
            fs = json.loads(text)["filesystems"][0]
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            raise PreflightError("fio hedefinin mount bilgisi doğrulanamadı.") from exc
        if rc or fs.get("fstype") not in ("ext4", "xfs", "zfs", "btrfs"):
            raise PreflightError("fio yalnızca yerel ext4/xfs/zfs/btrfs üzerinde çalışır; NFS/CIFS/tmpfs/overlay kabul edilmez.")
        if "ro" in fs.get("options", "").split(","):
            raise PreflightError("fio hedefi salt okunur.")
        self.meta["fio_filesystem"] = fs
        free = shutil.disk_usage(target).free
        margin = max(2 * GIB, shutil.disk_usage(target).total // 10)
        if free - self.args.fio_size < margin:
            raise PreflightError("fio için dosya boyutu + max(2 GiB, kapasitenin %10'u) boş alan gerekli.")
        return target, fs, margin

    def disk(self):
        self.load_guard()
        target, fs, margin = self.disk_preflight()
        self.io_target, self.io_margin = target, margin
        self.tempdir = Path(tempfile.mkdtemp(prefix=".linuxbenchmark-", dir=target))
        filename = self.tempdir / "test.bin"
        # O_EXCL/O_NOFOLLOW: never open or truncate an existing file/device/symlink.
        fd = os.open(filename, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            os.ftruncate(fd, self.args.fio_size)
        finally:
            os.close(fd)
        self.add("fio-target", "INFO", f"Yalnızca özel geçici normal dosya: {filename}; source={fs.get('source')}", "logs/fio-filesystem.log")
        rc, text, _ = self.run("fio-version", ["fio", "--version"])
        if rc or not re.match(r"fio-\d", text):
            raise PreflightError("fio binary Flexible I/O Tester değil veya kurulu değil.")
        common = ["fio", f"--filename={filename}", f"--size={self.args.fio_size}", "--ioengine=libaio",
                  "--direct=1", "--numjobs=1", "--group_reporting=1", "--output-format=json",
                  "--allow_file_create=0", "--refill_buffers=1", "--scramble_buffers=1"]
        jobs = [("seq-write", "write", "1M", 16), ("seq-read", "read", "1M", 16),
                ("randread-4k", "randread", "4k", 32), ("randwrite-4k", "randwrite", "4k", 32)]
        for name, rw, bs, depth in jobs:
            self.load_guard()
            if not stat.S_ISREG(filename.lstat().st_mode) or filename.stat().st_nlink != 1:
                raise PreflightError("fio geçici dosya tipi/link sayısı değişti; durduruldu.")
            if shutil.disk_usage(target).free < margin:
                raise PreflightError("fio sırasında boş alan rezervi azaldı.")
            argv = common + [f"--name={name}", f"--rw={rw}", f"--bs={bs}", f"--iodepth={depth}"]
            if rw in ("read", "randread"):
                argv += ["--readonly"]
            else:
                argv += ["--end_fsync=1"]
            if name.startswith("rand"):
                argv += ["--time_based=1", f"--runtime={self.args.fio_seconds}"]
            # Full-file initialization precedes reads; never read a sparse/unwritten test file.
            rc, text, ev = self.run("fio-" + name, argv, category="benchmarks",
                                    timeout=self.args.fio_seconds + 30 if name.startswith("rand") else 300, load=True)
            if rc:
                raise PreflightError("fio başarısız; devam edilmedi (buffered fallback yok).")
            try:
                rows = fio_metrics(json.loads(text))
            except (ValueError, TypeError, AttributeError) as exc:
                self.add("fio-" + name, "FAIL", f"Geçersiz/başarısız fio sonucu: {exc}", ev)
                raise PreflightError("fio sonuç doğrulaması başarısız.") from exc
            self.metrics.extend(rows)
            self.add("fio-" + name + "-result", "PASS", json.dumps(rows, ensure_ascii=False), ev)

    def network(self):
        self.load_guard()
        for reverse in (False, True):
            self.load_guard()
            name = "iperf-reverse" if reverse else "iperf-forward"
            argv = ["iperf3", "--client", self.args.iperf_server, "--port", str(self.args.iperf_port),
                    "--time", str(self.args.iperf_seconds), "--parallel", "1", "--json"]
            if reverse:
                argv += ["--reverse"]
            rc, text, ev = self.run(name, argv, category="benchmarks",
                                    timeout=self.args.iperf_seconds + 30, load=True)
            if rc:
                raise PreflightError("iperf3 başarısız; sonraki ağ testi durduruldu.")
            try:
                data = json.loads(text)
                if data.get("error"):
                    raise ValueError(data["error"])
                received = data["end"]["sum_received"]["bits_per_second"] / 1e9
                sent = data["end"]["sum_sent"]["bits_per_second"] / 1e9
                if not all(math.isfinite(n) and n > 0 for n in (received, sent)):
                    raise ValueError("Geçersiz throughput")
                self.metrics.append({"job": name, "received_gbit_s": received, "sent_gbit_s": sent,
                                     "retransmits": data["end"]["sum_sent"].get("retransmits")})
                self.add(name + "-result", "PASS", f"RX={received:.3f}, TX={sent:.3f} Gbit/s; tek TCP akışı.", ev)
            except (ValueError, KeyError, TypeError) as exc:
                self.add(name + "-result", "FAIL", f"iperf JSON geçersiz: {exc}", ev)
                raise PreflightError("iperf sonuç doğrulaması başarısız.") from exc

    def postcheck(self):
        after = snapshot()
        self.meta["after"] = after
        before = self.meta.get("before", {})
        for group in ("edac", "network", "throttling"):
            initial = before.get(group, {})
            if not initial:
                continue
            for key, value in after[group].items():
                if key not in initial:
                    continue
                delta = value - initial[key]
                if delta:
                    status = "FAIL" if group == "edac" and key.endswith("/ue_count") and delta > 0 else "WARN"
                    self.add(group + "-delta", status, f"{key}: {initial[key]} -> {value} (delta={delta}); negatif delta reset olabilir.")
            missing = set(initial) - set(after[group])
            if missing:
                self.add(group + "-coverage", "WARN", f"Son ölçümde kaybolan sayaçlar: {sorted(missing)}")
        since = self.meta["started"]
        rc, text, ev = self.run("kernel-since-start", ["journalctl", "-k", "-b", "--since", since,
                                                      "--no-pager", "-o", "short-iso"])
        if rc == 0:
            hits = [line for line in text.splitlines() if HARDWARE_PATTERN.search(line)]
            self.add("kernel-new-events", "WARN" if hits else "INFO",
                     f"Çalışma zaman aralığında {len(hits)} şüpheli kernel satırı; elle doğrulayın.", ev)
        rc, text, ev = self.run("post-ipmi-sel", ["ipmitool", "sel", "elist"], timeout=60)
        if rc == 0 and self.ipmi_sel_before is not None:
            new = set(text.splitlines()) - self.ipmi_sel_before
            self.add("ipmi-sel-delta", "WARN" if new else "INFO",
                     f"{len(new)} yeni/değişen SEL satırı; severity elle doğrulanmalı.", ev)
        if self.args.mode in ("full", "disk-only"):
            self.storage_health(prefix="post-")

    def cleanup(self):
        # No recursive deletion: delete only the one owned regular file and its empty directory.
        if self.tempdir is not None:
            target = self.tempdir / "test.bin"
            try:
                if target.is_file() and not target.is_symlink():
                    target.unlink()
                self.tempdir.rmdir()
                self.add("fio-cleanup", "INFO", "Geçici fio dosyası ve özel dizini kaldırıldı.")
            except OSError as exc:
                self.add("fio-cleanup", "WARN", f"Elle temizlik gerekli: {self.tempdir}: {exc}")

    def report(self, exit_override=None):
        self.meta["finished"] = utcnow()
        data = {"schema_version": 1, "metadata": self.meta, "summary": summary(self.records),
                "checks": self.records, "commands": self.commands, "metrics": self.metrics,
                "limitations": LIMITATIONS}
        data["metadata"]["process_exit_code"] = data["summary"]["exit_code"] if exit_override is None else exit_override
        atomic_write(self.out / "report.json", json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        text = render_text(data)
        atomic_write(self.out / "REPORT.txt", text)
        atomic_write(self.out / "REPORT.html", render_html(data))
        with (self.out / "benchmarks/metrics.csv").open("w", newline="") as stream:
            fields = sorted({k for row in self.metrics for k in row}) or ["job"]
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(self.metrics)
        atomic_write(self.out / "logs/telemetry.json", json.dumps(self.samples, indent=2))
        return data["summary"]["exit_code"]


def validate_fio_directory(path):
    if not path or not path.is_dir():
        raise PreflightError("--fio-dir mevcut bir dizin olmalı; aygıt/dosya kabul edilmez.")
    resolved = path.expanduser().resolve()
    if any(resolved == Path(p) or Path(p) in resolved.parents for p in ("/dev", "/proc", "/sys", "/run")):
        raise PreflightError("Sanal/aygıt dosya sistemleri fio hedefi olamaz.")
    # fio filename grammar treats ':' as a list separator (and backslash as an escape).
    if any(c in str(resolved) for c in (":", "\\", "\n", "\r")):
        raise PreflightError("fio dizininde ':', ters bölü veya satır sonu kullanılamaz.")
    # Other local users must not be able to rename/replace the benchmark directory.
    for parent in (resolved, *resolved.parents):
        info = parent.stat()
        if info.st_uid != 0 or (info.st_mode & 0o022):
            raise PreflightError("fio dizini ve üst dizinler root sahipli, grup/diğer kullanıcı yazmasına kapalı olmalı.")
    return resolved


def summary(records):
    counts = dict(Counter(r["status"] for r in records))
    if counts.get("FAIL"):
        state, code = "FAIL", 2
    elif counts.get("WARN"):
        state, code = "REVIEW_REQUIRED", 1
    elif counts.get("SKIP"):
        state, code = "INCOMPLETE", 1
    else:
        state, code = "NO_ISSUES_DETECTED", 0
    return {"state": state, "exit_code": code, "counts": counts,
            "acceptance": "MANUAL_REVIEW_REQUIRED"}


def render_text(data):
    meta, summ = data["metadata"], data["summary"]
    lines = [f"LinuxBenchmark {meta['version']}", f"Host: {meta['host']}",
             f"Başlangıç (UTC): {meta['started']}", f"Bitiş (UTC): {meta['finished']}",
             f"Mod: {meta['mode']}", f"Sonuç: {summ['state']} (bulgu kodu={summ['exit_code']}, süreç kodu={meta.get('process_exit_code')})",
             f"Sayaçlar: {summ['counts']}", "KABUL KARARI: MANUEL İNCELEME GEREKLİ", "", "BULGULAR"]
    for record in sorted(data["checks"], key=lambda r: {"FAIL": 0, "WARN": 1, "SKIP": 2, "PASS": 3, "INFO": 4}[r["status"]]):
        lines.append(f"[{record['status']}] {record['name']}: {record['message']}")
        if record["evidence"]:
            lines.append(f"  Kanıt: {record['evidence']}")
    lines += ["", "METRİKLER", json.dumps(data["metrics"], ensure_ascii=False, indent=2), "", "SINIRLAR"]
    lines += ["- " + s for s in data["limitations"]]
    return "\n".join(lines) + "\n"


def render_html(data):
    esc = lambda value: html.escape(str(value), quote=True)
    rows = "".join(f"<tr><td>{esc(r['status'])}</td><td>{esc(r['name'])}</td><td>{esc(r['message'])}</td>"
                   f"<td>{'<a href=' + chr(34) + esc(r['evidence']) + chr(34) + '>log</a>' if r['evidence'] else ''}</td></tr>"
                   for r in data["checks"])
    return ("<!doctype html><html lang='tr'><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
            "<title>LinuxBenchmark raporu</title><style>body{font:16px system-ui;margin:2rem;color:#17243a}"
            "table{border-collapse:collapse;width:100%}td,th{padding:.6rem;border:1px solid #ccd;text-align:left}"
            "pre{white-space:pre-wrap;overflow-wrap:anywhere}a{color:#1459a0}</style><body>"
            f"<h1>LinuxBenchmark — {esc(data['summary']['state'])}</h1>"
            "<p>Kabul kararı: manuel inceleme gerekli. Bu rapor otomatik kabul sertifikası değildir.</p>"
            f"<p>{esc(data['metadata']['host'])} · {esc(data['metadata']['mode'])}</p>"
            "<table><tr><th>Durum</th><th>Kontrol</th><th>Bulgu</th><th>Kanıt</th></tr>" + rows + "</table>"
            f"<h2>Metrikler</h2><pre>{esc(json.dumps(data['metrics'], ensure_ascii=False, indent=2))}</pre>"
            "<h2>Sınırlar</h2><ul>" + "".join(f"<li>{esc(s)}</li>" for s in data["limitations"]) + "</ul></body></html>\n")


def signal_handler(signum, _frame):
    raise Interrupted(signum)


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        validate_args(args)
    except PreflightError as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 3
    if args.dry_run:
        print(json.dumps({"version": VERSION, "plan": vars(args), "load_tests": args.mode != "health",
                          "disk_writes": args.mode in ("full", "disk-only"),
                          "note": "Plan: komut, root kontrolü, dizin oluşturma veya paket kurulumu yapılmadı."},
                         default=str, ensure_ascii=False, indent=2))
        return 0
    os.umask(0o077)
    runner = Runner(args)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, signal_handler)
    code = 3
    interrupted = None
    try:
        runner.setup()
        runner.install()
        runner.inventory()
        runner.health()
        if args.mode in ("full", "disk-only"):
            runner.disk_preflight()
        if args.mode in ("quick", "full", "stress-only"):
            runner.stress()
        if args.mode in ("full", "disk-only"):
            runner.disk()
        if args.mode == "network":
            runner.network()
        code = 0
    except Interrupted as exc:
        interrupted = exc.signum
        runner.add("interrupted", "WARN", f"Sinyal {exc.signum}; alt süreçler durduruldu.")
    except (PreflightError, OSError) as exc:
        runner.add("execution", "WARN", str(exc))
        if any(record["status"] == "FAIL" for record in runner.records):
            code = 2
    except Exception as exc:
        runner.add("internal-error", "FAIL", f"{type(exc).__name__}: {exc}")
        code = 2
    finally:
        # A second signal must not interrupt cleanup or leave a report half-written.
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, signal.SIG_IGN)
        if runner.out is not None:
            try:
                if "before" in runner.meta:
                    runner.postcheck()
            except Exception as exc:
                runner.add("postcheck", "WARN", str(exc))
            runner.cleanup()
            try:
                result = runner.report(128 + interrupted if interrupted else code if code else None)
                if code == 0:
                    code = result
                print(f"Rapor: {runner.out / 'REPORT.txt'}", flush=True)
            except OSError as exc:
                print(f"Rapor yazılamadı: {exc}", file=sys.stderr)
                code = 3
        if runner.lock is not None:
            runner.lock.close()
    return 128 + interrupted if interrupted else code


if __name__ == "__main__":
    sys.exit(main())
