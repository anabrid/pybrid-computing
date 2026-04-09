#include "updater.h"
#include <future>
#include <numeric>
#include <ranges>
#include <filesystem>
#include <fstream>

#include "proto/main.pb.h"

using namespace pb;
using namespace filesystem;

/**
 * AUXILIARY FUNCTIONS
 */
std::vector<uint8_t> hex2bin(const std::vector<uint8_t>& hex_data)
{
  std::vector<uint8_t> result;
  result.reserve(FW_MAX_SIZE);
  uint8_t buffer[256];
  uint32_t current_addr = 0;

  for (size_t hex_idx = 0; hex_idx < hex_data.size();)
  {
    auto colon = hex_data[hex_idx++];
    if (std::isspace(colon))
      continue;
    if (colon != ':')
      return {};

    uint8_t bytes = decode_8(hex_data, hex_idx);
    uint16_t addr = decode_16(hex_data, hex_idx);
    uint8_t kind = decode_8(hex_data, hex_idx);

    for (size_t buf_idx = 0; buf_idx < bytes; buf_idx++)
      buffer[buf_idx] = decode_8(hex_data, hex_idx);

    {
      uint8_t checksum = decode_8(hex_data, hex_idx);
      uint8_t sum = bytes + (addr >> 8) + (addr & 0xFF) + kind;
      for (size_t i = 0; i < bytes; i++) sum += buffer[i];
      sum += checksum;
      if (sum != 0) return {};
    }

    if (kind == Eof){
      return result;
    }else if (kind == ExtLinAddr){
      current_addr = buffer[0];
      current_addr <<= 8;
      current_addr += buffer[1];
      current_addr <<= 16;
    }else if (kind == Data){
      if(current_addr < FW_BASE_ADDR)
        return {};
      uint32_t full_addr = current_addr + addr - FW_BASE_ADDR;
      if (full_addr + bytes > result.size())
        result.resize(full_addr + bytes);
      std::memcpy(&result[full_addr], buffer, bytes);
    }else if (kind == StartLinAddr){
    }else{
      return {};
    }
  }

  return {};
}

/**
 * OTAUpdater
 */
OTAUpdater::UpdateResult OTAUpdater::execute(
    string firmware_path,
    const vector<string>& targets, 
    uint16_t port)
{
    vector<int> indices(targets.size());
    iota(indices.begin(), indices.end(), 0);

    auto firmware = read_firmware(firmware_path);
    if(firmware.is_err())
        return UpdateResult::err(firmware.err_value());

    m_firmware_bin.clear();
    m_firmware_bin = hex2bin(firmware.ok_value());
    if(m_firmware_bin.empty())
        return UpdateResult::err("Unable to convert firmware to binary data!");

    

    // connect to all endpoints in parallel and upload
    bool is_err = false;
    vector<unique_ptr<TCPTransport>> transports(targets.size(), nullptr);
    auto fan_connect = [this, &targets, &transports, port, &is_err](int index)
    {
        auto res = this->connect_to(targets[index], port);
        if(res.is_ok())
        {
            transports[index].swap(res.ok_value());
        }
        else
        {
            is_err = true;
            cerr << res.err_value() << endl;
        }
    };
    auto connect_futures = indices | views::transform([&](int index) {
        async(fan_connect, index);
    });
    for(auto& fut : connect_futures)
        fut.get();

    if(!is_err)
        return UpdateResult::err("Unable to connect to all targets.");

    return UpdateResult::ok(true);
}

OTAUpdater::ReadResult
OTAUpdater::read_firmware(const string& firmware_path)
{
    // load firmware and convert to bianry
    if(!exists(firmware_path))
        return ReadResult::err_fmt("Firmware not found at %s", firmware_path);

    vector<uint8_t> firmware_hex;
    basic_ifstream<uint8_t> firmware_in(firmware_path);
    if(!firmware_in.good())
        return ReadResult::err_fmt("Unable to read firmware file %s", firmware_path);

    auto& end = firmware_in.seekg(0, ios_base::end);
    const size_t firmware_size = firmware_in.tellg();
    firmware_in.seekg(0, ios_base::beg);
    firmware_hex.resize(firmware_size);

    firmware_in.read(firmware_hex.data(), firmware_size);
    firmware_in.close();

    return ReadResult::ok(firmware_hex);
}

OTAUpdater::TransportResult
OTAUpdater::connect_to(const string& host, uint16_t port)
{
    auto transport = make_unique<TCPTransport>();
    if(!transport->connect(host, port))
        return OTAUpdater::UpdateResult::err_fmt("Unable to connect to %s:%d", host, port);
}

OTAUpdater::UpdateResult OTAUpdater::upload(
    unique_ptr<TCPTransport>& transport
)
{
    // UpdateCommand cmd;
    // UpdateBegin* begin = cmd.mutable_begin();
    // begin->set_size(firmware.size());
    // begin->set_hash(hash);
}

OTAUpdater::UpdateResult OTAUpdater::commit(
    unique_ptr<TCPTransport>& transport
)
{
    // TODO
}