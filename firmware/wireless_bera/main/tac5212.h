/*
 * tac5212.h - TI TAC5212 stereo codec (U11), I2C control at 0x50.
 *
 * Wiring on this board (see board.h):
 *   IN1P/IN1M  <- IM73A135 MEMS microphone, AC-coupled through 22 uF
 *   IN2P/IN2M  <- LTC6373 differential output, DC-coupled, VOCM = 2.2 V
 *   OUT1P      -> stimulus jack ring  (OUT1M tied to GNDA through R49 = 0 R)
 *   OUT2P      -> stimulus jack tip   (OUT2M tied to GNDA through R46 = 0 R)
 *
 * Because OUT1M/OUT2M are grounded, both outputs must run in the codec's
 * "mono single-ended on OUTxP" mode (datasheet Figure 7-22) - any differential
 * or stereo-SE setting would drive a pin straight into the ground plane.
 *
 * There is no MCLK trace, so the codec derives everything from BCLK through
 * its PLL (CLK_SRC_SEL = 0). BCLK must therefore already be running before
 * the analog blocks are powered up.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/* ---- Page 0 registers actually used by this driver ------------------- */
#define TAC_REG_PAGE_CFG            0x00
#define TAC_REG_SW_RESET            0x01
#define TAC_REG_DEV_MISC_CFG        0x02
#define TAC_REG_AVDD_IOVDD_STS      0x03
#define TAC_REG_MISC_CFG            0x04
#define TAC_REG_ASI_CFG0            0x18
#define TAC_REG_PASI_CFG0           0x1A
#define TAC_REG_PASI_TX_CFG0        0x1B
#define TAC_REG_PASI_TX_CH1_CFG     0x1E
#define TAC_REG_PASI_TX_CH2_CFG     0x1F
#define TAC_REG_PASI_RX_CH1_CFG     0x28
#define TAC_REG_PASI_RX_CH2_CFG     0x29
#define TAC_REG_CLK_CFG0            0x32
#define TAC_REG_CLK_CFG2            0x34
#define TAC_REG_CLK_ERR_STS0        0x3C
#define TAC_REG_CLK_ERR_STS1        0x3D
#define TAC_REG_CLK_DET_STS0        0x3E
#define TAC_REG_CLK_DET_STS2        0x40
#define TAC_REG_CLK_DET_STS3        0x41
#define TAC_REG_VREF_MICBIAS_CFG    0x4D
#define TAC_REG_ADC_CH1_CFG0        0x50
#define TAC_REG_ADC_CH1_DVOL        0x52
#define TAC_REG_ADC_CH2_CFG0        0x55
#define TAC_REG_ADC_CH2_DVOL        0x57
#define TAC_REG_ADC_CFG1            0x62
#define TAC_REG_OUT1x_CFG0          0x64
#define TAC_REG_OUT1x_CFG1          0x65
#define TAC_REG_OUT1x_CFG2          0x66
#define TAC_REG_DAC_CH1A_DVOL       0x67
#define TAC_REG_DAC_CH1B_DVOL       0x69
#define TAC_REG_OUT2x_CFG0          0x6B
#define TAC_REG_OUT2x_CFG1          0x6C
#define TAC_REG_OUT2x_CFG2          0x6D
#define TAC_REG_DAC_CH2A_DVOL       0x6E
#define TAC_REG_DAC_CH2B_DVOL       0x70
#define TAC_REG_CH_EN               0x76
#define TAC_REG_PWR_CFG             0x78
#define TAC_REG_DEV_STS0            0x79
#define TAC_REG_DEV_STS1            0x7A

/* Output driver strength, OUTxP_DRIVE[1:0]. */
typedef enum {
    TAC_DRIVE_LINE = 0,     /* >= 300 ohm load  */
    TAC_DRIVE_HEADPHONE,    /* >= 16 ohm load   */
    TAC_DRIVE_4OHM,
    TAC_DRIVE_HIGH_DR,
} tac_drive_t;

