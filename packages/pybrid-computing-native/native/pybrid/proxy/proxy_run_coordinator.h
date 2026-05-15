#pragma once

#include <atomic>
#include <cstddef>
#include <cstdint>

namespace anabrid::pybrid::native {

class RunCoordinator {
public:
    void configure(size_t backend_count);
    void start_run();
    void on_take_off();
    bool on_done();

private:
    std::atomic<uint64_t> run_id_{0};
    std::atomic<size_t> take_off_count_{0};
    std::atomic<size_t> done_count_{0};
    // Written once by configure() before any forward callback can fire;
    // read-only thereafter, so no synchronisation is required.
    size_t backend_count_{0};
};

}  // namespace anabrid::pybrid::native
