// Host-side check of the firmware's Modules/apnea against Python-generated test vectors.
// Built and run by beatbox_dsp.export (and tests/test_apnea_cpp.py); not part of the firmware.
#include <cmath>
#include <cstdio>

#include "apnea/apnea.hpp"
#include "test_vectors.hpp"

static_assert(tv::kLen == apnea::weights::kWindowSamples, "test vectors don't match the model's window length");

int main() {
  namespace w = apnea::weights;
  bool failed = false;

  apnea::ZScore zscore;
  float zMax = 0.0f;
  for (int i = 0; i < tv::kZN; i++) {
    const float z = zscore.step(tv::z_in[i]);
    if (i < w::kZscoreN - 1) continue;  // warm-up: no output yet
    const float d = std::fabs(z - tv::z_out[i]);
    if (!(d <= zMax)) zMax = d;  // also catches NaN
  }
  bool ok = zMax <= tv::kZTol;
  failed |= !ok;
  std::printf("zscore %s max diff %.3g (tol %.3g)\n", ok ? "PASS" : "FAIL", zMax, tv::kZTol);

  for (int n = 0; n < tv::kVN; n++) {
    apnea::WindowVitals vitals;
    for (int i = 0; i < tv::kVLen; i++) vitals.add(tv::spo2[n * tv::kVLen + i], tv::hr[n * tv::kVLen + i]);
    const float* expected = &tv::vitals[n * w::kNumFeats];
    const bool expectReady = !std::isnan(expected[0]) && !std::isnan(expected[3]);
    float vMax = 0.0f;
    if (vitals.ready() && expectReady) {
      const apnea::Vitals got = vitals.features();
      for (int i = 0; i < w::kNumFeats; i++) {
        const float d = std::fabs(got[i] - expected[i]);
        if (!(d <= vMax)) vMax = d;
      }
    }
    ok = vitals.ready() == expectReady && vMax <= 1e-3f;
    failed |= !ok;
    std::printf("window %d vitals %s ready %d max diff %.3g\n", n, ok ? "PASS" : "FAIL", vitals.ready(), vMax);
  }

  static apnea::Model model;
  for (int n = 0; n < tv::kN; n++) {
    model.reset();
    for (int i = 0; i < tv::kLen; i++) model.step(tv::x[n * tv::kLen + i]);
    apnea::Vitals v{};
    for (int i = 0; i < w::kNumFeats; i++) v[i] = tv::feats[n * w::kNumFeats + i];
    const float logit = model.logit(v);
    const float d = std::fabs(logit - tv::logit[n]);
    ok = d <= tv::kLogitTol;
    failed |= !ok;
    std::printf("window %d logit %s got %+.6f expected %+.6f diff %.3g\n", n, ok ? "PASS" : "FAIL", logit,
                tv::logit[n], d);
  }
  return failed ? 1 : 0;
}
