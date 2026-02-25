#pragma once

#include <string>
#include "pybrid/proto/main.pb.h"

namespace anabrid::pybrid::native::utils {

/// @return The protobuf kind field number for the active oneof case, or 0 if none set.
int get_kind_field_number(const pb::MessageV1& msg);

/**
 * @brief Serialize a MessageV1 into a length-prefixed Envelope wire format.
 *
 * @throws std::runtime_error if serialization fails.
 */
std::string serialize_message(const pb::MessageV1& msg);

}  // namespace anabrid::pybrid::native::utils
