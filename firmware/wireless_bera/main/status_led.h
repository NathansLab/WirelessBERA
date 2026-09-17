/* status_led.h - D2 on GPIO21, driven by LEDC so patterns can fade. */
#pragma once

#include <stdint.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    LED_OFF = 0,
    LED_ON,
    LED_BLINK_SLOW,     /* 1 Hz  - idle / waiting for Wi-Fi     */
    LED_BLINK_FAST,     /* 5 Hz  - error                        */
    LED_BREATHE,        /* smooth fade - connected, idle        */
    LED_HEARTBEAT,      /* double blink - streaming             */
    LED_PATTERN_COUNT
} led_pattern_t;

esp_err_t status_led_init(void);

/* brightness: 0..100 % applied on top of the pattern. */
void status_led_set(led_pattern_t pattern, uint8_t brightness_pct);
led_pattern_t status_led_pattern(void);
uint8_t status_led_brightness(void);
const char *status_led_pattern_name(led_pattern_t p);

#ifdef __cplusplus
}
#endif
