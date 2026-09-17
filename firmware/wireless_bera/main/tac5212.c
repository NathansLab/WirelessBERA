#include "tac5212.h"

#include <inttypes.h>
#include <math.h>
#include <string.h>

#include "board.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "i2c_bus.h"

static const char *TAG = "tac5212";

static uint8_t s_page = 0xFF;           /* unknown until first select */
static float   s_adc_db[2] = { 0.0f, 0.0f };
static float   s_dac_db[2] = { 0.0f, 0.0f };
static uint8_t s_adc_fullscale[2] = { 0, 0 };
static tac_drive_t s_drive = TAC_DRIVE_HEADPHONE;

/* ------------------------------------------------------------------ */
/* Register plumbing                                                   */
/* ------------------------------------------------------------------ */

static esp_err_t select_page(uint8_t page)
{
    if (s_page == page) {
        return ESP_OK;
    }
    esp_err_t err = i2c_bus_write_u8(TAC5212_I2C_ADDR, TAC_REG_PAGE_CFG, page);
    if (err == ESP_OK) {
        s_page = page;
    } else {
        s_page = 0xFF;
    }
    return err;
}

esp_err_t tac5212_write_reg(uint8_t page, uint8_t reg, uint8_t val)
{
    esp_err_t err = select_page(page);
    if (err != ESP_OK) {
        return err;
    }
    if (reg == TAC_REG_PAGE_CFG) {
        s_page = val;   /* caller is switching pages behind our back */
    }
    return i2c_bus_write_u8(TAC5212_I2C_ADDR, reg, val);
}

esp_err_t tac5212_read_reg(uint8_t page, uint8_t reg, uint8_t *val)
{
    esp_err_t err = select_page(page);
    if (err != ESP_OK) {
        return err;
    }
    return i2c_bus_read_u8(TAC5212_I2C_ADDR, reg, val);
}

esp_err_t tac5212_dump_page(uint8_t page, uint8_t *buf128)
{
    esp_err_t err = select_page(page);
    if (err != ESP_OK) {
        return err;
    }
    /* Read in chunks: the codec supports sequential reads, but short bursts
     * keep the bus free for the audio-rate status poller. */
    for (int off = 0; off < 128; off += 16) {
        err = i2c_bus_read_burst(TAC5212_I2C_ADDR, (uint8_t)off, buf128 + off, 16);
        if (err != ESP_OK) {
            return err;
        }
    }
    return ESP_OK;
}

/* w0() writes page 0 and logs failures - used throughout the init sequence. */
static esp_err_t w0(uint8_t reg, uint8_t val)
{
    esp_err_t err = tac5212_write_reg(0, reg, val);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "write 0x%02X = 0x%02X failed: %s", reg, val, esp_err_to_name(err));
    }
    return err;
}

/* ------------------------------------------------------------------ */
/* Probe and reset                                                     */
/* ------------------------------------------------------------------ */

esp_err_t tac5212_probe(void)
{
    if (!i2c_bus_probe(TAC5212_I2C_ADDR)) {
        ESP_LOGE(TAG, "no ACK at 0x%02X - check FB1/FB2 and the 3.3 V TAC rails",
                 TAC5212_I2C_ADDR);
        return ESP_ERR_NOT_FOUND;
    }

    s_page = 0xFF;
    esp_err_t err = w0(TAC_REG_SW_RESET, 0x01);
    if (err != ESP_OK) {
        return err;
    }
    vTaskDelay(pdMS_TO_TICKS(20));
    s_page = 0;     /* reset returns the device to page 0 */

    uint8_t supply = 0;
    tac5212_read_reg(0, TAC_REG_AVDD_IOVDD_STS, &supply);
    ESP_LOGI(TAG, "found at 0x%02X, AVDD_IOVDD_STS = 0x%02X", TAC5212_I2C_ADDR, supply);
    return ESP_OK;
}

/* ------------------------------------------------------------------ */
/* Sample-rate code (CLK_CFG0 PASI_SAMP_RATE[5:0])                     */
/* ------------------------------------------------------------------ */

