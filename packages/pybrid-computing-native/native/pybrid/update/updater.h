#include <iostream>
#include <vector>
#include <string>
#include <cstdint>
#include <memory>

#include "../utils/result.h"
#include "pybrid/transport/tcp_transport.h"

using namespace std;
using namespace anabrid::pybrid::native;

/**
 * @brief A class implementing OTA update functionality for the Teensy MCU.
 * Using the code from @jung's `redac` project, uses a 2-step process:
 * - send update command with binarized firmware.hex, pre-loading the firmware
 * into the staging area
 */
class OTAUpdater
{
public:
    using ReadResult = Result<vector<uint8_t>>;
    using UpdateResult = Result<bool>;
    using TransportResult = Result<unique_ptr<TCPTransport>>;

    OTAUpdater() = default;
    ~OTAUpdater() = default;

    // used from pybrid CLI and frontend - reads firmware from disk, creates
    // new connections and closes them
    UpdateResult execute(
        string firmware_path,
        const vector<string>& targets,
        uint16_t port
    );

protected:
    ReadResult read_firmware(const string& firmware_path);
    TransportResult connect_to(const string& host, uint16_t port = 5732);
    UpdateResult upload(unique_ptr<TCPTransport>& transport);
    UpdateResult commit(unique_ptr<TCPTransport>& transport);

    vector<uint8_t> m_firmware_bin;
};

