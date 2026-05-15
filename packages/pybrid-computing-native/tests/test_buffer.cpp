#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstring>
#include <memory>
#include <mutex>
#include <set>
#include <thread>
#include <vector>

#include "pybrid/buffer.h"
#include "pybrid/lockfree_buffer.h"

using namespace anabrid::pybrid::native;

// ============================================================================
// Test Helpers
// ============================================================================

/**
 * @brief Simple barrier for C++17 thread synchronization.
 *
 * Used to ensure all threads start concurrently in tests, creating realistic
 * contention scenarios. C++20 provides std::barrier, but this project targets C++17.
 */
class SimpleBarrier {
public:
    explicit SimpleBarrier(std::size_t count) : m_count(count), m_waiting(0), m_generation(0) {}

    void arrive_and_wait() {
        std::unique_lock<std::mutex> lock(m_mutex);
        std::size_t gen = m_generation;
        m_waiting++;
        if (m_waiting == m_count) {
            m_generation++;
            m_waiting = 0;
            m_cv.notify_all();
        } else {
            m_cv.wait(lock, [this, gen] { return gen != m_generation; });
        }
    }

private:
    std::mutex m_mutex;
    std::condition_variable m_cv;
    std::size_t m_count;
    std::size_t m_waiting;
    std::size_t m_generation;
};

/**
 * @brief Test item structure for multi-threaded tests.
 * Contains producer ID and sequence number to verify ordering and detect duplicates.
 */
struct TestItem {
    uint32_t producer_id;
    uint32_t sequence_number;

    bool operator==(const TestItem& other) const {
        return producer_id == other.producer_id && sequence_number == other.sequence_number;
    }

    bool operator<(const TestItem& other) const {
        if (producer_id != other.producer_id) return producer_id < other.producer_id;
        return sequence_number < other.sequence_number;
    }
};

/**
 * @brief Constant backoff: sleep for a fixed duration when buffer is full.
 */
void constant_backoff() {
    std::this_thread::sleep_for(std::chrono::microseconds(100));
}

// ============================================================================
// Type Definitions for Parameterized Tests
// ============================================================================

// Type tags for test parameterization
struct LockFreeBufferTag {};

/**
 * @brief Factory for creating buffer instances with comparable configurations.
 *
 * LockFreeBuffer: Uses slot-based layout with fixed slot size
 * - SLOT_DATA_SIZE = 256 bytes (max item size)
 * - Unbounded capacity (grows as needed)
 */
template <typename Tag>
std::unique_ptr<IBuffer> createBuffer();

template <>
std::unique_ptr<IBuffer> createBuffer<LockFreeBufferTag>() {
    return std::make_unique<LockFreeBuffer<256>>();
}

// Smaller buffer factory for basic tests (same as above; capacity is unbounded)
template <typename Tag>
std::unique_ptr<IBuffer> createSmallBuffer();

template <>
std::unique_ptr<IBuffer> createSmallBuffer<LockFreeBufferTag>() {
    return std::make_unique<LockFreeBuffer<256>>();
}

// ============================================================================
// Shared Tests (Run Against Both Implementations)
// ============================================================================

template <typename T>
class BufferTest : public ::testing::Test {
protected:
    void SetUp() override { buffer = createSmallBuffer<T>(); }

    std::unique_ptr<IBuffer> buffer;
};

using BufferTypes = ::testing::Types<LockFreeBufferTag>;
TYPED_TEST_SUITE(BufferTest, BufferTypes);

// Tests basic put/get cycle with a single item.
TYPED_TEST(BufferTest, PutGetSingleItem) {
    const char data[] = "Hello, World!";
    char recv_buffer[64];

    this->buffer->put(sizeof(data), data);
    EXPECT_EQ(this->buffer->len(), 1u);

    size_t received = this->buffer->get(recv_buffer, sizeof(recv_buffer));
    EXPECT_EQ(received, sizeof(data));
    EXPECT_EQ(std::memcmp(data, recv_buffer, sizeof(data)), 0);
    EXPECT_EQ(this->buffer->len(), 0u);
}

