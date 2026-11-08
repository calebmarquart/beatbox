#pragma once

// Streaming apnea detector: C++ port of dsp/src/beatbox_dsp/stream.py.
// No heap, no HAL dependencies (also compiled on the host by dsp/cpp/host_check.cpp).
//
// Per sample (100 sps):
//   float z = frontEnd.step(absorbance);
//   if (!std::isnan(z)) model.step(z);
// After weights::kWindowSamples model steps:
//   float p = model.probability(vitals);
//   model.reset();              // the front end is NOT reset between windows

#include <array>

#include "apnea/model_weights.hpp"

namespace apnea {

// Window vitals, in this order: spo2_mean, spo2_min, spo2_drop (max - min), hr_mean, hr_range (max - min)
using Vitals = std::array<float, weights::kNumFeats>;

class FrontEnd {
 public:
  void reset();
  // Causal Butterworth band-pass + sliding z-score. Returns NaN for the first kZscoreN - 1 samples.
  float step(float x);

 private:
  // x[n-1], x[n-2], y[n-1], y[n-2] per stage; double, see kBiquad in model_weights.hpp
  std::array<std::array<double, 4>, weights::kNumBiquads> biquad_{};
  std::array<float, weights::kZscoreN> ring_{};
  unsigned count_ = 0;
};

class Model {
 public:
  void reset();
  // One z-scored sample through the causal conv stack (and the GRU on every 16th sample).
  void step(float z);
  float logit(const Vitals& vitals) const;
  float probability(const Vitals& vitals) const;

 private:
  std::array<std::array<float, weights::kMaxCh * 3>, weights::kNumConv> convBuf_{};  // [ch][k], k = 2 newest
  std::array<std::array<float, weights::kMaxCh>, weights::kNumGroups> poolHeld_{};
  std::array<bool, weights::kNumGroups> poolHas_{};
  std::array<std::array<float, weights::kGruHidden>, weights::kGruLayers> h_{};
};

}  // namespace apnea
