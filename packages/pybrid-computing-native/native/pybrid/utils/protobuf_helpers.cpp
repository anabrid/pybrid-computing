#include "pybrid/utils/protobuf_helpers.h"

#include <stdexcept>

#include "google/protobuf/descriptor.h"
#include "google/protobuf/message.h"

namespace anabrid::pybrid::native::utils {

int get_kind_field_number(const pb::MessageV1& msg) {
    const google::protobuf::Descriptor* descriptor = msg.GetDescriptor();
    const google::protobuf::OneofDescriptor* kind_oneof =
        descriptor->FindOneofByName("kind");
    if (!kind_oneof) return 0;

    const google::protobuf::Reflection* reflection = msg.GetReflection();
    const google::protobuf::FieldDescriptor* active =
        reflection->GetOneofFieldDescriptor(msg, kind_oneof);
    return active ? active->number() : 0;
}

std::string serialize_message(const pb::MessageV1& msg) {
    pb::Envelope env;
    *env.mutable_message_v1() = msg;
    std::string bytes;
    if (!env.SerializeToString(&bytes)) {
        throw std::runtime_error("serialize_message: protobuf serialization failed");
    }
    return bytes;
}

}  // namespace anabrid::pybrid::native::utils
