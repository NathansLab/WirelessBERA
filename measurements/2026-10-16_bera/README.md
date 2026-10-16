# First click BERA — 2026-10-16

First auditory brainstem response attempt with the Wireless BERA board, on the
author, left ear.

## Setup

| | |
|---|---|
| Board | Wireless BERA v1.0, firmware 2.0.0, LTC6373 fixed at G = 16, battery (3.42 → 3.39 V) |
| Codec | TAC5212 ADC high-pass switched off for these runs (P0_R114 = 0x08, set over `/api/codec/reg`) |
| Electrode+ (grey) | high forehead, at the hairline |
| Electrode− (yellow) | left mastoid |
| DRL (green) | right mastoid |
| Photo | [`electrode_placement_mastoid.jpg`](electrode_placement_mastoid.jpg) — Electrode− on the left mastoid: yellow lead wrapped around the snap, earbud cable (black) running right past the electrode |
| Stimulus | rectangular click, 105 µs, 21.108 /s (2274 frames at 48 kHz), alternating polarity, DAC ch 2 → left earbud only |
| Level | uncalibrated: run 1 amplitude 0.10 ("loud but comfortable"), run 2 amplitude 0.05 (−6 dB) |
| Acquisition | 48 kHz / 2 → 24 kHz, Wi-Fi WebSocket stream, ~1.1 % packets lost (gaps kept as gaps) |

## Files

| File | Content |
|---|---|
| `0_rest_no_stimulus.npz` | 8 s, stimulus off, seated — noise check |
| `1_click_amp0.10_21Hz.npz` | 205 s, amplitude 0.10, seated |
| `2_click_amp0.05_21Hz.npz` | 420 s, amplitude 0.05, lying down |
| `bera_analysis.png` | output of `../tools/bera_analysis.py` |

Each `.npz` holds `ch1` (headset mic) and `ch2` (biosignal) as int16 counts on a
continuous frame grid, `valid` (False where a packet was lost), `fs`, `decim`,
and the stimulus settings as JSON. In `2_click_amp0.05_21Hz.npz` the microphone
channel `ch1` is zeroed for the first 20 s (`ch1_muted_s`) for privacy; `ch2` is untouched. µV at the electrodes = −ch2 / 32768 × 2.8284 / 16 × 1e6.

## Results

Rest check: 50 Hz only 7 µVrms at the electrodes with DRL (chest without DRL: 1556 µVrms).

Analysis chain: 100–1500 Hz + 50 Hz comb on the continuous record, t = 0 at the
alternating stimulus artefact, ±25 µV rejection in whole ± pairs, 64-sweep
blocks with SD > 1.5 × median dropped.

| | Run 1 (0.10) | Run 2 (0.05) | Both |
|---|---|---|---|
| Sweeps kept | 3904 / 4325 | 5504 / 8864 | 9408 |
| Sweep SD | 2.9–4.1 µV | 1.9–2.2 µV | |
| Permutation p (1–10 ms) | 0.24 | **0.001** | **0.001** |
| Fsp | 1.3 | **6.1** | 3.6 |
| Wave V candidate | 5.9 ms, 126 nV | **6.1 ms (95 % CI 5.8–6.3), 164 nV** | 6.0 ms, 142 nV |

- Run 2 shows a stimulus-locked positive peak at 6.1 ms. Both polarities show it,
  so it is not cochlear microphonic or stimulus artefact, and its latency fits
  wave V at a moderate click level.
- Run 1 has the peak at the same place but does not reach significance: the
  subject was seated and the sweep noise was ~50 % higher.
- Run 2 lost its first ~80 s to restlessness (sweep SD 6–8 µV) before settling at 2 µV.

### Runs 3 and 4 (after midnight, battery 3.35 → 3.23 V)

| File | Content |
|---|---|
| `3_click_sham_toneburst_continuous.npz` + `.log` | one continuous 690 s stream; the log has the Unix time of each block switch: A click 0.035 left (246 s), B sham = same click to the open right channel (201 s), C 2 kHz tone burst, 4 ms Blackman, amplitude 0.01, left (233 s). Split with `../tools/bera_split.py`, which keeps the click phase of block A for all blocks. |
| `4_sham_click_amp0.035_earbud_out.npz` + `.log` | 240 s, click 0.035 on the left earbud, earbud taken out of the ear and placed next to the head |
| `3_blocks_analysis.png`, `4_control_vs_run2.png` | analyses |

| | Sweep SD | p | Fsp | Note |
|---|---|---|---|---|
| 3A click 0.035 | 4.7–7.0 µV | 0.89 | 0.4 | no response — noise 2–3× higher than run 2, level 3 dB lower |
| 3B sham (open channel) | 4.1–5.9 µV | 0.76 | 0.6 | flat, artefact 0.18 µV |
| 3C tone burst 2 kHz | 3.2–4.7 µV | 0.12 | 1.7 | not significant |
| 4 earbud out of ear | 3.5–5.5 µV | 0.44 | 0.9 | flat at 6 ms; electrical click artefact still 0.76 µV |

- The earbud-out control shows the electrical artefact at 0 ms but nothing at
  6 ms, which argues against a stimulus-locked artefact as the source of the
  run-2 peak. With its higher noise (residual ~65 nV) a 164 nV wave would only be
  ~2.5 σ, so the control is supportive, not conclusive.
- Runs 3/4 were much noisier than run 2 (electrodes ageing after > 1 h, or a
  restless subject); the sweep noise decides everything here.
- Next: fresh electrodes and skin prep, charged battery, lying relaxed; a
  level series (0.1 / 0.05 / 0.025) with an interleaved earbud-out control, and
  firmware click-onset markers in the stream header.

## Reproduce

```bash
python3 ../tools/bera_analysis.py bera_analysis.png "Lauf 1 (0,10)=1_click_amp0.10_21Hz.npz" "Lauf 2 (0,05)=2_click_amp0.05_21Hz.npz"
```

`../tools/bera_record.py` recorded the runs; `../tools/bera_average.py` is the quick single-run average.

`bera_mains_strategy.png` is the planning simulation behind the 21.1/s click
rate: mains residual in the average for a coherent (20/s, 25/s) against a
non-coherent rate, with and without the harmonic comb.

The `analysis_*.py` scripts in `../tools/` (EEG/EOG/EMG, heart/respiration,
technical artefacts, microphone) write about 50 further figures to `analysis/`
(not tracked); `../tools/bera_full_report.py` collects them into one PDF.
