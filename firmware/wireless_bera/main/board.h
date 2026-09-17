/*
 * board.h - Wireless BERA v1.0 hardware description.
 *
 * Single source of truth for every pin, bus address and electrical constant.
 * Everything here was derived from hardware/WirelessBERA.kicad_sch (netlist
 * extracted 2026-09-17) and the part datasheets in hardware/datasheets/.
 * If the schematic changes, change this file - nothing else should hard-code
 * a GPIO number.
 *
 * Board overview
 * --------------
 *   Electrode jack J6 (TRS)  ->  LTC6373 PGIA (U10, G = 0.25..16)
 *                            ->  TAC5212 IN2P/IN2M   (ADC channel 2, DC-coupled)
 *   MEMS mic MK1 (IM73A135)  ->  TAC5212 IN1P/IN1M   (ADC channel 1, AC-coupled)
 *   TAC5212 OUT1P / OUT2P    ->  stimulus jack J11 (TRS, AC-coupled, OUTxM to GND)
 *   OPA376 (U9)              ->  driven-right-leg feedback to J6 tip
 *
 * The ESP32-S3 is the I2S clock master; the TAC5212 recovers its internal
 * clocks from BCLK through its PLL (there is no MCLK line on this board).
 */
#pragma once

#include "driver/gpio.h"
#include "hal/i2s_types.h"
#include "hal/adc_types.h"

