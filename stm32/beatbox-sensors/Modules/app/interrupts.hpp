#ifndef MODULE_APP_INTERRUPTS_HPP
#define MODULE_APP_INTERRUPTS_HPP

#include "uart/dma_writer.hpp"
#include "usart.h"
#include <optional>

namespace interrupts {

static std::optional<uart::DmaWriter> waveform_writer;

inline uart::DmaWriter &init(UART_HandleTypeDef &uart) {
    waveform_writer.emplace(uart);
    return *waveform_writer;
}

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

#endif // MODULE_APP_INTERRUPTS_HPP
