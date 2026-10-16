"""Headset-microphone channel (CH1) of the 2026-10-16 BERA runs: background
sounds, announcements, the click as heard by the mic, mic quality, audio export.

Usage: analysis_mic_audio.py [data_dir] [fig_dir] [audio_dir]

CH1 counts -> volts at the codec: ch1 / 32768 * 2.8284.  dBFS here is
20*log10(rms / 32768), i.e. relative to a full-scale DC/peak value.
Lost Wi-Fi packets (valid == False) are zeroed after DC removal and excluded
from every RMS / average.
"""
import json
import os
import sys
import wave

import numpy as np
import scipy.signal as ss
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "2026-10-16_bera")
FIG = sys.argv[2] if len(sys.argv) > 2 else os.path.join(DATA, "analysis")
AUD = sys.argv[3] if len(sys.argv) > 3 else os.path.expanduser("~/Desktop/WirelessBERA_Audio")
os.makedirs(FIG, exist_ok=True)
os.makedirs(AUD, exist_ok=True)

C = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
GREY = "#8a8a8a"
FS = 24000
L = 1137                       # click period at 24 kHz (2274 frames at 48 kHz)
L2 = 2 * L                     # alternating polarity: the pattern repeats every two clicks
VFS = 2.8284                   # volts per full scale at the codec
plt.rcParams.update({"font.size": 9, "axes.titlesize": 10, "axes.titleweight": "bold",
                     "axes.spines.top": False, "axes.spines.right": False})

RUNS = {
    0: ("0_rest_no_stimulus.npz", "Lauf 0 – Ruhe, sitzend, kein Reiz"),
    1: ("1_click_amp0.10_21Hz.npz", "Lauf 1 – Klick 0,10, sitzend"),
    2: ("2_click_amp0.05_21Hz.npz", "Lauf 2 – Klick 0,05, liegend"),
    3: ("3_click_sham_toneburst_continuous.npz", "Lauf 3 – A Klick 0,035 | B Schein | C Tonburst"),
    4: ("4_sham_click_amp0.035_earbud_out.npz", "Lauf 4 – Klick 0,035, Ohrhörer neben dem Kopf"),
}


def db(x):
    return 20 * np.log10(np.maximum(x, 1e-12))


def load(k):
    d = np.load(os.path.join(DATA, RUNS[k][0]))
    v = d["valid"].astype(bool)
    x = d["ch1"].astype(float)
    x -= np.median(x[v])
    x[~v] = 0.0
    uv = -d["ch2"].astype(float) / 32768 * VFS / 16 * 1e6
    uv -= np.median(uv[v])
    uv[~v] = 0.0
    log = []
    lp = os.path.join(DATA, RUNS[k][0].replace(".npz", ".log"))
    if os.path.exists(lp):
        for line in open(lp):
            p = line.split()
            if p and p[0][:1].isdigit() and "." in p[0] and len(p[0]) > 12:
                log.append((float(p[0]) - float(d["t_start"]), " ".join(p[1:])))
    return dict(x=x, uv=uv, v=v, t0=float(d["t_start"]), stim=json.loads(str(d["stimulus"])), log=log,
                n=len(x))


def blocks(k, r):
    """(label, i0, i1) stimulus blocks. Run 3 is split at the log marks."""
    if k == 3:
        m = [t for t, _ in r["log"]]
        cut = [int(t * FS) for t in m[1:3]]
        return [("3A", 0, cut[0]), ("3B", cut[0], cut[1]), ("3C", cut[1], r["n"])]
    if k == 0:
        return [("0", 0, r["n"])]
    return [(str(k), 0, r["n"])]


