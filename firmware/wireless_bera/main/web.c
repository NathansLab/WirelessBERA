#include "web.h"

#include <inttypes.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "audio.h"
#include "battery.h"
#include "board.h"
#include "cJSON.h"
#include "esp_app_desc.h"
#include "esp_chip_info.h"
#include "esp_check.h"
#include "esp_heap_caps.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "i2c_bus.h"
#include "net.h"
#include "pgia.h"
#include "status_led.h"
#include "tac5212.h"
#include "tps65132.h"

static const char *TAG = "web";

/* The web UI is gzip-compressed at build time and linked into the binary. */
extern const uint8_t webui_start[] asm("_binary_index_html_gz_start");
extern const uint8_t webui_end[]   asm("_binary_index_html_gz_end");

#define MAX_WS_CLIENTS      4
#define SCOPE_QUEUE_DEPTH   8
#define MAX_BODY_LEN        1024

typedef struct {
    scope_header_t hdr;
    int16_t        samples[AUDIO_SCOPE_FRAMES * AUDIO_CHANNELS];
    uint16_t       bytes;   /* payload bytes actually used */
} scope_packet_t;

static httpd_handle_t   s_server;
static QueueHandle_t    s_scope_q;
static int              s_ws_fds[MAX_WS_CLIENTS];
static SemaphoreHandle_t s_ws_lock;

/* ------------------------------------------------------------------ */
/* WebSocket client bookkeeping                                        */
/* ------------------------------------------------------------------ */

static void ws_add_client(int fd)
{
    xSemaphoreTake(s_ws_lock, portMAX_DELAY);
    for (int i = 0; i < MAX_WS_CLIENTS; i++) {
        if (s_ws_fds[i] == fd) {
            xSemaphoreGive(s_ws_lock);
            return;
        }
    }
    for (int i = 0; i < MAX_WS_CLIENTS; i++) {
        if (s_ws_fds[i] < 0) {
            s_ws_fds[i] = fd;
            break;
        }
    }
    xSemaphoreGive(s_ws_lock);
    ESP_LOGI(TAG, "websocket client %d connected", fd);
}

static void ws_remove_client(int fd)
{
    xSemaphoreTake(s_ws_lock, portMAX_DELAY);
    for (int i = 0; i < MAX_WS_CLIENTS; i++) {
        if (s_ws_fds[i] == fd) {
            s_ws_fds[i] = -1;
        }
    }
    xSemaphoreGive(s_ws_lock);
}

static void ws_broadcast(httpd_ws_type_t type, const uint8_t *payload, size_t len)
{
    int fds[MAX_WS_CLIENTS];
    xSemaphoreTake(s_ws_lock, portMAX_DELAY);
    memcpy(fds, s_ws_fds, sizeof(fds));
    xSemaphoreGive(s_ws_lock);

    httpd_ws_frame_t frame = {
        .final = true,
        .type = type,
        .payload = (uint8_t *)payload,
        .len = len,
    };

    for (int i = 0; i < MAX_WS_CLIENTS; i++) {
        if (fds[i] < 0) {
            continue;
        }
        if (httpd_ws_send_frame_async(s_server, fds[i], &frame) != ESP_OK) {
            ws_remove_client(fds[i]);
        }
    }
}

/* ------------------------------------------------------------------ */
/* Status document                                                     */
/* ------------------------------------------------------------------ */

