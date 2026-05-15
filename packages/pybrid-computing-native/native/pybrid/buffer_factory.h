#pragma once

#include <memory>
#include <stdexcept>

#include "buffer.h"
#include "lockfree_buffer.h"

namespace anabrid::pybrid::native {

/**
 * @tparam MAX_ITEM_SIZE Maximum item size for LockFreeBuffer (compile-time).
 * @tparam INITIAL_CAPACITY Initial capacity hint for LockFreeBuffer pre-allocation
 *         (not an upper bound — the buffer grows without limit).
 */
template <size_t MAX_ITEM_SIZE, size_t INITIAL_CAPACITY = 256>
class BufferFactory {
public:
    /// @throws std::invalid_argument if type is unknown.
    static std::unique_ptr<IBuffer> create(BufferType type) {
        switch (type) {
            case BufferType::LockFree: return std::make_unique<LockFreeBuffer<MAX_ITEM_SIZE, INITIAL_CAPACITY>>();

            default: throw std::invalid_argument("Unknown buffer type");
        }
    }
};

}  // namespace anabrid::pybrid::native
