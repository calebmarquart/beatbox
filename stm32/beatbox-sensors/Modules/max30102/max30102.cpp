#include "max30102/max30102.hpp"
#include "stm32f4xx_hal.h"
#include "stm32f4xx_hal_def.h"
#include "stm32f4xx_hal_i2c.h"

constexpr uint16_t i2cAddress = 0x57 << 1; // HAL expects 8-bit address
constexpr uint32_t i2cTimeoutMs = 100;
constexpr uint32_t resetTimeoutMs = 100;

namespace reg {
constexpr uint8_t IntStatus1 = 0x00;
constexpr uint8_t IntEnable1 = 0x02;
constexpr uint8_t FifoWrPtr = 0x04;
constexpr uint8_t OvfCounter = 0x05;
constexpr uint8_t FifoRdPtr = 0x06;
constexpr uint8_t FifoData = 0x07;
constexpr uint8_t FifoConfig = 0x08;
constexpr uint8_t ModeConfig = 0x09;
constexpr uint8_t SpO2Config = 0x0A;
constexpr uint8_t Led1Pa = 0x0C; // Red
constexpr uint8_t Led2Pa = 0x0D; // IR
constexpr uint8_t PartId = 0xFF;
} // namespace reg

constexpr uint8_t partID = 0x15;

constexpr uint8_t resetModeBit = 1U << 6;
constexpr uint8_t intPpgReadyBit = 1U << 6;
constexpr uint8_t fifoRolloverBit = 1U << 4;

HAL_StatusTypeDef Max30102::init(const Config &cfg) {
  uint8_t val = 0;

  if (auto s = readRegister(reg::PartId, val); s != HAL_OK) {
    return s;
  }

  if (val != partID) {
    return HAL_ERROR;
  }

  // MODE_CONFIG bit 6 = RESET, clears automatically when done
  if (auto s = writeRegister(reg::ModeConfig, resetModeBit); s != HAL_OK) {
    return s;
  }

  const uint32_t start = HAL_GetTick();
  do {
    if (auto s = readRegister(reg::ModeConfig, val); s != HAL_OK) {
      return s;
    }

    if (HAL_GetTick() - start > resetTimeoutMs) {
      return HAL_TIMEOUT;
    }

    HAL_Delay(1);
  } while (val & resetModeBit);

  // Clear PWR_RDY left over from the reset
  if (auto s = readRegister(reg::IntStatus1, val); s != HAL_OK) {
    return s;
  }

  // FIFO_CONFIG: SMP_AVE[7:5], FIFO_ROLLOVER_EN bit 4
  const auto fifoCfg = static_cast<uint8_t>(
      (static_cast<uint8_t>(cfg.average) << 5) | fifoRolloverBit);

  // SPO2_CONFIG: ADC_REG[6:5], SR[4:2], LED_PW[1:0]
  const auto spo2Cfg =
      static_cast<uint8_t>((static_cast<uint8_t>(cfg.range) << 5) |
                           (static_cast<uint8_t>(cfg.rate) << 2) |
                           static_cast<uint8_t>(cfg.pulseWidth));

  const struct {
    uint8_t reg;
    uint8_t val;
  } writes[] = {
      {reg::FifoConfig, fifoCfg},
      {reg::SpO2Config, spo2Cfg},
      {reg::Led1Pa, cfg.redCurrent},
      {reg::Led2Pa, cfg.irCurrent},
      {reg::FifoWrPtr, 0},
      {reg::OvfCounter, 0},
      {reg::FifoRdPtr, 0},
      {reg::IntEnable1, intPpgReadyBit},
      {reg::ModeConfig, static_cast<uint8_t>(cfg.mode)},
  };

  for (const auto &w : writes) {
    if (auto s = writeRegister(w.reg, w.val); s != HAL_OK) {
      return s;
    }
  }

  cfg_ = cfg;
  return HAL_OK;
}

HAL_StatusTypeDef Max30102::readFifo(std::span<Sample, fifoDepth> out,
                                     std::size_t &count) {
  count = 0;

  // FIFO_WR_PTR (0x04), OVF_COUNTER (0x05), FIFO_RD_PTR (0x06) in one burst
  std::array<uint8_t, 3> ptrs{};
  if (auto s = HAL_I2C_Mem_Read(&hi2c_, i2cAddress, reg::FifoWrPtr,
                                I2C_MEMADD_SIZE_8BIT, ptrs.data(), ptrs.size(),
                                i2cTimeoutMs);
      s != HAL_OK) {
    return s;
  }

  constexpr uint8_t ptrMask = 0x1F;
  const uint8_t wr = ptrs[0] & ptrMask;
  const uint8_t ovf = ptrs[1] & ptrMask;
  const uint8_t rd = ptrs[2] & ptrMask;

  std::size_t available = static_cast<uint8_t>(wr - rd) & ptrMask;

  // wr == rd means empty or full; a nonzero overflow count means full
  if (ovf != 0) {
    samplesLost_ += ovf;
    available = fifoDepth;
  }

  if (available == 0) {
    return HAL_OK;
  }

  // HR mode: 3 bytes per sample (Red). SpO2 mode: 6 bytes (Red, then IR)
  const bool spo2 = (cfg_.mode == Mode::SpO2);
  const std::size_t bytesPerSample = spo2 ? 6 : 3;

  std::array<uint8_t, fifoDepth * 6> buffer{};
  if (auto s = HAL_I2C_Mem_Read(
          &hi2c_, i2cAddress, reg::FifoData, I2C_MEMADD_SIZE_8BIT,
          buffer.data(), static_cast<uint16_t>(available * bytesPerSample),
          i2cTimeoutMs);
      s != HAL_OK) {
    return s;
  }

  // Each value is 3 bytes big-endian, left-justified 18-bit ADC value
  constexpr uint32_t adcMask = 0x3FFFF;
  const std::span<const uint8_t> bytes{buffer};

  for (std::size_t i = 0; i < available; ++i) {
    const auto sample = bytes.subspan(i * bytesPerSample, bytesPerSample);

    out[i].red = unpackBe24(sample.first<3>()) & adcMask;
    out[i].ir = spo2 ? (unpackBe24(sample.subspan<3, 3>()) & adcMask) : 0;
  }

  count = available;
  return HAL_OK;
}

HAL_StatusTypeDef Max30102::writeRegister(uint8_t reg, uint8_t val) {
  return HAL_I2C_Mem_Write(&hi2c_, i2cAddress, reg, I2C_MEMADD_SIZE_8BIT, &val,
                           1, i2cTimeoutMs);
}

HAL_StatusTypeDef Max30102::readRegister(uint8_t reg, uint8_t &val) {
  return HAL_I2C_Mem_Read(&hi2c_, i2cAddress, reg, I2C_MEMADD_SIZE_8BIT, &val,
                          1, i2cTimeoutMs);
}
