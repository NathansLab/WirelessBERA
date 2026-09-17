/*
 * audio.h - I2S engine for the TAC5212.
 *
 * The ESP32-S3 is the clock master (there is no MCLK trace on the board, the
 * codec's PLL runs off BCLK). One full-duplex I2S channel pair carries:
 *   RX  <- ADC channel 1 (microphone) in the left slot,
 *          ADC channel 2 (biopotential) in the right slot
 *   TX  -> DAC channel 1 (OUT1P, jack ring) in the left slot,
 *          DAC channel 2 (OUT2P, jack tip)  in the right slot
 *
 * Samples are 24-bit, left-aligned in 32-bit slots, so BCLK = 64 * fs.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

#define AUDIO_CHANNELS          2
#define AUDIO_SLOT_BITS         32
#define AUDIO_SCOPE_FRAMES      128     /* decimated frames per scope packet */

/* ------------------------------------------------------------------ */
/* Stimulus generator                                                  */
/* ------------------------------------------------------------------ */

typedef enum {
    STIM_OFF = 0,
    STIM_SINE,
    STIM_SQUARE,
    STIM_TRIANGLE,
    STIM_NOISE,
    STIM_CLICK,         /* rectangular click train - the classic ABR stimulus */
    STIM_TONE_BURST,    /* gated sine with a Blackman envelope                */
    STIM_CHIRP,         /* linear sweep, restarted every epoch                */
    STIM_DC,            /* constant offset, for DC/offset checks              */
    STIM_TYPE_COUNT
} stim_type_t;

typedef enum {
    STIM_POL_RAREFACTION = 0,
    STIM_POL_CONDENSATION,
    STIM_POL_ALTERNATING,
} stim_polarity_t;

typedef struct {
    stim_type_t     type;
    float           amplitude;      /* 0..1 of digital full scale            */
    float           freq_hz;        /* carrier / sweep start                 */
    float           freq2_hz;       /* chirp end frequency                   */
    float           rate_hz;        /* epoch repetition rate (click/burst)   */
    float           width_us;       /* click width                           */
    float           burst_ms;       /* tone-burst / chirp duration           */
    stim_polarity_t polarity;
    bool            ch1_enable;     /* OUT1P, jack ring                      */
    bool            ch2_enable;     /* OUT2P, jack tip                       */
} stim_config_t;

/* ------------------------------------------------------------------ */
/* Scope stream                                                        */
/* ------------------------------------------------------------------ */

/* Binary WebSocket frame layout, little endian, immediately followed by
 * frames * channels int16 samples. */
typedef struct __attribute__((packed)) {
    uint32_t magic;             /* 'BERA' = 0x41524542                      */
    uint16_t version;           /* 1                                        */
    uint16_t channels;
    uint32_t seq;               /* packet counter, for drop detection       */
    uint32_t sample_rate;       /* codec rate before decimation             */
    uint16_t decimation;        /* effective rate = sample_rate/decimation  */
    uint16_t frames;            /* decimated frames in this packet          */
    uint32_t first_frame;       /* index of the first raw frame, since start*/
    uint32_t stim_epoch;        /* stimulus epochs emitted so far           */
    int32_t  stim_offset;       /* frame index in this packet where an epoch
                                 * started, or -1                           */
} scope_header_t;

#define SCOPE_MAGIC 0x41524542u

/* Called from the audio RX task. Keep it short; it must not block for long. */
typedef void (*audio_scope_cb_t)(const scope_header_t *hdr, const int16_t *samples,
                                 size_t sample_count);

/* ------------------------------------------------------------------ */
/* Live measurements, refreshed once per scope packet                  */
/* ------------------------------------------------------------------ */
typedef struct {
    float    rms_fs[AUDIO_CHANNELS];    /* RMS as a fraction of full scale  */
    float    peak_fs[AUDIO_CHANNELS];   /* |peak| as a fraction of full scale*/
    float    dc_fs[AUDIO_CHANNELS];     /* mean as a fraction of full scale */
    float    clip_pct[AUDIO_CHANNELS];  /* share of samples at full scale   */
    uint32_t clip_total[AUDIO_CHANNELS];/* clipped samples since boot       */
    uint32_t frames_captured;
    uint32_t overruns;
} audio_meters_t;

/* ------------------------------------------------------------------ */
/* API                                                                 */
/* ------------------------------------------------------------------ */

esp_err_t audio_init(uint32_t sample_rate_hz, audio_scope_cb_t scope_cb);

/* Tears the I2S channels down and brings them back up at a new rate.
 * The caller must re-run tac5212_configure() afterwards. */
esp_err_t audio_set_sample_rate(uint32_t sample_rate_hz);
uint32_t  audio_sample_rate(void);

/* Continuous scope streaming on/off. */
void audio_set_streaming(bool on);
bool audio_streaming(void);

/* Decimation factor for the scope stream, 1..4096. */
esp_err_t audio_set_decimation(uint16_t decim);
uint16_t  audio_decimation(void);

void audio_set_stimulus(const stim_config_t *cfg);
void audio_get_stimulus(stim_config_t *cfg);

void audio_get_meters(audio_meters_t *out);

const char *audio_stim_type_name(stim_type_t t);

#ifdef __cplusplus
}
#endif