// Tests FIFO ordering with multiple items.
TYPED_TEST(BufferTest, PutGetMultipleItems) {
    const char item1[] = "First";
    const char item2[] = "Second";
    const char item3[] = "Third";
    char recv_buffer[64];

    this->buffer->put(sizeof(item1), item1);
    this->buffer->put(sizeof(item2), item2);
    this->buffer->put(sizeof(item3), item3);

    EXPECT_EQ(this->buffer->len(), 3u);

    size_t r1 = this->buffer->get(recv_buffer, sizeof(recv_buffer));
    EXPECT_EQ(r1, sizeof(item1));
    EXPECT_EQ(std::memcmp(item1, recv_buffer, sizeof(item1)), 0);

    size_t r2 = this->buffer->get(recv_buffer, sizeof(recv_buffer));
    EXPECT_EQ(r2, sizeof(item2));
    EXPECT_EQ(std::memcmp(item2, recv_buffer, sizeof(item2)), 0);

    size_t r3 = this->buffer->get(recv_buffer, sizeof(recv_buffer));
    EXPECT_EQ(r3, sizeof(item3));
    EXPECT_EQ(std::memcmp(item3, recv_buffer, sizeof(item3)), 0);

    EXPECT_EQ(this->buffer->len(), 0u);
}

// Tests get() on empty buffer.
TYPED_TEST(BufferTest, GetFromEmpty) {
    char recv_buffer[64];
    size_t received = this->buffer->get(recv_buffer, sizeof(recv_buffer));
    EXPECT_EQ(received, 0u);
}

// Tests get() behavior when user buffer is too small.
// Item should NOT be consumed and remains available for later retrieval.
TYPED_TEST(BufferTest, GetBufferTooSmall) {
    const char data[] = "This is a longer message";
    char small_buffer[4];

    this->buffer->put(sizeof(data), data);
    EXPECT_EQ(this->buffer->len(), 1u);

    // Buffer too small - returns 0 but item remains in buffer
    size_t received = this->buffer->get(small_buffer, sizeof(small_buffer));
    EXPECT_EQ(received, 0u);

    // Item should still be in the buffer
    EXPECT_EQ(this->buffer->len(), 1u);

    // Now retrieve with adequate buffer
    char adequate_buffer[64];
    received = this->buffer->get(adequate_buffer, sizeof(adequate_buffer));
    EXPECT_EQ(received, sizeof(data));
    EXPECT_EQ(std::memcmp(data, adequate_buffer, sizeof(data)), 0);
    EXPECT_EQ(this->buffer->len(), 0u);
}

// Tests handling of zero-size items.
TYPED_TEST(BufferTest, ZeroSizeItem) {
    char recv_buffer[64];

    this->buffer->put(0, nullptr);
    EXPECT_EQ(this->buffer->len(), 1u);

    size_t received = this->buffer->get(recv_buffer, sizeof(recv_buffer));
    EXPECT_EQ(received, 0u);
    EXPECT_EQ(this->buffer->len(), 0u);
}

// Tests try_put() non-throwing variant.
TYPED_TEST(BufferTest, TryPutBasic) {
    const char data[] = "Test data";

    bool success = this->buffer->try_put(sizeof(data), data);
    EXPECT_TRUE(success);
    EXPECT_EQ(this->buffer->len(), 1u);

    char recv_buffer[64];
    size_t received = this->buffer->get(recv_buffer, sizeof(recv_buffer));
    EXPECT_EQ(received, sizeof(data));
    EXPECT_EQ(std::memcmp(data, recv_buffer, sizeof(data)), 0);
}

// Tests that has_exact_capacity() returns a valid boolean.
TYPED_TEST(BufferTest, HasExactCapacityReturnsBoolean) {
    // Just verify the method is callable and returns a boolean
    bool result = this->buffer->has_exact_capacity();
    EXPECT_TRUE(result == true || result == false);
}

