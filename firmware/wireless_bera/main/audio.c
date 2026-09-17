#include "audio.h"

#include <inttypes.h>
#include <math.h>
#include <string.h>

#include "board.h"
#include "driver/i2s_std.h"
#include "esp_check.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

static const char *TAG = "audio";

/* Raw frames moved per DMA transaction. 256 frames at 48 kHz is 5.3 ms, short
 * enough to keep stimulus timing tight and long enough to keep the task from
 * thrashing. */
#define AUDIO_BLOCK_FRAMES  256
#define AUDIO_BLOCK_WORDS   (AUDIO_BLOCK_FRAMES * AUDIO_CHANNELS)

/* 24-bit samples sit in bits [31:8] of each 32-bit slot. */
#define SAMPLE_SHIFT        8
#define SAMPLE_FULLSCALE    8388608.0f  /* 2^23 */

/* A converter sitting this close to full scale is clipping for any practical
 * purpose; counting those samples is the only honest way to tell an operator
 * that the waveform on screen is no longer the signal. */
#define SAMPLE_CLIP_LEVEL   8380000

static i2s_chan_handle_t s_tx, s_rx;
static uint32_t          s_sample_rate = 48000;
static volatile bool     s_streaming;
static volatile uint16_t s_decim = 48;
static audio_scope_cb_t  s_scope_cb;

static SemaphoreHandle_t s_cfg_lock;
static stim_config_t     s_stim = {
    .type = STIM_OFF,
    .amplitude = 0.25f,
    .freq_hz = 1000.0f,
    .freq2_hz = 8000.0f,
    .rate_hz = 20.0f,
    .width_us = 100.0f,
    .burst_ms = 5.0f,
    .polarity = STIM_POL_ALTERNATING,
    .ch1_enable = true,
    .ch2_enable = true,
};

/* Cross-task counters. Written by one task, read by the other; 32-bit aligned
 * loads/stores are atomic on this core so no lock is needed for a snapshot. */
static volatile uint32_t s_rx_frames;
static volatile uint32_t s_stim_epoch;
static volatile bool     s_stim_epoch_flag;           /* TX started an epoch  */
static volatile uint32_t s_overruns;

static audio_meters_t    s_meters;
static SemaphoreHandle_t s_meters_lock;

static TaskHandle_t s_rx_task, s_tx_task;
static volatile bool s_tasks_should_run;

static int32_t *s_rx_buf;
static int32_t *s_tx_buf;

static const char *s_stim_names[STIM_TYPE_COUNT] = {
    "off", "sine", "square", "triangle", "noise", "click", "tone_burst", "chirp", "dc"
};

const char *audio_stim_type_name(stim_type_t t)
{
    return (t < STIM_TYPE_COUNT) ? s_stim_names[t] : "?";
}

/* ------------------------------------------------------------------ */
/* Stimulus synthesis                                                  */
/* ------------------------------------------------------------------ */

static uint32_t rng_state = 0x1234ABCDu;

static inline float rng_bipolar(void)
{
    rng_state ^= rng_state << 13;
    rng_state ^= rng_state >> 17;
    rng_state ^= rng_state << 5;
    return (float)(int32_t)rng_state * (1.0f / 2147483648.0f);
}

/* Blackman window, t in 0..1. */
static inline float blackman(float t)
{
    return 0.42f - 0.5f * cosf(2.0f * (float)M_PI * t) + 0.08f * cosf(4.0f * (float)M_PI * t);
}

/*
 * Fills one block with the configured stimulus.
 *
 * Epoch-based stimuli (click, tone burst, chirp) restart every
 * fs / rate_hz frames. `epoch_pos` carries the position inside the current
 * epoch across calls, `phase` the carrier phase for the free-running shapes.
 */
