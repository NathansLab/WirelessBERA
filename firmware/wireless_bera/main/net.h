/*
 * net.h - Wi-Fi provisioning and connectivity.
 *
 * The board always brings up its own access point so it can be reached
 * standalone, and simultaneously joins a normal network whenever station
 * credentials have been stored. Credentials live in NVS only - nothing is
 * ever compiled into the binary, so the repository stays free of secrets.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

#define NET_SSID_MAX        32
#define NET_PASS_MAX        64
#define NET_SCAN_MAX        24

typedef enum {
    NET_STA_IDLE = 0,       /* no credentials stored        */
    NET_STA_CONNECTING,
    NET_STA_CONNECTED,
    NET_STA_FAILED,         /* credentials rejected / AP out of range */
} net_sta_state_t;

typedef struct {
    char    ssid[NET_SSID_MAX + 1];
    int8_t  rssi;
    uint8_t channel;
    uint8_t authmode;       /* wifi_auth_mode_t */
} net_scan_entry_t;

typedef struct {
    char            ap_ssid[NET_SSID_MAX + 1];
    char            ap_ip[16];
    int             ap_clients;
    net_sta_state_t sta_state;
    char            sta_ssid[NET_SSID_MAX + 1];
    char            sta_ip[16];
    char            sta_ip6[48];    /* link-local, reachable from the same L2 */
    int8_t          sta_rssi;
    char            hostname[32];
    uint8_t         mac[6];
} net_status_t;

/* Brings up NVS, netif, the soft AP and (if stored) the station. */
esp_err_t net_init(void);

void net_get_status(net_status_t *out);

/* Blocking scan; returns the number of entries written. */
int net_scan(net_scan_entry_t *entries, int max_entries);

/* Stores credentials in NVS and (re)connects. Pass an empty ssid to forget. */
esp_err_t net_set_sta_credentials(const char *ssid, const char *password);

/* Changes the access point password (>= 8 characters, or empty for open). */
esp_err_t net_set_ap_password(const char *password);

#ifdef __cplusplus
}
#endif