def fold(x, v, i0, i1):
    """Average over whole 2-click periods (grid anchored at sample 0) within [i0, i1).
    Periods whose rms exceeds 4x the median (rustling, speech) are left out."""
    a = -(-i0 // L2)
    b = i1 // L2
    e = x[a * L2:b * L2].reshape(-1, L2)
    w = v[a * L2:b * L2].reshape(-1, L2).astype(float)
    if len(e) == 0:
        return np.zeros(L2), 0
    rms = np.sqrt((e ** 2 * w).sum(1) / np.maximum(w.sum(1), 1))
    keep = rms <= 4 * np.median(rms)
    w = w * keep[:, None]
    return (e * w).sum(0) / np.maximum(w.sum(0), 1), int(keep.sum())


def remove_clicks(x, v, i0, i1, chunk_s=20.0):
    """Subtract the click-locked 2-period template inside [i0, i1), estimated in ~20 s chunks so that
    slow changes (earbud moving, run 4) are followed."""
    y = x.copy()
    step = max(int(chunk_s * FS) // L2, 1) * L2
    edges = list(range(i0, i1, step)) + [i1]
    if len(edges) > 2 and edges[-1] - edges[-2] < step // 2:
        edges.pop(-2)                      # merge a short tail into the previous chunk
    for a, b in zip(edges[:-1], edges[1:]):
        t, n = fold(x, v, a, b)
        if n < 20:
            t, n = fold(x, v, i0, i1)
        idx = np.arange(a, b)
        y[a:b] -= t[idx % L2] * v[a:b]
    return y


def level(x, v, win=2400):
    k = len(x) // win
    e = x[:k * win].reshape(k, win)
    w = v[:k * win].reshape(k, win)
    ms = (e ** 2 * w).sum(1) / np.maximum(w.sum(1), 1)
    ms[w.sum(1) < win / 4] = np.nan
    return np.arange(k) * win / FS + win / FS / 2, np.sqrt(ms)


def hp(x, f=80, order=4):
    return ss.sosfiltfilt(ss.butter(order, f, "hp", fs=FS, output="sos"), x)


def bp(x, lo, hi, order=4):
    return ss.sosfiltfilt(ss.butter(order, [lo, hi], "bp", fs=FS, output="sos"), x)


def specgram(ax, x, v, t_off=0.0, fmax=12000, nper=1024, vmin=-150, vmax=-95, cmap="magma", hop=None):
    hop = nper // 2 if hop is None else hop
    f, t, S = ss.spectrogram(x / 32768, FS, window="hann", nperseg=nper, noverlap=nper - hop,
                             scaling="density", mode="psd")
    S = 10 * np.log10(S + 1e-30)
    m = f <= fmax
    im = ax.imshow(S[m], origin="lower", aspect="auto", cmap=cmap, vmin=vmin, vmax=vmax,
                   extent=[t[0] + t_off, t[-1] + t_off, 0, f[m][-1] / 1000], interpolation="nearest")
    return im


def clean_for_listening(x, v):
    """Notch 50 Hz harmonics and 187.5 Hz family, high-pass 80 Hz."""
    y = hp(x, 80)
    for f0 in [50 * k for k in range(1, 8)] + [187.5 * k for k in range(1, 5)]:
        b, a = ss.iirnotch(f0, 30, FS)
        y = ss.filtfilt(b, a, y)
    y[~v] = 0.0
    return y


def spectral_gate(y, v, strength=0.6):
    """Gentle stationary noise reduction (spectral subtraction with a floor)."""
    f, t, Z = ss.stft(y, FS, nperseg=1024, noverlap=768)
    mag = np.abs(Z)
    noise = np.percentile(mag, 20, axis=1, keepdims=True)
    gain = np.maximum(1 - strength * (noise / np.maximum(mag, 1e-12)) ** 2, 0.25)
    gain = ss.medfilt2d(gain, (3, 5))
    _, z = ss.istft(Z * gain, FS, nperseg=1024, noverlap=768)
    z = z[:len(y)]
    z[~v] = 0.0
    return z


def write_wav(name, y, v, peak_db=-3.0):
    y = y.copy()
    y[~v] = 0.0
    pk = np.max(np.abs(y))
    g = 10 ** (peak_db / 20) * 32767 / pk if pk > 0 else 1.0
    s = np.clip(np.round(y * g), -32768, 32767).astype("<i2")
    fade = int(0.02 * FS)
    ramp = np.linspace(0, 1, fade)
    s[:fade] = (s[:fade] * ramp).astype("<i2")
    s[-fade:] = (s[-fade:] * ramp[::-1]).astype("<i2")
    p = os.path.join(AUD, name)
    with wave.open(p, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(FS)
        w.writeframes(s.tobytes())
    return p, g, os.path.getsize(p)


def savefig(fig, name):
    p = os.path.join(FIG, name)
    fig.savefig(p, dpi=130)
    plt.close(fig)
    print("  ->", p)


def find_events(t, lv, base, thr_db=8.0, min_gap=0.5):
    hi = db(lv) > db(base) + thr_db
    hi &= np.isfinite(lv)
    ev = []
    i = 0
    dt = t[1] - t[0]
    gap = int(min_gap / dt)
    while i < len(hi):
        if hi[i]:
            j = i
            while j < len(hi) and hi[j:j + gap].any():
                j += 1
            ev.append((t[i] - dt / 2, t[min(j, len(t) - 1)] - dt / 2, db(np.nanmax(lv[i:j])) - db(base)))
            i = j
        else:
            i += 1
    return ev


def band_fracs(x, v, a, b):
    seg = x[int(a * FS):int(b * FS)]
    f, p = ss.welch(seg, FS, nperseg=min(2048, len(seg)))
    tot = p[(f > 80)].sum()
    lo = p[(f > 80) & (f < 300)].sum() / tot
    mid = p[(f >= 300) & (f < 3400)].sum() / tot
    hi_ = p[(f >= 3400)].sum() / tot
    cen = (f[f > 80] * p[f > 80]).sum() / tot
    return lo, mid, hi_, cen


# ---------------------------------------------------------------------------
print("Lade Läufe ...")
R = {k: load(k) for k in RUNS}
for k, r in R.items():
    r["blocks"] = blocks(k, r)
    y = r["x"].copy()
    if k != 0:
        for _, a, b in r["blocks"]:
            y = remove_clicks(y, r["v"], a, b)
    r["xc"] = y                      # clicks removed
    r["xh"] = hp(y, 80) * r["v"]     # clicks removed + 80 Hz high-pass
    r["xs"] = bp(y, 300, 3400) * r["v"]  # speech band
    t, lv = level(r["x"], r["v"])
    _, lvh = level(r["xh"], r["v"])
    _, lvs = level(r["xs"], r["v"])
    r["lev"] = (t, lv, lvh, lvs)
    r["base"] = np.nanmedian(lvh)
    r["base_s"] = np.nanmedian(lvs)
    print(f"Lauf {k}: {r['n'] / FS:.1f} s, gültig {100 * r['v'].mean():.1f} %, Pegel roh median "
          f"{db(np.nanmedian(lv) / 32768):.1f} dBFS, nach HP/Klickentf. {db(r['base'] / 32768):.1f} dBFS, "
          f"Sprachband {db(r['base_s'] / 32768):.1f} dBFS, max (100 ms) {db(np.nanmax(lvh) / 32768):.1f} dBFS")

# ---------------------------------------------------------------------------
# 1. Click-locked average (electrical crosstalk + acoustic part)
print("\nKlick-gemittelte Antwort ...")
CL = {}
for k in (1, 2, 3, 4):
    r = R[k]
    for lab, a, b in r["blocks"]:
        hx = hp(r["x"][a:b], 100, 2)
        hu = hp(r["uv"][a:b], 100, 2)
        vv = r["v"][a:b]
        # keep the same absolute grid: pad so that local index matches global index mod L2
        off = a % L2
        hx = np.r_[np.zeros(off), hx]
        hu = np.r_[np.zeros(off), hu]
        vv = np.r_[np.zeros(off, bool), vv]
        t1, n1 = fold(hx, vv, off, len(hx))
        t2, _ = fold(hu, vv, off, len(hu))
        CL[lab] = dict(alt1=(t1[:L] - t1[L:]) / 2, sum1=(t1[:L] + t1[L:]) / 2,
                       alt2=(t2[:L] - t2[L:]) / 2, n=2 * n1, amp=r["stim"]["amplitude"])
# reference phase: largest CH1 spike of block 3A / run 1 etc.; 3B uses 3A's phase
for lab in CL:
    ref = "3A" if lab in ("3B",) else lab
    CL[lab]["p0"] = int(np.argmax(np.abs(CL[ref]["alt1"])))
# 3C: tone burst, search its own phase in CH1 (may be absent)
amps = {"1": 0.10, "2": 0.05, "3A": 0.035, "3B": 0.035, "3C": 0.01, "4": 0.035}


def aligned(lab, key, pre=24, post=120):
    a = CL[lab][key]
    p = CL[lab]["p0"]
    idx = (np.arange(p - pre, p + post)) % L
    s = np.sign(CL[lab]["alt1"][CL[lab]["p0"]]) if lab != "3B" else np.sign(CL["3A"]["alt1"][CL["3A"]["p0"]])
    if lab == "3C":
        s = 1.0
    return a[idx] * s, (np.arange(-pre, post)) / FS * 1e3


for lab in CL:
    a, _ = aligned(lab, "alt1")
    nz = np.median(np.abs(CL[lab]["alt1"])) * 1.4826
    CL[lab]["pk"] = a[24]
    CL[lab]["pp"] = a.max() - a.min()
    CL[lab]["noise"] = nz
    print(f"  {lab}: N = {CL[lab]['n']} Klicks, CH1 Spitze {a[24]:+.2f} counts, p-p {a.max() - a.min():.2f}, "
          f"Rest-Rauschen {nz:.3f} counts")

# acoustic residual: run 4 (earbud out) minus block 3A (same amplitude, earbud in)
a4, tms = aligned("4", "alt1")
a3, _ = aligned("3A", "alt1")
a1, _ = aligned("1", "alt1")
a2, _ = aligned("2", "alt1")
res4 = a4 - a3
res1 = a1 - a3 * 0.10 / 0.035
res2 = a2 - a3 * 0.05 / 0.035
# electrical template from in-ear runs, scaled with amplitude: check linearity
el = np.vstack([a1 / 0.10, a2 / 0.05, a3 / 0.035])
lin_dev = np.std(el[:, 20:30], axis=0).max() / np.abs(el[:, 24]).mean()
nz4 = np.sqrt(CL["4"]["noise"] ** 2 + CL["3A"]["noise"] ** 2)
# onset: first time after the electrical spike onset where the (8x upsampled) residual exceeds
# 10 % of its maximum; samples 0..2 hold the electrical on/off edges and subtract to ~0.
up = ss.resample_poly(res4, 8, 1)
tup = (np.arange(len(up)) / 8 - 24) / FS * 1e3
j = np.where((tup > 0.04) & (np.abs(up) > 0.1 * np.abs(up).max()))[0][0]
onset_ms = tup[j]
on4 = on20 = 24 + int(round(onset_ms * FS / 1e3))
f_ring = None
seg = res4[28:28 + 96]
sp = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), 4096))
fr = np.fft.rfftfreq(4096, 1 / FS)
f_ring = fr[np.argmax(sp * (fr > 500))]
print(f"  Linearität elektrisch: Abweichung {100 * lin_dev:.1f} % (Spitze/Amplitude)")
print(f"  Akustischer Rest Lauf 4: Spitze {np.abs(res4).max():.2f} counts, Rauschen {nz4:.3f}, "
      f"Einsatz (10 % der Spitze) {onset_ms:.3f} ms -> Luftweg {onset_ms * 0.343 * 100:.1f} cm, "
      f"Hauptfrequenz {f_ring:.0f} Hz")
