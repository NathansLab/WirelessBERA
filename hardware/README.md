# Hardware

KiCad 10 project for the Wireless BERA v1.0 board.

## Layout

| | |
|---|---|
| `WirelessBERA.kicad_pro` | open this — the root project |
| `WirelessBERA.kicad_sch` | root sheet; the design is split into three sub-sheets |
| `MCU.kicad_sch` | ESP32-S3-WROOM-1, USB-C, microSD, buttons, status LED |
| `Analog.kicad_sch` | LTC6373 PGIA, TAC5212 codec, OPA376 DRL, MEMS microphone, jacks |
| `Power.kicad_sch` | BQ24074 charger, TPS63000, TPS65132W, TPS7A39/7A94/7A2033 |
| `WirelessBERA.kicad_pcb` | 4-layer layout, split GNDA/GNDD |
| `WirelessBERA.kicad_dru` | Aisler 4-layer design rules |
| `library/` | project symbols, footprints and 3D models |
| `daughterboard/` | separate LTC6373 evaluation board, fixed gain 16 |
| `simulation/` | LTspice work behind the analog design |
| `manufacturing/` | what v1.0 was actually built from |
| `datasheets/` | vendor PDFs — present on disk, deliberately not in git |

## Key reference designators

| | |
|---|---|
| `U7` | ESP32-S3-WROOM-1-N16R8 |
| `U10` | LTC6373 programmable-gain instrumentation amplifier |
| `U11` | TAC5212 codec, I²C address `0x50` |
| `U9` | OPA376 driven-right-leg driver |
| `U5` | TPS65132W dual charge pump, I²C address `0x3E` |
| `MK1` | IM73A135 MEMS microphone |
| `J6` | electrode jack (3.5 mm TRS): tip = DRL, ring = Electrode+, sleeve = Electrode− |
| `J11` | stimulus jack (3.5 mm TRS): tip = OUT2P, ring = OUT1P, sleeve = GNDA |
| `J4` | microSD slot · `J5` USB-C · `J1` battery (JST PH) |
| `J7`–`J10`, `J12`, `J13`, `TP1`–`TP22` | test headers and points |

The authoritative pin map as used by the firmware lives in
[`../firmware/wireless_bera/main/board.h`](../firmware/wireless_bera/main/board.h).

## Assembly state

The populated v1.0 board and what is deliberately left off it are documented in
[`../docs/hardware_bringup_plan.md`](../docs/hardware_bringup_plan.md).
