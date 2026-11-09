#ifndef MODULE_PIPELINE_STREAM_HPP
#define MODULE_PIPELINE_STREAM_HPP

#include "filters/bandpass.hpp"
#include "units/absorbance.hpp"
#include <optional>
#include <utility>

namespace pipeline {

class Stream {
  public:
    Stream(float low_hz, float high_hz, float fs_hz)
        : filter_(low_hz, high_hz, fs_hz), offset_(), y_(0.0f) {}

    // Center the input on the first sample so the highpass starts settled
    std::optional<float> adjust_offset(std::optional<Absorbance> absorbance) {
        if (!absorbance) {
            return std::nullopt;
        }

        const float a = std::move(*absorbance).into_inner();
        if (!offset_) {
            offset_ = a;
        }

        return a - *offset_;
    }

    float bandpass(std::optional<float> centered) {
        if (centered) {
            y_ = filter_.update(*centered);
        }

        return y_;
    }

  private:
    BandPass filter_;
    std::optional<float> offset_;
    float y_;
};

} // namespace pipeline

#endif // MODULE_PIPELINE_STREAM_HPP
