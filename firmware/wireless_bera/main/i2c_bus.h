/* i2c_bus.h - shared I2C master for the TAC5212 codec and TPS65132W rails. */
#pragma once

#include <stdint.h>
#include <stdbool.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Initialises BOARD_I2C_PORT. Safe to call once, from app_main. */
esp_err_t i2c_bus_init(void);

/* 8-bit register access, the addressing scheme both on-board chips use. */
esp_err_t i2c_bus_write_u8(uint8_t dev_addr, uint8_t reg, uint8_t val);
esp_err_t i2c_bus_read_u8(uint8_t dev_addr, uint8_t reg, uint8_t *out);
esp_err_t i2c_bus_read_burst(uint8_t dev_addr, uint8_t reg, uint8_t *out, size_t len);

/* True if the device ACKs its address. */
bool i2c_bus_probe(uint8_t dev_addr);

/* Probes 0x08..0x77 and writes the found addresses into found[]. Returns the
 * number of devices detected (never more than max_found). */
int i2c_bus_scan(uint8_t *found, int max_found);

#ifdef __cplusplus
}
#endif
