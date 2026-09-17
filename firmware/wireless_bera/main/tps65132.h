/* tps65132.h - TPS65132W (U5) dual charge pump, +/-5.4 V by default.
 *
 * ENP/ENN are strapped to V_IN, so both rails come up with their factory
 * EEPROM values as soon as the board is powered; I2C is only needed to read
 * back or trim them. These raw rails feed the TPS7A39 dual LDO (U4) which
 * produces the +/-5 V analog supplies, so keep them above BOARD_RAIL_MIN_SAFE_V.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

#define TPS65132_REG_VPOS   0x00
#define TPS65132_REG_VNEG   0x01
#define TPS65132_REG_APPS   0x03
#define TPS65132_REG_CTRL   0xFF

bool tps65132_present(void);

/* Voltage magnitude in volts, 4.0 .. 6.0 in 0.1 V steps. */
esp_err_t tps65132_get_vpos(float *volts);
esp_err_t tps65132_get_vneg(float *volts);
esp_err_t tps65132_set_vpos(float volts);
esp_err_t tps65132_set_vneg(float volts);

esp_err_t tps65132_read_reg(uint8_t reg, uint8_t *val);

#ifdef __cplusplus
}
#endif