static cJSON *build_status(void)
{
    cJSON *root = cJSON_CreateObject();

    /* -- system ------------------------------------------------------ */
    {
        cJSON *sys = cJSON_AddObjectToObject(root, "system");
        const esp_app_desc_t *app = esp_app_get_description();
        esp_chip_info_t chip;
        esp_chip_info(&chip);

        cJSON_AddStringToObject(sys, "board", BOARD_NAME " v" BOARD_HW_REV);
        cJSON_AddStringToObject(sys, "firmware", FIRMWARE_VERSION);
        cJSON_AddStringToObject(sys, "idf", app->idf_ver);
        cJSON_AddStringToObject(sys, "build", app->date);
        cJSON_AddNumberToObject(sys, "cores", chip.cores);
        cJSON_AddNumberToObject(sys, "uptime_s", (double)(esp_timer_get_time() / 1000000));
        cJSON_AddNumberToObject(sys, "heap_free", heap_caps_get_free_size(MALLOC_CAP_INTERNAL));
        cJSON_AddNumberToObject(sys, "heap_min", heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL));
        cJSON_AddNumberToObject(sys, "psram_free", heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
        cJSON_AddNumberToObject(sys, "psram_total", heap_caps_get_total_size(MALLOC_CAP_SPIRAM));
    }

    /* -- network ----------------------------------------------------- */
    {
        net_status_t n;
        net_get_status(&n);
        cJSON *net = cJSON_AddObjectToObject(root, "net");
        cJSON_AddStringToObject(net, "ap_ssid", n.ap_ssid);
        cJSON_AddStringToObject(net, "ap_ip", n.ap_ip);
        cJSON_AddNumberToObject(net, "ap_clients", n.ap_clients);
        cJSON_AddNumberToObject(net, "sta_state", n.sta_state);
        cJSON_AddStringToObject(net, "sta_ssid", n.sta_ssid);
        cJSON_AddStringToObject(net, "sta_ip", n.sta_ip);
        cJSON_AddStringToObject(net, "sta_ip6", n.sta_ip6);
        cJSON_AddNumberToObject(net, "sta_rssi", n.sta_rssi);
        cJSON_AddStringToObject(net, "hostname", n.hostname);

        char mac[18];
        snprintf(mac, sizeof(mac), "%02X:%02X:%02X:%02X:%02X:%02X",
                 n.mac[0], n.mac[1], n.mac[2], n.mac[3], n.mac[4], n.mac[5]);
        cJSON_AddStringToObject(net, "mac", mac);
    }

    /* -- power ------------------------------------------------------- */
    {
        cJSON *pwr = cJSON_AddObjectToObject(root, "power");
        cJSON_AddNumberToObject(pwr, "vbat_mv", battery_millivolts());
        cJSON_AddNumberToObject(pwr, "vbat_pct", battery_percent());
        cJSON_AddBoolToObject(pwr, "external", battery_is_charging_hint());

        float vpos = 0, vneg = 0;
        const bool rails = (tps65132_get_vpos(&vpos) == ESP_OK) &&
                           (tps65132_get_vneg(&vneg) == ESP_OK);
        cJSON_AddBoolToObject(pwr, "rails_present", rails);
        cJSON_AddNumberToObject(pwr, "vpos", vpos);
        cJSON_AddNumberToObject(pwr, "vneg", vneg);
    }

    /* -- codec ------------------------------------------------------- */
    {
        tac5212_status_t st;
        cJSON *c = cJSON_AddObjectToObject(root, "codec");
        if (tac5212_read_status(&st) == ESP_OK) {
            cJSON_AddBoolToObject(c, "present", true);
            cJSON_AddNumberToObject(c, "mode", st.mode);
            cJSON_AddStringToObject(c, "mode_name", tac5212_mode_name(st.mode));
            cJSON_AddBoolToObject(c, "pll", st.pll_locked);
            cJSON_AddBoolToObject(c, "micbias", st.micbias_on);
            cJSON_AddBoolToObject(c, "adc1", st.adc_ch1_on);
            cJSON_AddBoolToObject(c, "adc2", st.adc_ch2_on);
            cJSON_AddBoolToObject(c, "dac1", st.dac_ch1_on);
            cJSON_AddBoolToObject(c, "dac2", st.dac_ch2_on);
            cJSON_AddNumberToObject(c, "clk_err0", st.clk_err0);
            cJSON_AddNumberToObject(c, "clk_err1", st.clk_err1);
            cJSON_AddNumberToObject(c, "bclk_ratio", st.clk_det_ratio);
        } else {
            cJSON_AddBoolToObject(c, "present", false);
        }
        cJSON_AddNumberToObject(c, "adc_vol1", tac5212_get_adc_volume_db(1));
        cJSON_AddNumberToObject(c, "adc_vol2", tac5212_get_adc_volume_db(2));
        cJSON_AddNumberToObject(c, "dac_vol1", tac5212_get_dac_volume_db(1));
        cJSON_AddNumberToObject(c, "dac_vol2", tac5212_get_dac_volume_db(2));
        cJSON_AddNumberToObject(c, "drive", tac5212_get_output_drive());

        uint16_t avdd_code = 0;
        float avdd_v = 0;
        if (tac5212_read_avdd(&avdd_code, &avdd_v) == ESP_OK) {
            cJSON_AddNumberToObject(c, "avdd", avdd_v);
            cJSON_AddNumberToObject(c, "avdd_code", avdd_code);
        }
    }

    /* -- audio ------------------------------------------------------- */
    {
        audio_meters_t m;
        audio_get_meters(&m);
        cJSON *a = cJSON_AddObjectToObject(root, "audio");
        cJSON_AddNumberToObject(a, "sample_rate", audio_sample_rate());
        cJSON_AddNumberToObject(a, "decimation", audio_decimation());
        cJSON_AddBoolToObject(a, "streaming", audio_streaming());
        cJSON_AddNumberToObject(a, "frames", m.frames_captured);

        cJSON *rms = cJSON_AddArrayToObject(a, "rms");
        cJSON *peak = cJSON_AddArrayToObject(a, "peak");
        cJSON *dc = cJSON_AddArrayToObject(a, "dc");
        cJSON *clip = cJSON_AddArrayToObject(a, "clip");
        cJSON *clip_total = cJSON_AddArrayToObject(a, "clip_total");
        for (int i = 0; i < AUDIO_CHANNELS; i++) {
            cJSON_AddItemToArray(rms, cJSON_CreateNumber(m.rms_fs[i]));
            cJSON_AddItemToArray(peak, cJSON_CreateNumber(m.peak_fs[i]));
            cJSON_AddItemToArray(dc, cJSON_CreateNumber(m.dc_fs[i]));
            cJSON_AddItemToArray(clip, cJSON_CreateNumber(m.clip_pct[i]));
            cJSON_AddItemToArray(clip_total, cJSON_CreateNumber(m.clip_total[i]));
        }
        cJSON_AddNumberToObject(a, "fullscale_vrms_ch1", tac5212_adc_fullscale_vrms(1));
        cJSON_AddNumberToObject(a, "fullscale_vrms_ch2", tac5212_adc_fullscale_vrms(2));
    }

    /* -- stimulus ---------------------------------------------------- */
    {
        stim_config_t s;
        audio_get_stimulus(&s);
        cJSON *st = cJSON_AddObjectToObject(root, "stimulus");
        cJSON_AddNumberToObject(st, "type", s.type);
        cJSON_AddStringToObject(st, "type_name", audio_stim_type_name(s.type));
        cJSON_AddNumberToObject(st, "amplitude", s.amplitude);
        cJSON_AddNumberToObject(st, "freq_hz", s.freq_hz);
        cJSON_AddNumberToObject(st, "freq2_hz", s.freq2_hz);
        cJSON_AddNumberToObject(st, "rate_hz", s.rate_hz);
        cJSON_AddNumberToObject(st, "width_us", s.width_us);
        cJSON_AddNumberToObject(st, "burst_ms", s.burst_ms);
        cJSON_AddNumberToObject(st, "polarity", s.polarity);
        cJSON_AddBoolToObject(st, "ch1", s.ch1_enable);
        cJSON_AddBoolToObject(st, "ch2", s.ch2_enable);
    }

    /* -- analog front end -------------------------------------------- */
    {
        cJSON *fe = cJSON_AddObjectToObject(root, "afe");
        cJSON_AddNumberToObject(fe, "gain", pgia_get());
        cJSON_AddStringToObject(fe, "gain_name", pgia_gain_name(pgia_get()));
        cJSON_AddNumberToObject(fe, "gain_value", pgia_gain_value(pgia_get()));
        cJSON_AddBoolToObject(fe, "gain_control", pgia_control_available());
        cJSON_AddNumberToObject(fe, "gain_effective", pgia_effective_gain_value());
        cJSON_AddNumberToObject(fe, "vocm", BOARD_PGIA_VOCM_V);
    }

    /* -- led --------------------------------------------------------- */
    {
        cJSON *led = cJSON_AddObjectToObject(root, "led");
        cJSON_AddNumberToObject(led, "pattern", status_led_pattern());
        cJSON_AddStringToObject(led, "pattern_name", status_led_pattern_name(status_led_pattern()));
        cJSON_AddNumberToObject(led, "brightness", status_led_brightness());
    }

    return root;
}

