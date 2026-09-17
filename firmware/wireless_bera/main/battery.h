/* battery.h - V_BAT monitor on ADC1_CH0 (GPIO1) behind a 10k/10k divider. */
#pragma once

#include <stdint.h>
#include <stdbool.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

esp_err_t battery_init(void);

/* Averaged battery terminal voltage in millivolts, or 0 if unavailable. */
int battery_millivolts(void);

/* Rough state of charge in percent, clamped to 0..100. */
int battery_percent(void);

/* True while the USB port is supplying the system (heuristic: the BQ24074
 * holds V_BAT at the charge voltage, so a sustained reading above the
 * cell's open-circuit maximum means external power). */
bool battery_is_charging_hint(void);

#ifdef __cplusplus
}
#endif
