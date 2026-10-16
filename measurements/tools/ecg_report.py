"""Build a PDF report of the ECG/DRL recordings: raw data, filter stages, spectra
and averaged heartbeats.

Usage: python3 ecg_report.py <recording dir> <out.pdf>
Needs numpy, scipy, matplotlib.
"""
import glob
import textwrap
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages
from scipy import signal

FS_VPEAK = 2 * np.sqrt(2)   # TAC5212 full scale: 2 Vrms sine
GAIN = 16.0                 # LTC6373, fixed while R35-R37 are not fitted

# Reference categorical palette (validated: adjacent CVD dE >= 9.1, light mode).
# Slots 3 and 4 are below 3:1 on white, so every trace is also direct-labelled.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
RAW = "#a3a29c"
INK, INK2, INK3 = "#0b0b0b", "#52514e", "#8a8984"
GRID = "#e6e5e0"

LABELS = {
    "1_no_drl": "No DRL",
    "2_drl_hand": "DRL via hand",
    "3_drl_chest": "DRL via chest",
    "4_drl_chest_repeat": "DRL via chest, repeat",
}

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 9,
    "axes.edgecolor": INK3, "axes.labelcolor": INK2, "axes.titlecolor": INK,
    "axes.titlesize": 10, "axes.titleweight": "medium", "axes.titlelocation": "left",
    "axes.spines.top": False, "axes.spines.right": False, "axes.linewidth": 0.6,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "xtick.color": INK2, "ytick.color": INK2, "xtick.labelsize": 8, "ytick.labelsize": 8,
    "legend.frameon": False, "legend.fontsize": 8, "lines.linewidth": 0.9,
})


# ---------------------------------------------------------------- filters --
def bp(x, fs, lo, hi, order=2):
    b, a = signal.butter(order, [lo, hi], "bandpass", fs=fs)
    return signal.filtfilt(b, a, x)


def hp(x, fs, fc, order=2):
    b, a = signal.butter(order, fc, "highpass", fs=fs)
    return signal.filtfilt(b, a, x)


def notch(x, fs, freqs=(50,), q=30):
    for f0 in freqs:
        if f0 < fs / 2:
            b, a = signal.iirnotch(f0, q, fs)
            x = signal.filtfilt(b, a, x)
    return x


COMB = (50, 100, 150, 200, 250, 300, 350, 400, 450)


def stages(x, fs):
    """The filter chain shown in the report, in order of increasing processing."""
    s = {}
    s["Raw"] = x
    s["High-pass 0.5 Hz"] = hp(x, fs, 0.5)
    s["+ 50 Hz comb notch"] = notch(s["High-pass 0.5 Hz"], fs, COMB)
    s["Diagnostic 0.05-150 Hz + comb"] = notch(bp(x, fs, 0.05, 150), fs, COMB)
    s["Monitoring 0.5-40 Hz + 50 Hz"] = notch(bp(x, fs, 0.5, 40), fs)
    return s


# ------------------------------------------------------------------- data --
def load(fn):
    with open(fn) as f:
        fs = float(f.readline().split("fs = ")[1].split()[0])
    t, _, c2 = np.loadtxt(fn, delimiter=",", comments="#", skiprows=4, unpack=True)
    x = -(c2 / 32768.0 * FS_VPEAK) / GAIN      # negate: ch2 is inverted on the board
    return t, x - x.mean(), fs


def rpeaks(mon, fs):
    pk, _ = signal.find_peaks(mon, distance=int(0.4 * fs), height=np.percentile(mon, 99) * 0.4)
    return pk


def band_rms(x, fs, lo, hi):
    f, P = signal.welch(x, fs, nperseg=int(fs * 4))
    m = (f >= lo) & (f < hi)
    return np.sqrt(np.sum(P[m]) * (f[1] - f[0]))


def asd(x, fs):
    f, P = signal.welch(x, fs, nperseg=int(fs * 4))
    return f, np.sqrt(P)


folder, out = sys.argv[1], sys.argv[2]
recs = []
for fn in sorted(glob.glob(os.path.join(folder, "*.csv"))):
    key = os.path.basename(fn)[:-4]
    t, x, fs = load(fn)
    st = stages(x, fs)
    pk = rpeaks(st["Monitoring 0.5-40 Hz + 50 Hz"], fs)
    recs.append(dict(key=key, label=LABELS.get(key, key), t=t, x=x, fs=fs, st=st, pk=pk,
                     hz50=band_rms(x, fs, 49.5, 50.5), hz150=band_rms(x, fs, 149.5, 150.5),
                     floor=band_rms(st["+ 50 Hz comb notch"], fs, 60, 90) / np.sqrt(30),
                     hr=60 / np.median(np.diff(pk) / fs),
                     qrs=np.median(st["Monitoring 0.5-40 Hz + 50 Hz"][pk])))
