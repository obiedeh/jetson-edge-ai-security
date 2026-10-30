# Thread-pool isolation on Jetson AGX Thor: thread count, spin-waiting, or both

Raw artifacts: `reports/thor_threads_isolation/`. Merged data: `thor_threads_isolation.json`. Every number names its source; `not recorded` marks values the harness does not capture.

## Preconditions

```
{
  "session_start_utc": "2026-09-16T05:37:26Z",
  "gdm": "inactive",
  "containers_running": 0,
  "gpu_processes": 0,
  "l4t_release": "# R38 (release), REVISION: 4.0, GCID: 43443517, BOARD: generic, EABI: aarch64, DATE: Wed Dec 31 00:15:19 UTC 2025",
  "onnxruntime": "1.29.0",
  "idle_baseline_60s": {
    "vin_p50_mw": 16056,
    "tj_p50_c": 38.312,
    "source": "session_idle_baseline_tegrastats.txt"
  },
  "cooldown_gate": {
    "vin_within_mw": 1000,
    "tj_within_c": 2.0,
    "window_s": 30,
    "cap_s": 900
  }
}
```

## Configurations

- **A**: default threads, spinning ON (no thread flags, no --no-spin)
- **B**: intra 1, inter 1, spinning OFF (--intra-op-threads 1 --inter-op-threads 1 --no-spin)
- **C**: default threads, spinning OFF (--no-spin)
- **D**: intra 1, inter 1, spinning ON (--intra-op-threads 1 --inter-op-threads 1)

Run order: run01_A, run02_B, run03_C, run04_D, run05_B, run06_C, run07_D, run08_A, run09_C, run10_D, run11_A, run12_B

## detector: per run

