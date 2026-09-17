/* pgia.h - LTC6373 programmable-gain instrumentation amplifier (U10).
 *
 * Gain is selected with three parallel pins A2/A1/A0 (datasheet Table 5).
 * There is no readback path, so the current setting is cached in RAM.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    PGIA_GAIN_16 = 0,       /* A2 A1 A0 = L L L */
    PGIA_GAIN_8,            /* L L H */
    PGIA_GAIN_4,            /* L H L */
    PGIA_GAIN_2,            /* L H H */
    PGIA_GAIN_1,            /* H L L */
    PGIA_GAIN_0_5,          /* H L H */
    PGIA_GAIN_0_25,         /* H H L */
    PGIA_SHUTDOWN,          /* H H H */
    PGIA_GAIN_COUNT
} pgia_gain_t;

esp_err_t pgia_init(pgia_gain_t initial);
esp_err_t pgia_set(pgia_gain_t gain);
pgia_gain_t pgia_get(void);

/* Numeric gain in V/V; 0.0f for PGIA_SHUTDOWN. */
float pgia_gain_value(pgia_gain_t gain);
const char *pgia_gain_name(pgia_gain_t gain);

/* False when the select lines cannot reach the amplifier because the series
 * resistors R35-R37 are unpopulated (see board.h). The GPIOs are still driven,
 * but the LTC6373 stays at its floating default. */
bool pgia_control_available(void);

/* The gain the amplifier is actually running at, which differs from
 * pgia_get() whenever pgia_control_available() is false. */
float pgia_effective_gain_value(void);

#ifdef __cplusplus
}
#endif