print(f"  Rest Lauf 1 / 2 (im Ohr): Spitze {np.abs(res1[28:]).max():.2f} / {np.abs(res2[28:]).max():.2f} counts")
ac_rms = {lab: np.sqrt(np.mean(r_[28:28 + 72] ** 2)) for lab, r_ in
          (("1", res1), ("2", res2), ("4", res4))}
print("  akustischer Rest rms 0,2-3,2 ms:", {k_: round(v_, 3) for k_, v_ in ac_rms.items()})

# --- figure: click waveforms
fig, ax = plt.subplots(2, 1, figsize=(10, 7), sharex=True, gridspec_kw=dict(height_ratios=[2, 1]))
for i, lab in enumerate(["1", "2", "3A", "4"]):
    a, tt = aligned(lab, "alt1")
    ax[0].plot(tt, a, color=C[i], lw=1.4,
               label=f"{lab}: Amplitude {amps[lab]}{' (Ohrhörer draußen)' if lab == '4' else ''}, N = {CL[lab]['n']}")
for lab, ls in (("3B", "--"), ("3C", ":")):
    a, tt = aligned(lab, "alt1")
    ax[0].plot(tt, a, color=GREY, lw=1.2, ls=ls,
               label=f"{lab}: {'Schein (offener rechter Kanal)' if lab == '3B' else 'Tonburst 2 kHz, 0,01'}")
ax[0].axvline(0, color="k", lw=0.5)
ax[0].set_ylabel("CH1 (counts, ±-Differenz)")
ax[0].set_title("Klick-gemittelte Mikrofonspur: elektrisches Übersprechen + akustischer Anteil", loc="left")
ax[0].legend(frameon=False, fontsize=8, loc="upper right")
ax[0].grid(alpha=0.3)
for i, lab in enumerate(["1", "2", "3A", "4"]):
    a, tt = aligned(lab, "alt2")
    ax[1].plot(tt, a, color=C[i], lw=1.2, label=lab)
ax[1].axvline(0, color="k", lw=0.5)
ax[1].set_ylabel("CH2 (µV, ±-Differenz)")
ax[1].set_xlabel("Zeit relativ zum Klickbeginn im Mikrofonkanal (ms)")
ax[1].set_title("Gleichzeitiges Reizartefakt im Biosignal (CH2)", loc="left")
ax[1].legend(frameon=False, fontsize=8, ncol=4, loc="upper right")
ax[1].grid(alpha=0.3)
ax[1].set_xlim(-1, 5)
fig.tight_layout()
savefig(fig, "mic_04_klick_gemittelt.png")

# --- figure: acoustic residual and linearity
fig, ax = plt.subplots(1, 2, figsize=(11, 4.2), gridspec_kw=dict(width_ratios=[1.6, 1]))
ax[0].plot(tms, a4, color=GREY, lw=1, label="Lauf 4 gesamt (Ohrhörer draußen)")
ax[0].plot(tms, res4, color=C[1], lw=1.6, label="Lauf 4 − Block 3A = akustischer Anteil")
ax[0].plot(tms, res2 * 0.035 / 0.05, color=C[0], lw=1.2,
           label="Lauf 2 − skaliertes 3A (im Ohr), auf 0,035 skaliert")
ax[0].axvline(0, color="k", lw=0.5)
ax[0].axvline(onset_ms, color=C[2], lw=1, ls="--")
ax[0].text(onset_ms + 0.08, -4.6, f"akust. Einsatz ≈ {onset_ms:.2f} ms ≈ {onset_ms * 34.3:.0f} cm Luftweg\n"
           f"Nachschwingen ≈ {f_ring / 1000:.1f} kHz", color=C[2], fontsize=8, va="bottom")
ax[0].set_xlim(-0.5, 4.5)
ax[0].set_xlabel("Zeit nach Klickbeginn (ms)")
ax[0].set_ylabel("CH1 (counts)")
ax[0].set_title("Akustischer Klick am Mikrofon (elektrischer Anteil abgezogen)", loc="left")
ax[0].legend(frameon=False, fontsize=8, loc="upper right")
ax[0].grid(alpha=0.3)
xs = np.array([0.035, 0.05, 0.10])
ys = np.array([abs(CL["3A"]["pk"]), abs(CL["2"]["pk"]), abs(CL["1"]["pk"])])
kfit = np.sum(xs * ys) / np.sum(xs ** 2)
xx = np.linspace(0.005, 0.12, 50)
ax[1].plot(xx, kfit * xx, color=GREY, lw=1, ls="--", label=f"Gerade durch 0: {kfit:.0f} counts/Amplitude")
for i, (lab, xv, yv) in enumerate(zip(["3A", "2", "1"], xs, ys)):
    ax[1].plot(xv, yv, "o", color=C[[2, 1, 0][i]], ms=7)
    ax[1].annotate(f"{lab}: {yv:.2f}", (xv, yv), textcoords="offset points", xytext=(6, -12), fontsize=8)
ax[1].plot(0.035, abs(CL["4"]["pk"]), "s", color=C[3], ms=7)
ax[1].annotate(f"4 (draußen): {abs(CL['4']['pk']):.2f}", (0.035, abs(CL["4"]["pk"])), textcoords="offset points",
               xytext=(6, 4), fontsize=8)
ax[1].plot(0.035, abs(CL["3B"]["pk"]), "x", color="k", ms=7)
ax[1].annotate(f"3B Schein: {abs(CL['3B']['pk']):.2f}", (0.035, abs(CL["3B"]["pk"])), textcoords="offset points",
               xytext=(6, 2), fontsize=8)
ax[1].set_xlim(0, 0.12)
ax[1].set_ylim(-1, 23)
ax[1].set_xlabel("DAC-Amplitude")
ax[1].set_ylabel("|Spitze| elektrischer Spike (counts)")
ax[1].set_title("Linearität des Übersprechens", loc="left")
ax[1].legend(frameon=False, fontsize=8, loc="upper left")
ax[1].grid(alpha=0.3)
fig.tight_layout()
savefig(fig, "mic_05_klick_akustisch_linear.png")

