#include "app/app.hpp"

#include "i2c.h"
#include "main.h"
#include "max30102/max30102.hpp"
#include "stm32f4xx_hal.h"
#include "stm32f4xx_hal_uart.h"
#include "usart.h"
#include "window/window.hpp"
#include <cstddef>

namespace app {
constexpr size_t windowSize = 64;

Max30102 sensor{hi2c1};

PpgWindow<windowSize> window;
} // namespace app

void appInit(void) {
  const Config cfg{};

  if (app::sensor.init(cfg) != HAL_OK) {
    Error_Handler();
  }
}

void appRun(void) {
  std::array<Sample, Max30102::fifoDepth> fifo{};
  std::size_t count = 0;

  if (app::sensor.readFifo(fifo, count) != HAL_OK) {
    return;
  }

  for (const auto &s : std::span{fifo}.first(count)) {
    if (app::window.push(app::sensor.toPhotocurrent(s))) {
      constexpr float microAbsorbance = 1e6f;

      const auto a = app::window.pulsatileAbsorbance();

      CsvLine buffer;
      const auto line =
          toCsv(buffer, static_cast<uint32_t>(a.red * microAbsorbance + 0.5f),
                static_cast<uint32_t>(a.ir * microAbsorbance + 0.5f));

      HAL_UART_Transmit(&huart4, reinterpret_cast<const uint8_t *>(line.data()),
                        line.size(), 10);

      app::window.clear();
    }
  }
}
