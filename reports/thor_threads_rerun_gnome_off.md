# Thread-pool power comparison rerun on Jetson AGX Thor with the GNOME desktop stopped, 2026-09-16

Raw per-run data: `thor_threads_rerun_gnome_off.json` in this directory. Every number below names its source file and field; nothing is rounded beyond the artifact's own precision except the W conversion (mW / 1000).

Session: session_start 2026-09-16T03:10:54Z base_vin=16130 base_tj=36.4; session_end 2026-09-16T03:55:31Z

Power metric: the harness stores p50 and peak of 1 Hz `tegrastats` VIN samples per tier. An arithmetic mean was not recorded, so "average power" is the p50.

## detector, per run

| Order | Configuration | Average (p50) power W | Peak power W | Idle before run W (harness 60 s) | Idle Tj before run C | Peak Tj C | Missed events | Target rate | Achieved rate | p95 ms | Finished (UTC) | L4T | ORT | Provider | Source |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | default thread pool | 46.608 | 47.046 | 15.770 | 35.812 | 52.468 | 99 | 1,000.0 | 1,000.0 | 0.0359 | 2026-09-16T03:17:25.533691+00:00 | # R38 (release), REVISION: 4.0, GCID: 43443517, BOARD: generic, EABI: aarch64, DATE: Wed Dec 31 00:15:19 UTC 2025 | 1.29.0 | CPUExecutionProvider | `run1_default.json: models[model=detector].tiers[target_rps=1000.0]` |
| 2 | single-threaded (intra-op 1, inter-op 1, spinning disabled) | 15.548 | 17.144 | 15.592 | 37.5 | 37.437 | 8 | 1,000.0 | 1,000.0 | 0.0229 | 2026-09-16T03:23:56.220348+00:00 | # R38 (release), REVISION: 4.0, GCID: 43443517, BOARD: generic, EABI: aarch64, DATE: Wed Dec 31 00:15:19 UTC 2025 | 1.29.0 | CPUExecutionProvider | `run2_single.json: models[model=detector].tiers[target_rps=1000.0]` |
| 3 | default thread pool | 46.676 | 48.300 | 15.778 | 36.906 | 53.562 | 389 | 1,000.0 | 1,000.0 | 0.0359 | 2026-09-16T03:30:26.934030+00:00 | # R38 (release), REVISION: 4.0, GCID: 43443517, BOARD: generic, EABI: aarch64, DATE: Wed Dec 31 00:15:19 UTC 2025 | 1.29.0 | CPUExecutionProvider | `run3_default.json: models[model=detector].tiers[target_rps=1000.0]` |
| 4 | single-threaded (intra-op 1, inter-op 1, spinning disabled) | 15.588 | 18.694 | 15.456 | 38.062 | 38.062 | 20 | 1,000.0 | 1,000.0 | 0.0224 | 2026-09-16T03:38:28.101792+00:00 | # R38 (release), REVISION: 4.0, GCID: 43443517, BOARD: generic, EABI: aarch64, DATE: Wed Dec 31 00:15:19 UTC 2025 | 1.29.0 | CPUExecutionProvider | `run4_single.json: models[model=detector].tiers[target_rps=1000.0]` |
| 5 | default thread pool | 46.852 | 47.210 | 15.860 | 37.468 | 54.125 | 226 | 1,000.0 | 1,000.0 | 0.0369 | 2026-09-16T03:44:58.858702+00:00 | # R38 (release), REVISION: 4.0, GCID: 43443517, BOARD: generic, EABI: aarch64, DATE: Wed Dec 31 00:15:19 UTC 2025 | 1.29.0 | CPUExecutionProvider | `run5_default.json: models[model=detector].tiers[target_rps=1000.0]` |
| 6 | single-threaded (intra-op 1, inter-op 1, spinning disabled) | 15.692 | 17.154 | 15.976 | 38.156 | 38.25 | 21 | 1,000.0 | 1,000.0 | 0.0225 | 2026-09-16T03:55:31.080532+00:00 | # R38 (release), REVISION: 4.0, GCID: 43443517, BOARD: generic, EABI: aarch64, DATE: Wed Dec 31 00:15:19 UTC 2025 | 1.29.0 | CPUExecutionProvider | `run6_single.json: models[model=detector].tiers[target_rps=1000.0]` |

## detector, per configuration (VIN p50 at 1000 events/s)

| Configuration | Runs | Median W | Min W | Max W | p95 ms median | Misses median |
|---|---|---|---|---|---|---|
| default | 3 | 46.676 | 46.608 | 46.852 | 0.0359 | 226 |
| single | 3 | 15.588 | 15.548 | 15.692 | 0.0225 | 20 |