# --- per-10-s click monitor: electrical spike and acoustic residual energy over time
print("\nKlick-Monitor über die Zeit ...")
BLK = int(10 * FS) // L2 * L2
tmpl_el = a3 / CL["3A"]["pk"]           # unit electrical template (in ear, contains tiny leakage)
fig, ax = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
mon = {}
for i, k in enumerate((1, 2, 3, 4)):
    r = R[k]
    hx = hp(r["x"], 100, 2)
    out_t, out_e, out_a = [], [], []
    for s0 in range(0, r["n"] - BLK, BLK):
        tt_, nn = fold(hx, r["v"], s0, s0 + BLK)
        alt = (tt_[:L] - tt_[L:]) / 2
        lab = "3A" if k == 3 else str(k)
        p = CL[lab]["p0"]
        idx = (np.arange(p - 24, p + 120)) % L
        seg_ = alt[idx]
        sgn = np.sign(CL[lab]["alt1"][p]) if k != 3 else np.sign(CL["3A"]["alt1"][p])
        seg_ = seg_ * sgn
        el_amp = seg_[24]
        resid = seg_ - el_amp * tmpl_el
        out_t.append((s0 + BLK / 2) / FS)
        out_e.append(abs(el_amp))
        out_a.append(np.sqrt(np.mean(resid[28:100] ** 2)))
    mon[k] = (np.array(out_t), np.array(out_e), np.array(out_a))
    tm_, e_, a_m = mon[k]
    okc = np.ones(len(tm_), bool) if k != 3 else tm_ < R[3]["log"][2][0]
    ax[0].plot(tm_[okc], e_[okc], "o-", color=C[i], ms=3, lw=1, label=RUNS[k][1])
    ax[1].plot(tm_[okc], a_m[okc], "o-", color=C[i], ms=3, lw=1, label=RUNS[k][1])
    if k == 3:
        ax[0].plot(tm_[~okc], e_[~okc], "o-", color=GREY, ms=2, lw=0.8)
        ax[1].plot(tm_[~okc], a_m[~okc], "o-", color=GREY, ms=2, lw=0.8)
        ax[1].text(560, 0.53, "3C Tonburst: anderer Reiz,\nKlick-Template passt nicht", color=GREY,
                   fontsize=8, ha="center", va="bottom")
for t_, lab in R[3]["log"][1:3]:
    ax[0].axvline(t_, color=C[2], lw=0.6, ls=":")
    ax[0].text(t_ + 3, 15, "3" + lab.split()[0], color=C[2], fontsize=8)
ax[0].set_ylabel("elektr. Spike (counts)")
ax[0].set_title("Klickmonitor je 10 s: elektrischer Spike (= Strom fließt durch den Ohrhörer)", loc="left")
ax[0].legend(frameon=False, fontsize=7.5, loc="upper right")
ax[1].set_ylabel("akust. Rest rms 0,2–3 ms (counts)")
ax[1].set_title("Akustischer Anteil nach Abzug des elektrischen Templates (= Schall erreicht das Mikrofon)",
                loc="left")
ax[1].set_xlabel("Zeit im Lauf (s)")
ax[1].annotate("Rascheln → Ohrhörer verlagert", (50, 0.82), xytext=(75, 0.62), fontsize=8, color=C[3],
               arrowprops=dict(arrowstyle="->", color=C[3], lw=0.8))
ax[1].annotate("Rascheln → Ohrhörer verlagert", (190, 0.36), xytext=(215, 0.3), fontsize=8, color=C[3],
               arrowprops=dict(arrowstyle="->", color=C[3], lw=0.8))
ax[1].text(330, 0.07, "im Ohr: ≈ Rauschgrenze (0,02–0,05)", fontsize=8, color=GREY)
ax[0].set_ylim(0, 24)
for a_ in ax:
    a_.grid(alpha=0.3)
fig.tight_layout()
savefig(fig, "mic_06_klickmonitor_zeitverlauf.png")
for k in mon:
    print(f"  Lauf {k}: elektr. {np.median(mon[k][1]):.2f} (Streuung {np.std(mon[k][1]):.2f}), "
          f"akust. rms median {np.median(mon[k][2]):.3f}")
if 3 in mon:
    t3, e3, a3m = mon[3]
    for lab, a, b in R[3]["blocks"]:
        m = (t3 * FS > a) & (t3 * FS < b)
        print(f"   {lab}: elektr. {np.median(e3[m]):.2f}, akust. {np.median(a3m[m]):.3f}")

# ---------------------------------------------------------------------------
# 2. Overview per run + events
print("\nÜbersicht und Ereignisse ...")
EVENTS = {}
for k in (0, 1, 2, 3, 4):
    r = R[k]
    t, lv, lvh, lvs = r["lev"]
    ev = find_events(t, lvh, r["base"], 8.0) if k else []
    evs = find_events(t, lvs, r["base_s"], 6.0, 1.0) if k else []
    EVENTS[k] = (ev, evs)
    print(f" Lauf {k}: Breitband-Ereignisse (> +8 dB):")
    for a, b, h in ev:
        lo, mid, hi_, cen = band_fracs(r["xh"], r["v"], max(a - 0.05, 0), b + 0.05)
        print(f"   {a:7.1f}–{b:7.1f} s  +{h:4.1f} dB  <300 Hz {lo:.2f}  300–3400 {mid:.2f}  >3400 {hi_:.2f}  "
              f"Schwerpunkt {cen:5.0f} Hz")
    print(f"  Sprachband-Ereignisse (> +6 dB): " + ", ".join(f"{a:.1f}–{b:.1f} s (+{h:.0f})" for a, b, h in evs))

# Manual classification after looking at every event spectrogram (see mic_03).
# Category -> colour: 0 speech/announcement, 1 rustle/movement, 2 body sound, 3 knock/handling
CAT = {0: ("Sprache / Ansage", C[0]), 1: ("Rascheln / Bewegung", C[1]),
       2: ("Körpergeräusch (Schlucken, Räuspern, Atem)", C[2]), 3: ("Klopfer / Handhabung", C[3])}
LABELS = {
    1: [(130.6, 131.1, "Husten/Räuspern?", 2), (131.6, 133.5, "", 2), (136.9, 138.6, "Rascheln", 1)],
    2: [(41.7, 42.0, "Knacken", 3), (54.2, 54.4, "Schlucken?", 2),
        (61.2, 72.0, "Unruhe: Rascheln", 1), (237.8, 238.0, "Schlucken?", 2)],
    3: [(0.3, 5.8, "Start: Klopfer, Handhabung", 3), (244.5, 248.8, "Ansage „Teil zwei“", 0),
        (450.7, 453.9, "Ansage „Teil drei“", 0), (467.5, 468.1, "Räuspern?", 2)],
    4: [(35.2, 39.3, "Rascheln", 1), (48.8, 52.9, "Rascheln (lautestes)", 1), (73.9, 74.5, "Atemzug?", 2),
        (106.3, 106.6, "Schlucken?", 2), (125.8, 126.3, "Schlucken?", 2), (184.2, 185.9, "Atem?", 2),
        (187.9, 188.5, "Rascheln", 1), (192.8, 193.4, "Rascheln", 1)],
}


