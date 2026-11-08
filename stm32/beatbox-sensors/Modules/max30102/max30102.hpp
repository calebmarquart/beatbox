#ifndef MAX30102_HPP
#define MAX30102_HPP

#include "bytes/bytes.hpp"
#include "stm32f4xx_hal.h"
#include "stm32f4xx_hal_def.h"
#include "stm32f4xx_hal_i2c.h"
#include <array>
#include <charconv>
#include <cstddef>
#include <cstdint>
#include <span>

enum class Mode : uint8_t {
  HeartRate = 0x02,
  SpO2 = 0x03,
};

enum class SampleAverage : uint8_t {
  x1 = 0,
  x2,
  x4,
  x8,
  x16,
  x32,
};

enum class AdcRange : uint8_t {
  nA2048 = 0,
  nA4096,
  nA8192,
  nA16384,
};

enum class SampleRate : uint8_t {
  Hz50 = 0,
  Hz100,
  Hz200,
  Hz400,
  Hz800,
  Hz1000,
  Hz1600,
  Hz3200,
};

enum class PulseWidth : uint8_t {
  us69 = 0,
  us118,
  us215,
  us411,
};

constexpr uint8_t ledCurrent(float mA) {
  const float mA_per_step = 0.2f;
  const float steps = mA / mA_per_step;

  if (steps <= 0.0f) {
    return 0U;
  }

  if (steps >= 255.0f) {
    return 255U;
  }

  return static_cast<uint8_t>(steps + 0.5f);
}

struct Config {
  Mode mode = Mode::SpO2;
  SampleAverage average = SampleAverage::x1;
  AdcRange range = AdcRange::nA4096;
  SampleRate rate = SampleRate::Hz400;
  PulseWidth pulseWidth = PulseWidth::us411;
  uint8_t redCurrent = ledCurrent(7.2f);
  uint8_t irCurrent = ledCurrent(7.2f);
};

// Worst case: "4294967295,4294967295\r\n" = 10 + 1 + 10 + 2 = 23 chars
using CsvLine = std::array<char, 23>;

// Formats "a,b\r\n" into buffer and returns the used part
inline std::span<const char> toCsv(CsvLine &buffer, uint32_t a, uint32_t b) {
  char *ptr = buffer.data();

  char *const end = buffer.data() + buffer.size();

  ptr = std::to_chars(ptr, end, a).ptr;
  *ptr++ = ',';

  ptr = std::to_chars(ptr, end, b).ptr;
  *ptr++ = '\r';
  *ptr++ = '\n';

  return {buffer.data(), ptr};
}

// Worst case: "-1.23e-03,-1.23e-03\r\n" = 9 + 1 + 9 + 2 = 21 chars
using FloatCsvLine = std::array<char, 21>;

inline std::span<const char> toCsv(FloatCsvLine &buffer, float a, float b) {
  char *ptr = buffer.data();
  char *const end = buffer.data() + buffer.size();

  ptr = std::to_chars(ptr, end, a, std::chars_format::scientific, 2).ptr;
  *ptr++ = ',';

  ptr = std::to_chars(ptr, end, b, std::chars_format::scientific, 2).ptr;
  *ptr++ = '\r';
  *ptr++ = '\n';

  return {buffer.data(), ptr};
}

// Raw 18-bit ADC counts
struct Sample {
  uint32_t red;
  uint32_t ir;

  using Bytes = std::array<uint8_t, 8>;

  constexpr Bytes serialize() const {
    Bytes b{};

    std::span<uint8_t> s{b};

    packLe32(s.subspan<0, 4>(), red);
    packLe32(s.subspan<4, 4>(), ir);

    return b;
  }

  std::span<const char> toCsv(CsvLine &buffer) const {
    return ::toCsv(buffer, red, ir);
  }
};

// Photocurrent in picoamps
struct Photocurrent {
  uint32_t red;
  uint32_t ir;

  std::span<const char> toCsv(CsvLine &buffer) const {
    return ::toCsv(buffer, red, ir);
  }
};

class Max30102 {
public:
  static constexpr size_t fifoDepth = 32;

  explicit Max30102(I2C_HandleTypeDef &hi2c) : hi2c_(hi2c) {}

  HAL_StatusTypeDef init(const Config &cfg = {});

  // Reads every sample waiting in the FIFO, oldest first, and sets count.
  // Returns immediately with count = 0 if the FIFO is empty.
  HAL_StatusTypeDef readFifo(std::span<Sample, fifoDepth> out,
                             std::size_t &count);

  const Config &config() const { return cfg_; }

  // Total samples the chip dropped because the FIFO was full
  uint32_t samplesLost() const { return samplesLost_; }

  // Raw 18-bit ADC count -> photocurrent in picoamps (datasheet SPO2_ADC_RGE
  // table). One count = 125/16 pA at 2048 nA full scale, doubled per range
  // step.
  static constexpr uint32_t toPicoamps(uint32_t counts, AdcRange range) {
    return ((counts * lsbNum) << static_cast<uint8_t>(range)) / lsbDen;
  }

  // Converts a whole sample using the range this instance was configured with
  Photocurrent toPhotocurrent(const Sample &s) const {
    return {toPicoamps(s.red, cfg_.range), toPicoamps(s.ir, cfg_.range)};
  }

private:
  HAL_StatusTypeDef writeRegister(uint8_t reg, uint8_t val);

  HAL_StatusTypeDef readRegister(uint8_t reg, uint8_t &val);

  I2C_HandleTypeDef &hi2c_;

  Config cfg_{};

  uint32_t samplesLost_ = 0;

  // 18-bit ADC, data left-justified so full scale is 2^18 counts at any pulse
  // width
  static constexpr uint32_t adcFullScaleCounts = 1U << 18;

  // Full scale at SPO2_ADC_RGE = 00 is 2048 nA
  static constexpr uint32_t minFullScalePa = 2048000U;

  // One count at range 00 = 2048000 / 2^18 = 7.8125 pA = 125/16 pA
  static constexpr uint32_t lsbNum = 125U;
  static constexpr uint32_t lsbDen = 16U;

  static_assert(minFullScalePa * lsbDen == adcFullScaleCounts * lsbNum,
                "LSB fraction must equal full scale / counts");

  // Worst case: (2^18 - 1) * 125 << 3 must fit in uint32_t
  static_assert(uint64_t{adcFullScaleCounts - 1} * lsbNum * 8U <= UINT32_MAX,
                "toPicoamps would overflow at the largest range");
};

static_assert(Max30102::toPicoamps(1, AdcRange::nA2048) == 7U); // 7.8125
static_assert(Max30102::toPicoamps(1U << 18, AdcRange::nA2048) == 2048000U);
static_assert(Max30102::toPicoamps(1U << 18, AdcRange::nA16384) == 16384000U);

#endif // MAX30102_HPP
