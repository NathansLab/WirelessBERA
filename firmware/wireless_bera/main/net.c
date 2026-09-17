#include "net.h"

#include <stdlib.h>
#include <string.h>

#include "board.h"
#include "esp_check.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_timer.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"
#include "mdns.h"
#include "nvs.h"
#include "nvs_flash.h"

static const char *TAG = "net";

#define NVS_NAMESPACE       "wbera"
#define NVS_KEY_STA_SSID    "sta_ssid"
#define NVS_KEY_STA_PASS    "sta_pass"
#define NVS_KEY_AP_PASS     "ap_pass"

/* Factory default for the board's own access point. It is a device default,
 * not anybody's secret, and can be changed from the web UI. */
#define AP_DEFAULT_PASS     "bera1234"
#define AP_CHANNEL          6
#define AP_MAX_CLIENTS      4
#define MDNS_HOSTNAME       "wirelessbera"

#define STA_RETRY_MAX       5

static esp_netif_t *s_ap_netif;
static esp_netif_t *s_sta_netif;

static volatile net_sta_state_t s_sta_state = NET_STA_IDLE;
static char     s_ap_ssid[NET_SSID_MAX + 1];
static char     s_sta_ssid[NET_SSID_MAX + 1];
static char     s_sta_ip[16] = "0.0.0.0";
static char     s_sta_ip6[48];
static char     s_ap_ip[16] = "192.168.4.1";
static uint8_t  s_mac[6];
static int      s_sta_retries;
static esp_timer_handle_t s_reconnect_timer;

/* Reconnect from a timer rather than from the event handler: the Wi-Fi event
 * task must not be blocked by a back-off delay. */
static void reconnect_cb(void *arg)
{
    if (s_sta_ssid[0]) {
        esp_wifi_connect();
    }
}

static void schedule_reconnect(uint32_t delay_ms)
{
    if (!s_reconnect_timer) {
        const esp_timer_create_args_t args = {
            .callback = reconnect_cb,
            .name = "wifi_reconnect",
        };
        if (esp_timer_create(&args, &s_reconnect_timer) != ESP_OK) {
            return;
        }
    }
    esp_timer_stop(s_reconnect_timer);
    esp_timer_start_once(s_reconnect_timer, (uint64_t)delay_ms * 1000);
}

/* ------------------------------------------------------------------ */
/* NVS helpers                                                         */
/* ------------------------------------------------------------------ */

static esp_err_t nvs_get_str_or_empty(const char *key, char *out, size_t out_size)
{
    out[0] = '\0';
    nvs_handle_t h;
    if (nvs_open(NVS_NAMESPACE, NVS_READONLY, &h) != ESP_OK) {
        return ESP_ERR_NVS_NOT_FOUND;
    }
    size_t len = out_size;
    const esp_err_t err = nvs_get_str(h, key, out, &len);
    nvs_close(h);
    if (err != ESP_OK) {
        out[0] = '\0';
    }
    return err;
}

static esp_err_t nvs_put_str(const char *key, const char *value)
{
    nvs_handle_t h;
    ESP_RETURN_ON_ERROR(nvs_open(NVS_NAMESPACE, NVS_READWRITE, &h), TAG, "nvs_open");
    esp_err_t err = (value && value[0]) ? nvs_set_str(h, key, value) : nvs_erase_key(h, key);
    if (err == ESP_ERR_NVS_NOT_FOUND) {
        err = ESP_OK;       /* erasing something that was never stored */
    }
    if (err == ESP_OK) {
        err = nvs_commit(h);
    }
    nvs_close(h);
    return err;
}

/* ------------------------------------------------------------------ */
/* Events                                                              */
/* ------------------------------------------------------------------ */

