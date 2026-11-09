#ifndef MODULE_PIPELINE_HISTORY_HPP
#define MODULE_PIPELINE_HISTORY_HPP

#include "algorithms/oximeter.hpp"
#include "apnea/model_weights.hpp"
#include <array>
#include <cstddef>

namespace pipeline {

template <std::size_t FS> struct History {
  using Oximeter = RfOximeter<FS>;

  std::array<float, Oximeter::N> oximeter_red{};
  std::array<float, Oximeter::N> oximeter_ir{};
  std::array<float, apnea::weights::kZscoreN> zscore{};
};

} // namespace pipeline

#endif // MODULE_PIPELINE_HISTORY_HPP
