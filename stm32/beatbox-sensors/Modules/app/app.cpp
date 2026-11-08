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
constexpr size_t fsHz = size_t(cfg.sampleRateHz()); // 100

Sensor sensor{hi2c1};
Ppg red{cfg.sampleRateHz()};
Ppg ir{cfg.sampleRateHz()};
RfOximeter<fsHz> oximeter; // 4 s blocks -> new result every 1 s

// Apnea model: z-scored red waveform + window vitals -> probability every 60 s
static_assert(fsHz == 100, "the apnea model was trained on 100 sps");
apnea::ZScore zscore;       // keeps running across windows
apnea::Model apneaModel;    // reset every window
apnea::WindowVitals vitals; // reset every window
int windowSteps = 0;
float apneaProb =
    -1.0f; // latest window result (-1 = none yet / invalid vitals)

static void sendAll(const char *buf, int len) {
  if (len <= 0) {
    return;
  }
  const auto *p = reinterpret_cast<const uint8_t *>(buf);
  HAL_UART_Transmit(&huart2, p, len, 10);
  HAL_UART_Transmit(&huart4, p, len, 10);
}

// Feeds one band-passed red sample to the model; at the end of each window,
// updates apneaProb (-1 = no valid SpO2/HR this window)
static void apneaStep(float yRed) {
  const float z = zscore.step(yRed);
  if (std::isnan(z)) {
    return; // z-score warm-up (first 256 samples)
  }
  apneaModel.step(z);
  if (++windowSteps < apnea::weights::kWindowSamples) {
    return;
  }

  apneaProb =
      vitals.ready() ? apneaModel.probability(vitals.features()) : -1.0f;

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
    oximeter.push(yRed, yIr); // updates result() once per second

    const auto &r = oximeter.result();
    vitals.add(r.spo2Valid ? r.spo2 : NAN, r.hrValid ? r.hrBpm : NAN);

    // after the oximeter, so a window's last vitals result is counted
    apneaStep(yRed);

    // red_ppm,ir_ppm,hr,spo2,correl,apnea  (hr/spo2/apnea = -1 when invalid)
    char buf[80];
    const int len = snprintf(buf, sizeof buf, "%ld,%ld,%.1f,%.1f,%.2f,%.3f\r\n",
                             long(yRed * 1e6f), long(yIr * 1e6f),
                             r.hrValid ? r.hrBpm : -1.0f,
                             r.spo2Valid ? r.spo2 : -1.0f, r.correl, apneaProb);
    sendAll(buf, len);
  }
}