Paired power delta, default minus single-threaded, consecutive pairs in run order: 31.060, 31.088, 31.160 W; median 31.088 W, spread 31.060 to 31.160 W over 3 pairs.

Do the two power ranges overlap: **no**.

## forecaster, per run

| Order | Configuration | Average (p50) power W | Peak power W | Idle before run W (harness 60 s) | Idle Tj before run C | Peak Tj C | Missed events | Target rate | Achieved rate | p95 ms | Finished (UTC) | L4T | ORT | Provider | Source |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | default thread pool | 15.944 | 16.946 | 15.770 | 35.812 | 43.968 | 6 | 1,000.0 | 1,000.0 | 0.0378 | 2026-09-16T03:17:25.533691+00:00 | # R38 (release), REVISION: 4.0, GCID: 43443517, BOARD: generic, EABI: aarch64, DATE: Wed Dec 31 00:15:19 UTC 2025 | 1.29.0 | CPUExecutionProvider | `run1_default.json: models[model=forecaster].tiers[target_rps=1000.0]` |
| 2 | single-threaded (intra-op 1, inter-op 1, spinning disabled) | 15.668 | 16.736 | 15.592 | 37.5 | 37.187 | 9 | 1,000.0 | 1,000.0 | 0.0378 | 2026-09-16T03:23:56.220348+00:00 | # R38 (release), REVISION: 4.0, GCID: 43443517, BOARD: generic, EABI: aarch64, DATE: Wed Dec 31 00:15:19 UTC 2025 | 1.29.0 | CPUExecutionProvider | `run2_single.json: models[model=forecaster].tiers[target_rps=1000.0]` |
| 3 | default thread pool | 16.104 | 22.164 | 15.778 | 36.906 | 45.125 | 6 | 1,000.0 | 1,000.0 | 0.0380 | 2026-09-16T03:30:26.934030+00:00 | # R38 (release), REVISION: 4.0, GCID: 43443517, BOARD: generic, EABI: aarch64, DATE: Wed Dec 31 00:15:19 UTC 2025 | 1.29.0 | CPUExecutionProvider | `run3_default.json: models[model=forecaster].tiers[target_rps=1000.0]` |
| 4 | single-threaded (intra-op 1, inter-op 1, spinning disabled) | 15.554 | 16.958 | 15.456 | 38.062 | 37.812 | 5 | 1,000.0 | 1,000.0 | 0.0370 | 2026-09-16T03:38:28.101792+00:00 | # R38 (release), REVISION: 4.0, GCID: 43443517, BOARD: generic, EABI: aarch64, DATE: Wed Dec 31 00:15:19 UTC 2025 | 1.29.0 | CPUExecutionProvider | `run4_single.json: models[model=forecaster].tiers[target_rps=1000.0]` |
| 5 | default thread pool | 15.704 | 17.238 | 15.860 | 37.468 | 45.625 | 10 | 1,000.0 | 1,000.0 | 0.0379 | 2026-09-16T03:44:58.858702+00:00 | # R38 (release), REVISION: 4.0, GCID: 43443517, BOARD: generic, EABI: aarch64, DATE: Wed Dec 31 00:15:19 UTC 2025 | 1.29.0 | CPUExecutionProvider | `run5_default.json: models[model=forecaster].tiers[target_rps=1000.0]` |
| 6 | single-threaded (intra-op 1, inter-op 1, spinning disabled) | 15.512 | 17.502 | 15.976 | 38.156 | 38.093 | 3 | 1,000.0 | 1,000.0 | 0.0437 | 2026-09-16T03:55:31.080532+00:00 | # R38 (release), REVISION: 4.0, GCID: 43443517, BOARD: generic, EABI: aarch64, DATE: Wed Dec 31 00:15:19 UTC 2025 | 1.29.0 | CPUExecutionProvider | `run6_single.json: models[model=forecaster].tiers[target_rps=1000.0]` |

## forecaster, per configuration (VIN p50 at 1000 events/s)

| Configuration | Runs | Median W | Min W | Max W | p95 ms median | Misses median |
|---|---|---|---|---|---|---|
| default | 3 | 15.944 | 15.704 | 16.104 | 0.0379 | 6 |
| single | 3 | 15.554 | 15.512 | 15.668 | 0.0378 | 5 |

Paired power delta, default minus single-threaded, consecutive pairs in run order: 0.276, 0.550, 0.192 W; median 0.276 W, spread 0.192 to 0.550 W over 3 pairs.

Do the two power ranges overlap: **no**.

## What else was running on the device

