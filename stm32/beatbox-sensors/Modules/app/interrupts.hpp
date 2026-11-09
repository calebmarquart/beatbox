#ifndef MODULE_APP_INTERRUPTS_HPP
#define MODULE_APP_INTERRUPTS_HPP

#include "i2c.h"
#include "max30102/max30102.hpp"
#include "stm32f4xx_hal.h"
#include "uart/dma_writer.hpp"
#include "usart.h"
#include <optional>

namespace interrupts {

static std::optional<uart::DmaWriter> waveform_writer;
static max30102::Sensor *sensor = nullptr;

inline uart::DmaWriter &init(UART_HandleTypeDef &uart) {
  waveform_writer.emplace(uart);
  return *waveform_writer;
}

inline void registerSensor(max30102::Sensor &s) { sensor = &s; }
} // namespace interrupts

extern "C" void HAL_UART_TxCpltCallback(UART_HandleTypeDef *huart) {
  if (huart == &huart4 && interrupts::waveform_writer) {
    interrupts::waveform_writer->on_transfer_complete();
  }
}

extern "C" void HAL_UART_ErrorCallback(UART_HandleTypeDef *huart) {
  if (huart == &huart4 && interrupts::waveform_writer) {
    interrupts::waveform_writer->on_transfer_error();
  }
}

extern "C" void HAL_I2C_MemRxCpltCallback(I2C_HandleTypeDef *hi2c) {
  if (hi2c == &hi2c1 && interrupts::sensor) {
    interrupts::sensor->onRxComplete();
  }
}

extern "C" void HAL_I2C_ErrorCallback(I2C_HandleTypeDef *hi2c) {
  if (hi2c == &hi2c1 && interrupts::sensor) {
    interrupts::sensor->onRxError();
  }
}

#endif // MODULE_APP_INTERRUPTS_HPP
