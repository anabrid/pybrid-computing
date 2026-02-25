#include "pybrid/channel/sample_decoding_data_channel.h"

#include <cstring>
#include <stdexcept>

namespace anabrid::pybrid::native
{

namespace {

/// Round value up to the next multiple of 8 (double alignment).
constexpr size_t align_up_to_double(size_t value) {
    constexpr size_t alignment = alignof(double);  // 8
    return (value + alignment - 1) / alignment * alignment;
}

}  // anonymous namespace

std::vector<uint8_t> DecodedSampleBlob::build(
    const std::string& entity_path,
    const std::vector<double>& samples,
    uint32_t channel_count,
    uint32_t sample_type,
    uint32_t chunk_number
) {
    uint32_t sample_count = channel_count > 0
        ? static_cast<uint32_t>(samples.size() / channel_count)
        : 0;

    size_t base_offset = sizeof(DecodedSampleBlobHeader) + entity_path.size();
    size_t aligned_samples_offset = align_up_to_double(base_offset);
    size_t total_size = aligned_samples_offset + samples.size() * sizeof(double);

    std::vector<uint8_t> blob(total_size, 0);

    DecodedSampleBlobHeader header{};
    header.entity_path_len = static_cast<uint32_t>(entity_path.size());
    header.sample_count = sample_count;
    header.channel_count = channel_count;
    header.sample_type = sample_type;
    header.chunk_number = chunk_number;

    std::memcpy(blob.data(), &header, sizeof(header));

    size_t offset = sizeof(DecodedSampleBlobHeader);
    std::memcpy(blob.data() + offset, entity_path.data(), entity_path.size());

    std::memcpy(blob.data() + aligned_samples_offset, samples.data(), samples.size() * sizeof(double));

    return blob;
}

const DecodedSampleBlobHeader* DecodedSampleBlob::header(const uint8_t* data) {
    return reinterpret_cast<const DecodedSampleBlobHeader*>(data);
}

std::string_view DecodedSampleBlob::entity_path(const uint8_t* data) {
    const auto* hdr = header(data);
    const char* path_start = reinterpret_cast<const char*>(data + sizeof(DecodedSampleBlobHeader));
    return std::string_view(path_start, hdr->entity_path_len);
}

const double* DecodedSampleBlob::samples(const uint8_t* data) {
    const auto* hdr = header(data);
    size_t base_offset = sizeof(DecodedSampleBlobHeader) + hdr->entity_path_len;
    size_t aligned_offset = align_up_to_double(base_offset);
    return reinterpret_cast<const double*>(data + aligned_offset);
}

void SampleDecodingDataChannel::set_output_queue(IBuffer* queue) {
    if (is_running()) {
        throw std::logic_error("Cannot call set_output_queue after start()");
    }
    m_output_queue = queue;
}

void SampleDecodingDataChannel::handle_data_message(pb::MessageV1& message) {
    if (message.has_run_data_message()) {
        const pb::RunDataMessage& data_msg = message.run_data_message();

        if (data_msg.has_entity() && data_msg.has_data()) {
            auto result = decode_daq_data(data_msg.data());

            uint32_t chunk = 0;
            if (data_msg.has_run()) {
                chunk = data_msg.run().chunk();
            }

            std::vector<uint8_t> blob = DecodedSampleBlob::build(
                data_msg.entity().path(),
                result.samples,
                result.channel_count,
                DecodedSampleBlob::SAMPLE_TYPE_OP,
                chunk
            );

            if (m_output_queue && !blob.empty()) {
                m_output_queue->put(blob.size(), blob.data());
            }
        }
    }
    else if (message.has_run_data_end_message()) {
        const pb::RunDataEndMessage& data_msg = message.run_data_end_message();

        if (data_msg.has_entity() && data_msg.has_data()) {
            auto result = decode_daq_data(data_msg.data());

            uint32_t chunk = 0;
            if (data_msg.has_run()) {
                chunk = data_msg.run().chunk();
            }

            std::vector<uint8_t> blob = DecodedSampleBlob::build(
                data_msg.entity().path(),
                result.samples,
                result.channel_count,
                DecodedSampleBlob::SAMPLE_TYPE_OP_END,
                chunk
            );

            if (m_output_queue && !blob.empty()) {
                m_output_queue->put(blob.size(), blob.data());
            }
        }
    }
}

namespace {

template<typename T>
double read_sample(const char* data, size_t index) {
    return static_cast<double>(reinterpret_cast<const T*>(data)[index]);
}

using SampleReader = double (*)(const char*, size_t);

struct DataTypeInfo {
    SampleReader reader;
    size_t element_size;
};

DataTypeInfo get_data_type_info(const pb::DataType& data_type) {
    if (data_type.has_float_()) {
        const pb::FloatType& float_t = data_type.float_();
        if (float_t.bitwidth() == 32) {
            return {read_sample<float>, sizeof(float)};
        } else if (float_t.bitwidth() == 64) {
            return {read_sample<double>, sizeof(double)};
        }
    } else if (data_type.has_integer()) {
        const pb::IntegerType& int_t = data_type.integer();
        bool is_signed = (int_t.signess() == pb::IntegerType_Signedness_Signed);

        if (is_signed) {
            if (int_t.bitwidth() == 16) {
                return {read_sample<int16_t>, sizeof(int16_t)};
            } else if (int_t.bitwidth() == 32) {
                return {read_sample<int32_t>, sizeof(int32_t)};
            }
        } else {
            if (int_t.bitwidth() == 16) {
                return {read_sample<uint16_t>, sizeof(uint16_t)};
            } else if (int_t.bitwidth() == 32) {
                return {read_sample<uint32_t>, sizeof(uint32_t)};
            }
        }
    }

    return {nullptr, 0};
}

}  // anonymous namespace

SampleDecodingDataChannel::DecodedDaqResult
SampleDecodingDataChannel::decode_daq_data(const pb::DaqData& daq_data) {
    const uint32_t wire_channels = daq_data.channel_count();
    const uint32_t num_samples = daq_data.sample_count();
    const size_t total_wire_values = static_cast<size_t>(wire_channels) * num_samples;

    if (total_wire_values == 0 || daq_data.data().empty()) {
        return {{}, 0};
    }

    DataTypeInfo type_info = get_data_type_info(daq_data.type());

    if (type_info.reader == nullptr) {
        return {{}, 0};
    }

    size_t required_size = total_wire_values * type_info.element_size;
    if (daq_data.data().size() < required_size) {
        return {{}, 0};
    }

    const char* raw_data = daq_data.data().c_str();

    // The LUCIDAC hardware rounds the channel count up to the next power of 2,
    // so the wire may carry more channels than configured. The scaling entries
    // tell us which channels are meaningful — use their count as the authoritative
    // channel number.
    const int scaling_count = daq_data.scaling_size();
    const uint32_t eff_channels = (scaling_count > 0)
        ? static_cast<uint32_t>(scaling_count)
        : wire_channels;

    // When scaling is present, each entry's idx selects a wire channel.
    // When absent, identity mapping (channel i → wire channel i).
    std::vector<uint32_t> channel_indices(eff_channels);
    std::vector<double> gains(eff_channels, 1.0);
    std::vector<double> offsets(eff_channels, 0.0);

    if (scaling_count > 0) {
        for (int s = 0; s < scaling_count; ++s) {
            channel_indices[s] = daq_data.scaling(s).idx();
            gains[s] = daq_data.scaling(s).gain();
            offsets[s] = daq_data.scaling(s).offset();
        }
    } else {
        for (uint32_t i = 0; i < eff_channels; ++i) {
            channel_indices[i] = i;
        }
    }

    // Output in column-major order (same convention as wire format):
    //   [ch0_s0, ch1_s0, ..., ch0_s1, ch1_s1, ...]
    // but only for the channels selected by the scaling entries.
    const size_t total_output = static_cast<size_t>(eff_channels) * num_samples;
    std::vector<double> decoded(total_output);

    for (uint32_t sample = 0; sample < num_samples; ++sample) {
        for (uint32_t ch = 0; ch < eff_channels; ++ch) {
            size_t wire_idx = static_cast<size_t>(sample) * wire_channels + channel_indices[ch];
            double raw_value = type_info.reader(raw_data, wire_idx);
            decoded[static_cast<size_t>(sample) * eff_channels + ch] =
                raw_value * gains[ch] + offsets[ch];
        }
    }

    return {std::move(decoded), eff_channels};
}

}  // namespace anabrid::pybrid::native
