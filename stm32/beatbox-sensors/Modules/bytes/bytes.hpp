#ifndef BYTES_HPP
#define BYTES_HPP

#include <cstdint>
#include <span>

constexpr void packLe32(std::span<uint8_t, 4> out, uint32_t val) {
  out[0] = static_cast<uint8_t>(val);
  out[1] = static_cast<uint8_t>(val >> 8);
  out[2] = static_cast<uint8_t>(val >> 16);
  out[3] = static_cast<uint8_t>(val >> 24);
}

constexpr uint32_t unpackLe32(std::span<const uint8_t, 4> in) {
  return uint32_t{in[0]} | (uint32_t{in[1]} << 8) | (uint32_t{in[2]} << 16) |
         (uint32_t{in[3]} << 24);
}

constexpr uint32_t unpackBe24(std::span<const uint8_t, 3> in) {
  return (uint32_t{in[0]} << 16) | (uint32_t{in[1]} << 8) | uint32_t{in[2]};
}

#endif // BYTES_HPP
