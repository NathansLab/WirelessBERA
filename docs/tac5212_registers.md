# TAC5212 Codec Register Documentation

The TAC5212 is a high-performance stereo audio codec from Texas Instruments. It is configured over I2C (or SPI) and transfers audio data over an Audio Serial Interface (ASI) such as I2S or TDM.

On the WirelessBERA PCB, the TAC5212 has its ADDR pin shorted to GNDD, resulting in a
7-bit **I2C address of `0x50`** (8-bit write address `0xA0`).

> The five most significant bits of the address are fixed at `0b10100` in silicon;
> only the two LSBs are set by the ADDR pin (datasheet Table 7-72):
> short to ground = `0x50`, 4.7 k to ground = `0x51`, 22 k to AVDD = `0x52`,
> 4.7 k to AVDD = `0x53`, short to AVDD = SPI mode.
> An earlier revision of this document claimed `0x4C`; that was wrong, and an
> I2C scan on the assembled board confirms `0x50`.

---

## 1. Key Interface Connections (ESP32-S3 to TAC5212)

* **I2C Control Interface**:
  * **SCL**: ESP32 GPIO5 -> TAC5212 SCL (Pin 7)
  * **SDA**: ESP32 GPIO4 -> TAC5212 SDA (Pin 8)
* **I2S Audio Interface**:
  * **BCLK** (Bit Clock): ESP32 GPIO16 -> TAC5212 BCLK (Pin 2)
  * **FSYNC** (Frame Sync / Word Select): ESP32 GPIO15 -> TAC5212 FSYNC (Pin 3)
  * **DOUT** (codec pin 4, ADC data *out of* the TAC5212): TAC5212 DOUT -> ESP32 **GPIO7**
  * **DIN** (codec pin 5, DAC data *into* the TAC5212): ESP32 **GPIO6** -> TAC5212 DIN

> The schematic net names `I2S_DOUT` / `I2S_DIN` are written from the **codec's**
> point of view, which is the opposite of the ESP-IDF naming. In
> `i2s_std_gpio_config_t` that means `.din = GPIO7` and `.dout = GPIO6`.
* **Power Supplies**:
  * **AVDD** (Analog Supply): `+3.3V_TAC_A` (Pin 23)
  * **IOVDD** (I/O Digital Supply): `+3.3V_TAC_D` (Pin 6)
  * **AREG / DREG**: Internal LDO decoupling points (Pins 24 and 1)

---

## 2. Page Selection Scheme

The TAC5212 registers are mapped using a page scheme. Each page contains 128 bytes (registers `0x00` to `0x7F`).
* **Register `0x00` (PAGE_CFG)** on *every* page is used to change the active page.
* To read/write registers on Page `N`, first write the value `N` to register `0x00`.
* All core configuration and status registers reside in **Page 0**, **Page 1**, and **Page 3**. Page 0 is the default.

---

## 3. Important Registers (Page 0)

Below is a detailed list of the critical registers required for device bring-up, clock validation, and audio path configuration.

### 3.1 Device Configuration & Reset
* **PAGE_CFG (Address: `0x00`, Reset: `0x00`)**: Device page configuration.
  * `PAGE[7:0]`: Write page number (e.g. `0` for Page 0, `1` for Page 1, etc.).
* **SW_RESET (Address: `0x01`, Reset: `0x00`)**: Software Reset.
  * Bit 0 (`SW_RESET`): Write `1` to reset all registers to default POR values. This bit is self-clearing.

### 3.2 System Status Registers
* **AVDD_IOVDD_STS (Address: `0x03`, Reset: `0x00`)**: Brownout and Supply status.
  * Bit 7 (`AVDD_MODE_STS`): AVDD voltage status (`0` = Configured, `1` = Forced to 3.3V operation).
  * Bit 6 (`IOVDD_IO_MODE_STS`): IOVDD voltage status (`0` = Configured, `1` = Forced to 3.3V operation).
  * Bit 1 (`BRWNOUT_SHDN_STS`): Brownout shutdown indicator.
* **DEV_STS0 (Address: `0x79`, Reset: `0x00`)**: Channel Power Status (Read-Only).
  * Bits 7-4 (`IN_CHx_STATUS`): Power status of ADC input channels 1 to 4 (`0` = Powered down, `1` = Powered up).
  * Bits 3-0 (`OUT_CHx_STATUS`): Power status of DAC output channels 1 to 4 (`0` = Powered down, `1` = Powered up).
