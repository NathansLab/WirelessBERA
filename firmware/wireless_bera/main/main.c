/*
 * Wireless BERA - ESP32-S3 firmware.
 *
 * Boot order matters here:
 *   1. LED first, so the board shows a sign of life before anything can hang.
 *   2. Networking early, so a failing analog section can still be debugged
 *      over Wi-Fi rather than only over the serial console.
 *   3. I2C, then I2S, then the codec. The TAC5212 has no MCLK input - it locks
 *      its PLL to BCLK - so the I2S peripheral must already be clocking before
 *      the codec is configured and powered up.
 */
#include <inttypes.h>

#include "audio.h"
#include "battery.h"
#include "board.h"
#include "console.h"
#include "esp_log.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "i2c_bus.h"
#include "net.h"
#include "pgia.h"
#include "status_led.h"
#include "tac5212.h"
#include "tps65132.h"
#include "web.h"

static const char *TAG = "main";

#define DEFAULT_SAMPLE_RATE     48000
#define DEFAULT_SCOPE_DECIM     48      /* -> 1 kHz on the scope stream */

static void log_banner(void)
{
    ESP_LOGI(TAG, "");
    ESP_LOGI(TAG, "=== %s v%s - firmware %s ===", BOARD_NAME, BOARD_HW_REV, FIRMWARE_VERSION);
    ESP_LOGI(TAG, "reset reason: %d", esp_reset_reason());
}

static void bring_up_analog(void)
{
    /* The charge pump comes up on its own (ENP/ENN are strapped high); we only
     * read it back so the log shows what the +/-5 V LDOs are being fed. */
    if (tps65132_present()) {
        float vpos = 0, vneg = 0;
        tps65132_get_vpos(&vpos);
        tps65132_get_vneg(&vneg);
        ESP_LOGI(TAG, "TPS65132W rails: +%.1f V / -%.1f V", (double)vpos, (double)vneg);
        if (vpos < BOARD_RAIL_MIN_SAFE_V || vneg < BOARD_RAIL_MIN_SAFE_V) {
            ESP_LOGW(TAG, "rails below %.1f V - the TPS7A39 will not hold +/-5 V",
                     (double)BOARD_RAIL_MIN_SAFE_V);
        }
    } else {
        ESP_LOGW(TAG, "TPS65132W did not answer at 0x%02X", TPS65132_I2C_ADDR);
    }

    /* Unity gain is the safe default: the electrode input is unknown at boot
     * and G = 16 would clip on any DC offset. */
    ESP_ERROR_CHECK(pgia_init(PGIA_GAIN_1));

    if (tac5212_probe() != ESP_OK) {
        ESP_LOGE(TAG, "codec not found - the web UI will come up without audio");
        status_led_set(LED_BLINK_FAST, 40);
        return;
    }

    /* I2S first: BCLK has to be running before the codec's PLL can lock. */
    ESP_ERROR_CHECK(audio_init(DEFAULT_SAMPLE_RATE, web_publish_scope));
    ESP_ERROR_CHECK(audio_set_decimation(DEFAULT_SCOPE_DECIM));
    vTaskDelay(pdMS_TO_TICKS(100));

    if (tac5212_configure(DEFAULT_SAMPLE_RATE, AUDIO_SLOT_BITS) != ESP_OK) {
        ESP_LOGE(TAG, "codec configuration failed");
        status_led_set(LED_BLINK_FAST, 40);
        return;
    }

    /* Nothing should be audible until the operator asks for a stimulus. */
    stim_config_t silent;
    audio_get_stimulus(&silent);
    silent.type = STIM_OFF;
    audio_set_stimulus(&silent);

    status_led_set(LED_BREATHE, 30);
}

void app_main(void)
{
    log_banner();

    ESP_ERROR_CHECK(status_led_init());
    status_led_set(LED_BLINK_SLOW, 40);
    console_start();

    ESP_ERROR_CHECK(battery_init());
    ESP_ERROR_CHECK(net_init());
    ESP_ERROR_CHECK(web_start());

    ESP_ERROR_CHECK(i2c_bus_init());
    i2c_bus_scan(NULL, 0);

    bring_up_analog();

    net_status_t n;
    net_get_status(&n);
    ESP_LOGI(TAG, "ready - http://%s (access point \"%s\") or http://%s.local",
             n.ap_ip, n.ap_ssid, n.hostname);

    /* Everything else runs in its own task; keep app_main alive only to report
     * that the system is still breathing. */
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(60000));
        ESP_LOGI(TAG, "uptime tick - heap %" PRIu32 " B, V_BAT %d mV",
                 (uint32_t)esp_get_free_heap_size(), battery_millivolts());
    }
}
