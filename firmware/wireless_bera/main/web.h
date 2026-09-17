/*
 * web.h - HTTP + WebSocket control surface.
 *
 *   GET  /                    single-page web UI (gzip, served from flash)
 *   GET  /api/status          everything the UI shows, as one JSON document
 *   GET  /api/i2c/scan        addresses that ACK on the control bus
 *   GET  /api/codec/regs      ?page=N -> 128 register values
 *   POST /api/codec/reg       {page, reg, value}
 *   POST /api/codec           volumes, front-end, power, channel enables
 *   POST /api/audio           {sample_rate, streaming, decimation}
 *   POST /api/stimulus        DAC signal generator settings
 *   POST /api/pgia            {gain}
 *   POST /api/rails           {vpos, vneg}
 *   POST /api/led             {pattern, brightness}
 *   GET  /api/wifi/scan       nearby networks
 *   POST /api/wifi/sta        {ssid, password}  (stored in NVS)
 *   POST /api/wifi/ap         {password}
 *   POST /api/system/reboot
 *   WS   /ws                  binary scope packets + 1 Hz status pushes
 */
#pragma once

#include "esp_err.h"
#include "audio.h"

#ifdef __cplusplus
extern "C" {
#endif

esp_err_t web_start(void);

/* Registered as the audio scope sink; queues one packet for the sender task. */
void web_publish_scope(const scope_header_t *hdr, const int16_t *samples, size_t count);

#ifdef __cplusplus
}
#endif
