#include "tps65132.h"

#include <math.h>

#include "board.h"
#include "esp_log.h"
#include "i2c_bus.h"

static const char *TAG = "tps65132";

#define RAIL_MIN_V  4.0f
#define RAIL_MAX_V  6.0f
#define RAIL_STEP_V 0.1f

static esp_err_t rail_get(uint8_t reg, float *volts)
{
    uint8_t code;
    esp_err_t err = i2c_bus_read_u8(TPS65132_I2C_ADDR, reg, &code);
    if (err != ESP_OK) {
        return err;
    }
    *volts = RAIL_MIN_V + (code & 0x1F) * RAIL_STEP_V;
    return ESP_OK;
}

static esp_err_t rail_set(uint8_t reg, float volts, const char *what)
{
    if (!(volts >= RAIL_MIN_V && volts <= RAIL_MAX_V)) {
        return ESP_ERR_INVALID_ARG;
    }
    const uint8_t code = (uint8_t)lroundf((volts - RAIL_MIN_V) / RAIL_STEP_V) & 0x1F;
    esp_err_t err = i2c_bus_write_u8(TPS65132_I2C_ADDR, reg, code);
    if (err != ESP_OK) {
        return err;
    }
    if (volts < BOARD_RAIL_MIN_SAFE_V) {
        ESP_LOGW(TAG, "%s set to %.1f V - below %.1f V the TPS7A39 loses headroom "
                      "and the +/-5 V analog rails will sag",
                 what, (double)volts, (double)BOARD_RAIL_MIN_SAFE_V);
    } else {
        ESP_LOGI(TAG, "%s = %.1f V (code 0x%02X)", what, (double)volts, code);
    }
    return ESP_OK;
}

bool tps65132_present(void)                 { return i2c_bus_probe(TPS65132_I2C_ADDR); }
esp_err_t tps65132_get_vpos(float *v)       { return rail_get(TPS65132_REG_VPOS, v); }
esp_err_t tps65132_get_vneg(float *v)       { return rail_get(TPS65132_REG_VNEG, v); }
esp_err_t tps65132_set_vpos(float v)        { return rail_set(TPS65132_REG_VPOS, v, "VPOS"); }
esp_err_t tps65132_set_vneg(float v)        { return rail_set(TPS65132_REG_VNEG, v, "VNEG"); }

esp_err_t tps65132_read_reg(uint8_t reg, uint8_t *val)
{
    return i2c_bus_read_u8(TPS65132_I2C_ADDR, reg, val);
}
