# Wireless BERA firmware

ESP-IDF firmware for the Wireless BERA v1.0 board. It brings the analog front
end up, streams both ADC channels to a browser, drives the DAC stimulus output,
and can run either as its own access point or as a client on an existing
network — both at the same time.

---

## Quick start

```bash
source ~/esp/esp-idf/export.sh
cd firmware/wireless_bera
idf.py set-target esp32s3
idf.py build
```

Flash at 115200 baud. The ESP32-S3's native USB-CDC needs the slower rate for
the auto-reset handshake to line up with the macOS driver — at higher rates the
port disappears mid-sequence:

```bash
python3 -m esptool --chip esp32s3 -p /dev/cu.usbmodem101 -b 115200 \
  --before default_reset --after hard_reset write_flash \
  --flash_mode dio --flash_freq 80m --flash_size 16MB \
  0x0     build/bootloader/bootloader.bin \
  0x8000  build/partition_table/partition-table.bin \
  0x10000 build/wireless_bera.bin
```

No button presses are needed. To force the bootloader by hand: hold BOOT (SW3),
tap RESET (SW2), release BOOT.

---

## First contact

On power-up the board always raises its own access point:

| | |
|---|---|
| SSID | `WirelessBERA-XXXX` (last two MAC bytes) |
| Password | `bera1234` (change it in the Wi-Fi tab) |
| Web UI | <http://192.168.4.1> |

Join it and open the page. To put the board on an existing 2.4 GHz network, use
the **Wi-Fi** tab, or the serial console:

```
wifi "My Network" mypassword
```

Credentials live only in the device's NVS partition. Nothing is ever written
into the binary or into this repository.

Once it has joined a network the board is also reachable at
`http://wirelessbera.local`, and it brings **IPv6** up.

That matters on networks that put clients in separate IPv4 NAT pools — a phone
hotspot, for example — where the IPv4 address is not reachable from another
client at all. If the network advertises a prefix, the board picks up a global
address by SLAAC and you can open it straight from a browser:

```
http://[2a01:599:918:e549:a6cb:8fff:feca:5a28]/
```

`/api/status` reports the current one as `net.sta_ip6`, and the serial console
prints it under `IPv6`. If only a link-local address (`fe80::…`) is available,
browsers will not accept the zone id in a URL, so put one hop in front:

```bash
socat TCP-LISTEN:8080,fork,reuseaddr TCP6:[fe80::a6cb:8fff:feca:5a28%en0]:80
```

---

## Serial console

The USB-Serial/JTAG port carries both the log and a small command line, so a
board fresh from the bench can be configured and probed before it is on any
network. Type `help`:

```
status                     device, codec and audio summary
wifi <ssid> [password]     store station credentials and connect
wifi-forget                clear stored station credentials
ap <password>              change the access point password
scan                       list nearby networks
i2c                        scan the control bus
reg <page> <addr> [value]  read or write a codec register (hex)
gain <0-7>                 PGIA gain index
stream <on|off>            scope streaming over the websocket
stim <type> [amp] [freq]   signal generator
led <pattern> [percent]    status LED
reboot
```

Quote arguments that contain spaces: `wifi "My Phone Hotspot" mypassword`.

---

## What the firmware does

**Acquisition.** The ESP32-S3 is the I²S clock master at 8/16/24/32/48/96 kHz,
32-bit slots, so BCLK = 64 × fs. The TAC5212 has no MCLK line on this board and
locks its PLL to BCLK, which is why the I²S peripheral is started *before* the
codec is configured. Samples are 24-bit, left-aligned in the slot.

- ADC channel 1 ← MEMS microphone, AC-coupled, 10 kΩ input
- ADC channel 2 ← LTC6373 differential output, DC-coupled at a 2.20 V common
  mode, 40 kΩ input, rail-to-rail common-mode tolerance

**Scope stream.** The device block-averages by a configurable factor and pushes
binary WebSocket packets (32-byte header + interleaved `int16`). At the default
48 kHz ÷ 48 that is 1 kSa/s per channel, about 4 kB/s. Full-rate RMS, peak, DC
and clipping figures are computed on the device regardless of decimation, so the
meters stay honest even when the display is heavily decimated.

**Stimulus.** Sine, square, triangle, white noise, click train, Blackman-gated
tone burst, linear chirp and DC, with amplitude, frequency, repetition rate,
click width, burst length and rarefaction/condensation/alternating polarity.
Both outputs are single-ended on OUTxP (OUT1M/OUT2M are grounded on the board),
AC-coupled through 22 µF and 10 Ω into the 3.5 mm jack.

**Also:** LTC6373 gain select, TPS65132W rail trim, codec register browser for
any page, battery monitor, status LED patterns, I²C scan.

---

## Source layout

