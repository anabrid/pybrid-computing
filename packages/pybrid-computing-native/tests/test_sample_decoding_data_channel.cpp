/**
 * @file test_sample_decoding_data_channel.cpp
 * @brief Unit tests for DecodedSampleBlob and SampleDecodingDataChannel classes.
 *
 * These tests verify:
 * - DecodedSampleBlob: Binary blob construction and accessor methods
 * - SampleDecodingDataChannel: Sample decoding from protobuf and queue pushing
 *
 * The SampleDecodingDataChannel is used in direct mode to decode DAQ samples
 * from protobuf messages, apply scaling (gain/offset), and push decoded double
 * samples to a thread-safe queue for Python consumption.
 *
 * ## Blob Format
 *
 * The decoded sample blob has the following layout:
 * - [DecodedSampleBlobHeader] - Fixed-size header (24 bytes, 6 x uint32)
 * - [entity_path_chars] - Variable-length entity path string (no null terminator)
 * - [probe_indices] - channel_count x uint32 probe indices (when has_probes == 1)
 * - [padding] - 0-7 bytes to align to 8-byte boundary
 * - [samples_double] - Decoded samples as double array (column-major, same as wire format)
 */

#include <gtest/gtest.h>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

#include "pybrid/buffer.h"
#include "pybrid/channel/sample_decoding_data_channel.h"
#include "pybrid/proto/main.pb.h"

namespace anabrid::pybrid::native {

// =============================================================================
// MockBuffer
// =============================================================================

/**
 * @brief Mock implementation of IBuffer for testing.
 *
 * Captures pushed blobs for verification in tests. Implements the IBuffer
 * interface to allow SampleDecodingDataChannel to push decoded blobs.
 */
class MockBuffer : public IBuffer {
public:
    MockBuffer() = default;
    ~MockBuffer() override = default;

    /**
     * @brief Put an item into the buffer.
     *
     * @param item_size Size of the item in bytes.
     * @param item Pointer to the item data.
     * @throws BufferFullError if buffer is marked as full.
     */
    void put(size_t item_size, const void* item) override {
        if (m_simulate_full) {
            throw BufferFullError("MockBuffer: simulated full");
        }
        const uint8_t* bytes = static_cast<const uint8_t*>(item);
        m_items.emplace_back(bytes, bytes + item_size);
        m_total_bytes += item_size;
    }

    /**
     * @brief Try to put an item without throwing.
     *
     * @param item_size Size of the item in bytes.
     * @param item Pointer to the item data.
     * @return true if item was stored, false if buffer is full.
     */
    bool try_put(size_t item_size, const void* item) override {
        if (m_simulate_full) {
            return false;
        }
        const uint8_t* bytes = static_cast<const uint8_t*>(item);
        m_items.emplace_back(bytes, bytes + item_size);
        m_total_bytes += item_size;
        return true;
    }

    /**
     * @brief Get the next item from the buffer.
     *
     * @param buffer User-supplied buffer to copy data into.
     * @param buffer_size Size of user buffer in bytes.
     * @return Size of retrieved item, or 0 if empty or buffer too small.
     */
    size_t get(void* buffer, size_t buffer_size) override {
        if (m_items.empty()) {
            return 0;
        }
        const auto& item = m_items.front();
        if (buffer_size < item.size()) {
            return 0;  // Buffer too small, item preserved
        }
        std::memcpy(buffer, item.data(), item.size());
        size_t size = item.size();
        m_total_bytes -= size;
        m_items.erase(m_items.begin());
        return size;
    }

    /**
     * @brief Get the number of items currently in the buffer.
     *
     * @return Number of items.
     */
    size_t len() const override {
        return m_items.size();
    }

    /**
     * @brief Get the total byte size of item data in the buffer.
     *
     * @return Total bytes.
     */
    size_t size() const override {
        return m_total_bytes;
    }

    /**
     * @brief Indicates whether this buffer enforces exact capacity constraints.
     *
     * @return true (mock buffer has exact capacity tracking).
     */
    bool has_exact_capacity() const override {
        return true;
    }

    // =========================================================================
    // Test Helpers
    // =========================================================================

    /**
     * @brief Get the last pushed item.
     *
     * @return Reference to the last pushed item, or empty vector if none.
     */
    const std::vector<uint8_t>& last_item() const {
        static std::vector<uint8_t> empty;
        return m_items.empty() ? empty : m_items.back();
    }

    /**
     * @brief Get all pushed items.
     *
     * @return Reference to the vector of all items.
     */
    const std::vector<std::vector<uint8_t>>& items() const {
        return m_items;
    }

    /**
     * @brief Get the number of items pushed.
     *
     * @return Number of items pushed.
     */
    size_t push_count() const {
        return m_items.size();
    }

    /**
     * @brief Clear all captured items.
     */
    void clear() {
        m_items.clear();
        m_total_bytes = 0;
    }

    /**
     * @brief Simulate buffer being full for testing error handling.
     *
     * @param full If true, put() will throw and try_put() will return false.
     */
    void set_simulate_full(bool full) {
        m_simulate_full = full;
    }

private:
    std::vector<std::vector<uint8_t>> m_items;
    size_t m_total_bytes = 0;
    bool m_simulate_full = false;
};

// =============================================================================
// TestableSampleDecodingDataChannel
// =============================================================================

/**
 * @brief Testable subclass of SampleDecodingDataChannel that exposes protected methods.
 *
 * This class allows direct testing of the handle_data_message method which is
 * protected in the base class. It accepts raw serialized protobuf bytes and
 * parses them before calling the base class method.
 */
class TestableSampleDecodingDataChannel : public SampleDecodingDataChannel {
public:
    using SampleDecodingDataChannel::SampleDecodingDataChannel;

    /**
     * @brief Public wrapper for the protected handle_data_message method.
     *
     * Parses the serialized protobuf data and calls the base class method.
     *
     * @param data Pointer to serialized protobuf message.
     * @param len Length of message data.
     */
    void test_handle_data_message(const void* data, size_t len) {
        if (data == nullptr || len == 0) {
            return;
        }

        pb::MessageV1 msg;
        if (!msg.ParseFromArray(data, static_cast<int>(len))) {
            return;  // Invalid protobuf, silently ignore
        }

        handle_data_message(msg);
    }
};

}  // namespace anabrid::pybrid::native

using namespace anabrid::pybrid::native;

// =============================================================================
// DecodedSampleBlob Tests
// =============================================================================

/**
 * @brief Test fixture for DecodedSampleBlob tests.
 *
 * DecodedSampleBlob provides a binary blob format for zero-copy numpy wrapping.
 * The format is: [header][entity_path_chars][samples_double]
 */
class DecodedSampleBlobTest : public ::testing::Test {
protected:
    /**
     * @brief Helper to build a blob and return it.
     *
     * @param entity_path Entity path string.
     * @param samples Vector of double samples.
     * @param channel_count Number of channels.
     * @return Built blob as byte vector.
     */
    std::vector<uint8_t> build_blob(
        const std::string& entity_path,
        const std::vector<double>& samples,
        uint32_t channel_count
    ) {
        return DecodedSampleBlob::build(entity_path, samples, channel_count);
    }
};

/**
 * @brief Test that blob header contains correct entity_path_len.
 */
TEST_F(DecodedSampleBlobTest, HeaderContainsCorrectEntityPathLen) {
    std::string entity_path = "/MAC/Carrier0/ADC0";
    std::vector<double> samples = {1.0, 2.0, 3.0, 4.0};

    std::vector<uint8_t> blob = build_blob(entity_path, samples, 2);
    const auto* header = DecodedSampleBlob::header(blob.data());

    EXPECT_EQ(header->entity_path_len, entity_path.size());
}

/**
 * @brief Test that blob header contains correct sample_count.
 *
 * sample_count should be total_samples / channel_count.
 */
TEST_F(DecodedSampleBlobTest, HeaderContainsCorrectSampleCount) {
    std::string entity_path = "/MAC/Carrier0/ADC0";
    std::vector<double> samples = {1.0, 2.0, 3.0, 4.0, 5.0, 6.0};  // 6 total

    std::vector<uint8_t> blob = build_blob(entity_path, samples, 2);  // 3 samples * 2 channels
    const auto* header = DecodedSampleBlob::header(blob.data());

    EXPECT_EQ(header->sample_count, 3u);  // 6 / 2 = 3
}

/**
 * @brief Test that blob header contains correct channel_count.
 */
TEST_F(DecodedSampleBlobTest, HeaderContainsCorrectChannelCount) {
    std::string entity_path = "/MAC/Carrier0/ADC0";
    std::vector<double> samples = {1.0, 2.0, 3.0, 4.0};

    std::vector<uint8_t> blob = build_blob(entity_path, samples, 4);
    const auto* header = DecodedSampleBlob::header(blob.data());

    EXPECT_EQ(header->channel_count, 4u);
}

/**
 * @brief Test that entity_path accessor returns correct string.
 */
