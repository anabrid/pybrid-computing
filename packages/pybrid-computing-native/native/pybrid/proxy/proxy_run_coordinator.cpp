#include "pybrid/proxy/proxy_run_coordinator.h"

namespace anabrid::pybrid::native {

void RunCoordinator::configure(size_t backend_count) {
    backend_count_ = backend_count;
    run_id_.store(0, std::memory_order_release);
    take_off_count_.store(0, std::memory_order_release);
    done_count_.store(0, std::memory_order_release);
}

void RunCoordinator::start_run() {
    run_id_.fetch_add(1, std::memory_order_acq_rel);
    take_off_count_.store(0, std::memory_order_release);
    done_count_.store(0, std::memory_order_release);
}

void RunCoordinator::on_take_off() {
    take_off_count_.fetch_add(1, std::memory_order_acq_rel);
}

bool RunCoordinator::on_done() {
    size_t dcount = done_count_.fetch_add(1, std::memory_order_acq_rel) + 1;
    return dcount >= backend_count_;
}

}  // namespace anabrid::pybrid::native