static void stimulus_fill(const stim_config_t *cfg, int32_t *out, size_t frames,
                          double *phase, uint32_t *epoch_pos, int *epoch_offset_out)
{
    const float fs = (float)s_sample_rate;
    const uint32_t epoch_len = (cfg->rate_hz > 0.01f)
                                   ? (uint32_t)(fs / cfg->rate_hz)
                                   : 0xFFFFFFFFu;
    const uint32_t click_len = (uint32_t)fmaxf(1.0f, cfg->width_us * 1e-6f * fs);
    const uint32_t burst_len = (uint32_t)fmaxf(1.0f, cfg->burst_ms * 1e-3f * fs);

    *epoch_offset_out = -1;

    for (size_t i = 0; i < frames; i++) {
        float v = 0.0f;

        switch (cfg->type) {
        case STIM_OFF:
            v = 0.0f;
            break;

        case STIM_DC:
            v = cfg->amplitude;
            break;

        case STIM_SINE:
            v = cfg->amplitude * sinf((float)(*phase));
            break;

        case STIM_SQUARE:
            v = (sinf((float)(*phase)) >= 0.0f) ? cfg->amplitude : -cfg->amplitude;
            break;

        case STIM_TRIANGLE: {
            const float t = (float)(*phase / (2.0 * M_PI));        /* 0..1 */
            v = cfg->amplitude * (4.0f * fabsf(t - 0.5f) - 1.0f);
            break;
        }

        case STIM_NOISE:
            v = cfg->amplitude * rng_bipolar();
            break;

        case STIM_CLICK:
            v = (*epoch_pos < click_len) ? cfg->amplitude : 0.0f;
            break;

        case STIM_TONE_BURST:
            if (*epoch_pos < burst_len) {
                const float t = (float)(*epoch_pos) / (float)burst_len;
                const float ph = 2.0f * (float)M_PI * cfg->freq_hz * (float)(*epoch_pos) / fs;
                v = cfg->amplitude * blackman(t) * sinf(ph);
            }
            break;

        case STIM_CHIRP:
            if (*epoch_pos < burst_len) {
                const float t = (float)(*epoch_pos) / fs;
                const float dur = (float)burst_len / fs;
                const float k = (cfg->freq2_hz - cfg->freq_hz) / dur;
                const float ph = 2.0f * (float)M_PI * (cfg->freq_hz * t + 0.5f * k * t * t);
                v = cfg->amplitude * blackman((float)(*epoch_pos) / (float)burst_len) * sinf(ph);
            }
            break;

        default:
            break;
        }

        /* Polarity handling for the epoch-based stimuli. */
        if (cfg->type == STIM_CLICK || cfg->type == STIM_TONE_BURST) {
            bool invert = (cfg->polarity == STIM_POL_CONDENSATION);
            if (cfg->polarity == STIM_POL_ALTERNATING) {
                invert = (s_stim_epoch & 1u) != 0;
            }
            if (invert) {
                v = -v;
            }
        }

        if (v >  1.0f) v =  1.0f;
        if (v < -1.0f) v = -1.0f;

        const int32_t s = (int32_t)(v * (SAMPLE_FULLSCALE - 1.0f)) << SAMPLE_SHIFT;
        out[i * AUDIO_CHANNELS + 0] = cfg->ch1_enable ? s : 0;
        out[i * AUDIO_CHANNELS + 1] = cfg->ch2_enable ? s : 0;

        /* Advance the carrier phase. */
        *phase += 2.0 * M_PI * (double)cfg->freq_hz / (double)fs;
        if (*phase >= 2.0 * M_PI) {
            *phase -= 2.0 * M_PI;
        }

        /* Advance the epoch counter. */
        if (++(*epoch_pos) >= epoch_len) {
            *epoch_pos = 0;
            s_stim_epoch++;
            if (*epoch_offset_out < 0) {
                *epoch_offset_out = (int)i;
            }
            s_stim_epoch_flag = true;
        }
    }
}

/* ------------------------------------------------------------------ */
/* Tasks                                                               */
/* ------------------------------------------------------------------ */

static void audio_tx_task(void *arg)
{
    double   phase = 0.0;
    uint32_t epoch_pos = 0;

    while (s_tasks_should_run) {
        stim_config_t cfg;
        xSemaphoreTake(s_cfg_lock, portMAX_DELAY);
        cfg = s_stim;
        xSemaphoreGive(s_cfg_lock);

        int epoch_offset;
        stimulus_fill(&cfg, s_tx_buf, AUDIO_BLOCK_FRAMES, &phase, &epoch_pos, &epoch_offset);

        size_t written = 0;
        const esp_err_t err = i2s_channel_write(s_tx, s_tx_buf,
                                                AUDIO_BLOCK_WORDS * sizeof(int32_t),
                                                &written, pdMS_TO_TICKS(1000));
        if (err != ESP_OK) {
            ESP_LOGW(TAG, "i2s write: %s", esp_err_to_name(err));
            vTaskDelay(pdMS_TO_TICKS(10));
        }
    }
    s_tx_task = NULL;
    vTaskDelete(NULL);
}

