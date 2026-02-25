#pragma once

#include "buffer.h"
#include "concurrentqueue.h"

#include <array>
#include <atomic>
#include <cstring>
#include <string>

namespace anabrid::pybrid::native {

/**
 * @brief Lock-free MPMC buffer for variable-sized items.
 *
 * Uses moodycamel::ConcurrentQueue with fixed-size slots. Each slot stores a
 * size field and a fixed-size data array; items smaller than SLOT_DATA_SIZE
 * waste the difference as padding, items larger are rejected.
 *
 * The buffer is unbounded: it grows as needed. INITIAL_CAPACITY is a hint
 * to reduce early reallocations but does NOT impose an upper limit.
 * try_put() only fails when the item exceeds SLOT_DATA_SIZE or the allocator
 * runs out of memory.
 *
 * len() and size() use relaxed atomic operations and may return approximate
 * values under concurrent access. Suitable for diagnostics but not for
 * synchronization decisions.
 *
 * @tparam SLOT_DATA_SIZE Maximum size of item data in bytes.
 * @tparam INITIAL_CAPACITY Initial capacity hint for the underlying queue.
 */
template <size_t SLOT_DATA_SIZE = 512, size_t INITIAL_CAPACITY = 32768>
class LockFreeBuffer : public IBuffer {
public:
    LockFreeBuffer();
    ~LockFreeBuffer() override = default;

    void put(size_t item_size, const void* item) override;
    bool try_put(size_t item_size, const void* item) override;
    size_t get(void* buffer, size_t buffer_size) override;
    size_t len() const override;
    size_t size() const override;

    /// The buffer grows without bound; only individual item size is checked.
    bool has_exact_capacity() const override { return false; }

    static constexpr size_t max_item_size() { return SLOT_DATA_SIZE; }

private:
    struct Slot {
        size_t size;
        std::array<char, SLOT_DATA_SIZE> data;
    };

    moodycamel::ConcurrentQueue<Slot> m_queue;
    std::atomic<size_t> m_len{0};   // Approximate item count
    std::atomic<size_t> m_size{0};  // Approximate total data bytes
};

template <size_t SLOT_DATA_SIZE, size_t INITIAL_CAPACITY>
LockFreeBuffer<SLOT_DATA_SIZE, INITIAL_CAPACITY>::LockFreeBuffer()
    : m_queue(INITIAL_CAPACITY) {}

template <size_t SLOT_DATA_SIZE, size_t INITIAL_CAPACITY>
bool LockFreeBuffer<SLOT_DATA_SIZE, INITIAL_CAPACITY>::try_put(size_t item_size, const void* item) {
    if (item_size > SLOT_DATA_SIZE) {
        return false;
    }

    Slot slot;
    slot.size = item_size;
    if (item_size > 0 && item != nullptr) {
        std::memcpy(slot.data.data(), item, item_size);
    }

    if (!m_queue.enqueue(std::move(slot))) {
        return false;
    }

    m_len.fetch_add(1, std::memory_order_relaxed);
    m_size.fetch_add(item_size, std::memory_order_relaxed);
    return true;
}

template <size_t SLOT_DATA_SIZE, size_t INITIAL_CAPACITY>
void LockFreeBuffer<SLOT_DATA_SIZE, INITIAL_CAPACITY>::put(size_t item_size, const void* item) {
    if (item_size > SLOT_DATA_SIZE) {
        throw MessageTooLargeError(item_size, SLOT_DATA_SIZE);
    }

    if (!try_put(item_size, item)) {
        throw BufferFullError("Enqueue failed (allocation failure)");
    }
}

template <size_t SLOT_DATA_SIZE, size_t INITIAL_CAPACITY>
size_t LockFreeBuffer<SLOT_DATA_SIZE, INITIAL_CAPACITY>::get(void* buffer, size_t buffer_size) {
    Slot slot;
    if (!m_queue.try_dequeue(slot)) {
        return 0;
    }

    if (slot.size > buffer_size) {
        // Re-enqueue to preserve the item. In MPMC scenarios this may cause minor
        // FIFO ordering variations — ensure adequate buffer sizes for strict ordering.
        m_queue.enqueue(std::move(slot));
        return 0;
    }

    m_len.fetch_sub(1, std::memory_order_relaxed);
    m_size.fetch_sub(slot.size, std::memory_order_relaxed);

    if (slot.size > 0 && buffer != nullptr) {
        std::memcpy(buffer, slot.data.data(), slot.size);
    }

    return slot.size;
}

template <size_t SLOT_DATA_SIZE, size_t INITIAL_CAPACITY>
size_t LockFreeBuffer<SLOT_DATA_SIZE, INITIAL_CAPACITY>::len() const {
    return m_len.load(std::memory_order_relaxed);
}

template <size_t SLOT_DATA_SIZE, size_t INITIAL_CAPACITY>
size_t LockFreeBuffer<SLOT_DATA_SIZE, INITIAL_CAPACITY>::size() const {
    return m_size.load(std::memory_order_relaxed);
}

}  // namespace anabrid::pybrid::native