* **DEV_STS1 (Address: `0x7A`, Reset: `0x80`)**: Device Status 1 (Read-Only).
  * Bits 7-5 (`MODE_STS[2:0]`): Device operation mode:
    * `4d` (`100b`): Sleep or software shutdown mode (Reset default).
    * `6d` (`110b`): Active mode, all channels off.
    * `7d` (`111b`): Active mode, at least one channel on.
  * Bit 4 (`PLL_STS`): PLL lock indicator (`0` = PLL unlocked/disabled, `1` = PLL locked).
  * Bit 3 (`MICBIAS_STS`): Microphone bias status (`0` = disabled, `1` = enabled).

### 3.3 Clock Configuration
* **CLK_CFG0 (Address: `0x32`, Reset: `0x00`)**: Primary ASI (PASI) Sample Rate.
  * Bits 7-2 (`PASI_SAMP_RATE[5:0]`): Sample rate selection (default: `0` = auto-detect).
* **CLK_CFG2 (Address: `0x34`, Reset: `0x40`)**: Clock source and PLL control.
  * Bit 7 (`PLL_DIS`): PLL enable (`0` = PLL enabled (default), `1` = PLL disabled).
  * Bit 6 (`AUTO_PLL_FR_ALLOW`): Allow fractional PLL modes (`0` = integer only, `1` = fractional allowed (default)).
  * Bits 3-1 (`CLK_SRC_SEL[2:0]`): Main clock source select:
    * `0d` (`000b`): **Primary ASI BCLK** (default).
    * `1d` (`001b`): CCLK synchronized with Primary ASI FSYNC.
    * `2d` (`010b`): Secondary ASI BCLK.
    * `5d` (`101b`): Internal oscillator clock (custom clock mode only).
* **CLK_ERR_STS0 (Address: `0x3C`, Reset: `0x00`)**: Clock Error Flags.
  * Bit 7 (`DSP_CLK_ERR`): Ratio error between FSYNC and selected clock.
  * Bit 4 (`SRC_RATIO_ERR`): Sample rate converter ratio unsupported.
  * Bit 1 (`RESET_ON_CLK_STOP_DET_STS`): Indicates if the clock stopped for >1ms.

### 3.4 Audio Serial Interface (ASI) Configuration
* **PASI_CFG0 (Address: `0x1A`, Reset: `0x30`)**: Primary ASI Format and Word Length.
  * Bits 7-6 (`PASI_FORMAT[1:0]`): Protocol format:
    * `0d` (`00b`): TDM format (Reset default).
    * `1d` (`01b`): **I2S format**.
    * `2d` (`10b`): Left-Justified (LJ) format.
  * Bits 5-4 (`PASI_WLEN[1:0]`): Word/slot length:
    * `0d` (`00b`): 16 bits.
    * `1d` (`01b`): 20 bits.
    * `2d` (`10b`): 24 bits.
    * `3d` (`11b`): **32 bits** (Reset default).
  * Bit 3 (`PASI_FSYNC_POL`): FSYNC polarity (`0` = Normal, `1` = Inverted).
  * Bit 2 (`PASI_BCLK_POL`): BCLK polarity (`0` = Normal, `1` = Inverted).

### 3.5 Power-Up & Channel Enables
* **CH_EN (Address: `0x76`, Reset: `0xCC`)**: Input and Output Channel Enables.
  * Bit 7 (`IN_CH1_EN`): Enable ADC input channel 1 (`0` = disabled, `1` = enabled (default)).
  * Bit 6 (`IN_CH2_EN`): Enable ADC input channel 2 (`0` = disabled, `1` = enabled (default)).
  * Bit 3 (`OUT_CH1_EN`): Enable DAC output channel 1 (`0` = disabled, `1` = enabled (default)).
  * Bit 2 (`OUT_CH2_EN`): Enable DAC output channel 2 (`0` = disabled, `1` = enabled (default)).
* **PWR_CFG (Address: `0x78`, Reset: `0x00`)**: Power-up control register.
  * Bit 7 (`ADC_PDZ`): Power down active ADCs (`0` = Power down all ADCs, `1` = Power up enabled ADCs).
  * Bit 6 (`DAC_PDZ`): Power down active DACs (`0` = Power down all DACs, `1` = Power up enabled DACs).
  * Bit 5 (`MICBIAS_PDZ`): Power control for MICBIAS (`0` = Power down, `1` = Power up).