// Tests state consistency after failed put().
TYPED_TEST(BufferTest, StateConsistencyAfterException) {
    char data[32];
    char recv_buffer[64];
    std::memset(data, 'X', sizeof(data));

    this->buffer->put(sizeof(data), data);
    this->buffer->put(sizeof(data), data);

    size_t len_before = this->buffer->len();
    size_t size_before = this->buffer->size();

    // Try to put something that will fail (too large for slot in LockFreeBuffer)
    char huge_data[512];
    EXPECT_THROW(this->buffer->put(sizeof(huge_data), huge_data), MessageTooLargeError);

    EXPECT_EQ(this->buffer->len(), len_before);
    EXPECT_EQ(this->buffer->size(), size_before);

    this->buffer->get(recv_buffer, sizeof(recv_buffer));
    EXPECT_EQ(this->buffer->len(), len_before - 1);
}

// ============================================================================
// Concurrency Tests (Run Against Both Implementations)
// ============================================================================

template <typename T>
class BufferConcurrencyTest : public ::testing::Test {
protected:
    void SetUp() override { buffer = createBuffer<T>(); }

    std::unique_ptr<IBuffer> buffer;
};

TYPED_TEST_SUITE(BufferConcurrencyTest, BufferTypes);

// Tests single producer, single consumer scenario.
TYPED_TEST(BufferConcurrencyTest, SingleProducerSingleConsumer) {
    const int NUM_ITEMS = 1000;
    std::atomic<bool> producer_done{false};
    std::vector<TestItem> received_items;
    std::mutex received_mutex;

    SimpleBarrier start_barrier(2);

    std::thread producer([&]() {
        start_barrier.arrive_and_wait();

        TestItem item;
        for (int i = 0; i < NUM_ITEMS; ++i) {
            item.producer_id = 0;
            item.sequence_number = i;
            while (true) {
                if (this->buffer->try_put(sizeof(TestItem), &item)) {
                    break;
                }
                constant_backoff();
            }
        }
        producer_done = true;
    });

    std::thread consumer([&]() {
        start_barrier.arrive_and_wait();

        TestItem recv_item;
        int consecutive_empty = 0;

        while (true) {
            size_t received = this->buffer->get(&recv_item, sizeof(TestItem));
            if (received > 0) {
                consecutive_empty = 0;
                std::lock_guard<std::mutex> lock(received_mutex);
                received_items.push_back(recv_item);
            } else {
                if (producer_done && this->buffer->len() == 0) {
                    consecutive_empty++;
                    if (consecutive_empty >= 3) break;
                }
                std::this_thread::yield();
            }
        }
    });

    producer.join();
    consumer.join();

    EXPECT_EQ(received_items.size(), static_cast<size_t>(NUM_ITEMS));
    for (int i = 0; i < NUM_ITEMS; ++i) {
        EXPECT_EQ(received_items[i].producer_id, 0u);
        EXPECT_EQ(received_items[i].sequence_number, static_cast<uint32_t>(i));
    }
}

// Tests multiple producers, single consumer scenario.
TYPED_TEST(BufferConcurrencyTest, MultipleProducersSingleConsumer) {
    const int NUM_PRODUCERS = 4;
    const int ITEMS_PER_PRODUCER = 250;
    std::atomic<int> done_count{0};

    std::vector<TestItem> received_items;
    std::mutex received_mutex;

    SimpleBarrier start_barrier(NUM_PRODUCERS + 1);

    std::vector<std::thread> producers;
    for (int p = 0; p < NUM_PRODUCERS; ++p) {
        producers.emplace_back([&, p]() {
            start_barrier.arrive_and_wait();

            TestItem item;
            item.producer_id = p;
            for (int i = 0; i < ITEMS_PER_PRODUCER; ++i) {
                item.sequence_number = i;
                while (true) {
                    if (this->buffer->try_put(sizeof(TestItem), &item)) {
                        break;
                    }
                    constant_backoff();
                }
            }
            done_count++;
        });
    }

    std::thread consumer([&]() {
        start_barrier.arrive_and_wait();

        TestItem recv_item;
        int consecutive_empty = 0;

        while (true) {
            size_t received = this->buffer->get(&recv_item, sizeof(TestItem));
            if (received > 0) {
                consecutive_empty = 0;
                std::lock_guard<std::mutex> lock(received_mutex);
                received_items.push_back(recv_item);
            } else {
                if (done_count == NUM_PRODUCERS && this->buffer->len() == 0) {
                    consecutive_empty++;
                    if (consecutive_empty >= 3) break;
                }
                std::this_thread::yield();
            }
        }
    });

    for (auto& t : producers)
        t.join();
    consumer.join();

    EXPECT_EQ(received_items.size(), static_cast<size_t>(NUM_PRODUCERS * ITEMS_PER_PRODUCER));

    // Verify per-producer ordering
    std::vector<std::vector<uint32_t>> per_producer(NUM_PRODUCERS);
    for (const auto& item : received_items) {
        per_producer[item.producer_id].push_back(item.sequence_number);
    }

    for (int p = 0; p < NUM_PRODUCERS; ++p) {
        EXPECT_EQ(per_producer[p].size(), static_cast<size_t>(ITEMS_PER_PRODUCER));
        for (int i = 0; i < ITEMS_PER_PRODUCER; ++i) {
            EXPECT_EQ(per_producer[p][i], static_cast<uint32_t>(i)) << "Producer " << p << " seq mismatch";
        }
    }
}

