// Host-side check of the firmware's Modules/apnea against PyTorch-generated test vectors.
// Built and run by beatbox_dsp.export (and tests/test_apnea_cpp.py); not part of the firmware.
#include <cmath>
#include <cstdio>

#include "apnea/apnea.hpp"
#include "test_vectors.hpp"

static_assert(tv::kLen == apnea::weights::kWindowSamples, "test vectors don't match the model's window length");

int main() {
  bool failed = false;

  apnea::FrontEnd fe;
  float feMax = 0.0f;
  for (int i = 0; i < tv::kFeN; i++) {
    const float z = fe.step(tv::fe_in[i]);
    if (i < apnea::weights::kZscoreN - 1) continue;  // warm-up: no output yet
    const float d = std::fabs(z - tv::fe_out[i]);
    if (!(d <= feMax)) feMax = d;  // also catches NaN
  }
  bool ok = feMax <= tv::kFeTol;
  failed |= !ok;
  std::printf("frontend %s max diff %.3g (tol %.3g)\n", ok ? "PASS" : "FAIL", feMax, tv::kFeTol);

  static apnea::Model model;
  for (int n = 0; n < tv::kN; n++) {
    model.reset();
    for (int i = 0; i < tv::kLen; i++) model.step(tv::x[n * tv::kLen + i]);
    apnea::Vitals v{};
    for (int i = 0; i < apnea::weights::kNumFeats; i++) v[i] = tv::feats[n * apnea::weights::kNumFeats + i];
    const float logit = model.logit(v);
    const float d = std::fabs(logit - tv::logit[n]);
    ok = d <= tv::kLogitTol;
    failed |= !ok;
    std::printf("window %d logit %s got %+.6f expected %+.6f diff %.3g\n", n, ok ? "PASS" : "FAIL", logit,
                tv::logit[n], d);
  }
  return failed ? 1 : 0;
}
