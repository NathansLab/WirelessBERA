"""Record a raw BERA run from the Wireless BERA scope stream.

Usage: bera_record.py <out.npz> <seconds> [decimation]

Streams 48 kHz / decimation (default 2 -> 24 kHz) and stores both channels as
int16 counts on a continuous frame grid built from each packet's first_frame,
so dropped packets leave gaps (valid=False) instead of shifting the time base.
The stimulus must be configured before the run and left alone during it - the
click grid (one click every floor(48000/rate) frames) is only fixed while the
stimulus settings stay unchanged.
"""
import json
import struct
import sys
import time
import urllib.request

import numpy as np
import websocket

HOST = "192.168.178.117"


def http(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://{HOST}{path}", data=data,
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=5).read() or b"{}")


out, seconds = sys.argv[1], float(sys.argv[2])
decim = int(sys.argv[3]) if len(sys.argv) > 3 else 2

status = http("/api/status")
ws = websocket.create_connection(f"ws://{HOST}/ws", timeout=5)
http("/api/audio", {"sample_rate": 48000, "decimation": decim, "streaming": True})

packets = []
t0 = time.time()
try:
    while time.time() - t0 < seconds:
        op, data = ws.recv_data()
        if op != websocket.ABNF.OPCODE_BINARY or len(data) < 32:
            continue
        magic, ver, ch, seq, rate, dec, frames, first, epoch, offs = struct.unpack("<IHHIIHHIIi", data[:32])
        if magic != 0x41524542 or dec != decim:
            continue
        x = np.frombuffer(data[32:32 + frames * ch * 2], dtype="<i2").reshape(frames, ch).copy()
        packets.append((seq, first, epoch, offs, x))
finally:
    try:
        http("/api/audio", {"streaming": False})
    finally:
        ws.close()

# Place every packet on one grid. first_frame is the raw 48 kHz frame index at
# which the packet's first decimated block completed.
f0 = packets[0][1]
n = (packets[-1][1] - f0) // decim + len(packets[-1][4])
grid = np.zeros((n, 2), dtype=np.int16)
valid = np.zeros(n, dtype=bool)
for seq, first, epoch, offs, x in packets:
    i = (first - f0) // decim
    grid[i:i + len(x)] = x[:n - i]
    valid[i:i + len(x)] = True
seqs = np.array([p[0] for p in packets])
lost = int(np.sum(np.diff(seqs) - 1))
np.savez_compressed(out, ch1=grid[:, 0], ch2=grid[:, 1], valid=valid,
                    fs=48000.0 / decim, decim=decim, first_frame0=f0,
                    epochs=np.array([(p[1], p[2], p[3]) for p in packets]),
                    stimulus=json.dumps(status.get("stimulus", {})),
                    t_start=t0)
print(f"{n} frames @ {48000 / decim:.0f} Hz = {n * decim / 48000:.1f} s, "
      f"packets {len(packets)}, lost {lost} ({100 * lost / max(1, len(packets) + lost):.2f} %), "
      f"valid {100 * valid.mean():.2f} %")