static uint8_t samp_rate_code(uint32_t hz)
{
    /* Datasheet Table 8-47. 0 means "auto-detect", which works whenever the
     * rate is one of the standard audio rates; we pin it explicitly for the
     * rates we offer so a marginal BCLK cannot pick the wrong divider. */
    switch (hz) {
    case 96000: return 15;
    case 48000: return 20;
    case 32000: return 23;
    case 24000: return 25;
    case 16000: return 28;
    case 8000:  return 33;
    default:    return 0;   /* auto detect */
    }
}

/* ------------------------------------------------------------------ */
/* Volume helpers                                                      */
/* ------------------------------------------------------------------ */

/* ADC: code 1 = -80 dB, 161 = 0 dB, 255 = +47 dB, 0.5 dB per step, 0 = mute. */
static uint8_t adc_db_to_code(float db)
{
    if (db < -80.0f) db = -80.0f;
    if (db >  47.0f) db =  47.0f;
    int code = 161 + (int)lroundf(db * 2.0f);
    if (code < 1)   code = 1;
    if (code > 255) code = 255;
    return (uint8_t)code;
}

/* DAC: code 1 = -100 dB, 201 = 0 dB, 255 = +27 dB, 0.5 dB per step, 0 = mute. */
static uint8_t dac_db_to_code(float db)
{
    if (db < -100.0f) db = -100.0f;
    if (db >   27.0f) db =   27.0f;
    int code = 201 + (int)lroundf(db * 2.0f);
    if (code < 1)   code = 1;
    if (code > 255) code = 255;
    return (uint8_t)code;
}

esp_err_t tac5212_set_adc_volume_db(int channel, float db, bool mute)
{
    if (channel < 1 || channel > 2) {
        return ESP_ERR_INVALID_ARG;
    }
    const uint8_t reg = (channel == 1) ? TAC_REG_ADC_CH1_DVOL : TAC_REG_ADC_CH2_DVOL;
    const uint8_t code = mute ? 0 : adc_db_to_code(db);
    esp_err_t err = w0(reg, code);
    if (err == ESP_OK && !mute) {
        s_adc_db[channel - 1] = db;
    }
    return err;
}

esp_err_t tac5212_set_dac_volume_db(int channel, float db, bool mute)
{
    if (channel < 1 || channel > 2) {
        return ESP_ERR_INVALID_ARG;
    }
    const uint8_t code = mute ? 0 : dac_db_to_code(db);
    /* Each output channel has two sub-DACs (A and B) that are summed into
     * OUTxP in mono single-ended mode - they must track each other. */
    const uint8_t reg_a = (channel == 1) ? TAC_REG_DAC_CH1A_DVOL : TAC_REG_DAC_CH2A_DVOL;
    const uint8_t reg_b = (channel == 1) ? TAC_REG_DAC_CH1B_DVOL : TAC_REG_DAC_CH2B_DVOL;

    esp_err_t err = w0(reg_a, code);
    if (err == ESP_OK) {
        err = w0(reg_b, code);
    }
    if (err == ESP_OK && !mute) {
        s_dac_db[channel - 1] = db;
    }
    return err;
}

float tac5212_get_adc_volume_db(int channel)
{
    return (channel >= 1 && channel <= 2) ? s_adc_db[channel - 1] : 0.0f;
}

float tac5212_get_dac_volume_db(int channel)
{
    return (channel >= 1 && channel <= 2) ? s_dac_db[channel - 1] : 0.0f;
}

/* ------------------------------------------------------------------ */
/* Front-end and output configuration                                  */
/* ------------------------------------------------------------------ */

esp_err_t tac5212_set_adc_frontend(int channel, uint8_t imp, uint8_t cm_tol, uint8_t fullscale)
{
    if (channel < 1 || channel > 2 || imp > 2 || cm_tol > 2 || fullscale > 1) {
        return ESP_ERR_INVALID_ARG;
    }
    /* INSRC = 0 (analog differential), BW_MODE = 0 (24 kHz audio band). */
    const uint8_t val = (uint8_t)((0 << 6) | (imp << 4) | (cm_tol << 2) | (fullscale << 1));
    const uint8_t reg = (channel == 1) ? TAC_REG_ADC_CH1_CFG0 : TAC_REG_ADC_CH2_CFG0;
    esp_err_t err = w0(reg, val);
    if (err == ESP_OK) {
        s_adc_fullscale[channel - 1] = fullscale;
    }
    return err;
}

