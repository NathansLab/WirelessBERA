# Measurements

In-vivo recordings with the Wireless BERA v1.0 prototype, all on the author,
board on battery, laptop off mains.

| Folder | Content |
|---|---|
| [`2026-10-16_ecg_drl/`](2026-10-16_ecg_drl/) | chest ECG with and without driven right leg, Apple Watch comparison, beat morphology |
| [`2026-10-16_bera/`](2026-10-16_bera/) | first click ABR: four runs incl. sham and earbud-out controls, electrode photo |

## Tools

All scripts run with Python 3 + numpy, scipy, matplotlib (`websocket-client`
for recording, `pymupdf` for reading the Apple Watch PDF export).

| Script | Purpose |
|---|---|
| `record_stream.py` | record the WebSocket scope stream (1 kHz ECG) |
| `analyze_ecg.py`, `ecg_report.py` | ECG/DRL levels and an 8-page ECG PDF report |
| `bera_record.py` | record a BERA run on a gap-aware frame grid (24 kHz) |
| `bera_split.py` | split a continuous multi-block run by its log |
| `bera_average.py` | quick single-run ABR average |
| `bera_analysis.py` | ABR statistics: permutation test, Fsp, polarities, wave V bootstrap |
| `analysis_eeg_eog_emg.py` | EEG bands, blinks, EMG and what drives the sweep noise |
| `analysis_heart_resp.py` | heart rate, HRV, respiration; ECG detection limit at the head |
| `analysis_tech_artefacts.py` | Wi-Fi, mains, packet loss, battery, quantisation, stimulus artefact |
| `analysis_mic_audio.py` | headset microphone: click monitor, events, audio excerpts |
| `bera_full_report.py` | collects all analysis figures into one PDF |
| `report_figures.py` | the figures of the report in `../report/figures/` |

The `analysis_*.py` scripts write their figures to `<folder>/analysis/`, which is
not tracked in git.
