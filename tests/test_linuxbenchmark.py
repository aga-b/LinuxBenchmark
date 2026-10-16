"""Hardware-free safety and parser regression tests; never run fio/stress/apt."""
import contextlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import linuxbenchmark as lb


def args(*argv):
    result = lb.parser().parse_args(argv)
    lb.validate_args(result)
    return result


def snap(available=32 * lb.GIB, temperature=40, ue=0):
    return {"at": "test", "memory": {"MemAvailable": available},
            "cpu_temperatures": {"cpu": temperature},
            "edac": {"mc0/ue_count": ue}, "network": {"eth0/rx_errors": 0}}


def fio_result(rw="write", error=0):
    return {"jobs": [{"jobname": "test", "error": error,
                      rw: {"io_bytes": 1024, "bw_bytes": 104857600, "iops": 100,
                           "clat_ns": {"mean": 2000000, "percentile": {"99.000000": 5000000}}}}]}


class SafetyTests(unittest.TestCase):
    def test_defaults_do_not_enable_load_or_install(self):
        config = args()
        self.assertEqual(config.mode, "health")
        self.assertFalse(config.install_deps)
        self.assertEqual(config.cpu_load, 75)

    def test_legacy_no_stress_is_health(self):
        self.assertEqual(args("--no-stress").mode, "health")

    def test_quick_is_cpu_memory_only(self):
        config = args("--quick")
        self.assertEqual(config.duration, 20)
        self.assertIsNone(config.fio_dir)

    def test_full_requires_explicit_disk_directory(self):
        with self.assertRaises(lb.PreflightError):
            args("--mode", "full")

    def test_conflicting_modes_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            args("--quick", "--no-stress")

    def test_invalid_sizes_rejected(self):
        for size in ("0G", "-1G", "1T", "65G", "32M", "999999999999999999G", "/dev/sda", "1G;reboot"):
            with self.subTest(size=size), self.assertRaises(Exception):
                lb.size_bytes(size)

    def test_memory_bound_uses_available_and_reserve(self):
        self.assertEqual(lb.memory_budget(16 * lb.GIB, 4 * lb.GIB), 4 * lb.GIB)
        self.assertEqual(lb.memory_budget(512 * lb.GIB, 4 * lb.GIB), 8 * lb.GIB)
        with self.assertRaises(lb.PreflightError):
            lb.memory_budget(3 * lb.GIB, 4 * lb.GIB)
        with self.assertRaises(lb.PreflightError):
            lb.memory_budget(16 * lb.GIB, 4 * lb.GIB, 8 * lb.GIB)

    def test_raw_and_virtual_targets_rejected(self):
        for path in ("/dev/null", "/dev", "/proc", "/sys", "/run"):
            with self.subTest(path=path), self.assertRaises(lb.PreflightError):
                lb.validate_fio_directory(Path(path))

    def test_fio_special_filename_grammar_rejected(self):
        with tempfile.TemporaryDirectory(prefix="colon:") as temp, self.assertRaises(lb.PreflightError):
            lb.validate_fio_directory(Path(temp))

    def test_world_writable_ancestor_rejected(self):
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(lb.PreflightError):
            lb.validate_fio_directory(Path(temp))  # /tmp is writable; root requirement alone is insufficient.

    def test_network_requires_explicit_endpoint(self):
        with self.assertRaises(lb.PreflightError):
            args("--mode", "network")
        with self.assertRaises(lb.PreflightError):
            args("--iperf-server", "127.0.0.1")
        with self.assertRaises(lb.PreflightError):
            args("--mode", "network", "--iperf-server=-s")

    def test_dry_run_creates_no_files_and_executes_no_commands(self):
        with patch.object(lb.Runner, "setup", side_effect=AssertionError("setup invoked")), \
             patch.object(subprocess, "Popen", side_effect=AssertionError("command invoked")), \
             patch.object(Path, "mkdir", side_effect=AssertionError("mkdir invoked")), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(lb.main(["--dry-run", "--install-deps"]), 0)
        self.assertFalse(json.loads(output.getvalue())["load_tests"])

    def test_unknown_workload_state_blocks_load(self):
        runner = lb.Runner(args("--quick"))
        with patch.object(lb.shutil, "which", return_value="/fake"), \
             patch.object(runner, "run", return_value=(0, "unexpected output", "log")), \
             self.assertRaises(lb.PreflightError):
            runner.workload_guard()

    def test_running_local_guests_block_load(self):
        runner = lb.Runner(args("--quick"))
        def fake(name, _cmd):
            text = "VMID NAME STATUS\n930 SQL running\n" if "qemu" in name else "VMID STATUS NAME\n"
            return 0, text, "log"
        with patch.object(lb.shutil, "which", return_value="/fake"), \
             patch.object(runner, "run", side_effect=fake), self.assertRaises(lb.PreflightError):
            runner.workload_guard()

    def test_stopped_local_guests_allow_load(self):
        runner = lb.Runner(args("--quick"))
        with patch.object(lb.shutil, "which", return_value="/fake"), \
             patch.object(runner, "run", return_value=(0, "VMID NAME STATUS\n930 SQL stopped\n", "log")):
            runner.workload_guard()

    def test_fail_health_blocks_load(self):
        runner = lb.Runner(args("--quick"))
        runner.records = [{"status": "FAIL"}]
        with patch.object(runner, "workload_guard"), patch.object(lb, "snapshot", return_value=snap()), \
             self.assertRaises(lb.PreflightError):
            runner.load_guard()

    def test_hot_host_blocks_load(self):
        runner = lb.Runner(args("--quick"))
        with patch.object(runner, "workload_guard"), patch.object(lb, "snapshot", return_value=snap(temperature=95)), \
             self.assertRaises(lb.PreflightError):
            runner.load_guard()

    def test_oversized_memory_rejected_before_cpu_stress(self):
        runner = lb.Runner(args("--quick", "--memory-mib", "32768"))
        with patch.object(lb.shutil, "which", return_value="/fake"), \
             patch.object(lb, "memory_info", return_value={"MemAvailable": 16 * lb.GIB}), \
             patch.object(runner, "run") as run, self.assertRaises(lb.PreflightError):
            runner.stress()
        run.assert_not_called()

    def test_explicit_large_memory_allowed_with_available_budget(self):
        self.assertEqual(lb.memory_budget(128 * lb.GIB, 8 * lb.GIB, 32 * lb.GIB, 50), 32 * lb.GIB)
        self.assertEqual(lb.memory_budget(128 * lb.GIB, 8 * lb.GIB, percent=50), 8 * lb.GIB)

    def test_cpu_worker_count_cannot_exceed_host(self):
        with patch.object(lb.os, "cpu_count", return_value=4), self.assertRaises(lb.PreflightError):
            args("--cpu-workers", "5")

    def test_unknown_guest_state_requires_explicit_override(self):
        runner = lb.Runner(args("--quick", "--allow-active-workloads"))
        with patch.object(lb.shutil, "which", return_value="/fake"), \
             patch.object(runner, "run", return_value=(1, "failed", "log")), \
             contextlib.redirect_stdout(io.StringIO()):
            runner.workload_guard()
        self.assertEqual(runner.records[-1]["status"], "WARN")


