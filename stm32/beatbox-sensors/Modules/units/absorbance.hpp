#ifndef MODULE_UNITS_ABSORBANCE_HPP
#define MODULE_UNITS_ABSORBANCE_HPP

#include <cmath>
#include <cstdint>
#include <optional>

class Absorbance {
  public:
    /// Converts the adc counts into an absorbance value
    /// 
    /// ## Option
    /// If counts are 0, then the absorbance returned is monostate
    static std::optional<Absorbance> try_from_counts(uint32_t counts) {
        if (counts == 0) {
            return std::nullopt;
        }

        return Absorbance(-std::log(float(counts)));
    }

    /// Consume the value and turn it into the `Absorbance` type
    float into_inner() const && { return std::move(this->value_); }

  private:
    explicit Absorbance(float value) : value_(value) {}

    float value_;
};

#endif // MODULE_UNITS_ABSORBANCE_HPP