| Order | Cfg | VIN p50 W | VIN peak W | CPU/SoC rail p50 W | Idle before run W / Tj C (harness 60 s) | Gate: VIN W / Tj C / settled / windows | Peak Tj C | p50 / p95 / p99 / max ms | Late slots / n_samples | OS threads det 30 s, 90 s; fc 30 s, 90 s | Finished UTC | Source |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | A | 46.582 | 48.432 | 32.628 | 15.904 / 38.25 | 16.090 / 38.343 / True / 1 | 54.781 | 0.0329 / 0.0372 / 0.0511 / 1.2711 | 91 / 120,001 | 29, 29, 29, 29 | 2026-09-16T05:43:57.417599+00:00 | `reports/thor_threads_isolation/run01_A.json: models[model=detector].tiers[target_rps=1000.0]` |
| 2 | B | 15.918 | 16.996 | 3.929 | 15.942 / 38.968 | 15.394 / 39.656 / True / 1 | 38.718 | 0.0215 / 0.0225 / 0.0289 / 0.3596 | 10 / 120,001 | 16, 16, 16, 16 | 2026-09-16T05:50:28.588390+00:00 | `reports/thor_threads_isolation/run02_B.json: models[model=detector].tiers[target_rps=1000.0]` |
| 3 | C | 15.714 | 17.616 | 3.929 | 15.552 / 36.937 | 16.178 / 37.156 / True / 1 | 36.875 | 0.0275 / 0.0286 / 0.0339 / 0.4338 | 12 / 120,001 | 30, 29, 29, 29 | 2026-09-16T05:57:00.049033+00:00 | `reports/thor_threads_isolation/run03_C.json: models[model=detector].tiers[target_rps=1000.0]` |
| 4 | D | 16.108 | 17.900 | 3.929 | 16.018 / 36.218 | 15.672 / 36.375 / True / 1 | 36.218 | 0.0213 / 0.0219 / 0.0262 / 0.4675 | 10 / 120,001 | 16, 16, 16, 16 | 2026-09-16T06:03:31.523500+00:00 | `reports/thor_threads_isolation/run04_D.json: models[model=detector].tiers[target_rps=1000.0]` |
| 5 | B | 15.770 | 16.930 | 3.929 | 15.950 / 35.656 | 15.496 / 35.781 / True / 1 | 35.718 | 0.0215 / 0.0223 / 0.0269 / 0.9498 | 5 / 120,001 | 17, 16, 16, 16 | 2026-09-16T06:10:02.944839+00:00 | `reports/thor_threads_isolation/run05_B.json: models[model=detector].tiers[target_rps=1000.0]` |
| 6 | C | 15.632 | 16.646 | 3.929 | 15.896 / 35.343 | 15.906 / 35.468 / True / 1 | 35.406 | 0.0276 / 0.0284 / 0.0324 / 0.9716 | 4 / 120,001 | 29, 29, 29, 29 | 2026-09-16T06:16:34.457917+00:00 | `reports/thor_threads_isolation/run06_C.json: models[model=detector].tiers[target_rps=1000.0]` |
| 7 | D | 15.654 | 17.056 | 3.536 | 15.684 / 35.093 | 15.578 / 35.156 / True / 1 | 35.187 | 0.0216 / 0.0226 / 0.0285 / 0.9702 | 22 / 120,001 | 16, 16, 16, 16 | 2026-09-16T06:23:05.912263+00:00 | `reports/thor_threads_isolation/run07_D.json: models[model=detector].tiers[target_rps=1000.0]` |
| 8 | A | 46.336 | 46.882 | 32.628 | 15.882 / 34.875 | 15.966 / 35.031 / True / 1 | 51.25 | 0.0332 / 0.0376 / 0.0514 / 3.3622 | 222 / 120,001 | 29, 29, 29, 29 | 2026-09-16T06:29:37.457777+00:00 | `reports/thor_threads_isolation/run08_A.json: models[model=detector].tiers[target_rps=1000.0]` |
| 9 | C | 15.944 | 16.840 | 3.929 | 15.924 / 36.062 | 15.624 / 36.531 / True / 1 | 35.937 | 0.0275 / 0.0287 / 0.0350 / 0.4925 | 2 / 120,001 | 29, 29, 29, 29 | 2026-09-16T06:36:08.601709+00:00 | `reports/thor_threads_isolation/run09_C.json: models[model=detector].tiers[target_rps=1000.0]` |
| 10 | D | 15.564 | 17.284 | 3.538 | 15.864 / 34.937 | 15.986 / 35.093 / True / 1 | 34.937 | 0.0216 / 0.0225 / 0.0274 / 0.4622 | 3 / 120,001 | 16, 16, 16, 16 | 2026-09-16T06:42:39.996930+00:00 | `reports/thor_threads_isolation/run10_D.json: models[model=detector].tiers[target_rps=1000.0]` |
| 11 | A | 46.196 | 47.738 | 32.628 | 15.906 / 34.531 | 15.850 / 34.687 / True / 1 | 50.843 | 0.0331 / 0.0374 / 0.0525 / 2.0438 | 66 / 120,001 | 30, 29, 29, 29 | 2026-09-16T06:49:11.469375+00:00 | `reports/thor_threads_isolation/run11_A.json: models[model=detector].tiers[target_rps=1000.0]` |
| 12 | B | 15.568 | 16.812 | 3.929 | 15.780 / 35.75 | 15.722 / 36.25 / True / 1 | 35.625 | 0.0216 / 0.0230 / 0.0309 / 0.4449 | 10 / 120,001 | 16, 16, 16, 16 | 2026-09-16T06:55:42.611463+00:00 | `reports/thor_threads_isolation/run12_B.json: models[model=detector].tiers[target_rps=1000.0]` |

## detector: analysis (VIN p50 at 1000 events/s)

| Cfg | n | Median W | Min W | Max W |
|---|---|---|---|---|
| A | 3 | 46.336 | 46.196 | 46.582 |
| B | 3 | 15.770 | 15.568 | 15.918 |
| C | 3 | 15.714 | 15.632 | 15.944 |
| D | 3 | 15.654 | 15.564 | 16.108 |

| Comparison | From medians W | From individual runs W | Ranges overlap |
|---|---|---|---|
| Spinning effect, default threads: A minus C | 30.622 | 30.252 to 30.950 | no |
| Spinning effect, one thread: D minus B | -0.116 | -0.354 to 0.540 | yes |
| Thread-count effect, spin on: A minus D | 30.682 | 30.088 to 31.018 | no |
| Thread-count effect, spin off: C minus B | -0.056 | -0.286 to 0.376 | yes |

Interaction (A minus C) minus (D minus B): 30.738 W from medians; 29.712 to 31.304 W from individual runs.

Gap A minus B from medians: 30.566 W.

