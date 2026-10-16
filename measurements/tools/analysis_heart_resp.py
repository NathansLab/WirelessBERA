"""Heart activity and respiration in the Wireless BERA recordings of 2026-10-16.

Usage: python3 analysis_heart_resp.py
Reads ../2026-10-16_ecg_drl/*.csv (1 kHz chest ECG) and ../2026-10-16_bera/*.npz
(24 kHz head runs), writes heart_*.png into ../2026-10-16_bera/analysis/ and
prints the numbers used in the summary.

Chest ECG (codec high-pass 0.96 Hz on): R detection, HR, HRV (SDNN, RMSSD,
pNN50, HF/LF), respiration from RSA, EDR (QRS amplitude) and baseline.
Head runs (forehead - left mastoid, codec high-pass off): cardiac detection
with a template / matched filter, checked against phase-randomised surrogates
and an injection test (chest-ECG waveform added at known times and amplitudes);
heart-rate line in the click-sweep RMS series; respiration from the CH2
baseline (0.05-1 Hz) and the microphone envelope; cardiac residual expected in
the ABR average (100-1500 Hz) by simulation.
"""
import glob
import json
import os
import datetime as dt

import numpy as np
import scipy.signal as ss
from scipy import ndimage
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
BERA = os.path.join(HERE, "..", "2026-10-16_bera")
CHEST = os.path.join(HERE, "..", "2026-10-16_ecg_drl")
OUT = os.path.join(BERA, "analysis")
os.makedirs(OUT, exist_ok=True)

GAIN, FS_VPEAK = 16.0, 2.0 * np.sqrt(2)
C = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
GREY, GREY2 = "#a3a29c", "#d9d8d3"
rng = np.random.default_rng(7)
TZ = dt.timezone(dt.timedelta(hours=2))      # CEST

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 9,
    "axes.edgecolor": "#8a8984", "axes.labelcolor": "#52514e",
    "axes.titlesize": 10, "axes.titlelocation": "left",
    "axes.spines.top": False, "axes.spines.right": False, "axes.linewidth": 0.6,
    "axes.grid": True, "grid.color": "#e6e5e0", "grid.linewidth": 0.6,
    "legend.frameon": False, "legend.fontsize": 8, "lines.linewidth": 1.0,
})


def save(fig, name):
    fig.savefig(os.path.join(OUT, name), dpi=130)
    plt.close(fig)
    print("  ->", name)


def sos(kind, f, fs, order=2):
    return ss.butter(order, f, kind, fs=fs, output="sos")


def bpf(x, lo, hi, fs, order=2):
    return ss.sosfiltfilt(sos("bandpass", [lo, hi], fs, order), x)


# ======================================================================
# Chest ECG
# ======================================================================
CHEST_RUNS = [  # file, label, approximate start time (local)
    ("1_no_drl", "Brust 1 (ohne DRL)", "22:38"),
    ("2_drl_hand", "Brust 2 (DRL Hand)", "22:42"),
    ("3_drl_chest", "Brust 3 (DRL Brust)", "22:46"),
    ("4_drl_chest_repeat", "Brust 4 (DRL Brust, Wdh.)", "22:56"),
    ("5_apple_watch_parallel", "Brust 5 (Apple Watch)", "23:09:56"),
]
# Times: run 5 from its CSV header; run 4 ends before its file time 22:57:08;
# runs 1-3 were saved together at 22:54:33, their start times are estimates.
T_EXACT = {"5_apple_watch_parallel": True}


def tstamp(hhmm):
    p = [int(v) for v in hhmm.split(":")] + [0]
    return dt.datetime(2026, 10, 16, p[0], p[1], p[2], tzinfo=TZ).timestamp()


def load_chest(name):
    d = np.loadtxt(os.path.join(CHEST, name + ".csv"), delimiter=",", skiprows=4)
    t = d[:, 0]
    assert np.allclose(np.diff(t), 1e-3, atol=2e-4), name
    uv = -d[:, 2] / 32768 * FS_VPEAK / GAIN * 1e6
    return uv


def detect_r_chest(uv, fs=1000):
    b = bpf(uv, 5, 30, fs, 3)
    pol = 1 if np.percentile(b, 99.9) > -np.percentile(b, 0.1) else -1
    pk, _ = ss.find_peaks(pol * b, distance=int(0.35 * fs), height=0.4 * np.percentile(pol * b, 99.5))
    w = bpf(uv, 0.5, 40, fs)
    edge = int(0.5 * fs)                          # filter transients at the file ends
    r = np.array([p - 40 + np.argmax(w[p - 40:p + 40]) for p in pk if edge < p < len(w) - edge])
    # Refine by cross-correlation with the run's median QRS (a notched R peak
    # otherwise makes the argmax jump by ~20 ms between beats).
    for _ in range(2):
        T = np.median(np.stack([w[p - 60:p + 61] for p in r]), axis=0)
        T = T - T.mean()
        lags = np.arange(-30, 31)
        r = np.array([p + lags[np.argmax([np.dot(w[p + k - 60:p + k + 61], T) for k in lags])] for p in r])
    return r, pol


def rr_clean(r, fs=1000):
    """RR in ms with intervals next to suspected misses/extras removed."""
    rr = np.diff(r) / fs * 1e3
    med = ndimage.median_filter(rr, 7, mode="nearest")
    gmed = np.median(rr)
    ok = (np.abs(rr - med) < 0.2 * med) & (np.abs(rr - gmed) < 0.35 * gmed)
    ok = ndimage.binary_erosion(ok, np.ones(3), border_value=1)     # drop neighbours of bad intervals
    return rr, ok


def hrv(rr, ok, tb):
    """SDNN, RMSSD, pNN50, and LF/HF from the RR series resampled at 4 Hz."""
    rrv = rr[ok]
    d = np.diff(rr)[ok[1:] & ok[:-1]]
    out = dict(hr=60e3 / np.mean(rrv), sdnn=np.std(rrv, ddof=1), rmssd=np.sqrt(np.mean(d ** 2)),
               pnn50=100 * np.mean(np.abs(d) > 50), n=len(rrv))
    ti = np.arange(tb[ok][0], tb[ok][-1], 0.25)
    x = np.interp(ti, tb[ok], rrv)
    x = ss.detrend(x)
    f, P = ss.welch(x, 4, nperseg=min(len(x), 256), nfft=2048, detrend="linear")
    df = f[1] - f[0]
    lf = P[(f >= 0.04) & (f < 0.15)].sum() * df
    hf = P[(f >= 0.15) & (f < 0.4)].sum() * df
    out.update(lf=lf, hf=hf, lfhf=lf / hf, dur=ti[-1] - ti[0])
    return out