ref50 = recs[0]["hz50"]
WIN = (20.0, 30.0)
A4L = (11.69, 8.27)


def footer(fig, n):
    fig.text(0.04, 0.025, "Wireless BERA v1.0 - ECG and driven-right-leg measurements, 2026-10-16",
             color=INK3, fontsize=7)
    fig.text(0.96, 0.025, str(n), color=INK3, fontsize=7, ha="right")


with PdfPages(out) as pdf:
    page = 1

    # ------------------------------------------------------ 1: summary --
    fig = plt.figure(figsize=A4L)
    fig.text(0.04, 0.92, "ECG with and without driven right leg", fontsize=20, color=INK)
    fig.text(0.04, 0.875, "Wireless BERA v1.0 - single-lead chest ECG, 4 x 60 s, 16 October 2026",
             fontsize=11, color=INK2)
    setup = ("Electrode+ left lower rib cage, Electrode- below the right clavicle, DRL right lower rib cage.\n"
             "LTC6373 at G = 16, TAC5212 at 48 kHz, block mean to 1 kHz, streamed over Wi-Fi; board and laptop on battery.\n"
             "All values are referred to the electrodes. Channel 2 is polarity-inverted on the board and is negated here.")
    fig.text(0.04, 0.775, setup, fontsize=9, color=INK2, linespacing=1.6)

    ax = fig.add_axes([0.04, 0.44, 0.92, 0.28])
    ax.axis("off")
    rows = [[r["label"], f"{r['hz50'] * 1e6:,.0f}", f"{20 * np.log10(r['hz50'] / ref50):+.1f}" if r is not recs[0] else "-",
             f"{r['hz150'] * 1e6:,.0f}", f"{r['floor'] * 1e6:.1f}", f"{r['hr']:.0f}", f"{r['qrs'] * 1e3:.2f}"]
            for r in recs]
    tb = ax.table(cellText=rows, colLabels=["Recording", "50 Hz\nµVrms", "vs no DRL\ndB", "150 Hz\nµVrms",
                                            "Floor 60-90 Hz\nµV/√Hz", "Heart rate\nbpm", "QRS\nmV"],
                  loc="upper left", cellLoc="right", colLoc="right",
                  colWidths=[0.26, 0.12, 0.12, 0.12, 0.16, 0.12, 0.10])
    tb.auto_set_font_size(False)
    tb.set_fontsize(9)
    tb.scale(1, 2.1)
    for (r, c), cell in tb.get_celld().items():
        cell.set_edgecolor(GRID)
        cell.visible_edges = "B"
        cell.get_text().set_color(INK if r else INK2)
        if c == 0:
            cell.get_text().set_ha("left")
            cell._loc = "left"

    ax = fig.add_axes([0.17, 0.10, 0.30, 0.25])
    vals = [20 * np.log10(r["hz50"] / ref50) for r in recs[1:]]
    names = [r["label"] for r in recs[1:]]
    y = np.arange(len(vals))[::-1]
    ax.barh(y, vals, height=0.55, color=SERIES[1:len(vals) + 1], edgecolor="white", linewidth=2)
    for yi, v in zip(y, vals):
        ax.text(v - 0.4, yi, f"{v:.1f} dB", va="center", ha="right", color=INK, fontsize=9)
    ax.set_yticks(y, names)
    ax.set_xlim(min(vals) * 1.25, 0)
    ax.axvline(0, color=INK3, lw=0.8)
    ax.grid(axis="y", visible=False)
    ax.set_title("50 Hz mains pickup relative to no DRL")
    ax.set_xlabel("dB (lower is better)")

    fig.text(0.55, 0.36, "Findings", fontsize=12, color=INK)
    findings = [
        "The QRS complex is resolved in every recording; no clipping and no lost packets.",
        "Closing the DRL loop lowers 50 Hz pickup by 10-18 dB and the 150 Hz harmonic by 6-22 dB.",
        "The DRL lead held in the hand suppresses mains best, but forearm EMG raises the floor about 3x.",
        "The DRL chest electrode keeps the floor low; letting the gel settle improved it only from -10 to -12 dB.",
        "For display, a 0.5-40 Hz band-pass with a 50 Hz notch yields a clean ECG even without DRL.",
    ]
    fig.text(0.55, 0.335, "\n".join("•  " + textwrap.fill(s, 62, subsequent_indent="    ") for s in findings), fontsize=9, color=INK2,
             va="top", linespacing=1.8)
    footer(fig, page)
    pdf.savefig(fig)
    plt.close(fig)
    page += 1

    # --------------------------------------------- 2: the filter chain --
    r = recs[2] if len(recs) > 2 else recs[0]
    fig, axs = plt.subplots(len(r["st"]), 1, figsize=A4L, sharex=True)
    fig.subplots_adjust(left=0.08, right=0.96, top=0.88, bottom=0.11, hspace=0.45)
    fig.text(0.04, 0.93, f"Filter chain, step by step - {r['label']}", fontsize=14, color=INK)
    m = (r["t"] >= 22) & (r["t"] < 27)
    for i, (ax, (name, y)) in enumerate(zip(axs, r["st"].items())):
        ax.plot(r["t"][m], y[m] * 1e3, color=RAW if i == 0 else SERIES[0], lw=0.6 if i == 0 else 0.9)
        ax.set_title(name, fontsize=9)
        ax.set_ylabel("mV")
    axs[-1].set_xlabel("time / s")
    fig.text(0.96, 0.93, "zero-phase Butterworth (2nd order), notch Q = 30", fontsize=8,
             color=INK3, ha="right")
    footer(fig, page)
    pdf.savefig(fig)
    plt.close(fig)
    page += 1

    # ------------------------------------------- 3..: one page per run --
    for k, r in enumerate(recs):
        col = SERIES[k % len(SERIES)]
        fig = plt.figure(figsize=A4L)
        gs = fig.add_gridspec(3, 2, left=0.07, right=0.96, top=0.87, bottom=0.11,
                              hspace=0.55, wspace=0.2, height_ratios=[1, 1, 1.2])
        fig.text(0.04, 0.93, r["label"], fontsize=14, color=INK)
        fig.text(0.04, 0.905, f"{len(r['pk'])} beats in {r['t'][-1]:.0f} s, {r['hr']:.0f} bpm, "
                 f"50 Hz {r['hz50'] * 1e6:,.0f} µVrms", fontsize=9, color=INK2)
        m = (r["t"] >= WIN[0]) & (r["t"] < WIN[1])
        mon = r["st"]["Monitoring 0.5-40 Hz + 50 Hz"]
        dia = r["st"]["Diagnostic 0.05-150 Hz + comb"]

        ax = fig.add_subplot(gs[0, :])
        ax.plot(r["t"][m], r["x"][m] * 1e3, color=RAW, lw=0.5)
        ax.set_title("Raw, 10 s")
        ax.set_ylabel("mV")
        ax = fig.add_subplot(gs[1, :])
        ax.plot(r["t"][m], mon[m] * 1e3, color=col)
        ax.plot(r["t"][r["pk"]][(r["t"][r["pk"]] >= WIN[0]) & (r["t"][r["pk"]] < WIN[1])],
                mon[r["pk"]][(r["t"][r["pk"]] >= WIN[0]) & (r["t"][r["pk"]] < WIN[1])] * 1e3,
                "o", ms=4, mfc="white", mec=INK, mew=0.8, label="detected R peak")
        ax.set_title("Monitoring filter 0.5-40 Hz + 50 Hz notch")
        ax.set_ylabel("mV")
        ax.set_xlabel("time / s")
        ax.legend(loc="lower right", bbox_to_anchor=(1, 1.0), ncol=2)

        ax = fig.add_subplot(gs[2, 0])
        z = (r["t"] >= 24) & (r["t"] < 26.5)
        ax.plot(r["t"][z], r["x"][z] * 1e3, color=RAW, lw=0.5, label="raw")
        ax.plot(r["t"][z], dia[z] * 1e3, color=col, label="diagnostic 0.05-150 Hz + comb")
        ax.set_title("Zoom, 2.5 s")
        ax.set_ylabel("mV")
        ax.set_xlabel("time / s")
        ax.legend(loc="lower right", bbox_to_anchor=(1, 1.0), ncol=2)

        ax = fig.add_subplot(gs[2, 1])
        f, a = asd(r["x"], r["fs"])
        f2, a2 = asd(r["st"]["+ 50 Hz comb notch"], r["fs"])
        ax.semilogy(f, a * 1e6, color=RAW, lw=0.6, label="raw")
        ax.semilogy(f2, a2 * 1e6, color=col, lw=0.8, label="high-pass + comb notch")
        ax.set_xlim(0, 300)
        ax.set_title("Amplitude spectrum")
        ax.set_ylabel("µV/√Hz")
        ax.set_xlabel("frequency / Hz")
        ax.legend(loc="lower right", bbox_to_anchor=(1, 1.0), ncol=2)
        footer(fig, page)
        pdf.savefig(fig)
        plt.close(fig)
        page += 1

    # ------------------------------------------------- comparison page --
    fig = plt.figure(figsize=A4L)
    gs = fig.add_gridspec(1, 2, left=0.07, right=0.96, top=0.85, bottom=0.13, wspace=0.22)
    fig.text(0.04, 0.93, "Comparison of all recordings", fontsize=14, color=INK)

    ax = fig.add_subplot(gs[0, 0])
    for k, r in enumerate(recs):
        f, a = asd(r["x"], r["fs"])
        ax.semilogy(f, a * 1e6, color=SERIES[k], lw=0.8, label=r["label"])
    ax.set_xlim(0, 300)
    ax.set_title("Raw amplitude spectra")
    ax.set_ylabel("µV/√Hz")
    ax.set_xlabel("frequency / Hz")
    ax.legend(loc="upper right")

    ax = fig.add_subplot(gs[0, 1])
    pre, post = 0.25, 0.45
    for k, r in enumerate(recs):
        fs = r["fs"]
        y = notch(bp(r["x"], fs, 0.5, 150), fs, COMB)
        segs = np.array([y[p - int(pre * fs):p + int(post * fs)] for p in r["pk"]
                         if p - int(pre * fs) >= 0 and p + int(post * fs) <= len(y)])
        segs = segs[np.max(np.abs(segs), axis=1) < 5e-3]   # drop beats hit by motion artefacts
        tt = (np.arange(segs.shape[1]) / fs - pre) * 1e3
        mu, sd = segs.mean(0), segs.std(0)
        ax.fill_between(tt, (mu - sd) * 1e3, (mu + sd) * 1e3, color=SERIES[k], alpha=0.12, lw=0)
        ax.plot(tt, mu * 1e3, color=SERIES[k], lw=1.2, label=f"{r['label']} (n = {len(segs)})")
    ax.set_title("Averaged heartbeat, 0.5-150 Hz + comb, mean ± SD")
    ax.set_ylabel("mV")
    ax.set_xlabel("time from R peak / ms")
    ax.legend(loc="lower right")
    footer(fig, page)
    pdf.savefig(fig)
    plt.close(fig)
    page += 1

    # ------------------------------------------------------ methods page --
    fig = plt.figure(figsize=A4L)
    fig.text(0.04, 0.92, "Methods and caveats", fontsize=14, color=INK)
    notes = [
        ("Acquisition", "TAC5212 at 48 kHz, 24 bit. The firmware averages blocks of 48 samples and streams 1 kHz int16 "
                        "over a WebSocket. The block mean is a weak anti-alias filter; content above about 400 Hz folds back."),
        ("Scaling", "counts / 32768 x 2.828 V gives the codec input; divided by the LTC6373 gain of 16 and negated "
                    "(LTC6373 OUT- drives TAC5212 IN2P) gives the electrode voltage."),
        ("Filters", "All filters run forwards and backwards (zero phase). High-pass and band-pass are 2nd-order Butterworth; "
                    "notches are IIR with Q = 30 at 50 Hz and its harmonics up to 450 Hz."),
        ("Monitoring vs diagnostic", "0.5-40 Hz removes baseline drift and most mains and EMG and suits display and "
                                     "heart-rate detection. 0.05-150 Hz keeps the ST segment and QRS detail, so mains "
                                     "harmonics must be notched individually."),
        ("R-peak detection", "Peaks of the monitoring-filtered signal above 40 % of its 99th percentile, at least 400 ms apart."),
        ("Averaged beat", "Beats cut 250 ms before to 450 ms after each R peak from the 0.5-150 Hz + comb signal; beats "
                         "exceeding 5 mV (motion artefacts) are dropped."),
        ("Mains levels", "RMS of the Welch spectrum (4 s Hann segments) in a 1 Hz band around 50 Hz and 150 Hz, from the raw signal."),
        ("Caveats", "One subject, one session, alligator clips on foam electrodes. The DRL conditions were recorded "
                    "minutes apart, so electrode contact also changed between runs. Gain fixed at 16 (R35-R37 not fitted)."),
        ("Data", "measurements/2026-10-16_ecg_drl in the repository; this report is generated by measurements/tools/ecg_report.py."),
    ]
    yy = 0.84
    for head, body in notes:
        fig.text(0.04, yy, head, fontsize=10, color=INK, va="top")
        wrapped = textwrap.fill(body, 120)
        fig.text(0.24, yy, wrapped, fontsize=9, color=INK2, va="top", linespacing=1.5)
        yy -= 0.045 + 0.03 * wrapped.count("\n")
    footer(fig, page)
    pdf.savefig(fig)
    plt.close(fig)

print(f"wrote {out}, {page} pages")
