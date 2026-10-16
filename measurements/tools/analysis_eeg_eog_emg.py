"""EEG, eye (EOG) and muscle (EMG) content of the 2026-10-16 head recordings.

Usage: analysis_eeg_eog_emg.py            (paths are fixed to the 2026-10-16 runs)

Montage: Electrode+ high forehead (hairline), Electrode- left mastoid, DRL right
mastoid. One channel, so "EEG" here is a frontal-mastoid lead that is dominated
by frontal activity and the vertical EOG.

Chain:
  - µV at the electrodes, lost Wi-Fi packets linearly bridged (they are 5 ms
    each, 1 % of the samples) and excluded from every RMS/SD figure,
  - the stimulus-locked component (period = one +/- click pair, 2274 samples at
    24 kHz) is estimated per 30 s chunk and subtracted, so neither the click
    artefact nor its 10.55 Hz line family leaks into the EEG/EMG,
  - 250 Hz stream (resample_poly /96) for EEG (0.5-45 Hz) and EOG (0.1-10 Hz),
  - 6 kHz stream (/4) for EMG (30-300 Hz, 300-2000 Hz, 50 Hz comb removed) and
    for the BERA sweep-noise equivalent (100-1500 Hz + 50 Hz comb, SD over 64
    click periods = 3.03 s, i.e. the "64-sweep block SD" without rejection).
Figures go to ../2026-10-16_bera/analysis/eeg_*.png.
"""
import json
import os

import numpy as np
import scipy.signal as ss
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker
from matplotlib.patches import Patch
from matplotlib.lines import Line2D

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "2026-10-16_bera")
CHEST = os.path.join(HERE, "..", "2026-10-16_ecg_drl", "3_drl_chest.csv")
OUT = os.path.join(DATA, "analysis")
os.makedirs(OUT, exist_ok=True)

C = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
GREY, LGREY = "#7a7a7a", "#c8c8c8"
FS, FE, FM = 24000.0, 250.0, 6000.0
PAIR = 2274                                    # samples at 24 kHz per +/- click pair
UV = 2.8284 / 32768 / 16 * 1e6                 # µV per count (sign handled in load)
BANDS = [("δ 0,5–4 Hz", 0.5, 4), ("θ 4–8 Hz", 4, 8), ("α 8–13 Hz", 8, 13), ("β 13–30 Hz", 13, 30)]
plt.rcParams.update({"font.size": 9, "axes.titlesize": 10, "axes.titlelocation": "left",
                     "axes.spines.top": False, "axes.spines.right": False})

RUNS = {
    0: ("0_rest_no_stimulus", "Lauf 0 – Ruhe, sitzend"),
    1: ("1_click_amp0.10_21Hz", "Lauf 1 – Klick 0,10, sitzend"),
    2: ("2_click_amp0.05_21Hz", "Lauf 2 – Klick 0,05, liegend"),
    3: ("3_click_sham_toneburst_continuous", "Lauf 3 – A Klick / B Sham / C Tonburst, liegend"),
    4: ("4_sham_click_amp0.035_earbud_out", "Lauf 4 – Ohrhörer draußen, liegend"),
}


def save(fig, name):
    for tx in fig.findobj(matplotlib.text.Text):          # German decimal comma in titles, legends, notes
        tx.set_text(de(tx.get_text()))
    p = os.path.join(OUT, name)
    fig.savefig(p, dpi=130)
    plt.close(fig)
    print("  ->", name)


def read_log(path, t0):
    if not os.path.exists(path):
        return []
    out = []
    for l in open(path):
        if l[:1].isdigit() and "." in l.split()[0][:12]:
            try:
                out.append((float(l.split()[0]) - t0, " ".join(l.split()[1:])))
            except ValueError:
                pass
    return out


def load(n):
    base, label = RUNS[n]
    d = np.load(os.path.join(DATA, base + ".npz"))
    v = d["valid"].astype(bool)
    x = -d["ch2"].astype(float) * UV
    i = np.arange(len(x))
    x[~v] = np.interp(i[~v], i[v], x[v])
    stim = json.loads(str(d["stimulus"]))
    t0 = float(d["t_start"])
    if stim.get("type", 0) != 0:               # subtract stimulus-locked component per ~30 s chunk
        k = int(30 * FS) // PAIR * PAIR
        for a in range(0, len(x) - PAIR + 1, k):
            seg = x[a:a + k]
            m = len(seg) // PAIR
            if m < 50:
                continue
            tpl = seg[:m * PAIR].reshape(m, PAIR).mean(axis=0)
            tpl -= tpl.mean()
            x[a:a + k] -= np.resize(tpl, len(seg))
    e = ss.resample_poly(x, 1, 96)             # 250 Hz
    m6 = ss.resample_poly(x, 1, 4)             # 6 kHz
    v6 = ~np.convolve(~v, np.ones(80), "same").astype(bool)[::4][:len(m6)]   # gap +/- ~1.7 ms
    v6 = np.r_[v6, np.ones(len(m6) - len(v6), bool)]
    marks = read_log(os.path.join(DATA, base + ".log"), t0)
    return dict(n=n, label=label, e=e, m6=m6, v6=v6, t0=t0, stim=stim, marks=marks, dur=len(x) / FS)