def overview(k):
    r = R[k]
    t, lv, lvh, lvs = r["lev"]
    dur = r["n"] / FS
    w = 12 if dur > 30 else 9
    fig, ax = plt.subplots(3, 1, figsize=(w, 7.6), sharex=True,
                           gridspec_kw=dict(height_ratios=[1.3, 1.6, 0.65]))
    ax[0].plot(t, db(lv / 32768), color=GREY, lw=0.6, label="roh (nur DC entfernt)")
    ax[0].plot(t, db(lvh / 32768), color=C[0], lw=0.7,
               label=("Klicks entfernt, " if k else "") + "Hochpass 80 Hz")
    ax[0].plot(t, db(lvs / 32768), color=C[1], lw=0.7, label="Sprachband 300–3400 Hz")
    ax[0].axhline(db(r["base"] / 32768), color=C[0], lw=0.6, ls="--")
    ax[0].set_ylabel("Pegel 100 ms (dBFS)")
    ax[0].set_ylim(-112, max(-60, np.nanmax(db(lv / 32768)) + 4))
    ax[0].legend(frameon=False, fontsize=8, loc="upper right", ncol=3)
    ax[0].set_title(f"{RUNS[k][1]} – Mikrofon CH1, Pegelverlauf", loc="left")
    ax[0].grid(alpha=0.3)
    # window = two click periods, hop = one period (or two for long runs): no beat with the click rate
    im = specgram(ax[1], r["x"], r["v"], 0, 12000, L2, vmin=-150, vmax=-110, hop=L2 if dur > 300 else L)
    ax[1].set_ylabel("Frequenz (kHz)")
    ax[1].set_title("Spektrogramm roh " + ("(inkl. Klicks; Fenster = 2 Klickperioden)" if k else "(kein Reiz)")
                    + ", dB re FS²/Hz", loc="left")
    cb = fig.colorbar(im, cax=ax[1].inset_axes([1.005, 0.0, 0.012, 1.0]))
    cb.ax.tick_params(labelsize=7)
    for t_, lab in r["log"]:
        for a_ in ax[:2]:
            a_.axvline(t_, color="k" if a_ is ax[0] else "w", lw=0.8, ls=":")
    # event strip
    ax[2].set_ylim(0, 3)
    ax[2].set_yticks([])
    ax[2].spines["left"].set_visible(False)
    lvl = 0
    last_end = {0: -1e9, 1: -1e9, 2: -1e9}
    for a, b, txt, cat in LABELS.get(k, []):
        col = CAT[cat][1]
        for a_ in ax[:2]:
            a_.axvspan(a, b, color=col, alpha=0.18 if a_ is ax[0] else 0.0, lw=0)
        ax[2].axvspan(a, b, ymin=0.0, ymax=0.18, color=col)
        if txt:
            # pick the lowest text row that is free
            est = (len(txt) + 2) * dur * 0.0062
            free = [l_ for l_ in (0, 1, 2) if a > last_end[l_]]
            lvl = free[0] if free else min(last_end, key=last_end.get)
            last_end[lvl] = a + est
            ax[2].text(a, 0.6 + lvl * 0.8, txt, fontsize=7.5, color=col, va="bottom")
    for t_, lab in r["log"]:
        ax[2].axvline(t_, color="k", lw=0.8, ls=":")
    if not LABELS.get(k):
        ax[2].text(dur / 2, 1.2, "keine Ereignisse über +8 dB – nur Grundrauschen; dunkle Streifen = verlorene "
                   "WLAN-Pakete (6 %)", ha="center", fontsize=8, color=GREY)
    handles = [plt.Rectangle((0, 0), 1, 1, color=CAT[c][1]) for c in CAT]
    ax[2].legend(handles, [CAT[c][0] for c in CAT], frameon=False, fontsize=7, ncol=4, loc="upper center",
                 bbox_to_anchor=(0.5, -0.55))
    ax[2].set_xlabel("Zeit im Lauf (s)" + ("   (gepunktet: Blockwechsel laut Log)" if r["log"] else ""))
    ax[2].set_xlim(0, dur)
    fig.tight_layout()
    savefig(fig, f"mic_01_uebersicht_lauf{k}.png")


print("\nÜbersichtsgrafiken ...")
for k in (0, 1, 2, 3, 4):
    overview(k)

# --- announcements / speech zooms
print("\nAnsagen ...")
ZO = [(3, 238, 256, "Lauf 3: Ansage „Teil zwei …“ vor dem Wechsel A → B"),
      (3, 444, 460, "Lauf 3: Ansage „Teil drei …“ vor dem Wechsel B → C"),
      (3, 0, 10, "Lauf 3: Beginn (Glas-Ton nicht erkennbar; Klopfer)"),
      (4, 0, 10, "Lauf 4: Beginn (Countdown lag vor dem Start; 2,5-kHz-Band = Klick, Ohrhörer draußen)")]
fig, axs = plt.subplots(len(ZO), 1, figsize=(11, 2.3 * len(ZO)))
for ax_, (k, a, b, title) in zip(axs, ZO):
    r = R[k]
    i0, i1 = int(a * FS), min(int(b * FS), r["n"])
    src = r["xh"]
    im = specgram(ax_, src[i0:i1], r["v"][i0:i1], a, 5000, 1024, vmin=-148, vmax=-118)
    ax_.set_ylabel("kHz")
    ax_.set_title(title, loc="left")
    tw = ax_.twinx()
    t, _, _, lvs = r["lev"]
    m = (t >= a) & (t <= b)
    tw.plot(t[m], db(lvs[m] / 32768), color="#ffffff", lw=1.0)
    tw.set_ylim(-120, -70)
    tw.set_ylabel("Sprachband\n(dBFS, weiß)", fontsize=7.5)
    tw.tick_params(labelsize=7)
    for t_, lab in r["log"]:
        if a <= t_ <= b:
            ax_.axvline(t_, color=C[3], lw=1.5, ls="--")
            ax_.text(t_ + 0.15, 4.3, "Log: " + lab.split()[0] + " " + " ".join(lab.split()[1:3]), color=C[3],
                     fontsize=8)
    for la, lb, txt, cat in LABELS.get(k, []):
        if cat == 0 and la < b and lb > a:
            ax_.annotate("", xy=(la, 4.7), xytext=(lb, 4.7),
                         arrowprops=dict(arrowstyle="<->", color=C[0], lw=1.2))
    ax_.set_xlim(a, b)
axs[-1].set_xlabel("Zeit im Lauf (s)")
fig.tight_layout()
savefig(fig, "mic_02_ansagen_sprache.png")
for k, a, b in [(3, 244.5, 248.8), (3, 450.7, 453.9)]:
    r = R[k]
    s = r["xs"][int(a * FS):int(b * FS)]
    vv = r["v"][int(a * FS):int(b * FS)]
    lev_ = db(np.sqrt(np.mean(s[vv] ** 2)) / 32768)
    print(f"  Lauf {k} {a}–{b} s: Sprachband {lev_:.1f} dBFS, Grundrauschen {db(r['base_s'] / 32768):.1f} dBFS, "
          f"SNR {lev_ - db(r['base_s'] / 32768):.1f} dB")
for t_, lab in R[3]["log"]:
    print(f"  Log Lauf 3: {t_:8.2f} s  {lab}")
for t_, lab in R[4]["log"]:
    print(f"  Log Lauf 4: {t_:8.2f} s  {lab}")

