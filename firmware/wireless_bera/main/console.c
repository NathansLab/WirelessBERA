#include "console.h"

#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "audio.h"
#include "battery.h"
#include "board.h"
#include "driver/usb_serial_jtag.h"
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

static const char *TAG = "console";

#define CON_LINE_MAX    160
#define CON_ARG_MAX     8

static void cmd_help(void)
{
    printf(
        "\n"
        "  help                       this list\n"
        "  status                     device, codec and audio summary\n"
        "  wifi <ssid> [password]     store station credentials and connect\n"
        "  wifi-forget                clear stored station credentials\n"
        "  ap <password>              change the access point password\n"
        "  scan                       list nearby networks\n"
        "  i2c                        scan the control bus\n"
        "  reg <page> <addr> [value]  read or write a codec register (hex)\n"
        "  gain <0-7>                 PGIA: 0=16x 1=8x 2=4x 3=2x 4=1x 5=0.5x 6=0.25x 7=off\n"
        "  stream <on|off>            scope streaming over the websocket\n"
        "  stim <type> [amp] [freq]   0=off 1=sine 2=square 3=tri 4=noise 5=click 6=burst 7=chirp\n"
        "  led <pattern> [percent]    0=off 1=on 2=slow 3=fast 4=breathe 5=heartbeat\n"
        "  reboot                     restart the device\n"
        "\n");
}

static void cmd_status(void)
{
    net_status_t n;
    net_get_status(&n);
    tac5212_status_t c;
    const bool codec_ok = tac5212_read_status(&c) == ESP_OK;
    audio_meters_t m;
    audio_get_meters(&m);
    float vpos = 0, vneg = 0;
    const bool rails = tps65132_get_vpos(&vpos) == ESP_OK && tps65132_get_vneg(&vneg) == ESP_OK;

    static const char *sta_names[] = { "no credentials", "connecting", "connected", "failed" };

    printf("\n%s v%s - firmware %s\n", BOARD_NAME, BOARD_HW_REV, FIRMWARE_VERSION);
    printf("  access point  %s at http://%s (%d client%s)\n",
           n.ap_ssid, n.ap_ip, n.ap_clients, n.ap_clients == 1 ? "" : "s");
    printf("  station       %s", sta_names[n.sta_state]);
    if (n.sta_ssid[0]) {
        printf(" - \"%s\" %s (%d dBm)", n.sta_ssid, n.sta_ip, n.sta_rssi);
    }
    if (n.sta_ip6[0]) {
        printf("\n  IPv6          %s", n.sta_ip6);
    }
    printf("\n  mDNS          http://%s.local\n", n.hostname);
    printf("  battery       %d mV (%d %%)%s\n", battery_millivolts(), battery_percent(),
           battery_is_charging_hint() ? ", external supply" : "");
    if (rails) {
        printf("  rails         +%.1f V / -%.1f V\n", (double)vpos, (double)vneg);
    }
    printf("  PGIA          %s%s\n", pgia_gain_name(pgia_get()),
           pgia_control_available() ? ""
                                    : "  (select lines not connected - R35-R37 unfitted,"
                                      " amplifier is fixed at 16x)");
    if (codec_ok) {
        printf("  codec         %s, PLL %s, ratio %u, fs code %u, clk err %02X/%02X\n",
               tac5212_mode_name(c.mode), c.pll_locked ? "locked" : "unlocked",
               c.clk_det_ratio, c.fs_det_code, c.clk_err0, c.clk_err1);
        printf("  channels      ADC %d%d  DAC %d%d  MICBIAS %d\n",
               c.adc_ch1_on, c.adc_ch2_on, c.dac_ch1_on, c.dac_ch2_on, c.micbias_on);
    } else {
        printf("  codec         not responding\n");
    }
    printf("  audio         %" PRIu32 " Hz, decimation %u, streaming %s, %" PRIu32 " frames\n",
           audio_sample_rate(), audio_decimation(), audio_streaming() ? "on" : "off",
           m.frames_captured);
    printf("  input rms     CH1 %.4f %%FS   CH2 %.4f %%FS\n",
           (double)(m.rms_fs[0] * 100), (double)(m.rms_fs[1] * 100));
    printf("  input peak    CH1 %.4f %%FS   CH2 %.4f %%FS\n",
           (double)(m.peak_fs[0] * 100), (double)(m.peak_fs[1] * 100));
    printf("  clipping      CH1 %.2f %%      CH2 %.2f %%%s\n",
           (double)m.clip_pct[0], (double)m.clip_pct[1],
           (m.clip_pct[0] > 0.01f || m.clip_pct[1] > 0.01f) ? "   <-- INPUT OVERLOADED" : "");
    printf("  free heap     %" PRIu32 " B\n\n", (uint32_t)esp_get_free_heap_size());
}

