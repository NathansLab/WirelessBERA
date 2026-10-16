"""Detailed analysis of BERA runs recorded with bera_record.py.

Usage: bera_analysis.py <out.png> <label>=<run.npz> [<label>=<run.npz> ...]

Per run: click phase from the alternating CH2 artefact (t = 0), band-pass +
50 Hz comb on the continuous record, epochs -2..12 ms, rejection in +/- pairs,
then
  - plain and block-weighted averages,
  - permutation test: random sign flips of whole +/- pairs (keeps the
    artefact cancelled, destroys any stimulus-locked response),
  - Fsp (single point at 5 ms),
  - separate rarefaction / condensation averages,
  - wave V: largest positive peak 4.5-8 ms, bootstrap CI of latency/amplitude,
  - filter variants and noise over time.
"""
import json
import sys

import numpy as np
import scipy.signal as ss
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

GAIN, FS_VPEAK = 16.0, 2.0 * np.sqrt(2)
PRE_MS, POST_MS, REJECT_UV = 2.0, 12.0, 25.0
rng = np.random.default_rng(1)


def load(path):
    d = np.load(path)
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
    if "click_phase" in d.files:                   # set by bera_split.py from a click block
        D = int(d["click_phase"])
    return dict(fs=fs, uv=uv, valid=valid, L=L, D=D, stim=stim, art=np.abs(f2[:L] - f2[L:]).max() / 2)


