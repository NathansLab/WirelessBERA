# ECG with and without driven right leg — 2026-10-16

Four 60 s recordings of a single-lead chest ECG on the author, to see what the
driven-right-leg (DRL) loop does to mains interference.

## Setup

| | |
|---|---|
| Board | Wireless BERA v1.0, firmware 2.0.0, LTC6373 fixed at G = 16 (R35–R37 not fitted) |
| Supply | battery; data streamed over Wi-Fi, laptop on battery |
| Acquisition | 48 kHz, block mean over 48 samples → **1 kHz**, 16-bit WebSocket scope stream |
| Electrodes | Philips 40493 foam electrodes, alligator clips on the snaps |
| Electrode+ (grey) | left lower rib cage |
| Electrode− (yellow) | below the right clavicle |
| DRL (green) | right lower rib cage (see per-recording notes) |

| File | DRL connection |
|---|---|
| `1_no_drl.csv` | green clip removed from its electrode — DRL loop open |
| `2_drl_hand.csv` | green clip held in the right hand instead of on the electrode |
| `3_drl_chest.csv` | green clip on the right lower rib electrode |
| `4_drl_chest_repeat.csv` | as 3, repeated a few minutes later (gel settled longer) |
| `5_apple_watch_parallel.csv` | 75 s, recorded in parallel with a 30 s Apple Watch ECG (lead I, started at 32.5 s); finger on the watch crown raised mains pickup to ~8.6 mVrms |
| `6_eeg_attempt_electrode_off.npz` | failed 70 s head EEG attempt at 1 kHz: an electrode came off after ~10 s (keys `ch1`, `ch2` in volts at the codec, `ch2_rti`, `fs`) |

Figures: `ecg_drl_comparison.png` (raw/filtered and spectra), `beat_morphology.png`
(averaged beat against a typical lead-II beat — PR 153–157 ms, QRS 90 ms, QTc
375–391 ms, all normal; the codec's default 0.96 Hz high-pass filter flattens the
T wave and was removed numerically), `apple_watch_comparison.png` (RR intervals
agree beat for beat, 0.2 ± 1.8 ms).

## File format

CSV with a 3-line `#` header, then `t_s, ch1_mic_counts, ch2_bio_counts`.
Counts are the int16 values exactly as streamed by the device.

- Volts at the codec input: `counts / 32768 × 2.8284` (full scale = 2 Vrms sine).
- Referred to the electrodes: divide by **16**, and **negate** — channel 2 is
  polarity-inverted on the board (LTC6373 OUT− drives TAC5212 IN2P).
- `ch1` is the headset electret microphone on the MK1 test points; ignore it here.
- The 1 kHz stream is a block mean, not an anti-aliased decimation.

## Results

From `../tools/analyze_ecg.py`, all values referred to the electrodes:

| | 50 Hz | 150 Hz | Heart rate | QRS (median) |
|---|---|---|---|---|
| No DRL | 1556 µVrms | 573 µVrms | 67 bpm | 1.70 mV |
| DRL via hand | 191 µVrms (−18 dB) | 43 µVrms (−22 dB) | 70 bpm | 1.69 mV |
| DRL via chest electrode | 498 µVrms (−10 dB) | 292 µVrms (−6 dB) | 67 bpm | 1.63 mV |
| DRL via chest, repeat | 383 µVrms (−12 dB) | 226 µVrms (−8 dB) | 66 bpm | 1.79 mV |

- The QRS complex is clearly resolved in all four recordings; no clipping, no
  lost packets.
- The DRL loop works: closing it lowers mains pickup by 10–18 dB.
- Holding the DRL lead in the hand gave the strongest mains reduction, but the
  forearm muscles add broadband EMG (the floor above 60 Hz rises roughly 3×).
  The chest electrode keeps the floor at the no-DRL level.
- Why the chest electrode suppresses less than the hand is open. Repeating
  the chest measurement after the gel had settled longer improved it only a
  little (−10 → −12 dB), so contact impedance alone does not explain the gap.

![ECG and spectra](ecg_drl_comparison.png)

## Reproduce

```bash
python3 ../tools/analyze_ecg.py .
```

`../tools/record_stream.py` is the recorder that produced the data (WebSocket
client; edit `HOST` for the board's address).
