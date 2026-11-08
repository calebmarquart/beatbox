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

static void sendAll(const char *buf, int len) {
  if (len <= 0) {
    return;
  }
  const auto *p = reinterpret_cast<const uint8_t *>(buf);
  HAL_UART_Transmit(&huart2, p, len, 10);
  HAL_UART_Transmit(&huart4, p, len, 10);
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

    // red_ppm,ir_ppm,hr,spo2,correl  (hr/spo2 = -1 when invalid)
    const auto &r = oximeter.result();
    char buf[64];
    const int len = snprintf(buf, sizeof buf, "%ld,%ld,%.1f,%.1f,%.2f\r\n",
                             long(yRed * 1e6f), long(yIr * 1e6f),
                             r.hrValid ? r.hrBpm : -1.0f,
                             r.spo2Valid ? r.spo2 : -1.0f, r.correl);
    sendAll(buf, len);
  }
}