/* ------------------------------------------------------------------ */
/* Small HTTP helpers                                                  */
/* ------------------------------------------------------------------ */

static esp_err_t send_json(httpd_req_t *req, cJSON *doc)
{
    char *text = cJSON_PrintUnformatted(doc);
    cJSON_Delete(doc);
    if (!text) {
        return httpd_resp_send_500(req);
    }
    httpd_resp_set_type(req, "application/json");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    const esp_err_t err = httpd_resp_sendstr(req, text);
    free(text);
    return err;
}

static esp_err_t send_result(httpd_req_t *req, esp_err_t status, const char *message)
{
    cJSON *doc = cJSON_CreateObject();
    cJSON_AddBoolToObject(doc, "ok", status == ESP_OK);
    if (status != ESP_OK) {
        cJSON_AddStringToObject(doc, "error", message ? message : esp_err_to_name(status));
    }
    return send_json(req, doc);
}

/* Reads the request body and parses it as JSON. Caller owns the result. */
static cJSON *read_body_json(httpd_req_t *req)
{
    if (req->content_len <= 0 || req->content_len > MAX_BODY_LEN) {
        return NULL;
    }
    char *buf = malloc(req->content_len + 1);
    if (!buf) {
        return NULL;
    }
    int got = 0;
    while (got < req->content_len) {
        const int n = httpd_req_recv(req, buf + got, req->content_len - got);
        if (n <= 0) {
            free(buf);
            return NULL;
        }
        got += n;
    }
    buf[got] = '\0';
    cJSON *doc = cJSON_Parse(buf);
    free(buf);
    return doc;
}

