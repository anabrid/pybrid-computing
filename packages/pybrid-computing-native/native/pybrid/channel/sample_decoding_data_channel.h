#pragma once

#include "pybrid/channel/data_channel.h"
#include "pybrid/buffer.h"
#include "pybrid/proto/main.pb.h"

#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

namespace anabrid::pybrid::native
{

/**
 * @brief Header for decoded sample binary blob.
 *
 * Placed at the start of every decoded sample blob.
 *
 * Layout:
 * - [DecodedSampleBlobHeader] - This fixed-size header (20 bytes)
 * - [entity_path_chars] - Variable-length entity path string (no null terminator)
 * - [padding] - 0-7 bytes to align samples to 8-byte boundary
 * - [samples_double] - Decoded samples as double array (column-major, same as wire format)
 */
struct DecodedSampleBlobHeader {
    uint32_t entity_path_len;  ///< Length of entity path string in bytes
    uint32_t sample_count;     ///< Number of samples per channel
    uint32_t channel_count;    ///< Number of channels
    uint32_t sample_type;      ///< Sample type: 0 = OP, 1 = OP_END
    uint32_t chunk_number;     ///< Chunk sequence number from the protobuf message
};

/// Binary blob format optimized for zero-copy numpy array wrapping on the Python side.
class DecodedSampleBlob {
public:
    /// Sample type for OP state data (from run_data_message)
    static constexpr uint32_t SAMPLE_TYPE_OP = 0;

    /// Sample type for OP_END state data (from run_data_end_message)
    static constexpr uint32_t SAMPLE_TYPE_OP_END = 1;

    static std::vector<uint8_t> build(
        const std::string& entity_path,
        const std::vector<double>& samples,
        uint32_t channel_count,
        uint32_t sample_type = SAMPLE_TYPE_OP,
        uint32_t chunk_number = 0
    );

    static const DecodedSampleBlobHeader* header(const uint8_t* data);

    /// @return String view of entity path (no null terminator)
    static std::string_view entity_path(const uint8_t* data);

    /// @return Pointer to first sample (double array, column-major, same as wire format)
    static const double* samples(const uint8_t* data);
};

// LUCIDAC hardware rounds channel count up to the next power of 2; scaling entries
// select which channels are meaningful and determine the effective channel count.
// set_output_queue() must be called before start().
class SampleDecodingDataChannel : public DataChannel {
public:
    /// @throws std::logic_error if called after start()
    void set_output_queue(IBuffer* queue);

protected:
    void handle_data_message(pb::MessageV1& message) override;

    struct DecodedDaqResult {
        std::vector<double> samples;   ///< Decoded sample values (column-major)
        uint32_t channel_count;        ///< Effective channel count
    };

    DecodedDaqResult decode_daq_data(const pb::DaqData& daq_data);

    IBuffer* m_output_queue = nullptr;
};

}  // namespace anabrid::pybrid::native