| File | Responsibility |
|---|---|
| `board.h` | every pin, bus address and electrical constant — the single source of truth |
| `main.c` | boot order |
| `i2c_bus.c` | shared I²C master, bus scan |
| `tac5212.c` | codec driver: register map, board-specific configuration, status |
| `audio.c` | full-duplex I²S, stimulus synthesis, decimation, meters |
| `pgia.c` | LTC6373 gain select |
| `tps65132.c` | ±5.4 V charge-pump rails |
| `battery.c` | V_BAT on ADC1_CH0 |
| `status_led.c` | LEDC patterns |
| `net.c` | AP + station, NVS credentials, mDNS, IPv6 |
| `web.c` | HTTP API and WebSocket |
| `console.c` | serial command line |
| `www/index.html` | the whole web UI; gzipped at build time and linked into the binary |

Editing `www/index.html` is enough — CMake re-compresses and re-embeds it.

---

## HTTP API

| Method | Path | |
|---|---|---|
| GET | `/` | web UI |
| GET | `/api/status` | everything the UI shows, as one JSON document |
| GET | `/api/i2c/scan` | addresses that ACK |
| GET | `/api/codec/regs?page=N` | 128 register values |
| POST | `/api/codec/reg` | `{page, reg, value}` |
| POST | `/api/codec` | volumes, front end, power, channel enables |
| POST | `/api/audio` | `{sample_rate, streaming, decimation}` |
| POST | `/api/stimulus` | signal generator |
| POST | `/api/pgia` | `{gain}` |
| POST | `/api/rails` | `{vpos, vneg}` |
| POST | `/api/led` | `{pattern, brightness}` |
| GET | `/api/wifi/scan` | nearby networks |
| POST | `/api/wifi/sta` | `{ssid, password}` |
| POST | `/api/wifi/ap` | `{password}` |
| POST | `/api/system/reboot` | |
| WS | `/ws` | binary scope packets + a 1 Hz status push |

Scope packet header, little endian, 32 bytes, followed by
`frames × channels` `int16` samples:

```c
uint32 magic = 'BERA'   uint16 version   uint16 channels
uint32 seq              uint32 sample_rate
uint16 decimation       uint16 frames
uint32 first_frame      uint32 stim_epoch   int32 stim_offset
```

`stim_epoch` counts stimulus repetitions and `stim_offset` marks where one
started inside the packet (`-1` if none) — the hooks a host needs for
stimulus-synchronous averaging.

---

## Things the hardware makes you care about

- **The codec is at I²C `0x50`**, not `0x4C`. The five MSBs of the address are
  fixed in silicon.
- **Schematic net names are from the codec's point of view.** `I2S_DOUT` is the
  codec's output and feeds ESP `din` (GPIO7); `I2S_DIN` is fed from ESP `dout`
  (GPIO6).
- **OUT1M/OUT2M are tied to ground through 0 Ω**, so both output channels must
  stay in "mono single-ended on OUTxP" mode. A differential or stereo-SE setting
  would drive a pin straight into the ground plane.
- **MICBIAS must stay at VREF (2.75 V).** It supplies the IM73A135, whose
  absolute maximum supply is 3.0 V, so the "bypass to AVDD" (3.3 V) setting must
  never be selected.
- **Do not program the TPS65132W below about 5.3 V.** Those raw rails feed the
  TPS7A39 LDOs that make ±5 V; below that they drop out.
- **The ESP32-S3 and the SD card run at 3.5 V**, not 3.3 V (TPS63000 feedback
  divider R20/R21). The I²C pull-ups go to 3.5 V while the codec's IOVDD is
  3.3 V — inside absolute maximum, but worth knowing.

### Current v1.0 assembly caveats

- **R35–R37 are not populated.** The gain select lines never reach the LTC6373;
  its internal pull-downs hold A2/A1/A0 low, so it runs permanently at **G = 16**.
  The firmware still drives the GPIOs and the web UI says so explicitly. Flip
  `BOARD_PGIA_RESISTORS_FITTED` in `board.h` once they are fitted.
- **MK1 (the MEMS microphone) is not populated**, so ADC channel 1 shows only
  the codec's input noise floor.
- With **no electrodes plugged into J6** the driven-right-leg loop is open and
  the 1 MΩ-biased differential input floats. Expect large, wandering readings on
  CH2 — measured here as 50 Hz mains pickup with 150/250 Hz harmonics at about
  141 µV referred to the input. That is the front end working, not failing.

### Open hardware question

The LTC6373 runs on ±5 V and its outputs are DC-coupled to the TAC5212 IN2 pins,
whose absolute maximum is **−0.3 V to +5.656 V**. Normal signals are safe: with
VOCM = 2.20 V, a full-scale ±2 Vrms differential keeps each leg between 0.8 V and
3.6 V. A *saturated* amplifier is not — it can pull a leg toward −5 V, well past
the −0.3 V limit, and the codec's ESD diodes then have to absorb it. Worth a
clamp or a series resistor on a future revision.

---

## Not implemented yet

microSD logging, NTP, stimulus-synchronous averaging on the device, and
single-shot full-rate capture. The pin map for the SD slot is already recorded
in `board.h` so nothing else claims those GPIOs, and the scope packet already
carries the epoch markers averaging would need.
