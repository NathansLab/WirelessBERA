"""Average a BERA run recorded with bera_record.py.

Usage: bera_average.py <run.npz> <out.png> [reject_uV]

Order: continuous data -> band-pass 100-1500 Hz -> 50 Hz harmonic comb ->
epochs around each click -> reject whole +/- pairs -> average.
The click grid is one click every L = floor(48000 / rate) raw frames; its
phase D is the peak of the polarity-alternating stimulus artefact on CH2,
so t = 0 is the electrical click.
"""
import json
import sys

import numpy as np
import scipy.signal as ss
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

GAIN = 16.0
FS_VPEAK = 2.0 * np.sqrt(2)

src, out = sys.argv[1], sys.argv[2]
reject = float(sys.argv[3]) if len(sys.argv) > 3 else 30.0
d = np.load(src)
fs, decim = float(d["fs"]), int(d["decim"])
stim = json.loads(str(d["stimulus"]))
valid = d["valid"]
uv = -d["ch2"].astype(float) / 32768 * FS_VPEAK / GAIN * 1e6     # µV at the electrodes
mic = d["ch1"].astype(float)
uv[~valid] = 0.0
mic[~valid] = 0.0

L_raw = int(48000 / stim["rate_hz"])           # firmware: (uint32_t)(fs / rate)
L = L_raw / decim                              # clicks per decimated sample grid (may be fractional)


def fold(x):
    n = int(len(x) // L)
    idx = (np.arange(n)[:, None] * L + np.arange(int(L))[None, :]).astype(int)
    return x[idx].mean(axis=0)


# Click phase: the electrical stimulus artefact on CH2 flips sign with the
# alternating polarity, so folding over two clicks and taking the difference
# of the halves isolates it from everything that does not alternate.
Li = int(round(L))
hp = ss.sosfiltfilt(ss.butter(4, 300, "hp", fs=fs, output="sos"), uv)
n2 = len(hp) // (2 * Li)
f2 = hp[:n2 * 2 * Li].reshape(n2, 2 * Li).mean(axis=0)
prof = np.abs(f2[:Li] - f2[Li:]) / 2
D = int(np.argmax(prof))                       # t = 0 at the artefact peak
print(f"L = {L_raw} raw frames ({48000 / L_raw:.3f} /s), D = {D} samples from the alternating "
      f"CH2 artefact ({prof.max():.2f} µV, peak/median {prof.max() / np.median(prof):.1f})")

# Mains frequency from the data, then band-pass + comb on the continuous record.
f, p = ss.welch(uv, fs, nperseg=int(fs * 8))
m = (f > 49.5) & (f < 50.5)
f0 = f[m][np.argmax(p[m])]
y = ss.sosfiltfilt(ss.butter(2, [100, 1500], "bp", fs=fs, output="sos"), uv)
for k in range(1, int(1500 // f0) + 2):
    fk = k * f0
    if fk < fs / 2 - 10:
        b, a = ss.iirnotch(fk, fk / 4.0, fs)
        y = ss.filtfilt(b, a, y)

pre, post = int(0.002 * fs), int(0.012 * fs)
onsets = (D + np.arange(int((len(y) - D - post) // L)) * L).astype(int)
onsets = onsets[onsets - pre >= 0]
good = np.array([valid[o - pre - int(0.01 * fs):o + post + int(0.01 * fs)].all() for o in onsets])
ep = np.stack([y[o - pre:o + post] for o in onsets])
amp = np.abs(ep[:, pre:]).max(axis=1)
ok = good & (amp < reject)
ok2 = ok.copy()                                # reject in +/- pairs
ok2[0::2] &= np.r_[ok[1::2], np.zeros(len(ok[0::2]) - len(ok[1::2]), bool)]
ok2[1::2] &= ok[0::2][:len(ok[1::2])]
sel = ep[ok2]
n = len(sel) - len(sel) % 2
sel = sel[:n]
avg = sel.mean(axis=0)
pm = (sel[0::2] - sel[1::2]).mean(axis=0) / 2 if n else avg * 0      # ± reference = noise
half_a, half_b = sel[: n // 2].mean(axis=0), sel[n // 2:].mean(axis=0)
t = (np.arange(-pre, post)) / fs * 1e3
sigma = np.std(ep[ok2][:, pre:]) if n else np.nan
noise = np.std(pm[pre:])
win = (t > 1) & (t < 10)
r_ab = np.corrcoef(half_a[win], half_b[win])[0, 1] if n > 10 else np.nan
print(f"f0 {f0:.3f} Hz, sweeps {len(onsets)}, valid {good.sum()}, accepted {n} "
      f"({100 * n / max(1, len(onsets)):.0f} %), sweep sigma {sigma:.2f} µV, "
      f"residual noise {noise * 1e3:.0f} nV, signal rms 1-10 ms {np.std(avg[win]) * 1e3:.0f} nV, "
      f"A/B corr {r_ab:.2f}")

fig, ax = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
ax[0].plot(t, avg, color="#2a78d6", lw=2, label=f"Mittel (N = {n})")
ax[0].plot(t, pm, color="#888888", lw=1, label="± Referenz (Restrauschen)")
ax[0].axvline(0, color="k", lw=0.6)
ax[0].set_ylabel("µV")
ax[0].legend(frameon=False, loc="upper right")
ax[0].set_title(f"BERA, Klick {48000 / L_raw:.2f}/s, Amplitude {stim['amplitude']}, "
                f"Polarität {stim['polarity']}, 100–1500 Hz + 50-Hz-Kamm", loc="left", fontsize=10)
ax[1].plot(t, half_a, color="#eb6834", lw=1.5, label="Hälfte A")
ax[1].plot(t, half_b, color="#1baf7a", lw=1.5, label="Hälfte B")
ax[1].axvline(0, color="k", lw=0.6)
ax[1].set_xlabel("Zeit nach Klick (ms)")
ax[1].set_ylabel("µV")
ax[1].legend(frameon=False, loc="upper right")
ax[1].set_title(f"Reproduzierbarkeit, Korrelation 1–10 ms: {r_ab:.2f}", loc="left", fontsize=10)
for a in ax:
    a.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(out, dpi=130)
print(out)