# --- event catalogue
CATL = [(1, 130.9, "Lauf 1: Husten/Räuspern?", 2), (2, 41.85, "Lauf 2: Knacken (Kabel?)", 3),
        (2, 54.3, "Lauf 2: Schlucken?", 2), (2, 67.0, "Lauf 2: Unruhe, Rascheln", 1),
        (3, 467.8, "Lauf 3: Räuspern?", 2), (4, 37.0, "Lauf 4: Rascheln", 1),
        (4, 50.8, "Lauf 4: Rascheln (lautestes Ereignis)", 1), (4, 126.1, "Lauf 4: Schlucken?", 2),
        (4, 185.0, "Lauf 4: Atem?", 2)]
fig, axs = plt.subplots(3, 3, figsize=(12, 8.4))
for ax_, (k, tc, title, cat) in zip(axs.flat, CATL):
    r = R[k]
    i0, i1 = int((tc - 2) * FS), int((tc + 2) * FS)
    specgram(ax_, r["xc"][i0:i1], r["v"][i0:i1], tc - 2, 8000, 512, vmin=-150, vmax=-100)
    seg = r["xh"][int((tc - 0.6) * FS):int((tc + 0.6) * FS)]
    pk = db(np.max(np.abs(seg)) / 32768)
    ax_.set_title(title, loc="left", color=CAT[cat][1], fontsize=9)
    ax_.text(0.98, 0.95, f"Spitze {pk:.0f} dBFS", transform=ax_.transAxes, ha="right", va="top", color="w",
             fontsize=8)
    ax_.set_ylabel("kHz")
    ax_.set_xlabel("s")
fig.suptitle("Ereigniskatalog Mikrofon (Klicks entfernt, Spektrogramm 0–8 kHz, ±2 s)", x=0.01, ha="left",
             fontweight="bold")
fig.tight_layout()
savefig(fig, "mic_03_ereigniskatalog.png")

# ---------------------------------------------------------------------------
# 3. Mic quality: noise spectrum, hum lines, coherence with CH2
print("\nRauschspektrum ...")


def quiet_mask(k):
    r = R[k]
    m = r["v"].copy()
    for a, b, *_ in LABELS.get(k, []):
        m[max(int((a - 1) * FS), 0):int((b + 1) * FS)] = False
    return m