static bool json_num(const cJSON *o, const char *key, double *out)
{
    const cJSON *i = cJSON_GetObjectItemCaseSensitive(o, key);
    if (cJSON_IsNumber(i)) {
        *out = i->valuedouble;
        return true;
    }
    return false;
}

static bool json_bool(const cJSON *o, const char *key, bool *out)
{
    const cJSON *i = cJSON_GetObjectItemCaseSensitive(o, key);
    if (cJSON_IsBool(i)) {
        *out = cJSON_IsTrue(i);
        return true;
    }
    return false;
}

static const char *json_str(const cJSON *o, const char *key)
{
    const cJSON *i = cJSON_GetObjectItemCaseSensitive(o, key);
    return cJSON_IsString(i) ? i->valuestring : NULL;
}

/* ------------------------------------------------------------------ */
/* Handlers                                                            */
/* ------------------------------------------------------------------ */

static esp_err_t h_root(httpd_req_t *req)
{
    httpd_resp_set_type(req, "text/html");
    httpd_resp_set_hdr(req, "Content-Encoding", "gzip");
    return httpd_resp_send(req, (const char *)webui_start, webui_end - webui_start);
}

static esp_err_t h_status(httpd_req_t *req)
{
    return send_json(req, build_status());
}

static esp_err_t h_i2c_scan(httpd_req_t *req)
{
    uint8_t found[16];
    const int n = i2c_bus_scan(found, sizeof(found));

    cJSON *doc = cJSON_CreateObject();
    cJSON *arr = cJSON_AddArrayToObject(doc, "addresses");
    for (int i = 0; i < n; i++) {
        cJSON_AddItemToArray(arr, cJSON_CreateNumber(found[i]));
    }
    return send_json(req, doc);
}

static esp_err_t h_codec_regs(httpd_req_t *req)
{
    int page = 0;
    char query[32];
    if (httpd_req_get_url_query_str(req, query, sizeof(query)) == ESP_OK) {
        char val[8];
        if (httpd_query_key_value(query, "page", val, sizeof(val)) == ESP_OK) {
            page = atoi(val);
        }
    }

    uint8_t regs[128];
    if (tac5212_dump_page((uint8_t)page, regs) != ESP_OK) {
        return send_result(req, ESP_FAIL, "codec did not respond");
    }

    cJSON *doc = cJSON_CreateObject();
    cJSON_AddNumberToObject(doc, "page", page);
    cJSON *arr = cJSON_AddArrayToObject(doc, "values");
    for (int i = 0; i < 128; i++) {
        cJSON_AddItemToArray(arr, cJSON_CreateNumber(regs[i]));
    }
    return send_json(req, doc);
}

