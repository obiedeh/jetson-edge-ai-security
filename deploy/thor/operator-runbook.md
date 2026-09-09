# Edge IDS — Jetson AGX Thor Operator Runbook

**Target:** Jetson AGX Thor-class target hardware. Record the exact device SKU, JetPack version, memory configuration, NIC/interface name, and benchmark environment in the generated benchmark artifact.  
**Service:** `edge-security.service` (systemd)  
**Dashboard:** `http://<jetson-ip>:8080`

## Prerequisites

| Item | Requirement |
|---|---|
| Hardware | Jetson AGX Thor-class target hardware; record the exact SKU and memory configuration |
| JetPack | Record the installed JetPack, TensorRT, and CUDA versions |
| Python | 3.10+ |
| Disk | 8 GB free for models, reports, and telemetry artifacts |
| Network | LAN access from operator workstation |

## 1. Initial Installation

```bash
# Clone repo on your dev machine, then copy to the Jetson target.
scp -r jetson-edge-ai-security/ thor:/tmp/edge-ids-src

# On the Jetson target:
cd /tmp/edge-ids-src

# Build web dashboard on dev and copy dist when Node/pnpm is not installed on target.
#   (dev) cd web && pnpm build
#   (dev) scp -r web/dist/ thor:/tmp/edge-ids-src/web/dist/

sudo bash deploy/thor/install.sh
```

After install:

- Service auto-starts on boot.
- Dashboard is available at `http://localhost:8080`.
- Data persists in `/var/lib/edge-ids/`.

## 2. Upgrade

```bash
sudo bash deploy/thor/install.sh --upgrade
```

The `--upgrade` flag recreates the virtual environment, reinstalls Python dependencies, and restarts the service.

## 3. Check Service Status

```bash
systemctl status edge-security
journalctl -fu edge-security
journalctl -u edge-security -n 100 --no-pager
journalctl -u edge-security -b
```

## 4. Restart / Stop / Disable

```bash
sudo systemctl restart edge-security
sudo systemctl stop edge-security
sudo systemctl disable edge-security
sudo systemctl enable edge-security && sudo systemctl start edge-security
```

## 5. Run Thor-Class Benchmark

The benchmark script is the measurement path for p50/p95/p99 inference latency, throughput, and memory/runtime notes. Do not publish performance claims until the output is generated on the exact target hardware and committed as an evidence artifact.

```bash
python3 deploy/thor/run_benchmark.py \
    --models-dir /opt/edge-ids/models/exports \
    --output /var/lib/edge-ids/reports/thor_benchmark.json \
    --intra-op-threads 1 --inter-op-threads 1 --no-spin

# Compare thread-pool settings (baseline defaults vs single thread, no spin):
python3 deploy/thor/run_benchmark.py --duration 120 --tiers 100,1000 --output reports/thor_threads/default.json
python3 deploy/thor/run_benchmark.py --duration 120 --tiers 100,1000 --intra-op-threads 1 --inter-op-threads 1 --no-spin --output reports/thor_threads/single_thread.json
python3 deploy/thor/compare_thread_runs.py --baseline reports/thor_threads/default.json --variant reports/thor_threads/single_thread.json --output reports/thor_benchmark_threads.json

# Shorter smoke run:
python3 deploy/thor/run_benchmark.py --duration 30 --tiers 100,1000
```

Results land in `reports/thor_benchmark.json` (plus `_tegrastats.jsonl` and `_run.log` beside it) and can be surfaced by the dashboard after the artifact is copied back into the repo.

## 6. Build TensorRT Engines

Engines are built by `install.sh` when TensorRT is available. To rebuild manually after updating ONNX files:

```bash
python3 deploy/thor/build_tensorrt_engines.py \
    --models-dir /opt/edge-ids/models/exports \
    --fp16
```

Engine files are written as `<name>.trt` alongside the ONNX files. A `trt_build_manifest.json` records build time and hash of each engine.

## 7. Train / Retrain Reference Models

```bash
# On a development machine, then deploy updated artifacts to the Jetson target.
edge-security train detector \
    --dataset data/datasets/edge_iiotset.csv \
    --output-dir models/exports

edge-security train forecaster \
    --dataset data/datasets/edge_iiotset.csv \
    --output-dir models/exports

edge-security export onnx mock-detector

scp models/exports/*.pkl models/exports/*.onnx thor:/opt/edge-ids/models/exports/
ssh thor "python3 /opt/edge-ids/deploy/thor/build_tensorrt_engines.py --fp16"
ssh thor "sudo systemctl restart edge-security"
```

## 8. Rollback

```bash
sudo systemctl stop edge-security
sudo cp /opt/edge-ids/models/backup/*.pkl /opt/edge-ids/models/exports/
sudo cp /opt/edge-ids/models/backup/*.onnx /opt/edge-ids/models/exports/
python3 /opt/edge-ids/deploy/thor/build_tensorrt_engines.py --fp16
sudo systemctl start edge-security
```

## 9. Collect Diagnostics

```bash
uname -a
cat /etc/nv_tegra_release
tegrastats --interval 1000
journalctl -u edge-security --since "1 hour ago" > /tmp/edge-ids-logs.txt
sqlite3 /var/lib/edge-ids/data/alerts.db \
    "SELECT attack_type, COUNT(*) FROM alerts GROUP BY attack_type;"
```

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

## 11. Benchmark Reference

Measured values below come from run `3cac5ed2b7bd` in `reports/thor_benchmark.json` (Jetson AGX Thor, R38 (release), 120W, CPU execution provider, 300 s per tier).

| Metric | Target | Measured |
|---|---|---|
| Detector p95 latency | <= 10 ms | 0.0237 ms at 1000 events/s |
| Forecaster p95 latency | <= 50 ms | 0.0141 ms at 1000 events/s |
| Throughput at 1000 events/sec | >= 1000 events/sec | 1000.0 events/s |
| Memory footprint | <= 4 GB | 0.3639 GB peak process RSS |

Whatever the benchmark measures is what goes in the report. These are inference-only figures on the CPU provider; do not claim line-rate capture or end-to-end latency before those artifacts exist.

**Thread-pool setting.** `reports/thor_benchmark_threads.json` shows the onnxruntime default thread pool costing about 30 W of board power and 16944 pacing misses per 120 s at 1000 events/s for the detector, with no latency benefit. Configure the runtime's inference sessions with one intra-op thread, one inter-op thread and spin waiting disabled on Thor. `--trt` is retained for a future JetPack 7 onnxruntime build; the current PyPI wheel has no usable GPU kernels on this device.

## 12. Troubleshooting

| Symptom | Check |
|---|---|
| Service will not start | `journalctl -u edge-security -n 50` for traceback |
| Port 8080 already in use | `ss -tlnp | grep 8080`, then stop the conflicting process |
| TRT engine load fails | Delete `.trt` files and run `build_tensorrt_engines.py` |
| Dashboard unreachable | Check firewall and allow port 8080 |
| High memory | Check `tegrastats`; reduce worker count in service config |
| Retrain flag stuck | Check `reports/training_run.json` AUC value vs floor in config |

