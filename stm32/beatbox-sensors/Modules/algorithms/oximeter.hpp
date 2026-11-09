// Heart rate + SpO2, based on R. Fraczkiewicz's MAX30102_by_RF
// (github.com/aromring/MAX30102_by_RF, MIT-style license), using CMSIS-DSP.
// Inputs: Stream::bandpass() outputs (bandpassed absorbance ~ -AC/DC).

#ifndef RF_OXIMETER_HPP
#define RF_OXIMETER_HPP

#include "arm_math.h"
#include <cstddef>
#include <optional>

template <size_t FS, size_t ST = 4, size_t HOP_MS = 1000> class RfOximeter {
public:
  static constexpr size_t N = FS * ST;              // 400 @ 100 Hz
  static constexpr size_t HOP = FS * HOP_MS / 1000; // 100 -> result every 1s
  static constexpr size_t minLag = FS * 60 / 180;   // 180 bpm
  static constexpr size_t maxLag = FS * 60 / 40;    //  40 bpm
  static constexpr float minAutoRatio = 0.6f;       // was 0.5
  static constexpr float minPearson = 0.8f;         // now gates SpO2 only
  static constexpr int maxMisses = 3; // hold last value for N failed results
  static_assert(maxLag + 1 < N, "window too short for MIN_HR");
  static_assert(HOP > 0 && HOP <= N);

  struct Result {
    std::optional<float> hrBpm;
    std::optional<float> spo2;
    float r = 0.0f;
    float correl = 0.0f;
    float autoRatio = 0.0f;
  };

  // One sample pair in; returns true every HOP samples once the window is full
  bool push(float yRed, float yIr) {
    ringRed_[head_] = yRed;
    ringIr_[head_] = yIr;
    head_ = (head_ + 1) % N;
    if (filled_ < N) {
      ++filled_;
    }
    if (++sinceLast_ < HOP || filled_ < N) {
      return false;
    }
    sinceLast_ = 0;

    // Unroll the ring oldest-first into the work buffers (compute() edits them)
    const size_t tail = N - head_;
    arm_copy_f32(ringRed_ + head_, red_, tail);
    arm_copy_f32(ringRed_, red_ + tail, head_);
    arm_copy_f32(ringIr_ + head_, ir_, tail);
    arm_copy_f32(ringIr_, ir_ + tail, head_);
    compute();

    // Bad window -> repeat last good value, up to maxMisses in a row
    res_.hrBpm = hrHold_.update(res_.hrBpm);
    res_.spo2 = spo2Hold_.update(res_.spo2);
    return true;
  }

  const Result &result() const { return res_; }

private:
  void compute() {
    res_ = {};
    detrend(ir_);
    detrend(red_);

    float32_t irSq, redSq, cross;
    arm_power_f32(ir_, N, &irSq);
    arm_power_f32(red_, N, &redSq);
    arm_dot_prod_f32(ir_, red_, N, &cross);
    if (irSq <= 0.0f || redSq <= 0.0f) {
      return;
    }

    // 1. Red/IR correlation: computed and reported, but only used for SpO2
    float32_t norm;
    arm_sqrt_f32(irSq * redSq, &norm);
    res_.correl = cross / norm;

    // 2. Normalized autocorrelation of IR over the HR range
    const float aut0 = irSq / N;
    for (size_t i = 0; i < M; ++i) {
      const size_t lag = minLag - 1 + i;
      float32_t s;
      arm_dot_prod_f32(ir_, ir_ + lag, N - lag, &s);
      acf_[i] = s / float(N - lag) / aut0;
    }

    // 3. Heart period = first strong local peak
    size_t i = 1;
    for (; i + 1 < M; ++i) {
      if (acf_[i] >= minAutoRatio && acf_[i] >= acf_[i - 1] &&
          acf_[i] > acf_[i + 1]) {
        break;
      }
    }
    if (i + 1 >= M) {
      return; // no periodic signal in 40-180 bpm -> HR and SpO2 invalid
    }

    const float a = acf_[i - 1], b = acf_[i], c = acf_[i + 1];
    const float lag =
        float(minLag - 1 + i) + 0.5f * (a - c) / (a - 2.0f * b + c);

    res_.autoRatio = b;
    res_.hrBpm = 60.0f * FS / lag;

    // 4. SpO2 needs red and IR to agree; HR above doesn't
    if (res_.correl < minPearson) {
      return;
    }
    arm_sqrt_f32(redSq / irSq, &res_.r);
    if (res_.r > 0.02f && res_.r < 1.84f) {
      res_.spo2 = (-45.060f * res_.r + 30.354f) * res_.r + 94.845f;
    }
  }

  // Remove mean + least-squares line (pressure/breathing drift within the
  // block)
  static void detrend(float32_t *x) {
    constexpr float xMean = (N - 1) / 2.0f;
    constexpr float sumX2 = float(N) * (float(N) * float(N) - 1.0f) / 12.0f;
    float32_t mean;
    arm_mean_f32(x, N, &mean);
    float beta = 0.0f;
    for (size_t k = 0; k < N; ++k) {
      beta += (float(k) - xMean) * x[k];
    }
    beta /= sumX2;
    for (size_t k = 0; k < N; ++k) {
      x[k] -= mean + beta * (float(k) - xMean);
    }
  }

  // Holds the last good value for up to maxMisses bad results, then gives up
  struct Hold {
    std::optional<float> last;
    int misses = 0;

    // Returns the value to report: v if present, else the held value
    std::optional<float> update(std::optional<float> v) {
      if (v) {
        last = v;
        misses = 0;
        return v;
      }
      if (last && ++misses <= maxMisses) {
        return last;
      }
      last.reset(); // too many misses in a row -> -1 until a fresh good one
      return std::nullopt;
    }
  };

  static constexpr size_t M = maxLag - minLag + 3;

  float32_t red_[N] = {};
  float32_t ir_[N] = {};
  float32_t acf_[M] = {};
  float32_t ringRed_[N] = {};
  float32_t ringIr_[N] = {};
  size_t head_ = 0;
  size_t filled_ = 0;
  size_t sinceLast_ = 0;
  Result res_;
  Hold hrHold_;
  Hold spo2Hold_;
};

#endif