static void audio_rx_task(void *arg)
{
    /* Decimation accumulators, one per channel. */
    int64_t  acc[AUDIO_CHANNELS] = { 0 };
    uint32_t acc_n = 0;

    static int16_t scope[AUDIO_SCOPE_FRAMES * AUDIO_CHANNELS];
    uint16_t scope_frames = 0;
    uint32_t seq = 0;
    uint32_t packet_first_frame = 0;
    int32_t  packet_stim_offset = -1;

    /* Per-packet meters. */
    double   sum_sq[AUDIO_CHANNELS] = { 0 };
    double   sum[AUDIO_CHANNELS] = { 0 };
    int32_t  peak[AUDIO_CHANNELS] = { 0 };
    uint32_t clipped[AUDIO_CHANNELS] = { 0 };
    uint32_t clip_total[AUDIO_CHANNELS] = { 0 };
    uint32_t meter_n = 0;

    while (s_tasks_should_run) {
        size_t read = 0;
        const esp_err_t err = i2s_channel_read(s_rx, s_rx_buf,
                                               AUDIO_BLOCK_WORDS * sizeof(int32_t),
                                               &read, pdMS_TO_TICKS(1000));
        if (err != ESP_OK || read == 0) {
            if (err != ESP_ERR_TIMEOUT) {
                ESP_LOGW(TAG, "i2s read: %s", esp_err_to_name(err));
            }
            continue;
        }

        const size_t frames = read / sizeof(int32_t) / AUDIO_CHANNELS;
        const uint16_t decim = s_decim ? s_decim : 1;

        /* Consume the "an epoch started" flag once per block; the offset is
         * approximate (DMA latency is not compensated) but the epoch counter
         * lets a host align averages exactly. */
        bool epoch_here = s_stim_epoch_flag;
        s_stim_epoch_flag = false;

        for (size_t i = 0; i < frames; i++) {
            for (int c = 0; c < AUDIO_CHANNELS; c++) {
                const int32_t v = s_rx_buf[i * AUDIO_CHANNELS + c] >> SAMPLE_SHIFT;
                acc[c] += v;
                sum[c] += v;
                sum_sq[c] += (double)v * (double)v;
                const int32_t a = v < 0 ? -v : v;
                if (a > peak[c]) {
                    peak[c] = a;
                }
                if (a >= SAMPLE_CLIP_LEVEL) {
                    clipped[c]++;
                    clip_total[c]++;
                }
            }
            meter_n++;

            if (++acc_n >= decim) {
                if (scope_frames == 0) {
                    packet_first_frame = s_rx_frames + (uint32_t)i;
                    packet_stim_offset = epoch_here ? 0 : -1;
                    epoch_here = false;
                }
                for (int c = 0; c < AUDIO_CHANNELS; c++) {
                    /* Mean of the block, scaled from 24-bit to int16. */
                    const int32_t mean = (int32_t)(acc[c] / (int64_t)decim);
                    scope[scope_frames * AUDIO_CHANNELS + c] = (int16_t)(mean >> 8);
                    acc[c] = 0;
                }
                acc_n = 0;

                if (++scope_frames >= AUDIO_SCOPE_FRAMES) {
                    if (s_streaming && s_scope_cb) {
                        const scope_header_t hdr = {
                            .magic = SCOPE_MAGIC,
                            .version = 1,
                            .channels = AUDIO_CHANNELS,
                            .seq = seq++,
                            .sample_rate = s_sample_rate,
                            .decimation = decim,
                            .frames = scope_frames,
                            .first_frame = packet_first_frame,
                            .stim_epoch = s_stim_epoch,
                            .stim_offset = packet_stim_offset,
                        };
                        s_scope_cb(&hdr, scope, (size_t)scope_frames * AUDIO_CHANNELS);
                    }
                    scope_frames = 0;
                }
            }
        }

        s_rx_frames += (uint32_t)frames;

        /* Refresh the meters roughly ten times a second. */
        if (meter_n >= s_sample_rate / 10) {
            xSemaphoreTake(s_meters_lock, portMAX_DELAY);
            for (int c = 0; c < AUDIO_CHANNELS; c++) {
                s_meters.rms_fs[c]  = (float)(sqrt(sum_sq[c] / meter_n) / SAMPLE_FULLSCALE);
                s_meters.peak_fs[c] = (float)(peak[c] / SAMPLE_FULLSCALE);
                s_meters.dc_fs[c]   = (float)((sum[c] / meter_n) / SAMPLE_FULLSCALE);
                s_meters.clip_pct[c] = 100.0f * (float)clipped[c] / (float)meter_n;
                s_meters.clip_total[c] = clip_total[c];
                sum_sq[c] = 0;
                sum[c] = 0;
                peak[c] = 0;
                clipped[c] = 0;
            }
            s_meters.frames_captured = s_rx_frames;
            s_meters.overruns = s_overruns;
            xSemaphoreGive(s_meters_lock);
            meter_n = 0;
        }
    }
    s_rx_task = NULL;
    vTaskDelete(NULL);
}