static void on_wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    switch (id) {
    case WIFI_EVENT_STA_START:
        if (s_sta_ssid[0]) {
            s_sta_state = NET_STA_CONNECTING;
            esp_wifi_connect();
        }
        break;

    case WIFI_EVENT_STA_DISCONNECTED: {
        const wifi_event_sta_disconnected_t *e = data;
        strcpy(s_sta_ip, "0.0.0.0");
        s_sta_ip6[0] = '\0';
        if (!s_sta_ssid[0]) {
            s_sta_state = NET_STA_IDLE;
            break;
        }
        if (s_sta_retries < STA_RETRY_MAX) {
            s_sta_retries++;
            s_sta_state = NET_STA_CONNECTING;
            ESP_LOGW(TAG, "station disconnected (reason %d), retry %d/%d",
                     e->reason, s_sta_retries, STA_RETRY_MAX);
            schedule_reconnect(1000u * (uint32_t)s_sta_retries);
        } else {
            s_sta_state = NET_STA_FAILED;
            ESP_LOGE(TAG, "station gave up after %d attempts (reason %d); the "
                          "access point stays available",
                     STA_RETRY_MAX, e->reason);
        }
        break;
    }

    case WIFI_EVENT_STA_CONNECTED:
        /* An IPv6 link-local address gives a direct path to the board from any
         * host on the same segment, which matters on networks (phone hotspots,
         * guest SSIDs) that put clients in separate IPv4 NAT pools. */
        esp_netif_create_ip6_linklocal(s_sta_netif);
        break;

    case WIFI_EVENT_AP_STACONNECTED:
        ESP_LOGI(TAG, "client joined the access point");
        break;

    case WIFI_EVENT_AP_STADISCONNECTED:
        ESP_LOGI(TAG, "client left the access point");
        break;

    default:
        break;
    }
}

static void on_ip_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (id == IP_EVENT_STA_GOT_IP) {
        const ip_event_got_ip_t *e = data;
        snprintf(s_sta_ip, sizeof(s_sta_ip), IPSTR, IP2STR(&e->ip_info.ip));
        s_sta_retries = 0;
        s_sta_state = NET_STA_CONNECTED;
        ESP_LOGI(TAG, "station got IP %s on \"%s\"", s_sta_ip, s_sta_ssid);
    } else if (id == IP_EVENT_GOT_IP6) {
        const ip_event_got_ip6_t *e = data;
        snprintf(s_sta_ip6, sizeof(s_sta_ip6), IPV6STR, IPV62STR(e->ip6_info.ip));
        ESP_LOGI(TAG, "IPv6 link-local %s - reachable as http://[%s%%<iface>]/",
                 s_sta_ip6, s_sta_ip6);
    }
}

/* ------------------------------------------------------------------ */
/* Bring-up                                                            */
/* ------------------------------------------------------------------ */

static void apply_ap_config(const char *password)
{
    wifi_config_t ap = { 0 };
    strlcpy((char *)ap.ap.ssid, s_ap_ssid, sizeof(ap.ap.ssid));
    ap.ap.ssid_len = strlen(s_ap_ssid);
    ap.ap.channel = AP_CHANNEL;
    ap.ap.max_connection = AP_MAX_CLIENTS;

    if (password && strlen(password) >= 8) {
        strlcpy((char *)ap.ap.password, password, sizeof(ap.ap.password));
        ap.ap.authmode = WIFI_AUTH_WPA2_PSK;
    } else {
        ap.ap.authmode = WIFI_AUTH_OPEN;
    }
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &ap));
    ESP_LOGI(TAG, "access point \"%s\" (%s) on channel %d",
             s_ap_ssid, ap.ap.authmode == WIFI_AUTH_OPEN ? "open" : "WPA2", AP_CHANNEL);
}

static void apply_sta_config(const char *ssid, const char *password)
{
    wifi_config_t sta = { 0 };
    strlcpy((char *)sta.sta.ssid, ssid, sizeof(sta.sta.ssid));
    strlcpy((char *)sta.sta.password, password, sizeof(sta.sta.password));
    sta.sta.threshold.authmode = password[0] ? WIFI_AUTH_WPA_PSK : WIFI_AUTH_OPEN;
    sta.sta.scan_method = WIFI_ALL_CHANNEL_SCAN;
    sta.sta.sort_method = WIFI_CONNECT_AP_BY_SIGNAL;
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &sta));
}

