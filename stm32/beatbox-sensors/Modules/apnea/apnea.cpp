#include "apnea/apnea.hpp"

#include <cmath>
#include <cstring>

namespace apnea {

namespace w = weights;

namespace {

float elu(float v) { return v > 0.0f ? v : std::expm1(v); }
float sigmoid(float v) { return 1.0f / (1.0f + std::exp(-v)); }

// Causal conv, kernel 3: buf holds the last 3 inputs per input channel, [ch][k], k = 2 newest.
void convStep(float* buf, int layer, const float* in, float* out) {
  const int nIn = w::kConvIn[layer];
  const int nOut = w::kConvOut[layer];
  const float* wt = w::kConvW[layer];
  const float* b = w::kConvB[layer];
  for (int i = 0; i < nIn; i++) {
    buf[3 * i] = buf[3 * i + 1];
    buf[3 * i + 1] = buf[3 * i + 2];
    buf[3 * i + 2] = in[i];
  }
  for (int o = 0; o < nOut; o++) {
    float acc = b[o];
    const float* wo = &wt[o * nIn * 3];
    for (int j = 0; j < nIn * 3; j++) acc += wo[j] * buf[j];
    out[o] = acc;
  }
}

// One GRU layer step, PyTorch gate order r, z, n.
void gruStep(float* h, int layer, const float* x, int nIn) {
  constexpr int H = w::kGruHidden;
  const float* wIh = w::kGru_w_ih[layer];
  const float* wHh = w::kGru_w_hh[layer];
  const float* bIh = w::kGru_b_ih[layer];
  const float* bHh = w::kGru_b_hh[layer];
  float gi[3 * H];
  float gh[3 * H];
  for (int r = 0; r < 3 * H; r++) {
    float a = bIh[r];
    float c = bHh[r];
    for (int j = 0; j < nIn; j++) a += wIh[r * nIn + j] * x[j];
    for (int j = 0; j < H; j++) c += wHh[r * H + j] * h[j];
    gi[r] = a;
    gh[r] = c;
  }
  for (int j = 0; j < H; j++) {
    const float r = sigmoid(gi[j] + gh[j]);
    const float z = sigmoid(gi[H + j] + gh[H + j]);
    const float n = std::tanh(gi[2 * H + j] + r * gh[2 * H + j]);
    h[j] = (1.0f - z) * n + z * h[j];
  }
}

}  // namespace

// ---------------- ZScore ----------------

void ZScore::reset() { *this = ZScore{}; }

std::optional<float> ZScore::step(float x) {
  ring_[count_ % w::kZscoreN] = x;
  count_++;
  if (count_ < static_cast<unsigned>(w::kZscoreN)) return std::nullopt;

  float mean = 0.0f;
  for (float v : ring_) mean += v;
  mean /= w::kZscoreN;
  float var = 0.0f;
  for (float v : ring_) var += (v - mean) * (v - mean);
  return (x - mean) / (std::sqrt(var / w::kZscoreN) + w::kZscoreEps);
}

// ---------------- WindowVitals ----------------

void WindowVitals::Stat::add(std::optional<float> v) {
  if (!v) return;
  min = n == 0 ? *v : std::fmin(min, *v);
  max = n == 0 ? *v : std::fmax(max, *v);
  sum += *v;
  n++;
}

void WindowVitals::reset() { *this = WindowVitals{}; }

void WindowVitals::add(std::optional<float> spo2, std::optional<float> hrBpm) {
  spo2_.add(spo2);
  hr_.add(hrBpm);
}

bool WindowVitals::ready() const { return spo2_.n > 0 && hr_.n > 0; }

Vitals WindowVitals::features() const {
  return {spo2_.sum / spo2_.n, spo2_.min, spo2_.max - spo2_.min, hr_.sum / hr_.n, hr_.max - hr_.min};
}

// ---------------- Model ----------------

void Model::reset() { *this = Model{}; }

void Model::step(float z) {
  float a[w::kMaxCh];
  float b[w::kMaxCh];
  a[0] = z;
  for (int g = 0; g < w::kNumGroups; g++) {
    convStep(convBuf_[2 * g].data(), 2 * g, a, b);
    convStep(convBuf_[2 * g + 1].data(), 2 * g + 1, b, a);
    const int ch = w::kConvOut[2 * g + 1];
    for (int c = 0; c < ch; c++) a[c] = elu(a[c]);
    if (!poolHas_[g]) {  // max-pool(2): hold the first of each pair
      std::memcpy(poolHeld_[g].data(), a, ch * sizeof(float));
      poolHas_[g] = true;
      return;
    }
    for (int c = 0; c < ch; c++) a[c] = std::fmax(a[c], poolHeld_[g][c]);
    poolHas_[g] = false;
  }
  gruStep(h_[0].data(), 0, a, w::kGruIn);
  for (int l = 1; l < w::kGruLayers; l++) gruStep(h_[l].data(), l, h_[l - 1].data(), w::kGruHidden);
}

float Model::logit(const Vitals& vitals) const {
  constexpr int nIn = w::kGruHidden + w::kNumFeats;
  float in[nIn];
  float hid[w::kFcHidden];
  std::memcpy(in, h_[w::kGruLayers - 1].data(), w::kGruHidden * sizeof(float));
  for (int i = 0; i < w::kNumFeats; i++) in[w::kGruHidden + i] = (vitals[i] - w::kFeatMean[i]) / w::kFeatStd[i];
  for (int o = 0; o < w::kFcHidden; o++) {
    float acc = w::head0_b[o];
    for (int j = 0; j < nIn; j++) acc += w::head0_w[o * nIn + j] * in[j];
    hid[o] = elu(acc);
  }
  float out = w::head1_b[0];
  for (int j = 0; j < w::kFcHidden; j++) out += w::head1_w[j] * hid[j];
  return out;
}

float Model::probability(const Vitals& vitals) const { return sigmoid(logit(vitals)); }

}  // namespace apnea
