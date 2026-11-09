#ifndef MODULE_PIPELINE_SCRATCH_HPP
#define MODULE_PIPELINE_SCRATCH_HPP

#include "algorithms/oximeter.hpp"
#include <array>
#include <cstddef>

namespace pipeline {

template <std::size_t FS> struct Scratch {
  using Oximeter = RfOximeter<FS>;

  std::array<float, Oximeter::N> red;
  std::array<float, Oximeter::N> ir;
  std::array<float, Oximeter::maxLag - Oximeter::minLag + 3> acf;
};

} // namespace pipeline

#endif // MODULE_PIPELINE_SCRATCH_HPP