// Tests single producer, multiple consumers scenario.
TYPED_TEST(BufferConcurrencyTest, SingleProducerMultipleConsumers) {
    const int NUM_ITEMS = 1000;
    const int NUM_CONSUMERS = 4;
    std::atomic<bool> producer_done{false};

    std::set<TestItem> received_set;
    std::mutex received_mutex;
    std::atomic<int> total_received{0};

    SimpleBarrier start_barrier(NUM_CONSUMERS + 1);

    std::thread producer([&]() {
        start_barrier.arrive_and_wait();

        TestItem item;
        item.producer_id = 0;
        for (int i = 0; i < NUM_ITEMS; ++i) {
            item.sequence_number = i;
            while (true) {
                if (this->buffer->try_put(sizeof(TestItem), &item)) {
                    break;
                }
                constant_backoff();
            }
        }
        producer_done = true;
    });

    std::vector<std::thread> consumers;
    for (int c = 0; c < NUM_CONSUMERS; ++c) {
        consumers.emplace_back([&]() {
            start_barrier.arrive_and_wait();

            TestItem recv_item;
            int consecutive_empty = 0;

            while (true) {
                size_t received = this->buffer->get(&recv_item, sizeof(TestItem));
                if (received > 0) {
                    consecutive_empty = 0;
                    {
                        std::lock_guard<std::mutex> lock(received_mutex);
                        received_set.insert(recv_item);
                    }
                    total_received++;
                } else {
                    if (producer_done && this->buffer->len() == 0) {
                        consecutive_empty++;
                        if (consecutive_empty >= 3) break;
                    }
                    std::this_thread::yield();
                }
            }
        });
    }

    producer.join();
    for (auto& t : consumers)
        t.join();

    EXPECT_EQ(total_received.load(), NUM_ITEMS);
    EXPECT_EQ(received_set.size(), static_cast<size_t>(NUM_ITEMS));
}

