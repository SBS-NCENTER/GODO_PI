// Track B-CONFIG (PR-CONFIG-α) — restart-pending flag manager tests.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <cstdio>
#include <filesystem>
#include <system_error>

#include <unistd.h>

#include "config/restart_pending.hpp"

using godo::config::clear_pending_flag;
using godo::config::is_pending;
using godo::config::touch_pending_flag;
namespace fs = std::filesystem;

namespace {

struct TempDir {
    fs::path path;
    explicit TempDir(const char* tag) {
        char buf[256];
        std::snprintf(buf, sizeof(buf), "/tmp/godo_pending_%d_%s",
                      static_cast<int>(::getpid()), tag);
        path = buf;
        std::error_code ec;
        fs::remove_all(path, ec);
        fs::create_directories(path);
    }
    ~TempDir() {
        std::error_code ec;
        fs::remove_all(path, ec);
    }
};

}  // namespace

TEST_CASE("touch creates the flag file") {
    TempDir td("touch");
    const auto flag = td.path / "restart_pending";
    CHECK_FALSE(is_pending(flag));
    touch_pending_flag(flag);
    CHECK(is_pending(flag));
    CHECK(fs::exists(flag));
}

TEST_CASE("clear removes the flag file") {
    TempDir td("clear");
    const auto flag = td.path / "restart_pending";
    touch_pending_flag(flag);
    REQUIRE(is_pending(flag));
    clear_pending_flag(flag);
    CHECK_FALSE(is_pending(flag));
    CHECK_FALSE(fs::exists(flag));
}

TEST_CASE("touch is idempotent") {
    TempDir td("idem_touch");
    const auto flag = td.path / "restart_pending";
    touch_pending_flag(flag);
    touch_pending_flag(flag);
    touch_pending_flag(flag);
    CHECK(is_pending(flag));
}

TEST_CASE("clear is idempotent (ENOENT is silent)") {
    TempDir td("idem_clear");
    const auto flag = td.path / "no_such_flag";
    CHECK_FALSE(is_pending(flag));
    clear_pending_flag(flag);  // should not throw or print catastrophe.
    clear_pending_flag(flag);
    CHECK_FALSE(is_pending(flag));
}

TEST_CASE("missing flag returns is_pending=false") {
    TempDir td("missing");
    const auto flag = td.path / "no_such_flag";
    CHECK_FALSE(is_pending(flag));
}

TEST_CASE("touch creates parent directory if missing") {
    TempDir td("nested");
    const auto flag = td.path / "deeper" / "nested" / "restart_pending";
    CHECK_FALSE(fs::exists(flag.parent_path()));
    touch_pending_flag(flag);
    CHECK(is_pending(flag));
    CHECK(fs::exists(flag.parent_path()));
}