- run1_default (`system_snapshot_run1_default.txt`): 2026-09-16T03:11:25Z |  22:11:25 up 38 days,  5:34,  4 users,  load average: 0.22, 0.94, 1.46 | 0 | inactive |     PID %CPU %MEM COMMAND | 3759295 45.9  0.0 kworker/u28:0-ext4-rsv-conversion | 3764747 22.7  0.0 kworker/u28:2-dce-async-ipc-wq |    1862  0.3  0.0 disp_eng_share_thread | 3692374  0.2  0.0 (udev-worker) |    2392  0.1  0.0 nv_queue | harness load average 1 min at start: 0.21728515625
- run2_single (`system_snapshot_run2_single.txt`): 2026-09-16T03:17:55Z |  22:17:55 up 38 days,  5:40,  5 users,  load average: 0.47, 2.48, 2.26 | 0 | inactive |     PID %CPU %MEM COMMAND | 3784013  100  0.0 ps | 3759295 45.8  0.0 kworker/u28:0-ext4-rsv-conversion | 3764747 22.6  0.0 kworker/u28:2-dce-async-ipc-wq |    1862  0.3  0.0 disp_eng_share_thread | 3692374  0.2  0.0 (udev-worker) | harness load average 1 min at start: 0.46923828125
- run3_default (`system_snapshot_run3_default.txt`): 2026-09-16T03:24:26Z |  22:24:26 up 38 days,  5:47,  4 users,  load average: 0.24, 0.84, 1.55 | 0 | inactive |     PID %CPU %MEM COMMAND | 3784257  100  0.0 ps | 3759295 45.6  0.0 kworker/u28:0-ext4-rsv-conversion | 3764747 22.5  0.0 kworker/u28:2-dce-async-ipc-wq |    1862  0.3  0.0 disp_eng_share_thread | 3692374  0.2  0.0 (udev-worker) | harness load average 1 min at start: 0.23974609375
- run4_single (`system_snapshot_run4_single.txt`): 2026-09-16T03:32:27Z |  22:32:27 up 38 days,  5:55,  5 users,  load average: 0.40, 1.92, 2.14 | 0 | inactive |     PID %CPU %MEM COMMAND | 3759295 45.5  0.0 kworker/u28:0-ext4-rsv-conversion | 3764747 22.5  0.0 kworker/u28:2-dce-async-ipc-wq |    1862  0.3  0.0 disp_eng_share_thread | 3692374  0.2  0.0 (udev-worker) | 3784461  0.2  0.0 fwupd | harness load average 1 min at start: 0.3994140625
- run5_default (`system_snapshot_run5_default.txt`): 2026-09-16T03:38:58Z |  22:38:58 up 38 days,  6:01,  5 users,  load average: 0.14, 0.62, 1.44 | 0 | inactive |     PID %CPU %MEM COMMAND | 3759295 45.4  0.0 kworker/u28:0-ext4-rsv-conversion | 3764747 22.4  0.0 kworker/u28:2-dce-async-ipc-wq |    1862  0.3  0.0 disp_eng_share_thread | 3692374  0.2  0.0 (udev-worker) |    2392  0.1  0.0 nv_queue | harness load average 1 min at start: 0.1416015625
- run6_single (`system_snapshot_run6_single.txt`): 2026-09-16T03:49:30Z |  22:49:30 up 38 days,  6:12,  5 users,  load average: 0.20, 1.22, 1.80 | 0 | inactive |     PID %CPU %MEM COMMAND | 3759295 45.2  0.0 kworker/u28:0-ext4-rsv-conversion | 3764747 22.3  0.0 kworker/u28:2-dce-async-ipc-wq |    1862  0.3  0.0 disp_eng_share_thread | 3692374  0.2  0.0 (udev-worker) |    2392  0.1  0.0 nv_queue | harness load average 1 min at start: 0.2001953125

`ps` percentages in the snapshots are lifetime averages per process, not instantaneous load. The display manager state line (`active`/`inactive`) is `systemctl is-active gdm` at snapshot time.

## Cooldown gate

- before run1_default: VIN p50 15.740 W, Tj max 35.937 C, settled=True (`cooldown.jsonl`)
- before run2_single: VIN p50 15.414 W, Tj max 37.937 C, settled=True (`cooldown.jsonl`)
- before run3_default: VIN p50 16.250 W, Tj max 37.031 C, settled=True (`cooldown.jsonl`)
- before run4_single: VIN p50 15.972 W, Tj max 38.343 C, settled=True (`cooldown.jsonl`)
- before run5_default: VIN p50 15.924 W, Tj max 37.625 C, settled=True (`cooldown.jsonl`)
- before run6_single: VIN p50 15.556 W, Tj max 38.375 C, settled=True (`cooldown.jsonl`)