TEST_F(DecodedSampleBlobTest, EntityPathAccessorReturnsCorrectString) {
    std::string entity_path = "/MAC/Carrier0/ADC0";
    std::vector<double> samples = {1.0, 2.0};

    std::vector<uint8_t> blob = build_blob(entity_path, samples, 1);
    std::string_view retrieved_path = DecodedSampleBlob::entity_path(blob.data());

    EXPECT_EQ(retrieved_path, entity_path);
}

/**
 * @brief Test that samples accessor returns correct double array.
 */
TEST_F(DecodedSampleBlobTest, SamplesAccessorReturnsCorrectDoubleArray) {
    std::string entity_path = "/MAC/ADC";
    std::vector<double> samples = {1.5, 2.5, 3.5, 4.5};

    std::vector<uint8_t> blob = build_blob(entity_path, samples, 2);
    const double* retrieved_samples = DecodedSampleBlob::samples(blob.data());

    ASSERT_NE(retrieved_samples, nullptr);
    for (size_t i = 0; i < samples.size(); ++i) {
        EXPECT_DOUBLE_EQ(retrieved_samples[i], samples[i]);
    }
}

/**
 * @brief Test with short entity path (single character).
 */
TEST_F(DecodedSampleBlobTest, ShortEntityPath) {
    std::string entity_path = "/";
    std::vector<double> samples = {1.0};

    std::vector<uint8_t> blob = build_blob(entity_path, samples, 1);
    const auto* header = DecodedSampleBlob::header(blob.data());

    EXPECT_EQ(header->entity_path_len, 1u);
    EXPECT_EQ(DecodedSampleBlob::entity_path(blob.data()), entity_path);
}

/**
 * @brief Test with long entity path.
 */
TEST_F(DecodedSampleBlobTest, LongEntityPath) {
    std::string entity_path = "/00:11:22:33:44:55/Carrier0/Cluster0/MBlock/Lane15/Output";
    std::vector<double> samples = {1.0, 2.0};

    std::vector<uint8_t> blob = build_blob(entity_path, samples, 1);
    const auto* header = DecodedSampleBlob::header(blob.data());

    EXPECT_EQ(header->entity_path_len, entity_path.size());
    EXPECT_EQ(DecodedSampleBlob::entity_path(blob.data()), entity_path);
}

/**
 * @brief Test with single sample and single channel.
 */
TEST_F(DecodedSampleBlobTest, SingleSampleSingleChannel) {
    std::string entity_path = "/MAC/ADC";
    std::vector<double> samples = {42.0};

    std::vector<uint8_t> blob = build_blob(entity_path, samples, 1);
    const auto* header = DecodedSampleBlob::header(blob.data());

    EXPECT_EQ(header->sample_count, 1u);
    EXPECT_EQ(header->channel_count, 1u);
    EXPECT_DOUBLE_EQ(DecodedSampleBlob::samples(blob.data())[0], 42.0);
}

/**
 * @brief Test with many samples and many channels.
 */
TEST_F(DecodedSampleBlobTest, ManySamplesAndChannels) {
    std::string entity_path = "/MAC/ADC";
    std::vector<double> samples;
    const uint32_t channel_count = 8;
    const uint32_t samples_per_channel = 100;

    // Generate test data: samples_per_channel * channel_count total values
    for (uint32_t i = 0; i < samples_per_channel * channel_count; ++i) {
        samples.push_back(static_cast<double>(i) * 0.1);
    }

    std::vector<uint8_t> blob = build_blob(entity_path, samples, channel_count);
    const auto* header = DecodedSampleBlob::header(blob.data());

    EXPECT_EQ(header->sample_count, samples_per_channel);
    EXPECT_EQ(header->channel_count, channel_count);

    const double* retrieved_samples = DecodedSampleBlob::samples(blob.data());
    for (size_t i = 0; i < samples.size(); ++i) {
        EXPECT_DOUBLE_EQ(retrieved_samples[i], samples[i]);
    }
}

/**
 * @brief Test that blob size is calculated correctly.
 *
 * Expected size: aligned_samples_offset + (total_samples * sizeof(double))
 * where aligned_samples_offset accounts for header, path, and padding.
 */
TEST_F(DecodedSampleBlobTest, BlobSizeIsCorrect) {
    std::string entity_path = "/MAC/Carrier0/ADC0";  // 18 chars
    std::vector<double> samples = {1.0, 2.0, 3.0, 4.0};  // 4 doubles

    std::vector<uint8_t> blob = build_blob(entity_path, samples, 2);

    // Calculate aligned offset (same formula as implementation: 8-byte aligned for double)
    size_t base_offset = sizeof(DecodedSampleBlobHeader) + entity_path.size();
    constexpr size_t alignment = alignof(double);  // 8
    size_t aligned_samples_offset = (base_offset + alignment - 1) / alignment * alignment;
    size_t expected_size = aligned_samples_offset + (samples.size() * sizeof(double));

    EXPECT_EQ(blob.size(), expected_size);
}

/**
 * @brief Test that probe indices are stored and retrieved correctly.
 */
TEST_F(DecodedSampleBlobTest, ProbeIndicesStoredAndRetrieved) {
    std::string entity_path = "/MAC/ADC";
    std::vector<double> samples = {1.0, 2.0, 3.0, 4.0, 5.0, 6.0};
    std::vector<uint32_t> probes = {5, 3, 7};

    auto blob = DecodedSampleBlob::build(entity_path, samples, 3,
        DecodedSampleBlob::SAMPLE_TYPE_OP, 0, probes);
    const auto* hdr = DecodedSampleBlob::header(blob.data());

    EXPECT_EQ(hdr->has_probes, 1u);
    EXPECT_EQ(hdr->channel_count, 3u);

    const uint32_t* retrieved_probes = DecodedSampleBlob::probe_indices(blob.data());
    ASSERT_NE(retrieved_probes, nullptr);
    EXPECT_EQ(retrieved_probes[0], 5u);
    EXPECT_EQ(retrieved_probes[1], 3u);
    EXPECT_EQ(retrieved_probes[2], 7u);

    // Samples must still be accessible and correct
    const double* retrieved_samples = DecodedSampleBlob::samples(blob.data());
    for (size_t i = 0; i < samples.size(); ++i) {
        EXPECT_DOUBLE_EQ(retrieved_samples[i], samples[i]);
    }
}

/**
 * @brief Test that probe_indices returns nullptr when has_probes == 0.
 */
TEST_F(DecodedSampleBlobTest, ProbeIndicesNullWhenNotSet) {
    std::string entity_path = "/MAC/ADC";
    std::vector<double> samples = {1.0, 2.0};

    auto blob = DecodedSampleBlob::build(entity_path, samples, 1);
    const auto* hdr = DecodedSampleBlob::header(blob.data());

    EXPECT_EQ(hdr->has_probes, 0u);
    EXPECT_EQ(DecodedSampleBlob::probe_indices(blob.data()), nullptr);
}

/**
 * @brief Test that sample_type is correctly stored in header.
 */
TEST_F(DecodedSampleBlobTest, SampleTypeStoredInHeader) {
    std::string entity_path = "/MAC/ADC";
    std::vector<double> samples = {1.0, 2.0};

    // Test OP type
    auto blob_op = DecodedSampleBlob::build(
        entity_path, samples, 1, DecodedSampleBlob::SAMPLE_TYPE_OP);
    EXPECT_EQ(DecodedSampleBlob::header(blob_op.data())->sample_type,
              DecodedSampleBlob::SAMPLE_TYPE_OP);

    // Test OP_END type
    auto blob_op_end = DecodedSampleBlob::build(
        entity_path, samples, 1, DecodedSampleBlob::SAMPLE_TYPE_OP_END);
    EXPECT_EQ(DecodedSampleBlob::header(blob_op_end.data())->sample_type,
              DecodedSampleBlob::SAMPLE_TYPE_OP_END);
}

// =============================================================================
// SampleDecodingDataChannel Tests
// =============================================================================

/**
 * @brief Test fixture for SampleDecodingDataChannel tests.
 *
 * Sets up a testable channel with mock buffer for verification.
 * The SampleDecodingDataChannel decodes samples from protobuf messages,
 * applies gain/offset scaling, and pushes decoded blobs to an output queue.
 */
class SampleDecodingDataChannelTest : public ::testing::Test {
protected:
    void SetUp() override {
        mock_buffer = std::make_unique<MockBuffer>();
    }