float tac5212_adc_fullscale_vrms(int channel)
{
    if (channel < 1 || channel > 2) {
        return 0.0f;
    }
    return s_adc_fullscale[channel - 1] ? 4.0f : 2.0f;
}

esp_err_t tac5212_set_output_drive(tac_drive_t drive)
{
    if (drive > TAC_DRIVE_HIGH_DR) {
        return ESP_ERR_INVALID_ARG;
    }
    /* OUTxP_DRIVE[7:6], OUTxP_LVL_CTRL[5:3] = 4 (0 dB), rest default. */
    const uint8_t cfg1 = (uint8_t)((drive << 6) | (4 << 3));
    esp_err_t err = w0(TAC_REG_OUT1x_CFG1, cfg1);
    if (err == ESP_OK) {
        err = w0(TAC_REG_OUT2x_CFG1, cfg1);
    }
    if (err == ESP_OK) {
        s_drive = drive;
    }
    return err;
}

tac_drive_t tac5212_get_output_drive(void) { return s_drive; }

esp_err_t tac5212_set_channels(bool adc_ch1, bool adc_ch2, bool dac_ch1, bool dac_ch2)
{
    const uint8_t val = (uint8_t)((adc_ch1 ? 0x80 : 0) | (adc_ch2 ? 0x40 : 0) |
                                  (dac_ch1 ? 0x08 : 0) | (dac_ch2 ? 0x04 : 0));
    return w0(TAC_REG_CH_EN, val);
}

esp_err_t tac5212_set_power(bool adc_on, bool dac_on, bool micbias_on)
{
    const uint8_t val = (uint8_t)((adc_on ? 0x80 : 0) | (dac_on ? 0x40 : 0) |
                                  (micbias_on ? 0x20 : 0));
    return w0(TAC_REG_PWR_CFG, val);
}

/* ------------------------------------------------------------------ */
/* Full board configuration                                            */
/* ------------------------------------------------------------------ */

