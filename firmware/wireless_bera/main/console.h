/*
 * console.h - line-oriented command interface on the USB-Serial/JTAG port.
 *
 * This exists so that a board fresh from the bench can be provisioned and
 * inspected without first having to join its access point - useful during
 * bring-up and when the Wi-Fi side is what you are debugging. Type "help".
 */
#pragma once

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

esp_err_t console_start(void);

#ifdef __cplusplus
}
#endif