    /**
     * @brief Helper to create a serialized RunDataMessage with float32 data.
     *
     * @param entity_path The entity path for the data source.
     * @param samples Raw float samples (will be serialized as bytes).
     * @param channel_count Number of channels.
     * @param gain Scaling gain (default 1.0).
     * @param offset Scaling offset (default 0.0).
     * @return Serialized protobuf bytes.
     */
    std::vector<uint8_t> create_float32_run_data_message(
        const std::string& entity_path,
        const std::vector<float>& samples,
        uint32_t channel_count,
        double gain = 1.0,
        double offset = 0.0
    ) {
        pb::MessageV1 msg;
        auto* run_data = msg.mutable_run_data_message();

        // Set run info
        auto* run = run_data->mutable_run();
        run->set_id("test-run");
        run->set_chunk(1);

        // Set entity info
        auto* entity = run_data->mutable_entity();
        entity->set_path(entity_path);

        // Set DAQ data
        auto* daq_data = run_data->mutable_data();

        // Serialize float samples as raw bytes
        std::string raw_data;
        raw_data.resize(samples.size() * sizeof(float));
        std::memcpy(raw_data.data(), samples.data(), raw_data.size());
        daq_data->set_data(raw_data);

        // Set data type as float32
        auto* data_type = daq_data->mutable_type();
        auto* float_type = data_type->mutable_float_();
        float_type->set_bitwidth(32);

        // Set channel entries (use same gain/offset)
        for (uint32_t c = 0; c < channel_count; ++c) {
            auto* ch = daq_data->add_channels();
            ch->set_idx(c);
            ch->set_gain(gain);
            ch->set_offset(offset);
            ch->set_probe(c);
        }

        // Set counts
        uint32_t sample_count = samples.size() / channel_count;
        daq_data->set_sample_count(sample_count);
        daq_data->set_channel_count(channel_count);

        std::string serialized;
        msg.SerializeToString(&serialized);
        return std::vector<uint8_t>(serialized.begin(), serialized.end());
    }

    /**
     * @brief Helper to create a serialized RunDataMessage with int16 signed data.
     *
     * @param entity_path The entity path for the data source.
     * @param samples Raw int16 samples (will be serialized as bytes).
     * @param channel_count Number of channels.
     * @param gain Scaling gain.
     * @param offset Scaling offset.
     * @return Serialized protobuf bytes.
     */
    std::vector<uint8_t> create_int16_signed_run_data_message(
        const std::string& entity_path,
        const std::vector<int16_t>& samples,
        uint32_t channel_count,
        double gain,
        double offset
    ) {
        pb::MessageV1 msg;
        auto* run_data = msg.mutable_run_data_message();

        auto* run = run_data->mutable_run();
        run->set_id("test-run");
        run->set_chunk(1);

        auto* entity = run_data->mutable_entity();
        entity->set_path(entity_path);

        auto* daq_data = run_data->mutable_data();

        // Serialize int16 samples as raw bytes
        std::string raw_data;
        raw_data.resize(samples.size() * sizeof(int16_t));
        std::memcpy(raw_data.data(), samples.data(), raw_data.size());
        daq_data->set_data(raw_data);

        // Set data type as int16 signed
        auto* data_type = daq_data->mutable_type();
        auto* integer_type = data_type->mutable_integer();
        integer_type->set_signess(pb::IntegerType::Signed);
        integer_type->set_bitwidth(16);

        // Set channel entries
        for (uint32_t c = 0; c < channel_count; ++c) {
            auto* ch = daq_data->add_channels();
            ch->set_idx(c);
            ch->set_gain(gain);
            ch->set_offset(offset);
            ch->set_probe(c);
        }

        uint32_t sample_count = samples.size() / channel_count;
        daq_data->set_sample_count(sample_count);
        daq_data->set_channel_count(channel_count);

        std::string serialized;
        msg.SerializeToString(&serialized);
        return std::vector<uint8_t>(serialized.begin(), serialized.end());
    }

    /**
     * @brief Helper to create a serialized RunDataMessage with int16 unsigned data.
     *
     * @param entity_path The entity path for the data source.
     * @param samples Raw uint16 samples (will be serialized as bytes).
     * @param channel_count Number of channels.
     * @param gain Scaling gain.
     * @param offset Scaling offset.
     * @return Serialized protobuf bytes.
     */
    std::vector<uint8_t> create_int16_unsigned_run_data_message(
        const std::string& entity_path,
        const std::vector<uint16_t>& samples,
        uint32_t channel_count,
        double gain,
        double offset
    ) {
        pb::MessageV1 msg;
        auto* run_data = msg.mutable_run_data_message();

        auto* run = run_data->mutable_run();
        run->set_id("test-run");
        run->set_chunk(1);

        auto* entity = run_data->mutable_entity();
        entity->set_path(entity_path);

        auto* daq_data = run_data->mutable_data();

        // Serialize uint16 samples as raw bytes
        std::string raw_data;
        raw_data.resize(samples.size() * sizeof(uint16_t));
        std::memcpy(raw_data.data(), samples.data(), raw_data.size());
        daq_data->set_data(raw_data);

        // Set data type as int16 unsigned
        auto* data_type = daq_data->mutable_type();
        auto* integer_type = data_type->mutable_integer();
        integer_type->set_signess(pb::IntegerType::Unsigned);
        integer_type->set_bitwidth(16);

        // Set channel entries
        for (uint32_t c = 0; c < channel_count; ++c) {
            auto* ch = daq_data->add_channels();
            ch->set_idx(c);
            ch->set_gain(gain);
            ch->set_offset(offset);
            ch->set_probe(c);
        }

        uint32_t sample_count = samples.size() / channel_count;
        daq_data->set_sample_count(sample_count);
        daq_data->set_channel_count(channel_count);

        std::string serialized;
        msg.SerializeToString(&serialized);
        return std::vector<uint8_t>(serialized.begin(), serialized.end());
    }

    /**
     * @brief Helper to create a RunDataMessage without scaling information.
     *
     * @param entity_path The entity path for the data source.
     * @param samples Raw float samples.
     * @param channel_count Number of channels.
     * @return Serialized protobuf bytes.
     */
    std::vector<uint8_t> create_run_data_message_no_scaling(
        const std::string& entity_path,
        const std::vector<float>& samples,
        uint32_t channel_count
    ) {
        pb::MessageV1 msg;
        auto* run_data = msg.mutable_run_data_message();

        auto* run = run_data->mutable_run();
        run->set_id("test-run");
        run->set_chunk(1);

        auto* entity = run_data->mutable_entity();
        entity->set_path(entity_path);

        auto* daq_data = run_data->mutable_data();

        // Serialize float samples as raw bytes
        std::string raw_data;
        raw_data.resize(samples.size() * sizeof(float));
        std::memcpy(raw_data.data(), samples.data(), raw_data.size());
        daq_data->set_data(raw_data);

        // Set data type as float32
        auto* data_type = daq_data->mutable_type();
        auto* float_type = data_type->mutable_float_();
        float_type->set_bitwidth(32);

        // NO channel entries set

        uint32_t sample_count = samples.size() / channel_count;
        daq_data->set_sample_count(sample_count);
        daq_data->set_channel_count(channel_count);

        std::string serialized;
        msg.SerializeToString(&serialized);
        return std::vector<uint8_t>(serialized.begin(), serialized.end());
    }

    /**
     * @brief Helper to create a serialized RunDataMessage with double64 data.
     *
     * @param entity_path The entity path for the data source.
     * @param samples Raw double samples (will be serialized as bytes).
     * @param channel_count Number of channels.
     * @param gain Scaling gain (default 1.0).
     * @param offset Scaling offset (default 0.0).
     * @return Serialized protobuf bytes.
     */
    std::vector<uint8_t> create_double64_run_data_message(
        const std::string& entity_path,
        const std::vector<double>& samples,
        uint32_t channel_count,
        double gain = 1.0,
        double offset = 0.0
    ) {
        pb::MessageV1 msg;
        auto* run_data = msg.mutable_run_data_message();

        auto* run = run_data->mutable_run();
        run->set_id("test-run");
        run->set_chunk(1);

        auto* entity = run_data->mutable_entity();
        entity->set_path(entity_path);

        auto* daq_data = run_data->mutable_data();

        // Serialize double samples as raw bytes
        std::string raw_data;
        raw_data.resize(samples.size() * sizeof(double));
        std::memcpy(raw_data.data(), samples.data(), raw_data.size());
        daq_data->set_data(raw_data);

        // Set data type as float64 (double)
        auto* data_type = daq_data->mutable_type();
        auto* float_type = data_type->mutable_float_();
        float_type->set_bitwidth(64);

        // Set channel entries
        for (uint32_t c = 0; c < channel_count; ++c) {
            auto* ch = daq_data->add_channels();
            ch->set_idx(c);
            ch->set_gain(gain);
            ch->set_offset(offset);
            ch->set_probe(c);
        }

        uint32_t sample_count = samples.size() / channel_count;
        daq_data->set_sample_count(sample_count);
        daq_data->set_channel_count(channel_count);

        std::string serialized;
        msg.SerializeToString(&serialized);
        return std::vector<uint8_t>(serialized.begin(), serialized.end());
    }