static esp_err_t h_codec_reg_write(httpd_req_t *req)
{
    cJSON *doc = read_body_json(req);
    if (!doc) {
        return send_result(req, ESP_ERR_INVALID_ARG, "malformed body");
    }
    double page = 0, reg = 0, value = 0;
    esp_err_t err = ESP_ERR_INVALID_ARG;
    if (json_num(doc, "reg", &reg) && json_num(doc, "value", &value)) {
        json_num(doc, "page", &page);
        err = tac5212_write_reg((uint8_t)page, (uint8_t)reg, (uint8_t)value);
    }
    cJSON_Delete(doc);
    return send_result(req, err, "write failed");
}

static esp_err_t h_codec(httpd_req_t *req)
{
    cJSON *doc = read_body_json(req);
    if (!doc) {
        return send_result(req, ESP_ERR_INVALID_ARG, "malformed body");
    }

    double d;
    bool b;

    if (json_num(doc, "adc_vol1", &d)) tac5212_set_adc_volume_db(1, (float)d, false);
    if (json_num(doc, "adc_vol2", &d)) tac5212_set_adc_volume_db(2, (float)d, false);
    if (json_num(doc, "dac_vol1", &d)) tac5212_set_dac_volume_db(1, (float)d, false);
    if (json_num(doc, "dac_vol2", &d)) tac5212_set_dac_volume_db(2, (float)d, false);
    if (json_num(doc, "drive", &d))    tac5212_set_output_drive((tac_drive_t)(int)d);

    /* Front-end: {"afe1":{"imp":1,"cm":1,"fs":0}} */
    for (int ch = 1; ch <= 2; ch++) {
        char key[8];
        snprintf(key, sizeof(key), "afe%d", ch);
        const cJSON *fe = cJSON_GetObjectItemCaseSensitive(doc, key);
        if (cJSON_IsObject(fe)) {
            double imp = 1, cm = 1, fs = 0;
            json_num(fe, "imp", &imp);
            json_num(fe, "cm", &cm);
            json_num(fe, "fs", &fs);
            tac5212_set_adc_frontend(ch, (uint8_t)imp, (uint8_t)cm, (uint8_t)fs);
        }
    }

    const cJSON *power = cJSON_GetObjectItemCaseSensitive(doc, "power");
    if (cJSON_IsObject(power)) {
        bool adc = true, dac = true, mic = true;
        json_bool(power, "adc", &adc);
        json_bool(power, "dac", &dac);
        json_bool(power, "micbias", &mic);
        tac5212_set_power(adc, dac, mic);
    }

    const cJSON *chan = cJSON_GetObjectItemCaseSensitive(doc, "channels");
    if (cJSON_IsObject(chan)) {
        bool a1 = true, a2 = true, d1 = true, d2 = true;
        json_bool(chan, "adc1", &a1);
        json_bool(chan, "adc2", &a2);
        json_bool(chan, "dac1", &d1);
        json_bool(chan, "dac2", &d2);
        tac5212_set_channels(a1, a2, d1, d2);
    }

    if (json_bool(doc, "dac_mute", &b)) {
        tac5212_set_dac_volume_db(1, tac5212_get_dac_volume_db(1), b);
        tac5212_set_dac_volume_db(2, tac5212_get_dac_volume_db(2), b);
    }

    cJSON_Delete(doc);
    return send_result(req, ESP_OK, NULL);
}

static esp_err_t h_audio(httpd_req_t *req)
{
    cJSON *doc = read_body_json(req);
    if (!doc) {
        return send_result(req, ESP_ERR_INVALID_ARG, "malformed body");
    }

    double d;
    bool b;
    esp_err_t err = ESP_OK;

    if (json_num(doc, "decimation", &d)) {
        err = audio_set_decimation((uint16_t)d);
    }
    if (json_bool(doc, "streaming", &b)) {
        audio_set_streaming(b);
        status_led_set(b ? LED_HEARTBEAT : LED_BREATHE, status_led_brightness());
    }
    if (err == ESP_OK && json_num(doc, "sample_rate", &d) && (uint32_t)d != audio_sample_rate()) {
        const uint32_t fs = (uint32_t)d;
        err = audio_set_sample_rate(fs);
        if (err == ESP_OK) {
            /* The codec locks its PLL to BCLK, so it has to be re-taught the
             * new rate after the I2S peripheral restarts. */
            vTaskDelay(pdMS_TO_TICKS(50));
            err = tac5212_configure(fs, AUDIO_SLOT_BITS);
        }
    }

    cJSON_Delete(doc);
    return send_result(req, err, "audio reconfiguration failed");
}