static void cmd_scan(void)
{
    net_scan_entry_t list[NET_SCAN_MAX];
    const int n = net_scan(list, NET_SCAN_MAX);
    printf("\n  %d network%s\n", n, n == 1 ? "" : "s");
    for (int i = 0; i < n; i++) {
        printf("  %-32s ch%-3d %4d dBm %s\n", list[i].ssid, list[i].channel,
               list[i].rssi, list[i].authmode == 0 ? "open" : "secured");
    }
    printf("\n");
}

static void cmd_i2c(void)
{
    uint8_t found[16];
    const int n = i2c_bus_scan(found, sizeof(found));
    printf("  %d device%s:", n, n == 1 ? "" : "s");
    for (int i = 0; i < n; i++) {
        printf(" 0x%02X", found[i]);
    }
    printf("\n");
}

static void cmd_reg(int argc, char **argv)
{
    if (argc < 3) {
        printf("  usage: reg <page> <addr> [value]   (all hex)\n");
        return;
    }
    const uint8_t page = (uint8_t)strtol(argv[1], NULL, 16);
    const uint8_t addr = (uint8_t)strtol(argv[2], NULL, 16);

    if (argc >= 4) {
        const uint8_t val = (uint8_t)strtol(argv[3], NULL, 16);
        printf("  write p%02X r%02X = %02X: %s\n", page, addr, val,
               tac5212_write_reg(page, addr, val) == ESP_OK ? "ok" : "failed");
        return;
    }
    uint8_t val;
    if (tac5212_read_reg(page, addr, &val) == ESP_OK) {
        printf("  p%02X r%02X = 0x%02X (0b%c%c%c%c%c%c%c%c)\n", page, addr, val,
               (val & 0x80) ? '1' : '0', (val & 0x40) ? '1' : '0',
               (val & 0x20) ? '1' : '0', (val & 0x10) ? '1' : '0',
               (val & 0x08) ? '1' : '0', (val & 0x04) ? '1' : '0',
               (val & 0x02) ? '1' : '0', (val & 0x01) ? '1' : '0');
    } else {
        printf("  read failed\n");
    }
}

static void cmd_stim(int argc, char **argv)
{
    stim_config_t s;
    audio_get_stimulus(&s);
    if (argc >= 2) s.type = (stim_type_t)atoi(argv[1]);
    if (argc >= 3) s.amplitude = strtof(argv[2], NULL);
    if (argc >= 4) s.freq_hz = strtof(argv[3], NULL);
    if (s.type >= STIM_TYPE_COUNT) {
        printf("  unknown stimulus type\n");
        return;
    }
    audio_set_stimulus(&s);
    printf("  stimulus %s, amplitude %.3f, %.1f Hz\n",
           audio_stim_type_name(s.type), (double)s.amplitude, (double)s.freq_hz);
}

/* Splits on whitespace but keeps "quoted strings" together, so network names
 * with spaces can be typed as: wifi "My Phone Hotspot" mypassword */
static int tokenize(char *line, char **argv, int max_args)
{
    int argc = 0;
    char *p = line;

    while (*p && argc < max_args) {
        while (*p == ' ' || *p == '\t') {
            p++;
        }
        if (!*p) {
            break;
        }
        char end = ' ';
        if (*p == '"' || *p == '\'') {
            end = *p++;
        }
        argv[argc++] = p;
        while (*p && *p != end && !(end == ' ' && *p == '\t')) {
            p++;
        }
        if (*p) {
            *p++ = '\0';
        }
    }
    return argc;
}