def psd(x, m, nper=24000):
    """Welch PSD over segments that are completely valid/quiet."""
    acc, n = 0, 0
    for i in range(0, len(x) - nper, nper // 2):
        if m[i:i + nper].all():
            f, p = ss.periodogram(x[i:i + nper] / 32768, FS, window="hann")
            acc = acc + p
            n += 1
    return f, acc / max(n, 1), n


fig, ax = plt.subplots(2, 1, figsize=(11, 7.5))
PS = {}
for i, k in enumerate((0, 1, 2, 3, 4)):
    r = R[k]
    m = quiet_mask(k)
    nper = 6000 if k == 0 else 24000
    f, p, n = psd(r["xc"], m, nper)
    PS[k] = (f, p)
    col = GREY if k == 0 else C[k - 1]
    lab = (RUNS[k][1].split(" – ")[0] + (" (Ruhe, sitzend)" if k == 0 else "")
           + f", {n} × {nper / FS:g} s".replace(".", ","))
    ax[0].semilogx(f[1:], 10 * np.log10(p[1:]), color=col, lw=0.8, label=lab)
    ax[1].plot(f, 10 * np.log10(p), color=col, lw=0.8, label=lab)
qfloor = 10 * np.log10((1 / 32768) ** 2 / 12 / (FS / 2))
for a_ in ax:
    a_.axhline(qfloor, color="k", lw=0.8, ls="--")
    a_.grid(alpha=0.3, which="both")
    a_.set_ylabel("dB re FS²/Hz")
ax[0].text(15, qfloor + 1.5, "Quantisierungsrauschen int16 (1 LSB = 86 µV)", fontsize=8)
ax[0].set_xlim(10, 12000)
ax[0].set_ylim(-150, -95)
ax[0].set_title("Rauschspektrum Mikrofon (ruhige Abschnitte, Klicks entfernt)", loc="left")
ax[0].legend(frameon=False, fontsize=8, loc="upper right")
ax[0].set_xlabel("Frequenz (Hz)")
ax[1].set_xlim(0, 1000)
ax[1].set_ylim(-150, -95)
for fk in (50, 100, 150, 200, 250):
    ax[1].axvline(fk, color=GREY, lw=0.5, ls=":")
for fk in (187.5, 375, 562.5, 750, 937.5):
    ax[1].axvline(fk, color=C[3], lw=0.6, ls=":")
ax[1].text(52, -99, "50-Hz-Raster (grau)", fontsize=8, color=GREY)
ax[1].text(380, -99, "187,5-Hz-Familie (WLAN-Paketrate, gelb): im Mikrofon keine Linien", fontsize=8,
           color=C[3])
ax[1].annotate("100 Hz nur liegend (Läufe 2–4)", (100, -109), xytext=(130, -105), fontsize=8,
               arrowprops=dict(arrowstyle="->", lw=0.8))
ax[1].set_title("Ausschnitt 0–1000 Hz: Brummlinien", loc="left")
ax[1].set_xlabel("Frequenz (Hz)")
fig.tight_layout()
savefig(fig, "mic_07_rauschspektrum.png")


def line_rms(f, p, f0, bw=1.5):
    m = (f > f0 - bw) & (f < f0 + bw)
    df = f[1] - f[0]
    side = (f > f0 - 8) & (f < f0 + 8) & ~m
    return np.sqrt(max(p[m].sum() - np.median(p[side]) * m.sum(), 0) * df) * 32768


for k in (0, 1, 2, 3, 4):
    f, p = PS[k]
    df = f[1] - f[0]
    tot = np.sqrt(p[(f > 80)].sum() * df) * 32768
    nz = {lab: 10 * np.log10(np.median(p[(f > a) & (f < b)])) for lab, a, b in
          (("300-3k", 300, 3000), ("3-8k", 3000, 8000), ("8-12k", 8000, 11500))}
    lines = {f0: line_rms(f, p, f0) for f0 in (50, 100, 150, 187.5, 375)}
    print(f"  Lauf {k}: rms >80 Hz {tot:.2f} counts ({db(tot / 32768):.1f} dBFS), Dichte "
          + ", ".join(f"{a}: {b:.1f}" for a, b in nz.items())
          + " dB/Hz | Linien (counts rms): " + ", ".join(f"{a:g} Hz {b:.3f}" for a, b in lines.items()))
print(f"  Quantisierungsboden: {qfloor:.1f} dB re FS²/Hz, Rauschen int16 allein {db(1 / np.sqrt(12) / 32768):.1f} dBFS")

# coherence CH1 vs CH2 (calm part of run 2)
fig, ax = plt.subplots(1, 1, figsize=(10, 3.8))
for i, (k, a, b) in enumerate([(2, 100, 420), (4, 60, 240), (3, 20, 240)]):
    r = R[k]
    y1 = r["xc"].copy()
    y2 = r["uv"].copy()
    for _, a0, b0 in r["blocks"]:
        y2 = remove_clicks(y2, r["v"], a0, b0)
    i0, i1 = int(a * FS), int(b * FS)
    f, coh = ss.coherence(y1[i0:i1], y2[i0:i1], FS, nperseg=24000)
    ax.semilogx(f[1:], coh[1:], color=C[i], lw=0.8, label=f"{RUNS[k][1].split(' – ')[0]}, {a}–{b} s")
    for f0 in (50, 100, 150, 187.5):
        j = np.argmin(np.abs(f - f0))
        print(f"  Kohärenz CH1–CH2 Lauf {k} bei {f0} Hz: {coh[j - 1:j + 2].max():.2f}")
    print(f"  Kohärenz CH1–CH2 Lauf {k} median 300–3000 Hz: {np.median(coh[(f > 300) & (f < 3000)]):.3f}")
ax.set_xlim(10, 12000)
ax.set_ylim(0, 1)
ax.set_xlabel("Frequenz (Hz)")
ax.set_ylabel("Kohärenz")
ax.set_title("Kohärenz Mikrofon (CH1) ↔ Biosignal (CH2), Klicks aus beiden Kanälen entfernt", loc="left")
ax.legend(frameon=False, fontsize=8, loc="upper right")
ax.grid(alpha=0.3, which="both")
fig.tight_layout()
savefig(fig, "mic_08_kohaerenz_ch1_ch2.png")

# breathing modulation
print("\nAtmung ...")
fig, ax = plt.subplots(1, 2, figsize=(12, 3.8), gridspec_kw=dict(width_ratios=[1.6, 1]))
r = R[4]
xb = bp(r["xc"], 80, 1000) * r["v"]
t, lvb = level(xb, r["v"], 1200)
m = (t > 120) & (t < 180)
ax[0].plot(t[m], db(lvb[m] / 32768), color=C[0], lw=0.8)
sm = ss.savgol_filter(np.nan_to_num(lvb, nan=np.nanmedian(lvb)), 41, 2)
ax[0].plot(t[m], db(sm[m] / 32768), color=C[1], lw=1.6, label="geglättet (2 s)")
ax[0].set_xlabel("Zeit im Lauf 4 (s)")
ax[0].set_ylabel("Pegel 80–1000 Hz (dBFS)")
ax[0].set_title("Lauf 4: langsame Pegelmodulation (vermutlich Atmung)", loc="left")
ax[0].legend(frameon=False, fontsize=8, loc="upper right")
ax[0].grid(alpha=0.3)
for i, (k, a, b) in enumerate([(1, 0, 125), (2, 100, 420), (3, 260, 440), (4, 60, 240)]):
    rr = R[k]
    xb = bp(rr["xc"], 80, 1000)
    tt, lv_ = level(xb[int(a * FS):int(b * FS)], rr["v"][int(a * FS):int(b * FS)], 1200)
    e = np.nan_to_num(lv_ ** 2, nan=np.nanmedian(lv_ ** 2))
    e = e - e.mean()
    f, p = ss.welch(e, 20, nperseg=1200)
    p = p / np.median(p[(f > 0.6) & (f < 3)])
    ax[1].plot(f * 60, p, color=C[i], lw=1.2, label=f"Lauf {k} ({a}–{b} s)")
    mm = (f > 0.1) & (f < 0.6)
    print(f"  Lauf {k}: Modulationsspitze {60 * f[mm][np.argmax(p[mm])]:.1f} /min, Verhältnis {p[mm].max():.1f}")
ax[1].set_xlim(0, 60)
ax[1].set_xlabel("Modulationsfrequenz (1/min)")
ax[1].set_ylabel("rel. Leistung (Median 36–180/min = 1)")
ax[1].set_title("Hüllkurvenspektrum 80–1000 Hz", loc="left")
ax[1].legend(frameon=False, fontsize=8, loc="upper right")
ax[1].grid(alpha=0.3)
fig.tight_layout()
savefig(fig, "mic_09_atmung_modulation.png")

# ---------------------------------------------------------------------------
# 4. Audio export
print("\nAudio ...")


def limit_norm(y, v):
    """Soft-limit rare transients (> 4x the 99.9th percentile), then -3 dBFS peak."""
    y = y.copy()
    y[~v] = 0.0
    ref = np.percentile(np.abs(y[v]), 99.9)
    if ref > 0:
        y = 4 * ref * np.tanh(y / (4 * ref))
    return y


MIC_X = [  # (file stem, run, start, end, description)
    ("01_lauf3_ansage_teil2", 3, 236, 262,
     "Lauf 3, 236–262 s: Klicks 0,035 (Block A), bei 244,5–248,8 s die Laptop-Ansage „Teil zwei …“, "
     "ab 249,4 s Schein-Block B (keine Klicks mehr)."),
    ("02_lauf3_ansage_teil3", 3, 441, 466,
     "Lauf 3, 441–466 s: Schein-Block B (still), Ansage „Teil drei …“ bei 450,7–453,9 s, ab 454,1 s "
     "2-kHz-Tonbursts (Block C; nur in der Roh-Datei als Pfeifton hörbar, in der bereinigten mit den "
     "Klicks herausgerechnet)."),
    ("04_lauf4_rascheln_ohrhoerer_draussen", 4, 30, 56,
     "Lauf 4, 30–56 s: Ohrhörer liegt neben dem Kopf; Rascheln bei 35–39 s und 49–53 s "
     "(lautestes Ereignis aller Läufe, −57 dBFS), danach lauterer akustischer Klick."),
    ("05_lauf4_klicks_akustisch", 4, 130, 155,
     "Lauf 4, 130–155 s: ruhig; das 21-Hz-Knattern ist der Klick, wie ihn das Mikrofon akustisch hört "
     "(+ elektrisches Übersprechen)."),
    ("06_lauf1_im_ohr_husten_rascheln", 1, 120, 145,
     "Lauf 1, 120–145 s: Ohrhörer im Ohr, Klick 0,10 (im Mikrofon fast nur elektrisch); "
     "Husten/Räuspern? bei 130,6 s, Rascheln bei 137–138,5 s."),
    ("07_lauf2_ruhe_hintergrund", 2, 300, 325,
     "Lauf 2, 300–325 s: ruhigster Abschnitt, liegend. Roh: Klick-Knattern über Rauschen; "
     "bereinigt: praktisch nur Grundrauschen (Quantisierung)."),
    ("08_lauf0_ruhe_sitzend", 0, 0, 8,
     "Lauf 0, 8 s, sitzend, kein Reiz: reines Grundrauschen (≈ −101 dBFS über 80 Hz)."),
]
README = ["Wireless BERA – Hörbeispiele aus den Messungen vom 16.10.2026",
          "=================================================================",
          "",
          "Erzeugt von measurements/tools/analysis_mic_audio.py. Alle Dateien: WAV, mono, 16 bit, 24 kHz.",
          "",
          "Mikrofon (CH1, Headset-Elektretmikrofon am Kabel):",
          "  *_roh.wav       nur Gleichanteil entfernt, verlorene WLAN-Pakete als Stille (kurze Aussetzer),",
          "                  auf −3 dBFS Spitze normiert. Enthält die Klicks (21,1/s).",
          "  *_bereinigt.wav Klicks per klick-synchronem Template abgezogen, 50-Hz-Raster und 187,5-Hz-",
          "                  Familie gekerbt, Hochpass 80 Hz, sanfte spektrale Rauschminderung (max. −12 dB),",
          "                  seltene Spitzen weich begrenzt, dann −3 dBFS Spitze.",
          "  ACHTUNG Pegel: Die Originalpegel sind extrem leise (Grundrauschen ≈ 0,3 LSB rms, −101 dBFS).",
          "  Jede Datei ist einzeln um ≈ 30–85 dB verstärkt; Lautstärken zwischen Dateien sind NICHT vergleichbar.",
          "  Leise anfangen – das Rauschen ist durch die Verstärkung kräftig.",
          ""]
AUDIO_LIST = []
for stem, k, a, b, desc in MIC_X:
    r = R[k]
    i0, i1 = int(a * FS), min(int(b * FS), r["n"])
    v = r["v"][i0:i1]
    raw = r["x"][i0:i1] - np.mean(r["x"][i0:i1][v])
    p1, g1, s1 = write_wav(stem + "_roh.wav", raw, v)
    cl = clean_for_listening(r["xc"][i0:i1] * v, v)
    cl = spectral_gate(cl, v, 0.6)
    cl = limit_norm(cl, v)
    p2, g2, s2 = write_wav(stem + "_bereinigt.wav", cl, v)
    print(f"  {os.path.basename(p1)} ({s1 / 1e6:.2f} MB, Verstärkung {db(g1):.0f} dB), "
          f"{os.path.basename(p2)} ({s2 / 1e6:.2f} MB)")
    README += [f"{stem}_roh.wav / _bereinigt.wav", "  " + desc, ""]
    AUDIO_LIST.append((stem, desc))

# CH2 sonification
SON = [("09_ch2_lauf2_unruhig_sonifiziert", 2, 55, 80,
        "Biosignal CH2, Lauf 2, 55–80 s (unruhige Anfangsphase): Rauschen = Verstärker + EEG-Hintergrund; "
        "Knistern/Brummen in Schüben = vermutlich Muskel-EMG (Kiefer, Nacken) und Bewegung; ein "
        "gleichmäßiges 21-Hz-Schnarren wäre das elektrische Klick-Artefakt (≈ 2–4 µV Spitze)."),
       ("10_ch2_lauf2_ruhig_sonifiziert", 2, 300, 325,
        "Biosignal CH2, Lauf 2, 300–325 s (ruhigste Phase, hier liegt die Welle V): fast gleichmäßiges "
        "Rauschen; das 21-Hz-Klick-Artefakt (≈ 2 µV Spitze) ist höchstens leise zu ahnen. Die BERA selbst (≈ 0,16 µV) "
        "ist nicht hörbar – sie entsteht erst durch Mitteln über Tausende Klicks."),
       ("11_ch2_lauf4_rascheln_sonifiziert", 4, 30, 56,
        "Biosignal CH2, Lauf 4, 30–56 s, gleiches Zeitfenster wie 04: Bewegungsartefakte/EMG beim Rascheln "
        "– Vergleich, ob die Mikrofon-Ereignisse auch im Biosignal stören.")]
README += ["Biosignal (CH2, Elektroden Stirn–Mastoid), hörbar gemacht:",
           "  Bandpass 100–3000 Hz, alle 50-Hz-Oberwellen bis 3 kHz gekerbt, stark verstärkt (≈ 100–110 dB),",
           "  seltene Spitzen weich begrenzt, −3 dBFS Spitze. Gleiche Zeitbasis wie das Original (Echtzeit).", ""]
fig, axs2 = plt.subplots(2 * len(SON), 1, figsize=(11, 3.2 * len(SON)),
                         gridspec_kw=dict(height_ratios=[2.2, 1] * len(SON)))
SON_T = {"09": "Lauf 2, 55–80 s, unruhige Anfangsphase", "10": "Lauf 2, 300–325 s, ruhigste Phase",
         "11": "Lauf 4, 30–56 s, Rascheln im Mikrofon"}
for j, (stem, k, a, b, desc) in enumerate(SON):
    ax_, axl = axs2[2 * j], axs2[2 * j + 1]
    r = R[k]
    i0, i1 = int(a * FS), int(b * FS)
    v = r["v"][i0:i1]
    y = bp(r["uv"], 100, 3000)[i0:i1]
    for f0 in range(50, 3001, 50):
        bb, aa = ss.iirnotch(f0, 30, FS)
        y = ss.filtfilt(bb, aa, y)
    y[~v] = 0.0
    rms_uv = np.sqrt(np.mean(y[v] ** 2))
    yl = limit_norm(y, v)
    p, g, sz = write_wav(stem + ".wav", yl, v)
    print(f"  {os.path.basename(p)} ({sz / 1e6:.2f} MB), CH2 rms 100–3000 Hz {rms_uv:.2f} µV")
    rms_de = f"{rms_uv:.1f}".replace(".", ",")
    README += [f"{stem}.wav", "  " + desc + f" (Effektivwert {rms_de} µV im Band 100–3000 Hz.)", ""]
    AUDIO_LIST.append((stem, desc))
    f, t, S = ss.spectrogram(y, FS, nperseg=1024, noverlap=512)
    m = f <= 3000
    im = ax_.imshow(10 * np.log10(S[m] + 1e-12), origin="lower", aspect="auto", cmap="magma",
                    extent=[a + t[0], a + t[-1], 0, 3], vmin=-65, vmax=-20, interpolation="nearest")
    cb = fig.colorbar(im, cax=ax_.inset_axes([1.005, 0, 0.012, 1]))
    cb.set_label("dB re µV²/Hz", fontsize=7)
    cb.ax.tick_params(labelsize=7)
    ax_.set_ylabel("kHz")
    ax_.set_xticklabels([])
    ax_.set_title(f"{SON_T[stem[:2]]} – Biosignal CH2, 100–3000 Hz, Effektivwert {rms_uv:.1f} µV "
                  f"(Datei {stem[:2]})", loc="left")
    tt_, lv_ = level(y, v, 2400)
    axl.plot(a + tt_, lv_, color=C[j], lw=1)
    axl.set_xlim(a, b)
    axl.set_ylim(0, None)
    axl.set_ylabel("µV rms\n(100 ms)", fontsize=8)
    axl.grid(alpha=0.3)
axs2[-1].set_xlabel("Zeit im Lauf (s)")
fig.tight_layout()
savefig(fig, "mic_10_ch2_sonifikation.png")

README += ["Hinweise",
           "  - Kurze Aussetzer (5–30 ms) sind verlorene WLAN-Pakete (≈ 1 %), keine Signalpausen.",
           "  - Das Mikrofon sitzt am Kabel (Kinn/Brust). Laptop-Ansagen liegen nur ≈ 3 dB über dem Rauschen:",
           "    in den bereinigten Dateien als leises, unverständliches Murmeln zu ahnen.",
           "  - Der Klick erreicht das Mikrofon im Ohr fast nur elektrisch (gemeinsamer Masse-Draht des",
           "    Headsets), mit Ohrhörer draußen zusätzlich akustisch (Nachschwingen ≈ 2,5 kHz).",
           ""]
with open(os.path.join(AUD, "LIESMICH.txt"), "w", encoding="utf-8") as fh:
    fh.write("\n".join(README))
print("  ->", os.path.join(AUD, "LIESMICH.txt"))