    /**
     * @brief Helper to create a RunDataMessage with per-channel scaling.
     *
     * @param entity_path The entity path for the data source.
     * @param samples Raw float samples (will be serialized as bytes).
     * @param channel_count Number of channels.
     * @param gains Vector of gains, one per channel.
     * @param offsets Vector of offsets, one per channel.
     * @return Serialized protobuf bytes.
     */
    std::vector<uint8_t> create_float32_run_data_message_per_channel_scaling(
        const std::string& entity_path,
        const std::vector<float>& samples,
        uint32_t channel_count,
        const std::vector<double>& gains,
        const std::vector<double>& offsets
    ) {
        pb::MessageV1 msg;
        auto* run_data = msg.mutable_run_data_message();

        auto* run = run_data->mutable_run();
        run->set_id("test-run");
        run->set_chunk(1);

        auto* entity = run_data->mutable_entity();
        entity->set_path(entity_path);

        auto* daq_data = run_data->mutable_data();

        // Serialize float samples as raw bytes
        std::string raw_data;
        raw_data.resize(samples.size() * sizeof(float));
        std::memcpy(raw_data.data(), samples.data(), raw_data.size());
        daq_data->set_data(raw_data);

        // Set data type as float32
        auto* data_type = daq_data->mutable_type();
        auto* float_type = data_type->mutable_float_();
        float_type->set_bitwidth(32);

        // Set per-channel gain/offset
        for (uint32_t c = 0; c < channel_count; ++c) {
            auto* ch = daq_data->add_channels();
            ch->set_idx(c);
            ch->set_gain(gains[c]);
            ch->set_offset(offsets[c]);
            ch->set_probe(c);
        }

        uint32_t sample_count = samples.size() / channel_count;
        daq_data->set_sample_count(sample_count);
        daq_data->set_channel_count(channel_count);

        std::string serialized;
        msg.SerializeToString(&serialized);
        return std::vector<uint8_t>(serialized.begin(), serialized.end());
    }

    /**
     * @brief Helper to create a RunDataMessage where wire channel_count exceeds
     *        the number of scaling entries.
     *
     * Simulates the LUCIDAC hardware behaviour of rounding the channel count
     * up to the next power of 2 (e.g. 3 configured ADC channels → 4 wire
     * channels). Only the first ``scaling_channels`` channels carry meaningful
     * data; the remaining wire channels are padding filled with 0.0f.
     *
     * @param entity_path     Entity path string.
     * @param real_samples    Samples for the meaningful channels only (column-major).
     * @param scaling_channels Number of meaningful channels (= number of scaling entries).
     * @param wire_channels   Total wire channel count (power-of-2 rounded up).
     * @param gains           Per-channel gains for the meaningful channels.
     * @param offsets         Per-channel offsets for the meaningful channels.
     * @return Serialized protobuf bytes.
     */
    std::vector<uint8_t> create_run_data_message_with_extra_wire_channels(
        const std::string& entity_path,
        const std::vector<float>& real_samples,
        uint32_t scaling_channels,
        uint32_t wire_channels,
        const std::vector<double>& gains,
        const std::vector<double>& offsets
    ) {
        // real_samples is column-major for scaling_channels channels.
        // We need to expand to wire_channels by inserting padding (0.0f)
        // for the extra channels at every sample point.
        uint32_t sample_count = real_samples.size() / scaling_channels;
        std::vector<float> wire_samples(sample_count * wire_channels, 0.0f);
        for (uint32_t s = 0; s < sample_count; ++s) {
            for (uint32_t ch = 0; ch < scaling_channels; ++ch) {
                wire_samples[s * wire_channels + ch] =
                    real_samples[s * scaling_channels + ch];
            }
        }

        pb::MessageV1 msg;
        auto* run_data = msg.mutable_run_data_message();

        auto* run = run_data->mutable_run();
        run->set_id("test-run");
        run->set_chunk(0);

        auto* entity = run_data->mutable_entity();
        entity->set_path(entity_path);

        auto* daq_data = run_data->mutable_data();

        std::string raw_data;
        raw_data.resize(wire_samples.size() * sizeof(float));
        std::memcpy(raw_data.data(), wire_samples.data(), raw_data.size());
        daq_data->set_data(raw_data);

        auto* data_type = daq_data->mutable_type();
        auto* float_type = data_type->mutable_float_();
        float_type->set_bitwidth(32);

        // Only add channel entries for the meaningful channels.
        for (uint32_t c = 0; c < scaling_channels; ++c) {
            auto* ch = daq_data->add_channels();
            ch->set_idx(c);
            ch->set_gain(gains[c]);
            ch->set_offset(offsets[c]);
            ch->set_probe(c);
        }

        daq_data->set_sample_count(sample_count);
        daq_data->set_channel_count(wire_channels);

        std::string serialized;
        msg.SerializeToString(&serialized);
        return std::vector<uint8_t>(serialized.begin(), serialized.end());
    }

    /**
     * @brief Helper to create a serialized RunDataMessage with explicit run_id and chunk.
     *
     * Unlike the other helpers which hardcode run_id="test-run" and chunk=1,
     * this allows full control over the Run fields for chunk sequence testing.
     *
     * @param entity_path The entity path for the data source.
     * @param samples Raw float samples (will be serialized as bytes).
     * @param channel_count Number of channels.
     * @param run_id Run identifier string.
     * @param chunk Chunk sequence number.
     * @param gain Scaling gain (default 1.0).
     * @param offset Scaling offset (default 0.0).
     * @return Serialized protobuf bytes.
     */
    std::vector<uint8_t> create_float32_run_data_message_with_chunk(
        const std::string& entity_path,
        const std::vector<float>& samples,
        uint32_t channel_count,
        const std::string& run_id,
        uint32_t chunk,
        double gain = 1.0,
        double offset = 0.0
    ) {
        pb::MessageV1 msg;
        auto* run_data = msg.mutable_run_data_message();

        auto* run = run_data->mutable_run();
        run->set_id(run_id);
        run->set_chunk(chunk);

        auto* entity = run_data->mutable_entity();
        entity->set_path(entity_path);

        auto* daq_data = run_data->mutable_data();

        std::string raw_data;
        raw_data.resize(samples.size() * sizeof(float));
        std::memcpy(raw_data.data(), samples.data(), raw_data.size());
        daq_data->set_data(raw_data);

        auto* data_type = daq_data->mutable_type();
        auto* float_type = data_type->mutable_float_();
        float_type->set_bitwidth(32);

        for (uint32_t c = 0; c < channel_count; ++c) {
            auto* ch = daq_data->add_channels();
            ch->set_idx(c);
            ch->set_gain(gain);
            ch->set_offset(offset);
            ch->set_probe(c);
        }

        uint32_t sample_count = samples.size() / channel_count;
        daq_data->set_sample_count(sample_count);
        daq_data->set_channel_count(channel_count);

        std::string serialized;
        msg.SerializeToString(&serialized);
        return std::vector<uint8_t>(serialized.begin(), serialized.end());
    }

    /**
     * @brief Helper to create a serialized RunDataEndMessage with explicit run_id and chunk.
     *
     * @param entity_path The entity path for the data source.
     * @param samples Raw float samples (will be serialized as bytes).
     * @param channel_count Number of channels.
     * @param run_id Run identifier string.
     * @param chunk Chunk sequence number.
     * @param gain Scaling gain (default 1.0).
     * @param offset Scaling offset (default 0.0).
     * @return Serialized protobuf bytes.
     */
    std::vector<uint8_t> create_float32_run_data_end_message_with_chunk(
        const std::string& entity_path,
        const std::vector<float>& samples,
        uint32_t channel_count,
        const std::string& run_id,
        uint32_t chunk,
        double gain = 1.0,
        double offset = 0.0
    ) {
        pb::MessageV1 msg;
        auto* run_data_end = msg.mutable_run_data_end_message();

        auto* run = run_data_end->mutable_run();
        run->set_id(run_id);
        run->set_chunk(chunk);

        auto* entity = run_data_end->mutable_entity();
        entity->set_path(entity_path);

        auto* daq_data = run_data_end->mutable_data();

        std::string raw_data;
        raw_data.resize(samples.size() * sizeof(float));
        std::memcpy(raw_data.data(), samples.data(), raw_data.size());
        daq_data->set_data(raw_data);

        auto* data_type = daq_data->mutable_type();
        auto* float_type = data_type->mutable_float_();
        float_type->set_bitwidth(32);

        for (uint32_t c = 0; c < channel_count; ++c) {
            auto* ch = daq_data->add_channels();
            ch->set_idx(c);
            ch->set_gain(gain);
            ch->set_offset(offset);
            ch->set_probe(c);
        }

        uint32_t sample_count = samples.size() / channel_count;
        daq_data->set_sample_count(sample_count);
        daq_data->set_channel_count(channel_count);

        std::string serialized;
        msg.SerializeToString(&serialized);
        return std::vector<uint8_t>(serialized.begin(), serialized.end());
    }

    std::unique_ptr<MockBuffer> mock_buffer;
};

/**
 * @brief Test that channel can be instantiated and starts in correct initial state.
 */
TEST_F(SampleDecodingDataChannelTest, CanInstantiate) {
    TestableSampleDecodingDataChannel channel;

    EXPECT_FALSE(channel.is_running());
    EXPECT_EQ(channel.current_run_state(), pb::NEW);
}

/**
 * @brief Test that channel decodes RunDataMessage and pushes blob to queue.
 */
