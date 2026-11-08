// MAX30102 ADC count into clean pulse waveform
// One sample in, one sample out
//
// 1. counts = bytes & 0x3FFFF
//
// 2. i = counts * FS / 18-bit-count = counts * FS / 2^18
//
// 3. A_rel = -ln(i / I_ref)
//
// 4. A_dc = slow low-pass of A_rel (0.2 Hz, follows drift, ignores the beat)
//
// 5. dA = A_rel - A_dc (the pulse, centered on zero)
//
// 6. y = fast low-pass of dA (8 Hz, follows the beat, removes noise)

#ifndef PPG_HPP
#define PPG_HPP

#include "filters/lowpass.hpp"
#include <cmath>
#include <cstddef>
#include <cstdint>

constexpr float slowFcHz = 0.2;
constexpr float fastFcHz = 8;

constexpr size_t adc18bitCountMask = 0x3FFFF;
constexpr float adc18bitCount = 262144.0f; // 2^18

class Ppg {
public:
  Ppg(float fullScaleNanoamps, float fs_hz)
      : fullScaleNanoamps_(fullScaleNanoamps), baseline_(slowFcHz, fs_hz),
        smoother_(fastFcHz, fs_hz) {}

  // Raw FIFO bytes (MSB first)
  float process(const uint8_t bytes[3]) {
    return process((uint32_t(bytes[0]) << 16) | (uint32_t(bytes[1]) << 8) |
                   uint32_t(bytes[2]));
  }

  // Already-unpacked counts (e.g. Sample::red / Sample::ir)
  float process(uint32_t counts) {
    counts &= adc18bitCountMask;
    if (counts == 0) {
      return last_;
    }

    i_nA = counts * (fullScaleNanoamps_ / adc18bitCount);
    a_rel = -std::log(i_nA / fullScaleNanoamps_);
    a_dc = baseline_.update(a_rel);
    dA = a_rel - a_dc;

    last_ = smoother_.update(dA);
    return last_;
  }

  float i_nA = 0.0f;
  float a_rel = 0.0f;
  float a_dc = 0.0f; // needed later for SpO2? smt, smt, perfusion index?
  float dA = 0.0f;

private:
  float fullScaleNanoamps_;
  LowPass baseline_;
  LowPass smoother_;
  float last_ = 0.0f;
};

#endif