class ParsingTests(unittest.TestCase):
    def test_smart_historical_bits_are_not_healthy_or_current_failure(self):
        results = lb.smart_findings({"smart_status": {"passed": True}}, 64)
        self.assertIn("WARN", [r[0] for r in results])
        self.assertNotIn("PASS", [r[0] for r in results])
        self.assertNotIn("FAIL", [r[0] for r in results])

    def test_smart_failing_bit_is_failure(self):
        self.assertIn("FAIL", [r[0] for r in lb.smart_findings({}, 8)])

    def test_smart_no_health_not_passed(self):
        self.assertEqual(lb.smart_findings({}, 0)[0][0], "SKIP")

    def test_smart_command_error_not_health_failure(self):
        self.assertEqual(lb.smart_findings({}, 2)[0][0], "WARN")

    def test_nvme_warning_is_fail(self):
        data = {"nvme_smart_health_information_log": {"critical_warning": 1}}
        self.assertIn("FAIL", [r[0] for r in lb.smart_findings(data, 0)])

    def test_perc_offline_disk_fails(self):
        data = {"Controllers": [{"Command Status": {"Status": "Success"},
                                  "Response Data": {"PD LIST": [{"State": "Offln"}]}}]}
        self.assertIn("FAIL", [r[0] for r in lb.perc_findings(data)])

    def test_unknown_perc_schema_is_incomplete(self):
        data = {"Controllers": [{"Command Status": {"Status": "Success"}, "Response Data": {}}]}
        self.assertIn("SKIP", [r[0] for r in lb.perc_findings(data)])

    def test_fio_units_and_job_error(self):
        row = lb.fio_metrics(fio_result())[0]
        self.assertEqual(row["mib_s"], 100)
        self.assertEqual(row["clat_p99_ms"], 5)
        with self.assertRaises(ValueError):
            lb.fio_metrics(fio_result(error=5))
        with self.assertRaises(ValueError):
            lb.fio_metrics({"jobs": []})

    def test_skips_are_not_green(self):
        result = lb.summary([{"status": "PASS"}, {"status": "SKIP"}])
        self.assertEqual(result["state"], "INCOMPLETE")
        self.assertEqual(result["exit_code"], 1)
        self.assertEqual(result["acceptance"], "MANUAL_REVIEW_REQUIRED")

    def test_stress_metrics_units_and_format(self):
        text = "stress-ng: metrc: [123] cpu 1200 20.00 30.00 1.00 60.00 38.71"
        result = lb.stress_metrics(text, "cpu")
        self.assertEqual(result["bogo_ops_per_real_second"], 60)
        self.assertEqual(result["bogo_ops"], 1200)
        self.assertIsNone(lb.stress_metrics("unrecognized output", "cpu"))

    def test_perc_hotspare_is_not_offline_failure(self):
        data = {"Controllers": [{"Command Status": {"Status": "Success"},
                                  "Response Data": {"PD LIST": [{"State": "GHS"}]}}]}
        self.assertNotIn("FAIL", [r[0] for r in lb.perc_findings(data)])


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runner = lb.Runner(args())
        self.runner.out = Path(self.temp.name)
        for folder in ("logs", "inventory", "benchmarks"):
            (self.runner.out / folder).mkdir()

    def test_command_failure_recorded(self):
        rc, _, _ = self.runner.run("failure", [sys.executable, "-c", "raise SystemExit(7)"])
        self.assertEqual(rc, 7)
        self.assertEqual(self.runner.commands[0]["exit_code"], 7)
        self.assertEqual(self.runner.records[-1]["status"], "WARN")

    def test_timeout_kills_process_group(self):
        pidfile = self.runner.out / "child.pid"
        script = ("import subprocess,sys,time; "
                  "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)']); "
                  "open(sys.argv[1],'w').write(str(p.pid)); time.sleep(120)")
        rc, _, _ = self.runner.run("timeout", [sys.executable, "-c", script, str(pidfile)], timeout=0.5)
        self.assertEqual(rc, 124)
        self.assertTrue(pidfile.exists())
        state = lb.read_text(Path("/proc") / pidfile.read_text() / "stat")
        self.assertTrue(not state or state.split()[2] == "Z", "worker still running")

    def test_temperature_during_load_aborts(self):
        with patch.object(lb, "snapshot", return_value=snap(temperature=99)):
            rc, _, _ = self.runner.run("hot", [sys.executable, "-c", "import time;time.sleep(120)"], load=True)
        self.assertEqual(rc, 124)
        self.assertTrue(self.runner.aborted)
        self.assertEqual(self.runner.records[-1]["status"], "FAIL")

    def test_ecc_increase_during_load_aborts(self):
        self.runner.meta["before"] = snap(ue=0)
        with patch.object(lb, "snapshot", return_value=snap(ue=1)):
            rc, _, _ = self.runner.run("ecc", [sys.executable, "-c", "import time;time.sleep(120)"], load=True)
        self.assertEqual(rc, 124)

    def test_memory_pressure_during_load_aborts(self):
        with patch.object(lb, "snapshot", return_value=snap(available=lb.GIB)):
            rc, _, _ = self.runner.run("ram", [sys.executable, "-c", "import time;time.sleep(120)"], load=True)
        self.assertEqual(rc, 124)

    def test_cleanup_does_not_follow_symlinks(self):
        self.runner.tempdir = self.runner.out / "owned"
        self.runner.tempdir.mkdir()
        sentinel = self.runner.out / "sentinel"
        sentinel.write_text("keep")
        (self.runner.tempdir / "test.bin").symlink_to(sentinel)
        self.runner.cleanup()
        self.assertEqual(sentinel.read_text(), "keep")
        self.assertEqual(self.runner.records[-1]["status"], "WARN")

    def test_disk_jobs_use_only_private_file_and_read_jobs_are_readonly(self):
        self.runner.args = args("--mode", "disk-only", "--fio-dir", self.temp.name)
        calls = []
        def fake(name, argv, **kwargs):
            calls.append((name, argv))
            if name == "fio-version":
                return 0, "fio-3.33", "version.log"
            if name.startswith("fio-"):
                rw = "read" if "read" in name else "write"
                return 0, json.dumps(fio_result(rw)), "fio.log"
            raise AssertionError(name)
        with patch.object(self.runner, "load_guard"), \
             patch.object(self.runner, "disk_preflight", return_value=(Path(self.temp.name), {"source": "test"}, 0)), \
             patch.object(self.runner, "run", side_effect=fake):
            self.runner.disk()
        jobs = [argv for name, argv in calls if name != "fio-version"]
        self.assertEqual(len(jobs), 4)
        for argv in jobs:
            name = next(a.split("=", 1)[1] for a in argv if a.startswith("--filename="))
            self.assertTrue(Path(name).is_file())
            self.assertEqual(Path(name).parent, self.runner.tempdir)
            self.assertIn("--allow_file_create=0", argv)
            if any(a in argv for a in ("--rw=read", "--rw=randread")):
                self.assertIn("--readonly", argv)
        self.runner.cleanup()
        self.assertFalse(self.runner.tempdir.exists())


    def test_remote_or_virtual_filesystem_rejected(self):
        self.runner.args.fio_dir = Path(self.temp.name)
        for fstype in ("nfs", "cifs", "tmpfs", "overlay"):
            data = {"filesystems": [{"fstype": fstype, "options": "rw"}]}
            with self.subTest(fstype=fstype), \
                 patch.object(lb, "validate_fio_directory", return_value=Path(self.temp.name)), \
                 patch.object(self.runner, "run", return_value=(0, json.dumps(data), "log")), \
                 self.assertRaises(lb.PreflightError):
                self.runner.disk_preflight()

    def test_insufficient_disk_space_rejected(self):
        self.runner.args.fio_dir = Path(self.temp.name)
        data = {"filesystems": [{"fstype": "ext4", "options": "rw"}]}
        usage = type("Usage", (), {"free": lb.GIB, "total": 10 * lb.GIB})()
        with patch.object(lb, "validate_fio_directory", return_value=Path(self.temp.name)), \
             patch.object(self.runner, "run", return_value=(0, json.dumps(data), "log")), \
             patch.object(lb.shutil, "disk_usage", return_value=usage), \
             self.assertRaises(lb.PreflightError):
            self.runner.disk_preflight()

    def test_readonly_filesystem_rejected(self):
        self.runner.args.fio_dir = Path(self.temp.name)
        data = {"filesystems": [{"fstype": "ext4", "options": "ro,noexec"}]}
        with patch.object(lb, "validate_fio_directory", return_value=Path(self.temp.name)), \
             patch.object(self.runner, "run", return_value=(0, json.dumps(data), "log")), \
             self.assertRaises(lb.PreflightError):
            self.runner.disk_preflight()

    def test_disk_reserve_monitored_during_load(self):
        self.runner.io_target = self.runner.out
        self.runner.io_margin = 4 * lb.GIB
        usage = type("Usage", (), {"free": lb.GIB})()
        with patch.object(lb, "snapshot", return_value=snap()), \
             patch.object(lb.shutil, "disk_usage", return_value=usage):
            rc, _, _ = self.runner.run("space", [sys.executable, "-c", "import time;time.sleep(120)"], load=True)
        self.assertEqual(rc, 124)
        self.assertTrue(self.runner.aborted)

    def test_report_escapes_html_and_preserves_process_code(self):
        self.runner.add("<script>", "WARN", "<img onerror='x'>")
        self.runner.report(exit_override=3)
        document = (self.runner.out / "REPORT.html").read_text()
        self.assertNotIn("<script>", document)
        self.assertIn("&lt;img", document)
        result = json.loads((self.runner.out / "report.json").read_text())
        self.assertEqual(result["metadata"]["process_exit_code"], 3)
        self.assertEqual(result["summary"]["exit_code"], 1)

    def test_health_flow_never_runs_apt_fio_or_stress(self):
        invoked = []
        def setup(runner):
            runner.out = self.runner.out
        def fake(runner, name, argv, **kwargs):
            invoked.append(argv)
            if name == "smart-scan":
                return 0, '{"devices": []}', "logs/test.log"
            return 0, "", "logs/test.log"
        previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
        try:
            with patch.object(lb.Runner, "setup", setup), patch.object(lb.Runner, "run", fake), \
                 patch.object(lb, "snapshot", return_value=snap()), \
                 patch.object(lb.shutil, "which", return_value=None), \
                 contextlib.redirect_stdout(io.StringIO()):
                rc = lb.main([])
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
        self.assertEqual(rc, 1)  # Missing SMART/PERC coverage must not be green.
        self.assertFalse(any(command[0] in ("fio", "stress-ng", "apt-get", "iperf3") and "--version" not in command for command in invoked))
        self.assertTrue((self.runner.out / "REPORT.txt").exists())


if __name__ == "__main__":
    unittest.main()