**Decision rule outcome (detector): neither factor meets the 'accounts for the gap' rule (effect present at both levels of the other factor with separated ranges). spinning effect at default threads (A minus C): present (30.622 W from medians, ranges separated); spinning effect at one thread (D minus B): inconclusive, ranges overlap (-0.116 W from medians); thread-count effect with spinning on (A minus D): present (30.682 W from medians, ranges separated); thread-count effect with spinning off (C minus B): inconclusive, ranges overlap (-0.056 W from medians); gap A minus B from medians 30.566 W. C and D both sit near B rather than near A, so the 'requires both settings together' rule does not apply either: in these runs either change alone brought power to the B level.**

Did max latency follow the same pattern as power: yes: every A run's max latency (1.2711 ms lowest) exceeds every B, C and D run's max (0.9716 ms highest); B, C and D overlap each other.

Max latency per configuration (ms): A: 1.2711, 3.3622, 2.0438; B: 0.3596, 0.9498, 0.4449; C: 0.4338, 0.9716, 0.4925; D: 0.4675, 0.9702, 0.4622.

## forecaster: per run

| Order | Cfg | VIN p50 W | VIN peak W | CPU/SoC rail p50 W | Idle before run W / Tj C (harness 60 s) | Gate: VIN W / Tj C / settled / windows | Peak Tj C | p50 / p95 / p99 / max ms | Late slots / n_samples | OS threads det 30 s, 90 s; fc 30 s, 90 s | Finished UTC | Source |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | A | 15.998 | 17.234 | 3.929 | 15.904 / 38.25 | 16.090 / 38.343 / True / 1 | 46.562 | 0.0371 / 0.0381 / 0.0406 / 6.0776 | 12 / 120,001 | 29, 29, 29, 29 | 2026-09-16T05:43:57.417599+00:00 | `reports/thor_threads_isolation/run01_A.json: models[model=forecaster].tiers[target_rps=1000.0]` |
| 2 | B | 15.960 | 17.034 | 3.929 | 15.942 / 38.968 | 15.394 / 39.656 / True / 1 | 37.968 | 0.0363 / 0.0373 / 0.0404 / 3.6221 | 15 / 120,001 | 16, 16, 16, 16 | 2026-09-16T05:50:28.588390+00:00 | `reports/thor_threads_isolation/run02_B.json: models[model=forecaster].tiers[target_rps=1000.0]` |
| 3 | C | 15.532 | 16.940 | 3.929 | 15.552 / 36.937 | 16.178 / 37.156 / True / 1 | 36.625 | 0.0368 / 0.0378 / 0.0398 / 2.0934 | 2 / 120,001 | 30, 29, 29, 29 | 2026-09-16T05:57:00.049033+00:00 | `reports/thor_threads_isolation/run03_C.json: models[model=forecaster].tiers[target_rps=1000.0]` |
| 4 | D | 15.594 | 16.658 | 3.929 | 16.018 / 36.218 | 15.672 / 36.375 / True / 1 | 36.062 | 0.0362 / 0.0372 / 0.0402 / 2.1171 | 11 / 120,001 | 16, 16, 16, 16 | 2026-09-16T06:03:31.523500+00:00 | `reports/thor_threads_isolation/run04_D.json: models[model=forecaster].tiers[target_rps=1000.0]` |
| 5 | B | 15.872 | 17.834 | 3.929 | 15.950 / 35.656 | 15.496 / 35.781 / True / 1 | 35.625 | 0.0360 / 0.0372 / 0.0411 / 2.1870 | 12 / 120,001 | 17, 16, 16, 16 | 2026-09-16T06:10:02.944839+00:00 | `reports/thor_threads_isolation/run05_B.json: models[model=forecaster].tiers[target_rps=1000.0]` |
| 6 | C | 15.490 | 16.512 | 3.538 | 15.896 / 35.343 | 15.906 / 35.468 / True / 1 | 35.343 | 0.0370 / 0.0381 / 0.0415 / 2.1909 | 5 / 120,001 | 29, 29, 29, 29 | 2026-09-16T06:16:34.457917+00:00 | `reports/thor_threads_isolation/run06_C.json: models[model=forecaster].tiers[target_rps=1000.0]` |
| 7 | D | 15.560 | 16.622 | 3.536 | 15.684 / 35.093 | 15.578 / 35.156 / True / 1 | 35.125 | 0.0364 / 0.0376 / 0.0415 / 2.0909 | 5 / 120,001 | 16, 16, 16, 16 | 2026-09-16T06:23:05.912263+00:00 | `reports/thor_threads_isolation/run07_D.json: models[model=forecaster].tiers[target_rps=1000.0]` |
| 8 | A | 15.726 | 16.812 | 3.929 | 15.882 / 34.875 | 15.966 / 35.031 / True / 1 | 42.843 | 0.0371 / 0.0438 / 0.0465 / 2.1090 | 10 / 120,001 | 29, 29, 29, 29 | 2026-09-16T06:29:37.457777+00:00 | `reports/thor_threads_isolation/run08_A.json: models[model=forecaster].tiers[target_rps=1000.0]` |
| 9 | C | 15.644 | 16.610 | 3.929 | 15.924 / 36.062 | 15.624 / 36.531 / True / 1 | 35.531 | 0.0368 / 0.0379 / 0.0414 / 2.1163 | 9 / 120,001 | 29, 29, 29, 29 | 2026-09-16T06:36:08.601709+00:00 | `reports/thor_threads_isolation/run09_C.json: models[model=forecaster].tiers[target_rps=1000.0]` |
| 10 | D | 15.476 | 16.636 | 3.538 | 15.864 / 34.937 | 15.986 / 35.093 / True / 1 | 34.843 | 0.0363 / 0.0373 / 0.0403 / 2.2175 | 5 / 120,001 | 16, 16, 16, 16 | 2026-09-16T06:42:39.996930+00:00 | `reports/thor_threads_isolation/run10_D.json: models[model=forecaster].tiers[target_rps=1000.0]` |
| 11 | A | 15.998 | 17.144 | 3.929 | 15.906 / 34.531 | 15.850 / 34.687 / True / 1 | 42.406 | 0.0363 / 0.0374 / 0.0408 / 2.1257 | 11 / 120,001 | 30, 29, 29, 29 | 2026-09-16T06:49:11.469375+00:00 | `reports/thor_threads_isolation/run11_A.json: models[model=forecaster].tiers[target_rps=1000.0]` |
| 12 | B | 15.808 | 16.970 | 3.929 | 15.780 / 35.75 | 15.722 / 36.25 / True / 1 | 35.187 | 0.0359 / 0.0374 / 0.0433 / 2.0845 | 10 / 120,001 | 16, 16, 16, 16 | 2026-09-16T06:55:42.611463+00:00 | `reports/thor_threads_isolation/run12_B.json: models[model=forecaster].tiers[target_rps=1000.0]` |

