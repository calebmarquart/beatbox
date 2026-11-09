#include "uart/dma_writer.hpp"
#include <cstring>

namespace uart {

bool DmaWriter::write(std::span<const char> data) {
    if (data.size() > kBufferSize - fill_length_) {
        dropped_bytes_ += data.size();
        return false;
    }

    std::memcpy(buffers_[fill_index_].data() + fill_length_, data.data(), data.size());
    fill_length_ += data.size();
    return true;
}

void DmaWriter::flush() {
    if (fill_length_ == 0 || busy_.load()) {
        return;
    }

    busy_.store(true);
    if (HAL_UART_Transmit_DMA(&uart_, buffers_[fill_index_].data(),
                              static_cast<uint16_t>(fill_length_)) != HAL_OK) {
        busy_.store(false);
        return;
    }

    fill_index_ ^= 1;
    fill_length_ = 0;
}

void DmaWriter::on_transfer_complete() { busy_.store(false); }

void DmaWriter::on_transfer_error() { busy_.store(false); }

} // namespace uart