// Tests multiple producers, multiple consumers scenario (stress test).
TYPED_TEST(BufferConcurrencyTest, MultipleProducersMultipleConsumers) {
    const int NUM_PRODUCERS = 4;
    const int NUM_CONSUMERS = 4;
    const int ITEMS_PER_PRODUCER = 100000;
    std::atomic<int> done_count{0};

    std::set<TestItem> received_set;
    std::mutex received_mutex;
    std::atomic<int> total_received{0};

    SimpleBarrier start_barrier(NUM_PRODUCERS + NUM_CONSUMERS);

    std::vector<std::thread> producers;
    for (int p = 0; p < NUM_PRODUCERS; ++p) {
        producers.emplace_back([&, p]() {
            start_barrier.arrive_and_wait();

            TestItem item;
            item.producer_id = p;
            for (int i = 0; i < ITEMS_PER_PRODUCER; ++i) {
                item.sequence_number = i;
                while (true) {
                    if (this->buffer->try_put(sizeof(TestItem), &item)) {
                        break;
                    }
                    constant_backoff();
                }
            }
            done_count++;
        });
    }

    std::vector<std::thread> consumers;
    for (int c = 0; c < NUM_CONSUMERS; ++c) {
        consumers.emplace_back([&]() {
            start_barrier.arrive_and_wait();

            TestItem recv_item;
            int consecutive_empty = 0;

            while (true) {
                size_t received = this->buffer->get(&recv_item, sizeof(TestItem));
                if (received > 0) {
                    consecutive_empty = 0;
                    {
                        std::lock_guard<std::mutex> lock(received_mutex);
                        received_set.insert(recv_item);
                    }
                    total_received++;
                } else {
                    if (done_count == NUM_PRODUCERS && this->buffer->len() == 0) {
                        consecutive_empty++;
                        if (consecutive_empty >= 3) break;
                    }
                    std::this_thread::yield();
                }
            }
        });
    }

    for (auto& t : producers)
        t.join();
    for (auto& t : consumers)
        t.join();

    const int TOTAL_ITEMS = NUM_PRODUCERS * ITEMS_PER_PRODUCER;
    EXPECT_EQ(total_received.load(), TOTAL_ITEMS);
    EXPECT_EQ(received_set.size(), static_cast<size_t>(TOTAL_ITEMS));
}

// Tests high contention with many threads doing rapid put/get operations.
TYPED_TEST(BufferConcurrencyTest, HighContention) {
    const int NUM_THREADS = 8;
    const int OPS_PER_THREAD = 100000;
    std::atomic<int> successful_puts{0};
    std::atomic<int> successful_gets{0};
    std::atomic<bool> stop{false};

    SimpleBarrier start_barrier(NUM_THREADS);

    std::vector<std::thread> threads;
    for (int t = 0; t < NUM_THREADS; ++t) {
        threads.emplace_back([&, t]() {
            start_barrier.arrive_and_wait();

            TestItem item;
            item.producer_id = t;
            TestItem recv_item;

            for (int i = 0; i < OPS_PER_THREAD && !stop; ++i) {
                // Alternate between put and get
                if (i % 2 == 0) {
                    item.sequence_number = i;
                    if (this->buffer->try_put(sizeof(TestItem), &item)) {
                        successful_puts++;
                    }
                } else {
                    size_t received = this->buffer->get(&recv_item, sizeof(TestItem));
                    if (received > 0) {
                        successful_gets++;
                    }
                }
            }
        });
    }

    for (auto& t : threads)
        t.join();

    EXPECT_FALSE(stop.load());

    // Drain remaining items
    TestItem drain_item;
    while (this->buffer->len() > 0) {
        size_t received = this->buffer->get(&drain_item, sizeof(TestItem));
        if (received > 0) {
            successful_gets++;
        }
    }

    // All puts should have corresponding gets
    EXPECT_EQ(successful_puts.load(), successful_gets.load());
}

// ============================================================================
// LockFreeBuffer-Specific Tests
// ============================================================================

class LockFreeBufferSpecificTest : public ::testing::Test {
protected:
    void SetUp() override { buffer = std::make_unique<LockFreeBuffer<256>>(); }

    std::unique_ptr<LockFreeBuffer<256>> buffer;
};

// Tests that LockFreeBuffer reports unbounded capacity.
TEST_F(LockFreeBufferSpecificTest, HasNoExactCapacity) {
    EXPECT_FALSE(buffer->has_exact_capacity());
}

// Tests that the buffer grows beyond initial capacity without dropping items.
TEST_F(LockFreeBufferSpecificTest, GrowsBeyondInitialCapacity) {
    char data[64];
    std::memset(data, 'X', sizeof(data));

    // Enqueue many more items than any reasonable initial capacity hint.
    // The underlying moodycamel::ConcurrentQueue should grow to accommodate them.
    constexpr int COUNT = 100000;
    for (int i = 0; i < COUNT; ++i) {
        EXPECT_TRUE(buffer->try_put(sizeof(data), data)) << "Item " << i;
    }
    EXPECT_EQ(buffer->len(), static_cast<size_t>(COUNT));
}

