#ifndef MODULE_PIPELINE_SAMPLE_HPP
#define MODULE_PIPELINE_SAMPLE_HPP

#include "units/absorbance.hpp"
#include <optional>
#include <utility>

namespace pipeline {

class Sample {
  public:
    Sample() : red_(), ir_() {}

    Sample(std::optional<Absorbance> red, std::optional<Absorbance> ir)
        : red_(std::move(red)), ir_(std::move(ir)) {}

    const std::optional<Absorbance> &red() const { return red_; }
    const std::optional<Absorbance> &ir() const { return ir_; }

  private:
    std::optional<Absorbance> red_;
    std::optional<Absorbance> ir_;
};

} // namespace pipeline

#endif // MODULE_PIPELINE_SAMPLE_HPP