def resp_rate(x, fs, lo=0.12, hi=0.5):
    f, P = ss.periodogram(ss.detrend(x) * np.hanning(len(x)), fs, nfft=8192)
    m = (f >= lo) & (f <= hi)
    return f[m][np.argmax(P[m])] * 60, f, P


def sliding_rate(t, x, fs, win=30, step=5):
    tc, rate = [], []
    n = int(win * fs)
    for a in range(0, len(x) - n + 1, int(step * fs)):
        r, _, _ = resp_rate(x[a:a + n], fs)
        tc.append(t[a] + win / 2)
        rate.append(r)
    return np.array(tc), np.array(rate)


def chest_analysis():
    print("\n=== Brust-EKG ===")
    res = []
    for name, label, hhmm in CHEST_RUNS:
        uv = load_chest(name)
        fs = 1000
        r, pol = detect_r_chest(uv)
        rr, ok = rr_clean(r)
        tb = r[1:] / fs
        H = hrv(rr, ok, tb)
        # R-locked average (0.5-40 Hz + 50 Hz notch)
        w = ss.filtfilt(*ss.iirnotch(50, 30, fs), bpf(uv, 0.5, 40, fs))
        rr_ = r[(r > 300) & (r < len(w) - 600)]
        E = np.stack([w[p - 300:p + 600] for p in rr_])
        avg = np.median(E, axis=0)
        # QRS amplitude (EDR): peak-to-peak within +-60 ms in 0.5-40 Hz
        amp = np.array([np.ptp(w[p - 60:p + 60]) for p in r if 60 < p < len(w) - 60])
        ta = np.array([p for p in r if 60 < p < len(w) - 60]) / fs
        # 4 Hz series for respiration
        t4 = np.arange(max(tb[0], ta[0]), min(tb[-1], ta[-1]), 0.25)
        rsa = np.interp(t4, tb[ok], rr[ok])
        edr = np.interp(t4, ta, amp)
        base = ss.resample_poly(bpf(ss.resample_poly(uv, 1, 10), 0.08, 0.6, 100, 2), 1, 25)
        tbase = np.arange(len(base)) / 4
        base = np.interp(t4, tbase, base)
        series = {}
        for k, x in [("RSA", rsa), ("EDR", edr), ("Basislinie", base)]:
            series[k] = bpf(ss.detrend(x), 0.1, 0.6, 4)[12:-12]
        rates = {k: resp_rate(v, 4)[0] for k, v in series.items()}
        # waveform agreement RSA vs EDR / baseline: max |r| within +-2 s lag
        def xcorr(a, b):
            best = 0
            for lag in range(-8, 9):
                aa, bb = (a[lag:], b[:len(b) - lag]) if lag >= 0 else (a[:lag], b[-lag:])
                c = np.corrcoef(aa, bb)[0, 1]
                if abs(c) > abs(best):
                    best = c
            return best
        agree = dict(rsa_edr=xcorr(series["RSA"], series["EDR"]), rsa_base=xcorr(series["RSA"], series["Basislinie"]),
                     edr_base=xcorr(series["EDR"], series["Basislinie"]))
        t4 = t4[12:-12]
        slid = {k: sliding_rate(t4, v, 4) for k, v in series.items()}
        res.append(dict(name=name, label=label, hhmm=hhmm, uv=uv, r=r, rr=rr, ok=ok, tb=tb, H=H, avg=avg,
                        amp=amp, ta=ta, t4=t4, series=series, rates=rates, agree=agree, slid=slid,
                        t0=tstamp(hhmm), pol=pol))
        print(f"{label:28s} {len(r)} R, HR {H['hr']:.1f}/min, SDNN {H['sdnn']:.0f} ms, RMSSD {H['rmssd']:.0f} ms, "
              f"pNN50 {H['pnn50']:.0f} %, LF/HF {H['lfhf']:.2f} (nur {H['dur']:.0f} s), QRS {np.median(amp):.0f} µV, "
              f"EDR-Mod {100 * np.std(amp) / np.mean(amp):.1f} %; Atmung RSA {rates['RSA']:.1f}, "
              f"EDR {rates['EDR']:.1f}, Basis {rates['Basislinie']:.1f} /min; "
              f"r(RSA,EDR) {agree['rsa_edr']:.2f}, r(RSA,Basis) {agree['rsa_base']:.2f}, r(EDR,Basis) {agree['edr_base']:.2f}")
    return res


def fig_chest_overview(res):
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.6), gridspec_kw=dict(width_ratios=[1, 1.4]))
    t = np.arange(-300, 600)
    for i, R in enumerate(res):
        col = C[i % 4] if i < 4 else "#52514e"
        ax[0].plot(t, R["avg"] / 1000, color=col, lw=1.2, label=R["label"])
        ax[1].plot(R["tb"][R["ok"]], 60e3 / R["rr"][R["ok"]], color=col, lw=1.2, marker="o", ms=2.2)
    ax[0].set_xlabel("Zeit relativ zur R-Zacke (ms)")
    ax[0].set_ylabel("mV an den Elektroden")
    ax[0].set_title("Gemittelter Herzschlag (Median, 0,5–40 Hz)")
    ax[0].legend(loc="upper right", fontsize=7.5)
    ax[1].set_xlabel("Zeit in der Aufnahme (s)")
    ax[1].set_ylabel("Herzfrequenz (1/min)")
    ax[1].set_title("Momentane Herzfrequenz (60/RR); Atemrhythmus als Welligkeit sichtbar")
    qrs = [np.median(R["amp"]) / 1000 for R in res]
    fig.suptitle(f"Brust-EKG 22:38–23:11: QRS {min(qrs):.1f}–{max(qrs):.1f} mV Spitze-Spitze, jede R-Zacke erkannt", x=0.01, ha="left")
    fig.tight_layout()
    save(fig, "heart_01_brust_ekg_herzschlag_hf.png")


