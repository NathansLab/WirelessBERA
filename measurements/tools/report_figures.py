"""Figures for the Forschungspraxis report (report/figures/fig_*.pdf).

Usage: report_figures.py

Reads the raw recordings in measurements/2026-10-16_ecg_drl and
measurements/2026-10-16_bera and writes vector figures sized for the
two-column MFE report template.
"""
import json
import os, sys

import numpy as np
import scipy.signal as ss
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
ECG = os.path.join(HERE, "..", "2026-10-16_ecg_drl")
BERA = os.path.join(HERE, "..", "2026-10-16_bera")
OUT = os.path.join(HERE, "..", "..", "report", "figures")
C1, C2, C3, C4 = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
GREY = "#9a9a9a"
FS_VPEAK, GAIN = 2.0 * np.sqrt(2), 16.0
rng = np.random.default_rng(1)

plt.rcParams.update({
    "font.size": 8, "axes.titlesize": 8.5, "axes.labelsize": 8, "legend.fontsize": 7,
    "xtick.labelsize": 7, "ytick.labelsize": 7, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.alpha": 0.25, "lines.linewidth": 1.2, "pdf.fonttype": 42,
    "axes.titlelocation": "left",
})


def save(fig, name):
    fig.savefig(os.path.join(OUT, name), bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)
    print(name)


# --------------------------------------------------------------------------- ECG
def ecg_csv(name):
    d = np.loadtxt(os.path.join(ECG, name), delimiter=",", skiprows=4)
    return -d[:, 2] / 32768 * FS_VPEAK / GAIN * 1e3          # mV at the electrodes, 1 kHz


def line_rms(x, fs, f0):
    f, p = ss.welch(x, fs, window="flattop", nperseg=8192)
    m = np.abs(f - f0) < 2
    return np.sqrt(p[m].sum() * (f[1] - f[0])) * 1e3          # µV rms


def monitor(x, fs=1000.0):
    y = ss.sosfiltfilt(ss.butter(2, [0.5, 40], "bp", fs=fs, output="sos"), x)
    return ss.filtfilt(*ss.iirnotch(50, 30, fs), y)


fig, ax = plt.subplots(1, 3, figsize=(7.1, 2.0), gridspec_kw=dict(width_ratios=[1.35, 1, 1], wspace=0.38))
raw = ecg_csv("4_drl_chest_repeat.csv")
t = np.arange(len(raw)) / 1000
s = (t >= 20) & (t < 24)
ax[0].plot(t[s] - 20, raw[s] - raw[s].mean() + 2.2, color=GREY, lw=0.5, label="raw")
ax[0].plot(t[s] - 20, monitor(raw)[s], color=C1, lw=1.0, label="0.5–40 Hz + 50 Hz notch")
ax[0].set_xlabel("time (s)")
ax[0].set_ylabel("mV at electrodes")
ax[0].set_title("(a) chest ECG, DRL on")
ax[0].legend(loc="upper right", frameon=False, ncol=2, fontsize=6.3)
ax[0].set_ylim(-1, 6.0)

conds = [("no\nDRL", "1_no_drl.csv"), ("DRL\nhand", "2_drl_hand.csv"),
         ("DRL\nchest", "3_drl_chest.csv"), ("DRL\nchest 2", "4_drl_chest_repeat.csv")]
v50 = [line_rms(ecg_csv(f), 1000.0, 50) for _, f in conds]
v150 = [line_rms(ecg_csv(f), 1000.0, 150) for _, f in conds]
x = np.arange(len(conds))
ax[1].bar(x - 0.19, v50, 0.36, color=C1, label="50 Hz")
ax[1].bar(x + 0.19, v150, 0.36, color=C2, label="150 Hz")
ax[1].set_yscale("log")
ax[1].set_ylim(20, 4000)
ax[1].set_xticks(x, [c for c, _ in conds], fontsize=6.5)
ax[1].set_ylabel("µV rms at electrodes")
ax[1].set_title("(b) mains pickup")
ax[1].legend(frameon=False, loc="upper right")
ax[1].grid(axis="x", visible=False)
for i in range(1, 4):
    ax[1].text(i - 0.19, v50[i] * 1.15, f"{20 * np.log10(v50[i] / v50[0]):.0f} dB", ha="center", fontsize=6)