TEST_F(SampleDecodingDataChannelTest, DecodesRunDataMessageAndPushesToQueue) {
    TestableSampleDecodingDataChannel channel;
    channel.set_output_queue(mock_buffer.get());

    // Wire (col-major, 2ch x 2samp): [ch0_s0, ch1_s0, ch0_s1, ch1_s1]
    std::vector<float> samples = {1.0f, 2.0f, 3.0f, 4.0f};
    std::vector<uint8_t> message = create_float32_run_data_message(
        "/MAC/Carrier0/ADC0", samples, 2);

    channel.test_handle_data_message(message.data(), message.size());

    ASSERT_EQ(mock_buffer->push_count(), 1u);

    // Verify the blob content
    const auto& blob = mock_buffer->last_item();
    const auto* header = DecodedSampleBlob::header(blob.data());

    EXPECT_EQ(header->sample_count, 2u);  // 4 samples / 2 channels
    EXPECT_EQ(header->channel_count, 2u);
    EXPECT_EQ(header->sample_type, DecodedSampleBlob::SAMPLE_TYPE_OP);

    // Output stays col-major (same as wire): [ch0_s0, ch1_s0, ch0_s1, ch1_s1]
    const double* decoded_samples = DecodedSampleBlob::samples(blob.data());
    EXPECT_DOUBLE_EQ(decoded_samples[0], 1.0);  // ch0_s0
    EXPECT_DOUBLE_EQ(decoded_samples[1], 2.0);  // ch1_s0
    EXPECT_DOUBLE_EQ(decoded_samples[2], 3.0);  // ch0_s1
    EXPECT_DOUBLE_EQ(decoded_samples[3], 4.0);  // ch1_s1
}

/**
 * @brief Test that DaqScaling (gain/offset) is applied to samples.
 *
 * Formula: decoded_sample = raw_sample * gain + offset
 */
TEST_F(SampleDecodingDataChannelTest, AppliesDaqScalingToSamples) {
    TestableSampleDecodingDataChannel channel;
    channel.set_output_queue(mock_buffer.get());

    // Raw samples: [1.0, 2.0, 3.0, 4.0]
    // Gain: 2.0, Offset: 10.0
    // Expected: [12.0, 14.0, 16.0, 18.0]
    std::vector<float> raw_samples = {1.0f, 2.0f, 3.0f, 4.0f};
    std::vector<uint8_t> message = create_float32_run_data_message(
        "/MAC/ADC", raw_samples, 1, 2.0, 10.0);

    channel.test_handle_data_message(message.data(), message.size());

    ASSERT_EQ(mock_buffer->push_count(), 1u);

    const auto& blob = mock_buffer->last_item();
    const double* decoded_samples = DecodedSampleBlob::samples(blob.data());

    EXPECT_DOUBLE_EQ(decoded_samples[0], 12.0);  // 1.0 * 2.0 + 10.0
    EXPECT_DOUBLE_EQ(decoded_samples[1], 14.0);  // 2.0 * 2.0 + 10.0
    EXPECT_DOUBLE_EQ(decoded_samples[2], 16.0);  // 3.0 * 2.0 + 10.0
    EXPECT_DOUBLE_EQ(decoded_samples[3], 18.0);  // 4.0 * 2.0 + 10.0
}

/**
 * @brief Test that multiple channels are handled correctly.
 *
 * Wire and output are both column-major for (num_channels x num_samples):
 *   [ch0_s0, ch1_s0, ch2_s0, ch3_s0, ch0_s1, ch1_s1, ...]
 * Python uses reshape(order="F") for zero-copy channel separation.
 */
TEST_F(SampleDecodingDataChannelTest, HandlesMultipleChannelsCorrectly) {
    TestableSampleDecodingDataChannel channel;
    channel.set_output_queue(mock_buffer.get());

    // 4 channels, 3 samples per channel = 12 total samples
    // Col-major: sample points interleaved
    //   s0: [10, 20, 30, 40], s1: [11, 21, 31, 41], s2: [12, 22, 32, 42]
    std::vector<float> samples = {
        10.0f, 20.0f, 30.0f, 40.0f,   // sample point 0
        11.0f, 21.0f, 31.0f, 41.0f,   // sample point 1
        12.0f, 22.0f, 32.0f, 42.0f,   // sample point 2
    };

    std::vector<uint8_t> message = create_float32_run_data_message(
        "/MAC/ADC", samples, 4);

    channel.test_handle_data_message(message.data(), message.size());

    ASSERT_EQ(mock_buffer->push_count(), 1u);

    const auto& blob = mock_buffer->last_item();
    const auto* header = DecodedSampleBlob::header(blob.data());

    EXPECT_EQ(header->sample_count, 3u);   // 12 / 4 = 3
    EXPECT_EQ(header->channel_count, 4u);

    // Output stays col-major (same order as input, scaling=1.0 identity)
    const double* decoded_samples = DecodedSampleBlob::samples(blob.data());
    // s0: ch0=10, ch1=20, ch2=30, ch3=40
    EXPECT_DOUBLE_EQ(decoded_samples[0], 10.0);
    EXPECT_DOUBLE_EQ(decoded_samples[1], 20.0);
    EXPECT_DOUBLE_EQ(decoded_samples[2], 30.0);
    EXPECT_DOUBLE_EQ(decoded_samples[3], 40.0);
    // s1: ch0=11, ch1=21, ch2=31, ch3=41
    EXPECT_DOUBLE_EQ(decoded_samples[4], 11.0);
    EXPECT_DOUBLE_EQ(decoded_samples[5], 21.0);
    EXPECT_DOUBLE_EQ(decoded_samples[6], 31.0);
    EXPECT_DOUBLE_EQ(decoded_samples[7], 41.0);
    // s2: ch0=12, ch1=22, ch2=32, ch3=42
    EXPECT_DOUBLE_EQ(decoded_samples[8], 12.0);
    EXPECT_DOUBLE_EQ(decoded_samples[9], 22.0);
    EXPECT_DOUBLE_EQ(decoded_samples[10], 32.0);
    EXPECT_DOUBLE_EQ(decoded_samples[11], 42.0);
}

/**
 * @brief Test that int16 signed data is decoded and scaled correctly.
 *
 * int16 range: -32768 to 32767
 * Formula: decoded_sample = (double)raw_int16 * gain + offset
 */
TEST_F(SampleDecodingDataChannelTest, DecodesInt16SignedDataCorrectly) {
    TestableSampleDecodingDataChannel channel;
    channel.set_output_queue(mock_buffer.get());

    // Raw int16 samples: [0, 1000, -1000, 32767]
    // Gain: 0.001, Offset: 0.0
    // Expected: [0.0, 1.0, -1.0, 32.767]
    std::vector<int16_t> raw_samples = {0, 1000, -1000, 32767};
    std::vector<uint8_t> message = create_int16_signed_run_data_message(
        "/MAC/ADC", raw_samples, 1, 0.001, 0.0);

    channel.test_handle_data_message(message.data(), message.size());

    ASSERT_EQ(mock_buffer->push_count(), 1u);

    const auto& blob = mock_buffer->last_item();
    const double* decoded_samples = DecodedSampleBlob::samples(blob.data());

    EXPECT_DOUBLE_EQ(decoded_samples[0], 0.0);
    EXPECT_DOUBLE_EQ(decoded_samples[1], 1.0);
    EXPECT_DOUBLE_EQ(decoded_samples[2], -1.0);
    EXPECT_NEAR(decoded_samples[3], 32.767, 0.001);
}

/**
 * @brief Test that int16 unsigned data is decoded and scaled correctly.
 *
 * uint16 range: 0 to 65535
 * Formula: decoded_sample = (double)raw_uint16 * gain + offset
 */
TEST_F(SampleDecodingDataChannelTest, DecodesInt16UnsignedDataCorrectly) {
    TestableSampleDecodingDataChannel channel;
    channel.set_output_queue(mock_buffer.get());

    // Raw uint16 samples: [0, 1000, 32768, 65535]
    // Gain: 0.001, Offset: -32.768
    // Expected: [-32.768, -31.768, 0.0, 32.767]
    std::vector<uint16_t> raw_samples = {0, 1000, 32768, 65535};
    std::vector<uint8_t> message = create_int16_unsigned_run_data_message(
        "/MAC/ADC", raw_samples, 1, 0.001, -32.768);

    channel.test_handle_data_message(message.data(), message.size());

    ASSERT_EQ(mock_buffer->push_count(), 1u);

    const auto& blob = mock_buffer->last_item();
    const double* decoded_samples = DecodedSampleBlob::samples(blob.data());

    EXPECT_NEAR(decoded_samples[0], -32.768, 0.001);
    EXPECT_NEAR(decoded_samples[1], -31.768, 0.001);
    EXPECT_NEAR(decoded_samples[2], 0.0, 0.001);
    EXPECT_NEAR(decoded_samples[3], 32.767, 0.001);
}

/**
 * @brief Test that null output queue is handled gracefully (no crash).
 */
