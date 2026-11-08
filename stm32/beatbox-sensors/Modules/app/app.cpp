#include "app/app.hpp"
#include "algorithms/oximeter.hpp"
#include "algorithms/ppg.hpp"
#include "i2c.h"
#include "main.h"
#include "max30102/max30102.hpp"
#include "usart.h"
#include <array>
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

static void send(UART_HandleTypeDef &uart, const char *buf, int len) {
  if (len <= 0) {
    return;
  }
  HAL_UART_Transmit(&uart, reinterpret_cast<const uint8_t *>(buf), len, 10);
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

    if (!oximeter.push(yRed, yIr)) {
      continue;
    }

    // new HR/SpO2 result (every 4 s); -1 = invalid
    const auto &r = oximeter.result();
    len = snprintf(buf, sizeof buf, "HR=%.1f,SPO2=%.1f,C=%.2f\r\n",
                   r.hrValid ? r.hrBpm : -1.0f, r.spo2Valid ? r.spo2 : -1.0f,
                   r.correl);
    send(huart2, buf, len);
  }
}