# Apple Watch beat-by-beat RR comparison (vector trace in the Health export PDF).
try:
    import fitz
    import glob
    pdfp = (sys.argv[1:] or sorted(glob.glob(os.path.expanduser("~/Desktop/Health*EKG*.pdf"))))[0]
    MM = 72 / 25.4
    p = fitz.open(pdfp)[0]
    seg = []
    for d in p.get_drawings():
        c = d.get("color")
        if c and c[0] > 0.7 and c[1] < 0.2:
            for it in d["items"]:
                if it[0] == "l":
                    seg += [(it[1].x, it[1].y), (it[2].x, it[2].y)]
    seg = np.unique(np.array(seg), axis=0)
    tw = np.arange(0, 30, 1 / 512)
    w = np.full_like(tw, np.nan)
    for r, y0 in enumerate([218.5, 323.0, 427.6]):
        q = seg[(seg[:, 1] > y0) & (seg[:, 1] < y0 + 86.2)]
        q = q[np.argsort(q[:, 0])]
        tt = (q[:, 0] - 39.75) / (25 * MM) + 10 * r
        if r == 0:
            q, tt = q[tt > 0.45], tt[tt > 0.45]
        sel = (tw >= tt.min()) & (tw <= tt.max())
        w[sel] = np.interp(tw[sel], tt, -(q[:, 1] - np.median(q[:, 1])) / (10 * MM))
    ok = ~np.isnan(w)
    tw, w = tw[ok], w[ok]
    b = monitor(ecg_csv("5_apple_watch_parallel.csv"))
    wf = ss.sosfiltfilt(ss.butter(2, [0.5, 40], "bp", fs=512, output="sos"), w)
    kb = ss.find_peaks(b, height=0.5 * np.percentile(b, 99), distance=400)[0] / 1000
    kw = ss.find_peaks(wf, height=0.5 * np.percentile(wf, 99), distance=205)[0] / 512
    kb = kb[kb < 74]
    rb, rw = np.diff(kb), np.diff(kw)
    best = min(range(len(rb) - len(rw) + 1), key=lambda i: np.mean(np.abs(rb[i:i + len(rw)] - rw)))
    err = (rb[best:best + len(rw)] - rw) * 1e3
    ax[2].plot(rw * 1e3, "o-", color=C2, ms=3, lw=1, label="Apple Watch (lead I)")
    ax[2].plot(rb[best:best + len(rw)] * 1e3, "s--", color=C1, ms=2.5, lw=1, label="Wireless BERA")
    ax[2].set_title(f"(c) RR vs. Apple Watch\nΔ = {err.mean():+.1f} ± {err.std():.1f} ms", fontsize=8)
    ax[2].set_xlabel("beat")
    ax[2].set_ylabel("RR interval (ms)")
    ax[2].set_ylim(730, 1090)
    ax[2].legend(frameon=False, loc="lower right", fontsize=6.3)
except Exception as e:                                          # export PDF not available
    print("Apple Watch panel skipped:", e)
save(fig, "fig_ecg_drl.pdf")


# --------------------------------------------------------------------------- ABR
def bera_load(name):
    d = np.load(os.path.join(BERA, name))
    fs, decim = float(d["fs"]), int(d["decim"])
    stim = json.loads(str(d["stimulus"]))
    valid = d["valid"]
    uv = -d["ch2"].astype(float) / 32768 * FS_VPEAK / GAIN * 1e6
    uv[~valid] = 0.0
    L = int(48000 / stim["rate_hz"]) // decim
    hp = ss.sosfiltfilt(ss.butter(4, 300, "hp", fs=fs, output="sos"), uv)
    n2 = len(hp) // (2 * L)
    f2 = hp[:n2 * 2 * L].reshape(n2, 2 * L).mean(axis=0)
    D = int(np.argmax(np.abs(f2[:L] - f2[L:])))
    return dict(fs=fs, uv=uv, valid=valid, L=L, D=D)


