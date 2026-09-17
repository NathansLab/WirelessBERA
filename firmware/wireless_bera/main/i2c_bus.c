#include "i2c_bus.h"

#include <string.h>

#include "board.h"
#include "driver/i2c.h"
#include "esp_check.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

static const char *TAG = "i2c";

#define I2C_TIMEOUT pdMS_TO_TICKS(100)

static SemaphoreHandle_t s_lock;

esp_err_t i2c_bus_init(void)
{
    if (s_lock) {
        return ESP_OK;
    }

    const i2c_config_t cfg = {
        .mode = I2C_MODE_MASTER,
        .sda_io_num = BOARD_I2C_SDA_GPIO,
        .scl_io_num = BOARD_I2C_SCL_GPIO,
        /* R30/R31 provide 10 k external pull-ups; the weak internal ones
         * would only slow the edges down. */
        .sda_pullup_en = GPIO_PULLUP_DISABLE,
        .scl_pullup_en = GPIO_PULLUP_DISABLE,
        .master.clk_speed = BOARD_I2C_HZ,
    };

    ESP_RETURN_ON_ERROR(i2c_param_config(BOARD_I2C_PORT, &cfg), TAG, "param_config");
    ESP_RETURN_ON_ERROR(i2c_driver_install(BOARD_I2C_PORT, I2C_MODE_MASTER, 0, 0, 0), TAG, "driver_install");

    s_lock = xSemaphoreCreateMutex();
    if (!s_lock) {
        i2c_driver_delete(BOARD_I2C_PORT);
        return ESP_ERR_NO_MEM;
    }

    ESP_LOGI(TAG, "bus up: SDA=%d SCL=%d %d Hz",
             BOARD_I2C_SDA_GPIO, BOARD_I2C_SCL_GPIO, BOARD_I2C_HZ);
    return ESP_OK;
}

esp_err_t i2c_bus_write_u8(uint8_t dev_addr, uint8_t reg, uint8_t val)
{
    const uint8_t buf[2] = { reg, val };
    xSemaphoreTake(s_lock, portMAX_DELAY);
    esp_err_t err = i2c_master_write_to_device(BOARD_I2C_PORT, dev_addr, buf, sizeof(buf), I2C_TIMEOUT);
    xSemaphoreGive(s_lock);
    return err;
}

esp_err_t i2c_bus_read_burst(uint8_t dev_addr, uint8_t reg, uint8_t *out, size_t len)
{
    xSemaphoreTake(s_lock, portMAX_DELAY);
    esp_err_t err = i2c_master_write_read_device(BOARD_I2C_PORT, dev_addr, &reg, 1, out, len, I2C_TIMEOUT);
    xSemaphoreGive(s_lock);
    return err;
}

esp_err_t i2c_bus_read_u8(uint8_t dev_addr, uint8_t reg, uint8_t *out)
{
    return i2c_bus_read_burst(dev_addr, reg, out, 1);
}

bool i2c_bus_probe(uint8_t dev_addr)
{
    xSemaphoreTake(s_lock, portMAX_DELAY);
    i2c_cmd_handle_t cmd = i2c_cmd_link_create();
    i2c_master_start(cmd);
    i2c_master_write_byte(cmd, (dev_addr << 1) | I2C_MASTER_WRITE, true);
    i2c_master_stop(cmd);
    esp_err_t err = i2c_master_cmd_begin(BOARD_I2C_PORT, cmd, pdMS_TO_TICKS(50));
    i2c_cmd_link_delete(cmd);
    xSemaphoreGive(s_lock);
    return err == ESP_OK;
}

int i2c_bus_scan(uint8_t *found, int max_found)
{
    int n = 0;
    for (uint8_t addr = 0x08; addr <= 0x77; addr++) {
        if (i2c_bus_probe(addr)) {
            ESP_LOGI(TAG, "device at 0x%02X", addr);
            if (found && n < max_found) {
                found[n] = addr;
            }
            n++;
        }
    }
    if (n == 0) {
        ESP_LOGW(TAG, "no devices found - is FB1/FB2 fitted so the TAC5212 is powered?");
    }
    return n > max_found ? max_found : n;
}
