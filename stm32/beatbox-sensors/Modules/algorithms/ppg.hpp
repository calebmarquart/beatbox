// MAX30102 ADC count into clean pulse waveform
// One sample in, one sample out
//
// 1. counts = bytes & 0x3FFFF
//
// 2. i = counts * FS / 18-bit-count = counts * FS / 2^18
// 3. A_rel = -ln(i / I_ref)
// 2 (optimal). A_rel = -ln(counts / 2^18)
//    (same as -ln(i / I_fs); the full-scale current cancels, see process())
//
// 3. y = bandpass(A_rel - A_rel[0]), 0.2 to 4.5 Hz
//    - highpass removes the slow drift (baseline)
//    - lowpass removes noise
//    - A_rel[0] (first sample) is subtracted so the highpass doesn't ring
//    for several seconds at startup. a constant offset doesn't change the
//    highpass output otherwise
//
// The DC component is thrown away on purpose. Because of the -ln in step 3,
// the pulse in absorbance is already normalized by DC:
//
//   i = I_dc + i_ac,  with i_ac << I_dc
//   -ln(i) = -ln(I_dc) - ln(1 + i_ac/I_dc) ≈ -ln(I_dc) - i_ac/I_dc
//
// so the bandpass output is about -AC/DC. Then:
//   SpO2:            R = (AC/DC)_red / (AC/DC)_ir = amp(y_red) / amp(y_ir)
//   perfusion index: PI = AC/DC = amp(y_ir)
//
// Neither one needs a separate DC value

#ifndef PPG_HPP
#define PPG_HPP

#include "filters/bandpass.hpp"
#include <cmath>
#include <cstddef>
#include <cstdint>

constexpr float slowFcHz = 0.2f;
constexpr float fastFcHz = 4.5f;

constexpr size_t adc18bitCountMask = 0x3FFFF;
constexpr float adc18bitCount = 262144.0f; // 2^18

class Ppg {
public:
  Ppg(float fsHz)
      // : fullScaleNanoamps_(fullScaleNanoamps),
      : bandpass_(slowFcHz, fastFcHz, fsHz) {}

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

    // -ln(counts / 2^18) = ln(2^18) - ln(counts). The ln(2^18) term is a
    // constant, which a_offset_ and the highpass remove anyway, so it's
    // dropped.
    // i_nA = counts * (fullScaleNanoamps_ / adc18bitCount);
    // a_rel = -std::log(i_nA / fullScaleNanoamps_);
    a_rel = -std::log(float(counts));

    // Center the input on the first sample so the highpass starts settled
    if (!started_) {
      a_offset_ = a_rel;
      started_ = true;
    }

    last_ = bandpass_.update(a_rel - a_offset_);
    return last_;
  }

  float i_nA = 0.0f;
  float a_rel = 0.0f;

private:
  // float fullScaleNanoamps_;
  BandPass bandpass_;
  float a_offset_ = 0.0f;
  bool started_ = false;
  float last_ = 0.0f;
};

#endif