def fig_chest_hrv(res):
    fig, ax = plt.subplots(1, 3, figsize=(13, 4.2))
    for i, R in enumerate(res):
        col = C[i % 4] if i < 4 else "#52514e"
        rr = R["rr"]
        okp = R["ok"][1:] & R["ok"][:-1]
        ax[0].plot(rr[:-1][okp], rr[1:][okp], "o", ms=2.5, color=col, alpha=0.7, label=R["label"])
    ax[0].set_xlabel("RR$_n$ (ms)")
    ax[0].set_ylabel("RR$_{n+1}$ (ms)")
    ax[0].set_title("Poincaré-Diagramm")
    ax[0].legend(fontsize=7, loc="upper left")
    x = np.arange(len(res))
    lab = [R["label"].split(" (")[0] for R in res]
    sd = [R["H"]["sdnn"] for R in res]
    rm = [R["H"]["rmssd"] for R in res]
    ax[1].bar(x - 0.2, sd, 0.4, color=C[0], label="SDNN")
    ax[1].bar(x + 0.2, rm, 0.4, color=C[1], label="RMSSD")
    for xi, a, b in zip(x, sd, rm):
        ax[1].text(xi - 0.2, a + 1, f"{a:.0f}", ha="center", fontsize=7.5)
        ax[1].text(xi + 0.2, b + 1, f"{b:.0f}", ha="center", fontsize=7.5)
    ax[1].set_xticks(x, lab, rotation=20)
    ax[1].set_ylabel("ms")
    ax[1].set_title("HRV im Zeitbereich (je 60–75 s)")
    ax[1].legend(loc="upper left")
    ax[1].set_ylim(0, max(max(sd), max(rm)) * 1.25)
    lfhf = [R["H"]["lfhf"] for R in res]
    ax[2].bar(x, lfhf, 0.55, color=GREY)
    for xi, v in zip(x, lfhf):
        ax[2].text(xi, v + 0.05, f"{v:.2f}", ha="center", fontsize=7.5)
    ax[2].set_xticks(x, lab, rotation=20)
    ax[2].set_ylabel("LF/HF")
    ax[2].set_title("LF/HF nur orientierend: Serien < 2 min")
    ax[2].set_ylim(0, max(lfhf) * 1.25)
    fig.tight_layout()
    save(fig, "heart_02_brust_hrv.png")


def fig_chest_resp(res):
    fig, axs = plt.subplots(len(res), 2, figsize=(13, 2.3 * len(res) + 0.8),
                            gridspec_kw=dict(width_ratios=[2.4, 1]), sharex="col")
    for i, R in enumerate(res):
        ax = axs[i, 0]
        for j, (k, v) in enumerate(R["series"].items()):
            z = v / np.std(v)
            sgn = -1 if (k != "RSA" and np.corrcoef(z, R["series"]["RSA"])[0, 1] < 0) else 1
            ax.plot(R["t4"], sgn * z - 4.0 * j, color=C[j], lw=1.1,
                    label=f"{k}{' (inv.)' if sgn < 0 else ''}: {R['rates'][k]:.1f}/min")
        ax.set_yticks([])
        ax.set_ylim(-11.5, 6.5)
        ax.set_title(R["label"] + f"   r(RSA,EDR) = {R['agree']['rsa_edr']:.2f}", fontsize=9)
        ax.legend(loc="upper right", ncol=3, fontsize=7, bbox_to_anchor=(1.0, 1.05))
        ax2 = axs[i, 1]
        for j, k in enumerate(R["slid"]):
            tc, rate = R["slid"][k]
            ax2.plot(tc, rate, color=C[j], marker="o", ms=3, lw=1)
        ax2.set_ylim(5, 32)
        ax2.set_ylabel("Atemzüge/min", fontsize=8)
    axs[-1, 0].set_xlabel("Zeit (s)")
    axs[-1, 1].set_xlabel("Fenstermitte (s), 30-s-Fenster")
    fig.suptitle("Atmung aus dem Brust-EKG: RSA (RR-Intervalle), EDR (QRS-Amplitude), Basislinie (0,1–0,6 Hz); "
                 "normiert, versetzt", x=0.01, ha="left")
    fig.tight_layout()
    save(fig, "heart_03_brust_atmung_methoden.png")


# ======================================================================
# Head runs
# ======================================================================
HEAD_RUNS = [
    ("1_click_amp0.10_21Hz", "Lauf 1 (sitzend)"),
    ("2_click_amp0.05_21Hz", "Lauf 2 (liegend)"),
    ("3_click_sham_toneburst_continuous", "Lauf 3 (liegend)"),
    ("4_sham_click_amp0.035_earbud_out", "Lauf 4 (liegend)"),
]


def read_log(name):
    p = os.path.join(BERA, name + ".log")
    if not os.path.exists(p):
        return []
    out = []
    for line in open(p):
        s = line.split()
        try:
            out.append(float(s[0]))
        except (ValueError, IndexError):
            pass
    return out


