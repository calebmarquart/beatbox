#include "max30102/max30102.hpp"

#include <array>

namespace max30102 {

constexpr uint16_t i2cAddress = 0x57 << 1; // HAL wants the 8-bit address
constexpr uint32_t i2cTimeoutMs = 100;
constexpr uint32_t resetTimeoutMs = 100;
constexpr uint8_t partId = 0x15;

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

constexpr uint8_t resetBit = 1U << 6;        // MODE_CONFIG
constexpr uint8_t ppgReadyBit = 1U << 6;     // INT_ENABLE_1
constexpr uint8_t fifoRolloverBit = 1U << 4; // FIFO_CONFIG

constexpr uint8_t u8(auto e) { return static_cast<uint8_t>(e); }

// 3 bytes, big-endian, 18-bit value
uint32_t read18bits(const uint8_t *p) {
  return ((uint32_t{p[0]} << 16) | (uint32_t{p[1]} << 8) | p[2]) & 0x3FFFF;
}

HAL_StatusTypeDef Sensor::init(const Config &cfg) {
  uint8_t val = 0;
  HAL_StatusTypeDef s;

  // Check we're talking to a MAX30102
  if ((s = readRegister(reg::PartId, val)) != HAL_OK) {
    return s;
  }
  if (val != partId) {
    return HAL_ERROR;
  }

  // Soft reset; the bit clears itself when done
  if ((s = writeRegister(reg::ModeConfig, resetBit)) != HAL_OK) {
    return s;
  }

  const uint32_t start = HAL_GetTick();
  do {
    if (HAL_GetTick() - start > resetTimeoutMs) {
      return HAL_TIMEOUT;
    }

    HAL_Delay(1);

    if ((s = readRegister(reg::ModeConfig, val)) != HAL_OK) {
      return s;
    }
  } while (val & resetBit);

  // Reading INT_STATUS_1 clears the PWR_RDY flag left by the reset
  if ((s = readRegister(reg::IntStatus1, val)) != HAL_OK) {
    return s;
  }

  const uint8_t fifoCfg = (u8(cfg.average) << 5) | fifoRolloverBit;
  const uint8_t spo2Cfg =
      (u8(cfg.range) << 5) | (u8(cfg.rate) << 2) | u8(cfg.pulseWidth);

  const uint8_t writes[][2] = {
      {reg::FifoConfig, fifoCfg},
      {reg::SpO2Config, spo2Cfg},
      {reg::Led1Pa, cfg.redCurrent},
      {reg::Led2Pa, cfg.irCurrent},
      {reg::FifoWrPtr, 0},
      {reg::OvfCounter, 0},
      {reg::FifoRdPtr, 0},
      {reg::IntEnable1, ppgReadyBit},
      {reg::ModeConfig, u8(cfg.mode)}, // last: starts sampling
  };

  for (const auto &w : writes) {
    if ((s = writeRegister(w[0], w[1])) != HAL_OK) {
      return s;
    }
  }

  mode_ = cfg.mode;
  return HAL_OK;
}

std::size_t Sensor::readFifo(std::span<Sample, fifoDepth> out) {
  // FIFO_WR_PTR, OVF_COUNTER, FIFO_RD_PTR are consecutive, read in one go
  uint8_t ptrs[3];
  if (HAL_I2C_Mem_Read(&hi2c_, i2cAddress, reg::FifoWrPtr, I2C_MEMADD_SIZE_8BIT,
                       ptrs, sizeof ptrs, i2cTimeoutMs) != HAL_OK) {
    return 0;
  }

  const uint8_t wr = ptrs[0] & 0x1F;
  const uint8_t ovf = ptrs[1] & 0x1F;
  const uint8_t rd = ptrs[2] & 0x1F;

  // wr == rd means empty, unless samples overflowed, in which case it's full
  const std::size_t count = ovf ? fifoDepth : ((wr - rd) & 0x1F);
  if (count == 0) {
    return 0;
  }

  const bool spo2 = (mode_ == Mode::SpO2);
  const std::size_t bytesPerSample = spo2 ? 6 : 3; // Red [, IR]

  std::array<uint8_t, fifoDepth * 6> buf;
  if (HAL_I2C_Mem_Read(&hi2c_, i2cAddress, reg::FifoData, I2C_MEMADD_SIZE_8BIT,
                       buf.data(), count * bytesPerSample,
                       i2cTimeoutMs) != HAL_OK) {
    return 0;
  }

  for (std::size_t i = 0; i < count; ++i) {
    const uint8_t *p = &buf[i * bytesPerSample];
    out[i].red = read18bits(p);
    out[i].ir = spo2 ? read18bits(p + 3) : 0;
  }

  return count;
}

HAL_StatusTypeDef Sensor::writeRegister(uint8_t reg, uint8_t val) {
  return HAL_I2C_Mem_Write(&hi2c_, i2cAddress, reg, I2C_MEMADD_SIZE_8BIT, &val,
                           1, i2cTimeoutMs);
}

HAL_StatusTypeDef Sensor::readRegister(uint8_t reg, uint8_t &val) {
  return HAL_I2C_Mem_Read(&hi2c_, i2cAddress, reg, I2C_MEMADD_SIZE_8BIT, &val,
                          1, i2cTimeoutMs);
}

} // namespace max30102
