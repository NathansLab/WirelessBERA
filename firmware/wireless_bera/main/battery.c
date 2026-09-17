#include "battery.h"

#include "board.h"
#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "battery";

#define VBAT_SAMPLES        32
#define VBAT_PERIOD_MS      5000

static adc_oneshot_unit_handle_t s_adc;
static adc_cali_handle_t s_cali;
static volatile int s_millivolts;

static int battery_sample_once(void)
{
    int64_t acc = 0;
    int taken = 0;

    for (int i = 0; i < VBAT_SAMPLES; i++) {
        int raw;
        if (adc_oneshot_read(s_adc, BOARD_VBAT_ADC_CHANNEL, &raw) != ESP_OK) {
            continue;
        }
        int mv = raw;
        if (s_cali) {
            if (adc_cali_raw_to_voltage(s_cali, raw, &mv) != ESP_OK) {
                continue;
            }
        } else {
            /* Uncalibrated fallback: 12 dB attenuation, 12-bit, ~3100 mV span. */
            mv = raw * 3100 / 4095;
        }
        acc += mv;
        taken++;
    }

    if (taken == 0) {
        return 0;
    }
    return (int)((acc / taken) * BOARD_VBAT_DIVIDER);
}

static void battery_task(void *arg)
{
    for (;;) {
        s_millivolts = battery_sample_once();
        vTaskDelay(pdMS_TO_TICKS(VBAT_PERIOD_MS));
    }
}

esp_err_t battery_init(void)
{
    const adc_oneshot_unit_init_cfg_t unit_cfg = {
        .unit_id = BOARD_VBAT_ADC_UNIT,
        .ulp_mode = ADC_ULP_MODE_DISABLE,
    };
    esp_err_t err = adc_oneshot_new_unit(&unit_cfg, &s_adc);
    if (err != ESP_OK) {
        return err;
    }

    const adc_oneshot_chan_cfg_t chan_cfg = {
        .atten = ADC_ATTEN_DB_12,       /* ~0..3.1 V -> V_BAT up to ~6.2 V */
        .bitwidth = ADC_BITWIDTH_DEFAULT,
    };
    err = adc_oneshot_config_channel(s_adc, BOARD_VBAT_ADC_CHANNEL, &chan_cfg);
    if (err != ESP_OK) {
        return err;
    }

    const adc_cali_curve_fitting_config_t cali_cfg = {
        .unit_id = BOARD_VBAT_ADC_UNIT,
        .atten = ADC_ATTEN_DB_12,
        .bitwidth = ADC_BITWIDTH_DEFAULT,
    };
    if (adc_cali_create_scheme_curve_fitting(&cali_cfg, &s_cali) != ESP_OK) {
        ESP_LOGW(TAG, "no eFuse calibration - readings will be approximate");
        s_cali = NULL;
    }

    s_millivolts = battery_sample_once();
    ESP_LOGI(TAG, "V_BAT = %d mV (GPIO%d, divider %.1f)",
             s_millivolts, BOARD_VBAT_GPIO, (double)BOARD_VBAT_DIVIDER);

    if (xTaskCreate(battery_task, "battery", 3072, NULL, 2, NULL) != pdPASS) {
        return ESP_ERR_NO_MEM;
    }
    return ESP_OK;
}

int battery_millivolts(void) { return s_millivolts; }

int battery_percent(void)
{
    const int mv = s_millivolts;
    if (mv <= 0) {
        return 0;
    }
    int pct = (mv - BOARD_VBAT_EMPTY_MV) * 100 /
              (BOARD_VBAT_FULL_MV - BOARD_VBAT_EMPTY_MV);
    if (pct < 0)   pct = 0;
    if (pct > 100) pct = 100;
    return pct;
}

bool battery_is_charging_hint(void)
{
    return s_millivolts > (BOARD_VBAT_FULL_MV + 50);
}