def comb(y, fs, fmax):
    for k in range(1, int(fmax // 50) + 1):
        y = ss.filtfilt(*ss.iirnotch(50.0 * k, 50.0 * k / 4.0, fs), y)
    return y


def bp(y, lo, hi, fs, order=2):
    return ss.sosfiltfilt(ss.butter(order, [lo, hi], "bp", fs=fs, output="sos"), y)


def win_stat(y, ok, fs, w, fn):
    n = int(w * fs)
    nb = len(y) // n
    Y, O = y[:nb * n].reshape(nb, n), ok[:nb * n].reshape(nb, n)
    return (np.arange(nb) + 0.5) * w, np.array([fn(Y[i][O[i]]) if O[i].sum() > n // 4 else np.nan for i in range(nb)])


rms = lambda a: np.sqrt(np.mean(a ** 2))


def de(txt):
    """German decimal comma for numbers in titles."""
    import re
    return re.sub(r"(?<=\d)\.(?=\d)", ",", txt)


def smooth(a, k=5):
    return np.convolve(np.pad(a, k // 2, mode="edge"), np.ones(k) / k, "valid")

# ---------------------------------------------------------------- processing
R = {}
for n in RUNS:
    print("load", RUNS[n][0])
    r = load(n)
    e = r["e"]
    r["eeg"] = comb(bp(e, 0.5, 45, FE, 4), FE, 50)
    r["eog"] = bp(e, 0.3, 10, FE)                    # blinks
    r["slow"] = bp(e, 0.1, 1.0, FE)                  # slow eye movements
    r["eog5"] = bp(e, 0.1, 5.0, FE)                  # EOG activity (RMS)
    r["ctx"] = bp(e, 0.1, 30, FE)                    # display trace
    m6 = r["m6"]
    mc = comb(m6, FM, 2000)
    r["emg_lo"] = bp(mc, 30, 300, FM, 4)
    r["emg_hi"] = bp(mc, 300, 2000, FM, 4)
    r["bera"] = bp(mc, 100, 1500, FM, 2)
    r["mc"] = mc
    R[n] = r

# --- eye events
for r in R.values():
    eog, slow = r["eog"], r["slow"]
    pk, pr = ss.find_peaks(eog, prominence=50, width=(0.04 * FE, 0.8 * FE), rel_height=0.5)
    r["blinks"] = pk / FE
    r["blink_amp"] = pr["prominences"]
    sem = []
    for sgn in (1, -1):
        p, q = ss.find_peaks(sgn * slow, prominence=30, width=0.5 * FE)
        sem += [(t, sgn, a) for t, a in zip(p / FE, q["prominences"])]
    sem = [s for s in sorted(sem) if np.all(np.abs(r["blinks"] - s[0]) > 1.0)]
    r["sem"] = np.array([s[0] for s in sem])
    r["sem_amp"] = np.array([s[2] for s in sem])

# --- windowed measures (1 s for EMG, 3.03 s blocks for BERA sweep noise)
BLK = 64 * PAIR / 2 / FS                               # 64 sweeps = 3.032 s
for r in R.values():
    ok = r["v6"]
    r["t1"], r["emg_lo_rms"] = win_stat(r["emg_lo"], ok, FM, 1.0, rms)
    _, r["emg_hi_rms"] = win_stat(r["emg_hi"], ok, FM, 1.0, rms)
    r["tb"], r["sweep_sd"] = win_stat(r["bera"], ok, FM, BLK, np.std)
    _, r["blk_emg_lo"] = win_stat(r["emg_lo"], ok, FM, BLK, rms)
    _, r["blk_emg_hi"] = win_stat(r["emg_hi"], ok, FM, BLK, rms)
    okE = np.ones(len(r["eog5"]), bool)
    _, r["blk_eog"] = win_stat(r["eog5"], okE, FE, BLK, rms)
    _, r["blk_eeg"] = win_stat(bp(r["e"], 4, 30, FE), okE, FE, BLK, rms)

# --- spectral measures in 4 s windows, 2 s hop
for r in R.values():
    f, t, S = ss.spectrogram(r["eeg"], FE, nperseg=1000, noverlap=500, window="hann", scaling="density")
    r["sg"] = (f, t, S)
    band = lambda lo, hi: np.trapezoid(S[(f >= lo) & (f < hi)], f[(f >= lo) & (f < hi)], axis=0)
    r["bp_t"] = {k: band(lo, hi) for k, lo, hi in [("d", 0.5, 4), ("t", 4, 8), ("a", 8, 13), ("s", 11, 15), ("b", 15, 30), ("g", 30, 45)]}
    pa = S[(f >= 9.25) & (f <= 10.5)].mean(axis=0)
    pbg = np.r_[S[(f >= 6.5) & (f <= 8.5)], S[(f >= 11.5) & (f <= 14)]].mean(axis=0)
    r["alpha_idx"] = 10 * np.log10(pa / pbg)

# --- conditions for spectra
def seg(n, a, b, lab):
    return dict(n=n, a=a, b=b, label=lab)

m3 = {lab[:1]: t for t, lab in R[3]["marks"]}
COND = [seg(0, 0, 8, "Lauf 0 Ruhe sitzend (8 s)"),
        seg(1, 0, 205, "Lauf 1 sitzend"),
        seg(2, 0, 80, "Lauf 2, 0–80 s (unruhig)"),
        seg(2, 80, 420, "Lauf 2, 80–420 s (ruhig)"),
        seg(3, m3["A"] + 30, m3["B"], "Lauf 3 A Klick"),
        seg(3, m3["B"] + 3, m3["C"], "Lauf 3 B Sham"),
        seg(3, m3["C"] + 3, m3["e"], "Lauf 3 C Tonburst"),
        seg(4, 3, 240, "Lauf 4 Ohrhörer draußen")]
for c in COND:
    y = R[c["n"]]["eeg"][int(c["a"] * FE):int(c["b"] * FE)]
    c["f"], c["p"] = ss.welch(y, FE, nperseg=1000, average="median")
    f, p = c["f"], c["p"]
    c["bands"] = {k: np.trapezoid(p[(f >= lo) & (f < hi)], f[(f >= lo) & (f < hi)]) for k, lo, hi in BANDS}
    c["g"] = np.trapezoid(p[(f >= 30) & (f < 45)], f[(f >= 30) & (f < 45)])
    fh, ph = ss.welch(y, FE, nperseg=min(len(y), int(16 * FE)), average="median")
    c["fh"], c["ph"] = fh, ph
    w = (fh >= 8) & (fh <= 12.5)
    c["apk"] = fh[w][np.argmax(ph[w])]
    bgm = ((fh >= 6.5) & (fh <= 8.5)) | ((fh >= 11.5) & (fh <= 14))
    c["aex"] = 10 * np.log10(ph[w].max() / np.median(ph[bgm]))
    i = R[c["n"]]
    ia, ib = c["a"], c["b"]
    c["blink_pm"] = np.sum((i["blinks"] >= ia) & (i["blinks"] < ib)) / (ib - ia) * 60
    c["sem_pm"] = np.sum((i["sem"] >= ia) & (i["sem"] < ib)) / (ib - ia) * 60
    sel = (i["t1"] >= ia) & (i["t1"] < ib)
    c["emg_lo"] = np.nanmedian(i["emg_lo_rms"][sel])
    c["emg_hi"] = np.nanmedian(i["emg_hi_rms"][sel])
    c["emg_lo90"] = np.nanpercentile(i["emg_lo_rms"][sel], 90)
    sb = (i["tb"] >= ia) & (i["tb"] < ib)
    c["sweep"] = np.nanmedian(i["sweep_sd"][sb])
    print(f"{c['label']:28s} δ {c['bands']['δ 0,5–4 Hz']:6.1f} θ {c['bands']['θ 4–8 Hz']:5.1f} "
          f"α {c['bands']['α 8–13 Hz']:5.1f} β {c['bands']['β 13–30 Hz']:5.1f} γ {c['g']:5.1f} µV²  "
          f"α-Peak {c['apk']:.2f} Hz +{c['aex']:.1f} dB | Blinks {c['blink_pm']:.1f}/min SEM {c['sem_pm']:.1f}/min | "
          f"EMG30-300 {c['emg_lo']:.2f} (P90 {c['emg_lo90']:.2f}) µV, 300-2k {c['emg_hi']:.2f} µV, sweepSD {c['sweep']:.2f} µV")

# --- EMG bursts (swallow / clench candidates): 0.25 s RMS of 30-300 Hz > 1.6x the local 15 s median for >= 0.5 s,
#     settling phases excluded (run 2 < 80 s, run 3 < 25 s, run 4 < 12 s)
SKIP = {0: 8, 1: 0, 2: 80, 3: 25, 4: 12}
for r in R.values():
    tq, q = win_stat(r["emg_lo"], r["v6"], FM, 0.25, rms)
    q = np.nan_to_num(q, nan=np.nanmedian(q))
    _, qh = win_stat(r["emg_hi"], r["v6"], FM, 0.25, rms)
    qh = np.nan_to_num(qh, nan=np.nanmedian(qh))
    base = ss.medfilt(q, 61)
    baseh = ss.medfilt(qh, 61)
    hi = q > 1.6 * base
    lab = np.diff(np.r_[0, hi.astype(int), 0])
    st, en = np.where(lab == 1)[0], np.where(lab == -1)[0]
    ev = []
    for a, b in zip(st, en):
        if b - a >= 2 and a * 0.25 >= SKIP[r["n"]]:
            i0, i1 = int(a * 0.25 * FE), int(b * 0.25 * FE)
            slow = r["ctx"][max(0, i0 - int(0.5 * FE)):i1 + int(0.5 * FE)]
            ev.append(dict(t=a * 0.25, dur=(b - a) * 0.25, peak=q[a:b].max(), ratio=q[a:b].max() / base[a],
                           base=base[a], slow_ptp=np.ptp(slow), hi_ratio=qh[a:b].max() / baseh[a],
                           after=np.median(q[b + 8:b + 68]) / np.median(q[max(0, a - 68):a - 8]) if a > 76 else np.nan))
    r["bursts"] = ev
    r["emg_q"] = (tq, q)

# --- spindle candidates: 11-15 Hz RMS envelope > 3x median for 0.5-2 s, no EMG burst, no eye event
for r in R.values():
    sg = bp(r["e"], 11, 15, FE, 4)
    env = np.sqrt(np.convolve(sg ** 2, np.ones(int(0.3 * FE)) / int(0.3 * FE), "same"))
    br = bp(r["e"], 20, 40, FE, 4)
    envb = np.sqrt(np.convolve(br ** 2, np.ones(int(0.3 * FE)) / int(0.3 * FE), "same"))
    thr = 3 * np.median(env)
    hi = env > thr
    lab = np.diff(np.r_[0, hi.astype(int), 0])
    out = []
    for a, b in zip(np.where(lab == 1)[0], np.where(lab == -1)[0]):
        d = (b - a) / FE
        tm = (a + b) / 2 / FE
        if 0.5 <= d <= 2.0 and envb[a:b].mean() < 2 * np.median(envb) and \
                np.all(np.abs(r["blinks"] - tm) > 1.5) and np.all(np.abs(r["sem"] - tm) > 1.5):
            out.append((tm, d, env[a:b].max()))
    r["spindles"] = out
    r["sig_env"], r["sig_thr"] = env, thr

# --- usability classification per 4 s window
EMG_FLOOR = np.nanmedian(np.concatenate([R[n]["emg_lo_rms"][R[n]["t1"] > 80 if n == 2 else slice(None)] for n in (2, 3, 4)]))
EMG_THR = 1.6 * EMG_FLOOR
CLS = ["sauber", "Augen (Blinzeln/SEM)", "Muskel (EMG)", "grobes Artefakt"]
for r in R.values():
    nb = int(r["dur"] // 4)
    cl = np.zeros(nb, int)
    for i in range(nb):
        a, b = i * 4, i * 4 + 4
        x = r["ctx"][int(a * FE):int(b * FE)]
        sel = (r["t1"] >= a) & (r["t1"] < b)
        if np.ptp(x) > 300:
            cl[i] = 3
        elif np.nanmax(r["emg_lo_rms"][sel]) > EMG_THR:
            cl[i] = 2
        elif np.any((r["blinks"] >= a - 0.5) & (r["blinks"] < b + 0.5)) or np.any((r["sem"] >= a) & (r["sem"] < b)) \
                or np.ptp(x) > 80:
            cl[i] = 1
    r["cls"] = cl
    print(f"{r['label']}: " + ", ".join(f"{CLS[k]} {100 * np.mean(cl == k):.0f} %" for k in range(4)) +
          f" | Blinks {len(r['blinks'])} ({len(r['blinks']) / r['dur'] * 60:.1f}/min, Median {np.median(r['blink_amp']) if len(r['blinks']) else 0:.0f} µV)"
          f", SEM {len(r['sem'])} ({len(r['sem']) / r['dur'] * 60:.1f}/min), EMG-Bursts {len(r['bursts'])}, Spindel-Kandidaten {len(r['spindles'])}")
print(f"EMG 30–300 Hz Boden (Median Läufe 2 ab 80 s, 3, 4): {EMG_FLOOR:.2f} µV, Schwelle {EMG_THR:.2f} µV")

# --- what drives the sweep noise?
X = {k: [] for k in ("sd", "lo", "hi", "eog", "eeg", "run")}
for n in (1, 2, 3, 4):
    r = R[n]
    ok = np.isfinite(r["sweep_sd"]) & np.isfinite(r["blk_emg_lo"]) & np.isfinite(r["blk_emg_hi"])
    X["sd"] += list(r["sweep_sd"][ok]); X["lo"] += list(r["blk_emg_lo"][ok]); X["hi"] += list(r["blk_emg_hi"][ok])
    X["eog"] += list(r["blk_eog"][:len(ok)][ok]); X["eeg"] += list(r["blk_eeg"][:len(ok)][ok]); X["run"] += [n] * ok.sum()
X = {k: np.array(v) for k, v in X.items()}
R2 = {}
for k in ("lo", "hi", "eog", "eeg"):
    R2[k] = np.corrcoef(np.log(X[k]), np.log(X["sd"]))[0, 1] ** 2
print("R² (log) sweep SD vs: " + ", ".join(f"{k} {v:.2f}" for k, v in R2.items()))
# variance decomposition: (sweep SD)^2 vs EMG 30-300 + EMG 300-2000 RMS^2 overlap
for n in (1, 2, 3, 4):
    r = R[n]
    print(f"Lauf {n}: Median Sweep-SD {np.nanmedian(r['sweep_sd']):.2f} µV, EMG30–300 {np.nanmedian(r['emg_lo_rms']):.2f}, "
          f"EMG300–2k {np.nanmedian(r['emg_hi_rms']):.2f} µV, Anteil Blöcke SD>3 µV {100 * np.nanmean(r['sweep_sd'] > 3):.0f} %")

# ================================================================ figures
def shade_blocks(ax, r, text=True, y=0.97):
    if r["n"] != 3:
        return
    mk = r["marks"]
    for j, (t, lab) in enumerate(mk):
        ax.axvline(t, color="k", lw=0.8, ls="--")
        if text and lab != "end":
            ax.text(t + 4, y, lab.split()[0], transform=ax.get_xaxis_transform(), fontsize=8, va="top",
                    fontweight="bold")


# 01 overview with eye events
fig, axs = plt.subplots(5, 1, figsize=(13, 13), gridspec_kw=dict(height_ratios=[0.6, 1, 1, 1.4, 1]))
for ax, n in zip(axs, RUNS):
    r = R[n]
    t = np.arange(len(r["ctx"])) / FE
    ax.plot(t, r["ctx"], color=C[0], lw=0.4)
    yb = np.interp(r["blinks"], t, r["ctx"])
    ax.plot(r["blinks"], np.full(len(yb), 175), "v", color=C[1], ms=5)
    ax.plot(r["sem"], np.full(len(r["sem"]), -175), "^", color=C[2], ms=5)
    ax.set_ylim(-220, 220)
    ax.set_xlim(0, r["dur"])
    shade_blocks(ax, r, y=0.80)
    ax.set_ylabel("µV")
    ax.set_title(de(f"{r['label']}: Lidschläge {len(r['blinks'])} ({len(r['blinks']) / r['dur'] * 60:.1f}/min), "
                    f"langsame Augenbewegungen {len(r['sem'])} ({len(r['sem']) / r['dur'] * 60:.1f}/min)"))
    ax.grid(alpha=0.25)
axs[-1].set_xlabel("Zeit ab Aufnahmebeginn (s)")
fig.legend([Line2D([], [], color=C[0]), Line2D([], [], marker="v", ls="", color=C[1]),
            Line2D([], [], marker="^", ls="", color=C[2])],
           ["Stirn–Mastoid, 0,1–30 Hz", "Lidschlag erkannt", "langsame Augenbewegung (0,1–1 Hz) erkannt"],
           loc="upper center", ncol=3, frameon=False, bbox_to_anchor=(0.5, 0.995))
fig.suptitle("")
fig.tight_layout(rect=(0, 0, 1, 0.975))
save(fig, "eeg_01_uebersicht_augen.png")

# 02 spectra
fig, axs = plt.subplots(1, 2, figsize=(13, 5.2), sharey=True)
groups = [[(0, GREY), (1, C[0]), (3, C[1]), (7, C[2])], [(3, GREY), (2, C[0]), (4, C[1]), (5, C[2]), (6, C[3])]]
titles = ["Sitzend vs. liegend", "Lauf 2 unruhig vs. ruhig, Lauf 3 Blöcke"]
for ax, g, tt in zip(axs, groups, titles):
    for k, (lo, hi) in enumerate([(0.5, 4), (4, 8), (8, 13), (13, 30)]):
        ax.axvspan(lo, hi, color=["#e8eef8", "#fbefe8", "#e6f5ef", "#fbf3e0"][k], lw=0, zorder=0)
        ax.text((lo * hi) ** 0.5, 0.985, ["δ", "θ", "α", "β"][k], transform=ax.get_xaxis_transform(), ha="center",
                va="top", fontsize=11, color="#555")
    for ci, col in g:
        c = COND[ci]
        w = c["f"] >= 0.5
        ax.loglog(c["f"][w], c["p"][w], color=col, lw=1.4 if col != GREY else 1.0,
                  ls="-" if col != GREY else "--", label=c["label"])
    ax.set_xlim(0.5, 60)
    ax.set_xlabel("Frequenz (Hz)")
    ax.set_title(tt)
    ax.grid(alpha=0.3, which="both")
    ax.legend(frameon=False, fontsize=8, loc="lower left")
axs[0].set_ylabel("Leistungsdichte (µV²/Hz)")
axs[0].set_ylim(5e-3, 5e3)
fig.suptitle("EEG-Spektren Stirn–Mastoid (Welch 4 s, Median-Mittelung, 0,5–45 Hz + 50-Hz-Kerbe, Stimulus-Artefakt subtrahiert)",
             x=0.01, ha="left", fontsize=10)
fig.tight_layout()
save(fig, "eeg_02_spektren.png")

# 03 relative band power
fig, (ax, ax2) = plt.subplots(1, 2, figsize=(13, 4.8), gridspec_kw=dict(width_ratios=[2.2, 1]))
labs = [c["label"] for c in COND]
y = np.arange(len(COND))[::-1]
for i, c in enumerate(COND):
    tot = sum(c["bands"].values()) + c["g"]
    left = 0
    for k, (bn, _, _) in enumerate(BANDS):
        w = c["bands"][bn] / tot * 100
        ax.barh(y[i], w, left=left, color=C[k], height=0.7)
        if w > 6:
            ax.text(left + w / 2, y[i], f"{w:.0f}", ha="center", va="center", color="white", fontsize=8)
        left += w
    ax.barh(y[i], c["g"] / tot * 100, left=left, color=LGREY, height=0.7)
ax.set_yticks(y)
ax.set_yticklabels(labs)
ax.set_xlim(0, 100)
ax.set_xlabel("Anteil an der Leistung 0,5–45 Hz (%)")
ax.set_title("Relative Bandleistung")
ax.legend(handles=[Patch(color=C[k], label=BANDS[k][0]) for k in range(4)] + [Patch(color=LGREY, label="γ/EMG 30–45 Hz")],
          frameon=False, fontsize=8, ncol=5, loc="upper center", bbox_to_anchor=(0.45, -0.13))
for i, c in enumerate(COND):
    ax2.barh(y[i], c["bands"]["α 8–13 Hz"], color=C[2], height=0.35, label="α 8–13 Hz" if i == 0 else None)
    ax2.barh(y[i] - 0.35, c["bands"]["θ 4–8 Hz"], color=C[1], height=0.35, label="θ 4–8 Hz" if i == 0 else None)
ax2.set_yticks(y - 0.17)
ax2.set_yticklabels([])
ax2.set_xlabel("Absolute Bandleistung (µV²)")
ax2.set_title("α und θ absolut")
ax2.legend(frameon=False, fontsize=8, loc="lower right")
ax2.grid(alpha=0.3, axis="x")
fig.tight_layout()
save(fig, "eeg_03_bandleistung.png")

# 04-06 spectrograms of long runs
for idx, n in enumerate((2, 3, 4)):
    r = R[n]
    f, t, S = r["sg"]
    fig = plt.figure(figsize=(13, 9.5))
    gs = fig.add_gridspec(4, 2, height_ratios=[2.2, 1, 1, 1], width_ratios=[60, 1], hspace=0.42, wspace=0.02,
                          left=0.07, right=0.93, top=0.95, bottom=0.07)
    axs = [fig.add_subplot(gs[0, 0])]
    axs += [fig.add_subplot(gs[i, 0], sharex=axs[0]) for i in (1, 2, 3)]
    w = (f >= 0.5) & (f <= 45)
    im = axs[0].pcolormesh(t, f[w], 10 * np.log10(S[w]), shading="auto", cmap="viridis",
                           vmin=np.percentile(10 * np.log10(S[w]), 3), vmax=np.percentile(10 * np.log10(S[w]), 99.5))
    axs[0].set_ylabel("Frequenz (Hz)")
    for fb in (4, 8, 13):
        axs[0].axhline(fb, color="w", lw=0.5, ls=":")
    cb = fig.colorbar(im, cax=fig.add_subplot(gs[0, 1]))
    cb.set_label("dB re 1 µV²/Hz")
    axs[0].set_title(f"{r['label']}: Spektrogramm (4-s-Fenster, 2 s Schritt)")
    sm = smooth
    bpt = r["bp_t"]
    for k, (key, lab) in enumerate([("d", "δ 0,5–4"), ("t", "θ 4–8"), ("a", "α 8–13"), ("s", "σ 11–15 (Spindeln)")]):
        axs[1].semilogy(t, sm(bpt[key]), color=C[k], lw=1.1, label=lab + " Hz")
    axs[1].set_ylabel("µV²")
    axs[1].set_title("Bandleistung (gleitend über 10 s)")
    axs[1].legend(frameon=False, fontsize=8, ncol=4, loc="upper right")
    axs[2].plot(t, r["alpha_idx"], color=LGREY, lw=0.7)
    axs[2].plot(t, sm(r["alpha_idx"]), color=C[2], lw=1.4, label="α-Index: 9,25–10,5 Hz über Nachbarbändern")
    axs[2].plot(t, sm(10 * np.log10(bpt["t"] / bpt["a"])), color=C[1], lw=1.1, label="θ/α-Verhältnis")
    axs[2].axhline(0, color="k", lw=0.5)
    axs[2].set_ylabel("dB")
    axs[2].set_title("α-Index und θ/α-Verhältnis (θ/α > 0 dB = Müdigkeitszeichen), 10 s geglättet")
    axs[2].legend(frameon=False, fontsize=8, loc="lower right", ncol=2)
    axs[2].set_ylim(-15, 17)
    axs[3].plot(r["t1"], r["emg_lo_rms"], color=C[0], lw=0.8, label="EMG 30–300 Hz (RMS 1 s)")
    axs[3].plot(r["t1"], r["emg_hi_rms"], color=C[3], lw=0.8, label="300–2000 Hz")
    ye = np.full(len(r["blinks"]), 0.95)
    axs[3].plot(r["blinks"], ye, "v", color=C[1], ms=4, transform=axs[3].get_xaxis_transform(), label="Lidschlag")
    axs[3].plot(r["sem"], np.full(len(r["sem"]), 0.85), "^", color=C[2], ms=4, transform=axs[3].get_xaxis_transform(),
                label="langsame Augenbew.")
    axs[3].set_ylabel("µV")
    axs[3].set_ylim(0, np.nanpercentile(r["emg_lo_rms"], 99.5) * 1.35)
    axs[3].set_title("Muskel- und Augenaktivität")
    axs[3].legend(frameon=False, fontsize=8, ncol=4, loc="center right")
    axs[3].set_xlabel("Zeit ab Aufnahmebeginn (s)")
    for ax in axs:
        shade_blocks(ax, r, text=(ax is axs[0]), y=0.97)
        ax.grid(alpha=0.25)
    axs[0].grid(False)
    save(fig, f"eeg_{4 + idx:02d}_spektrogramm_lauf{n}.png")

# 07 alpha check
fig = plt.figure(figsize=(13, 9))
gs = fig.add_gridspec(2, 2, hspace=0.38, wspace=0.22)
ax = fig.add_subplot(gs[0, 0])
for ci, col in [(1, C[0]), (3, C[1]), (4, C[2]), (7, C[3])]:
    c = COND[ci]
    w = (c["fh"] >= 5) & (c["fh"] <= 16)
    ax.semilogy(c["fh"][w], c["ph"][w], color=col, lw=1.2, label=f"{c['label']}: Peak {c['apk']:.2f} Hz, +{c['aex']:.1f} dB")
ax.axvline(1e3 / 102.4, color=GREY, ls=":", lw=1, label="Referenz: WLAN-Beacon 9,77 Hz")
ax.axvline(21.108 / 2, color=GREY, ls="--", lw=1, label="Referenz: Klickpaar-Rate 10,55 Hz")
ax.set_ylim(top=80)
ax.set_xlabel("Frequenz (Hz)")
ax.set_ylabel("µV²/Hz")
ax.set_title("α-Bereich, hochaufgelöst (Welch 16 s)")
ax.legend(frameon=False, fontsize=7.5, loc="upper right")
ax.grid(alpha=0.3, which="both")

ax = fig.add_subplot(gs[0, 1])
# controls: headset mic CH1 of run 3, and chest ECG (1 kHz)
d = np.load(os.path.join(DATA, RUNS[3][0] + ".npz"))
v = d["valid"]
mic = d["ch1"].astype(float) / 32768 * 2.8284 * 1e3
ii = np.arange(len(mic)); mic[~v] = np.interp(ii[~v], ii[v], mic[v])
mic = ss.resample_poly(mic, 1, 96)
fmc, pmc = ss.welch(mic, FE, nperseg=int(16 * FE), average="median")
raw = np.loadtxt(CHEST, delimiter=",", skiprows=4)
ecg = -raw[:, 2] * UV
fec, pec = ss.welch(ecg, 1000, nperseg=16000, average="median")
c3 = COND[4]
for (fx, px, lab, col) in [(c3["fh"], c3["ph"], "Kopf CH2, Lauf 3 A", C[1]),
                           (fec, pec, "Brust-EKG CH2 (Kontrolle, 1 kHz)", GREY)]:
    w = (fx >= 5) & (fx <= 16)
    ax.semilogy(fx[w], px[w] / np.median(px[w]), color=col, lw=1.2, label=lab)
w = (fmc >= 5) & (fmc <= 16)
ax.semilogy(fmc[w], pmc[w] / np.median(pmc[w]), color=C[0], lw=1.0, label="Mikrofon CH1, Lauf 3 (Kontrolle)")
ax.set_xlabel("Frequenz (Hz)")
ax.set_ylabel("relativ zum Median 5–16 Hz")
ax.set_title("Kontrollen: Peak nur am Kopf, nicht im Mikrofon/EKG")


def phase_lock(y, f0=1e3 / 102.4, win=2.0):
    """Resultant length of the 2 s complex demodulates at f0 (1 = phase-stable line, ~0 = random phase)."""
    t = np.arange(len(y)) / FE
    z = bp(y, f0 - 0.25, f0 + 0.25, FE) * np.exp(-2j * np.pi * f0 * t)
    k = int(win * FE)
    Z = z[:len(z) // k * k].reshape(-1, k).mean(axis=1)
    return np.abs(Z.sum()) / np.abs(Z).sum(), np.std(np.abs(Z)) / np.mean(np.abs(Z))


PL = {ci: phase_lock(R[COND[ci]["n"]]["e"][int(COND[ci]["a"] * FE):int(COND[ci]["b"] * FE)]) for ci in (3, 4, 7)}
print("Phasenstabilität 9,766 Hz (R, Amplituden-CV):", {COND[k]["label"]: (round(v[0], 2), round(v[1], 2)) for k, v in PL.items()})
ax.text(0.02, 0.03, "Phasenstabilität bei 9,766 Hz (2-s-Demodulation):\n" +
        "\n".join(f"{COND[k]['label']}: R = {v[0]:.2f}, Amplituden-CV {v[1]:.2f}" for k, v in PL.items()) +
        "\n(Störlinie: R ≈ 1, CV ≈ 0; Rauschen/EEG: R ≈ 0, CV ≈ 0,5)", transform=ax.transAxes, fontsize=7.5,
        va="bottom", bbox=dict(fc="white", ec=LGREY))
ax.legend(frameon=False, fontsize=8, loc="upper right")
ax.grid(alpha=0.3, which="both")

ax = fig.add_subplot(gs[1, 0])
for k, n in enumerate((2, 3, 4)):
    r = R[n]
    t = r["sg"][1]
    ax.plot(t / 60, smooth(r["alpha_idx"]), color=C[k], lw=1.1, label=f"Lauf {n}")
ax.axhline(0, color="k", lw=0.5)
ax.set_xlabel("Zeit ab Aufnahmebeginn (min)")
ax.set_ylabel("α-Index (dB, 10 s geglättet)")
ax.set_title("α kommt und geht (α-Index je 4-s-Fenster)")
ax.legend(frameon=False, fontsize=8, ncol=3, loc="upper right")
ax.grid(alpha=0.3)

ax = fig.add_subplot(gs[1, 1])
r = R[4]
ai = smooth(r["alpha_idx"], 3)
okw = r["cls"][np.clip((r["sg"][1] // 4).astype(int), 0, len(r["cls"]) - 1)] == 0
j = np.argmax(np.where(okw & (r["sg"][1] > 10), ai, -99))
tc = r["sg"][1][j]
a0 = max(0, tc - 4)
sl = slice(int(a0 * FE), int((a0 + 8) * FE))
tt = np.arange(sl.start, sl.stop) / FE
ax.plot(tt, r["eeg"][sl] + 25, color=GREY, lw=0.7, label="EEG 0,5–45 Hz (+25 µV versetzt)")
ax.plot(tt, bp(r["e"], 8.5, 11.5, FE, 4)[sl] - 10, color=C[2], lw=1.0, label="8,5–11,5 Hz (−10 µV versetzt)")
ax.axhline(-10 + 5.4 / 2, color=C[3], lw=0.6, ls=":")
ax.axhline(-10 - 5.4 / 2, color=C[3], lw=0.6, ls=":", label="±½ LSB (5,4 µV)")
ax.set_xlabel("Zeit ab Aufnahmebeginn (s)")
ax.set_ylabel("µV")
ax.set_title(f"Lauf 4: stärkste α-Phase bei {tc:.0f} s")
ax.legend(frameon=False, fontsize=7.5, loc="upper right", ncol=1)
ax.set_ylim(-30, 58)
ax.grid(alpha=0.3)
save(fig, "eeg_07_alpha_pruefung.png")

# 08 eye examples
ex = []
r2 = R[2]
if len(R[1]["blinks"]):
    b = R[1]["blinks"][np.argsort(R[1]["blink_amp"])[len(R[1]["blinks"]) // 2]]
    ex.append((1, b - 2, b + 3, "Lauf 1: typischer Lidschlag (positiv an der Stirn)"))
if len(R[2]["blinks"]):
    b = [x for x in R[2]["blinks"] if x > 90]
    if b:
        ex.append((2, b[0] - 2, b[0] + 3, "Lauf 2 (ruhig): einzelner Lidschlag"))
for n in (2, 4):
    sel = [(t_, a_) for t_, a_ in zip(R[n]["sem"], R[n]["sem_amp"]) if t_ > SKIP[n] + 10]
    if sel:
        t_, a_ = max(sel, key=lambda z: z[1])
        ex.append((n, t_ - 4, t_ + 4, f"Lauf {n}: langsame Augenbewegung / Blickwechsel ({a_:.0f} µV in 0,1–1 Hz)"))
ex.append((2, 38, 48, "Lauf 2, 38–48 s: unruhige Phase (Augen + Muskel)"))
ex.append((3, 10, 25, "Lauf 3, 10–25 s: Bewegung/Lagewechsel kurz nach Start"))
fig, axs = plt.subplots(len(ex), 1, figsize=(13, 2.15 * len(ex)))
for ax, (n, a, b, tt) in zip(axs, ex):
    r = R[n]
    a = max(a, 0)
    sl = slice(int(a * FE), int(b * FE))
    t = np.arange(sl.start, sl.stop) / FE
    ax.plot(t, r["ctx"][sl], color=C[0], lw=0.8, label="0,1–30 Hz")
    ax.plot(t, r["slow"][sl], color=C[2], lw=1.2, label="0,1–1 Hz")
    s6 = slice(int(a * FM), int(b * FM))
    t6 = np.arange(s6.start, s6.stop) / FM
    off = min(np.min(r["ctx"][sl]), -40) - 30
    ax.plot(t6, r["emg_lo"][s6] + off, color=C[1], lw=0.3)
    for x in r["blinks"][(r["blinks"] >= a) & (r["blinks"] <= b)]:
        ax.axvline(x, color=C[1], lw=0.8, ls=":")
    ax.set_title(tt)
    ax.set_ylabel("µV")
    ax.set_xlim(a, b)
    ax.grid(alpha=0.25)
axs[-1].set_xlabel("Zeit ab Aufnahmebeginn (s)")
fig.legend([Line2D([], [], color=C[0]), Line2D([], [], color=C[2]), Line2D([], [], color=C[1], lw=0.6),
            Line2D([], [], color=C[1], ls=":")],
           ["Stirn–Mastoid 0,1–30 Hz", "0,1–1 Hz (langsame Komponente)", "EMG 30–300 Hz (nach unten versetzt)",
            "erkannter Lidschlag"], loc="upper center", ncol=4, frameon=False, bbox_to_anchor=(0.5, 0.997))
fig.tight_layout(rect=(0, 0, 1, 0.98))
save(fig, "eeg_08_augen_beispiele.png")

# 09 eye event rate per minute
fig, axs = plt.subplots(4, 1, figsize=(13, 8.5))
for ax, n in zip(axs, (1, 2, 3, 4)):
    r = R[n]
    edges = np.arange(0, r["dur"] + 1e-6, 30.0)
    if edges[-1] < r["dur"] - 10:
        edges = np.r_[edges, r["dur"]]
    wdt = np.diff(edges)
    hb, _ = np.histogram(r["blinks"], edges)
    hs, _ = np.histogram(r["sem"], edges)
    ctr = edges[:-1] + wdt / 2
    ax.bar(ctr - wdt * 0.2, hb / wdt * 60, width=wdt * 0.38, color=C[1], label="Lidschläge/min")
    ax.bar(ctr + wdt * 0.2, hs / wdt * 60, width=wdt * 0.38, color=C[2], label="langsame Augenbewegungen/min")
    shade_blocks(ax, r, y=0.97)
    ax.set_xlim(0, r["dur"])
    ax.set_ylabel("pro min")
    ax.set_title(f"{r['label']} (30-s-Abschnitte)")
    ax.grid(alpha=0.25, axis="y")
    ax.set_ylim(0, max(12, 1.25 * max((hb / wdt * 60).max(), (hs / wdt * 60).max())))
axs[0].legend(frameon=False, fontsize=8, loc="upper right", ncol=2)
axs[-1].set_xlabel("Zeit ab Aufnahmebeginn (s)")
fig.tight_layout()
save(fig, "eeg_09_augen_rate.png")

# 10 EMG + sweep noise timeline
fig, axs = plt.subplots(4, 1, figsize=(13, 10))
for ax, n in zip(axs, (1, 2, 3, 4)):
    r = R[n]
    ax.plot(r["t1"], r["emg_lo_rms"], color=C[0], lw=0.8, label="EMG 30–300 Hz (RMS 1 s)")
    ax.plot(r["t1"], r["emg_hi_rms"], color=C[3], lw=0.8, label="EMG 300–2000 Hz (RMS 1 s)")
    ax.step(r["tb"], r["sweep_sd"], where="mid", color=C[1], lw=1.5, label="BERA-Sweep-SD 100–1500 Hz (64er-Block)")
    ax.axhline(EMG_THR, color=GREY, lw=0.8, ls=":", label="EMG-Schwelle für Nutzbarkeit")
    shade_blocks(ax, r, y=0.97)
    ax.set_xlim(0, r["dur"])
    ax.set_ylim(0, min(12, np.nanpercentile(np.r_[r["sweep_sd"], r["emg_lo_rms"]], 99.5) * 1.3))
    ax.set_ylabel("µV")
    ax.set_title(f"{r['label']}: Median Sweep-SD {np.nanmedian(r['sweep_sd']):.2f} µV, EMG 30–300 Hz "
                 f"{np.nanmedian(r['emg_lo_rms']):.2f} µV, 300–2000 Hz {np.nanmedian(r['emg_hi_rms']):.2f} µV")
    ax.grid(alpha=0.25)
axs[0].legend(frameon=False, fontsize=8, ncol=4, loc="upper right")
axs[-1].set_xlabel("Zeit ab Aufnahmebeginn (s)")
fig.tight_layout()
save(fig, "eeg_10_emg_und_sweeprauschen.png")


# 16 EMG spectra: is the extra broadband noise in runs 1/3/4 muscle?
fig, (ax, ax2) = plt.subplots(1, 2, figsize=(13, 4.8))
ref = None
spec = []
for ci, col in [(3, GREY), (2, C[0]), (1, C[1]), (4, C[2]), (7, C[3])]:
    c = COND[ci]
    r = R[c["n"]]
    y = r["mc"][int(c["a"] * FM):int(c["b"] * FM)]
    f, p = ss.welch(y, FM, nperseg=3000, average="median")
    spec.append((c["label"], col, f, p))
    if ref is None:
        ref = p
w = (f >= 10) & (f <= 2800)
for lab, col, f, p in spec:
    ax.loglog(f[w], p[w], color=col, lw=1.1 if col != GREY else 1.4, ls="-" if col != GREY else "--", label=lab)
    if col != GREY:
        ax2.semilogx(f[w], 10 * np.log10(p[w] / ref[w]), color=col, lw=1.1, label=lab)
for a_ in (ax, ax2):
    a_.axvspan(30, 300, color="#e8eef8", lw=0, zorder=0)
    a_.axvspan(300, 2000, color="#fbf3e0", lw=0, zorder=0)
    a_.grid(alpha=0.3, which="both")
    a_.set_xlabel("Frequenz (Hz)")
    a_.set_xlim(10, 2800)
ax.text(95, 0.97, "30–300 Hz", transform=ax.get_xaxis_transform(), ha="center", va="top", fontsize=8)
ax.text(775, 0.97, "300–2000 Hz", transform=ax.get_xaxis_transform(), ha="center", va="top", fontsize=8)
ax.set_ylabel("µV²/Hz")
ax.set_title("Spektrum 10–2800 Hz (50-Hz-Kamm und Stimulus-Artefakt entfernt)")
ax.legend(frameon=False, fontsize=8, loc="lower left")
ax2.axhline(0, color="k", lw=0.6)
ax2.set_ylabel("dB relativ zu Lauf 2, 80–420 s")
ax2.set_title("Mehrleistung gegenüber der ruhigsten Phase")
ax2.legend(frameon=False, fontsize=8, loc="upper right")
fig.tight_layout()
save(fig, "eeg_16_emg_spektren.png")

# 11 noise drivers scatter
fig, axs = plt.subplots(1, 4, figsize=(14, 4.2), sharey=True)
names = {"lo": "EMG 30–300 Hz RMS (µV)", "hi": "EMG 300–2000 Hz RMS (µV)", "eog": "EOG 0,1–5 Hz RMS (µV)",
         "eeg": "EEG 4–30 Hz RMS (µV)"}
for ax, k in zip(axs, ("lo", "hi", "eog", "eeg")):
    for j, n in enumerate((1, 2, 3, 4)):
        s = X["run"] == n
        ax.scatter(X[k][s], X["sd"][s], s=7, color=C[j], alpha=0.6, lw=0, label=f"Lauf {n}")
    ax.set_xscale("log")
    ax.set_yscale("log")
    for axis in (ax.xaxis, ax.yaxis):
        axis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}"))
        axis.set_minor_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}" if str(f"{v:g}")[0] in "25" else ""))
    ax.set_xlabel(names[k])
    ax.set_title(f"R² (log–log) = {R2[k]:.2f}")
    ax.grid(alpha=0.3, which="both")
axs[0].set_ylabel("Sweep-SD je 64er-Block (µV)")
axs[0].legend(frameon=False, fontsize=8, markerscale=2, loc="upper left")
fig.suptitle("Was treibt das BERA-Rauschen? Jeder Punkt = ein 64-Sweep-Block (3,03 s), Läufe 1–4", x=0.01, ha="left",
             fontsize=10)
fig.tight_layout()
save(fig, "eeg_11_rauschtreiber.png")

# 12 run 2 restless phase
r = R[2]
fig, axs = plt.subplots(4, 1, figsize=(13, 9), sharex=True)
lim = 160
t = np.arange(int(lim * FE)) / FE
axs[0].plot(t, r["ctx"][:len(t)], color=C[0], lw=0.5)
axs[0].plot(r["blinks"][r["blinks"] < lim], np.full(np.sum(r["blinks"] < lim), 0.95), "v", color=C[1], ms=5,
            transform=axs[0].get_xaxis_transform())
axs[0].set_ylabel("µV")
axs[0].set_title("Lauf 2, erste 160 s: Rohsignal 0,1–30 Hz (▼ Lidschlag)")
axs[0].set_ylim(-250, 300)
tb, sd = r["tb"], r["sweep_sd"]
_, eogb = tb, r["blk_eog"][:len(tb)]
axs[1].step(tb, eogb, where="mid", color=C[2], lw=1.3)
axs[1].set_ylabel("µV")
axs[1].set_title("EOG-Aktivität 0,1–5 Hz (RMS je 3-s-Block)")
axs[2].plot(r["t1"], r["emg_lo_rms"], color=C[0], lw=0.9, label="30–300 Hz")
axs[2].plot(r["t1"], r["emg_hi_rms"], color=C[3], lw=0.9, label="300–2000 Hz")
axs[2].set_ylabel("µV")
axs[2].legend(frameon=False, fontsize=8, loc="upper right")
axs[3].step(tb, sd, where="mid", color=C[1], lw=1.5)
axs[3].set_ylabel("µV")
axs[3].set_xlabel("Zeit ab Aufnahmebeginn (s)")
w1, w2 = tb < 80, (tb >= 80) & (tb < 420)
for ax in axs:
    ax.axvline(80, color="k", lw=0.8, ls="--")
    ax.grid(alpha=0.25)
w1e, w2e = r["t1"] < 80, r["t1"] >= 80
axs[1].set_title(f"EOG-Aktivität 0,1–5 Hz (RMS je 3-s-Block): Median 0–80 s {np.nanmedian(eogb[w1]):.0f} µV, "
                 f"80–420 s {np.nanmedian(eogb[w2]):.0f} µV")
axs[2].set_title(f"EMG 30–300 Hz (RMS 1 s): Median 0–80 s {np.nanmedian(r['emg_lo_rms'][w1e]):.1f} µV, "
                 f"80–420 s {np.nanmedian(r['emg_lo_rms'][w2e]):.1f} µV")
axs[3].set_title(f"BERA-Sweep-SD 100–1500 Hz je 64er-Block: Median 0–80 s {np.nanmedian(sd[w1]):.1f} µV, "
                 f"80–130 s {np.nanmedian(sd[(tb >= 80) & (tb < 130)]):.1f} µV, 130–420 s {np.nanmedian(sd[(tb >= 130) & (tb < 420)]):.1f} µV")
axs[3].set_xlim(0, lim)
fig.tight_layout()
save(fig, "eeg_12_lauf2_unruhe.png")

# 13 EMG bursts gallery
allb = [(n, b) for n in (1, 2, 3, 4) for b in R[n]["bursts"]]
allb = sorted(allb, key=lambda x: -x[1]["ratio"])[:6]
allb = sorted(allb, key=lambda x: (x[0], x[1]["t"]))
if allb:
    fig, axs = plt.subplots(len(allb), 1, figsize=(13, 1.95 * len(allb) + 0.6))
    axs = np.atleast_1d(axs)
    for ax, (n, b) in zip(axs, allb):
        r = R[n]
        a, e_ = max(0, b["t"] - 2), b["t"] + b["dur"] + 2
        sl = slice(int(a * FE), int(e_ * FE))
        s6 = slice(int(a * FM), int(e_ * FM))
        ax.plot(np.arange(sl.start, sl.stop) / FE, r["ctx"][sl], color=C[0], lw=0.9, label="0,1–30 Hz")
        off = -60 - 3 * np.std(r["emg_lo"][s6])
        ax.plot(np.arange(s6.start, s6.stop) / FM, r["emg_lo"][s6] + off, color=C[1], lw=0.3,
                label=f"EMG 30–300 Hz (versetzt {off:.0f} µV)")
        ax.axvspan(b["t"], b["t"] + b["dur"], color=C[3], alpha=0.18, lw=0)
        ax.set_xlim(a, e_)
        ax.set_ylabel("µV")
        aft = "" if not np.isfinite(b["after"]) else f", Grundtonus danach ×{b['after']:.2f}"
        ax.set_title(f"Lauf {n}, {b['t']:.1f} s: Burst {b['dur']:.2f} s, 30–300 Hz ×{b['ratio']:.1f} "
                     f"({b['peak']:.1f} µV), 300–2000 Hz ×{b['hi_ratio']:.1f}, langsame Welle {b['slow_ptp']:.0f} µV ss{aft}")
        ax.grid(alpha=0.25)
    axs[-1].set_xlabel("Zeit ab Aufnahmebeginn (s)")
    fig.legend([Line2D([], [], color=C[0]), Line2D([], [], color=C[1]), Patch(color=C[3], alpha=0.3)],
               ["Stirn–Mastoid 0,1–30 Hz", "EMG 30–300 Hz (nach unten versetzt)", "erkannter EMG-Burst"],
               loc="upper center", ncol=3, frameon=False, bbox_to_anchor=(0.5, 0.995))
    fig.tight_layout(rect=(0, 0, 1, 0.975))
    save(fig, "eeg_13_emg_ereignisse.png")

# 14 spindles
cand = [(n, s) for n in (2, 3, 4) for s in R[n]["spindles"]]
cand = sorted(cand, key=lambda x: -x[1][2])[:4]
fig = plt.figure(figsize=(13, 2.2 * len(cand) + 3.0))
gs = fig.add_gridspec(len(cand) + 1, 1, hspace=0.75, bottom=0.18 if not cand else 0.08, left=0.06, right=0.98)
ax = fig.add_subplot(gs[0])
for k, n in enumerate((2, 3, 4)):
    r = R[n]
    tt = np.arange(len(r["sig_env"])) / FE
    ax.plot(tt[::25] / 60, r["sig_env"][::25], color=C[k], lw=0.6, label=f"Lauf {n}: {len(r['spindles'])} Kandidaten")
    ax.plot([s[0] / 60 for s in r["spindles"]], [s[2] for s in r["spindles"]], "o", color=C[k], ms=4)
ax.set_ylabel("µV")
ax.set_xlabel("Zeit ab Aufnahmebeginn (min)")
ax.set_title("σ-Hüllkurve 11–15 Hz (RMS 0,3 s); Punkte = Kandidaten > 3 × Median, 0,5–2 s, ohne EMG/Augen")
ax.legend(frameon=False, fontsize=8, ncol=3, loc="upper right")
ax.set_ylim(0, None)
ax.grid(alpha=0.25)
for i, (n, (tm, d, pkv)) in enumerate(cand):
    r = R[n]
    ax = fig.add_subplot(gs[i + 1])
    a = max(0, tm - 3)
    sl = slice(int(a * FE), int((tm + 3) * FE))
    tt = np.arange(sl.start, sl.stop) / FE
    ax.plot(tt, r["eeg"][sl] + 20, color=GREY, lw=0.7, label="EEG 0,5–45 Hz (+20 µV)")
    ax.plot(tt, bp(r["e"], 11, 15, FE, 4)[sl], color=C[0], lw=0.9, label="11–15 Hz")
    ax.axvspan(tm - d / 2, tm + d / 2, color=C[3], alpha=0.2, lw=0)
    ax.set_xlim(a, tm + 3)
    ax.set_ylabel("µV")
    ax.set_title(f"Lauf {n}, {tm:.1f} s: Kandidat {d:.2f} s, Hüllkurve {pkv:.1f} µV")
    ax.legend(frameon=False, fontsize=7.5, loc="upper right", ncol=2)
    ax.grid(alpha=0.25)
    if i == len(cand) - 1:
        ax.set_xlabel("Zeit ab Aufnahmebeginn (s)")
save(fig, "eeg_14_spindel_kandidaten.png")

# 15 usability timeline
CC = [C[2], C[3], C[1], GREY]
fig, ax = plt.subplots(figsize=(13, 4.2))
ylab = []
for k, n in enumerate((0, 1, 2, 3, 4)):
    r = R[n]
    yk = 4 - k
    for i, cl in enumerate(r["cls"]):
        ax.barh(yk, 4 / 60, left=i * 4 / 60, color=CC[cl], height=0.7, lw=0)
    pct = 100 * np.mean(r["cls"] == 0)
    ylab.append((yk, f"Lauf {n} ({pct:.0f} % sauber)"))
    if n == 3:
        for t, lab in r["marks"]:
            ax.plot([t / 60, t / 60], [yk - 0.42, yk + 0.42], color="k", lw=1)
            if lab != "end":
                ax.text(t / 60 + 0.05, yk + 0.38, lab.split()[0], fontsize=7.5, va="bottom", fontweight="bold")
ax.set_yticks([y for y, _ in ylab])
ax.set_yticklabels([l for _, l in ylab])
ax.set_xlabel("Zeit ab Aufnahmebeginn (min)")
ax.set_xlim(0, 11.6)
ax.set_title("Nutzbarkeit je 4-s-Fenster (EMG-Schwelle "
             f"{EMG_THR:.1f} µV RMS 30–300 Hz, Augen = Lidschlag/SEM oder > 80 µV ss, grob = > 300 µV ss)")
ax.legend(handles=[Patch(color=CC[k], label=CLS[k]) for k in range(4)], frameon=False, fontsize=8, ncol=4,
          loc="upper center", bbox_to_anchor=(0.5, -0.2))
fig.tight_layout()
save(fig, "eeg_15_nutzbarkeit.png")

# summary numbers
print("\nBedingungen:")
for c in COND:
    print(f"  {c['label']:28s} Blinks {c['blink_pm']:.1f}/min, SEM {c['sem_pm']:.1f}/min, α {c['bands']['α 8–13 Hz']:.1f} µV², "
          f"α-Peak {c['apk']:.2f} Hz +{c['aex']:.1f} dB, EMG {c['emg_lo']:.2f}/{c['emg_hi']:.2f} µV, Sweep-SD {c['sweep']:.2f} µV")
for n in (2, 3, 4):
    r = R[n]
    ai = r["alpha_idx"]
    print(f"Lauf {n}: α-Index Median {np.median(ai):.1f} dB, P10 {np.percentile(ai, 10):.1f}, P90 {np.percentile(ai, 90):.1f}; "
          f"Anteil Fenster > 3 dB {100 * np.mean(ai > 3):.0f} %; θ/α Median {np.median(r['bp_t']['t'] / r['bp_t']['a']):.2f}")
    for b in r["bursts"]:
        print(f"   burst {b['t']:.1f}s dur {b['dur']:.2f} peak {b['peak']:.1f} hi x{b['hi_ratio']:.1f} slow {b['slow_ptp']:.0f}")