## forecaster: analysis (VIN p50 at 1000 events/s)

| Cfg | n | Median W | Min W | Max W |
|---|---|---|---|---|
| A | 3 | 15.998 | 15.726 | 15.998 |
| B | 3 | 15.872 | 15.808 | 15.960 |
| C | 3 | 15.532 | 15.490 | 15.644 |
| D | 3 | 15.560 | 15.476 | 15.594 |

| Comparison | From medians W | From individual runs W | Ranges overlap |
|---|---|---|---|
| Spinning effect, default threads: A minus C | 0.466 | 0.082 to 0.508 | no |
| Spinning effect, one thread: D minus B | -0.312 | -0.484 to -0.214 | no |
| Thread-count effect, spin on: A minus D | 0.438 | 0.132 to 0.522 | no |
| Thread-count effect, spin off: C minus B | -0.340 | -0.470 to -0.164 | no |

Interaction (A minus C) minus (D minus B): 0.778 W from medians; 0.296 to 0.992 W from individual runs.

Gap A minus B from medians: 0.126 W.

**Decision rule outcome (forecaster): neither factor meets the 'accounts for the gap' rule (effect present at both levels of the other factor with separated ranges). spinning effect at default threads (A minus C): present (0.466 W from medians, ranges separated); spinning effect at one thread (D minus B): ranges separated but the difference is negative (-0.312 W from medians); thread-count effect with spinning on (A minus D): present (0.438 W from medians, ranges separated); thread-count effect with spinning off (C minus B): ranges separated but the difference is negative (-0.340 W from medians); gap A minus B from medians 0.126 W.**