TEST_F(SampleDecodingDataChannelTest, HandlesNullOutputQueueGracefully) {
    TestableSampleDecodingDataChannel channel;
    // Do NOT set output queue - it remains nullptr

    std::vector<float> samples = {1.0f, 2.0f};
    std::vector<uint8_t> message = create_float32_run_data_message(
        "/MAC/ADC", samples, 1);

    // Should not crash
    channel.test_handle_data_message(message.data(), message.size());

    // No buffer, so nothing was pushed (verify mock_buffer wasn't touched)
    EXPECT_EQ(mock_buffer->push_count(), 0u);
}

/**
 * @brief Test that invalid protobuf is handled gracefully.
 */
TEST_F(SampleDecodingDataChannelTest, HandlesInvalidProtobufGracefully) {
    TestableSampleDecodingDataChannel channel;
    channel.set_output_queue(mock_buffer.get());

    std::vector<uint8_t> garbage = {0x00, 0xFF, 0xAB, 0xCD, 0xEF, 0x12, 0x34};

    // Should not crash
    channel.test_handle_data_message(garbage.data(), garbage.size());

    // Invalid message should not produce output
    EXPECT_EQ(mock_buffer->push_count(), 0u);
}

/**
 * @brief Test that empty data is handled gracefully.
 */
TEST_F(SampleDecodingDataChannelTest, HandlesEmptyDataGracefully) {
    TestableSampleDecodingDataChannel channel;
    channel.set_output_queue(mock_buffer.get());

    // Test with nullptr
    channel.test_handle_data_message(nullptr, 0);
    EXPECT_EQ(mock_buffer->push_count(), 0u);

    // Test with valid pointer but zero length
    uint8_t dummy = 0;
    channel.test_handle_data_message(&dummy, 0);
    EXPECT_EQ(mock_buffer->push_count(), 0u);
}

/**
 * @brief Test that missing channels entries causes the message to be silently
 *        dropped (the runtime_error is caught by TestableSampleDecodingDataChannel
 *        which ignores parse failures).
 */
TEST_F(SampleDecodingDataChannelTest, RejectsMissingChannelsEntries) {
    TestableSampleDecodingDataChannel channel;
    channel.set_output_queue(mock_buffer.get());

    std::vector<float> samples = {1.0f, 2.0f, 3.0f, 4.0f};
    std::vector<uint8_t> message = create_run_data_message_no_scaling(
        "/MAC/ADC", samples, 1);

    // decode_daq_data now throws when channels_size() == 0;
    // handle_data_message does not catch, so we expect the exception to propagate.
    EXPECT_THROW(
        channel.test_handle_data_message(message.data(), message.size()),
        std::runtime_error
    );

    EXPECT_EQ(mock_buffer->push_count(), 0u);
}

/**
 * @brief Test that entity path is preserved in output blob.
 */
TEST_F(SampleDecodingDataChannelTest, PreservesEntityPathInOutputBlob) {
    TestableSampleDecodingDataChannel channel;
    channel.set_output_queue(mock_buffer.get());

    std::string entity_path = "/00:11:22:33:44:55/Carrier0/ADC0";
    std::vector<float> samples = {1.0f, 2.0f};
    std::vector<uint8_t> message = create_float32_run_data_message(
        entity_path, samples, 1);

    channel.test_handle_data_message(message.data(), message.size());

    ASSERT_EQ(mock_buffer->push_count(), 1u);

    const auto& blob = mock_buffer->last_item();
    std::string_view retrieved_path = DecodedSampleBlob::entity_path(blob.data());

    EXPECT_EQ(retrieved_path, entity_path);
}

/**
 * @brief Test decoding with zero gain (all samples become offset).
 */
TEST_F(SampleDecodingDataChannelTest, HandlesZeroGain) {
    TestableSampleDecodingDataChannel channel;
    channel.set_output_queue(mock_buffer.get());

    std::vector<float> samples = {100.0f, 200.0f, 300.0f};
    std::vector<uint8_t> message = create_float32_run_data_message(
        "/MAC/ADC", samples, 1, 0.0, 5.0);  // gain=0.0, offset=5.0

    channel.test_handle_data_message(message.data(), message.size());

    ASSERT_EQ(mock_buffer->push_count(), 1u);

    const auto& blob = mock_buffer->last_item();
    const double* decoded_samples = DecodedSampleBlob::samples(blob.data());

    // All samples should be equal to offset (0.0 * any + 5.0 = 5.0)
    EXPECT_DOUBLE_EQ(decoded_samples[0], 5.0);
    EXPECT_DOUBLE_EQ(decoded_samples[1], 5.0);
    EXPECT_DOUBLE_EQ(decoded_samples[2], 5.0);
}

/**
 * @brief Test decoding with negative gain (inverts samples).
 */
TEST_F(SampleDecodingDataChannelTest, HandlesNegativeGain) {
    TestableSampleDecodingDataChannel channel;
    channel.set_output_queue(mock_buffer.get());

    std::vector<float> samples = {1.0f, 2.0f, 3.0f};
    std::vector<uint8_t> message = create_float32_run_data_message(
        "/MAC/ADC", samples, 1, -1.0, 0.0);  // gain=-1.0, offset=0.0

    channel.test_handle_data_message(message.data(), message.size());

    ASSERT_EQ(mock_buffer->push_count(), 1u);

    const auto& blob = mock_buffer->last_item();
    const double* decoded_samples = DecodedSampleBlob::samples(blob.data());

    EXPECT_DOUBLE_EQ(decoded_samples[0], -1.0);
    EXPECT_DOUBLE_EQ(decoded_samples[1], -2.0);
    EXPECT_DOUBLE_EQ(decoded_samples[2], -3.0);
}

/**
 * @brief Test that non-data messages are ignored.
 *
 * Only run_data_message should produce output; other message types
 * (like extract_command, config_response) should be ignored.
 */
TEST_F(SampleDecodingDataChannelTest, IgnoresNonDataMessages) {
    TestableSampleDecodingDataChannel channel;
    channel.set_output_queue(mock_buffer.get());

    // Create an extract_command message (not a data message)
    pb::MessageV1 msg;
    auto* cmd = msg.mutable_extract_command();
    cmd->set_recursive(true);
    cmd->set_specification(true);

    std::string serialized;
    msg.SerializeToString(&serialized);
    std::vector<uint8_t> message(serialized.begin(), serialized.end());

    channel.test_handle_data_message(message.data(), message.size());

    // Non-data message should not produce output
    EXPECT_EQ(mock_buffer->push_count(), 0u);
}

/**
 * @brief Test handling of message with empty sample data.
 */
TEST_F(SampleDecodingDataChannelTest, HandlesMessageWithEmptySampleData) {
    TestableSampleDecodingDataChannel channel;
    channel.set_output_queue(mock_buffer.get());

    // Create message with zero samples
    pb::MessageV1 msg;
    auto* run_data = msg.mutable_run_data_message();

    auto* run = run_data->mutable_run();
    run->set_id("test-run");
    run->set_chunk(1);

    auto* entity = run_data->mutable_entity();
    entity->set_path("/MAC/ADC");

    auto* daq_data = run_data->mutable_data();
    daq_data->set_data("");  // Empty data
    daq_data->set_sample_count(0);
    daq_data->set_channel_count(1);

    std::string serialized;
    msg.SerializeToString(&serialized);
    std::vector<uint8_t> message(serialized.begin(), serialized.end());

    // Should not crash
    channel.test_handle_data_message(message.data(), message.size());

    // Empty sample data should not produce output (empty blob filtered)
    // Implementation may or may not produce an empty blob
}

/**
 * @brief Test that multiple messages can be processed sequentially.
 */
TEST_F(SampleDecodingDataChannelTest, ProcessesMultipleMessagesSequentially) {
    TestableSampleDecodingDataChannel channel;
    channel.set_output_queue(mock_buffer.get());

    // Process three messages
    for (int i = 0; i < 3; ++i) {
        std::vector<float> samples = {static_cast<float>(i), static_cast<float>(i + 1)};
        std::vector<uint8_t> message = create_float32_run_data_message(
            "/MAC/ADC" + std::to_string(i), samples, 1);

        channel.test_handle_data_message(message.data(), message.size());
    }

    EXPECT_EQ(mock_buffer->push_count(), 3u);

    // Verify each blob has the correct entity path
    const auto& items = mock_buffer->items();
    for (int i = 0; i < 3; ++i) {
        std::string_view path = DecodedSampleBlob::entity_path(items[i].data());
        EXPECT_EQ(path, "/MAC/ADC" + std::to_string(i));
    }
}

/**
 * @brief Test that run_data_end_message is decoded with OP_END sample type.
 */
