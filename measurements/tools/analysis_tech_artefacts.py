"""Technical artefacts and data quality of the Wireless BERA recordings (2026-10-16).

Usage: analysis_tech_artefacts.py [bera_dir] [ecg_dir]

Looks at everything in the BERA runs that is not the ABR: Wi-Fi coupling
(packet rate, beacons, bursts), packet loss, mains, supply/battery, int16
quantisation, DC offset, the electrical click artefact, and a per-sweep
quality map. Figures go to <bera_dir>/analysis/tech_*.png (German labels).

All CH2 values are referred to the electrodes (µV, sign corrected); CH1 is the
headset microphone in codec counts (1 count = 86.3 µV at the codec input).
Lost packets (valid = False) are linearly interpolated for filtering and
spectra, and excluded from every average and statistic.
"""
import datetime as dt
import json
import locale
import os
import sys

import numpy as np
import scipy.signal as ss
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap

HERE = os.path.dirname(os.path.abspath(__file__))
BERA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "2026-10-16_bera")
ECG = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "..", "2026-10-16_ecg_drl")
OUT = os.path.join(BERA, "analysis")
os.makedirs(OUT, exist_ok=True)

try:
    locale.setlocale(locale.LC_NUMERIC, "de_DE.UTF-8")
    plt.rcParams["axes.formatter.use_locale"] = True
except locale.Error:
    pass
