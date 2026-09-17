#include "status_led.h"

#include <math.h>

#include "board.h"
#include "driver/ledc.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "led";

#define LED_TIMER       LEDC_TIMER_0
#define LED_CHANNEL     LEDC_CHANNEL_0
#define LED_MODE        LEDC_LOW_SPEED_MODE
#define LED_RES         LEDC_TIMER_12_BIT
#define LED_MAX_DUTY    ((1 << 12) - 1)
#define LED_TICK_MS     20

static const char *s_names[LED_PATTERN_COUNT] = {
    "off", "on", "blink_slow", "blink_fast", "breathe", "heartbeat"
};

static volatile led_pattern_t s_pattern = LED_BLINK_SLOW;
static volatile uint8_t s_brightness = 40;

static void led_apply(float level)
{
    if (level < 0.0f) level = 0.0f;
    if (level > 1.0f) level = 1.0f;
    /* Perceptual correction: the eye responds roughly to the square of duty. */
    const float corrected = level * level * (s_brightness / 100.0f);
    const uint32_t duty = (uint32_t)(corrected * LED_MAX_DUTY + 0.5f);
    ledc_set_duty(LED_MODE, LED_CHANNEL, duty);
    ledc_update_duty(LED_MODE, LED_CHANNEL);
}

static void led_task(void *arg)
{
    uint32_t phase_ms = 0;
    for (;;) {
        const led_pattern_t p = s_pattern;
        float level = 0.0f;

        switch (p) {
        case LED_OFF:
            level = 0.0f;
            break;
        case LED_ON:
            level = 1.0f;
            break;
        case LED_BLINK_SLOW:
            level = (phase_ms % 1000) < 120 ? 1.0f : 0.0f;
            break;
        case LED_BLINK_FAST:
            level = (phase_ms % 200) < 100 ? 1.0f : 0.0f;
            break;
        case LED_BREATHE:
            level = 0.5f * (1.0f - cosf(2.0f * (float)M_PI * (phase_ms % 3000) / 3000.0f));
            break;
        case LED_HEARTBEAT: {
            const uint32_t t = phase_ms % 1200;
            level = (t < 90 || (t >= 200 && t < 290)) ? 1.0f : 0.0f;
            break;
        }
        default:
            break;
        }

        led_apply(level);
        phase_ms += LED_TICK_MS;
        vTaskDelay(pdMS_TO_TICKS(LED_TICK_MS));
    }
}

esp_err_t status_led_init(void)
{
    const ledc_timer_config_t timer = {
        .speed_mode = LED_MODE,
        .timer_num = LED_TIMER,
        .duty_resolution = LED_RES,
        .freq_hz = 2000,
        .clk_cfg = LEDC_AUTO_CLK,
    };
    ESP_ERROR_CHECK(ledc_timer_config(&timer));

    const ledc_channel_config_t ch = {
        .speed_mode = LED_MODE,
        .channel = LED_CHANNEL,
        .timer_sel = LED_TIMER,
        .intr_type = LEDC_INTR_DISABLE,
        .gpio_num = BOARD_LED_GPIO,
        .duty = 0,
        .hpoint = 0,
    };
    ESP_ERROR_CHECK(ledc_channel_config(&ch));

    if (xTaskCreate(led_task, "led", 2560, NULL, 2, NULL) != pdPASS) {
        return ESP_ERR_NO_MEM;
    }
    ESP_LOGI(TAG, "status LED on GPIO%d", BOARD_LED_GPIO);
    return ESP_OK;
}

void status_led_set(led_pattern_t pattern, uint8_t brightness_pct)
{
    if (pattern < LED_PATTERN_COUNT) {
        s_pattern = pattern;
    }
    if (brightness_pct > 100) {
        brightness_pct = 100;
    }
    s_brightness = brightness_pct;
}

led_pattern_t status_led_pattern(void) { return s_pattern; }
uint8_t status_led_brightness(void)    { return s_brightness; }
const char *status_led_pattern_name(led_pattern_t p)
{
    return (p < LED_PATTERN_COUNT) ? s_names[p] : "?";
}
