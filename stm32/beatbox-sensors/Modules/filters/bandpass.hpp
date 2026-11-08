#ifndef FILTERS_BANDPASS_HPP
#define FILTERS_BANDPASS_HPP

#include "arm_math.h"
#include <cmath>
#include <numbers>

class BandPass {
public:
  BandPass(float loHz, float hiHz, float fsHz) {
    design(&coeffs_[0], loHz, fsHz, true);  // stage 1: highpass (removes drift)
    design(&coeffs_[5], hiHz, fsHz, false); // stage 2: lowpass (removes noise)
    arm_biquad_cascade_df2T_init_f32(&inst_, 2, coeffs_, state_);
  }

  float update(float x) {
    float y;
    arm_biquad_cascade_df2T_f32(&inst_, &x, &y, 1);
    return y;
  }

private:
  // RBJ cookbook, Q = 1/sqrt2 (Butterworth). Writes {b0,b1,b2,-a1,-a2}
  static void design(float *c, float fc, float fs, bool highpass) {
    const float w0 = 2.0f * std::numbers::pi_v<float> * fc / fs;
    const float alpha = std::sin(w0) / std::numbers::sqrt2_v<float>;
    const float cw = std::cos(w0);
    const float a0 = 1.0f + alpha;
    const float k = highpass ? (1.0f + cw) : (1.0f - cw);
    c[0] = k / 2.0f / a0;
    c[1] = (highpass ? -k : k) / a0;
    c[2] = c[0];
    c[3] = 2.0f * cw / a0;
    c[4] = -(1.0f - alpha) / a0;
  }

  arm_biquad_cascade_df2T_instance_f32 inst_;
  float coeffs_[10];
  float state_[4] = {};
};

#endif