plt.rcParams.update({"font.size": 9, "axes.titlesize": 10, "axes.labelsize": 9,
                     "legend.fontsize": 8, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.alpha": 0.25, "figure.dpi": 130})

C = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
GREY = "#8a8a8a"
LGREY = "#cfcfcf"

FS = 24000.0
GAIN = 16.0
FSV = 2.0 * np.sqrt(2.0)
UV_PER_LSB = FSV / 32768 / GAIN * 1e6          # 5.39 µV at the electrodes
L_CLICK = int(48000 / 21.1) // 2               # 1137 samples at 24 kHz (firmware: (uint32_t)(fs/rate))
PKT = 128                                      # decimated frames per WebSocket packet
TU = 1.024e-3                                  # Wi-Fi time unit
BEACON = 100 * TU                              # 102.4 ms

RUNS = [
    dict(key="0", file="0_rest_no_stimulus", name="Lauf 0 Ruhe", amp=0.0, col=GREY),
    dict(key="1", file="1_click_amp0.10_21Hz", name="Lauf 1 Klick 0,10 (sitzend)", amp=0.10, col=C[0]),
    dict(key="2", file="2_click_amp0.05_21Hz", name="Lauf 2 Klick 0,05 (liegend)", amp=0.05, col=C[1]),
    dict(key="3", file="3_click_sham_toneburst_continuous", name="Lauf 3 A/B/C (liegend)", amp=0.035, col=C[2]),
    dict(key="4", file="4_sham_click_amp0.035_earbud_out", name="Lauf 4 Ohrhörer draußen", amp=0.035, col=C[3]),
]


def de(x, nd=2):
    return f"{x:.{nd}f}".replace(".", ",")


def save(fig, name):
    path = os.path.join(OUT, name)
    fig.savefig(path, dpi=130)
    plt.close(fig)
    print("wrote", path)


def read_log(path):
    marks, vbat = [], []
    if not os.path.exists(path):
        return marks, vbat
    for line in open(path):
        p = line.split()
        if not p:
            continue
        if p[0][:1].isdigit() and "." in p[0] and len(p[0]) > 12:
            marks.append((float(p[0]), " ".join(p[1:])))
        elif p[0] == "vbat":                               # "vbat after A: 3346 mV"
            vbat.append((len(marks), float(p[-2]) / 1000))
        elif ":" in p[0] and p[1] == "vbat":               # "00:07:58 vbat 3252 False"
            vbat.append((p[0], float(p[2]) / 1000))
    return marks, vbat


def interp_gaps(x, valid):
    x = x.astype(float)
    if (~valid).any():
        i = np.arange(len(x))
        x[~valid] = np.interp(i[~valid], i[valid], x[valid])
    return x


def comb(x, f0, fmax, fs=FS):
    for k in range(1, int(fmax // f0) + 2):
        fk = k * f0
        if fk < fs / 2 - 10:
            b, a = ss.iirnotch(fk, fk / 4.0, fs)       # 4 Hz wide, as in bera_average.py
            x = ss.filtfilt(b, a, x)
    return x


def line_amp(f, p, f0, half, navg=None):
    """RMS of a narrow line at f0 from a density PSD (local median background removed).

    Returns (amplitude, noise power in the window as rms); with navg (number of
    Welch segments) the second value is the 3-sigma detection limit instead.
    """
    df = f[1] - f[0]
    d = np.abs(f - f0)
    sel = d <= half
    bg_sel = (d > 2 * half + df) & (d < 2 * half + max(3.0, 20 * df))
    bg = np.median(p[bg_sel])
    pw = (p[sel] - bg).sum() * df
    if navg:
        return np.sqrt(max(pw, 0.0)), np.sqrt(3 * bg * df * sel.sum() / np.sqrt(navg))
    return np.sqrt(max(pw, 0.0)), np.sqrt(bg * df * sel.sum())


def fold(x, valid, period, start=0):
    n = (len(x) - start) // period
    X = x[start:start + n * period].reshape(n, period)
    V = valid[start:start + n * period].reshape(n, period)
    cnt = V.sum(0)
    m = (X * V).sum(0) / cnt
    s = np.sqrt((((X - m) ** 2) * V).sum(0) / (cnt - 1))
    return m, s / np.sqrt(cnt), n


def click_phase(x, valid, L=L_CLICK):
    """Phase of the polarity-alternating click artefact (as bera_average.py)."""
    hp = ss.sosfiltfilt(ss.butter(4, 300, "hp", fs=FS, output="sos"), x)
    m, _, _ = fold(hp, valid, 2 * L)
    prof = np.abs(m[:L] - m[L:]) / 2
    return int(np.argmax(prof))


# ---------------------------------------------------------------- battery
def battery_points():
    pts = []
    t1 = float(np.load(os.path.join(BERA, RUNS[1]["file"] + ".npz"))["t_start"])
    pts.append((t1 - 60, 3.42))
    d2 = np.load(os.path.join(BERA, RUNS[2]["file"] + ".npz"))
    pts.append((float(d2["t_start"]) + len(d2["valid"]) / FS, 3.39))
    m3, v3 = read_log(os.path.join(BERA, RUNS[3]["file"] + ".log"))
    for idx, v in v3:                                   # value written after mark idx-1 started block idx
        pts.append((m3[idx - 1][0], v))                 # logged right after mark idx-1
    m4, v4 = read_log(os.path.join(BERA, RUNS[4]["file"] + ".log"))
    day = dt.datetime.fromtimestamp(m4[0][0]).date()
    for hms, v in v4:
        h, mi, s = map(int, hms.split(":"))
        pts.append((dt.datetime(day.year, day.month, day.day, h, mi, s).timestamp(), v))
    pts.append((m4[-1][0], 3.23))
    pts.sort()
    return np.array(pts)


VB = None


def vbat_at(t):
    return np.interp(t, VB[:, 0], VB[:, 1])


# ---------------------------------------------------------------- per-run analysis
def analyse(run):
    d = np.load(os.path.join(BERA, run["file"] + ".npz"))
    valid = d["valid"].astype(bool)
    raw = d["ch2"].astype(np.int16)
    n = len(raw)
    t0 = float(d["t_start"])
    stim = json.loads(str(d["stimulus"]))
    uv = interp_gaps(-raw.astype(float) * UV_PER_LSB, valid)
    mic = interp_gaps(d["ch1"].astype(float), valid)
    uv -= uv[valid].mean()
    mic -= mic[valid].mean()
    pk_phase = int(((d["epochs"][1:, 0] - d["first_frame0"]) // 2 % PKT)[0])
    marks, vlog = read_log(os.path.join(BERA, run["file"] + ".log"))
    R = dict(run, n=n, dur=n / FS, t0=t0, stim=stim, marks=[(m - t0, lab) for m, lab in marks])
    ev = [m - t0 for m, lab in marks if lab != "end" and m - t0 > 1]
    day = dt.datetime.fromtimestamp(t0).date()
    for hms, _v in vlog:
        if isinstance(hms, str):
            h, mi, sec = map(int, hms.split(":"))
            ev.append(dt.datetime(day.year, day.month, day.day, h, mi, sec).timestamp() + 0.5 - t0)
    R["events"] = np.array(sorted(e for e in ev if 0 < e < n / FS))
    print(f"--- {run['name']}: {n / FS:.0f} s, loss {100 * (1 - valid.mean()):.2f} %")

    # spectra
    nhr = min(2 ** 17, max(2 ** 15, n // 4))
    f, p = ss.welch(uv, FS, nperseg=nhr)
    R["f_hr"], R["p_hr"] = f, p
    fm, pm = ss.welch(mic, FS, nperseg=nhr)
    R["p_hr_mic"] = pm
    f, p = ss.welch(uv, FS, nperseg=2 ** 14)
    R["f_ov"], R["p_ov"] = f, p
    R["p_ov_mic"] = ss.welch(mic, FS, nperseg=2 ** 14)[1]
    f16, p16 = ss.welch(uv, FS, nperseg=min(2 ** 16, n))

    # mains f0 (global + tracked) and harmonics
    fh, ph = R["f_hr"], R["p_hr"]
    cand = np.arange(49.85, 50.15, 0.0005)              # harmonic-sum search (works when 50 Hz itself is weak)
    lp = np.log(ph)
    score = [sum(np.interp(k * c, fh, lp) - np.median(lp[(fh > k * c - 8) & (fh < k * c + 8)])
                 for k in (1, 3, 5, 7, 9)) for c in cand]
    f0 = cand[int(np.argmax(score))]
    R["f0"] = f0
    R["harm"] = np.array([line_amp(f16, p16, k * f0, max(0.8, 0.06 * k))[0] for k in range(1, 31)])
    R["harm_floor"] = np.array([line_amp(f16, p16, k * f0, max(0.8, 0.06 * k))[1] for k in range(1, 31)])
    lo = ss.resample_poly(uv, 1, 24)                    # 1 kHz
    bp = ss.sosfiltfilt(ss.butter(2, [48.5, 51.5], "bp", fs=1000, output="sos"), lo)
    ph_ = np.unwrap(np.angle(ss.hilbert(bp)))
    W = 5000
    nw = len(ph_) // W
    tt, ff0, aa = [], [], []
    snr = []
    for k in range(nw):
        seg = ph_[k * W:(k + 1) * W]
        sl = np.polyfit(np.arange(W) / 1000, seg, 1)[0] / (2 * np.pi)
        tt.append((k + 0.5) * W / 1000)
        ff0.append(sl)
        aa.append(bp[k * W:(k + 1) * W].std() * np.sqrt(2))
        fw_, pw_ = ss.periodogram(lo[k * W:(k + 1) * W], 1000, window="hann")
        snr.append(pw_[(fw_ > 49.5) & (fw_ < 50.5)].max() / np.median(pw_[(fw_ > 35) & (fw_ < 65)]))
    R["f0_snr"] = np.array(snr)
    R["f0_t"], R["f0_v"], R["f0_a"] = np.array(tt), np.array(ff0), np.array(aa)
    good = R["f0_snr"] > 30
    if good.sum() >= 1:                                 # tracked phase slope is more precise than the spectrum
        f0 = float(np.median(R["f0_v"][good]))
        R["f0"] = f0

    # filter chains
    sos_bp = ss.butter(2, [100, 1500], "bp", fs=FS, output="sos")
    y_abr = comb(ss.sosfiltfilt(sos_bp, uv), f0, 1500)
    y_hp = comb(ss.sosfiltfilt(ss.butter(4, 100, "hp", fs=FS, output="sos"), uv), f0, 3000)
    mic_hp = ss.sosfiltfilt(ss.butter(4, 100, "hp", fs=FS, output="sos"), mic)
    R["p_abr_nocomb"] = ss.welch(ss.sosfiltfilt(sos_bp, uv), FS, nperseg=min(2 ** 16, n))[1]
    R["p_abr"] = ss.welch(y_abr, FS, nperseg=min(2 ** 16, n))[1]
    R["f16"] = f16
    nav = n / len(f16)
    ha = np.array([line_amp(f16, R["p_abr"], k * f0, max(0.8, 0.06 * k), nav) for k in range(1, 31)])
    R["harm_after"], R["harm_after_lim"] = ha[:, 0], ha[:, 1]
    hb = np.array([line_amp(f16, p16, k * f0, max(0.8, 0.06 * k), nav) for k in range(1, 31)])
    R["harm_lim"] = hb[:, 1]
    R["harm_before_bp"] = np.array([line_amp(f16, R["p_abr_nocomb"], k * f0, max(0.8, 0.06 * k))[0] for k in range(1, 31)])

    # Wi-Fi / CPU-locked folds
    folds = {}
    for P in (PKT, 2 * PKT, 24, 12288):
        folds[P] = fold(y_hp, valid, P, start=pk_phase)
    R["folds"] = folds
    R["fold_mic"] = fold(mic_hp, valid, PKT, start=pk_phase)
    R["noise_hp"] = y_hp[valid].std()
    # beacon fold: phase of 102.4 ms in 256 bins (non-integer period)
    R["_y_hp"], R["_valid"] = y_hp, valid             # beacon fold done after the gap period is known

    # HF envelope (2-10 kHz) in 0.25 ms bins, ACF, gap-locked average
    hf = ss.sosfiltfilt(ss.butter(4, [2000, 10000], "bp", fs=FS, output="sos"), uv)
    B = 6
    nb = n // B
    e = (hf[:nb * B] ** 2).reshape(nb, B).mean(1)
    vb = valid[:nb * B].reshape(nb, B).all(1)
    e = np.where(vb, e, np.median(e[vb]))
    ec = e - e.mean()
    nfft = 1 << int(np.ceil(np.log2(2 * nb)))
    F = np.fft.rfft(ec, nfft)
    acf = np.fft.irfft(F * np.conj(F))[:int(1.2 * FS / B)]
    R["acf"] = acf / acf[0]
    R["acf_dt"] = B / FS
    # HF signal folded on the tracked mains phase (mains-synchronous spikes)
    phs = (np.interp(np.arange(n) / FS, np.arange(len(ph_)) / 1000, ph_) % (2 * np.pi)) / (2 * np.pi)
    pb = (phs * 480).astype(int).clip(0, 479)
    cnt = np.bincount(pb[valid], minlength=480)
    pw2 = hf[valid] ** 2
    pw2 = np.minimum(pw2, 30 * np.median(pw2))           # one movement spike must not dominate the fold
    R["hf_mains"] = np.bincount(pb[valid], weights=pw2, minlength=480) / cnt / np.median(pw2)
    R["hf_floor_nv"] = np.sqrt(np.median(R["p_ov"][(R["f_ov"] > 2000) & (R["f_ov"] < 8000)])) * 1e3
    # 10 ms windows: burst statistics
    W10 = int(0.010 * FS / B)
    e10 = e[:len(e) // W10 * W10].reshape(-1, W10).mean(1)
    R["burst_frac"] = float(np.mean(e10 > 4 * np.median(e10)))

    # spectrogram (for the overview figure)
    fsg, tsg, S = ss.spectrogram(uv, FS, nperseg=512, noverlap=0)
    k = max(1, int(0.5 / (512 / FS)))
    ncol = S.shape[1] // k
    S = S[:, :ncol * k].reshape(len(fsg), ncol, k).mean(2)
    R["sg"] = (fsg, tsg[:ncol * k].reshape(ncol, k).mean(1), S / np.median(S, axis=1, keepdims=True))

    # packet loss
    ff = (d["epochs"][:, 0] - d["first_frame0"]) // 2
    dff = np.diff(ff)
    g = dff > PKT
    R["gap_t"] = (ff[:-1][g] + PKT) / FS
    R["gap_len"] = (dff[g] - PKT) // PKT
    R["loss"] = 1 - valid.mean()
    if len(R["gap_t"]) > 20:
        Ps = np.linspace(0.50, 0.55, 50001)
        Rz = np.abs(np.exp(2j * np.pi * R["gap_t"][None, :] / Ps[:, None]).mean(1)) if len(R["gap_t"]) < 300 else \
            np.array([abs(np.exp(2j * np.pi * R["gap_t"] / P).mean()) for P in Ps])
        R["gap_period"] = Ps[np.argmax(Rz)]
        R["gap_R"] = Rz.max()

    # gap-locked HF envelope (±150 ms around each gap start)
    wb = int(0.15 * FS / B)
    gi = (R["gap_t"] * FS / B).astype(int)
    gi = gi[(gi > wb) & (gi < len(e) - wb)]
    e_nan = np.where(vb, e, np.nan)
    R["gap_env"] = np.nanmean([e_nan[j - wb:j + wb] for j in gi], axis=0) / np.nanmedian(e_nan) if len(gi) else None

    # microphone speech envelope: 0.1 s RMS of 300-3000 Hz, relative to a 20 s running median
    sp = ss.sosfiltfilt(ss.butter(4, [200, 4000], "bp", fs=FS, output="sos"), mic)
    Wc = int(20 * FS) // L_CLICK * L_CLICK              # remove the click-locked mic signal per 20 s
    for a0 in range(0, n - Wc + 1, Wc):
        seg = sp[a0:a0 + Wc].reshape(-1, L_CLICK)
        sp[a0:a0 + Wc] = (seg - seg.mean(0)).ravel()
    W1 = int(0.1 * FS)
    env = np.sqrt((sp[:n // W1 * W1] ** 2).reshape(-1, W1).mean(1))
    base = ss.medfilt(env, 201) if len(env) > 201 else np.full_like(env, np.median(env))
    R["mic_env"] = env / base
    R["speech"] = ss.medfilt((R["mic_env"] > 1.45).astype(float), 5) > 0

    # click grid, artefact templates and per-sweep quality
    L = L_CLICK
    if stim["type_name"] != "off":
        endA = int((marks[1][0] - t0) * FS) if len(marks) > 2 else n
        D = click_phase(uv[:endA], valid[:endA])
    else:
        D = 0
    R["D"] = D
    hp300 = ss.sosfiltfilt(ss.butter(4, 300, "hp", fs=FS, output="sos"), uv)
    blocks = [("", 0, n, run["amp"])]
    if run["key"] == "3":
        mk = [(m - t0) for m, _ in marks]
        blocks = [("3A Klick 0,035", mk[0] + 3, mk[1] - 0.5, 0.035),
                  ("3B Schein (re. Kanal offen)", mk[1] + 3, mk[2] - 0.5, 0.035),
                  ("3C Tonburst 2 kHz 0,01", mk[2] + 3, n / FS, 0.01)]
        blocks = [(lab, int(a * FS), int(min(b * FS, n)), am) for lab, a, b, am in blocks]
    tmpl = []
    for lab, a, b, am in blocks:
        a = D + int(np.ceil((a - D - 1 + L) / (2 * L))) * 2 * L      # keeps a - L/2 >= 0 and click parity
        nn = (b - a) // (2 * L) * 2 * L
        out = {}
        for nm, sig in (("hp100", y_hp), ("hp300", hp300), ("abr", y_abr), ("mic", mic_hp)):
            m_, se_, k_ = fold(sig[a - L // 2:a - L // 2 + nn], valid[a - L // 2:a - L // 2 + nn], 2 * L)
            alt = (m_[:L] - m_[L:]) / 2
            com = (m_[:L] + m_[L:]) / 2
            out[nm] = (alt, com, np.sqrt(se_[:L] ** 2 + se_[L:] ** 2) / 2)
        # artefact amplitude in 30 s chunks (stability)
        chunk = int(30 * FS) // (2 * L) * 2 * L
        amps = []
        for c0 in range(a, a + nn - chunk + 1, chunk):
            m_, _, _ = fold(hp300[c0 - L // 2:c0 - L // 2 + chunk], valid[c0 - L // 2:c0 - L // 2 + chunk], 2 * L)
            alt = (m_[:L] - m_[L:]) / 2
            amps.append(((c0 - a) / FS + 15, np.abs(alt[L // 2 - 12:L // 2 + 24]).max()))
        tmpl.append(dict(label=lab or run["name"], amp=am, t=(np.arange(L) - L // 2) / FS * 1e3,
                         sweeps=nn // L, chunks=np.array(amps), **out))
    R["tmpl"] = tmpl

    on = D + np.arange((n - D - int(0.03 * FS)) // L) * L
    on = on[on > int(0.03 * FS)]
    pre, post = int(0.002 * FS), int(0.012 * FS)
    cv = np.concatenate([[0], np.cumsum(~valid)])
    gap = (cv[on + post + 240] - cv[on - pre - 240]) > 0
    idx = on[:, None] + np.arange(-pre, post)[None, :]
    ep = y_abr[idx]
    pk = np.abs(ep[:, pre:]).max(1)
    sd = ep.std(1)
    emg = (pk > 25) & ~gap
    ok = ~gap & ~emg
    nblk = len(on) // 64
    bsd = np.array([np.median(sd[k * 64:(k + 1) * 64][ok[k * 64:(k + 1) * 64]])
                    if ok[k * 64:(k + 1) * 64].sum() > 8 else np.nan for k in range(nblk)])
    brej = bsd > 1.5 * np.nanmedian(bsd)
    blk = np.zeros(len(on), bool)
    for k in np.where(brej)[0]:
        blk[k * 64:(k + 1) * 64] = True
    blk &= ok
    q = np.zeros(len(on), int)                         # 0 clean, 1 noise/EMG, 2 block rejected, 3 gap
    q[emg] = 1
    q[blk] = 2
    q[gap] = 3
    R["q_t"], R["q"], R["sweep_sd"] = on / FS, q, sd
    R["blk_t"] = (np.arange(nblk) * 64 + 32) * L / FS + D / FS
    R["blk_sd"] = bsd
    R["frac"] = np.bincount(q, minlength=4) / len(q)
    R["sweep_sd_clean"] = np.median(sd[q == 0]) if (q == 0).any() else np.nan

    # 30 s windows: floors, mains, DC, 1 kHz comb, loss -> battery trend
    win = int(30 * FS) if n > 60 * FS else n
    rows = []
    for a in range(0, n - win + 1, win):
        seg = uv[a:a + win]
        fw, pw = ss.welch(seg, FS, nperseg=2 ** 15)
        fl_hf = np.sqrt(np.median(pw[(fw > 2000) & (fw < 8000)])) * 1e3
        fl_mid = np.sqrt(np.median(pw[(fw > 300) & (fw < 1500)])) * 1e3
        a50 = line_amp(fw, pw, f0, 1.0)[0]
        k1 = sum(line_amp(fw, pw, 1000 * k * 0.999977, 0.8)[0] ** 2 for k in (2, 3, 6, 7, 8)) ** 0.5
        dc = raw[a:a + win][valid[a:a + win]].mean()
        rows.append((t0 + (a + win / 2) / FS, fl_hf, fl_mid, a50, k1, dc,
                     1 - valid[a:a + win].mean()))
    R["win"] = np.array(rows)
    W10s = int(10 * FS)
    R["dc10"] = np.array([(t0 + (a + W10s / 2) / FS, raw[a:a + W10s][valid[a:a + W10s]].mean())
                          for a in range(0, n - W10s + 1, W10s)]) if n >= W10s else \
        np.array([(t0 + n / 2 / FS, raw[valid].mean())])
    R["dc"] = raw[valid].mean()
    R["raw_pct"] = np.percentile(raw[valid], [0.01, 0.5, 50, 99.5, 99.99])
    R["raw_minmax"] = (int(raw[valid].min()), int(raw[valid].max()))
    calm = slice(int(150 * FS), int(400 * FS)) if run["key"] == "2" else slice(0, n)
    R["codes"] = np.bincount((raw[calm][valid[calm]].astype(int) + 200).clip(0, 400), minlength=401)
    R["raw_sd"] = raw[calm][valid[calm]].std()
    hpq = ss.sosfiltfilt(ss.butter(4, 2000, "hp", fs=FS, output="sos"), -raw[calm].astype(float))
    R["hf_sd_lsb"] = hpq[valid[calm]].std()

    # narrowband spurs (> 8 dB over the local median, 60 Hz .. 11.9 kHz)
    fh, ph = R["f_hr"], R["p_hr"]
    bg = ss.medfilt(ph, 301)
    pk_, _ = ss.find_peaks(ph / bg, height=6.3 if n > 60 * FS else 12, distance=4)
    pk_ = pk_[(fh[pk_] > 60) & (fh[pk_] < 11950)]
    spurs = []
    for j in pk_:
        amp, _ = line_amp(fh, ph, fh[j], 2.5 * (fh[1] - fh[0]))
        spurs.append((fh[j], amp))
    R["spurs"] = spurs
    return R


def classify(f, f0):
    if abs(f / 999.977 - round(f / 999.977)) * 999.977 < 0.3:
        return 2                                        # 1 kHz comb
    if abs(f - round(f / 187.5) * 187.5) < 0.2:
        return 3                                        # Wi-Fi packet rate
    if abs(f - round(f / f0) * f0) < 0.3 + 0.0005 * f:
        return 0                                        # mains (f0 wanders ±0.02 Hz)
    h = 48000 / 2274 / 2
    if abs(f - round(f / h) * h) < 0.1:
        return 1                                        # click comb
    return 4


# ---------------------------------------------------------------- chest ECG reference
def chest():
    out = []
    for fn, lab in (("1_no_drl.csv", "Brust ohne DRL"), ("2_drl_hand.csv", "Brust DRL Hand"),
                    ("3_drl_chest.csv", "Brust DRL Brust"), ("4_drl_chest_repeat.csv", "Brust DRL Brust (Wdh.)")):
        x = np.loadtxt(os.path.join(ECG, fn), delimiter=",", skiprows=4)
        uv = -x[:, 2] / 32768 * FSV / GAIN * 1e6
        f, p = ss.welch(uv - uv.mean(), 1000, nperseg=8192)
        m = (f > 49.5) & (f < 50.5)
        f0 = f[m][np.argmax(p[m])]
        hk = []
        for k in range(1, 10):
            fk = k * f0
            h = abs(np.sin(np.pi * fk * 48 / 48000) / (48 * np.sin(np.pi * fk / 48000)))
            hk.append(line_amp(f, p, fk, 0.6)[0] / h)
        out.append((lab, np.array(hk)))
    return out


def phase_fold(y, valid, period, nbins=64):
    ph = ((np.arange(len(y)) / FS % period) / period * nbins).astype(int)
    cnt = np.bincount(ph[valid], minlength=nbins)
    return np.bincount(ph[valid], weights=y[valid], minlength=nbins) / cnt


def beacon_folds(R, tu):
    """Fold CH2 on the beacon interval (100 TU in the router's time base) and on 12 nearby null periods."""
    y, v = R["_y_hp"], R["_valid"]
    R["fold_beacon"] = phase_fold(y, v, 100 * tu)
    nulls = [phase_fold(y, v, P * 1e-3) for P in np.r_[np.linspace(93, 100, 6), np.linspace(105, 112, 6)]]
    R["fold_beacon_null"] = np.array(nulls)
    R["beacon_stat"] = (R["fold_beacon"].std(), R["fold_beacon_null"].std(axis=1).mean())
    R["fold_gapper"] = phase_fold(y, v, 512 * tu, 128)
    R["fold_gapper_null"] = np.array([phase_fold(y, v, 512 * tu * k, 128) for k in (0.93, 0.95, 0.97, 1.03, 1.05, 1.07)])
    del R["_y_hp"], R["_valid"]


# ================================================================= figures
def fig_spectra(Rs):
    fig, ax = plt.subplots(2, 1, figsize=(10, 7.4), sharex=True)
    for R in Rs:
        f, p = R["f_ov"], R["p_ov"]
        ax[0].loglog(f[1:], np.sqrt(p[1:]) * 1e3, color=R["col"], lw=0.8, label=R["name"])
        ax[1].loglog(f[1:], np.sqrt(R["p_ov_mic"][1:]) * FSV / 32768 * 1e6, color=R["col"], lw=0.8)
    lsb = UV_PER_LSB * 1e3 / np.sqrt(12 * FS / 2)
    tot = np.sqrt(8 ** 2 + 1.4 ** 2 + lsb ** 2)
    ax[0].axhline(lsb, color="k", ls=":", lw=1)
    ax[0].axhline(8, color="k", ls="--", lw=0.8)
    ax[0].axhline(tot, color="k", ls="-", lw=0.8)
    ax[0].text(1.2, lsb * 1.08, f"int16-Quantisierung {de(lsb, 1)} nV/√Hz", fontsize=8, va="bottom")
    ax[0].text(1.2, 8 * 0.9, "LTC6373 (G = 16) 8 nV/√Hz", fontsize=8, va="top")
    ax[0].text(1.2, tot * 1.6, f"Summe Theorie {de(tot, 1)} nV/√Hz", fontsize=8, va="bottom")
    ax[0].axvspan(100, 1500, color=LGREY, alpha=0.35, lw=0)
    ax[0].text(390, 2.2e4, "ABR-Band 100–1500 Hz", ha="center", fontsize=8)
    ax[0].set_ylim(5, 5e4)
    ax[0].set_ylabel("CH2 an den Elektroden (nV/√Hz)")
    ax[0].set_title("Rauschdichte CH2 (Biosignal) – alle Läufe, Welch 0,68 s")
    ax[0].legend(loc="upper right", ncol=2)
    ax[1].set_ylabel("CH1 am Codec (µV/√Hz)")
    ax[1].axhline(FSV / 32768 * 1e6 / np.sqrt(12 * FS / 2), color="k", ls=":", lw=1)
    ax[1].text(1.2, FSV / 32768 * 1e6 / np.sqrt(12 * FS / 2) * 1.1, "int16-Quantisierung", fontsize=8, va="bottom")
    ax[1].set_title("Rauschdichte CH1 (Headset-Mikrofon)")
    ax[1].set_xlabel("Frequenz (Hz)")
    ax[1].set_xlim(1, 12000)
    fig.tight_layout()
    save(fig, "tech_01_spektren_uebersicht.png")


def fig_wifi_lines(Rs):
    targets = [(187.5, "Paketrate 187,5 Hz"), (375.0, "2 × Paketrate"), (562.5, "3 × Paketrate"),
               (937.5, "5 × Paketrate"), (1999.954, "2 kHz (1-kHz-Kamm)"), (2999.93, "3 kHz (1-kHz-Kamm)"),
               (7999.82, "8 kHz (1-kHz-Kamm)"), (6282.1, "Spur 6282 Hz")]
    fig, axs = plt.subplots(2, 4, figsize=(12, 6.2))
    rows = []
    for (ft, lab), ax in zip(targets, axs.ravel()):
        best = 0
        lims = []
        for R in Rs[1:]:
            f, p = R["f_hr"], R["p_hr"]
            m = np.abs(f - ft) < 2.5
            ax.plot(f[m] - ft, np.sqrt(p[m]) * 1e3, color=R["col"], lw=0.9, label=R["name"])
            navg = 2 * R["n"] / len(f) / 2
            a, lim = line_amp(f, p, ft, 0.25, navg)
            a = a if a > lim else 0.0
            best = max(best, a)
            lims.append(lim)
            rows.append((lab, R["key"], a, lim))
        ax.set_yscale("log")
        ttl = f"max. {de(best * 1e3, 0)} nVrms" if best > 0 else f"< {de(np.median(lims) * 1e3, 0)} nVrms (Nachweisgrenze)"
        ax.set_title(f"{lab}\n{ttl}", fontsize=9)
        ax.set_xlabel(f"Δf zu {de(ft, 1)} Hz (Hz)")
        ax.set_xlim(-2.5, 2.5)
    for ax in axs[:, 0]:
        ax.set_ylabel("nV/√Hz (Elektroden)")
    axs[0, 0].legend(loc="upper left", fontsize=7)
    fig.suptitle("Hochaufgelöste Spektren (Welch 5,5 s, 0,18 Hz) an Wi-Fi-/CPU-typischen Frequenzen")
    fig.tight_layout()
    save(fig, "tech_02_wifi_linien_zoom.png")
    return rows


def fig_packet_fold(Rs):
    fig, axs = plt.subplots(2, 2, figsize=(11, 7))
    stats = []
    for R in Rs[1:]:
        m, se, n = R["folds"][PKT]
        t = np.arange(PKT) / FS * 1e3
        axs[0, 0].plot(t, m * 1e3, color=R["col"], lw=1, label=f"{R['name']} (n = {n})")
        exp_rms = np.sqrt(np.mean(se ** 2))
        stats.append((R["key"], m.std(), exp_rms, np.ptp(m)))
        m2, se2, n2 = R["folds"][2 * PKT]
        axs[0, 1].plot(np.arange(2 * PKT) / FS * 1e3, m2 * 1e3, color=R["col"], lw=1)
        mb = R["fold_beacon"]
        axs[1, 0].plot((np.arange(64) + 0.5) / 64 * BEACON * 1e3, mb * 1e3, color=R["col"], lw=1)
        mm, sem, _ = R["fold_mic"]
        axs[1, 1].plot(t, mm, color=R["col"], lw=1)
    R3 = Rs[3]
    m, se, _ = R3["folds"][PKT]
    t = np.arange(PKT) / FS * 1e3
    axs[0, 0].fill_between(t, -2 * se * 1e3, 2 * se * 1e3, color=LGREY, alpha=0.6, lw=0, label="±2 SE Rauschen (Lauf 3)")
    axs[0, 0].set_title("CH2 gemittelt über die Paketperiode (128 Samples = 5,33 ms)")
    axs[0, 0].set_xlabel("Zeit ab Paketgrenze (ms)")
    axs[0, 0].set_ylabel("nV (HP 100 Hz + 50-Hz-Kamm)")
    axs[0, 0].legend(fontsize=7, loc="lower left")
    lim = 250
    axs[0, 0].set_ylim(-lim, lim)
    axs[0, 1].set_title("… über zwei Pakete (10,7 ms)")
    axs[0, 1].set_xlabel("Zeit ab Paketgrenze (ms)")
    axs[0, 1].set_ylim(-lim, lim)
    axs[0, 1].axvline(PKT / FS * 1e3, color=GREY, ls=":", lw=1)
    axs[1, 0].set_title("CH2 gemittelt über das Beacon-Intervall 100 TU (64 Bins à 1,6 ms)")
    axs[1, 0].set_xlabel("Phase im Beacon-Intervall (ms)")
    axs[1, 0].set_ylabel("nV")
    nb = 2 * max(R["fold_beacon_null"].std() for R in Rs[1:])
    axs[1, 0].axhspan(-nb * 1e3, nb * 1e3, color=LGREY, alpha=0.6, lw=0, label="±2σ Null (Nachbarperioden)")
    axs[1, 0].legend(fontsize=7, loc="lower left")
    axs[1, 0].set_ylim(-lim, lim)
    axs[1, 1].set_title("CH1 (Mikrofon) über die Paketperiode")
    axs[1, 1].set_xlabel("Zeit ab Paketgrenze (ms)")
    axs[1, 1].set_ylabel("Counts (1 Count = 86 µV am Codec)")
    txt = "\n".join(f"Lauf {k}: rms {de(s * 1e3, 0)} nV, Rauscherwartung {de(e * 1e3, 0)} nV"
                    for k, s, e, _ in stats)
    axs[0, 1].text(0.02, 0.03, txt, transform=axs[0, 1].transAxes, fontsize=7, va="bottom",
                   bbox=dict(fc="white", ec=LGREY))
    fig.tight_layout()
    save(fig, "tech_03_paket_und_beacon_mittelung.png")
    return stats


def fig_hf_bursts(Rs):
    fig = plt.figure(figsize=(12, 8))
    gs = fig.add_gridspec(2, 3, height_ratios=[1.15, 1])
    for j, R in enumerate((Rs[2], Rs[3])):
        ax = fig.add_subplot(gs[0, 0] if j == 0 else gs[0, 1:3])
        f, t, S = R["sg"]
        im = ax.pcolormesh(t, f / 1e3, 10 * np.log10(S), shading="auto", cmap="viridis",
                           vmin=-3, vmax=6, rasterized=True)
        ax.set_ylabel("Frequenz (kHz)")
        ax.set_xlabel("Zeit (s)")
        ax.set_title(f"Spektrogramm CH2, je Frequenz normiert – Lauf {R['key']}", fontsize=9)
        ax.grid(False)
        for tm, lab in R["marks"][1:]:
            ax.axvline(tm, color="w", ls="--", lw=1)
        if j:
            cb = fig.colorbar(im, ax=ax, pad=0.01)
            cb.set_label("dB relativ zum Median je Frequenz")
    ax = fig.add_subplot(gs[1, 0])
    for R in Rs[1:]:
        lag = np.arange(len(R["acf"])) * R["acf_dt"] * 1e3
        ax.plot(lag[4:], R["acf"][4:], color=R["col"], lw=0.8, label=R["name"])
    for k in range(1, 12):
        ax.axvline(k * BEACON * 1e3, color=GREY, lw=0.6, ls=":")
    ax.axvline(512 * TU * 1e3, color="k", lw=0.8, ls="--")
    ax.text(0.01, 0.03, "gepunktet: Beacon 102,4 ms, gestrichelt: 512 TU\nSpitzen alle 20 ms = Netzperiode (Lauf 1)", fontsize=7,
            transform=ax.transAxes)
    ax.set_xlabel("Verzögerung (ms)")
    ax.set_ylabel("Autokorrelation")
    ax.set_xlim(0, 600)
    ax.legend(fontsize=6.5, ncol=2, loc="upper center")
    ax.set_title("Autokorrelation HF-Leistung 2–10 kHz", fontsize=9)
    ax.set_ylim(-0.02, 0.075)
    ax = fig.add_subplot(gs[1, 1])
    for R in Rs[1:3]:
        ph = (np.arange(480) + 0.5) / 480 * 20
        ax.plot(ph, R["hf_mains"], color=R["col"], lw=0.8, label=f"Lauf {R['key']}")
    ax.set_xlabel("Phase der 50-Hz-Komponente von CH2 (ms)")
    ax.set_ylabel("HF-Leistung 2–10 kHz / Median")
    ax.set_title("HF-Leistung über die Netzperiode (begrenzt auf 30 × Median)\n(nur Läufe mit messbarem Brumm)", fontsize=9)
    ax.legend(fontsize=6.5, loc="upper right")
    ax = fig.add_subplot(gs[1, 2])
    for R in Rs[1:]:
        if R["gap_env"] is None:
            continue
        tt = (np.arange(len(R["gap_env"])) - len(R["gap_env"]) // 2) * R["acf_dt"] * 1e3
        ax.plot(tt, R["gap_env"], color=R["col"], lw=0.7)
    ax.axvline(0, color="k", lw=0.8)
    ax.axvspan(0, 10.6, color=LGREY, alpha=0.5, lw=0)
    ax.set_ylim(0.8, 1.6)
    ax.set_title("HF-Leistung um Paketlücken\n(grau: mittlere Lücke 10,6 ms, keine Daten)", fontsize=9)
    ax.set_xlabel("Zeit relativ zum Lückenbeginn (ms)")
    ax.set_ylabel("Leistung / Median")
    fig.tight_layout()
    save(fig, "tech_04_hf_spektrogramm_bursts.png")


def fig_beat(Rs):
    R = Rs[2]
    n_click = np.arange(300)
    phase = (R["D"] + n_click * L_CLICK) % PKT
    fig, axs = plt.subplots(1, 3, figsize=(12.5, 4.0))
    axs[0].plot(n_click, phase, ".", ms=2.5, color=C[0])
    axs[0].set_xlabel("Klick-Nr.")
    axs[0].set_ylabel("Lage der Paketgrenze im Sweep (Samples)")
    axs[0].set_title("Paketphase je Klick: 1137 mod 128 = 113\n→ alle 128 Phasen nach 128 Klicks", fontsize=9)
    rng = np.random.default_rng(1)
    burst = np.r_[np.hanning(12), np.zeros(PKT - 12)]
    burst = (burst - burst.mean()) / np.ptp(burst)
    meas = Rs[3]["folds"][PKT][0]
    templ = [("gemessen (Lauf 3)", meas - meas.mean(), C[2]), ("angenommen: 1 µVpp-Burst je Paket", burst, C[1])]
    Ns = np.unique(np.logspace(0, np.log10(8000), 60).astype(int))
    tau = np.arange(int(0.012 * FS))
    for lab, tp, col in templ:
        res_all, res_rej = [], []
        for N in Ns:
            ph = (R["D"] + np.arange(N)[:, None] * L_CLICK + tau[None, :]) % PKT
            res_all.append(np.sqrt(np.mean(tp[ph].mean(0) ** 2)))
            keep = rng.random(N) > 0.35
            keep[0] = True
            res_rej.append(np.sqrt(np.mean(tp[ph[keep]].mean(0) ** 2)))
        axs[1].loglog(Ns, np.maximum(res_all, 1e-5) * 1e3, color=col, lw=1.2, label=f"{lab}, alle Sweeps")
        axs[1].loglog(Ns, np.array(res_rej) * 1e3, color=col, lw=0.8, ls="--", label=f"{lab}, 35 % zufällig verworfen")
    axs[1].axhline(16.4, color=GREY, ls=":", lw=1)
    axs[1].text(8000, 16.4 * 1.15, "10 % von Welle V (164 nV)", fontsize=7, color=GREY, ha="right")
    axs[1].set_ylim(0.01, 1000)
    axs[1].set_xlabel("Anzahl gemittelter Sweeps")
    axs[1].set_ylabel("Restartefakt im Mittel (nVrms)")
    axs[1].set_title("Paket-Artefakt im Klick-Mittel\n(volle Zyklen à 128 Sweeps löschen exakt)", fontsize=9)
    axs[1].legend(fontsize=6.5, loc="lower left")
    h = 48000 / 2274
    ks = np.arange(1, 9)
    dist = np.array([abs(k * 187.5 / h - round(k * 187.5 / h)) * h for k in ks])
    axs[2].bar(ks, dist, color=C[0])
    for k, dd in zip(ks, dist):
        axs[2].text(k, dd + 0.15, de(dd, 2), ha="center", fontsize=7)
    axs[2].set_xticks(ks)
    axs[2].set_xticklabels([f"{de(k * 187.5, 1)}" for k in ks], rotation=45, fontsize=7)
    axs[2].set_xlabel("Paket-Harmonische (Hz)")
    axs[2].set_ylabel("Abstand zur nächsten Klick-Harmonischen (Hz)")
    axs[2].set_title("Schwebung gegen die Klickrate 21,108 Hz\n(nie 0 → keine Phasenkopplung)", fontsize=9)
    axs[2].set_ylim(0, 11.5)
    fig.tight_layout()
    save(fig, "tech_05_schwebung_paket_klick.png")


def fig_loss_timeline(Rs):
    fig, axs = plt.subplots(len(Rs), 1, figsize=(12, 9.5))
    for ax, R in zip(axs, Rs):
        te = np.arange(len(R["mic_env"])) * 0.1
        ax.fill_between(te, 0, np.where(R["speech"], 1, 0), color=C[3], alpha=0.35, lw=0, step="mid",
                        transform=ax.get_xaxis_transform(), label="Sprache/Systemton im Mikrofon")
        ax.vlines(R["gap_t"], 0, R["gap_len"], color=R["col"] if R["key"] != "0" else "k", lw=1)
        bins = np.arange(0, R["dur"] + 10, 10)
        h = np.histogram(R["gap_t"], bins, weights=R["gap_len"])[0] / (10 * FS / PKT) * 100
        ax2 = ax.twinx()
        ax2.step(bins[:-1], h, where="post", color=GREY, lw=1)
        ax2.set_ylabel("Verlust %/10 s", color=GREY, fontsize=8)
        ax2.set_ylim(0, max(4, h.max() * 1.2))
        ax2.grid(False)
        ax2.spines["right"].set_visible(True)
        for tm, lab in R["marks"][1:]:
            ax.axvline(tm, color="k", ls="--", lw=1)
        if len(R["events"]):
            ax.plot(R["events"], np.full(len(R["events"]), 0.97), "v", color="k", ms=5,
                    transform=ax.get_xaxis_transform())
        ax.set_ylabel("Pakete")
        ax.set_ylim(0, max(4, R["gap_len"].max() + 1))
        ax.set_xlim(0, R["dur"])
        ax.set_title(f"{R['name']}: {de(100 * R['loss'], 2)} % verloren, {len(R['gap_t'])} Lücken "
                     f"({de(len(R['gap_t']) / R['dur'] * 60, 0)}/min)", fontsize=9, loc="left")
    axs[0].plot([], [], "v", color="k", ms=5, label="HTTP-Zugriff (Umschalten/Akku-Abfrage)")
    axs[0].legend(fontsize=7, loc="upper left", ncol=2)
    axs[-1].set_xlabel("Zeit ab Aufnahmebeginn (s)")
    fig.suptitle("Paketverlust über der Zeit (Strichhöhe = verlorene Pakete je Lücke; gestrichelt = Blockwechsel)")
    fig.tight_layout()
    save(fig, "tech_06_paketverlust_zeitverlauf.png")


def loss_series(R, dtb=0.5):
    """Lost-packet fraction in bins of dtb seconds."""
    nb = int(np.ceil(R["dur"] / dtb))
    lost = np.zeros(nb)
    np.add.at(lost, (R["gap_t"] / dtb).astype(int).clip(0, nb - 1), R["gap_len"])
    return lost / (dtb * FS / PKT)


def fig_loss_stats(Rs):
    fig, axs = plt.subplots(2, 3, figsize=(13.5, 7.6))
    allg = np.concatenate([R["gap_len"] for R in Rs[1:]])
    for i, R in enumerate(Rs[1:]):
        h = np.bincount(R["gap_len"], minlength=13)[1:13]
        axs[0, 0].bar(np.arange(1, 13) + (i - 1.5) * 0.2, h / h.sum() * 100, 0.2, color=R["col"], label=R["name"])
    axs[0, 0].set_xlabel("Lückenlänge (Pakete à 5,33 ms)")
    axs[0, 0].set_ylabel("Anteil der Lücken (%)")
    axs[0, 0].set_title(f"Lückenlänge: Mittel {de(allg.mean(), 2)} Pakete = {de(allg.mean() * 5.333, 1)} ms", fontsize=9)
    axs[0, 0].legend(fontsize=6.5)
    P = np.median([R["gap_period"] for R in Rs[1:]])
    for i, R in enumerate(Rs[1:]):
        ig = np.diff(R["gap_t"]) / P
        axs[0, 1].hist(ig, bins=np.arange(0, 8.05, 0.05), color=R["col"], alpha=0.65, histtype="stepfilled")
    axs[0, 1].set_xlabel(f"Abstand aufeinanderfolgender Lücken / {de(P * 1e3, 2)} ms")
    axs[0, 1].set_ylabel("Anzahl")
    axs[0, 1].set_title("Lücken nur in ganzzahligen Vielfachen von 512 TU", fontsize=9)
    for i, R in enumerate(Rs[1:]):
        ph = (R["gap_t"] % P) * 1e3
        axs[0, 2].hist(ph, bins=np.arange(0, P * 1e3 + 5, 5), color=R["col"], alpha=0.65, histtype="stepfilled",
                       label=f"Lauf {R['key']}: {de(R['gap_period'] * 1e3, 2)} ms, R = {de(R['gap_R'], 2)}")
    axs[0, 2].set_xlabel(f"Lage der Lücke in der {de(P * 1e3, 1)}-ms-Periode (ms)")
    axs[0, 2].set_ylabel("Anzahl")
    axs[0, 2].set_title("Phase: eine feste Lage je Lauf (Ursprung beliebig)", fontsize=9)
    axs[0, 2].legend(fontsize=6.5, loc="upper left")
    labels = ["48 kHz\n(früher)", "24 kHz\n(früher)", "16 kHz\n(früher)"] + [f"Lauf {R['key']}" for R in Rs]
    vals = [11.0, 1.5, 0.0] + [100 * R["loss"] for R in Rs]
    cols = [LGREY, LGREY, LGREY] + [R["col"] for R in Rs]
    axs[1, 0].bar(range(len(vals)), vals, color=cols)
    axs[1, 0].errorbar([1], [1.5], yerr=[[0.5], [0.5]], color="k", capsize=3, lw=1)
    for i, v in enumerate(vals):
        axs[1, 0].text(i, v + (0.7 if i == 1 else 0.2), de(v, 2 if v < 10 else 0), ha="center", fontsize=7)
    axs[1, 0].set_xticks(range(len(vals)))
    axs[1, 0].set_xticklabels(labels, fontsize=7)
    axs[1, 0].set_ylabel("Paketverlust (%)")
    axs[1, 0].set_title("Verlustrate (Lauf 0 = erste 8 s nach Verbindungsaufbau)", fontsize=9)
    # event-locked loss around HTTP accesses (stimulus switch, battery query)
    dtb = 0.5
    rel = np.arange(-10, 10, dtb)
    acc, base = [], []
    for R in Rs[1:]:
        ls_ = loss_series(R, dtb)
        base.append(ls_)
        for e in R["events"]:
            i0 = int(e / dtb) + int(rel[0] / dtb)
            if i0 >= 0 and i0 + len(rel) <= len(ls_):
                acc.append(ls_[i0:i0 + len(rel)])
    acc = np.array(acc)
    bl = np.concatenate(base).mean() * 100
    axs[1, 1].bar(rel + dtb / 2, acc.mean(0) * 100, dtb * 0.9, color=C[0])
    axs[1, 1].axhline(bl, color=GREY, ls="--", lw=1, label=f"Mittel aller Läufe {de(bl, 2)} %")
    axs[1, 1].legend(fontsize=7, loc="upper left")
    axs[1, 1].set_ylim(0, 2.6)
    axs[1, 1].set_xlabel("Zeit relativ zum HTTP-Zugriff (s)")
    axs[1, 1].set_ylabel("Paketverlust (%)")
    axs[1, 1].set_title(f"Verlust um {len(acc)} HTTP-Zugriffe (Lauf 3/4)", fontsize=9)
    # speech / system sounds detected in the microphone
    sp_in, sp_out, names = [], [], []
    for R in Rs[1:]:
        sp = R["speech"]
        ls_ = loss_series(R, 0.1)[:len(sp)]
        sp = sp[:len(ls_)]
        sp_in.append(ls_[sp].mean() * 100 if sp.any() else np.nan)
        sp_out.append(ls_[~sp].mean() * 100)
        names.append(f"Lauf {R['key']}\n({de(sp.sum() * 0.1, 0)} s Ton)")
    x = np.arange(len(names))
    axs[1, 2].bar(x - 0.2, sp_out, 0.4, color=GREY, label="ohne Ton im Mikrofon")
    axs[1, 2].bar(x + 0.2, sp_in, 0.4, color=C[3], label="während Sprache/Systemton")
    axs[1, 2].set_xticks(x)
    axs[1, 2].set_xticklabels(names, fontsize=7)
    axs[1, 2].set_ylabel("Paketverlust (%)")
    axs[1, 2].set_title("Verlust während Ansagen (Mikrofon-Detektion)", fontsize=9)
    axs[1, 2].legend(fontsize=7)
    fig.tight_layout()
    save(fig, "tech_07_paketverlust_statistik.png")
    return acc, bl, sp_in, sp_out


def fig_mains(Rs, ch):
    fig, axs = plt.subplots(1, 2, figsize=(12, 4.6), gridspec_kw=dict(width_ratios=[1.6, 1]))
    k = np.arange(1, 31)
    for R in Rs:
        h = np.where(R["harm"] > R["harm_lim"], R["harm"], np.nan)
        axs[0].semilogy(k * 50, h, "o-", ms=3, lw=0.8, color=R["col"], label=R["name"])
    for (lab, hk), mk in zip(ch, ("s", "^", "v", "D")):
        axs[0].semilogy(np.arange(1, 10) * 50, np.where(hk > 0.05, hk, np.nan), mk + "--", ms=4, lw=0.8, color="k",
                        alpha=0.65, label=lab)
    axs[0].set_xlabel("Frequenz (Hz) – Harmonische von 50 Hz")
    axs[0].set_ylabel("Amplitude (µVrms an den Elektroden)")
    axs[0].set_title("Netzbrumm: Kopf (24 kHz) gegen Brust (1 kHz, Blockmittel korrigiert)", fontsize=9)
    axs[0].legend(fontsize=7, ncol=2)
    axs[0].set_ylim(0.02, 5000)
    axs[0].text(0.99, 0.02, "nur Linien über der 3σ-Nachweisgrenze", transform=axs[0].transAxes, ha="right",
                fontsize=7, color=GREY)
    for R in Rs:
        ok = R["f0_snr"] > 30
        tw = [dt.datetime.fromtimestamp(R["t0"] + t) for t, o in zip(R["f0_t"], ok) if o]
        axs[1].plot(tw, R["f0_v"][ok], ".", ms=3, color=R["col"])
        if ok.any():
            axs[1].plot([dt.datetime.fromtimestamp(R["t0"] + R["dur"] / 2)], [R["f0"]], "D", ms=6, mec="k",
                        color=R["col"])
        else:
            tm = dt.datetime.fromtimestamp(R["t0"] + R["dur"] / 2)
            axs[1].axvspan(dt.datetime.fromtimestamp(R["t0"]), dt.datetime.fromtimestamp(R["t0"] + R["dur"]),
                           color=R["col"], alpha=0.15, lw=0)
            axs[1].text(tm, 49.95 + 0.012 * (R["key"] == "4"), f"Lauf {R['key']}:\nBrumm unter\nNachweisgrenze",
                        fontsize=7, ha="center", color="k")
    axs[1].set_xlim(dt.datetime.fromtimestamp(Rs[0]["t0"] - 120), dt.datetime.fromtimestamp(Rs[-1]["t0"] + Rs[-1]["dur"] + 120))
    axs[1].set_ylabel("f₀ (Hz), 5-s-Fenster mit SNR > 15 dB; ◆ = Lauf")
    axs[1].set_xlabel("Uhrzeit 16./17.10.")
    axs[1].set_title("Netzfrequenz über die Läufe")
    axs[1].xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%H:%M"))
    axs[1].set_ylim(49.94, 50.06)
    fig.tight_layout()
    save(fig, "tech_08_netz_harmonische_f0.png")


def fig_comb(Rs):
    R = Rs[2]
    f = R["f16"]
    fig, axs = plt.subplots(1, 2, figsize=(12, 4.4), gridspec_kw=dict(width_ratios=[1.6, 1]))
    m = (f > 60) & (f < 1700)
    axs[0].semilogy(f[m], np.sqrt(R["p_abr_nocomb"][m]) * 1e3, color=GREY, lw=0.7, label="nur Bandpass 100–1500 Hz")
    axs[0].semilogy(f[m], np.sqrt(R["p_abr"][m]) * 1e3, color=C[0], lw=0.7, label="+ 50-Hz-Kamm (4 Hz breit)")
    axs[0].set_xlabel("Frequenz (Hz)")
    axs[0].set_ylabel("nV/√Hz")
    axs[0].set_title(f"Lauf 2, ABR-Filterkette (Welch 2,7 s); f₀ = {de(R['f0'], 3)} Hz")
    axs[0].legend(fontsize=7)
    k = np.arange(1, 31)
    w = 0.18
    nafter = 0
    for i, R in enumerate(Rs[1:]):
        hb = np.where(R["harm_before_bp"] > R["harm_lim"], R["harm_before_bp"], np.nan)
        axs[1].semilogy(k * 50 + (i - 1.5) * 6, hb * 1e3, "o", ms=3.5, color=R["col"], label=R["name"])
        det = R["harm_after"] > R["harm_after_lim"]
        nafter += det[1:].sum()
        axs[1].semilogy((k * 50 + (i - 1.5) * 6)[det], R["harm_after"][det] * 1e3, "x", ms=6, color="k")
        axs[1].semilogy(k * 50 + (i - 1.5) * 6, R["harm_lim"] * 1e3, "_", ms=4, color=R["col"], alpha=0.6)
    axs[1].text(0.02, 0.03, f"nach dem Kamm: {nafter} von 116 Linien (100–1500 Hz) über der Nachweisgrenze (×)\n"
                            "Striche = 3σ-Nachweisgrenze je Lauf", transform=axs[1].transAxes, fontsize=7)
    axs[1].set_ylim(3, 1e4)
    axs[1].set_xlim(80, 1550)
    axs[1].set_xlabel("Harmonische (Hz)")
    axs[1].set_ylabel("Linienamplitude (nVrms)")
    axs[1].set_title("Netzlinien im ABR-Band vor dem Kamm", fontsize=9)
    axs[1].legend(fontsize=6.5, loc="upper right")
    fig.tight_layout()
    save(fig, "tech_09_kammfilter_rest.png")


def fig_battery(Rs):
    fig, axs = plt.subplots(2, 3, figsize=(12, 6.8))
    labs = [("HF-Rauschboden 2–8 kHz (nV/√Hz)", 1), ("Boden 300–1500 Hz (nV/√Hz)", 2), ("50 Hz (µVrms)", 3),
            ("1-kHz-Kamm 2/3/6/7/8 kHz (nVrms)", 4), ("DC-Mittel CH2 (LSB)", 5), ("Paketverlust (%)", 6)]
    for ax, (lab, j) in zip(axs.ravel(), labs):
        for R in Rs:
            w = R["win"]
            v = vbat_at(w[:, 0])
            y = w[:, j] * (1e3 if j == 4 else 100 if j == 6 else 1)
            ax.plot(v, y, "o", ms=4, color=R["col"], label=R["name"])
        ax.set_xlabel("Akkuspannung (V, interpoliert)")
        ax.set_title(lab, fontsize=9)
        ax.invert_xaxis()
    axs[0, 0].legend(fontsize=6.5)
    fig.suptitle("Kenngrößen je 30-s-Fenster gegen die Akkuspannung (Zeit läuft nach rechts)")
    fig.tight_layout()
    save(fig, "tech_10_akku_trends.png")


def fig_spurs(Rs):
    cls = ["Netz-Harmonische", "Klick-Kamm (10,55 Hz)", "1-kHz-Kamm (999,977 Hz)", "Paketrate 187,5 Hz", "sonstige"]
    cols = [GREY, C[0], C[1], C[2], C[3]]
    fig, ax = plt.subplots(figsize=(12, 4.6))
    tab = {}
    for i, R in enumerate(Rs):
        for f, a in R["spurs"]:
            c = classify(f, R["f0"])
            ax.scatter(f, i, s=8 + 300 * min(a, 1.5), color=cols[c], alpha=0.75, lw=0)
            if c == 4:
                tab.setdefault(round(f, 0), []).append((R["key"], a))
    for c, lab in enumerate(cls):
        ax.scatter([], [], s=40, color=cols[c], label=lab)
    for s_, lab in ((0.1, "0,1 µV"), (1.0, "1 µV")):
        ax.scatter([], [], s=8 + 300 * s_, color="k", alpha=0.3, label=lab)
    ax.set_xscale("log")
    ax.set_yticks(range(len(Rs)))
    ax.set_yticklabels([R["name"] for R in Rs])
    ax.set_xlim(60, 12000)
    ax.set_ylim(-0.6, len(Rs) - 0.4)
    ax.set_xlabel("Frequenz (Hz)")
    ax.set_title("Schmalbandige Linien > 8 dB über dem lokalen Median (Welch 5,5 s; Lauf 0: > 11 dB, 1,4 s); Fläche ∝ Amplitude",
                 fontsize=9)
    ax.legend(fontsize=7, loc="upper left", bbox_to_anchor=(1.01, 1))
    fig.tight_layout()
    save(fig, "tech_11_spur_karte.png")
    return tab


def fig_quant(Rs):
    R = Rs[2]
    fig, axs = plt.subplots(2, 2, figsize=(11.5, 7.5))
    codes = np.arange(-200, 201)
    h = R["codes"]
    m = h > 0
    axs[0, 0].bar(codes[m], h[m] / h.sum() * 100, 1.0, color=C[0])
    mu = (codes * h).sum() / h.sum()
    sd = np.sqrt(((codes - mu) ** 2 * h).sum() / h.sum())
    xx = np.linspace(-25, 25, 400)
    axs[0, 0].plot(xx, 100 * np.exp(-0.5 * ((xx - mu) / sd) ** 2) / (sd * np.sqrt(2 * np.pi)), color=C[1], lw=1.2,
                   label=f"Normal: µ = {de(mu, 2)}, σ = {de(sd, 2)} LSB")
    axs[0, 0].set_xlim(-25, 25)
    axs[0, 0].set_xlabel("CH2-Rohcode (LSB, 1 LSB = 5,39 µV)")
    axs[0, 0].set_ylabel("Anteil (%)")
    axs[0, 0].set_title("Rohcodes, Lauf 2 ruhig (150–400 s)")
    axs[0, 0].legend(fontsize=7)
    # Largest systematic error of an average after floor-quantisation, Gaussian noise sigma (LSB):
    # first Fourier term of the quantiser error, (1/pi) exp(-2 pi^2 sigma^2) LSB.
    sig = np.linspace(0.05, 2.0, 400)
    bias = UV_PER_LSB * 1e3 / np.pi * np.exp(-2 * np.pi ** 2 * sig ** 2)
    axs[0, 1].semilogy(sig, bias, color=C[0], lw=1.4)
    axs[0, 1].axhline(164, color=GREY, ls=":", lw=1)
    axs[0, 1].text(1.05, 164 * 1.15, "Welle V 164 nV", fontsize=7, color=GREY)
    axs[0, 1].axhline(1, color=GREY, ls=":", lw=1)
    axs[0, 1].text(1.05, 1.15, "1 nV", fontsize=7, color=GREY)
    sh = np.mean([R_["hf_sd_lsb"] for R_ in Rs[1:]])
    axs[0, 1].axvline(sh, color=C[2], lw=1.2)
    axs[0, 1].text(sh + 0.03, 1e-3, f"σ nur > 2 kHz\n{de(sh, 2)} LSB", fontsize=7, color=C[2])
    axs[0, 1].axvline(Rs[2]["raw_sd"], color=C[1], lw=1.2)
    axs[0, 1].text(Rs[2]["raw_sd"] - 0.03, 1e-3, f"σ breitbandig\nLauf 2 ruhig\n{de(Rs[2]['raw_sd'], 2)} LSB", fontsize=7,
                   color=C[1], ha="right")
    axs[0, 1].set_ylim(1e-6, 3e3)
    axs[0, 1].set_xlabel("Rauschen σ vor der Quantisierung (LSB)")
    axs[0, 1].set_ylabel("max. systematischer Fehler im Mittel (nV)")
    axs[0, 1].set_title("Dithering: Quantisierungsfehler im Mittelwert", fontsize=9)
    f, p = R["f_ov"], R["p_ov"]
    mm = f > 50
    axs[1, 0].loglog(f[mm], np.sqrt(p[mm]) * 1e3, color=C[1], lw=0.7, label="gemessen Lauf 2")
    lsb = UV_PER_LSB * 1e3 / np.sqrt(12 * FS / 2)
    codec = 2 * 10 ** (-116 / 20) / np.sqrt(20000) * 1e9 / GAIN
    th = 0.13e-9 ** 0.5
    rel = np.sqrt(4 * 1.38e-23 * 305 * 10e3) * 1e9
    for val, lab, ls in ((8, "LTC6373 8 nV/√Hz", "--"), (lsb, f"int16 {de(lsb, 1)} nV/√Hz", ":"),
                         (codec, f"TAC5212 ADC ≈ {de(codec, 1)} nV/√Hz", "-."),
                         (rel, f"Elektroden 2×5 kΩ thermisch {de(rel, 1)} nV/√Hz", (0, (1, 3)))):
        axs[1, 0].axhline(val, color="k", ls=ls, lw=0.8, label=lab)
    tot = np.sqrt(8 ** 2 + lsb ** 2 + codec ** 2 + rel ** 2)
    axs[1, 0].axhline(tot, color=C[0], lw=1.2, label=f"Summe {de(tot, 1)} nV/√Hz")
    meas = np.sqrt(np.median(p[(f > 2000) & (f < 8000)])) * 1e3
    axs[1, 0].set_ylim(1, 3e3)
    axs[1, 0].set_xlabel("Frequenz (Hz)")
    axs[1, 0].set_ylabel("nV/√Hz (Elektroden)")
    axs[1, 0].set_title(f"Rauschboden: gemessen 2–8 kHz {de(meas, 1)} nV/√Hz")
    axs[1, 0].legend(fontsize=6.5, loc="upper right")
    x = np.arange(len(Rs))
    lo = [R_["raw_pct"][1] for R_ in Rs]
    hi = [R_["raw_pct"][3] for R_ in Rs]
    mn = [R_["raw_minmax"][0] for R_ in Rs]
    mx = [R_["raw_minmax"][1] for R_ in Rs]
    for i, R_ in enumerate(Rs):
        axs[1, 1].plot([i, i], [mn[i], mx[i]], color=R_["col"], lw=1)
        axs[1, 1].plot([i, i], [lo[i], hi[i]], color=R_["col"], lw=6, solid_capstyle="butt")
        axs[1, 1].text(i + 0.1, mx[i], f"{mx[i]}", fontsize=7, va="bottom")
    axs[1, 1].axhline(32767, color="k", lw=0.8)
    axs[1, 1].text(2, 32767 * 0.5, "Vollausschlag ±32768 (1,7 % genutzt)", fontsize=7, va="top", ha="center")
    axs[1, 1].axhline(-32768, color="k", lw=0.8)
    axs[1, 1].set_yscale("symlog", linthresh=10)
    axs[1, 1].set_xticks(x)
    axs[1, 1].set_xticklabels([f"Lauf {R_['key']}" for R_ in Rs])
    axs[1, 1].set_ylabel("CH2-Code (LSB, symlog)")
    axs[1, 1].set_title("Genutzter Codebereich: dick 0,5–99,5 %, dünn min/max")
    fig.tight_layout()
    save(fig, "tech_12_quantisierung_rauschboden.png")


def fig_dc(Rs):
    fig, ax = plt.subplots(figsize=(11, 3.8))
    for R in Rs:
        tw = [dt.datetime.fromtimestamp(t) for t in R["dc10"][:, 0]]
        ax.plot(tw, R["dc10"][:, 1], "o-", ms=2.5, lw=0.8, color=R["col"],
                label=f"{R['name']}: {de(R['dc'], 2)} LSB = {de(-R['dc'] * UV_PER_LSB, 1)} µV")
    ax.axhline(-0.5, color="k", ls=":", lw=1)
    ax.text(0.37, -0.6, "gepunktet: −0,5 LSB =\nAbschneidefehler von\n»mean >> 8« (Firmware)", fontsize=7, va="top",
            transform=ax.get_yaxis_transform())
    ax.set_ylabel("CH2-Mittel je 10 s (LSB)")
    ax.set_xlabel("Uhrzeit")
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%H:%M"))
    ax.set_title("DC-Offset von CH2 (Codec-Hochpass aus; Elektroden über C49/C52 AC-gekoppelt)")
    ax.legend(fontsize=7, loc="upper left", bbox_to_anchor=(1.01, 1))
    fig.tight_layout()
    save(fig, "tech_13_dc_offset.png")


def all_templates(Rs):
    out = []
    for R in Rs[1:]:
        for T in R["tmpl"]:
            name = T["label"]
            if R["key"] == "1":
                name = "1 Klick 0,10 im Ohr"
            elif R["key"] == "2":
                name = "2 Klick 0,05 im Ohr"
            elif R["key"] == "4":
                name = "4 Klick 0,035 Ohrhörer draußen"
            out.append((name, R, T))
    return out


def model_fit(T):
    """Fit rectangle-current and derivative (capacitive/inductive) models to the alternating artefact."""
    up = 10
    fsu = 48000 * up
    n = 4096
    rect = np.zeros(n)
    rect[n // 2:n // 2 + int(round(105e-6 * fsu))] = 1.0
    lp = ss.firwin(801, 21600, fs=fsu)
    r = np.convolve(rect, lp, "same")
    r = np.convolve(r, np.ones(2 * up) / (2 * up), "same")
    hp = ss.butter(4, 300, "hp", fs=fsu, output="sos")
    models = {"Strompuls (resistiv)": ss.sosfiltfilt(hp, r), "Ableitung (kapazitiv/induktiv)": ss.sosfiltfilt(hp, np.gradient(r))}
    y = T["hp300"][0]
    t = T["t"]
    win = (t > -1.5) & (t < 3)
    yy = y[win]
    res = {}
    for nm, mdl in models.items():
        best = (-1, None)
        for off in range(0, 2 * up * 24 * 4):
            idx = np.arange(win.sum()) * 2 * up + off
            if idx[-1] >= n:
                break
            x = mdl[idx]
            g = (x @ yy) / (x @ x)
            r2 = 1 - ((yy - g * x) ** 2).sum() / ((yy - yy.mean()) ** 2).sum()
            if r2 > best[0]:
                best = (r2, g * x)
        res[nm] = best
    return t[win], res


def fig_artefact_shape(Rs):
    tl = all_templates(Rs)
    fig, axs = plt.subplots(2, 3, figsize=(12.5, 7.2))
    cols = [C[0], C[1], C[2], GREY, C[3], "k"]
    abr_noise = []
    for i, (name, R, T) in enumerate(tl):
        col = cols[i]
        t = T["t"]
        m = (t > -2) & (t < 5)
        alt, com, se = T["hp100"]
        axs[0, 0].plot(t[m], alt[m], color=col, lw=1, label=name)
        alt3 = T["hp300"][0]
        axs[0, 1].plot(t[m], alt3[m], color=col, lw=1)
        axs[0, 2].plot(t[m], T["abr"][0][m] * 1e3, color=col, lw=1)
        abr_noise.append(T["abr"][0][(t > 8) | (t < -8)].std())
        axs[1, 0].plot(t[m], T["mic"][0][m], color=col, lw=1)
        axs[1, 1].plot(t[m], com[m], color=col, lw=1)
    axs[0, 0].set_title("CH2 alternierender Anteil (HP 100 Hz)")
    axs[0, 0].set_ylabel("µV")
    axs[0, 0].legend(fontsize=6.5, loc="lower right")
    axs[0, 1].set_title("CH2 alternierend (HP 300 Hz, wie bera_average)")
    nz = 2 * np.median(abr_noise) * 1e3
    axs[0, 2].axhspan(-nz, nz, color=LGREY, alpha=0.6, lw=0)
    axs[0, 2].text(4.9, -nz - 8, "±2σ Rauschen (Median)", fontsize=7, ha="right", va="top", color=GREY)
    axs[0, 2].set_title("CH2 alternierend in der ABR-Kette\n(100–1500 Hz + Kamm)", fontsize=9)
    axs[0, 2].set_ylabel("nV")
    axs[1, 0].set_title("CH1 Mikrofon alternierend")
    axs[1, 0].set_ylabel("Counts")
    axs[1, 1].set_title("CH2 nicht-alternierender Anteil (HP 100 Hz)")
    axs[1, 1].set_ylabel("µV")
    tw, res = model_fit(tl[0][2])
    axs[1, 2].plot(tw, tl[0][2]["hp300"][0][(tl[0][2]["t"] > -1.5) & (tl[0][2]["t"] < 3)], color=C[0], lw=1.5,
                   label="Lauf 1 gemessen (HP 300 Hz)")
    for (nm, (r2, fit)), col in zip(res.items(), (C[1], C[2])):
        axs[1, 2].plot(tw, fit, color=col, lw=1, ls="--", label=f"{nm}: R² = {de(r2, 2)}")
    axs[1, 2].set_title("Modellvergleich Lauf 1")
    axs[1, 2].legend(fontsize=6.5, loc="lower right")
    for ax in axs.ravel():
        ax.set_xlabel("Zeit ab Klick (ms)")
    fig.tight_layout()
    save(fig, "tech_14_reizartefakt_form.png")
    return res


def fig_artefact_lin(Rs):
    tl = all_templates(Rs)
    fig, axs = plt.subplots(1, 3, figsize=(12.5, 4.9))
    rows = []
    for name, R, T in tl:
        t = T["t"]
        w = (t > -0.5) & (t < 1.0)
        a300 = np.abs(T["hp300"][0][w]).max()
        a100 = np.abs(T["hp100"][0][w]).max()
        aab = np.abs(T["abr"][0][(t > -0.5) & (t < 3)]).max()
        noise = T["hp300"][0][(t > 8) | (t < -8)].std()
        amic = np.abs(T["mic"][0][w]).max()
        rows.append((name, T["amp"], a300, a100, aab, noise, amic, T["sweeps"], T["chunks"]))
    cols = {"1": C[0], "2": C[1], "3A": C[2], "3B": GREY, "3C": "k", "4": C[3]}

    def key(nm):
        return nm.split()[0]

    for nm, amp, a300, a100, aab, noise, amic, nsw, ch in rows:
        k = key(nm)
        if k == "3C":
            continue
        mk = "o" if k in ("1", "2", "3A") else ("s" if k == "4" else "x")
        axs[0].errorbar(amp, a300, yerr=2 * noise, fmt=mk, color=cols[k], ms=6, capsize=2, label=nm)
    pts = [(amp, a300) for nm, amp, a300, *_ in rows if key(nm) in ("1", "2", "3A")]
    A = np.array(pts)
    g = (A[:, 0] @ A[:, 1]) / (A[:, 0] @ A[:, 0])
    xx = np.linspace(0, 0.11, 10)
    axs[0].plot(xx, g * xx, color=GREY, ls="--", lw=1, label=f"proportional: {de(g, 0)} µV je Amplitude 1")
    pf = np.polyfit(np.log(A[:, 0]), np.log(A[:, 1]), 1)
    axs[0].set_title(f"Artefakt (HP 300 Hz, Spitze) gegen Klickamplitude\nlog-log-Steigung {de(pf[0], 2)} (linear = 1)")
    axs[0].set_xlabel("Klickamplitude (DAC-Vollaussteuerung)")
    axs[0].set_ylabel("µV an den Elektroden (±2σ Rauschen)")
    axs[0].legend(fontsize=6.5, loc="upper left")
    for nm, amp, a300, a100, aab, noise, amic, nsw, ch in rows:
        if len(ch):
            axs[1].plot(ch[:, 0], ch[:, 1], "o-", ms=3, lw=0.9, color=cols[key(nm)], label=nm)
    axs[1].set_xlabel("Zeit im Lauf/Block (s)")
    axs[1].set_ylabel("Artefaktspitze je 30 s (µV)")
    axs[1].set_title("Zeitliche Stabilität des Artefakts")
    axs[1].set_yscale("log")
    axs[1].legend(fontsize=6.5, loc="upper center", ncol=2, bbox_to_anchor=(0.5, -0.17))
    x = np.arange(len(rows))
    axs[2].bar(x - 0.2, [r[4] * 1e3 for r in rows], 0.4, color=C[0], label="CH2 in ABR-Kette (nV)")
    ax2 = axs[2].twinx()
    ax2.bar(x + 0.2, [r[6] for r in rows], 0.4, color=C[1], label="CH1 Mikrofon (Counts)")
    ax2.grid(False)
    ax2.spines["right"].set_visible(True)
    ax2.set_ylabel("CH1 Counts", color=C[1])
    axs[2].set_ylabel("CH2 Spitze in ABR-Kette (nV)", color=C[0])
    axs[2].set_xticks(x)
    axs[2].set_xticklabels([key(r[0]) for r in rows])
    axs[2].set_title("Artefakt nach der ABR-Filterkette und im Mikrofon")
    h1, l1 = axs[2].get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    axs[2].legend(h1 + h2, l1 + l2, fontsize=6.5, loc="upper right")
    fig.tight_layout()
    save(fig, "tech_15_reizartefakt_linearitaet.png")
    return rows, g, pf[0]


def fig_quality(Rs):
    cmap = ListedColormap([C[0], C[1], C[3], "#404040"])
    labels = ["sauber", "Amplitude > 25 µV (EMG/Bewegung)", "Block verworfen (SD > 1,5 × Median)", "Paketlücke"]
    fig = plt.figure(figsize=(12.5, 7.8))
    gs = fig.add_gridspec(2, 1, height_ratios=[1, 1.1])
    ax = fig.add_subplot(gs[0])
    tmax = max(R["dur"] for R in Rs)
    for i, R in enumerate(Rs):
        dtw = L_CLICK / FS
        ax.broken_barh([(t, dtw) for t in R["q_t"][R["q"] == 0]], (i - 0.4, 0.8), color=C[0], lw=0)
        for qv in (1, 2, 3):
            ax.broken_barh([(t, dtw) for t in R["q_t"][R["q"] == qv]], (i - 0.4, 0.8), color=cmap(qv), lw=0)
        fr = R["frac"]
        ax.text(tmax + 8, i, f"sauber {de(100 * fr[0], 0)} %\nEMG {de(100 * fr[1], 0)} %, Blk {de(100 * fr[2], 0)} %, "
                             f"Lücke {de(100 * fr[3], 0)} %", fontsize=7, va="center")
        for tm, lab in R["marks"][1:]:
            if lab != "end":
                ax.plot([tm, tm], [i - 0.45, i + 0.45], color="w", lw=2)
                ax.text(tm + 3, i + 0.42, lab.split()[0] if len(lab) < 3 else lab[:1], fontsize=7, va="top", color="w")
    ax.set_yticks(range(len(Rs)))
    ax.set_yticklabels([R["name"] for R in Rs], fontsize=8)
    ax.set_xlim(0, tmax + 150)
    ax.set_ylim(len(Rs) - 0.5, -0.5)
    ax.set_xlabel("Zeit ab Aufnahmebeginn (s)")
    ax.set_title("Qualitätskarte je Sweep (47,4 ms): ABR-Kette 100–1500 Hz + Kamm, Fenster −2…12 ms")
    ax.grid(False)
    for c, lab in enumerate(labels):
        ax.bar([0], [0], color=cmap(c), label=lab)
    ax.legend(fontsize=7, ncol=4, loc="upper center", bbox_to_anchor=(0.45, -0.18))
    ax = fig.add_subplot(gs[1])
    for R in Rs:
        ax.plot(R["blk_t"], R["blk_sd"], "o-", ms=2.5, lw=0.9, color=R["col"], label=R["name"])
    ax.axhline(2, color=GREY, ls=":", lw=1)
    ax.set_xlim(0, tmax + 150)
    ax.set_ylabel("Sweep-SD, Median je 64 Sweeps (µV)")
    ax.set_xlabel("Zeit ab Aufnahmebeginn (s)")
    ax.set_title("Rauschen je 64-Sweep-Block (3 s)")
    ax.legend(fontsize=7, loc="upper right")
    fig.tight_layout()
    save(fig, "tech_16_qualitaetskarte.png")


def main():
    global VB
    VB = battery_points()
    Rs = [analyse(r) for r in RUNS]
    tu = np.median([R["gap_period"] for R in Rs[1:]]) / 512
    print(f"TU in codec time: {tu * 1e6:.4f} us ({(tu / TU - 1) * 1e6:+.0f} ppm)")
    for R in Rs:
        beacon_folds(R, tu)
    ch = chest()
    fig_spectra(Rs)
    wl = fig_wifi_lines(Rs)
    pst = fig_packet_fold(Rs)
    fig_hf_bursts(Rs)
    fig_beat(Rs)
    fig_loss_timeline(Rs)
    acc, bl, sp_in, sp_out = fig_loss_stats(Rs)
    fig_mains(Rs, ch)
    fig_comb(Rs)
    fig_battery(Rs)
    tab = fig_spurs(Rs)
    fig_quant(Rs)
    fig_dc(Rs)
    mres = fig_artefact_shape(Rs)
    arows, g, slope = fig_artefact_lin(Rs)
    fig_quality(Rs)

    print("\n==== Summary numbers")
    for R in Rs:
        sp = R["speech"]
        gi = (R["gap_t"] / 0.1).astype(int).clip(0, len(sp) - 1)
        in_sp = R["gap_len"][sp[gi]].sum() / max(sp.sum() * 0.1 * FS / PKT, 1)
        out_sp = R["gap_len"][~sp[gi]].sum() / max((~sp).sum() * 0.1 * FS / PKT, 1)
        print(f"Run {R['key']}: dur {R['dur']:.0f}s loss {100 * R['loss']:.2f}% gaps {len(R['gap_t'])} "
              f"meanlen {R['gap_len'].mean():.2f} period {R.get('gap_period', np.nan) * 1e3:.3f}ms R {R.get('gap_R', np.nan):.2f} "
              f"| loss in speech {100 * in_sp:.2f}% ({sp.sum() * 0.1:.0f}s) outside {100 * out_sp:.2f}%")
        okf = R["f0_snr"] > 30
        print(f"   f0 {R['f0']:.4f} Hz (5s range {R['f0_v'][okf].min() if okf.any() else np.nan:.3f}-{R['f0_v'][okf].max() if okf.any() else np.nan:.3f}); 50Hz {R['harm'][0]:.2f} uV, "
              f"100 {R['harm'][1]:.2f}, 150 {R['harm'][2]:.2f}; sum 2..30 {np.sqrt((R['harm'][1:] ** 2).sum()):.2f} uV; "
              f"after comb max {R['harm_after'][1:30].max() * 1e3:.1f} nV")
        print(f"   HF floor {R['hf_floor_nv']:.1f} nV/rtHz, burst frac {R['burst_frac']:.4f}, DC {R['dc']:.3f} LSB, "
              f"raw sd {R['raw_sd']:.2f} LSB, hf sd {R['hf_sd_lsb']:.2f} LSB, minmax {R['raw_minmax']}, "
              f"pct {R['raw_pct'].round(1)}")
        print(f"   quality frac clean/emg/blk/gap {np.round(100 * R['frac'], 1)}, sweep sd clean {R['sweep_sd_clean']:.2f}, "
              f"D {R['D']}, vbat {vbat_at(R['t0']):.3f}-{vbat_at(R['t0'] + R['dur']):.3f}")
        print(f"   win rows (t, hf, mid, 50, 1k, dc, loss):\n", np.round(R["win"][:, 1:], 3)[:3])
    print("packet fold stats (key, rms, expected, pp):", [(k, round(s * 1e3, 1), round(e * 1e3, 1), round(p * 1e3, 1)) for k, s, e, p in pst])
    for R in Rs:
        m24, se24, _ = R["folds"][24]
        mb = R["folds"][12288]
        print(f"   run {R['key']} 1k-fold rms {m24.std() * 1e3:.1f} nV (exp {np.sqrt(np.mean(se24 ** 2)) * 1e3:.1f}); "
              f"12288 fold rms {mb[0].std() * 1e3:.1f} (exp {np.sqrt(np.mean(mb[1] ** 2)) * 1e3:.1f})")
    print("wifi line amps (nV, lim):", [(l, k, round(a * 1e3, 1), round(m * 1e3, 1)) for l, k, a, m in wl])
    print("event-locked loss (%), -10..10 s in 0.5 s:", np.round(acc.mean(0) * 100, 2), "baseline", round(bl, 2), "n", len(acc))
    print("loss speech in/out:", np.round(sp_in, 2), np.round(sp_out, 2))
    for R in Rs:
        print(f"  run {R['key']} beacon fold rms {R['beacon_stat'][0] * 1e3:.1f} nV, null {R['beacon_stat'][1] * 1e3:.1f}; "
              f"512TU fold rms {R['fold_gapper'].std() * 1e3:.1f}, null {R['fold_gapper_null'].std(axis=1).mean() * 1e3:.1f}; "
              f"f0 snr>30 windows {np.mean(R['f0_snr'] > 30):.2f}; 50Hz lim {R['harm_lim'][0]:.3f}; "
              f"after-comb detections {(R['harm_after'] > R['harm_after_lim'])[1:].sum()}")
        if R["key"] == "3":
            for lab, a_, b_ in (("A", 0, R["marks"][1][0]), ("B", R["marks"][1][0], R["marks"][2][0]),
                                ("C", R["marks"][2][0], R["dur"])):
                sel = (R["q_t"] >= a_) & (R["q_t"] < b_)
                print(f"     block {lab}: frac {np.round(100 * np.bincount(R['q'][sel], minlength=4) / sel.sum(), 1)}, "
                      f"sd clean {np.median(R['sweep_sd'][sel & (R['q'] == 0)]):.2f}")
    print("model fit:", {k: round(v[0], 3) for k, v in mres.items()})
    print("artefact rows (name, amp, hp300, hp100, abr nV, noise, mic, sweeps):")
    for r in arows:
        print("  ", r[0], r[1], round(r[2], 3), round(r[3], 3), round(r[4] * 1e3, 1), round(r[5], 3), round(r[6], 2), r[7])
    print(f"proportional gain {g:.1f} uV/unit, log-log slope {slope:.2f}")
    print("other spurs:", sorted((f, [(k, round(a, 3)) for k, a in v]) for f, v in tab.items()))
    for lab, hk in ch:
        print("chest", lab, np.round(hk, 2))
    print("battery points:", VB)


if __name__ == "__main__":
    main()