/* ------------------------------------------------------------------ */
/* I2S bring-up                                                        */
/* ------------------------------------------------------------------ */

/* Raised by the I2S driver when a DMA buffer was overwritten before the task
 * read it - the honest signal that acquisition lost samples. */
static IRAM_ATTR bool on_rx_overflow(i2s_chan_handle_t handle, i2s_event_data_t *event, void *ctx)
{
    s_overruns++;
    return false;
}

static esp_err_t i2s_start(uint32_t sample_rate_hz)
{
    i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(BOARD_I2S_PORT, I2S_ROLE_MASTER);
    chan_cfg.dma_desc_num = 6;
    chan_cfg.dma_frame_num = AUDIO_BLOCK_FRAMES;
    chan_cfg.auto_clear = true;     /* send zeros rather than stale data on
                                       underrun, so nothing screeches */

    ESP_RETURN_ON_ERROR(i2s_new_channel(&chan_cfg, &s_tx, &s_rx), TAG, "new_channel");

    i2s_std_config_t std = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(sample_rate_hz),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT,
                                                        I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,        /* no MCLK trace on this board */
            .bclk = BOARD_I2S_BCLK_GPIO,
            .ws   = BOARD_I2S_FSYNC_GPIO,
            .dout = BOARD_I2S_DOUT_GPIO,    /* ESP -> codec DIN  */
            .din  = BOARD_I2S_DIN_GPIO,     /* ESP <- codec DOUT */
            .invert_flags = { false, false, false },
        },
    };

    ESP_RETURN_ON_ERROR(i2s_channel_init_std_mode(s_tx, &std), TAG, "init tx");
    ESP_RETURN_ON_ERROR(i2s_channel_init_std_mode(s_rx, &std), TAG, "init rx");

    const i2s_event_callbacks_t cbs = { .on_recv_q_ovf = on_rx_overflow };
    ESP_RETURN_ON_ERROR(i2s_channel_register_event_callback(s_rx, &cbs, NULL), TAG, "rx callbacks");

    ESP_RETURN_ON_ERROR(i2s_channel_enable(s_tx), TAG, "enable tx");
    ESP_RETURN_ON_ERROR(i2s_channel_enable(s_rx), TAG, "enable rx");

    s_sample_rate = sample_rate_hz;
    ESP_LOGI(TAG, "I2S master up: fs=%" PRIu32 " Hz, %d-bit slots, BCLK=%" PRIu32 " Hz "
                  "(BCLK=%d, WS=%d, DOUT=%d, DIN=%d)",
             sample_rate_hz, AUDIO_SLOT_BITS,
             sample_rate_hz * AUDIO_SLOT_BITS * AUDIO_CHANNELS,
             BOARD_I2S_BCLK_GPIO, BOARD_I2S_FSYNC_GPIO,
             BOARD_I2S_DOUT_GPIO, BOARD_I2S_DIN_GPIO);
    return ESP_OK;
}