Did max latency follow the same pattern as power: no clean separation: the lowest A max (2.1090 ms) is below the highest max among B, C and D (3.6221 ms).

Max latency per configuration (ms): A: 6.0776, 2.1090, 2.1257; B: 3.6221, 2.1870, 2.0845; C: 2.0934, 2.1909, 2.1163; D: 2.1171, 2.0909, 2.2175.

## What else was running

- run01_A (`reports/thor_threads_isolation/system_snapshot_run01_A.txt`): 2026-09-16T05:37:57Z |  00:37:57 up 38 days,  8:00,  5 users,  load average: 0.09, 0.16, 0.17 | containers: 0 | gdm: inactive |     PID %CPU %MEM COMMAND | 3786382  100  0.0 ps | 3759295 43.5  0.0 kworker/u28:0-ext4-rsv-conversion | 3764747 21.2  0.0 kworker/u28:2-dce-async-ipc-wq | 3786226  2.1  0.0 kworker/u28:1-ext4-rsv-conversion |    1862  0.3  0.0 disp_eng_share_thread | harness load average 1 min at start: 0.09375
- run02_B (`reports/thor_threads_isolation/system_snapshot_run02_B.txt`): 2026-09-16T05:44:28Z |  00:44:28 up 38 days,  8:07,  6 users,  load average: 0.62, 2.32, 1.43 | containers: 0 | gdm: inactive |     PID %CPU %MEM COMMAND | 3787548  100  0.0 ps | 3759295 43.4  0.0 kworker/u28:0-ext4-rsv-conversion | 3786226  0.5  0.0 kworker/u28:1-ext4-rsv-conversion |    1862  0.3  0.0 disp_eng_share_thread | 3692374  0.2  0.0 (udev-worker) | harness load average 1 min at start: 0.625
- run03_C (`reports/thor_threads_isolation/system_snapshot_run03_C.txt`): 2026-09-16T05:50:59Z |  00:50:59 up 38 days,  8:13,  6 users,  load average: 0.14, 0.75, 0.99 | containers: 0 | gdm: inactive |     PID %CPU %MEM COMMAND | 3759295 43.3  0.0 kworker/u28:0-ext4-rsv-conversion |    1862  0.3  0.0 disp_eng_share_thread | 3786226  0.3  0.0 kworker/u28:1-ext4-rsv-conversion | 3692374  0.2  0.0 (udev-worker) |    2392  0.1  0.0 nv_queue | harness load average 1 min at start: 0.14453125
- run04_D (`reports/thor_threads_isolation/system_snapshot_run04_D.txt`): 2026-09-16T05:57:31Z |  00:57:31 up 38 days,  8:20,  6 users,  load average: 0.14, 0.32, 0.70 | containers: 0 | gdm: inactive |     PID %CPU %MEM COMMAND | 3759295 43.1  0.0 kworker/u28:0-ext4-rsv-conversion |    1862  0.3  0.0 disp_eng_share_thread | 3692374  0.2  0.0 (udev-worker) | 3786226  0.2  0.0 kworker/u28:1-ext4-rsv-conversion |    2392  0.1  0.0 nv_queue | harness load average 1 min at start: 0.13818359375
- run05_B (`reports/thor_threads_isolation/system_snapshot_run05_B.txt`): 2026-09-16T06:04:02Z |  01:04:02 up 38 days,  8:26,  6 users,  load average: 0.10, 0.20, 0.51 | containers: 0 | gdm: inactive |     PID %CPU %MEM COMMAND | 3759295 43.0  0.0 kworker/u28:0-ext4-rsv-conversion |    1862  0.3  0.0 disp_eng_share_thread | 3692374  0.2  0.0 (udev-worker) | 3786226  0.1  0.0 kworker/u28:1-ext4-rsv-conversion |    2392  0.1  0.0 nv_queue | harness load average 1 min at start: 0.0986328125
- run06_C (`reports/thor_threads_isolation/system_snapshot_run06_C.txt`): 2026-09-16T06:10:34Z |  01:10:34 up 38 days,  8:33,  6 users,  load average: 0.10, 0.15, 0.38 | containers: 0 | gdm: inactive |     PID %CPU %MEM COMMAND | 3792232  100  0.0 ps | 3759295 42.9  0.0 kworker/u28:0-ext4-rsv-conversion |    1862  0.3  0.0 disp_eng_share_thread | 3692374  0.2  0.0 (udev-worker) |    2392  0.1  0.0 nv_queue | harness load average 1 min at start: 0.103515625
- run07_D (`reports/thor_threads_isolation/system_snapshot_run07_D.txt`): 2026-09-16T06:17:05Z |  01:17:05 up 38 days,  8:39,  6 users,  load average: 0.15, 0.17, 0.31 | containers: 0 | gdm: inactive |     PID %CPU %MEM COMMAND | 3759295 42.8  0.0 kworker/u28:0-ext4-rsv-conversion |    1862  0.3  0.0 disp_eng_share_thread | 3692374  0.2  0.0 (udev-worker) |    2392  0.1  0.0 nv_queue | 3516574  0.1  0.0 systemd-udevd | harness load average 1 min at start: 0.1494140625
- run08_A (`reports/thor_threads_isolation/system_snapshot_run08_A.txt`): 2026-09-16T06:23:37Z |  01:23:37 up 38 days,  8:46,  6 users,  load average: 0.14, 0.19, 0.26 | containers: 0 | gdm: inactive |     PID %CPU %MEM COMMAND | 3794722  100  0.0 ps | 3759295 42.8  0.0 kworker/u28:0-ext4-rsv-conversion |    1862  0.3  0.0 disp_eng_share_thread | 3692374  0.2  0.0 (udev-worker) |    2392  0.1  0.0 nv_queue | harness load average 1 min at start: 0.138671875
- run09_C (`reports/thor_threads_isolation/system_snapshot_run09_C.txt`): 2026-09-16T06:30:08Z |  01:30:08 up 38 days,  8:53,  6 users,  load average: 0.66, 2.40, 1.54 | containers: 0 | gdm: inactive |     PID %CPU %MEM COMMAND | 3795895  100  0.0 ps | 3759295 42.7  0.0 kworker/u28:0-ext4-rsv-conversion |    1862  0.3  0.0 disp_eng_share_thread | 3692374  0.2  0.0 (udev-worker) |    2392  0.1  0.0 nv_queue | harness load average 1 min at start: 0.6552734375
- run10_D (`reports/thor_threads_isolation/system_snapshot_run10_D.txt`): 2026-09-16T06:36:39Z |  01:36:39 up 38 days,  8:59,  6 users,  load average: 0.21, 0.79, 1.06 | containers: 0 | gdm: inactive |     PID %CPU %MEM COMMAND | 3797055  100  0.0 ps | 3759295 42.6  0.0 kworker/u28:0-ext4-rsv-conversion |    1862  0.3  0.0 disp_eng_share_thread | 3692374  0.2  0.0 (udev-worker) |    2392  0.1  0.0 nv_queue | harness load average 1 min at start: 0.20556640625
- run11_A (`reports/thor_threads_isolation/system_snapshot_run11_A.txt`): 2026-09-16T06:43:11Z |  01:43:11 up 38 days,  9:06,  6 users,  load average: 0.26, 0.37, 0.76 | containers: 0 | gdm: inactive |     PID %CPU %MEM COMMAND | 3759295 42.5  0.0 kworker/u28:0-ext4-rsv-conversion |    1862  0.3  0.0 disp_eng_share_thread | 3692374  0.2  0.0 (udev-worker) |    2392  0.1  0.0 nv_queue | 3516574  0.1  0.0 systemd-udevd | harness load average 1 min at start: 0.25537109375
- run12_B (`reports/thor_threads_isolation/system_snapshot_run12_B.txt`): 2026-09-16T06:49:42Z |  01:49:42 up 38 days,  9:12,  6 users,  load average: 0.50, 2.34, 1.81 | containers: 0 | gdm: inactive |     PID %CPU %MEM COMMAND | 3799417  100  0.0 ps | 3759295 42.4  0.0 kworker/u28:0-ext4-rsv-conversion |    1862  0.3  0.0 disp_eng_share_thread | 3692374  0.2  0.0 (udev-worker) |    2392  0.1  0.0 nv_queue | harness load average 1 min at start: 0.49951171875

`ps` percentages are lifetime averages per process.

