#include "app/app.hpp"
#include "i2c.h"
#include "main.h"
#include "max30102/max30102.hpp"
#include "ppg/ppg.hpp"
#include "stm32f4xx_hal_uart.h"
#include "usart.h"
#include <cmath>
#include <cstddef>
#include <cstdio>

using namespace max30102;

constexpr float sampleRateHz(SampleRate r) {
  constexpr float table[] = {50, 100, 200, 400, 800, 1000, 1600, 3200};
  return table[static_cast<uint8_t>(r)];
}

constexpr float effectiveFsHz(const Config &c) {
  // on-chip averaging divides the output rate
  return sampleRateHz(c.rate) / float(1u << static_cast<uint8_t>(c.average));
}

constexpr float fullScaleNa(AdcRange r) {
  return 2048.0f * float(1u << static_cast<uint8_t>(r));
}

constexpr Config cfg{};
Sensor sensor{hi2c1};
Ppg red{cfg.fullScaleNanoamps(), cfg.sampleRateHz()};
Ppg ir{cfg.fullScaleNanoamps(), cfg.sampleRateHz()};

void appInit(void) {
  if (sensor.init(cfg) != HAL_OK) {
    Error_Handler();
  }
}

void appRun() {
  std::array<Sample, Sensor::fifoDepth> fifo{};
  const std::size_t n = sensor.readFifo(fifo);

  for (const auto &s : std::span{fifo}.first(n)) {
    const auto yRed = static_cast<int32_t>(red.process(s.red) * 1e6f);
    const auto yIr = static_cast<int32_t>(ir.process(s.ir) * 1e6f);

    char buf[32];
    const int len =
        snprintf(buf, sizeof buf, "%ld,%ld\r\n", (long)yRed, (long)yIr);
    HAL_UART_Transmit(&huart4, reinterpret_cast<uint8_t *>(buf), len, 10);
  }
}