def load_head(name):
    """CH2 µV and CH1 counts at 24 kHz with gaps interpolated and the
    stimulus-periodic component (per block) subtracted; also 1 kHz versions."""
    d = np.load(os.path.join(BERA, name + ".npz"))
    fs = float(d["fs"])
    st = json.loads(str(d["stimulus"]))
    v = d["valid"].astype(bool)
    t0 = float(d["t_start"])
    uv = -d["ch2"].astype(float) / 32768 * FS_VPEAK / GAIN * 1e6
    mic = d["ch1"].astype(float)
    n = len(uv)
    marks = read_log(name)
    edges = [0] + [int((m - t0) * fs) for m in marks if 0 < (m - t0) * fs < n] + [n]
    P = 2 * int(48000 / st["rate_hz"]) // int(d["decim"])        # one +/- click pair
    clean = {}
    for key, x in [("uv", uv), ("mic", mic)]:
        x = x.copy()
        if st["type"] != 0:
            for a, b in zip(edges[:-1], edges[1:]):
                m = (b - a) // P * P
                if m < 4 * P:
                    continue
                X = x[a:a + m].reshape(-1, P)
                V = v[a:a + m].reshape(-1, P)
                Xm = np.where(V, X, np.nan)
                Xm = Xm - np.nanmean(Xm, axis=1, keepdims=True)
                tm = np.nanmean(Xm, axis=0)
                x[a:a + m] -= np.tile(tm, m // P)
        idx = np.arange(n)
        x = np.interp(idx, idx[v], x[v])
        clean[key] = x
    k1 = ss.resample_poly(clean["uv"], 1, 24)
    m1 = ss.resample_poly(clean["mic"], 1, 24)
    v1 = ss.resample_poly(v.astype(float), 1, 24) > 0.99
    # raw (gap-zeroed) data and click phase for the sweep analysis, as bera_analysis.py
    raw = -d["ch2"].astype(float) / 32768 * FS_VPEAK / GAIN * 1e6
    raw[~v] = 0
    L = int(48000 / st["rate_hz"]) // int(d["decim"])
    a_end = edges[1] if len(edges) > 2 else n
    hp = ss.sosfiltfilt(sos("highpass", 300, fs, 4), raw[:a_end])
    n2 = len(hp) // (2 * L)
    f2 = hp[:n2 * 2 * L].reshape(n2, 2 * L).mean(axis=0)
    D = int(np.argmax(np.abs(f2[:L] - f2[L:])))
    return dict(name=name, fs=fs, uv24=clean["uv"], raw24=raw, v24=v, y=k1, mic=m1, v1=v1, t0=t0,
                st=st, L=L, D=D, edges=edges, marks=marks, dur=n / fs)


def ricker(sig_ms, half=60):
    t = np.arange(-half, half + 1) / 1e3
    s = sig_ms / 1e3
    w = (1 - (t / s) ** 2) * np.exp(-t ** 2 / 2 / s ** 2)
    return w - w.mean()


DET_BAND = (10, 40)       # QRS band for the head; cuts most of the alpha rhythm


def zscore_mf(x, tmpl):
    tm = tmpl - tmpl.mean()
    tm = tm / np.linalg.norm(tm)
    z = np.correlate(x, tm, "same")
    return z / (1.4826 * np.median(np.abs(z - np.median(z))))


def dp_beats(c, s, T, lam):
    """Dynamic-programming beat tracker over candidate peaks c with scores s;
    intervals are penalised by lam * log(RR/T)^2 around the local period T."""
    n = len(c)
    Cs = s.copy()
    prev = -np.ones(n, int)
    j0 = 0
    for i in range(n):
        lo, hi = c[i] - 1.5 * T[i], c[i] - 0.6 * T[i]
        while c[j0] < lo:
            j0 += 1
        js = np.arange(j0, i)
        js = js[c[js] <= hi]
        if len(js):
            pen = Cs[js] - lam * np.log((c[i] - c[js]) / T[i]) ** 2
            k = np.argmax(pen)
            if pen[k] > 0:
                Cs[i] = s[i] + pen[k]
                prev[i] = js[k]
    i = int(np.argmax(Cs))
    out = []
    while i >= 0:
        out.append(c[i])
        i = prev[i]
    return np.array(out[::-1]), Cs.max()


def track(x, tmpl, z0=1.0, lam=20.0, n_it=4, T0=900.0, adapt=False):
    """Matched filter + DP tracking. adapt=True re-estimates the template
    from the tracked beats (blind bootstrap)."""
    tm = tmpl
    for it in range(n_it):
        z = zscore_mf(x, tm)
        c, _ = ss.find_peaks(z, distance=150)
        s = z[c] - z0
        T = np.full(len(c), T0) if it == 0 else np.interp(c, b[1:], ss.medfilt(np.diff(b), 15))
        b, score = dp_beats(c, s, T, lam)
        b = b[(b > 300) & (b < len(x) - 600)]
        if adapt:
            tm = np.stack([x[p - 60:p + 61] for p in b]).mean(axis=0)
    return b, score, tm


def blind_track(x):
    best = None
    for sgn in (1, -1):
        b, score, tm = track(x, sgn * ricker(8), adapt=True)
        if best is None or score > best[1]:
            best = (b, score, tm)
    return best


def phase_rand(x):
    X = np.fft.rfft(x)
    ph = np.exp(1j * rng.uniform(0, 2 * np.pi, len(X)))
    ph[0] = 1
    return np.fft.irfft(X * ph, len(x))


def synth_ecg(n, fs, tmpl, rr_ms, scale, offset=500):
    """Chest-shaped cardiac signal: template (R at 1/3 of its length) placed
    at the RR series (repeated)."""
    x = np.zeros(n)
    beats = []
    p = offset
    i = 0
    h = len(tmpl)
    pre = h // 3
    while p - pre >= 0 and p - pre + h <= n:
        beats.append(p)
        x[p - pre:p - pre + h] += tmpl * scale
        p += int(round(rr_ms[i % len(rr_ms)] * fs / 1000))
        i += 1
    return x, np.array(beats)


def match(det, truth, tol=25):
    if len(det) == 0:
        return 0.0, 0.0, 0.0
    j = np.searchsorted(truth, det)
    d = np.minimum(np.abs(det - truth[np.clip(j - 1, 0, len(truth) - 1)]),
                   np.abs(det - truth[np.clip(j, 0, len(truth) - 1)]))
    tp = np.sum(d <= tol)
    sens, ppv = tp / len(truth), tp / len(det)
    return sens, ppv, (2 * sens * ppv / (sens + ppv) if tp else 0.0)


def match_offset(det, truth, tol=25):
    """As match(), after removing a constant offset (a blind template may lock
    onto S or T instead of R)."""
    if len(det) < 3:
        return 0.0, 0.0, 0.0
    j = np.clip(np.searchsorted(truth, det), 1, len(truth) - 1)
    d1, d2 = det - truth[j - 1], det - truth[j]
    d = np.where(np.abs(d1) < np.abs(d2), d1, d2)
    d = d[np.abs(d) < 200]
    off = int(np.median(d)) if len(d) else 0
    return match(det - off, truth, tol)


def rr_spread(b):
    rr = np.diff(b)
    return np.median(np.abs(np.diff(rr)))        # median successive RR difference (ms)


AMPS = [0, 5, 10, 15, 20, 30, 40]


def head_cardiac(heads, chest5):
    print("\n=== Kopf: Herz ===")
    tmpl = chest5["avg"]                      # 0.5-40 Hz, -300..+600 ms, µV
    tmpl = tmpl * ss.windows.tukey(len(tmpl), 0.25)       # no steps at the template ends
    tmpl_n = tmpl / np.ptp(tmpl[300 - 60:300 + 60])       # QRS p2p = 1 µV
    rr5 = chest5["rr"][chest5["ok"]]
    pad = np.r_[np.zeros(300), tmpl_n, np.zeros(300)]
    to = bpf(pad, *DET_BAND, 1000, 3)[600 - 60:600 + 61]  # known shape in the detection band
    print(f"Brust-QRS: Anteil im {DET_BAND[0]}–{DET_BAND[1]}-Hz-Band {np.ptp(to):.2f} der Spitze-Spitze-Amplitude")
    for H in heads:
        x0 = bpf(H["y"], *DET_BAND, 1000, 3)
        bb, _, tmb = blind_track(x0)
        sur = []
        for _ in range(4):
            bs, _, _ = blind_track(phase_rand(x0))
            sur.append(rr_spread(bs))
        f1o, f1b, spb = [], [], []
        for A in AMPS:
            inj, truth = synth_ecg(len(H["y"]), 1000, tmpl_n, rr5, A, offset=int(rng.integers(400, 1200)))
            xi = bpf(H["y"] + inj, *DET_BAND, 1000, 3)
            b, _, _ = track(xi, to)
            f1o.append(match(b, truth)[2])
            b2, _, _ = blind_track(xi)
            f1b.append(match_offset(b2, truth)[2])
            spb.append(rr_spread(b2))
        E = np.stack([x0[p - 300:p + 600] for p in bb])
        H["card"] = dict(beats=bb, avg=E.mean(axis=0), spread=rr_spread(bb), sur=sur, f1o=np.array(f1o),
                         f1b=np.array(f1b), spb=np.array(spb), x0=x0)
        print(f"{H['label']}: blind {len(bb)} 'Schläge', RR-Folgedifferenz {rr_spread(bb):.0f} ms "
              f"(Surrogate {min(sur):.0f}–{max(sur):.0f} ms; Brust 5: {rr_spread(chest5['r']):.0f} ms); "
              f"F1 bekannt {np.round(f1o, 2)}, blind {np.round(f1b, 2)}, Spread blind {np.round(spb)}")
    return tmpl_n, rr5


def fig_head_detect(heads, tmpl_n, chest5):
    fig = plt.figure(figsize=(13, 9.5))
    gs = fig.add_gridspec(3, 2, height_ratios=[1.25, 1, 1], hspace=0.6, wspace=0.22)
    ax = fig.add_subplot(gs[0, :])
    H = heads[1]
    t = np.arange(len(H["y"])) / 1000
    a, b = 200000, 210000
    rr5 = chest5["rr"][chest5["ok"]]
    inj, truth = synth_ecg(len(H["y"]), 1000, tmpl_n, rr5, 1.0, offset=200400)
    x0 = bpf(H["y"], *DET_BAND, 1000, 3)
    ax.plot(t[a:b], x0[a:b], color=GREY, lw=0.8, label=f"gemessen, {DET_BAND[0]}–{DET_BAND[1]} Hz (Lauf 2, ruhige Phase)")
    for j, A in enumerate([10, 30]):
        xi = bpf(H["y"] + A * inj, *DET_BAND, 1000, 3)
        ax.plot(t[a:b], xi[a:b] - 35 * (j + 1), color=C[j], lw=0.8, label=f"+ Brust-EKG-Form mit QRS {A} µV")
    tb = truth[(truth >= a) & (truth < b)] / 1000
    ax.plot(tb, np.full(len(tb), 24), "v", color="#52514e", ms=5, label="eingefügte R-Zacken")
    ax.set_xlim(t[a], t[b])
    ax.set_ylim(-95, 30)
    ax.set_yticks([0, -35, -70], ["0", "0", "0"])
    ax.set_ylabel("µV (Spuren versetzt)")
    ax.set_xlabel("Zeit in Lauf 2 (s)")
    ax.legend(loc="upper center", ncol=4, fontsize=7.5, bbox_to_anchor=(0.5, 1.2))
    ax.set_title("Kein EKG im Kopfsignal (Stirn – li. Mastoid) erkennbar; ein QRS von 30 µV wäre sichtbar", pad=26)
    ax = fig.add_subplot(gs[1, 0])
    for i, H in enumerate(heads):
        c = H["card"]
        ax.plot(AMPS[1:], c["f1o"][1:], "-o", color=C[i], ms=3.5, label=H["label"])
        ax.plot(AMPS[1:], c["f1b"][1:], "--", color=C[i], lw=0.9)
    ax.axhline(0.9, color=GREY, lw=0.8)
    ax.set_xlabel("eingefügte QRS-Amplitude (µV Spitze-Spitze)")
    ax.set_ylabel("F1 der Schlagerkennung")
    ax.set_ylim(0, 1.02)
    ax.set_title("Injektionstest: — Form bekannt, - - blind")
    ax.legend(fontsize=7, loc="upper left")
    ax = fig.add_subplot(gs[1, 1])
    for i, H in enumerate(heads):
        c = H["card"]
        ax.plot(AMPS, c["spb"], "-o", color=C[i], ms=3.5, label=H["label"])
        ax.plot([-1.5 + 0.6 * i] * len(c["sur"]), c["sur"], "x", color=C[i], ms=5)
    sp5 = rr_spread(chest5["r"])
    ax.axhline(sp5, color="#52514e", lw=0.8, ls=":")
    ax.text(-2, sp5 + 3, f"echtes EKG (Brust 5): {sp5:.0f} ms", ha="left", fontsize=7.5, color="#52514e")
    ax.set_xlabel("eingefügte QRS-Amplitude (µV); × = Surrogat ohne EKG")
    ax.set_ylabel("Median |ΔRR| der blinden Suche (ms)")
    ax.set_title("Blinde Suche: unregelmäßige 'Schläge' bis ~15 µV")
    ax.set_xlim(-3, 42)
    ax.legend(fontsize=7, loc="upper right")
    ax = fig.add_subplot(gs[2, 0])
    tt = np.arange(-300, 600)
    for i, H in enumerate(heads):
        ax.plot(tt, H["card"]["avg"], color=C[i], lw=1, label=H["label"])
    ax.set_xlabel("Zeit relativ zum gefundenen 'Schlag' (ms)")
    ax.set_ylabel("µV")
    ax.set_title("Blind gemittelte 'Schläge' (echte Daten): nur die selbst gesuchte Zacke")
    ax.legend(fontsize=7, ncol=2, loc="upper right")
    ax = fig.add_subplot(gs[2, 1])
    for i, H in enumerate(heads):
        ax.hist(np.diff(H["card"]["beats"]), bins=np.arange(400, 1800, 40), histtype="step", color=C[i], lw=1.2,
                density=True, label=H["label"])
    rr = chest5["rr"][chest5["ok"]]
    ax.hist(rr, bins=np.arange(400, 1800, 40), color=GREY2, density=True, label="Brust 5 (echte RR)", zorder=0)
    ax.set_xlabel("Abstand gefundener 'Schläge' (ms)")
    ax.set_ylabel("Dichte")
    ax.set_title("Abstände: breit statt schmaler RR-Gipfel")
    ax.legend(fontsize=7, loc="upper right")
    save(fig, "heart_04_kopf_ekg_nachweisgrenze.png")


def sweep_rms_series(H, lo=100, hi=1500):
    fs = H["fs"]
    y = ss.sosfiltfilt(sos("bandpass", [lo, hi], fs, 2), H["raw24"])
    for k in range(1, int(hi // 50) + 2):
        y = ss.filtfilt(*ss.iirnotch(50.0 * k, 50.0 * k / 4.0, fs), y)
    L, D = H["L"], H["D"]
    post = int(0.012 * fs)
    on = D + np.arange(1, (len(y) - D - post) // L) * L
    v = H["v24"]
    ok = np.array([v[o:o + post].all() for o in on])
    rms = np.array([np.sqrt(np.mean(y[o:o + post] ** 2)) for o in on])
    rate = fs / L
    rms_i = np.interp(np.arange(len(on)), np.where(ok)[0], rms[ok])
    return rms_i, rate, on


def fig_sweep_hr(heads, hr_band):
    fig, ax = plt.subplots(1, 2, figsize=(12.5, 4.2))
    print("\n=== Sweep-RMS-Spektrum (Herzlinie?) ===")
    for i, H in enumerate(heads):
        rms, rate, on = sweep_rms_series(H)
        H["sweep_rms"] = (rms, rate, on)
        x = np.log(rms)
        x = x - ss.medfilt(x, 211)
        f, P = ss.welch(x, rate, nperseg=1024, nfft=4096)
        P = P / np.median(P[(f > 0.5) & (f < 3)])
        ax[0].plot(f, P + 1.5 * i, color=C[i], lw=1, label=H["label"])
        m = (f > hr_band[0] / 60) & (f < hr_band[1] / 60)
        print(f"{H['label']}: max relative Leistung im HF-Band {P[m].max():.2f}, Median außerhalb 1.0")
        # 5-30 Hz envelope spectrum
        bp = bpf(H["y"], 5, 30, 1000, 3) ** 2
        e = ss.resample_poly(ss.sosfiltfilt(sos("lowpass", 5, 1000), bp), 1, 50)
        e = np.log(np.maximum(e, 1e-3))
        f2, P2 = ss.welch(e - e.mean(), 20, nperseg=1200, nfft=4096)
        P2 = P2 / np.median(P2[(f2 > 0.5) & (f2 < 3)])
        ax[1].plot(f2, P2 + 1.5 * i, color=C[i], lw=1, label=H["label"])
    for a in ax:
        a.axvspan(hr_band[0] / 60, hr_band[1] / 60, color=GREY2, alpha=0.6, lw=0,
                  label="Herzfrequenzbereich der Brust-EKGs")
        a.set_xlim(0.3, 3)
        a.set_ylim(-0.3, 8.5)
        a.set_xlabel("Modulationsfrequenz (Hz)")
        a.set_ylabel("rel. Leistung (versetzt um 1,5)")
    ax[0].set_title("Spektrum der Sweep-RMS (100–1500 Hz, 0–12 ms)")
    ax[1].set_title("Spektrum der 5–30-Hz-Hüllkurve")
    h, l = ax[0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=5, fontsize=7.5)
    fig.suptitle("Keine Herzfrequenz-Linie: weder das ABR-Rauschen noch die 5–30-Hz-Energie schwankt im Herzrhythmus",
                 x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    save(fig, "heart_05_kopf_sweeprauschen_herzlinie.png")


def head_resp(heads, resp_band):
    """CH2 baseline (0.05-1 Hz) and microphone envelope: mean spectra over
    60-s windows without blink/movement transients."""
    print("\n=== Kopf: Atmung ===")
    for H in heads:
        y = H["y"]
        x10 = ss.resample_poly(ss.resample_poly(y, 1, 10), 1, 10)          # 10 Hz
        base = bpf(x10, 0.05, 1.0, 10, 2)
        hf = bpf(H["mic"], 150, 450, 1000, 3)
        env = np.log(np.maximum(ss.sosfiltfilt(sos("lowpass", 2, 1000), hf ** 2), 1e-3))
        menv = bpf(ss.resample_poly(env, 1, 100), 0.05, 1.0, 10, 2)
        n = min(len(base), len(menv))
        base, menv = base[:n], menv[:n]
        art = np.abs(base) > 12
        art = np.convolve(art, np.ones(31), "same") > 0                      # +-1.5 s
        win, step = 600, 150
        Pb, Pm, starts = [], [], []
        for a in range(50, n - win - 50, step):
            if art[a:a + win].mean() > 0.0:
                continue
            for lst, s in [(Pb, base[a:a + win]), (Pm, menv[a:a + win])]:
                f, P = ss.periodogram(ss.detrend(s) * np.hanning(win), 10, nfft=2400)
                lst.append(P)
            starts.append(a / 10)
        R = dict(base=base, menv=menv, art=art, n_win=len(starts), starts=starts)
        if starts:
            Pb, Pm = np.mean(Pb, axis=0), np.mean(Pm, axis=0)
            band = (f >= resp_band[0] / 60) & (f <= resp_band[1] / 60)
            side = ((f >= 0.1) & (f < resp_band[0] / 60 - 0.03)) | ((f > resp_band[1] / 60 + 0.03) & (f <= 0.6))
            df = f[1] - f[0]
            R.update(f=f, Pb=Pb, Pm=Pm, ratio_b=Pb[band].mean() / Pb[side].mean(),
                     ratio_m=Pm[band].mean() / Pm[side].mean(),
                     rms_band=np.sqrt(Pb[band].sum() * df), rms_tot=np.sqrt(Pb[(f >= 0.05) & (f <= 1)].sum() * df))
            print(f"{H['label']}: {len(starts)} ruhige 60-s-Fenster ({100 * (1 - art.mean()):.0f} % artefaktfrei); "
                  f"Basislinie Atemband/Nachbarn {R['ratio_b']:.2f}, Mikrofon {R['ratio_m']:.2f}; "
                  f"Basislinie im Atemband {R['rms_band']:.2f} µV RMS (0,05–1 Hz gesamt {R['rms_tot']:.2f} µV); "
                  f"Transienten > 12 µV: {np.sum(np.diff(np.abs(base) > 12) > 0) / (n / 600):.1f}/min")
        else:
            print(f"{H['label']}: kein artefaktfreies 60-s-Fenster; Transienten > 12 µV "
                  f"{np.sum(np.diff(np.abs(base) > 12) > 0) / (n / 600):.1f}/min")
        H["resp"] = R


def fig_head_resp(heads, resp_band):
    fig, axs = plt.subplots(len(heads), 2, figsize=(13, 2.4 * len(heads) + 0.9),
                            gridspec_kw=dict(width_ratios=[2.3, 1]))
    for i, H in enumerate(heads):
        R = H["resp"]
        t = np.arange(len(R["base"])) / 10
        ax = axs[i, 0]
        ax.fill_between(t, -45, 45, where=R["art"], color=GREY2, alpha=0.6, lw=0,
                        label="Lidschlag-/Bewegungstransiente (±1,5 s)")
        ax.plot(t, np.clip(R["base"], -40, 40), color=C[0], lw=0.7, label="CH2-Basislinie 0,05–1 Hz (µV)")
        z = R["menv"] / np.std(R["menv"]) * 4 - 62
        ax.plot(t, np.clip(z, -85, -42), color=C[1], lw=0.7, label="Mikrofon-Hüllkurve 150–450 Hz (normiert)")
        ax.set_ylim(-85, 45)
        ax.set_yticks([-25, 0, 25])
        ax.set_title(f"{H['label']}: {R['n_win']} ruhige 60-s-Fenster", fontsize=9)
        ax.set_ylabel("µV")
        ax2 = axs[i, 1]
        ax2.axvspan(resp_band[0], resp_band[1], color=GREY2, alpha=0.7, lw=0, label="Atemfrequenz Brust-EKG (EDR)")
        if R["n_win"]:
            f = R["f"] * 60
            m = (f >= 4) & (f <= 50)
            nb = R["Pb"][m] / np.median(R["Pb"][m])
            nm = R["Pm"][m] / np.median(R["Pm"][m])
            ax2.semilogy(f[m], nb, color=C[0], lw=1.1, label="Basislinie")
            ax2.semilogy(f[m], nm, color=C[1], lw=1.1, label="Mikrofon")
            ax2.text(0.98, 0.92, f"Atemband/Nachbarn: {R['ratio_b']:.2f} | {R['ratio_m']:.2f}",
                     transform=ax2.transAxes, ha="right", va="top", fontsize=7.5)
        else:
            ax2.text(0.5, 0.5, "kein artefaktfreies\n60-s-Fenster (Lidschläge)", transform=ax2.transAxes,
                     ha="center", va="center", fontsize=8.5, color="#52514e")
            ax2.set_yscale("log")
        ax2.set_ylim(0.05, 30)
        ax2.set_xlim(4, 50)
        ax2.set_ylabel("rel. Leistung", fontsize=8)
    axs[-1, 0].set_xlabel("Zeit (s)")
    axs[-1, 1].set_xlabel("Frequenz (1/min)")
    h1, l1 = axs[0, 0].get_legend_handles_labels()
    h2, l2 = axs[1, 1].get_legend_handles_labels()
    fig.legend(h1 + h2, l1 + l2, loc="upper center", ncol=3, fontsize=7.5, bbox_to_anchor=(0.5, 0.975))
    fig.suptitle("Atmung am Kopf: CH2-Basislinie ist von Lidschlägen dominiert; in ruhigen Fenstern keine Atemlinie",
                 x=0.01, y=0.995, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.935))
    save(fig, "heart_06_kopf_atmung.png")


def abr_residual(heads, tmpl_n, chest5, amps_uv=(10, 30)):
    """Simulated cardiac residual in the click average of run 2."""
    print("\n=== Herzfeld im ABR-Mittel (Simulation) ===")
    H = heads[1]
    fs = H["fs"]
    t24 = ss.resample_poly(np.r_[np.zeros(100), tmpl_n, np.zeros(100)], 24, 1)[2400:-2400]
    # content of the chest QRS above 100 Hz (1 kHz block-mean data, so only up to ~450 Hz)
    hb = bpf(np.r_[np.zeros(300), tmpl_n, np.zeros(300)], 100, 450, 1000, 2)
    frac = np.ptp(hb) / 1.0
    rr5 = chest5["rr"][chest5["ok"]]
    n = len(H["raw24"])
    out = {}
    L, D = H["L"], H["D"]
    pre, post = int(0.002 * fs), int(0.012 * fs)
    on = D + np.arange(1, (n - D - post) // L) * L
    on = on[on > 80 * fs]                       # calm part, as in bera_analysis (block rejection)
    for A in amps_uv:
        ecg, beats = synth_ecg(n, fs, t24, rr5, A, offset=int(0.37 * fs))
        y = ss.sosfiltfilt(sos("bandpass", [100, 1500], fs, 2), ecg)
        for k in range(1, 32):
            y = ss.filtfilt(*ss.iirnotch(50.0 * k, 50.0 * k / 4.0, fs), y)
        E = np.stack([y[o - pre:o + post] for o in on])
        avg = E.mean(axis=0)
        tt = np.arange(-pre, post) / fs * 1e3
        w = (tt >= 1) & (tt <= 10)
        nn = np.unique(np.round(np.logspace(1, np.log10(len(E)), 25)).astype(int))
        cum = np.cumsum(E, axis=0)
        run = np.array([np.std(cum[k - 1][w] / k) for k in nn])
        # sweep variance by cardiac phase
        last = np.searchsorted(beats, on) - 1
        ph = (on - beats[np.clip(last, 0, None)]) / fs * 1e3
        sw = np.sqrt((E[:, w] ** 2).mean(axis=1))
        bins = np.arange(-50, 1000, 50)
        ph2 = np.where(ph > 900, ph - (rr5.mean()), ph)
        out[A] = dict(avg=avg, tt=tt, rms=np.std(avg[w]), nn=nn, run=run, ph=ph, sw=sw,
                      band_rms=np.std(y[int(80 * fs):]), qrs_band=np.ptp(y[beats[50] - 2400:beats[50] + 2400]))
        print(f"QRS {A} µV: im 100–1500-Hz-Band {out[A]['qrs_band'] * 1e3:.0f} nV Spitze-Spitze, "
              f"Band-RMS {out[A]['band_rms'] * 1e3:.1f} nV, Restanteil im Mittel aus {len(E)} Sweeps "
              f"{out[A]['rms'] * 1e3:.2f} nV RMS (1–10 ms); Sweep-RMS max {sw.max() * 1e3:.0f} nV vs. EEG ~2000 nV")
    print(f"Anteil des Brust-QRS oberhalb 100 Hz: {100 * frac:.1f} % der QRS-Spitze-Spitze")
    return out, frac, len(on)


def fig_abr(out, frac, n_sw):
    fig, ax = plt.subplots(1, 3, figsize=(13.5, 4.2))
    for j, (A, o) in enumerate(out.items()):
        ax[0].plot(o["tt"], o["avg"] * 1e3, color=C[j], lw=1.2, label=f"QRS {A} µV")
        ax[1].loglog(o["nn"], o["run"] * 1e3, color=C[j], lw=1.2, label=f"QRS {A} µV")
        ph = o["ph"]
        b = np.arange(0, 1000, 25)
        idx = np.digitize(ph, b)
        mv = [o["sw"][idx == k].mean() * 1e3 if np.any(idx == k) else np.nan for k in range(1, len(b))]
        ax[2].plot(b[:-1] + 12.5, mv, color=C[j], lw=1.2, label=f"QRS {A} µV")
    ax[0].axhspan(-65, 65, color=GREY2, alpha=0.6, lw=0, label="Restrauschen Lauf 2 (±1 σ, 65 nV)")
    ax[0].axhline(164, color="#52514e", lw=0.8, ls=":")
    ax[0].text(9.5, 150, "Welle V 164 nV", ha="right", va="top", fontsize=7.5, color="#52514e")
    ax[0].set_ylim(-200, 200)
    ax[0].set_xlabel("Zeit nach Klick (ms)")
    ax[0].set_ylabel("nV")
    ax[0].set_title(f"Simulierter Herz-Rest im ABR-Mittel ({n_sw} Sweeps)")
    ax[0].legend(fontsize=7, loc="lower right")
    nn = list(out.values())[0]["nn"]
    ax[1].loglog(nn, 2000 / np.sqrt(nn), color=GREY, lw=1.2, ls="--", label="EEG-Rauschen 2 µV/√N")
    ax[1].set_xlabel("Anzahl gemittelter Sweeps")
    ax[1].set_ylabel("RMS 1–10 ms (nV)")
    ax[1].set_title("Herz-Rest im Mittel ~100× unter dem EEG-Rest")
    ax[1].legend(fontsize=7, loc="lower left")
    ax[2].axhline(2000, color=GREY, lw=1.2, ls="--")
    ax[2].text(980, 1000, "EEG-Sweep-SD Lauf 2 ≈ 2000 nV", ha="right", va="top", fontsize=7.5, color="#52514e")
    ax[2].set_yscale("log")
    ax[2].set_ylim(0.01, 5000)
    ax[2].set_xlabel("Herzphase: Zeit seit R-Zacke (ms)")
    ax[2].set_ylabel("Sweep-RMS des Herzanteils (nV)")
    ax[2].set_title("Herzanteil pro Sweep je Herzphase")
    ax[2].text(980, 0.03, "ab ~200 ms nur Rauschen\ndes Brust-Templates", ha="right", fontsize=7.5, color="#52514e")
    ax[2].legend(fontsize=7, loc="lower left")
    fig.suptitle(f"Herzfeld und ABR: Simulation mit Brust-EKG-Form (Anteil > 100 Hz: {100 * frac:.1f} % der QRS-Amplitude, "
                 "Daten nur bis 450 Hz)", x=0.01, ha="left")
    fig.tight_layout()
    save(fig, "heart_07_abr_herzrest_simulation.png")


def fig_timeline(chest, heads, battery):
    fig, ax = plt.subplots(2, 1, figsize=(13, 6.2), sharex=True, gridspec_kw=dict(height_ratios=[2.2, 1]))
    def tnum(ts):
        return matplotlib.dates.date2num(dt.datetime.fromtimestamp(ts, TZ).replace(tzinfo=None))
    for i, R in enumerate(chest):
        col = C[i % 4] if i < 4 else "#52514e"
        tb = R["tb"][R["ok"]]
        hr = 60e3 / R["rr"][R["ok"]]
        # stretch the 60-s recording to 4 min on the axis so it is visible
        ax[0].plot([tnum(R["t0"] + t * 4) for t in tb], hr, color=col, lw=0.9)
        ax[0].plot(tnum(R["t0"] + 120), R["H"]["hr"], "o", color=col, ms=7, mec="white")
        ax[0].annotate(f"{R['label'].split(' (')[0]}\n{R['H']['hr']:.0f}/min" + ("" if R["name"] in T_EXACT else "*"),
                       (tnum(R["t0"] + 120), R["H"]["hr"]), xytext=(0, 26), textcoords="offset points",
                       ha="center", fontsize=7.5)
        RR = R["slid"]["EDR"]
        ax[1].plot([tnum(R["t0"] + t * 4) for t in RR[0]], RR[1], color=col, marker="o", ms=2.5, lw=0.8)
    for i, H in enumerate(heads):
        a, b = tnum(H["t0"]), tnum(H["t0"] + H["dur"])
        for k in range(2):
            ax[k].axvspan(a, b, color=C[i], alpha=0.12, lw=0)
        ax[0].text((a + b) / 2, 50.5, H["label"].replace(" (", "\n("), ha="center", fontsize=7.5, color="#52514e")
    ax[0].text(tnum(heads[0]["t0"] - 60), 88, "Kopfläufe: EKG und Atmung nicht nachweisbar\n(HF-Trend ab 23:25 fehlt)",
               fontsize=8, color="#52514e")
    ax[0].set_ylim(48, 95)
    ax[0].set_ylabel("Herzfrequenz (1/min)")
    ax[0].set_title("Herzfrequenz über den Abend (Brust-EKG je 60–75 s, auf der Zeitachse 4× gedehnt; * Startzeit geschätzt)")
    ax[1].set_ylabel("Atemzüge/min (EDR)")
    ax[1].set_ylim(4, 26)
    ax[1].set_title("Atemfrequenz aus EDR (QRS-Amplitude), 30-s-Fenster")
    ax[1].xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%H:%M"))
    ax[1].set_xlabel("Ortszeit 16./17.10.2026")
    fig.tight_layout()
    save(fig, "heart_08_zeitverlauf_abend.png")


def main():
    chest = chest_analysis()
    fig_chest_overview(chest)
    fig_chest_hrv(chest)
    fig_chest_resp(chest)
    c5 = chest[-1]
    hr_all = np.concatenate([60e3 / R["rr"][R["ok"]] for R in chest])
    hr_band = (np.percentile(hr_all, 2), np.percentile(hr_all, 98))
    rates = np.array([R["rates"]["EDR"] for R in chest if R["name"] != "2_drl_hand"])
    resp_band = (rates.min() - 1, rates.max() + 1)
    print(f"HF-Bereich Brust {hr_band[0]:.0f}–{hr_band[1]:.0f}/min, Atembereich {resp_band}")
    heads = []
    for name, label in HEAD_RUNS:
        H = load_head(name)
        H["label"] = label
        heads.append(H)
        print(f"{label}: Start {dt.datetime.fromtimestamp(H['t0'], TZ):%H:%M:%S}, {H['dur']:.0f} s, D={H['D']}")
    tmpl_n, rr5 = head_cardiac(heads, c5)
    fig_head_detect(heads, tmpl_n, c5)
    fig_sweep_hr(heads, hr_band)
    head_resp(heads, resp_band)
    fig_head_resp(heads, resp_band)
    out, frac, n_sw = abr_residual(heads, tmpl_n, c5)
    fig_abr(out, frac, n_sw)
    fig_timeline(chest, heads, None)


if __name__ == "__main__":
    main()