esp_err_t tac5212_configure(uint32_t sample_rate_hz, uint8_t slot_bits)
{
    esp_err_t err;

    /* 1. Leave sleep mode. SLEEP_ENZ = 1, and bring VREF up with it so the
     *    2.2 uF VREF cap is charged before the analog blocks start.
     *    AVDD_MODE = 0 and IOVDD_IO_MODE = 0 are correct for 3.3 V on both. */
    if ((err = w0(TAC_REG_DEV_MISC_CFG, 0x09)) != ESP_OK) return err;
    vTaskDelay(pdMS_TO_TICKS(20));      /* datasheet: >= 2 ms, >= 10 ms before
                                           channel-config registers */

    /* 2. Audio serial interface: primary ASI only, I2S, slot width to match
     *    what the ESP32 generates. */
    if ((err = w0(TAC_REG_ASI_CFG0, 0x40)) != ESP_OK) return err;   /* PASI on, SASI off */

    uint8_t wlen;
    switch (slot_bits) {
    case 16: wlen = 0; break;
    case 20: wlen = 1; break;
    case 24: wlen = 2; break;
    default: wlen = 3; break;   /* 32 bits */
    }
    /* PASI_FORMAT = 1 (I2S), normal FSYNC/BCLK polarity, bus-error detect on. */
    if ((err = w0(TAC_REG_PASI_CFG0, (uint8_t)((1 << 6) | (wlen << 4)))) != ESP_OK) return err;

    /* 3. Slot assignment. The reset values put channel 2 on "left slot 1",
     *    which does not exist in a two-slot I2S frame - move it to the right
     *    half (slot number 16). */
    if ((err = w0(TAC_REG_PASI_TX_CH1_CFG, 0x20 | 0)) != ESP_OK) return err;   /* ADC1 -> left  */
    if ((err = w0(TAC_REG_PASI_TX_CH2_CFG, 0x20 | 16)) != ESP_OK) return err;  /* ADC2 -> right */
    if ((err = w0(TAC_REG_PASI_RX_CH1_CFG, 0x20 | 0)) != ESP_OK) return err;   /* left  -> DAC1 */
    if ((err = w0(TAC_REG_PASI_RX_CH2_CFG, 0x20 | 16)) != ESP_OK) return err;  /* right -> DAC2 */

    /* 4. Clocking: PLL on, fractional allowed, source = primary ASI BCLK. */
    if ((err = w0(TAC_REG_CLK_CFG2, 0x40)) != ESP_OK) return err;
    if ((err = w0(TAC_REG_CLK_CFG0, (uint8_t)(samp_rate_code(sample_rate_hz) << 2))) != ESP_OK) return err;

    /* 5. VREF = 2.75 V (2 Vrms differential full scale) and MICBIAS = VREF.
     *    MICBIAS feeds the IM73A135, whose absolute maximum supply is 3.0 V,
     *    so the "bypass to AVDD" setting (3.3 V) must never be used here. */
    if ((err = w0(TAC_REG_VREF_MICBIAS_CFG, 0x00)) != ESP_OK) return err;

    /* 6. ADC channel 1 - MEMS microphone, AC-coupled through 22 uF into a
     *    10 k input, common mode set by the codec itself. */
    if ((err = tac5212_set_adc_frontend(1, /*imp*/1, /*cm_tol*/1, /*fullscale*/0)) != ESP_OK) return err;

    /* 7. ADC channel 2 - LTC6373 output, DC-coupled with a 2.2 V common mode.
     *    That is well outside the +/-500 mV window, so the channel needs the
     *    rail-to-rail high-CMRR mode. 40 k input impedance keeps the PGIA
     *    from having to drive a 5 k load. */
    if ((err = tac5212_set_adc_frontend(2, /*imp*/2, /*cm_tol*/2, /*fullscale*/0)) != ESP_OK) return err;

    /* 8. Outputs. OUT1M/OUT2M are tied to GNDA on this board, so both
     *    channels run as "mono single-ended on OUTxP" fed from the DAC. */
    const uint8_t outx_cfg0 = (uint8_t)((1 << 5) | (2 << 2));   /* SRC = DAC, CFG = mono SE */
    if ((err = w0(TAC_REG_OUT1x_CFG0, outx_cfg0)) != ESP_OK) return err;
    if ((err = w0(TAC_REG_OUT2x_CFG0, outx_cfg0)) != ESP_OK) return err;
    if ((err = tac5212_set_output_drive(TAC_DRIVE_HEADPHONE)) != ESP_OK) return err;

    /* 9. Unity digital gain everywhere; the DAC starts muted so that nothing
     *    pops into a headphone before the host asks for a stimulus. */
    if ((err = tac5212_set_adc_volume_db(1, 0.0f, false)) != ESP_OK) return err;
    if ((err = tac5212_set_adc_volume_db(2, 0.0f, false)) != ESP_OK) return err;
    if ((err = tac5212_set_dac_volume_db(1, 0.0f, false)) != ESP_OK) return err;
    if ((err = tac5212_set_dac_volume_db(2, 0.0f, false)) != ESP_OK) return err;

    /* 10. Enable both ADC and both DAC channels, then power up. MICBIAS first
     *     so the microphone supply has settled before its channel starts. */
    if ((err = tac5212_set_channels(true, true, true, true)) != ESP_OK) return err;

    if ((err = tac5212_set_power(false, false, true)) != ESP_OK) return err;
    vTaskDelay(pdMS_TO_TICKS(20));
    if ((err = tac5212_set_power(true, true, true)) != ESP_OK) return err;
    vTaskDelay(pdMS_TO_TICKS(30));

    tac5212_status_t st;
    if (tac5212_read_status(&st) == ESP_OK) {
        ESP_LOGI(TAG, "configured @ %" PRIu32 " Hz, %u-bit slots: mode=%s pll=%d "
                      "adc=%d%d dac=%d%d micbias=%d clk_err=%02X/%02X ratio=%u fs_code=%u",
                 sample_rate_hz, slot_bits, tac5212_mode_name(st.mode), st.pll_locked,
                 st.adc_ch1_on, st.adc_ch2_on, st.dac_ch1_on, st.dac_ch2_on,
                 st.micbias_on, st.clk_err0, st.clk_err1, st.clk_det_ratio, st.fs_det_code);
        if (st.clk_err0 || st.clk_err1) {
            ESP_LOGW(TAG, "clock errors reported - check BCLK is running and the "
                          "BCLK:FSYNC ratio is supported");
        }
    }
    return ESP_OK;
}

