#include <gtest/gtest.h>
#include "pybrid/proto/main.pb.h"

TEST(ProtobufTest, ParseMessageV1) {
    pb::MessageV1 msg;
    msg.mutable_describe_command();  // Set any field

    std::string serialized;
    ASSERT_TRUE(msg.SerializeToString(&serialized));

    pb::MessageV1 parsed;
    ASSERT_TRUE(parsed.ParseFromString(serialized));
    ASSERT_TRUE(parsed.has_describe_command());
}

TEST(ProtobufTest, ParseRunDataMessage) {
    pb::MessageV1 msg;
    auto* run_data = msg.mutable_run_data_message();
    run_data->mutable_entity()->set_path("/MAC/Carrier0/ADC0");

    std::string serialized;
    ASSERT_TRUE(msg.SerializeToString(&serialized));

    pb::MessageV1 parsed;
    ASSERT_TRUE(parsed.ParseFromString(serialized));
    ASSERT_EQ(parsed.run_data_message().entity().path(), "/MAC/Carrier0/ADC0");
}

// Test empty message handling
TEST(ProtobufTest, EmptyMessageV1) {
    pb::MessageV1 msg;
    std::string serialized;
    ASSERT_TRUE(msg.SerializeToString(&serialized));

    pb::MessageV1 parsed;
    ASSERT_TRUE(parsed.ParseFromString(serialized));
    EXPECT_EQ(parsed.kind_case(), pb::MessageV1::KIND_NOT_SET);
}

// Test invalid/truncated data
TEST(ProtobufTest, ParseInvalidData) {
    pb::MessageV1 parsed;
    std::string garbage = "not a valid protobuf";
    EXPECT_FALSE(parsed.ParseFromString(garbage));
}

// Test RunState enum serialization
TEST(ProtobufTest, ParseEnumField) {
    pb::RunStateChangeMessage state_change;
    state_change.set_old(pb::RunState::IC);
    state_change.set_new_(pb::RunState::OP);

    std::string serialized;
    ASSERT_TRUE(state_change.SerializeToString(&serialized));

    pb::RunStateChangeMessage parsed;
    ASSERT_TRUE(parsed.ParseFromString(serialized));
    EXPECT_EQ(parsed.old(), pb::RunState::IC);
    EXPECT_EQ(parsed.new_(), pb::RunState::OP);
}