TEST_F(SampleDecodingDataChannelTest, DecodesRunDataEndMessageWithOpEndType) {
    TestableSampleDecodingDataChannel channel;
    channel.set_output_queue(mock_buffer.get());

    // Create a RunDataEndMessage
    pb::MessageV1 msg;
    auto* run_data_end = msg.mutable_run_data_end_message();

    auto* run = run_data_end->mutable_run();
    run->set_id("test-run");
    run->set_chunk(1);

    auto* entity = run_data_end->mutable_entity();
    entity->set_path("/MAC/ADC");

    auto* daq_data = run_data_end->mutable_data();

    // Create sample data
    std::vector<float> samples = {1.0f, 2.0f};
    std::string raw_data;
    raw_data.resize(samples.size() * sizeof(float));
    std::memcpy(raw_data.data(), samples.data(), raw_data.size());
    daq_data->set_data(raw_data);

    auto* data_type = daq_data->mutable_type();
    auto* float_type = data_type->mutable_float_();
    float_type->set_bitwidth(32);

    auto* ch = daq_data->add_channels();
    ch->set_idx(0);
    ch->set_gain(1.0);
    ch->set_offset(0.0);
    ch->set_probe(0);

    daq_data->set_sample_count(2);
    daq_data->set_channel_count(1);

    std::string serialized;
    msg.SerializeToString(&serialized);
    std::vector<uint8_t> message(serialized.begin(), serialized.end());

    channel.test_handle_data_message(message.data(), message.size());

    ASSERT_EQ(mock_buffer->push_count(), 1u);

    const auto& blob = mock_buffer->last_item();
    const auto* header = DecodedSampleBlob::header(blob.data());

    // Verify sample_type is OP_END
    EXPECT_EQ(header->sample_type, DecodedSampleBlob::SAMPLE_TYPE_OP_END);
}

/**
 * @brief Test that probe indices from DaqData.channels are embedded in the output blob.
 */
TEST_F(SampleDecodingDataChannelTest, ProbeIndicesEmbeddedInOutputBlob) {
    TestableSampleDecodingDataChannel channel;
    channel.set_output_queue(mock_buffer.get());

    // 2 channels, 2 samples each
    std::vector<float> samples = {1.0f, 2.0f, 3.0f, 4.0f};
    std::vector<uint8_t> message = create_float32_run_data_message(
        "/MAC/ADC", samples, 2);

    channel.test_handle_data_message(message.data(), message.size());

    ASSERT_EQ(mock_buffer->push_count(), 1u);

    const auto& blob = mock_buffer->last_item();
    const auto* header = DecodedSampleBlob::header(blob.data());

    EXPECT_EQ(header->has_probes, 1u);

    const uint32_t* probes = DecodedSampleBlob::probe_indices(blob.data());
    ASSERT_NE(probes, nullptr);
    // create_float32_run_data_message sets ch->set_probe(c) for c in [0, channel_count)
    EXPECT_EQ(probes[0], 0u);
    EXPECT_EQ(probes[1], 1u);

    // Samples must still be correct
    const double* decoded_samples = DecodedSampleBlob::samples(blob.data());
    EXPECT_DOUBLE_EQ(decoded_samples[0], 1.0);
    EXPECT_DOUBLE_EQ(decoded_samples[1], 2.0);
    EXPECT_DOUBLE_EQ(decoded_samples[2], 3.0);
    EXPECT_DOUBLE_EQ(decoded_samples[3], 4.0);
}

/**
 * @brief Test that per-channel scaling applies different gains to each channel.
 *
 * Wire and output are both col-major: [ch0_s0, ch1_s0, ch0_s1, ch1_s1, ...]
 * Each channel should have its own gain and offset applied.
 */
TEST_F(SampleDecodingDataChannelTest, AppliesPerChannelScaling) {
    TestableSampleDecodingDataChannel channel;
    channel.set_output_queue(mock_buffer.get());

    // 2 channels, 3 samples per channel = 6 total samples
    // Col-major: [ch0_s0, ch1_s0, ch0_s1, ch1_s1, ch0_s2, ch1_s2]
    std::vector<float> raw_samples = {1.0f, 10.0f, 2.0f, 20.0f, 3.0f, 30.0f};

    // Channel 0: gain=2.0, offset=0.0
    // Channel 1: gain=0.1, offset=5.0
    std::vector<double> gains = {2.0, 0.1};
    std::vector<double> offsets = {0.0, 5.0};

    std::vector<uint8_t> message = create_float32_run_data_message_per_channel_scaling(
        "/MAC/ADC", raw_samples, 2, gains, offsets);

    channel.test_handle_data_message(message.data(), message.size());

    ASSERT_EQ(mock_buffer->push_count(), 1u);

    const auto& blob = mock_buffer->last_item();
    const auto* header = DecodedSampleBlob::header(blob.data());
    const double* decoded_samples = DecodedSampleBlob::samples(blob.data());

    EXPECT_EQ(header->channel_count, 2u);
    EXPECT_EQ(header->sample_count, 3u);

    // Output stays col-major with scaling applied:
    // s0: ch0=1.0*2.0+0.0=2.0, ch1=10.0*0.1+5.0=6.0
    EXPECT_DOUBLE_EQ(decoded_samples[0], 2.0);
    EXPECT_DOUBLE_EQ(decoded_samples[1], 6.0);
    // s1: ch0=2.0*2.0+0.0=4.0, ch1=20.0*0.1+5.0=7.0
    EXPECT_DOUBLE_EQ(decoded_samples[2], 4.0);
    EXPECT_DOUBLE_EQ(decoded_samples[3], 7.0);
    // s2: ch0=3.0*2.0+0.0=6.0, ch1=30.0*0.1+5.0=8.0
    EXPECT_DOUBLE_EQ(decoded_samples[4], 6.0);
    EXPECT_DOUBLE_EQ(decoded_samples[5], 8.0);
}

/**
 * @brief Test that double64 (float64) data type is decoded correctly.
 *
 * This verifies support for 64-bit floating point DAQ data.
 */
TEST_F(SampleDecodingDataChannelTest, DecodesDouble64DataCorrectly) {
    TestableSampleDecodingDataChannel channel;
    channel.set_output_queue(mock_buffer.get());

    // Use double values that cannot be exactly represented in float32
    // to verify we're actually reading double precision data
    std::vector<double> raw_samples = {
        1.1234567890123456,
        2.9876543210987654,
        -3.141592653589793,
        1e-15  // Very small number
    };

    std::vector<uint8_t> message = create_double64_run_data_message(
        "/MAC/ADC", raw_samples, 1, 1.0, 0.0);

    channel.test_handle_data_message(message.data(), message.size());

    ASSERT_EQ(mock_buffer->push_count(), 1u);

    const auto& blob = mock_buffer->last_item();
    const auto* header = DecodedSampleBlob::header(blob.data());
    const double* decoded_samples = DecodedSampleBlob::samples(blob.data());

    EXPECT_EQ(header->sample_count, 4u);
    EXPECT_EQ(header->channel_count, 1u);

    // Verify exact double precision is preserved
    EXPECT_DOUBLE_EQ(decoded_samples[0], 1.1234567890123456);
    EXPECT_DOUBLE_EQ(decoded_samples[1], 2.9876543210987654);
    EXPECT_DOUBLE_EQ(decoded_samples[2], -3.141592653589793);
    EXPECT_DOUBLE_EQ(decoded_samples[3], 1e-15);
}

/**
 * @brief Test that double64 data with scaling is handled correctly.
 */
TEST_F(SampleDecodingDataChannelTest, DecodesDouble64DataWithScaling) {
    TestableSampleDecodingDataChannel channel;
    channel.set_output_queue(mock_buffer.get());

    std::vector<double> raw_samples = {1.0, 2.0, 3.0};
    // gain=2.5, offset=0.5
    std::vector<uint8_t> message = create_double64_run_data_message(
        "/MAC/ADC", raw_samples, 1, 2.5, 0.5);

    channel.test_handle_data_message(message.data(), message.size());

    ASSERT_EQ(mock_buffer->push_count(), 1u);

    const auto& blob = mock_buffer->last_item();
    const double* decoded_samples = DecodedSampleBlob::samples(blob.data());

    // 1.0*2.5+0.5=3.0, 2.0*2.5+0.5=5.5, 3.0*2.5+0.5=8.0
    EXPECT_DOUBLE_EQ(decoded_samples[0], 3.0);
    EXPECT_DOUBLE_EQ(decoded_samples[1], 5.5);
    EXPECT_DOUBLE_EQ(decoded_samples[2], 8.0);
}

/**
 * @brief Test that wire channels exceeding scaling entries are filtered out.
 *
 * Simulates the LUCIDAC hardware rounding 3 configured ADC channels up to
 * 4 wire channels. Only the 3 channels referenced by scaling entries should
 * appear in the decoded output.
 */
