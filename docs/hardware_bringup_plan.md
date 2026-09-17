# Hardware bring-up

Status of the assembled Wireless BERA v1.0 prototype, and what is left to check.
Last updated 2026-09-17.

The board is fully populated — all ferrite beads `FB1`–`FB7` are fitted, so every
supply rail is live — with two deliberate exceptions listed under
[Not populated](#not-populated).

---

## What is verified

Measured on the assembled board over the firmware's HTTP API and serial console
(`firmware/wireless_bera/`), not inferred from the schematic.

### Power

| | |
|---|---|
| `+3.5V_ESP` | ESP32-S3 boots and runs; TPS63000 feedback divider R20/R21 sets 3.5 V |
| `+3.3V_TAC_A` | codec's own AVDD monitor reads **3.31 V** (page 1 diagnostic SAR) |
| `+5.5V` / `−5.5V` | TPS65132W register readback: **+5.4 V / −5.4 V** (factory default) |
| `V_BAT` sense | GPIO1 / ADC1_CH0, 10 k/10 k divider, reads plausibly |

The BQ24074's `~PGOOD` and `~CHG` outputs are **not** routed to the MCU, so the
firmware cannot report charger state. `~CHG` only drives the D1 LED.

### Digital

| | |
|---|---|
| I²C bus | `0x3E` TPS65132W, `0x50` TAC5212 — both ACK |
| I²S | ESP32-S3 as clock master, 32-bit slots, BCLK = 64 × fs |
| Codec PLL | locks off BCLK at **8, 16, 24, 32, 48 and 96 kHz**, no clock errors |
| Detected ratio | codec reports BCLK:FSYNC = 64 and the correct sample-rate code |
| SD card | **not yet tested** |
| USB | native USB-Serial/JTAG carries console and log; flashing works at 115200 |

### Analog signal chain

ADC channel 2 (the biopotential path) was confirmed end to end by spectrum
analysis of the live stream, with the electrode jack left open:

```
50.05 Hz   0.113 % FS      <- mains
150.15 Hz  0.024 % FS      <- 3rd harmonic
250.00 Hz  0.007 % FS      <- 5th harmonic
```

That is mains pickup on the open, 1 MΩ-biased differential input, amplified by
the LTC6373 and digitised cleanly — about **141 µV referred to the input**. It
proves electrode jack → LTC6373 → TAC5212 IN2 → I²S → Wi-Fi → browser.

ADC channel 1 shows a flat broadband floor at 0.002 % FS with no dominant line,
which is the codec's own input noise with the microphone unpopulated.

---

## Not populated

| Part | Consequence |
|---|---|
| `MK1` (IM73A135 MEMS microphone) | ADC channel 1 only shows the codec's input noise floor |
| `R35`, `R36`, `R37` (10 k, GPIO → LTC6373 A0/A1/A2) | the gain select lines never reach `U10`; its internal pull-downs hold A2/A1/A0 low, so it runs permanently at **G = 16** |

The firmware drives the gain GPIOs correctly regardless; `BOARD_PGIA_RESISTORS_FITTED`
in `firmware/wireless_bera/main/board.h` records the state and the web UI shows a
warning. Flip it to `1` once the resistors are fitted.

---

## Open items

### Verify next

1. **Gain scaling.** Fit `R35`–`R37`, then apply a known differential signal and
   confirm the amplitude tracks 0.25× … 16×.
2. **Noise floor.** Short `J8` pins 2 (IN+), 3 (IN−) and 4 (GNDA) together to give
   the front end a defined zero, then measure the input-referred noise. With the
   input open the driven-right-leg loop is not closed and the reading wanders.
3. **DAC output.** Plug headphones or insert earphones into `J11` and listen to a
   tone burst. The DAC channels report powered and the digital path is configured,
   but the analog output has not been measured. The codec's page-1 output monitors
   (`DIAG_MON_*_OUT1P` …) would allow an in-system check, but they need an enable
   sequence documented only in TI's diagnostics application note.
4. **DRL loop.** With electrodes attached, confirm the OPA376 output sits in its
   linear range and that common-mode rejection improves.
5. **microSD.** Mount and read/write. The pin map is already reserved in `board.h`.
6. **Access point with a real client.** The AP beacons and the device reports it as
   up, but no client association has been exercised.

### Hardware notes for a future revision

- **TAC5212 input protection.** The analog input pins are rated −0.3 V to
  +5.656 V. Normal signals are safe: with `VOCM` = 2.20 V, a full-scale ±2 Vrms
  differential keeps each leg between 0.8 V and 3.6 V. A *saturated* LTC6373 on
  ±5 V is not — it can pull a leg toward −5 V, well past the −0.3 V limit, leaving
  the codec's ESD diodes to absorb it. A series resistor plus a clamp to GNDA
  would close that gap.
- **I²C level mismatch.** The pull-ups R30/R31 go to `+3.5V_ESP` while the codec's
  IOVDD is 3.3 V. Inside absolute maximum, but not ideal.
- **`R38`, `R45`, `C49`, `C52` are still `TBD`** in the BOM — the input bias and
  coupling network around the electrode inputs is not finalised.

---

## Register and pin reference

See [`tac5212_registers.md`](tac5212_registers.md) for the codec register map and
the corrected I²C address, and `firmware/wireless_bera/main/board.h` for the
authoritative pin map — it is derived from the schematic netlist and is what the
firmware actually uses.