esp_err_t net_init(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_RETURN_ON_ERROR(err, TAG, "nvs_flash_init");

    ESP_RETURN_ON_ERROR(esp_netif_init(), TAG, "netif_init");
    ESP_RETURN_ON_ERROR(esp_event_loop_create_default(), TAG, "event_loop");

    s_ap_netif = esp_netif_create_default_wifi_ap();
    s_sta_netif = esp_netif_create_default_wifi_sta();

    const wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_RETURN_ON_ERROR(esp_wifi_init(&cfg), TAG, "wifi_init");

    ESP_ERROR_CHECK(esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
                                                        on_wifi_event, NULL, NULL));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP,
                                                        on_ip_event, NULL, NULL));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(IP_EVENT, IP_EVENT_GOT_IP6,
                                                        on_ip_event, NULL, NULL));

    esp_read_mac(s_mac, ESP_MAC_WIFI_SOFTAP);
    snprintf(s_ap_ssid, sizeof(s_ap_ssid), "WirelessBERA-%02X%02X", s_mac[4], s_mac[5]);

    char ap_pass[NET_PASS_MAX + 1];
    if (nvs_get_str_or_empty(NVS_KEY_AP_PASS, ap_pass, sizeof(ap_pass)) != ESP_OK ||
        strlen(ap_pass) < 8) {
        strlcpy(ap_pass, AP_DEFAULT_PASS, sizeof(ap_pass));
    }

    char sta_pass[NET_PASS_MAX + 1] = { 0 };
    nvs_get_str_or_empty(NVS_KEY_STA_SSID, s_sta_ssid, sizeof(s_sta_ssid));
    nvs_get_str_or_empty(NVS_KEY_STA_PASS, sta_pass, sizeof(sta_pass));

    /* Set before any config is applied, so credentials are never mirrored into
     * the Wi-Fi driver's own NVS namespace - this firmware owns that storage. */
    ESP_RETURN_ON_ERROR(esp_wifi_set_storage(WIFI_STORAGE_RAM), TAG, "set_storage");
    ESP_RETURN_ON_ERROR(esp_wifi_set_mode(WIFI_MODE_APSTA), TAG, "set_mode");
    apply_ap_config(ap_pass);
    if (s_sta_ssid[0]) {
        apply_sta_config(s_sta_ssid, sta_pass);
        ESP_LOGI(TAG, "stored station credentials for \"%s\"", s_sta_ssid);
    } else {
        ESP_LOGI(TAG, "no station credentials stored - join \"%s\" and use the "
                      "Wi-Fi tab to provision", s_ap_ssid);
    }

    ESP_RETURN_ON_ERROR(esp_wifi_start(), TAG, "wifi_start");
    esp_wifi_set_ps(WIFI_PS_NONE);      /* streaming latency beats idle power */

    esp_netif_ip_info_t ip;
    if (esp_netif_get_ip_info(s_ap_netif, &ip) == ESP_OK) {
        snprintf(s_ap_ip, sizeof(s_ap_ip), IPSTR, IP2STR(&ip.ip));
    }

    if (mdns_init() == ESP_OK) {
        mdns_hostname_set(MDNS_HOSTNAME);
        mdns_instance_name_set(BOARD_NAME);
        mdns_service_add(NULL, "_http", "_tcp", 80, NULL, 0);
        ESP_LOGI(TAG, "mDNS: http://%s.local", MDNS_HOSTNAME);
    }

    ESP_LOGI(TAG, "access point ready at http://%s", s_ap_ip);
    return ESP_OK;
}

/* ------------------------------------------------------------------ */
/* Public operations                                                   */
/* ------------------------------------------------------------------ */

