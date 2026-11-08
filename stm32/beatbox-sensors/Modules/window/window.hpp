#ifndef PPG_WINDOW_HPP
#define PPG_WINDOW_HPP

#include "max30102/max30102.hpp"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <span>

// Red and IR absorbance pair
struct Absorbance {
  float red;
  float ir;
};

// Red and IR windows of N samples. Each buffer is 2N floats so it can later
// hold N complex values in place: [re0, im0, re1, im1, ...].
template <size_t N> class PpgWindow {
  static_assert(N > 0 && (N & (N - 1)) == 0, "N must be a power of 2");

public:
  static constexpr size_t samples = N;

  bool push(const Photocurrent &pa) {
    red_[2 * count_] = static_cast<float>(pa.red);
    red_[2 * count_ + 1] = 0.0f;

    ir_[2 * count_] = static_cast<float>(pa.ir);
    ir_[2 * count_ + 1] = 0.0f;

    return ++count_ == N;
  }

  // Pulsatile absorbance over the whole window, one value per channel:
  // log10(Imax / Imin). Call on photocurrent, before toAbsorbance().
  Absorbance pulsatileAbsorbance() const { return {deltaA(red_), deltaA(ir_)}; }

  // Per channel: x -> -log10(x / mean), the change in absorbance relative to
  // the window average
  void toAbsorbance() {
    toAbsorbance(red_);
    toAbsorbance(ir_);
  }

  float red(std::size_t i) const { return red_[2 * i]; }
  float ir(std::size_t i) const { return ir_[2 * i]; }

  std::span<float, 2 * N> red() { return red_; }
  std::span<float, 2 * N> ir() { return ir_; }

  void clear() { count_ = 0; }

private:
  static float deltaA(const std::array<float, 2 * N> &buf) {
    float lo = buf[0];
    float hi = buf[0];

    for (std::size_t i = 1; i < N; ++i) {
      lo = std::min(lo, buf[2 * i]);
      hi = std::max(hi, buf[2 * i]);
    }

    return lo > 0.0f ? std::log10(hi / lo) : 0.0f; // no light at all -> 0
  }

  static void toAbsorbance(std::array<float, 2 * N> &buf) {
    float sum = 0.0f;
    for (std::size_t i = 0; i < N; ++i) {
      sum += buf[2 * i];
    }

    const float mean = sum / N;
    if (mean <= 0.0f) {
      return; // no light at all
    }

    const float inv = 1.0f / mean;
    for (std::size_t i = 0; i < N; ++i) {
      const float ratio = buf[2 * i] * inv;
      buf[2 * i] = ratio > 0.0f ? -std::log10(ratio) : 0.0f;
    }
  }

  std::array<float, 2 * N> red_{};
  std::array<float, 2 * N> ir_{};
  size_t count_ = 0;
};

#endif