#ifdef __cplusplus
extern "C" {
#endif

/* ------------------------------------------------------------------ */
/* Identity                                                            */
/* ------------------------------------------------------------------ */
#define BOARD_NAME              "Wireless BERA"
#define BOARD_HW_REV            "1.0"
#define FIRMWARE_VERSION        "2.0.0"

/* ------------------------------------------------------------------ */
/* I2C control bus (TAC5212 + TPS65132W)                               */
/* ------------------------------------------------------------------ */
#define BOARD_I2C_PORT          I2C_NUM_0
#define BOARD_I2C_SDA_GPIO      GPIO_NUM_4      /* U7.4  <-> U11.8, U5.7   */
#define BOARD_I2C_SCL_GPIO      GPIO_NUM_5      /* U7.5  <-> U11.7, U5.8   */
#define BOARD_I2C_HZ            400000          /* R30/R31 = 10k to +3.5V  */

/* TAC5212 ADDR pin (U11.13) is shorted to GNDD -> 7-bit address 0x50.
 * (The five MSBs of the address are fixed at 0b10100 in the silicon.)     */
#define TAC5212_I2C_ADDR        0x50
#define TPS65132_I2C_ADDR       0x3E

/* ------------------------------------------------------------------ */
/* I2S audio serial interface to the TAC5212                           */
/* ------------------------------------------------------------------ */
/* Net names in the schematic are from the CODEC's point of view:
 *   net I2S_DOUT = TAC5212 DOUT (pin 4) -> ESP GPIO7  => ESP receives here
 *   net I2S_DIN  = TAC5212 DIN  (pin 5) <- ESP GPIO6  => ESP transmits here   */
#define BOARD_I2S_PORT          I2S_NUM_0
#define BOARD_I2S_BCLK_GPIO     GPIO_NUM_16     /* U7.9  -> U11.2 BCLK     */
#define BOARD_I2S_FSYNC_GPIO    GPIO_NUM_15     /* U7.8  -> U11.3 FSYNC    */
#define BOARD_I2S_DIN_GPIO      GPIO_NUM_7      /* ESP in  <- codec DOUT   */
#define BOARD_I2S_DOUT_GPIO     GPIO_NUM_6      /* ESP out -> codec DIN    */

/* ------------------------------------------------------------------ */
/* LTC6373 programmable-gain instrumentation amplifier (U10)           */
/* ------------------------------------------------------------------ */
/* Logic levels are referenced to the LTC6373 DGND pin, which is tied to
 * GNDA on this board: VIL <= 0.6 V, VIH >= 1.5 V. The ESP drives 3.5 V
 * CMOS through 10 k series resistors (R35/R36/R37), so both are satisfied.
 * All three pins have internal pull-downs, so a floating ESP pin (e.g. at
 * reset, before gpio config) selects G = 16.
 *
 * HARDWARE CAVEAT on the current v1.0 build: R35, R36 and R37 are NOT fitted,
 * so these GPIOs are not connected to U10 at all. The amplifier's A2/A1/A0
 * pins float, its internal pull-downs take them to DGND, and it therefore
 * runs permanently at G = 16. The driver below still toggles the pins (and
 * they are correct), but the gain will not change until those three resistors
 * are populated. Set BOARD_PGIA_RESISTORS_FITTED to 1 once they are.        */
#define BOARD_PGIA_RESISTORS_FITTED  0
#define BOARD_PGIA_FIXED_GAIN        16.0f   /* while the above is 0 */
#define BOARD_PGIA_A0_GPIO      GPIO_NUM_8      /* U7.12 -> R35 -> U10.2   */
#define BOARD_PGIA_A1_GPIO      GPIO_NUM_18     /* U7.11 -> R36 -> U10.3   */
#define BOARD_PGIA_A2_GPIO      GPIO_NUM_17     /* U7.10 -> R37 -> U10.11  */

/* ------------------------------------------------------------------ */
/* Status LED D2 (green, 0603) - active high through R32 = 330 R        */
/* ------------------------------------------------------------------ */
#define BOARD_LED_GPIO          GPIO_NUM_21     /* U7.23 -> R32 -> D2      */

/* ------------------------------------------------------------------ */
/* Battery sense - R23/R24 = 10k/10k divider from V_BAT                 */
/* ------------------------------------------------------------------ */
#define BOARD_VBAT_GPIO         GPIO_NUM_1      /* U7.39                   */
#define BOARD_VBAT_ADC_UNIT     ADC_UNIT_1
#define BOARD_VBAT_ADC_CHANNEL  ADC_CHANNEL_0   /* GPIO1 = ADC1_CH0        */
#define BOARD_VBAT_DIVIDER      2.0f            /* (R23 + R24) / R24       */

/* Single-cell Li-Ion, charged by the BQ24074 (U2) to 4.2 V. */
#define BOARD_VBAT_FULL_MV      4200
#define BOARD_VBAT_EMPTY_MV     3300

/* ------------------------------------------------------------------ */
/* microSD card J4 - SDMMC slot 1, 4-bit, card VDD = +3.5V_ESP          */
/* ------------------------------------------------------------------ */
/* Not used by this firmware version yet, recorded here so that nobody
 * re-assigns these pins by accident. D2 sits on GPIO44 (= U0RXD); that is
 * fine because the console runs over the native USB-Serial/JTAG port.      */
#define BOARD_SD_CLK_GPIO       GPIO_NUM_40
#define BOARD_SD_CMD_GPIO       GPIO_NUM_41
#define BOARD_SD_D0_GPIO        GPIO_NUM_39
#define BOARD_SD_D1_GPIO        GPIO_NUM_38
#define BOARD_SD_D2_GPIO        GPIO_NUM_44
#define BOARD_SD_D3_GPIO        GPIO_NUM_42

/* ------------------------------------------------------------------ */
/* Buttons                                                             */
/* ------------------------------------------------------------------ */
#define BOARD_BOOT_GPIO         GPIO_NUM_0      /* SW3, active low         */

/* ------------------------------------------------------------------ */
/* Analog front-end constants                                          */
/* ------------------------------------------------------------------ */
/* LTC6373 differential output common mode, set by R40 (4.99k to +3.3V_TAC_A)
 * and R43 (10k to GNDA): VOCM = 3.3 * 10 / 14.99 = 2.20 V.
 * The TAC5212 IN2x pins are DC-coupled to this, so ADC channel 2 must run in
 * rail-to-rail common-mode tolerance mode (CM_TOL = 2).                    */
#define BOARD_PGIA_VOCM_V       2.20f

/* MEMS microphone MK1 (IM73A135V01) is powered from the codec MICBIAS pin.
 * Its ABSOLUTE MAXIMUM supply is 3.0 V, so MICBIAS must stay at VREF
 * (2.75 V) - never switch MICBIAS to the "bypass to AVDD" (3.3 V) setting. */
#define BOARD_MIC_VDD_MAX_V     3.0f
#define BOARD_MIC_SENS_DBV      (-38.0f)        /* dBV @ 94 dB SPL, 1 kHz  */

/* TPS65132W (U5) pre-programmed defaults are +/-5.4 V. The TPS7A39 dual LDO
 * (U4) downstream needs roughly 250 mV of headroom for its +/-5 V outputs,
 * so do not program the rails below about 5.3 V.                           */
#define BOARD_RAIL_DEFAULT_V    5.4f
#define BOARD_RAIL_MIN_SAFE_V   5.3f

#ifdef __cplusplus
}
#endif