// Tests rejection of items larger than slot size.
TEST_F(LockFreeBufferSpecificTest, ItemTooLarge) {
    char huge_data[512];  // Larger than 256-byte slot
    EXPECT_THROW(buffer->put(sizeof(huge_data), huge_data), MessageTooLargeError);
}

// Tests that try_put returns false for oversized items.
TEST_F(LockFreeBufferSpecificTest, TryPutTooLarge) {
    char huge_data[512];
    EXPECT_FALSE(buffer->try_put(sizeof(huge_data), huge_data));
}

// Tests accuracy of len() and size() counters.
TEST_F(LockFreeBufferSpecificTest, LenAndSizeAccuracy) {
    char data8[8];
    char data16[16];
    char recv_buffer[64];

    EXPECT_EQ(buffer->len(), 0u);
    EXPECT_EQ(buffer->size(), 0u);

    buffer->put(sizeof(data8), data8);
    EXPECT_EQ(buffer->len(), 1u);
    EXPECT_EQ(buffer->size(), 8u);

    buffer->put(sizeof(data16), data16);
    EXPECT_EQ(buffer->len(), 2u);
    EXPECT_EQ(buffer->size(), 24u);

    buffer->get(recv_buffer, sizeof(recv_buffer));
    EXPECT_EQ(buffer->len(), 1u);
    EXPECT_EQ(buffer->size(), 16u);

    buffer->get(recv_buffer, sizeof(recv_buffer));
    EXPECT_EQ(buffer->len(), 0u);
    EXPECT_EQ(buffer->size(), 0u);
}

// Tests max_item_size() static method.
TEST_F(LockFreeBufferSpecificTest, MaxItemSize) {
    EXPECT_EQ(buffer->max_item_size(), 256u);
}

// Tests that we can put and retrieve multiple items correctly.
TEST_F(LockFreeBufferSpecificTest, MultipleItems) {
    char data[100];
    std::memset(data, 'A', sizeof(data));

    // Put several items
    const int NUM_ITEMS = 16;
    for (int i = 0; i < NUM_ITEMS; ++i) {
        EXPECT_TRUE(buffer->try_put(sizeof(data), data));
    }

    EXPECT_EQ(buffer->len(), static_cast<size_t>(NUM_ITEMS));
    EXPECT_EQ(buffer->size(), NUM_ITEMS * sizeof(data));

    // Retrieve all items
    char recv_buffer[128];
    for (int i = 0; i < NUM_ITEMS; ++i) {
        size_t received = buffer->get(recv_buffer, sizeof(recv_buffer));
        EXPECT_EQ(received, sizeof(data));
    }

    EXPECT_EQ(buffer->len(), 0u);
    EXPECT_EQ(buffer->size(), 0u);
}

// Tests repeated fill-drain cycles with a fixed number of items.
TEST_F(LockFreeBufferSpecificTest, RepeatedFillDrain) {
    char data[16];
    char recv_buffer[32];
    const int ITEMS_PER_CYCLE = 10;

    for (int cycle = 0; cycle < 5; ++cycle) {
        // Fill with fixed number of items
        for (int i = 0; i < ITEMS_PER_CYCLE; ++i) {
            std::memset(data, 'A' + cycle, sizeof(data));
            EXPECT_TRUE(buffer->try_put(sizeof(data), data)) << "Cycle " << cycle;
        }

        EXPECT_EQ(buffer->len(), static_cast<size_t>(ITEMS_PER_CYCLE)) << "Cycle " << cycle;

        // Drain completely
        for (int i = 0; i < ITEMS_PER_CYCLE; ++i) {
            size_t received = buffer->get(recv_buffer, sizeof(recv_buffer));
            EXPECT_EQ(received, sizeof(data)) << "Cycle " << cycle;
            for (size_t j = 0; j < sizeof(data); ++j) {
                EXPECT_EQ(recv_buffer[j], 'A' + cycle) << "Cycle " << cycle << " byte " << j;
            }
        }

        EXPECT_EQ(buffer->len(), 0u) << "Cycle " << cycle;
        EXPECT_EQ(buffer->size(), 0u) << "Cycle " << cycle;
    }
}
