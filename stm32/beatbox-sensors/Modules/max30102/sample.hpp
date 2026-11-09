#ifndef MAX30102_SAMPLE_HPP
#define MAX30102_SAMPLE_HPP

#include <cstdint>

namespace max30102 {

// Raw 18-bit ADC counts (ir = 0 in HeartRate mode)
struct Sample {
  uint32_t red;
  uint32_t ir;
};

} // namespace max30102

#endif