static esp_err_t h_stimulus(httpd_req_t *req)
{
    cJSON *doc = read_body_json(req);
    if (!doc) {
        return send_result(req, ESP_ERR_INVALID_ARG, "malformed body");
    }

    stim_config_t s;
    audio_get_stimulus(&s);

    double d;
    bool b;
    if (json_num(doc, "type", &d) && d >= 0 && d < STIM_TYPE_COUNT) s.type = (stim_type_t)(int)d;
    if (json_num(doc, "amplitude", &d))  s.amplitude = (float)d;
    if (json_num(doc, "freq_hz", &d))    s.freq_hz = (float)d;
    if (json_num(doc, "freq2_hz", &d))   s.freq2_hz = (float)d;
    if (json_num(doc, "rate_hz", &d))    s.rate_hz = (float)d;
    if (json_num(doc, "width_us", &d))   s.width_us = (float)d;
    if (json_num(doc, "burst_ms", &d))   s.burst_ms = (float)d;
    if (json_num(doc, "polarity", &d))   s.polarity = (stim_polarity_t)(int)d;
    if (json_bool(doc, "ch1", &b))       s.ch1_enable = b;
    if (json_bool(doc, "ch2", &b))       s.ch2_enable = b;

    audio_set_stimulus(&s);
    cJSON_Delete(doc);
    return send_result(req, ESP_OK, NULL);
}

static esp_err_t h_pgia(httpd_req_t *req)
{
    cJSON *doc = read_body_json(req);
    if (!doc) {
        return send_result(req, ESP_ERR_INVALID_ARG, "malformed body");
    }
    double d;
    esp_err_t err = ESP_ERR_INVALID_ARG;
    if (json_num(doc, "gain", &d)) {
        err = pgia_set((pgia_gain_t)(int)d);
    }
    cJSON_Delete(doc);
    return send_result(req, err, "invalid gain index");
}

static esp_err_t h_rails(httpd_req_t *req)
{
    cJSON *doc = read_body_json(req);
    if (!doc) {
        return send_result(req, ESP_ERR_INVALID_ARG, "malformed body");
    }
    double d;
    esp_err_t err = ESP_OK;
    if (json_num(doc, "vpos", &d)) err = tps65132_set_vpos((float)d);
    if (err == ESP_OK && json_num(doc, "vneg", &d)) err = tps65132_set_vneg((float)d);
    cJSON_Delete(doc);
    return send_result(req, err, "rail setting rejected (4.0 - 6.0 V)");
}

static esp_err_t h_led(httpd_req_t *req)
{
    cJSON *doc = read_body_json(req);
    if (!doc) {
        return send_result(req, ESP_ERR_INVALID_ARG, "malformed body");
    }
    double pattern = status_led_pattern();
    double brightness = status_led_brightness();
    json_num(doc, "pattern", &pattern);
    json_num(doc, "brightness", &brightness);
    status_led_set((led_pattern_t)(int)pattern, (uint8_t)brightness);
    cJSON_Delete(doc);
    return send_result(req, ESP_OK, NULL);
}

static esp_err_t h_wifi_scan(httpd_req_t *req)
{
    net_scan_entry_t entries[NET_SCAN_MAX];
    const int n = net_scan(entries, NET_SCAN_MAX);

    cJSON *doc = cJSON_CreateObject();
    cJSON *arr = cJSON_AddArrayToObject(doc, "networks");
    for (int i = 0; i < n; i++) {
        cJSON *e = cJSON_CreateObject();
        cJSON_AddStringToObject(e, "ssid", entries[i].ssid);
        cJSON_AddNumberToObject(e, "rssi", entries[i].rssi);
        cJSON_AddNumberToObject(e, "channel", entries[i].channel);
        cJSON_AddBoolToObject(e, "open", entries[i].authmode == 0);
        cJSON_AddItemToArray(arr, e);
    }
    return send_json(req, doc);
}

