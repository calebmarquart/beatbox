#include "pipeline/pipeline.hpp"
#include <utility>

namespace pipeline {

Processed Pipeline::step(Sample s) {
    Processed out{};

    out.y_red = red_.bandpass(red_.adjust_offset(s.red()));
    out.y_ir = ir_.bandpass(ir_.adjust_offset(s.ir()));

    if (oximeter_.push(out.y_red, out.y_ir)) {
        const auto &r = oximeter_.result();
        out.vitals = r;
        vitals_.add(r.spo2, r.hrBpm);
    }

    // after the oximeter, so a window's last vitals result is counted
    out.apnea_likelihood = apnea_step(out.y_red);

    return out;
}

Result<void> Pipeline::run(std::span<Sample> in, std::span<Processed> out) {
    if (out.size() < in.size()) {
        return std::unexpected(Error::Misuse);
    }

    for (std::size_t i = 0; i < in.size(); ++i) {
        out[i] = step(std::move(in[i]));
    }

    return {};
}

std::optional<float> Pipeline::apnea_step(float y_red) {
    const std::optional<float> z = zscore_.step(y_red);
    if (!z) {
        return std::nullopt; // z-score warm-up (first 256 samples)
    }

    model_.step(*z);
    if (++window_steps_ < apnea::weights::kWindowSamples) {
        return std::nullopt;
    }

    const float p = vitals_.ready() ? model_.probability(vitals_.features()) : -1.0f;
    model_.reset();
    vitals_.reset();
    window_steps_ = 0;

    return p;
}

} // namespace pipeline