typedef struct {
    bool     present;       /* device ACKed on the I2C bus              */
    uint8_t  dev_sts0;      /* per-channel power status                 */
    uint8_t  dev_sts1;      /* mode / PLL / MICBIAS                     */
    uint8_t  clk_err0;      /* clock error flags                        */
    uint8_t  clk_err1;
    uint16_t clk_det_ratio; /* FSYNC:clock-source ratio the codec found */
    uint8_t  fs_det_code;   /* CLK_DET_STS0 sample-rate code            */
    uint8_t  mode;          /* DEV_STS1[7:5]: 4 = sleep, 6/7 = active   */
    bool     pll_locked;
    bool     micbias_on;
    bool     adc_ch1_on;
    bool     adc_ch2_on;
    bool     dac_ch1_on;
    bool     dac_ch2_on;
} tac5212_status_t;

/* Probe + software reset. Does not power any analog block up. */
esp_err_t tac5212_probe(void);

/*
 * Full configuration for this board. Call AFTER the I2S peripheral is running
 * and BCLK/FSYNC are toggling, otherwise the PLL has nothing to lock to.
 *
 * slot_bits must match the I2S slot width the ESP32 generates (32 here).
 */
esp_err_t tac5212_configure(uint32_t sample_rate_hz, uint8_t slot_bits);

/* Power the enabled channels up or down (PWR_CFG). */
esp_err_t tac5212_set_power(bool adc_on, bool dac_on, bool micbias_on);

/* Channel enables (CH_EN). ch1 = microphone, ch2 = biopotential. */
esp_err_t tac5212_set_channels(bool adc_ch1, bool adc_ch2, bool dac_ch1, bool dac_ch2);

/* Digital volume, -80 .. +47 dB for the ADC, -100 .. +27 dB for the DAC.
 * Values outside the range are clamped; mute is a separate flag. */
esp_err_t tac5212_set_adc_volume_db(int channel /*1,2*/, float db, bool mute);
esp_err_t tac5212_set_dac_volume_db(int channel /*1,2*/, float db, bool mute);
float     tac5212_get_adc_volume_db(int channel);
float     tac5212_get_dac_volume_db(int channel);

/* Output driver strength for OUT1P / OUT2P. */
esp_err_t tac5212_set_output_drive(tac_drive_t drive);
tac_drive_t tac5212_get_output_drive(void);

/* ADC channel front-end. imp: 0 = 5k, 1 = 10k, 2 = 40k.
 * cm_tol: 0 = AC only, 1 = +/-500 mV, 2 = rail-to-rail (needed for the
 * DC-coupled LTC6373 output on channel 2).
 * fullscale: 0 = 2 Vrms differential, 1 = 4 Vrms differential. */
esp_err_t tac5212_set_adc_frontend(int channel, uint8_t imp, uint8_t cm_tol, uint8_t fullscale);

esp_err_t tac5212_read_status(tac5212_status_t *out);
const char *tac5212_mode_name(uint8_t mode);

/* Raw register access for the web register browser. */
esp_err_t tac5212_write_reg(uint8_t page, uint8_t reg, uint8_t val);
esp_err_t tac5212_read_reg(uint8_t page, uint8_t reg, uint8_t *val);
esp_err_t tac5212_dump_page(uint8_t page, uint8_t *buf128);

/*
 * Reads the codec's internal diagnostic SAR monitor for AVDD (page 1).
 * Returns the raw 12-bit code; `volts` is the in-system estimate using the
 * scale factor calibrated at first use against the nominal 3.3 V rail, so it
 * tracks a sagging supply even though TI does not publish the LSB size.
 */
esp_err_t tac5212_read_avdd(uint16_t *code, float *volts);

/* Full-scale differential input voltage of an ADC channel, in volts RMS.
 * Used to convert codec counts into physical units. */
float tac5212_adc_fullscale_vrms(int channel);

#ifdef __cplusplus
}
#endif