void net_get_status(net_status_t *out)
{
    memset(out, 0, sizeof(*out));
    strlcpy(out->ap_ssid, s_ap_ssid, sizeof(out->ap_ssid));
    strlcpy(out->ap_ip, s_ap_ip, sizeof(out->ap_ip));
    strlcpy(out->sta_ssid, s_sta_ssid, sizeof(out->sta_ssid));
    strlcpy(out->sta_ip, s_sta_ip, sizeof(out->sta_ip));
    strlcpy(out->sta_ip6, s_sta_ip6, sizeof(out->sta_ip6));
    strlcpy(out->hostname, MDNS_HOSTNAME, sizeof(out->hostname));
    memcpy(out->mac, s_mac, sizeof(out->mac));
    out->sta_state = s_sta_state;

    wifi_sta_list_t clients;
    out->ap_clients = (esp_wifi_ap_get_sta_list(&clients) == ESP_OK) ? clients.num : 0;

    wifi_ap_record_t rec;
    out->sta_rssi = (esp_wifi_sta_get_ap_info(&rec) == ESP_OK) ? rec.rssi : 0;
}

int net_scan(net_scan_entry_t *entries, int max_entries)
{
    const wifi_scan_config_t cfg = {
        .show_hidden = false,
        .scan_type = WIFI_SCAN_TYPE_ACTIVE,
        .scan_time.active = { .min = 100, .max = 200 },
    };

    esp_err_t err = esp_wifi_scan_start(&cfg, true);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "scan failed: %s", esp_err_to_name(err));
        return 0;
    }

    uint16_t found = 0;
    esp_wifi_scan_get_ap_num(&found);
    if (found == 0) {
        return 0;
    }
    if (found > NET_SCAN_MAX) {
        found = NET_SCAN_MAX;
    }

    wifi_ap_record_t *records = calloc(found, sizeof(wifi_ap_record_t));
    if (!records) {
        esp_wifi_clear_ap_list();
        return 0;
    }
    esp_wifi_scan_get_ap_records(&found, records);

    int n = 0;
    for (int i = 0; i < found && n < max_entries; i++) {
        if (records[i].ssid[0] == '\0') {
            continue;
        }
        strlcpy(entries[n].ssid, (const char *)records[i].ssid, sizeof(entries[n].ssid));
        entries[n].rssi = records[i].rssi;
        entries[n].channel = records[i].primary;
        entries[n].authmode = records[i].authmode;
        n++;
    }
    free(records);
    return n;
}

esp_err_t net_set_sta_credentials(const char *ssid, const char *password)
{
    if (!ssid) {
        return ESP_ERR_INVALID_ARG;
    }
    if (strlen(ssid) > NET_SSID_MAX || (password && strlen(password) > NET_PASS_MAX)) {
        return ESP_ERR_INVALID_SIZE;
    }

    ESP_RETURN_ON_ERROR(nvs_put_str(NVS_KEY_STA_SSID, ssid), TAG, "store ssid");
    ESP_RETURN_ON_ERROR(nvs_put_str(NVS_KEY_STA_PASS, password), TAG, "store pass");

    strlcpy(s_sta_ssid, ssid, sizeof(s_sta_ssid));
    s_sta_retries = 0;
    esp_wifi_disconnect();

    if (!ssid[0]) {
        s_sta_state = NET_STA_IDLE;
        ESP_LOGI(TAG, "station credentials cleared");
        return ESP_OK;
    }

    apply_sta_config(ssid, password ? password : "");
    s_sta_state = NET_STA_CONNECTING;
    ESP_LOGI(TAG, "connecting to \"%s\"", ssid);
    return esp_wifi_connect();
}

esp_err_t net_set_ap_password(const char *password)
{
    if (password && password[0] && strlen(password) < 8) {
        return ESP_ERR_INVALID_SIZE;    /* WPA2 needs at least 8 characters */
    }
    ESP_RETURN_ON_ERROR(nvs_put_str(NVS_KEY_AP_PASS, password), TAG, "store ap pass");
    apply_ap_config(password);
    return ESP_OK;
}
