"""Record the Wireless BERA scope stream over the WebSocket.

Usage: rec.py <out.npz> <seconds> [decimation] [sample_rate]
Saves ch1/ch2 as volts at the codec input (ch2 additionally /gain = RTI),
plus the per-packet stimulus epoch markers.
"""
import json
import struct
import sys
import time
import urllib.request

import numpy as np
import websocket

HOST = "192.168.178.117"
GAIN = 16.0                     # LTC6373 fixed at 16 (R35-R37 not fitted)
FS_VPEAK = 2.0 * np.sqrt(2)     # codec full scale: 2 Vrms sine


def post(path, body):
    req = urllib.request.Request(f"http://{HOST}{path}", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=5).read()


out, seconds = sys.argv[1], float(sys.argv[2])
decim = int(sys.argv[3]) if len(sys.argv) > 3 else 48
fs_in = int(sys.argv[4]) if len(sys.argv) > 4 else 48000

ws = websocket.create_connection(f"ws://{HOST}/ws", timeout=5)
post("/api/audio", {"sample_rate": fs_in, "decimation": decim, "streaming": True})

chunks, epochs, seqs = [], [], []
fs = None
t0 = time.time()
try:
    while time.time() - t0 < seconds:
        op, data = ws.recv_data()
        if op != websocket.ABNF.OPCODE_BINARY or len(data) < 32:
            continue
        magic, ver, ch, seq, rate, dec, frames, first, epoch, offs = struct.unpack("<IHHIIHHIIi", data[:32])
        if magic != 0x41524542:
            continue
        fs = rate / dec
        x = np.frombuffer(data[32:32 + frames * ch * 2], dtype="<i2").reshape(frames, ch)
        chunks.append(x.copy())
        seqs.append(seq)
        epochs.append((len(chunks) - 1, epoch, offs))
finally:
    try:
        post("/api/audio", {"streaming": False})
    finally:
        ws.close()

x = np.concatenate(chunks).astype(np.float64) / 32768.0 * FS_VPEAK
gaps = int(np.sum(np.diff(seqs) != 1)) if len(seqs) > 1 else 0
np.savez(out, ch1=x[:, 0], ch2=x[:, 1], ch2_rti=x[:, 1] / GAIN, fs=fs,
         seqs=np.array(seqs), epochs=np.array(epochs), gain=GAIN)
print(f"{len(x)} frames @ {fs:.1f} Hz = {len(x) / fs:.1f} s, packets {len(seqs)}, seq gaps {gaps}")
