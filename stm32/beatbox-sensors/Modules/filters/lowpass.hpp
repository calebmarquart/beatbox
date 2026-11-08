// First-order IIR low-pass filter
// y[n] = y[n-1] + alpha * (x[n] - y[n-1])
// alpha = 1 - exp(-2*pi*fc/fs)

#ifndef FILTERS_LOWPASS_HPP
#define FILTERS_LOWPASS_HPP

#include <cmath>
#include <numbers>

struct LowPass {
public:
  LowPass(float fcHz, float fsHz)
      : alpha_(1.0f - std::exp(-2.0f * std::numbers::pi * fcHz / fsHz)) {}

  float update(float x) {
    if (!started_) {
      y_ = x;
      started_ = true;
    } else {
      y_ += alpha_ * (y_ - x);
    }
    return y_;
  }

private:
  float alpha_;
  float y_ = 0.0f;
  bool started_ = false;
};

#endif