static void dispatch(char *line)
{
    char *argv[CON_ARG_MAX];
    const int argc = tokenize(line, argv, CON_ARG_MAX);
    if (argc == 0) {
        return;
    }

    if (!strcmp(argv[0], "help") || !strcmp(argv[0], "?")) {
        cmd_help();
    } else if (!strcmp(argv[0], "status")) {
        cmd_status();
    } else if (!strcmp(argv[0], "wifi")) {
        if (argc < 2) {
            printf("  usage: wifi <ssid> [password]\n");
        } else {
            const esp_err_t err = net_set_sta_credentials(argv[1], argc >= 3 ? argv[2] : "");
            printf("  %s\n", err == ESP_OK ? "stored, connecting..." : esp_err_to_name(err));
        }
    } else if (!strcmp(argv[0], "wifi-forget")) {
        net_set_sta_credentials("", "");
        printf("  cleared\n");
    } else if (!strcmp(argv[0], "ap")) {
        if (argc < 2) {
            printf("  usage: ap <password>\n");
        } else {
            printf("  %s\n", net_set_ap_password(argv[1]) == ESP_OK ? "ok" : "rejected");
        }
    } else if (!strcmp(argv[0], "scan")) {
        cmd_scan();
    } else if (!strcmp(argv[0], "i2c")) {
        cmd_i2c();
    } else if (!strcmp(argv[0], "reg")) {
        cmd_reg(argc, argv);
    } else if (!strcmp(argv[0], "gain")) {
        if (argc < 2) {
            printf("  current gain %s\n", pgia_gain_name(pgia_get()));
        } else {
            pgia_set((pgia_gain_t)atoi(argv[1]));
        }
    } else if (!strcmp(argv[0], "stream")) {
        const bool on = (argc >= 2) && !strcmp(argv[1], "on");
        audio_set_streaming(on);
        printf("  streaming %s\n", on ? "on" : "off");
    } else if (!strcmp(argv[0], "stim")) {
        cmd_stim(argc, argv);
    } else if (!strcmp(argv[0], "led")) {
        status_led_set((led_pattern_t)(argc >= 2 ? atoi(argv[1]) : 0),
                       argc >= 3 ? (uint8_t)atoi(argv[2]) : status_led_brightness());
        printf("  led %s\n", status_led_pattern_name(status_led_pattern()));
    } else if (!strcmp(argv[0], "reboot")) {
        printf("  rebooting\n");
        fflush(stdout);
        vTaskDelay(pdMS_TO_TICKS(200));
        esp_restart();
    } else {
        printf("  unknown command \"%s\" - try \"help\"\n", argv[0]);
    }
}

static void console_task(void *arg)
{
    char line[CON_LINE_MAX];
    int len = 0;

    /* Give the boot log a moment so the prompt is not buried in it. */
    vTaskDelay(pdMS_TO_TICKS(1500));
    printf("\nWireless BERA console - type \"help\"\n> ");
    fflush(stdout);

    for (;;) {
        uint8_t ch;
        const int n = usb_serial_jtag_read_bytes(&ch, 1, pdMS_TO_TICKS(200));
        if (n <= 0) {
            continue;
        }
        if (ch == '\r' || ch == '\n') {
            printf("\n");
            if (len > 0) {
                line[len] = '\0';
                dispatch(line);
                len = 0;
            }
            printf("> ");
            fflush(stdout);
        } else if (ch == 0x08 || ch == 0x7F) {      /* backspace */
            if (len > 0) {
                len--;
                printf("\b \b");
                fflush(stdout);
            }
        } else if (ch >= 0x20 && len < CON_LINE_MAX - 1) {
            line[len++] = (char)ch;
            printf("%c", ch);
            fflush(stdout);
        }
    }
}

esp_err_t console_start(void)
{
    usb_serial_jtag_driver_config_t cfg = USB_SERIAL_JTAG_DRIVER_CONFIG_DEFAULT();
    cfg.rx_buffer_size = 512;
    cfg.tx_buffer_size = 2048;
    const esp_err_t err = usb_serial_jtag_driver_install(&cfg);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "USB serial driver not available: %s", esp_err_to_name(err));
        return err;
    }
    if (xTaskCreate(console_task, "console", 5120, NULL, 3, NULL) != pdPASS) {
        return ESP_ERR_NO_MEM;
    }
    return ESP_OK;
}
