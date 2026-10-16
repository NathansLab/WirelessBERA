"""Analyse the ECG/DRL recordings in measurements/2026-10-16_ecg_drl.

Usage: python3 analyze_ecg.py <recording dir>
Prints mains and band levels referred to the electrodes, beat count and heart
rate, and writes ecg_drl_comparison.png next to the data.
Needs numpy, scipy, matplotlib.
"""
import glob
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy import signal

FS_VPEAK = 2 * np.sqrt(2)   # TAC5212 full scale: 2 Vrms sine
GAIN = 16.0                 # LTC6373, fixed while R35-R37 are not fitted

folder = sys.argv[1]
files = sorted(glob.glob(os.path.join(folder, "*.csv")))
fig, ax = plt.subplots(len(files), 2, figsize=(13, 3.2 * len(files)), squeeze=False)

for i, fn in enumerate(files):
    with open(fn) as f:
        fs = float(f.readline().split("fs = ")[1].split()[0])
    t, _, c2 = np.loadtxt(fn, delimiter=",", comments="#", skiprows=4, unpack=True)
    # ch2 is polarity-inverted on the board (LTC6373 OUT- -> IN2P), so negate it.
    x = -(c2 / 32768.0 * FS_VPEAK) / GAIN
    x -= x.mean()

    f, P = signal.welch(x, fs, nperseg=int(fs * 4))
    df = f[1] - f[0]
    band = lambda lo, hi: np.sqrt(np.sum(P[(f >= lo) & (f < hi)]) * df) * 1e6

    b, a = signal.butter(2, [0.5, 40], "bandpass", fs=fs)
    bn, an = signal.iirnotch(50, 30, fs)
    y = signal.filtfilt(bn, an, signal.filtfilt(b, a, x))
    bq, aq = signal.butter(2, [5, 30], "bandpass", fs=fs)
    q = signal.filtfilt(bq, aq, x)
    pk, _ = signal.find_peaks(q, distance=int(0.4 * fs), height=np.percentile(q, 99) * 0.4)
    hr = 60 / np.median(np.diff(pk) / fs)
    name = os.path.basename(fn)[:-4]
    print(f"{name:12s} 50 Hz {band(49.5, 50.5):7.1f} uV  150 Hz {band(149.5, 150.5):6.1f} uV  "
          f"noise 60-90 Hz {band(60, 90) / np.sqrt(30):5.2f} uV/rtHz  "
          f"beats {len(pk)}  HR {hr:5.1f} bpm  QRS {np.median(y[pk]) * 1e3:4.2f} mV")

    m = (t > 20) & (t < 30)
    ax[i, 0].plot(t[m], x[m] * 1e3, lw=0.5, color="0.6", label="raw")
    ax[i, 0].plot(t[m], y[m] * 1e3, lw=0.8, color="C3", label="0.5-40 Hz, 50 Hz notch")
    ax[i, 0].set_title(f"{name}: {len(pk)} beats in {t[-1]:.0f} s, {hr:.0f} bpm")
    ax[i, 0].set_ylabel("mV at electrodes")
    ax[i, 0].legend(fontsize=7, loc="upper right")
    ax[i, 1].semilogy(f, np.sqrt(P) * 1e6, lw=0.7)
    ax[i, 1].set_xlim(0, 300)
    ax[i, 1].set_ylabel("µV/√Hz")
    ax[i, 1].grid(alpha=0.3)

ax[-1, 0].set_xlabel("time / s")
ax[-1, 1].set_xlabel("frequency / Hz")
plt.tight_layout()
plt.savefig(os.path.join(folder, "ecg_drl_comparison.png"), dpi=110)
