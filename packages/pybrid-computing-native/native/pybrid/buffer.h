#pragma once

#include <cstddef>
#include <stdexcept>
#include <string>

namespace anabrid::pybrid::native {

enum class BufferType {
    LockFree     ///< Lock-free buffer using moodycamel::ConcurrentQueue
};

class BufferFullError : public std::runtime_error {
public:
    explicit BufferFullError(const std::string& message) : std::runtime_error(message) {}
};

/// Propagates to Python as a specific error type, distinguishing "buffer full"
/// (capacity limit) from "message too large" (individual message exceeds slot size).
class MessageTooLargeError : public std::runtime_error {
public:
    explicit MessageTooLargeError(const std::string& message) : std::runtime_error(message) {}

    MessageTooLargeError(size_t message_size, size_t max_size)
        : std::runtime_error("Message size " + std::to_string(message_size) +
                             " bytes exceeds maximum slot size of " +
                             std::to_string(max_size) + " bytes") {}
};

/**
 * @brief Abstract interface for variable-sized item buffers.
 *
 * Supports MPMC (multiple producer, multiple consumer) patterns.
 * All methods are thread-safe for concurrent access.
 *
 * If the user-supplied buffer is too small in get(), the item is NOT consumed
 * and remains available for later retrieval with an adequate buffer.
 *
 * For lock-free implementations, len() and size() may be approximate under
 * concurrent access.
 */
class IBuffer {
public:
    virtual ~IBuffer() = default;

    /// @throws BufferFullError if buffer cannot accept the item.
    virtual void put(size_t item_size, const void* item) = 0;

    /// @return true if item was enqueued, false if buffer is full.
    virtual bool try_put(size_t item_size, const void* item) = 0;

    /// @return Size of retrieved item, or 0 if empty or buffer too small.
    virtual size_t get(void* buffer, size_t buffer_size) = 0;

    virtual size_t len() const = 0;

    /// @return Sum of user data bytes only (excludes internal headers/alignment).
    virtual size_t size() const = 0;

    /// @return true if capacity is strictly enforced (LockFreeBuffer returns false — unbounded).
    virtual bool has_exact_capacity() const = 0;
};

} // namespace anabrid::pybrid::native
