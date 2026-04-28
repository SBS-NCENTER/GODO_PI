// Track B-CONFIG (PR-CONFIG-α) — atomic TOML writer tests.
//
// Mode-A TB2 fold: every failure-mode assertion verifies on-disk
// state, not just return codes. Specifically:
//   (a) target_path either contains pre-call bytes verbatim OR does
//       not exist (never partially written),
//   (b) target_path.parent_path() does not contain any
//       `.tracker.toml.*` tmp leftovers post-call.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>
#include <system_error>

#include <sys/stat.h>
#include <unistd.h>

#include "config/atomic_toml_writer.hpp"

using godo::config::write_atomic;
using godo::config::WriteOutcome;
namespace fs = std::filesystem;

namespace {

struct TempDir {
    fs::path path;
    explicit TempDir(const char* tag) {
        char buf[256];
        std::snprintf(buf, sizeof(buf), "/tmp/godo_atom_%d_%s",
                      static_cast<int>(::getpid()), tag);
        path = buf;
        std::error_code ec;
        fs::remove_all(path, ec);
        fs::create_directories(path);
    }
    ~TempDir() {
        // Ensure parent is writable before remove_all.
        std::error_code ec;
        fs::permissions(path, fs::perms::owner_all, ec);
        fs::remove_all(path, ec);
    }
    TempDir(const TempDir&) = delete;
    TempDir& operator=(const TempDir&) = delete;
};

std::string read_file(const fs::path& p) {
    std::ifstream f(p);
    std::stringstream ss;
    ss << f.rdbuf();
    return ss.str();
}

bool any_tmp_leftover(const fs::path& parent) {
    std::error_code ec;
    for (const auto& e : fs::directory_iterator(parent, ec)) {
        const std::string fname = e.path().filename().string();
        if (fname.rfind(".tracker.toml.", 0) == 0) return true;
    }
    return false;
}

}  // namespace

TEST_CASE("write_atomic: happy path round-trip") {
    TempDir td("happy");
    const fs::path target = td.path / "tracker.toml";
    const std::string body = "[network]\nue_host = \"10.0.0.1\"\n";

    const auto r = write_atomic(target, body);
    CHECK(r.outcome == WriteOutcome::Ok);
    CHECK(read_file(target) == body);
    CHECK_FALSE(any_tmp_leftover(td.path));
}

TEST_CASE("write_atomic: empty body produces zero-length file") {
    TempDir td("empty");
    const fs::path target = td.path / "tracker.toml";

    const auto r = write_atomic(target, "");
    CHECK(r.outcome == WriteOutcome::Ok);
    CHECK(fs::file_size(target) == 0);
    CHECK_FALSE(any_tmp_leftover(td.path));
}

TEST_CASE("write_atomic: overwrite preserves new content") {
    TempDir td("overwrite");
    const fs::path target = td.path / "tracker.toml";
    write_atomic(target, "old\n");
    REQUIRE(read_file(target) == "old\n");

    const auto r = write_atomic(target, "new\n");
    CHECK(r.outcome == WriteOutcome::Ok);
    CHECK(read_file(target) == "new\n");
    CHECK_FALSE(any_tmp_leftover(td.path));
}

TEST_CASE("write_atomic: parent missing → ParentNotWritable") {
    TempDir td("missing_parent");
    const fs::path target = td.path / "no_such_subdir" / "tracker.toml";
    const std::string pre_body = "untouched";

    // Pre-existing target obviously can't exist (parent doesn't).
    const auto r = write_atomic(target, pre_body);
    CHECK(r.outcome == WriteOutcome::ParentNotWritable);
    CHECK_FALSE(fs::exists(target));
    // No tmp leakage in the (existing) td.path either.
    CHECK_FALSE(any_tmp_leftover(td.path));
}

TEST_CASE("write_atomic: read-only parent → ParentNotWritable (Mode-A S1)") {
    // Skip when running as root: chmod 0500 on a dir does not block
    // root's write access, so the test would falsely assert
    // ParentNotWritable.
    if (::geteuid() == 0) {
        WARN("skipping read-only-parent test under root euid");
        return;
    }

    TempDir td("ro_parent");
    const fs::path target = td.path / "tracker.toml";
    const std::string pre_body = "pre\n";
    REQUIRE(write_atomic(target, pre_body).outcome == WriteOutcome::Ok);

    fs::permissions(td.path,
        fs::perms::owner_read | fs::perms::owner_exec,
        fs::perm_options::replace);

    const auto r = write_atomic(target, "new\n");
    CHECK(r.outcome == WriteOutcome::ParentNotWritable);

    // Restore perms for the read-back assertion.
    fs::permissions(td.path, fs::perms::owner_all, fs::perm_options::replace);

    // Mode-A TB2 (a): target either contains pre-call bytes OR does not
    // exist. Since we wrote `pre_body` first, it must equal `pre_body`.
    CHECK(read_file(target) == pre_body);
    // Mode-A TB2 (b): no .tracker.toml.* tmp leftovers.
    CHECK_FALSE(any_tmp_leftover(td.path));
}

TEST_CASE("write_atomic: target file content is exactly the request body") {
    TempDir td("exact_bytes");
    const fs::path target = td.path / "tracker.toml";
    // Include various whitespace and structural bytes.
    const std::string body =
        "[smoother]\n"
        "deadband_mm = 12.5\n"
        "\n"
        "[network]\n"
        "ue_host = \"x.y.z\"\n";

    const auto r = write_atomic(target, body);
    REQUIRE(r.outcome == WriteOutcome::Ok);
    CHECK(read_file(target) == body);
}

TEST_CASE("write_atomic: tmp file lives in the target's parent dir") {
    // Indirect proof: after a successful write, no tmp leakage anywhere
    // in the parent (rules out any stray .tracker.toml.* artifact in a
    // different filesystem). This is the structural shape that prevents
    // `rename(2)` EXDEV.
    TempDir td("tmp_in_parent");
    const fs::path target = td.path / "tracker.toml";

    REQUIRE(write_atomic(target, "x\n").outcome == WriteOutcome::Ok);
    CHECK_FALSE(any_tmp_leftover(td.path));
    // Also: only `tracker.toml` should be present.
    int file_count = 0;
    for (const auto& e : fs::directory_iterator(td.path)) {
        (void)e;
        ++file_count;
    }
    CHECK(file_count == 1);
}

TEST_CASE("write_atomic: file mode is 0644 (operator-readable)") {
    TempDir td("mode");
    const fs::path target = td.path / "tracker.toml";
    REQUIRE(write_atomic(target, "x\n").outcome == WriteOutcome::Ok);

    struct ::stat st{};
    REQUIRE(::stat(target.c_str(), &st) == 0);
    // Strip file-type bits; compare only permission bits.
    const mode_t perms = st.st_mode & 0777;
    CHECK(perms == 0644);
}

TEST_CASE("outcome_to_string handles every variant") {
    using godo::config::outcome_to_string;
    CHECK(outcome_to_string(WriteOutcome::Ok)                == "ok");
    CHECK(outcome_to_string(WriteOutcome::ParentNotWritable) == "parent_not_writable");
    CHECK(outcome_to_string(WriteOutcome::MkstempFailed)     == "mkstemp_failed");
    CHECK(outcome_to_string(WriteOutcome::WriteFailed)       == "write_failed");
    CHECK(outcome_to_string(WriteOutcome::FsyncFailed)       == "fsync_failed");
    CHECK(outcome_to_string(WriteOutcome::RenameFailed)      == "rename_failed");
}
