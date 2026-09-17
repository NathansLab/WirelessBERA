#include "pgia.h"

#include "board.h"
#include "esp_log.h"

static const char *TAG = "pgia";

/* Index == pgia_gain_t. The enum is ordered so that the value itself is the
 * three-bit code {A2,A1,A0} - see LTC6373 datasheet Table 5. */
static const float  s_gain_value[PGIA_GAIN_COUNT] = { 16, 8, 4, 2, 1, 0.5f, 0.25f, 0.0f };
static const char  *s_gain_name[PGIA_GAIN_COUNT]  = { "16x", "8x", "4x", "2x", "1x",
                                                      "0.5x", "0.25x", "shutdown" };

static pgia_gain_t s_gain = PGIA_GAIN_1;

esp_err_t pgia_init(pgia_gain_t initial)
{
    const gpio_config_t cfg = {
        .pin_bit_mask = (1ULL << BOARD_PGIA_A0_GPIO) |
                        (1ULL << BOARD_PGIA_A1_GPIO) |
                        (1ULL << BOARD_PGIA_A2_GPIO),
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    esp_err_t err = gpio_config(&cfg);
    if (err != ESP_OK) {
        return err;
    }
    if (!pgia_control_available()) {
        ESP_LOGW(TAG, "R35-R37 are not fitted: the select lines do not reach U10, "
                      "so the LTC6373 runs at its floating default of G = %.0f "
                      "regardless of what is requested here",
                 (double)BOARD_PGIA_FIXED_GAIN);
    }
    return pgia_set(initial);
}

esp_err_t pgia_set(pgia_gain_t gain)
{
    if (gain < 0 || gain >= PGIA_GAIN_COUNT) {
        return ESP_ERR_INVALID_ARG;
    }
    gpio_set_level(BOARD_PGIA_A0_GPIO, (gain >> 0) & 1);
    gpio_set_level(BOARD_PGIA_A1_GPIO, (gain >> 1) & 1);
    gpio_set_level(BOARD_PGIA_A2_GPIO, (gain >> 2) & 1);
    s_gain = gain;
    ESP_LOGI(TAG, "gain = %s (A2A1A0 = %d%d%d)", s_gain_name[gain],
             (gain >> 2) & 1, (gain >> 1) & 1, gain & 1);
    return ESP_OK;
}

pgia_gain_t pgia_get(void)                 { return s_gain; }

bool pgia_control_available(void)
{
    return BOARD_PGIA_RESISTORS_FITTED != 0;
}

float pgia_effective_gain_value(void)
{
    return pgia_control_available() ? s_gain_value[s_gain] : BOARD_PGIA_FIXED_GAIN;
}
float pgia_gain_value(pgia_gain_t gain)    { return (gain < PGIA_GAIN_COUNT) ? s_gain_value[gain] : 0.0f; }
const char *pgia_gain_name(pgia_gain_t gain) { return (gain < PGIA_GAIN_COUNT) ? s_gain_name[gain] : "?"; }
