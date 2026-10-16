"""Split one continuous BERA recording into its stimulus blocks.

Usage: bera_split.py <run.npz> <run.log> <out_prefix> [guard_s]

The log holds "<unix time> <label>" lines written when each block's stimulus
was set (same click rate throughout, so the click grid never moves). Blocks are
cut on whole click periods, and the click phase found in the first block is
stored as `click_phase` so blocks without an audible/visible artefact (sham)
still use the right t = 0.
"""
import json
import sys

import numpy as np
import scipy.signal as ss

run, log, prefix = sys.argv[1], sys.argv[2], sys.argv[3]
guard = float(sys.argv[4]) if len(sys.argv) > 4 else 3.0
d = np.load(run)
fs, decim = float(d["fs"]), int(d["decim"])
stim = json.loads(str(d["stimulus"]))
L = int(48000 / stim["rate_hz"]) // decim
marks = [(float(l.split()[0]), " ".join(l.split()[1:])) for l in open(log) if l[:1].isdigit()]
t0 = float(d["t_start"])
n = len(d["ch2"])

uv = -d["ch2"].astype(float)
uv[~d["valid"]] = 0
first_end = int((marks[1][0] - t0) * fs) if len(marks) > 1 else n
hp = ss.sosfiltfilt(ss.butter(4, 300, "hp", fs=fs, output="sos"), uv[:first_end])
n2 = len(hp) // (2 * L)
f2 = hp[:n2 * 2 * L].reshape(n2, 2 * L).mean(axis=0)
D = int(np.argmax(np.abs(f2[:L] - f2[L:])))

for i, (tm, label) in enumerate(marks):
    if label == "end":
        continue
    a = int((tm - t0 + guard) * fs)
    b = int((marks[i + 1][0] - t0 - 0.5) * fs) if i + 1 < len(marks) else n
    a = (a // (2 * L)) * 2 * L                  # whole click pairs: keeps phase and polarity parity
    b = min(b, n)
    st = dict(stim)
    st["block"] = label
    out = f"{prefix}_{chr(ord('A') + i)}.npz"
    np.savez_compressed(out, ch1=d["ch1"][a:b], ch2=d["ch2"][a:b], valid=d["valid"][a:b], fs=fs,
                        decim=decim, stimulus=json.dumps(st), t_start=t0 + a / fs, click_phase=D)
    print(f"{out}: {label}, {(b - a) / fs:.0f} s, click phase {D}")
