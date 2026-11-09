#ifndef MODULE_PIPELINE_PIPELINE_HPP
#define MODULE_PIPELINE_PIPELINE_HPP

#include "algorithms/oximeter.hpp"
#include "apnea/apnea.hpp"
#include "pipeline/sample.hpp"
#include "pipeline/stream.hpp"
#include <cstddef>
#include <expected>
#include <optional>
#include <span>

using apnea::ZScore;
using apnea::Model;
using apnea::WindowVitals;

namespace pipeline {

inline constexpr std::size_t kPipelineFsHz = 100;
static_assert(kPipelineFsHz == 100, "the apnea model was trained on 100 sps");

// y = bandpass(A - A[0]), 0.2 to 4.5 Hz
//    - highpass removes the slow drift (baseline)
//    - lowpass removes noise
//    - A[0] (first sample) is subtracted so the highpass doesn't ring
//    for several seconds at startup. a constant offset doesn't change the
//    highpass output otherwise
//
// The DC component is thrown away on purpose. Because of the -ln in
// Absorbance, the pulse in absorbance is already normalized by DC:
//
//   i = I_dc + i_ac,  with i_ac << I_dc
//   -ln(i) = -ln(I_dc) - ln(1 + i_ac/I_dc) ≈ -ln(I_dc) - i_ac/I_dc
//
// so the bandpass output is about -AC/DC. Then:
//   SpO2:            R = (AC/DC)_red / (AC/DC)_ir = amp(y_red) / amp(y_ir)
//   perfusion index: PI = AC/DC = amp(y_ir)
//
// Neither one needs a separate DC value
inline constexpr float kSlowFcHz = 0.2f;
inline constexpr float kFastFcHz = 4.5f;

/// Range of errors that can be returned from the pipeline
enum class Error {
    Internal,
    Misuse,
};

/// Alias to possible responses of the pipeline
template<typename T>
using Result = std::expected<T, Error>;

/// The result of a given pipeline operation
struct Processed {
    float y_red = 0.0f;
    float y_ir = 0.0f;
    std::optional<RfOximeter<kPipelineFsHz>::Result> vitals;
    std::optional<float> apnea_likelihood;
};

class Pipeline {
  public:
    Pipeline()
        : red_(kSlowFcHz, kFastFcHz, float(kPipelineFsHz)),
          ir_(kSlowFcHz, kFastFcHz, float(kPipelineFsHz)),
          oximeter_(),
          zscore_(),
          model_(),
          vitals_(),
          window_steps_(0) {}

    Processed step(Sample s);

    /// Completely transform the input buffer into the output buffer
    Result<void> run(std::span<Sample> in, std::span<Processed> out);

  private:
    std::optional<float> apnea_step(float y_red);

    Stream red_;
    Stream ir_;

    RfOximeter<kPipelineFsHz> oximeter_;
    ZScore zscore_;
    Model model_;
    WindowVitals vitals_;

    int window_steps_;
};

};  // namespace pipeline

#endif  // MODULE_PIPELINE_PIPELINE_HPP
