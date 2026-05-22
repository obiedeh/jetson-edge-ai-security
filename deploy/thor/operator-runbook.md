# Edge IDS — Jetson AGX Thor Operator Runbook

**Target:** NVIDIA Jetson AGX Thor (aarch64, JetPack 6.x, TensorRT 10.x)
**Service:** `edge-security.service` (systemd)
**Dashboard:** `http://<jetson-ip>:8080`

---

## Prerequisites

| Item | Requirement |
|---|---|
| Hardware | Jetson AGX Thor (64 GB LPDDR5) |
| JetPack | 6.0+ (includes TensorRT 10.x, CUDA 12.x) |
| Python | 3.10+ (included in JetPack) |
| Disk | 8 GB free (models + data) |
| Network | LAN access from operator workstation |

---

## 1. Initial Installation

```bash
# Clone repo on your dev machine, then scp to Thor
scp -r jetson-edge-ai-security/ thor:/tmp/edge-ids-src

# On Thor:
cd /tmp/edge-ids-src

# Build web dashboard (requires Node.js + pnpm on Thor, or build on dev and copy dist/)
# Option A — build on dev machine, copy dist:
#   (dev) cd web && pnpm build
#   (dev) scp -r web/dist/ thor:/tmp/edge-ids-src/web/dist/

# Install (as root)
sudo bash deploy/thor/install.sh
```

After install:
- Service auto-starts on boot
- Dashboard available at `http://localhost:8080`
- Data persisted in `/var/lib/edge-ids/`

---

## 2. Upgrade

```bash
# Pull latest changes on dev, scp to Thor, then:
sudo bash deploy/thor/install.sh --upgrade
```

The `--upgrade` flag recreates the virtualenv and reinstalls all Python deps.
The service is restarted automatically.

---

## 3. Check Service Status

```bash
# One-line status
systemctl status edge-security

# Live logs (follow)
journalctl -fu edge-security

# Last 100 lines
journalctl -u edge-security -n 100 --no-pager

# Since last boot
journalctl -u edge-security -b
```

---

## 4. Restart / Stop / Disable

```bash
# Restart (applies config changes without reinstall)
sudo systemctl restart edge-security

# Stop (does not disable on reboot)
sudo systemctl stop edge-security

# Disable (won't start on next boot)
sudo systemctl disable edge-security

# Re-enable
sudo systemctl enable edge-security && sudo systemctl start edge-security
```

---

## 5. Run Thor Benchmark

The benchmark measures p50/p95/p99 inference latency and throughput at three
load tiers (10 / 100 / 1000 events/sec), each sustained for 5 minutes.

```bash
# From repo root on Thor:
python3 deploy/thor/run_benchmark.py \
    --models-dir /opt/edge-ids/models/exports \
    --output /var/lib/edge-ids/reports/thor_benchmark.json \
    --trt          # use TensorRT EP (recommended on Thor)

# Shorter run for smoke test (30s per tier):
python3 deploy/thor/run_benchmark.py --duration 30 --tiers 100,1000
```

Results land in `reports/thor_benchmark.json` and are immediately visible in
the dashboard under **Settings → Thor Benchmark → Previous Runs**.

---

## 6. Build TensorRT Engines

Engines are built automatically by `install.sh` when TensorRT is available.
To rebuild manually (e.g. after updating ONNX files):

```bash
python3 deploy/thor/build_tensorrt_engines.py \
    --models-dir /opt/edge-ids/models/exports \
    --fp16
```

Engine files are written as `<name>.trt` alongside the ONNX files.
A `trt_build_manifest.json` records build time and hash of each engine.

---

## 7. Train / Retrain Reference Models

The dashboard flags `retrain_recommended = true` when the moving-average AUC
drops below the floor (default 0.90).

```bash
# On dev machine (GPU training) — then deploy updated PKL + ONNX to Thor:
edge-security train detector \
    --dataset data/datasets/edge_iiotset.csv \
    --output-dir models/exports

edge-security train forecaster \
    --dataset data/datasets/edge_iiotset.csv \
    --output-dir models/exports

# Export ONNX
edge-security export onnx mock-detector  # swap for reference models

# Deploy to Thor
scp models/exports/*.pkl models/exports/*.onnx thor:/opt/edge-ids/models/exports/

# Rebuild TRT engines on Thor
ssh thor "python3 /opt/edge-ids/deploy/thor/build_tensorrt_engines.py --fp16"

# Restart service
ssh thor "sudo systemctl restart edge-security"
```

---

## 8. Rollback

```bash
# Stop service
sudo systemctl stop edge-security

# Restore previous model files (keep them in /opt/edge-ids/models/backup/)
sudo cp /opt/edge-ids/models/backup/*.pkl /opt/edge-ids/models/exports/
sudo cp /opt/edge-ids/models/backup/*.onnx /opt/edge-ids/models/exports/

# Rebuild engines
python3 /opt/edge-ids/deploy/thor/build_tensorrt_engines.py --fp16

# Restart
sudo systemctl start edge-security
```

---

## 9. Collect Diagnostics

```bash
# System snapshot
uname -a
cat /etc/nv_tegra_release
nvidia-smi       # GPU status
tegrastats --interval 1000  # power / temp / memory

# Service logs for support bundle
journalctl -u edge-security --since "1 hour ago" > /tmp/edge-ids-logs.txt

# DB stats
sqlite3 /var/lib/edge-ids/data/alerts.db \
    "SELECT attack_type, COUNT(*) FROM alerts GROUP BY attack_type;"
```

---

## 10. File Locations

| Path | Contents |
|---|---|
| `/opt/edge-ids/` | Application root |
| `/opt/edge-ids/src/` | Python source |
| `/opt/edge-ids/models/exports/` | ONNX + TRT engine files |
| `/opt/edge-ids/configs/default.yaml` | Runtime config |
| `/opt/edge-ids/web/dist/` | Web dashboard static files |
| `/var/lib/edge-ids/data/alerts.db` | SQLite alerts database |
| `/var/lib/edge-ids/reports/` | Training run JSON, benchmark JSON |
| `/var/lib/edge-ids/artifacts/` | Pipeline evidence artifacts |
| `/etc/systemd/system/edge-security.service` | Systemd unit file |
| `/opt/edge-ids/.venv/` | Python virtual environment |

---

## 11. Performance Reference

Measured on Jetson AGX Thor (TensorRT 10.x, FP16):

| Metric | Target | Measured |
|---|---|---|
| Detector p95 latency | ≤ 10 ms | See `thor_benchmark.json` |
| Forecaster p95 latency | ≤ 50 ms | See `thor_benchmark.json` |
| Throughput @ 1000 ev/s | ≥ 1000 ev/s | See `thor_benchmark.json` |
| Memory footprint (both engines) | ≤ 4 GB | See `thor_benchmark.json` |

Run `python3 deploy/thor/run_benchmark.py` to regenerate with current hardware.
Numbers are **not aspirational** — whatever the benchmark measures is what
goes in the report.

---

## 12. Troubleshooting

| Symptom | Check |
|---|---|
| Service won't start | `journalctl -u edge-security -n 50` for traceback |
| Port 8080 already in use | `ss -tlnp | grep 8080` → kill conflicting process |
| TRT engine load fails | Delete `.trt` files and run `build_tensorrt_engines.py` |
| Dashboard unreachable | Check firewall: `ufw status`; allow port 8080 |
| High memory | Check `tegrastats`; reduce `--workers` in service ExecStart |
| Retrain flag stuck | Check `reports/training_run.json` AUC value vs floor in config |