static esp_err_t h_wifi_sta(httpd_req_t *req)
{
    cJSON *doc = read_body_json(req);
    if (!doc) {
        return send_result(req, ESP_ERR_INVALID_ARG, "malformed body");
    }
    const char *ssid = json_str(doc, "ssid");
    const char *pass = json_str(doc, "password");
    const esp_err_t err = net_set_sta_credentials(ssid ? ssid : "", pass ? pass : "");
    cJSON_Delete(doc);
    return send_result(req, err, "could not store credentials");
}

static esp_err_t h_wifi_ap(httpd_req_t *req)
{
    cJSON *doc = read_body_json(req);
    if (!doc) {
        return send_result(req, ESP_ERR_INVALID_ARG, "malformed body");
    }
    const char *pass = json_str(doc, "password");
    const esp_err_t err = net_set_ap_password(pass ? pass : "");
    cJSON_Delete(doc);
    return send_result(req, err, "password must be empty or at least 8 characters");
}

static void reboot_cb(void *arg)
{
    esp_restart();
}

static esp_err_t h_reboot(httpd_req_t *req)
{
    const esp_err_t err = send_result(req, ESP_OK, NULL);
    const esp_timer_create_args_t args = { .callback = reboot_cb, .name = "reboot" };
    esp_timer_handle_t t;
    if (esp_timer_create(&args, &t) == ESP_OK) {
        esp_timer_start_once(t, 500000);    /* let the response flush first */
    }
    return err;
}

/* ------------------------------------------------------------------ */
/* WebSocket                                                           */
/* ------------------------------------------------------------------ */

static esp_err_t h_ws(httpd_req_t *req)
{
    if (req->method == HTTP_GET) {
        ws_add_client(httpd_req_to_sockfd(req));
        return ESP_OK;
    }

    /* Control happens over REST, so anything a client sends is drained and
     * ignored - but it must be drained, or the framing desynchronises. */
    httpd_ws_frame_t frame = { .type = HTTPD_WS_TYPE_TEXT };
    esp_err_t err = httpd_ws_recv_frame(req, &frame, 0);
    if (err != ESP_OK) {
        return err;
    }
    if (frame.len == 0) {
        return ESP_OK;
    }
    uint8_t *buf = malloc(frame.len + 1);
    if (!buf) {
        return ESP_ERR_NO_MEM;
    }
    frame.payload = buf;
    err = httpd_ws_recv_frame(req, &frame, frame.len);
    free(buf);
    return err;
}

static void ws_close_fn(httpd_handle_t hd, int sockfd)
{
    ws_remove_client(sockfd);
    close(sockfd);
}

/* Sends queued scope packets and a 1 Hz status push. Doing both from one
 * task keeps all WebSocket writes serialised. */
static void ws_tx_task(void *arg)
{
    scope_packet_t *pkt = malloc(sizeof(scope_packet_t));
    if (!pkt) {
        vTaskDelete(NULL);
        return;
    }
    static uint8_t frame[sizeof(scope_header_t) + sizeof(pkt->samples)];
    int64_t next_status_us = 0;

    for (;;) {
        if (xQueueReceive(s_scope_q, pkt, pdMS_TO_TICKS(100)) == pdTRUE) {
            memcpy(frame, &pkt->hdr, sizeof(scope_header_t));
            memcpy(frame + sizeof(scope_header_t), pkt->samples, pkt->bytes);
            ws_broadcast(HTTPD_WS_TYPE_BINARY, frame, sizeof(scope_header_t) + pkt->bytes);
        }

        const int64_t now = esp_timer_get_time();
        if (now >= next_status_us) {
            next_status_us = now + 1000000;
            bool any = false;
            xSemaphoreTake(s_ws_lock, portMAX_DELAY);
            for (int i = 0; i < MAX_WS_CLIENTS; i++) {
                any |= (s_ws_fds[i] >= 0);
            }
            xSemaphoreGive(s_ws_lock);
            if (any) {
                cJSON *doc = build_status();
                char *text = cJSON_PrintUnformatted(doc);
                cJSON_Delete(doc);
                if (text) {
                    ws_broadcast(HTTPD_WS_TYPE_TEXT, (const uint8_t *)text, strlen(text));
                    free(text);
                }
            }
        }
    }
}

