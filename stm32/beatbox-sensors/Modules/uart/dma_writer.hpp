#ifndef MODULE_UART_DMA_WRITER_HPP
#define MODULE_UART_DMA_WRITER_HPP

#include "stm32f4xx_hal.h"
#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <span>

namespace uart {

class DmaWriter {
  public:
    // Fits a full 32-sample FIFO read of ~40-byte lines
    static constexpr std::size_t kBufferSize = 2048;

    explicit DmaWriter(UART_HandleTypeDef &uart)
        : uart_(uart),
          buffers_(),
          fill_index_(0),
          fill_length_(0),
          busy_(false),
          dropped_bytes_(0) {}

    bool write(std::span<const char> data);
    void flush();

    void on_transfer_complete();
    void on_transfer_error();

    const std::size_t &dropped_bytes() const { return dropped_bytes_; }

  private:
    UART_HandleTypeDef &uart_;
    std::array<std::array<uint8_t, kBufferSize>, 2> buffers_;
    std::size_t fill_index_;
    std::size_t fill_length_;
    std::atomic<bool> busy_;
    std::size_t dropped_bytes_;
};

} // namespace uart

#endif // MODULE_UART_DMA_WRITER_HPP