TEST_F(SampleDecodingDataChannelTest, FiltersExtraWireChannelsByScaling) {
    TestableSampleDecodingDataChannel channel;
    channel.set_output_queue(mock_buffer.get());

    // 3 meaningful channels, 4 wire channels (LUCIDAC rounds up to power of 2).
    // 2 samples per channel, column-major for the 3 real channels:
    //   s0: ch0=1.0, ch1=2.0, ch2=3.0
    //   s1: ch0=4.0, ch1=5.0, ch2=6.0
    std::vector<float> real_samples = {1.0f, 2.0f, 3.0f, 4.0f, 5.0f, 6.0f};
    std::vector<double> gains   = {1.0, 1.0, 1.0};
    std::vector<double> offsets  = {0.0, 0.0, 0.0};

    std::vector<uint8_t> message = create_run_data_message_with_extra_wire_channels(
        "/MAC/ADC", real_samples, 3, 4, gains, offsets);

    channel.test_handle_data_message(message.data(), message.size());

    ASSERT_EQ(mock_buffer->push_count(), 1u);

    const auto& blob = mock_buffer->last_item();
    const auto* header = DecodedSampleBlob::header(blob.data());

    // Effective channel count must be 3, not 4.
    EXPECT_EQ(header->channel_count, 3u);
    EXPECT_EQ(header->sample_count, 2u);

    const double* decoded = DecodedSampleBlob::samples(blob.data());
    // Column-major output: [ch0_s0, ch1_s0, ch2_s0, ch0_s1, ch1_s1, ch2_s1]
    EXPECT_DOUBLE_EQ(decoded[0], 1.0);
    EXPECT_DOUBLE_EQ(decoded[1], 2.0);
    EXPECT_DOUBLE_EQ(decoded[2], 3.0);
    EXPECT_DOUBLE_EQ(decoded[3], 4.0);
    EXPECT_DOUBLE_EQ(decoded[4], 5.0);
    EXPECT_DOUBLE_EQ(decoded[5], 6.0);
}

/**
 * @brief Test channel filtering with non-identity scaling (gain + offset).
 *
 * Same wire-vs-scaling mismatch as above, but with gain=2.0 and offset=10.0
 * to verify that scaling is applied correctly to the filtered channels.
 */
TEST_F(SampleDecodingDataChannelTest, FiltersExtraWireChannelsWithScaling) {
    TestableSampleDecodingDataChannel channel;
    channel.set_output_queue(mock_buffer.get());

    // 2 meaningful channels, 4 wire channels.
    // 1 sample: s0: ch0=1.0, ch1=2.0
    std::vector<float> real_samples = {1.0f, 2.0f};
    std::vector<double> gains   = {2.0, 0.5};
    std::vector<double> offsets  = {10.0, -1.0};

    std::vector<uint8_t> message = create_run_data_message_with_extra_wire_channels(
        "/MAC/ADC", real_samples, 2, 4, gains, offsets);

    channel.test_handle_data_message(message.data(), message.size());

    ASSERT_EQ(mock_buffer->push_count(), 1u);

    const auto& blob = mock_buffer->last_item();
    const auto* header = DecodedSampleBlob::header(blob.data());

    EXPECT_EQ(header->channel_count, 2u);
    EXPECT_EQ(header->sample_count, 1u);

    const double* decoded = DecodedSampleBlob::samples(blob.data());
    // ch0: 1.0 * 2.0 + 10.0 = 12.0
    // ch1: 2.0 * 0.5 + (-1.0) = 0.0
    EXPECT_DOUBLE_EQ(decoded[0], 12.0);
    EXPECT_DOUBLE_EQ(decoded[1], 0.0);
}

// =============================================================================
// Chunk Passthrough Tests
// =============================================================================

/**
 * @brief Test that an OP blob carries the correct chunk_number from protobuf.
 *
 * Send a single OP message with chunk=42, verify the blob header has
 * chunk_number == 42.
 */
TEST_F(SampleDecodingDataChannelTest, ChunkPassthrough_OpBlob) {
    TestableSampleDecodingDataChannel channel;
    channel.set_output_queue(mock_buffer.get());

    std::vector<float> samples = {1.0f, 2.0f, 3.0f, 4.0f};

    auto message = create_float32_run_data_message_with_chunk(
        "/MAC/Carrier0", samples, 2, "run-chunk42", 42);
    channel.test_handle_data_message(message.data(), message.size());

    ASSERT_EQ(mock_buffer->push_count(), 1u);

    const auto& blob = mock_buffer->last_item();
    const auto* header = DecodedSampleBlob::header(blob.data());
    EXPECT_EQ(header->chunk_number, 42u);
    EXPECT_EQ(header->sample_type, DecodedSampleBlob::SAMPLE_TYPE_OP);
    EXPECT_EQ(header->channel_count, 2u);
    EXPECT_EQ(header->sample_count, 2u);
}

/**
 * @brief Test that an OP_END blob carries the correct chunk_number from protobuf.
 */
TEST_F(SampleDecodingDataChannelTest, ChunkPassthrough_OpEndBlob) {
    TestableSampleDecodingDataChannel channel;
    channel.set_output_queue(mock_buffer.get());

    std::vector<float> samples = {1.0f, 2.0f};

    auto message = create_float32_run_data_end_message_with_chunk(
        "/MAC/Carrier0", samples, 1, "run-chunk7", 7);
    channel.test_handle_data_message(message.data(), message.size());

    ASSERT_EQ(mock_buffer->push_count(), 1u);

    const auto& blob = mock_buffer->last_item();
    const auto* header = DecodedSampleBlob::header(blob.data());
    EXPECT_EQ(header->chunk_number, 7u);
    EXPECT_EQ(header->sample_type, DecodedSampleBlob::SAMPLE_TYPE_OP_END);
    EXPECT_EQ(header->channel_count, 1u);
    EXPECT_EQ(header->sample_count, 2u);
}

/**
 * @brief Test sequential chunks: send chunks 0, 1, 2 and verify all three
 *        blobs carry the correct chunk_number in order.
 */
TEST_F(SampleDecodingDataChannelTest, ChunkPassthrough_Sequential) {
    TestableSampleDecodingDataChannel channel;
    channel.set_output_queue(mock_buffer.get());

    std::vector<float> samples = {1.0f, 2.0f, 3.0f, 4.0f};

    for (uint32_t chunk = 0; chunk < 3; ++chunk) {
        auto message = create_float32_run_data_message_with_chunk(
            "/MAC/Carrier0", samples, 2, "run-seq", chunk);
        channel.test_handle_data_message(message.data(), message.size());
    }

    ASSERT_EQ(mock_buffer->push_count(), 3u);

    for (uint32_t i = 0; i < 3; ++i) {
        const auto& blob = mock_buffer->items()[i];
        const auto* header = DecodedSampleBlob::header(blob.data());
        EXPECT_EQ(header->chunk_number, i)
            << "Blob " << i << " has wrong chunk_number";
        EXPECT_EQ(header->sample_type, DecodedSampleBlob::SAMPLE_TYPE_OP);
    }
}

// =============================================================================
// Alignment Tests
// =============================================================================

/**
 * @brief Test that blob samples are correctly aligned for double access.
 *
 * This test verifies that samples are 8-byte aligned regardless of
 * entity path length to prevent unaligned memory access issues.
 */
TEST_F(DecodedSampleBlobTest, SamplesAreAlignedForDoubleAccess) {
    // Test various entity path lengths that would cause misalignment
    // without proper padding (header is 20 bytes, so path lengths of
    // 1, 2, 3, 5, 6, 7 would be misaligned)
    std::vector<size_t> path_lengths = {1, 2, 3, 4, 5, 6, 7, 8, 9, 15, 17, 23};

    for (size_t len : path_lengths) {
        std::string entity_path(len, 'X');
        std::vector<double> samples = {1.5, 2.5, 3.5};

        std::vector<uint8_t> blob = DecodedSampleBlob::build(entity_path, samples, 1);
        const double* sample_ptr = DecodedSampleBlob::samples(blob.data());

        // Verify pointer is 8-byte aligned
        uintptr_t addr = reinterpret_cast<uintptr_t>(sample_ptr);
        EXPECT_EQ(addr % 8, 0u) << "Samples not aligned for path length " << len;

        // Verify samples are still accessible and correct
        EXPECT_DOUBLE_EQ(sample_ptr[0], 1.5);
        EXPECT_DOUBLE_EQ(sample_ptr[1], 2.5);
        EXPECT_DOUBLE_EQ(sample_ptr[2], 3.5);
    }
}

/**
 * @brief Test that chunk_number defaults to 0 when not specified.
 */
TEST_F(DecodedSampleBlobTest, ChunkNumberDefaultsToZero) {
    std::string entity_path = "/MAC/ADC";
    std::vector<double> samples = {1.0, 2.0};

    auto blob = DecodedSampleBlob::build(entity_path, samples, 1);
    const auto* header = DecodedSampleBlob::header(blob.data());
    EXPECT_EQ(header->chunk_number, 0u);
}

/**
 * @brief Test that chunk_number is correctly stored in header.
 */
TEST_F(DecodedSampleBlobTest, ChunkNumberStoredInHeader) {
    std::string entity_path = "/MAC/ADC";
    std::vector<double> samples = {1.0, 2.0};

    auto blob = DecodedSampleBlob::build(entity_path, samples, 1,
        DecodedSampleBlob::SAMPLE_TYPE_OP, 99);
    const auto* header = DecodedSampleBlob::header(blob.data());
    EXPECT_EQ(header->chunk_number, 99u);
}
