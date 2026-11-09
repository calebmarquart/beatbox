#pragma once

// Streaming apnea detector: sample-by-sample version of dsp/src/beatbox_dsp/model.py (TinyCNN),
// checked against PyTorch by `uv run python -m beatbox_dsp.export` (dsp/cpp/host_check.cpp).
// No heap, no HAL dependencies, so it also compiles on the host.
//
// Signal path (absorbance + 0.2-4.5 Hz band-pass come from pipeline/stream.hpp):
//   y_red = red.bandpass(red.adjust_offset(sample.red()));   // Stream
//   std::optional<float> z = zscore.step(y_red);
//   if (z) model.step(*z);
//   on each new RfOximeter result:  vitals.add(result.spo2, result.hrBpm);
// After weights::kWindowSamples model steps:
//   float p = model.probability(vitals.features());   // if vitals.ready()
//   model.reset(); vitals.reset();                     // zscore keeps running

#include <array>
#include <optional>

#include "apnea/model_weights.hpp"

namespace apnea {

// Window vitals, in this order: spo2_mean, spo2_min, spo2_drop (max - min), hr_mean, hr_range (max - min)
using Vitals = std::array<float, weights::kNumFeats>;

// Sliding z-score over the last kZscoreN band-passed samples (population std).
class ZScore {
 public:
  void reset();
  // Returns nothing until kZscoreN samples have been seen.
  std::optional<float> step(float x);

 private:
  std::array<float, weights::kZscoreN> ring_{};
  unsigned count_ = 0;
};

// Collects SpO2 / HR results during one window (empty = invalid result, ignored).
class WindowVitals {
 public:
  void reset();
  void add(std::optional<float> spo2, std::optional<float> hrBpm);
  // At least one valid SpO2 and one valid HR result this window (training drops windows otherwise).
  bool ready() const;
  Vitals features() const;

 private:
  struct Stat {
    float sum = 0.0f;
    float min = 0.0f;
    float max = 0.0f;
    int n = 0;
    void add(std::optional<float> v);
  };
  Stat spo2_{};
  Stat hr_{};
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