/* ------------------------------------------------------------------ */
/* Status                                                              */
/* ------------------------------------------------------------------ */

esp_err_t tac5212_read_status(tac5212_status_t *out)
{
    memset(out, 0, sizeof(*out));

    uint8_t v;
    esp_err_t err = tac5212_read_reg(0, TAC_REG_DEV_STS0, &v);
    if (err != ESP_OK) {
        return err;
    }
    out->present = true;
    out->dev_sts0 = v;
    out->adc_ch1_on = v & 0x80;
    out->adc_ch2_on = v & 0x40;
    out->dac_ch1_on = v & 0x08;
    out->dac_ch2_on = v & 0x04;

    if (tac5212_read_reg(0, TAC_REG_DEV_STS1, &v) == ESP_OK) {
        out->dev_sts1 = v;
        out->mode = (uint8_t)(v >> 5);
        out->pll_locked = v & 0x10;
        out->micbias_on = v & 0x08;
    }
    tac5212_read_reg(0, TAC_REG_CLK_ERR_STS0, &out->clk_err0);
    tac5212_read_reg(0, TAC_REG_CLK_ERR_STS1, &out->clk_err1);

    /* The detected ratio is a 14-bit value split over two registers. */
    uint8_t msb = 0, lsb = 0;
    tac5212_read_reg(0, TAC_REG_CLK_DET_STS2, &msb);
    tac5212_read_reg(0, TAC_REG_CLK_DET_STS3, &lsb);
    out->clk_det_ratio = (uint16_t)(((msb & 0x3F) << 8) | lsb);

    uint8_t fs_sts = 0;
    if (tac5212_read_reg(0, TAC_REG_CLK_DET_STS0, &fs_sts) == ESP_OK) {
        out->fs_det_code = (uint8_t)(fs_sts >> 2);
    }
    return ESP_OK;
}

/* Page 1 holds the diagnostic SAR monitors. Each one is a 12-bit value split
 * into an MSB byte and the top nibble of the following register; the low
 * nibble is a channel id that lets us confirm we read the right pair. */
#define TAC_P1_DIAG_CFG13       0x53
#define TAC_P1_MON_MSB_AVDD     0x6E
#define TAC_P1_MON_LSB_AVDD     0x6F
#define TAC_P1_AVDD_CHANNEL_ID  12

esp_err_t tac5212_read_avdd(uint16_t *code, float *volts)
{
    static bool enabled;
    if (!enabled) {
        /* DIAG_CFG13: enable the AVDD (and GPA) monitor channels. */
        if (tac5212_write_reg(1, TAC_P1_DIAG_CFG13, 0x06) != ESP_OK) {
            return ESP_FAIL;
        }
        enabled = true;
        vTaskDelay(pdMS_TO_TICKS(5));
    }

    uint8_t raw[2];
    esp_err_t err = tac5212_read_reg(1, TAC_P1_MON_MSB_AVDD, &raw[0]);
    if (err == ESP_OK) {
        err = tac5212_read_reg(1, TAC_P1_MON_LSB_AVDD, &raw[1]);
    }
    tac5212_write_reg(0, TAC_REG_PAGE_CFG, 0);      /* leave the page as we found it */
    if (err != ESP_OK) {
        return err;
    }
    if ((raw[1] & 0x0F) != TAC_P1_AVDD_CHANNEL_ID) {
        return ESP_ERR_INVALID_RESPONSE;
    }

    const uint16_t c = (uint16_t)((raw[0] << 4) | (raw[1] >> 4));
    if (code) {
        *code = c;
    }
    if (volts) {
        /* Calibrate once against the nominal rail; afterwards the reading is a
         * real measurement relative to that point. */
        static float lsb_v;
        if (lsb_v == 0.0f && c > 1000) {
            lsb_v = 3.3f / (float)c;
        }
        *volts = lsb_v > 0.0f ? c * lsb_v : 0.0f;
    }
    return ESP_OK;
}

const char *tac5212_mode_name(uint8_t mode)
{
    switch (mode) {
    case 4:  return "sleep";
    case 6:  return "active, all channels off";
    case 7:  return "active, channels running";
    default: return "reserved";
    }
}