def bera_epochs(r, lo=100, hi=1500, reject=25.0):
    fs, L, D = r["fs"], r["L"], r["D"]
    y = ss.sosfiltfilt(ss.butter(2, [lo, hi], "bp", fs=fs, output="sos"), r["uv"])
    for k in range(1, int(hi // 50) + 2):
        y = ss.filtfilt(*ss.iirnotch(50.0 * k, 50.0 * k / 4.0, fs), y)
    pre, post = int(0.002 * fs), int(0.012 * fs)
    on = D + np.arange(1, (len(y) - D - post) // L) * L
    g = int(0.01 * fs)
    good = np.array([r["valid"][o - pre - g:o + post + g].all() for o in on])
    ep = np.stack([y[o - pre:o + post] for o in on])
    ok = good & (np.abs(ep[:, pre:]).max(axis=1) < reject)
    m = len(ok) // 2 * 2
    keep = np.repeat(ok[0:m:2] & ok[1:m:2], 2)
    E = ep[:m][keep]
    nb = len(E) // 64
    sd = E[:nb * 64].reshape(nb, 64, -1).std(axis=(1, 2))
    E = E[:nb * 64][np.repeat(sd < 1.5 * np.median(sd), 64)]
    return np.arange(-pre, post) / fs * 1e3, E, y


def perm(t, E, n=1000):
    w = (t >= 1) & (t <= 10)
    obs = np.std(E.mean(0)[w])
    P = E.reshape(-1, 2, E.shape[1]).sum(1)
    null = np.array([np.std((rng.choice([-1.0, 1.0], len(P)) @ P)[w] / len(E)) for _ in range(n)])
    return obs, null, (1 + np.sum(null >= obs)) / (1 + n)


runs = {}
for key, f in [("r2", "2_click_amp0.05_21Hz.npz"), ("r4", "4_sham_click_amp0.035_earbud_out.npz"),
               ("r1", "1_click_amp0.10_21Hz.npz")]:
    r = bera_load(f)
    t, E, y = bera_epochs(r)
    obs, null, p = perm(t, E)
    noise = np.std(((E[0::2] - E[1::2]) / 2).mean(0)[(t >= 1) & (t <= 10)])
    runs[key] = dict(t=t, E=E, avg=E.mean(0), obs=obs, null=null, p=p, noise=noise, r=r, y=y)
    print(key, len(E), f"p={p:.3f}", f"noise={noise * 1e3:.0f} nV")

fig, ax = plt.subplots(1, 3, figsize=(7.1, 2.15), gridspec_kw=dict(width_ratios=[1.45, 1.0, 1.0], wspace=0.36))
R2, R4 = runs["r2"], runs["r4"]
a = ax[0]
a.fill_between(R2["t"], -2 * R2["noise"] * 1e3, 2 * R2["noise"] * 1e3, color="#dddddd", lw=0, label="±2σ residual noise")
a.plot(R4["t"], R4["avg"] * 1e3, color=C2, lw=1.0, label=f"control: earbud out, N = {len(R4['E'])}")
a.plot(R2["t"], R2["avg"] * 1e3, color=C1, lw=1.6, label=f"click 0.05, earbud in, N = {len(R2['E'])}")
a.axvline(0, color="k", lw=0.6)
m = (R2["t"] > 4.5) & (R2["t"] < 8)
iv = np.argmax(R2["avg"][m])
tv, av = R2["t"][m][iv], R2["avg"][m][iv] * 1e3
a.annotate(f"V  {tv:.1f} ms", xy=(tv, av), xytext=(tv + 1.4, av + 40), fontsize=7,
           arrowprops=dict(arrowstyle="-", lw=0.6))
a.set_xlim(-2, 12)
a.set_ylim(-190, 380)
a.set_xlabel("time after click (ms)")
a.set_ylabel("nV")
a.set_title("(a) averaged response, 100–1500 Hz")
a.legend(frameon=False, loc="upper left", fontsize=6.0, ncol=1, borderaxespad=0.1)

a = ax[1]
E = R2["E"]
a.plot(R2["t"], E[0::2].mean(0) * 1e3, color=C1, lw=1.1, label="polarity A")
a.plot(R2["t"], E[1::2].mean(0) * 1e3, color=C3, lw=1.1, label="polarity B")
a.axvline(0, color="k", lw=0.6)
a.set_xlim(-2, 12)
a.set_ylim(-300, 340)
a.set_xlabel("time after click (ms)")
a.set_title("(b) click polarities separately")
a.legend(frameon=False, loc="upper left", fontsize=6.3)

a = ax[2]
bins = np.linspace(0, 110, 45)
a.hist(R2["null"] * 1e3, bins=bins, color=C1, alpha=0.45, label="null, click")
a.hist(R4["null"] * 1e3, bins=bins, color=C2, alpha=0.45, label="null, control")
a.axvline(R2["obs"] * 1e3, color=C1, lw=1.6)
a.axvline(R4["obs"] * 1e3, color=C2, lw=1.6)
top = a.get_ylim()[1]
a.text(R2["obs"] * 1e3 + 2, top * 0.55, f"click\np = {R2['p']:.3f}", color=C1, fontsize=6.3)
a.text(R4["obs"] * 1e3 - 2, top * 0.72, f"control\np = {R4['p']:.2f}", color=C2, fontsize=6.3, ha="right")
a.set_xlabel("rms 1–10 ms (nV)")
a.set_ylabel("count")
a.set_title("(c) permutation test")
save(fig, "fig_abr.pdf")


# --------------------------------------------------------------------------- noise drivers
fig, ax = plt.subplots(2, 1, figsize=(3.45, 3.9), gridspec_kw=dict(hspace=0.55))
cols = {"r1": C4, "r2": C1, "r4": C2}
labels = {"r1": "run 1, seated", "r2": "run 2, lying", "r4": "run 4, lying (control)"}
for k in ("r1", "r2", "r4"):
    r = runs[k]["r"]
    fs, L = r["fs"], r["L"]
    y = ss.sosfiltfilt(ss.butter(2, [100, 1500], "bp", fs=fs, output="sos"), r["uv"])
    emg = ss.sosfiltfilt(ss.butter(2, [30, 300], "bp", fs=fs, output="sos"), r["uv"])
    blk = 64 * L
    n = len(y) // blk
    sd, em, tb = [], [], []
    for i in range(n):
        sl = slice(i * blk, (i + 1) * blk)
        v = r["valid"][sl]
        if v.mean() < 0.9:
            continue
        sd.append(np.std(y[sl][v]))
        em.append(np.std(emg[sl][v]))
        tb.append((i + 0.5) * blk / fs)
    sd, em, tb = map(np.array, (sd, em, tb))
    ax[0].plot(tb, sd, color=cols[k], lw=1.1, label=labels[k])
    ax[1].scatter(em, sd, s=5, color=cols[k], alpha=0.7, lw=0)
    runs[k]["blk"] = (em, sd)
allx = np.log(np.concatenate([runs[k]["blk"][0] for k in cols]))
ally = np.log(np.concatenate([runs[k]["blk"][1] for k in cols]))
r2 = np.corrcoef(allx, ally)[0, 1] ** 2
ax[0].set_yscale("log")
ax[0].set_yticks([2, 3, 5, 10, 20], ["2", "3", "5", "10", "20"])
ax[0].set_xlabel("time in run (s)")
ax[0].set_ylabel("sweep SD, 100–1500 Hz (µV)")
ax[0].set_title("(a) noise per 64-sweep block")
ax[0].legend(frameon=False, loc="upper right", fontsize=6.3)
ax[1].set_ylabel("sweep SD (µV)")
ax[1].set_xscale("log")
ax[1].set_yscale("log")
ax[1].set_xticks([2, 5, 10, 20], ["2", "5", "10", "20"])
ax[1].set_yticks([2, 3, 5, 10, 20], ["2", "3", "5", "10", "20"])
ax[1].set_xlabel("EMG 30–300 Hz rms (µV)")
ax[1].set_title(f"(b) sweep noise vs. EMG, R² = {r2:.2f}")
save(fig, "fig_noise.pdf")