def filt(r, lo, hi):
    fs = r["fs"]
    y = ss.sosfiltfilt(ss.butter(2, [lo, hi], "bp", fs=fs, output="sos"), r["uv"])
    for k in range(1, int(hi // 50) + 2):
        fk = 50.0 * k
        if fk < fs / 2 - 10:
            y = ss.filtfilt(*ss.iirnotch(fk, fk / 4.0, fs), y)
    return y


def epochs(r, y):
    fs, L, D = r["fs"], r["L"], r["D"]
    pre, post = int(PRE_MS * fs / 1e3), int(POST_MS * fs / 1e3)
    on = D + np.arange(1, (len(y) - D - post) // L) * L
    guard = int(0.01 * fs)
    good = np.array([r["valid"][o - pre - guard:o + post + guard].all() for o in on])
    ep = np.stack([y[o - pre:o + post] for o in on])
    ok = good & (np.abs(ep[:, pre:]).max(axis=1) < REJECT_UV)
    m = len(ok) // 2 * 2
    pair_ok = ok[0:m:2] & ok[1:m:2]                 # keep whole +/- pairs only
    keep = np.repeat(pair_ok, 2)
    t = np.arange(-pre, post) / fs * 1e3
    E = ep[:m][keep]
    # Drop 64-sweep blocks whose sweep SD is > 1.5x the run median (restless
    # stretches, e.g. before the subject settled).
    nb = len(E) // 64
    sd = E[:nb * 64].reshape(nb, 64, -1).std(axis=(1, 2))
    blk_ok = np.repeat(sd < 1.5 * np.median(sd), 64)
    E = E[:nb * 64][blk_ok]
    return t, E, on[:m][keep][:nb * 64][blk_ok], len(on)


def stats(t, E, n_perm=1000):
    w = (t >= 1) & (t <= 10)
    avg = E.mean(axis=0)
    obs = np.std(avg[w])
    pairs = E.reshape(-1, 2, E.shape[1]).sum(axis=1)          # each pair sum (artefact cancelled)
    null = np.empty(n_perm)
    for i in range(n_perm):
        s = rng.choice([-1.0, 1.0], size=len(pairs))
        null[i] = np.std((s @ pairs)[w] / len(E))
    p = (1 + np.sum(null >= obs)) / (1 + n_perm)
    sp = np.argmin(np.abs(t - 5))
    fsp = np.var(avg[w]) / (np.var(E[:, sp]) / len(E))
    noise = np.std(((E[0::2] - E[1::2]) / 2).mean(axis=0)[w])      # ± reference
    return avg, obs, null, p, fsp, noise


def weighted(E, block=64):
    nb = len(E) // block
    B = E[:nb * block].reshape(nb, block, -1)
    var = B.var(axis=(1, 2))
    wts = 1 / var
    return (B.mean(axis=1) * wts[:, None]).sum(axis=0) / wts.sum(), np.sqrt(var)


def wave_v(t, E, n_boot=500):
    m = (t >= 4.5) & (t <= 8.0)
    def pk(a):
        i = np.argmax(a[m])
        return t[m][i], a[m][i]
    lat, amp = pk(E.mean(axis=0))
    bl = np.empty(n_boot)
    ba = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.integers(0, len(E) // 2, len(E) // 2) * 2
        idx = np.r_[idx, idx + 1]
        bl[i], ba[i] = pk(E[idx].mean(axis=0))
    return lat, amp, np.percentile(bl, [2.5, 97.5]), np.percentile(ba, [2.5, 97.5])


out = sys.argv[1]
runs = [a.split("=", 1) for a in sys.argv[2:]]
C = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
CR = C
res = []
for (label, path) in runs:
    r = load(path)
    y = filt(r, 100, 1500)
    t, E, on, n_all = epochs(r, y)
    avg, obs, null, p, fsp, noise = stats(t, E)
    wavg, blk_sd = weighted(E)
    lat, amp, lat_ci, amp_ci = wave_v(t, E)
    rare, cond = E[0::2].mean(axis=0), E[1::2].mean(axis=0)
    variants = {}
    for lo, hi in [(30, 1500), (100, 3000), (200, 1000)]:
        tv, Ev, _, _ = epochs(r, filt(r, lo, hi))
        variants[f"{lo}–{hi} Hz"] = (tv, Ev.mean(axis=0))
    P = E.reshape(-1, 2, E.shape[1])            # interleaved split: even vs odd pairs
    w = (t > 4) & (t < 9)
    r_ab = np.corrcoef(P[0::2].mean((0, 1))[w], P[1::2].mean((0, 1))[w])[0, 1]
    res.append(dict(label=label, r=r, t=t, E=E, avg=avg, obs=obs, null=null, p=p, fsp=fsp, noise=noise,
                    wavg=wavg, blk_sd=blk_sd, lat=lat, amp=amp, lat_ci=lat_ci, amp_ci=amp_ci,
                    rare=rare, cond=cond, variants=variants, n_all=n_all, r_ab=r_ab))
    print(f"[{label}] amp {r['stim']['amplitude']:.3f}, artefact {r['art']:.2f} µV, sweeps {len(E)}/{n_all} "
          f"({100 * len(E) / n_all:.0f} %), rms 1–10 ms {obs * 1e3:.0f} nV, null median "
          f"{np.median(null) * 1e3:.0f} nV / 95 % {np.percentile(null, 95) * 1e3:.0f} nV, p = {p:.3f}, "
          f"Fsp {fsp:.2f}, A/B r(4–9 ms) {r_ab:.2f}")
    print(f"        wave V candidate {lat:.2f} ms (95 % CI {lat_ci[0]:.2f}–{lat_ci[1]:.2f}), "
          f"{amp * 1e3:.0f} nV (CI {amp_ci[0] * 1e3:.0f}–{amp_ci[1] * 1e3:.0f}); "
          f"block sweep SD {blk_sd.min():.2f}–{blk_sd.max():.2f} µV")

nc = max(2, len(res))
fig = plt.figure(figsize=(6.5 * nc, 13))
gs = fig.add_gridspec(4, nc, hspace=0.55, wspace=0.22)
for i, R in enumerate(res):
    ax = fig.add_subplot(gs[0, i])
    ax.fill_between(R["t"], -2 * R["noise"], 2 * R["noise"], color="#cccccc", alpha=0.6, lw=0,
                    label="±2 σ Restrauschen")
    ax.plot(R["t"], R["avg"] * 1, color=C[0], lw=2, label="Mittel")
    ax.plot(R["t"], R["wavg"], color=C[1], lw=1.2, label="gewichtet (64er-Blöcke)")
    ax.axvline(0, color="k", lw=0.6)
    ax.axvspan(*R["lat_ci"], color=C[2], alpha=0.25, lw=0, label="Welle V Kandidat, 95 % KI")
    ax.set_title(f"{R['label']}: N = {len(R['E'])}, p = {R['p']:.3f} (Permutation), Fsp {R['fsp']:.1f}", loc="left", fontsize=10)
    ax.set_ylabel("µV")
    ax.set_xlabel("Zeit nach Klick (ms)")
    if i == 0:
        fig.legend(*ax.get_legend_handles_labels(), loc="upper center", ncol=4, frameon=False,
                   fontsize=9, bbox_to_anchor=(0.5, 0.965))
    ax.grid(alpha=0.3)

    ax = fig.add_subplot(gs[1, i])
    ax.plot(R["t"], R["rare"], color=C[0], lw=1.3, label="Polarität A")
    ax.plot(R["t"], R["cond"], color=C[1], lw=1.3, label="Polarität B")
    ax.axvline(0, color="k", lw=0.6)
    ax.set_ylim(-0.6, 0.6)
    ax.set_title(f"{R['label']}: Polaritäten getrennt (Artefakt bei 0 ms abgeschnitten)", loc="left", fontsize=10)
    ax.set_ylabel("µV")
    ax.set_xlabel("Zeit nach Klick (ms)")
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    ax.grid(alpha=0.3)

    ax = fig.add_subplot(gs[2, i])
    for j, (k, (tv, av)) in enumerate(R["variants"].items()):
        ax.plot(tv, av, color=C[j], lw=1.3, label=k)
    ax.axvline(0, color="k", lw=0.6)
    ax.set_title(f"{R['label']}: Filtervarianten", loc="left", fontsize=10)
    ax.set_ylabel("µV")
    ax.set_xlabel("Zeit nach Klick (ms)")
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    ax.grid(alpha=0.3)

ax = fig.add_subplot(gs[3, 0])
for i, R in enumerate(res):
    ax.hist(R["null"] * 1e3, bins=40, color=C[i], alpha=0.5, label=f"{R['label']} Null")
    ax.axvline(R["obs"] * 1e3, color=C[i], lw=2, label=f"{R['label']} gemessen")
ax.set_xlabel("RMS des Mittels 1–10 ms (nV)")
ax.set_ylabel("Anzahl")
ax.set_title("Permutationstest (Vorzeichen ganzer ±-Paare zufällig)", loc="left", fontsize=10)
ax.legend(frameon=False, fontsize=8)
ax = fig.add_subplot(gs[3, 1])
for i, R in enumerate(res):
    tb = np.arange(len(R["blk_sd"])) * 64 / 21.1
    ax.plot(tb, R["blk_sd"], color=C[i], lw=1.5, label=R["label"])
ax.set_xlabel("Messzeit der behaltenen Blöcke (s)")
ax.set_ylabel("Sweep-SD (µV)")
ax.set_title("Störpegel der behaltenen 64-Sweep-Blöcke", loc="left", fontsize=10)
ax.legend(frameon=False, fontsize=8)
ax.grid(alpha=0.3)
if len(res) > 1:
    Eall = np.concatenate([R["E"] for R in res])
    g_avg, g_obs, g_null, g_p, g_fsp, g_noise = stats(res[0]["t"], Eall)
    g_lat, g_amp, g_lci, g_aci = wave_v(res[0]["t"], Eall)
    print(f"[gesamt] sweeps {len(Eall)}, rms {g_obs * 1e3:.0f} nV, p = {g_p:.3f}, Fsp {g_fsp:.2f}, "
          f"wave V {g_lat:.2f} ms (CI {g_lci[0]:.2f}–{g_lci[1]:.2f}), {g_amp * 1e3:.0f} nV "
          f"(CI {g_aci[0] * 1e3:.0f}–{g_aci[1] * 1e3:.0f}), ± noise {g_noise * 1e3:.0f} nV")
fig.suptitle("Wireless BERA – Klick-BERA links, Stirn(+) / Mastoid links(−) / DRL Mastoid rechts, "
             "100–1500 Hz + 50-Hz-Kamm", x=0.06, ha="left", fontsize=12, y=0.985)
fig.savefig(out, dpi=120, bbox_inches="tight")
print(out)
