#ifndef MAX30102_HPP
#define MAX30102_HPP

#include "stm32f4xx_hal.h"
#include <cstddef>
#include <cstdint>
#include <span>

namespace max30102 {

enum class Mode : uint8_t { HeartRate = 0x02, SpO2 = 0x03 };
enum class SampleAverage : uint8_t { x1, x2, x4, x8, x16, x32 };
enum class AdcRange : uint8_t { nA2048, nA4096, nA8192, nA16384 };
enum class SampleRate : uint8_t {
  Hz50,
  Hz100,
  Hz200,
  Hz400,
  Hz800,
  Hz1000,
  Hz1600,
  Hz3200
};
enum class PulseWidth : uint8_t { us69, us118, us215, us411 };

// LED current register: 0.2 mA per step, 0..51 mA
constexpr uint8_t ledCurrent(float mA) {
  if (mA <= 0.0f)
    return 0;
  if (mA >= 51.0f)
    return 255;
  return static_cast<uint8_t>(mA / 0.2f + 0.5f);
}

struct Config {
  Mode mode = Mode::SpO2;
  SampleAverage average = SampleAverage::x1;
  AdcRange range = AdcRange::nA4096;
  SampleRate rate = SampleRate::Hz100;
  PulseWidth pulseWidth = PulseWidth::us411;
  uint8_t redCurrent = ledCurrent(7.0f);
  uint8_t irCurrent = ledCurrent(7.0f);

  // Output rate after on-chip averaging
  constexpr float sampleRateHz() const {
    constexpr float hz[] = {50, 100, 200, 400, 800, 1000, 1600, 3200};
    return hz[static_cast<uint8_t>(rate)] /
           float(1u << static_cast<uint8_t>(average));
  }

  constexpr float fullScaleNanoamps() const {
    return 2048.0f * float(1u << static_cast<uint8_t>(range));
  }
};

// Raw 18-bit ADC counts (ir = 0 in HeartRate mode)
struct Sample {
  uint32_t red;
  uint32_t ir;
};

class Sensor {
public:
  static constexpr std::size_t fifoDepth = 32;

  explicit Sensor(I2C_HandleTypeDef &hi2c) : hi2c_(hi2c) {}

  HAL_StatusTypeDef init(const Config &cfg = {});

  // Drains the FIFO into `out`, oldest first. Returns the number of samples
  // read (0 if empty or on I2C error).
  std::size_t readFifo(std::span<Sample, fifoDepth> out);

private:
  HAL_StatusTypeDef writeRegister(uint8_t reg, uint8_t val);
  HAL_StatusTypeDef readRegister(uint8_t reg, uint8_t &val);

  I2C_HandleTypeDef &hi2c_;
  Mode mode_ = Mode::SpO2;
};

} // namespace max30102

#endif
