// Copyright (c) 2022-2025 anabrid GmbH
// SPDX-License-Identifier: MIT OR GPL-2.0-or-later

#include <gtest/gtest.h>

#include "pybrid/proxy/proxy_run_coordinator.h"

using namespace anabrid::pybrid::native;

TEST(RunCoordinatorTest, StartRun_BumpsRunId) {
    // Observed indirectly via done_count_ reset: after configure(2),
    // one on_done() then start_run() should reset the count, so two
    // subsequent on_done() calls return false then true.
    RunCoordinator coord;
    coord.configure(/*backend_count=*/2);

    EXPECT_FALSE(coord.on_done());

    coord.start_run();

    EXPECT_FALSE(coord.on_done());
    EXPECT_TRUE(coord.on_done());
}

TEST(RunCoordinatorTest, OnDone_ReturnsTrueOnlyOnLastBackend) {
    RunCoordinator coord;
    coord.configure(/*backend_count=*/3);

    EXPECT_FALSE(coord.on_done());
    EXPECT_FALSE(coord.on_done());
    EXPECT_TRUE(coord.on_done());
}

TEST(RunCoordinatorTest, OnDone_AfterStartRun_ResetsCount) {
    RunCoordinator coord;
    coord.configure(/*backend_count=*/3);

    EXPECT_FALSE(coord.on_done());
    EXPECT_FALSE(coord.on_done());

    coord.start_run();

    EXPECT_FALSE(coord.on_done());
    EXPECT_FALSE(coord.on_done());
    EXPECT_TRUE(coord.on_done());
}

TEST(RunCoordinatorTest, OnTakeOff_BookkeepingOnly) {
    RunCoordinator coord;
    coord.configure(/*backend_count=*/2);

    // on_take_off does not throw and does not affect on_done() outcomes.
    EXPECT_NO_THROW(coord.on_take_off());
    EXPECT_NO_THROW(coord.on_take_off());
    EXPECT_NO_THROW(coord.on_take_off());

    EXPECT_FALSE(coord.on_done());
    EXPECT_TRUE(coord.on_done());
}