void web_publish_scope(const scope_header_t *hdr, const int16_t *samples, size_t count)
{
    if (!s_scope_q) {
        return;
    }
    scope_packet_t pkt;
    pkt.hdr = *hdr;
    pkt.bytes = (uint16_t)(count * sizeof(int16_t));
    if (pkt.bytes > sizeof(pkt.samples)) {
        pkt.bytes = sizeof(pkt.samples);
    }
    memcpy(pkt.samples, samples, pkt.bytes);

    /* Never block the audio task: if the network cannot keep up, drop. */
    if (xQueueSend(s_scope_q, &pkt, 0) != pdTRUE) {
        static uint32_t dropped;
        if ((++dropped % 200) == 1) {
            ESP_LOGW(TAG, "scope queue full, dropped %" PRIu32 " packets", dropped);
        }
    }
}

/* ------------------------------------------------------------------ */
/* Start                                                               */
/* ------------------------------------------------------------------ */

static void register_uri(const char *path, httpd_method_t method, esp_err_t (*fn)(httpd_req_t *))
{
    const httpd_uri_t uri = { .uri = path, .method = method, .handler = fn };
    ESP_ERROR_CHECK(httpd_register_uri_handler(s_server, &uri));
}

esp_err_t web_start(void)
{
    for (int i = 0; i < MAX_WS_CLIENTS; i++) {
        s_ws_fds[i] = -1;
    }
    s_ws_lock = xSemaphoreCreateMutex();
    s_scope_q = xQueueCreate(SCOPE_QUEUE_DEPTH, sizeof(scope_packet_t));
    if (!s_ws_lock || !s_scope_q) {
        return ESP_ERR_NO_MEM;
    }

    httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
    cfg.max_uri_handlers = 20;
    cfg.max_open_sockets = 7;
    cfg.stack_size = 8192;
    cfg.lru_purge_enable = true;
    cfg.close_fn = ws_close_fn;
    cfg.uri_match_fn = httpd_uri_match_wildcard;

    ESP_RETURN_ON_ERROR(httpd_start(&s_server, &cfg), TAG, "httpd_start");

    register_uri("/",                  HTTP_GET,  h_root);
    register_uri("/api/status",        HTTP_GET,  h_status);
    register_uri("/api/i2c/scan",      HTTP_GET,  h_i2c_scan);
    register_uri("/api/codec/regs",    HTTP_GET,  h_codec_regs);
    register_uri("/api/codec/reg",     HTTP_POST, h_codec_reg_write);
    register_uri("/api/codec",         HTTP_POST, h_codec);
    register_uri("/api/audio",         HTTP_POST, h_audio);
    register_uri("/api/stimulus",      HTTP_POST, h_stimulus);
    register_uri("/api/pgia",          HTTP_POST, h_pgia);
    register_uri("/api/rails",         HTTP_POST, h_rails);
    register_uri("/api/led",           HTTP_POST, h_led);
    register_uri("/api/wifi/scan",     HTTP_GET,  h_wifi_scan);
    register_uri("/api/wifi/sta",      HTTP_POST, h_wifi_sta);
    register_uri("/api/wifi/ap",       HTTP_POST, h_wifi_ap);
    register_uri("/api/system/reboot", HTTP_POST, h_reboot);

    const httpd_uri_t ws = {
        .uri = "/ws",
        .method = HTTP_GET,
        .handler = h_ws,
        .is_websocket = true,
        /* Left false so the server answers PING with PONG itself; disconnects
         * are picked up by ws_close_fn. */
        .handle_ws_control_frames = false,
    };
    ESP_ERROR_CHECK(httpd_register_uri_handler(s_server, &ws));

    if (xTaskCreate(ws_tx_task, "ws_tx", 6144, NULL, 4, NULL) != pdPASS) {
        return ESP_ERR_NO_MEM;
    }

    ESP_LOGI(TAG, "HTTP server listening on port 80 (%d bytes of web UI)",
             (int)(webui_end - webui_start));
    return ESP_OK;
}
