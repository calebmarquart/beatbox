#include "app/app.hpp"
#include "algorithms/oximeter.hpp"
#include "algorithms/ppg.hpp"
#include "apnea/apnea.hpp"
#include "i2c.h"
#include "main.h"
#include "max30102/max30102.hpp"
#include "usart.h"
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdio>
#include <span>

using namespace max30102;

constexpr Config cfg{};
constexpr std::size_t fsHz = std::size_t(cfg.sampleRateHz()); // 100

Sensor sensor{hi2c1};
Ppg red{cfg.sampleRateHz()};
Ppg ir{cfg.sampleRateHz()};
RfOximeter<fsHz> oximeter; // 4 s blocks -> new result every 1 s

// Apnea model: z-scored red waveform + window vitals -> probability every 60 s
static_assert(fsHz == 100, "the apnea model was trained on 100 sps");
apnea::ZScore zscore;        // keeps running across windows
apnea::Model apneaModel;     // reset every window
apnea::WindowVitals vitals;  // reset every window
int windowSteps = 0;

static void send(UART_HandleTypeDef &uart, const char *buf, int len) {
  if (len <= 0) {
    return;
  }
  HAL_UART_Transmit(&uart, reinterpret_cast<const uint8_t *>(buf), len, 10);
}

// Feeds one band-passed red sample to the model; at the end of each window,
// reports the apnea probability (-1 = no valid SpO2/HR this window)
static void apneaStep(float yRed) {
  const float z = zscore.step(yRed);
  if (std::isnan(z)) {
    return; // z-score warm-up (first 256 samples)
  }
  apneaModel.step(z);
  if (++windowSteps < apnea::weights::kWindowSamples) {
    return;
  }

  const float p =
      vitals.ready() ? apneaModel.probability(vitals.features()) : -1.0f;
  char buf[32];
  const int len = snprintf(buf, sizeof buf, "APNEA=%.3f\r\n", p);
  send(huart2, buf, len);

  apneaModel.reset();
  vitals.reset();
  windowSteps = 0;
}

void appInit(void) {
  if (sensor.init(cfg) != HAL_OK) {
    Error_Handler();
  }
}

void appRun() {
  std::array<Sample, Sensor::fifoDepth> fifo{};
  const std::size_t n = sensor.readFifo(fifo);

  for (const auto &s : std::span{fifo}.first(n)) {
    const float yRed = red.process(s.red);
    const float yIr = ir.process(s.ir);

    // waveform stream (scaled to integers, signed)
    char buf[48];
    int len = snprintf(buf, sizeof buf, "%.2e,%.2e\r\n", yRed, yIr);
    send(huart4, buf, len);

    if (oximeter.push(yRed, yIr)) {
      // new HR/SpO2 result (every 1 s); -1 = invalid
      const auto &r = oximeter.result();
      len = snprintf(buf, sizeof buf, "HR=%.1f,SPO2=%.1f,C=%.2f\r\n",
                     r.hrValid ? r.hrBpm : -1.0f, r.spo2Valid ? r.spo2 : -1.0f,
                     r.correl);
      send(huart2, buf, len);
      vitals.add(r.spo2Valid ? r.spo2 : NAN, r.hrValid ? r.hrBpm : NAN);
    }

    // after the oximeter, so a window's last vitals result is counted
    apneaStep(yRed);
  }
}