static void i2s_stop(void)
{
    if (s_rx) {
        i2s_channel_disable(s_rx);
        i2s_del_channel(s_rx);
        s_rx = NULL;
    }
    if (s_tx) {
        i2s_channel_disable(s_tx);
        i2s_del_channel(s_tx);
        s_tx = NULL;
    }
}

static esp_err_t tasks_start(void)
{
    s_tasks_should_run = true;
    if (xTaskCreate(audio_tx_task, "audio_tx", 4096, NULL, 6, &s_tx_task) != pdPASS) {
        return ESP_ERR_NO_MEM;
    }
    if (xTaskCreate(audio_rx_task, "audio_rx", 5120, NULL, 6, &s_rx_task) != pdPASS) {
        return ESP_ERR_NO_MEM;
    }
    return ESP_OK;
}

static void tasks_stop(void)
{
    s_tasks_should_run = false;
    /* The tasks block on I2S with a 1 s timeout; give them time to notice. */
    for (int i = 0; i < 200 && (s_rx_task || s_tx_task); i++) {
        vTaskDelay(pdMS_TO_TICKS(10));
    }
}

esp_err_t audio_init(uint32_t sample_rate_hz, audio_scope_cb_t scope_cb)
{
    s_scope_cb = scope_cb;
    s_cfg_lock = xSemaphoreCreateMutex();
    s_meters_lock = xSemaphoreCreateMutex();
    if (!s_cfg_lock || !s_meters_lock) {
        return ESP_ERR_NO_MEM;
    }

    /* DMA-capable internal RAM - PSRAM would work but adds latency. */
    s_rx_buf = heap_caps_malloc(AUDIO_BLOCK_WORDS * sizeof(int32_t), MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    s_tx_buf = heap_caps_malloc(AUDIO_BLOCK_WORDS * sizeof(int32_t), MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    if (!s_rx_buf || !s_tx_buf) {
        return ESP_ERR_NO_MEM;
    }
    memset(s_tx_buf, 0, AUDIO_BLOCK_WORDS * sizeof(int32_t));

    ESP_RETURN_ON_ERROR(i2s_start(sample_rate_hz), TAG, "i2s_start");
    return tasks_start();
}

esp_err_t audio_set_sample_rate(uint32_t sample_rate_hz)
{
    if (sample_rate_hz == s_sample_rate) {
        return ESP_OK;
    }
    tasks_stop();
    i2s_stop();
    ESP_RETURN_ON_ERROR(i2s_start(sample_rate_hz), TAG, "restart");
    return tasks_start();
}

uint32_t audio_sample_rate(void) { return s_sample_rate; }

void audio_set_streaming(bool on) { s_streaming = on; }
bool audio_streaming(void)        { return s_streaming; }

esp_err_t audio_set_decimation(uint16_t decim)
{
    if (decim < 1 || decim > 4096) {
        return ESP_ERR_INVALID_ARG;
    }
    s_decim = decim;
    return ESP_OK;
}

uint16_t audio_decimation(void) { return s_decim; }

void audio_set_stimulus(const stim_config_t *cfg)
{
    xSemaphoreTake(s_cfg_lock, portMAX_DELAY);
    s_stim = *cfg;
    if (s_stim.amplitude < 0.0f) s_stim.amplitude = 0.0f;
    if (s_stim.amplitude > 1.0f) s_stim.amplitude = 1.0f;
    xSemaphoreGive(s_cfg_lock);
    ESP_LOGI(TAG, "stimulus: %s amp=%.3f f=%.1f Hz rate=%.1f Hz ch=%d%d",
             audio_stim_type_name(cfg->type), (double)cfg->amplitude,
             (double)cfg->freq_hz, (double)cfg->rate_hz,
             cfg->ch1_enable, cfg->ch2_enable);
}

void audio_get_stimulus(stim_config_t *cfg)
{
    xSemaphoreTake(s_cfg_lock, portMAX_DELAY);
    *cfg = s_stim;
    xSemaphoreGive(s_cfg_lock);
}

void audio_get_meters(audio_meters_t *out)
{
    xSemaphoreTake(s_meters_lock, portMAX_DELAY);
    *out = s_meters;
    xSemaphoreGive(s_meters_lock);
}
