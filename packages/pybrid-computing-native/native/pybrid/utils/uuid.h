#pragma once

#include <cstdint>
#include <iomanip>
#include <random>
#include <sstream>
#include <string>

namespace anabrid::pybrid::native::utils {

/**
 * Uses a thread-local mt19937 RNG seeded from std::random_device.
 * Thread-safe by design — each thread gets its own RNG instance.
 */
inline std::string generate_uuid() {
    thread_local std::mt19937 rng{std::random_device{}()};
    thread_local std::uniform_int_distribution<uint32_t> dist(0, 0xFFFFFFFFu);

    uint32_t a = dist(rng);
    uint32_t b = dist(rng);
    uint32_t c = dist(rng);
    uint32_t d = dist(rng);

    // Set version 4 bits (bits 12-15 of the third group = 0100).
    b = (b & 0xFFFF0FFFu) | 0x00004000u;

    // Set variant 1 bits (bits 30-31 of the fourth group = 10).
    c = (c & 0x3FFFFFFFu) | 0x80000000u;

    std::ostringstream oss;
    oss << std::hex << std::setfill('0')
        << std::setw(8) << a
        << '-'
        << std::setw(4) << ((b >> 16) & 0xFFFFu)
        << '-'
        << std::setw(4) << (b & 0xFFFFu)
        << '-'
        << std::setw(4) << ((c >> 16) & 0xFFFFu)
        << '-'
        << std::setw(4) << (c & 0xFFFFu)
        << std::setw(8) << d;

    return oss.str();
}

}  // namespace anabrid::pybrid::native::utils
