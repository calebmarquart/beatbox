#ifndef FILTERS_LOWPASS_HPP
#define FILTERS_LOWPASS_HPP

#include "arm_math.h"
#include <cmath>
#include <numbers>

class LowPass {
public:
  LowPass(float fcHz, float fsHz) {
    // RBJ cookbook 2nd-order Butterworth LPF (Q = 1/sqrt2)
    const float w0 = 2.0f * std::numbers::pi_v<float> * fcHz / fsHz;
    const float alpha =
        std::sin(w0) / std::numbers::sqrt2_v<float>; // sin(w0)/(2Q), Q=0.7071
    const float c = std::cos(w0);
    const float a0 = 1.0f + alpha;
    // CMSIS form: {b0, b1, b2, a1, a2}, with a1/a2 NEGATED vs. textbook
    coeffs_[0] = (1.0f - c) / 2.0f / a0;
    coeffs_[1] = (1.0f - c) / a0;
    coeffs_[2] = coeffs_[0];
    coeffs_[3] = (2.0f * c) / a0;
    coeffs_[4] = -(1.0f - alpha) / a0;
    arm_biquad_cascade_df2T_init_f32(&inst_, 1, coeffs_, state_);
  }

  float update(float x) {
    float y;
    arm_biquad_cascade_df2T_f32(&inst_, &x, &y, 1);
    return y;
  }

  // block version: cheaper per sample if you process FIFO batches
  void process(const float *in, float *out, uint32_t n) {
    arm_biquad_cascade_df2T_f32(&inst_, in, out, n);
  }

private:
  arm_biquad_cascade_df2T_instance_f32 inst_;
  float coeffs_[5];
  float state_[2] = {};
};

// First-order IIR low-pass filter
// y[n] = y[n-1] + alpha * (x[n] - y[n-1])
// alpha = 1 - exp(-2*pi*fc/fs)
struct LowPassFirstOrder {
public:
  LowPassFirstOrder(float fcHz, float fsHz)
      : alpha_(1.0f - std::exp(-2.0f * std::numbers::pi * fcHz / fsHz)) {}

  float update(float x) {
    if (!started_) {
      y_ = x;
      started_ = true;
    } else {
      y_ += alpha_ * (x - y_);
    }
    return y_;
  }

private:
  float alpha_;
  float y_ = 0.0f;
  bool started_ = false;
};

#endif
