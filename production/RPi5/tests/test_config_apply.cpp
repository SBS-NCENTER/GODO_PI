// Track B-CONFIG (PR-CONFIG-α) — apply_set / apply_get_all /
// apply_get_schema integration tests.
//
// Pattern: build a default Config + tmp dir → call apply_set → assert
// (a) live_cfg mutated, (b) TOML file changed, (c) hot_seq published
// (for hot keys) OR pending flag touched (for restart/recalibrate).

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <cstdio>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <sstream>
#include <string>
#include <system_error>

#include <unistd.h>

#include "config/apply.hpp"
#include "config/restart_pending.hpp"
#include "core/config.hpp"
#include "core/hot_config.hpp"
#include "core/seqlock.hpp"

using godo::config::apply_get_all;
using godo::config::apply_get_schema;
using godo::config::apply_set;
using godo::config::is_pending;
using godo::core::Config;
using godo::core::HotConfig;
using godo::core::config_schema::ReloadClass;
using godo::rt::Seqlock;
namespace fs = std::filesystem;

namespace {

struct TempDir {
    fs::path path;
    explicit TempDir(const char* tag) {
        char buf[256];
        std::snprintf(buf, sizeof(buf), "/tmp/godo_apply_%d_%s",
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

std::string read_file(const fs::path& p) {
    std::ifstream f(p);
    std::stringstream ss;
    ss << f.rdbuf();
    return ss.str();
}

}  // namespace

TEST_CASE("apply_set hot-class: deadband_mm publishes HotConfig + no flag touch") {
    TempDir td("hot");
    Config live_cfg = Config::make_default();
    std::mutex mtx;
    Seqlock<HotConfig> hot_seq;
    hot_seq.store(godo::core::snapshot_hot(live_cfg));
    const auto toml = td.path / "tracker.toml";
    const auto flag = td.path / "restart_pending";

    const auto pre_gen = hot_seq.generation();
    const auto r = apply_set("smoother.deadband_mm", "12.5",
                             live_cfg, mtx, hot_seq, toml, flag);
    CHECK(r.ok);
    CHECK(r.reload_class == ReloadClass::Hot);
    CHECK(live_cfg.deadband_mm == 12.5);
    CHECK(fs::exists(toml));
    const auto h = hot_seq.load();
    CHECK(h.deadband_mm == 12.5);
    CHECK(hot_seq.generation() != pre_gen);
    // Hot keys do NOT touch the flag.
    CHECK_FALSE(is_pending(flag));
}

TEST_CASE("apply_set restart-class: ue_port touches flag + no HotConfig publish") {
    TempDir td("restart");
    Config live_cfg = Config::make_default();
    std::mutex mtx;
    Seqlock<HotConfig> hot_seq;
    hot_seq.store(godo::core::snapshot_hot(live_cfg));
    const auto toml = td.path / "tracker.toml";
    const auto flag = td.path / "restart_pending";

    const auto pre_gen  = hot_seq.generation();
    const auto pre_port = live_cfg.ue_port;

    const auto r = apply_set("network.ue_port", "7777",
                             live_cfg, mtx, hot_seq, toml, flag);
    CHECK(r.ok);
    CHECK(r.reload_class == ReloadClass::Restart);
    CHECK(live_cfg.ue_port == 7777);
    CHECK(live_cfg.ue_port != pre_port);
    CHECK(is_pending(flag));
    // Restart class must NOT republish HotConfig.
    CHECK(hot_seq.generation() == pre_gen);
}

TEST_CASE("apply_set recalibrate-class: origin_x_m touches flag + no HotConfig publish") {
    TempDir td("recal");
    Config live_cfg = Config::make_default();
    std::mutex mtx;
    Seqlock<HotConfig> hot_seq;
    hot_seq.store(godo::core::snapshot_hot(live_cfg));
    const auto toml = td.path / "tracker.toml";
    const auto flag = td.path / "restart_pending";

    const auto pre_gen = hot_seq.generation();

    const auto r = apply_set("amcl.origin_x_m", "1.25",
                             live_cfg, mtx, hot_seq, toml, flag);
    CHECK(r.ok);
    CHECK(r.reload_class == ReloadClass::Recalibrate);
    CHECK(live_cfg.amcl_origin_x_m == 1.25);
    CHECK(is_pending(flag));
    CHECK(hot_seq.generation() == pre_gen);
}

TEST_CASE("apply_set bad_key: live_cfg + TOML + hot_seq + flag all unchanged") {
    TempDir td("bad_key");
    Config live_cfg = Config::make_default();
    std::mutex mtx;
    Seqlock<HotConfig> hot_seq;
    hot_seq.store(godo::core::snapshot_hot(live_cfg));
    const auto toml = td.path / "tracker.toml";
    const auto flag = td.path / "restart_pending";

    const auto pre_gen     = hot_seq.generation();
    const auto pre_port    = live_cfg.ue_port;
    const auto pre_dead_mm = live_cfg.deadband_mm;

    const auto r = apply_set("nope.foo", "1",
                             live_cfg, mtx, hot_seq, toml, flag);
    CHECK_FALSE(r.ok);
    CHECK(r.err == "bad_key");
    CHECK(live_cfg.ue_port     == pre_port);
    CHECK(live_cfg.deadband_mm == pre_dead_mm);
    CHECK_FALSE(fs::exists(toml));
    CHECK_FALSE(is_pending(flag));
    CHECK(hot_seq.generation() == pre_gen);
}

TEST_CASE("apply_set bad_value: live_cfg + TOML + hot_seq + flag all unchanged") {
    TempDir td("bad_value");
    Config live_cfg = Config::make_default();
    std::mutex mtx;
    Seqlock<HotConfig> hot_seq;
    hot_seq.store(godo::core::snapshot_hot(live_cfg));
    const auto toml = td.path / "tracker.toml";
    const auto flag = td.path / "restart_pending";

    const auto pre_gen     = hot_seq.generation();
    const auto pre_dead_mm = live_cfg.deadband_mm;

    const auto r = apply_set("smoother.deadband_mm", "9999.0",
                             live_cfg, mtx, hot_seq, toml, flag);
    CHECK_FALSE(r.ok);
    CHECK(r.err == "bad_value");
    CHECK(live_cfg.deadband_mm == pre_dead_mm);
    CHECK_FALSE(fs::exists(toml));
    CHECK_FALSE(is_pending(flag));
    CHECK(hot_seq.generation() == pre_gen);
}

TEST_CASE("apply_set bad_type: int field rejects decimal form") {
    TempDir td("bad_type");
    Config live_cfg = Config::make_default();
    std::mutex mtx;
    Seqlock<HotConfig> hot_seq;
    hot_seq.store(godo::core::snapshot_hot(live_cfg));
    const auto toml = td.path / "tracker.toml";
    const auto flag = td.path / "restart_pending";

    const auto r = apply_set("network.ue_port", "6677.0",
                             live_cfg, mtx, hot_seq, toml, flag);
    CHECK_FALSE(r.ok);
    CHECK(r.err == "bad_type");
    CHECK_FALSE(fs::exists(toml));
}

TEST_CASE("apply_set string field updates live_cfg + TOML") {
    TempDir td("string");
    Config live_cfg = Config::make_default();
    std::mutex mtx;
    Seqlock<HotConfig> hot_seq;
    hot_seq.store(godo::core::snapshot_hot(live_cfg));
    const auto toml = td.path / "tracker.toml";
    const auto flag = td.path / "restart_pending";

    const auto r = apply_set("network.ue_host", "10.0.0.42",
                             live_cfg, mtx, hot_seq, toml, flag);
    CHECK(r.ok);
    CHECK(live_cfg.ue_host == "10.0.0.42");
    const auto body = read_file(toml);
    CHECK(body.find("ue_host = \"10.0.0.42\"") != std::string::npos);
}

TEST_CASE("apply_set: write to non-existent parent → write_failed; live_cfg untouched") {
    TempDir td("write_failed");
    Config live_cfg = Config::make_default();
    std::mutex mtx;
    Seqlock<HotConfig> hot_seq;
    hot_seq.store(godo::core::snapshot_hot(live_cfg));
    // toml path's parent dir does not exist.
    const auto toml = td.path / "no_such_subdir" / "tracker.toml";
    const auto flag = td.path / "restart_pending";

    const auto pre_dead_mm = live_cfg.deadband_mm;

    const auto r = apply_set("smoother.deadband_mm", "12.5",
                             live_cfg, mtx, hot_seq, toml, flag);
    CHECK_FALSE(r.ok);
    CHECK(r.err == "write_failed");
    CHECK(r.err_detail.find("parent_not_writable") != std::string::npos);
    CHECK(live_cfg.deadband_mm == pre_dead_mm);
    CHECK_FALSE(fs::exists(toml));
}

TEST_CASE("apply_get_all returns 68 keys, alphabetical, valid JSON-ish") {
    Config live_cfg = Config::make_default();
    std::mutex mtx;
    const std::string body = apply_get_all(live_cfg, mtx);
    // Trivial structural checks.
    CHECK_FALSE(body.empty());
    CHECK(body.front() == '{');
    CHECK(body.back()  == '}');
    // Count commas as "key separators" — exactly 67 between 68 items
    // (issue#11 added amcl.parallel_eval_workers).
    int commas = 0;
    int depth = 0;
    bool in_str = false;
    for (char c : body) {
        if (c == '"') in_str = !in_str;
        else if (!in_str) {
            if (c == '{' || c == '[') ++depth;
            else if (c == '}' || c == ']') --depth;
            else if (c == ',' && depth == 1) ++commas;
        }
    }
    CHECK(commas == 67);
    // issue#11 — fork-join particle eval pool workers default = 3.
    CHECK(body.find("\"amcl.parallel_eval_workers\":3") != std::string::npos);
    // First key (alphabetical): "amcl.anneal_iters_per_phase" (Track D-5).
    CHECK(body.find("\"amcl.anneal_iters_per_phase\":") != std::string::npos);
    // issue#3 — hint default rows.
    CHECK(body.find("\"amcl.hint_sigma_xy_m_default\":") != std::string::npos);
    CHECK(body.find("\"amcl.hint_sigma_yaw_deg_default\":") != std::string::npos);
    // issue#5 — Live-carry rows.
    CHECK(body.find("\"amcl.live_carry_pose_as_hint\":") != std::string::npos);
    CHECK(body.find("\"amcl.live_carry_schedule_m\":") != std::string::npos);
    CHECK(body.find("\"amcl.live_carry_sigma_xy_m\":") != std::string::npos);
    CHECK(body.find("\"amcl.live_carry_sigma_yaw_deg\":") != std::string::npos);
    // issue#12 — webctl-owned rows. Default value is 30 for each
    // (Config::make_default wires WEBCTL_*_STREAM_HZ_DEFAULT).
    CHECK(body.find("\"webctl.pose_stream_hz\":30") != std::string::npos);
    CHECK(body.find("\"webctl.scan_stream_hz\":30") != std::string::npos);
    // issue#14 Maj-1 / issue#16.1 — webctl-owned mapping-stop timing
    // ladder rows. Defaults: docker_stop_grace=30,
    // systemctl_subprocess_timeout=45, systemd_stop_timeout=45,
    // webctl_stop_timeout=50.
    CHECK(body.find("\"webctl.mapping_docker_stop_grace_s\":30") != std::string::npos);
    CHECK(body.find("\"webctl.mapping_systemctl_subprocess_timeout_s\":45") != std::string::npos);
    CHECK(body.find("\"webctl.mapping_systemd_stop_timeout_s\":45") != std::string::npos);
    CHECK(body.find("\"webctl.mapping_webctl_stop_timeout_s\":50") != std::string::npos);
    // Last key (alphabetical): "webctl.scan_stream_hz".
    CHECK(body.find("\"webctl.scan_stream_hz\":") != std::string::npos);
}

TEST_CASE("apply_get_schema returns 68-element JSON array") {
    const std::string body = apply_get_schema();
    CHECK(body.front() == '[');
    CHECK(body.back()  == ']');
    int commas = 0;
    int depth = 0;
    bool in_str = false;
    for (char c : body) {
        if (c == '"') in_str = !in_str;
        else if (!in_str) {
            if (c == '{' || c == '[') ++depth;
            else if (c == '}' || c == ']') --depth;
            else if (c == ',' && depth == 1) ++commas;
        }
    }
    CHECK(commas == 67);
    // issue#11 — schema row name surfaces.
    CHECK(body.find("\"name\":\"amcl.parallel_eval_workers\"") !=
          std::string::npos);
    // Spot-check schema field names.
    CHECK(body.find("\"reload_class\":\"hot\"")         != std::string::npos);
    CHECK(body.find("\"reload_class\":\"restart\"")     != std::string::npos);
    CHECK(body.find("\"reload_class\":\"recalibrate\"") != std::string::npos);
    CHECK(body.find("\"type\":\"int\"")    != std::string::npos);
    CHECK(body.find("\"type\":\"double\"") != std::string::npos);
    CHECK(body.find("\"type\":\"string\"") != std::string::npos);
    // issue#12 — webctl-owned rows surface in the schema endpoint.
    CHECK(body.find("\"name\":\"webctl.pose_stream_hz\"") != std::string::npos);
    CHECK(body.find("\"name\":\"webctl.scan_stream_hz\"") != std::string::npos);
    // issue#14 Maj-1 / issue#16.1 — webctl-owned mapping timing rows surface too.
    CHECK(body.find("\"name\":\"webctl.mapping_docker_stop_grace_s\"") != std::string::npos);
    CHECK(body.find("\"name\":\"webctl.mapping_systemctl_subprocess_timeout_s\"") != std::string::npos);
    CHECK(body.find("\"name\":\"webctl.mapping_systemd_stop_timeout_s\"") != std::string::npos);
    CHECK(body.find("\"name\":\"webctl.mapping_webctl_stop_timeout_s\"") != std::string::npos);
}

TEST_CASE("apply_set webctl.pose_stream_hz: round-trips through render_toml") {
    // issue#12 / Mode-A C2 + C3 fix (post Parent decision A1, A5):
    // webctl.* keys are first-class Config fields; apply_set must
    // succeed (not return internal_error), the rendered tracker.toml
    // must carry the new value, and apply_get_all must reflect it.
    TempDir td("webctl_pose");
    Config live_cfg = Config::make_default();
    std::mutex mtx;
    Seqlock<HotConfig> hot_seq;
    hot_seq.store(godo::core::snapshot_hot(live_cfg));
    const auto toml = td.path / "tracker.toml";
    const auto flag = td.path / "restart_pending";

    const auto r = apply_set("webctl.pose_stream_hz", "45",
                             live_cfg, mtx, hot_seq, toml, flag);
    CHECK(r.ok);
    CHECK(r.reload_class == ReloadClass::Restart);
    CHECK(live_cfg.webctl_pose_stream_hz == 45);
    CHECK(is_pending(flag));
    const auto body = read_file(toml);
    CHECK(body.find("[webctl]") != std::string::npos);
    CHECK(body.find("pose_stream_hz = 45") != std::string::npos);

    // apply_get_all reflects the post-edit value (Mode-A C3 RESOLVED).
    const std::string snap = apply_get_all(live_cfg, mtx);
    CHECK(snap.find("\"webctl.pose_stream_hz\":45") != std::string::npos);
}

TEST_CASE("apply_set webctl.mapping ladder: torn ordering rejected with bad_value") {
    // issue#14 Mode-B M1 fix (2026-05-02 KST) + issue#16.1 (2026-05-03):
    // the cross-quartet ordering invariant
    //   docker_stop_grace < systemd_stop_timeout < webctl_stop_timeout
    //   AND systemctl_subprocess_timeout < webctl_stop_timeout
    // must be enforced at apply time. Without this check the operator
    // can save inverted trios via the Config tab → tracker writes
    // torn payload → next webctl boot raises WebctlTomlError → crash
    // loop, recoverable only via SSH.

    // Case A: docker >= systemd → reject.
    // Defaults are docker=30, systemd=45. Push docker to 45 (==systemd).
    {
        TempDir td("ladder_a");
        Config live_cfg = Config::make_default();
        std::mutex mtx;
        Seqlock<HotConfig> hot_seq;
        hot_seq.store(godo::core::snapshot_hot(live_cfg));
        const auto toml = td.path / "tracker.toml";
        const auto flag = td.path / "restart_pending";
        const auto r = apply_set("webctl.mapping_docker_stop_grace_s", "45",
                                 live_cfg, mtx, hot_seq, toml, flag);
        CHECK_FALSE(r.ok);
        CHECK(r.err == "bad_value");
        CHECK(r.err_detail.find("docker_stop_grace_s") != std::string::npos);
        CHECK(r.err_detail.find("systemd_stop_timeout_s") != std::string::npos);
        CHECK(live_cfg.webctl_mapping_docker_stop_grace_s == 30);  // unchanged
        CHECK_FALSE(fs::exists(toml));
    }

    // Case B: systemd >= webctl → reject.
    // Default systemd=45, webctl=50. Push systemd to 50 (==).
    {
        TempDir td("ladder_b");
        Config live_cfg = Config::make_default();
        std::mutex mtx;
        Seqlock<HotConfig> hot_seq;
        hot_seq.store(godo::core::snapshot_hot(live_cfg));
        const auto toml = td.path / "tracker.toml";
        const auto flag = td.path / "restart_pending";
        const auto r = apply_set("webctl.mapping_systemd_stop_timeout_s", "50",
                                 live_cfg, mtx, hot_seq, toml, flag);
        CHECK_FALSE(r.ok);
        CHECK(r.err == "bad_value");
        CHECK(r.err_detail.find("systemd_stop_timeout_s") != std::string::npos);
        CHECK(r.err_detail.find("webctl_stop_timeout_s") != std::string::npos);
        CHECK(live_cfg.webctl_mapping_systemd_stop_timeout_s == 45);  // unchanged
        CHECK_FALSE(fs::exists(toml));
    }

    // Case C: valid bump (preserves ordering) succeeds.
    // Bump webctl 50 → 60 to preserve all relations.
    {
        TempDir td("ladder_c");
        Config live_cfg = Config::make_default();
        std::mutex mtx;
        Seqlock<HotConfig> hot_seq;
        hot_seq.store(godo::core::snapshot_hot(live_cfg));
        const auto toml = td.path / "tracker.toml";
        const auto flag = td.path / "restart_pending";
        const auto r = apply_set("webctl.mapping_webctl_stop_timeout_s", "60",
                                 live_cfg, mtx, hot_seq, toml, flag);
        CHECK(r.ok);
        CHECK(live_cfg.webctl_mapping_webctl_stop_timeout_s == 60);
    }
}

TEST_CASE("apply_set webctl.mapping_systemctl_subprocess_timeout_s round-trips through render_toml") {
    // issue#16.1 — new schema row must round-trip through render_toml +
    // apply_get_all without internal_error. Range [10, 90]; default 45.
    TempDir td("systemctl_rt");
    Config live_cfg = Config::make_default();
    std::mutex mtx;
    Seqlock<HotConfig> hot_seq;
    hot_seq.store(godo::core::snapshot_hot(live_cfg));
    const auto toml = td.path / "tracker.toml";
    const auto flag = td.path / "restart_pending";

    const auto r = apply_set("webctl.mapping_systemctl_subprocess_timeout_s", "40",
                             live_cfg, mtx, hot_seq, toml, flag);
    CHECK(r.ok);
    CHECK(r.reload_class == ReloadClass::Restart);
    CHECK(live_cfg.webctl_mapping_systemctl_subprocess_timeout_s == 40);
    CHECK(is_pending(flag));
    const auto body = read_file(toml);
    CHECK(body.find("[webctl]") != std::string::npos);
    CHECK(body.find("mapping_systemctl_subprocess_timeout_s = 40") != std::string::npos);

    const std::string snap = apply_get_all(live_cfg, mtx);
    CHECK(snap.find("\"webctl.mapping_systemctl_subprocess_timeout_s\":40") != std::string::npos);
}

TEST_CASE("apply_set webctl.mapping_systemctl_subprocess_timeout_s exceeds webctl_stop_timeout → bad_value") {
    // issue#16.1 — operator pushes systemctl_s past webctl_s; apply_set
    // ladder gate must reject with both key names in err_detail.
    TempDir td("systemctl_over");
    Config live_cfg = Config::make_default();
    std::mutex mtx;
    Seqlock<HotConfig> hot_seq;
    hot_seq.store(godo::core::snapshot_hot(live_cfg));
    const auto toml = td.path / "tracker.toml";
    const auto flag = td.path / "restart_pending";
    // Default systemctl=45, webctl=50. Push systemctl to 60.
    const auto r = apply_set("webctl.mapping_systemctl_subprocess_timeout_s", "60",
                             live_cfg, mtx, hot_seq, toml, flag);
    CHECK_FALSE(r.ok);
    CHECK(r.err == "bad_value");
    CHECK(r.err_detail.find("systemctl_subprocess_timeout_s") != std::string::npos);
    CHECK(r.err_detail.find("webctl_stop_timeout_s") != std::string::npos);
    CHECK(live_cfg.webctl_mapping_systemctl_subprocess_timeout_s == 45);  // unchanged
    CHECK_FALSE(fs::exists(toml));
}

TEST_CASE("apply_set webctl.scan_stream_hz: out-of-range rejected at validate") {
    // Schema range is [1, 60]. apply_set must fail bad_value and leave
    // live_cfg untouched.
    TempDir td("webctl_scan_oor");
    Config live_cfg = Config::make_default();
    std::mutex mtx;
    Seqlock<HotConfig> hot_seq;
    hot_seq.store(godo::core::snapshot_hot(live_cfg));
    const auto toml = td.path / "tracker.toml";
    const auto flag = td.path / "restart_pending";

    const auto pre = live_cfg.webctl_scan_stream_hz;

    const auto r = apply_set("webctl.scan_stream_hz", "100",
                             live_cfg, mtx, hot_seq, toml, flag);
    CHECK_FALSE(r.ok);
    CHECK(r.err == "bad_value");
    CHECK(live_cfg.webctl_scan_stream_hz == pre);
    CHECK_FALSE(fs::exists(toml));
}

TEST_CASE("render_toml round-trips through apply_set") {
    TempDir td("render");
    Config live_cfg = Config::make_default();
    std::mutex mtx;
    Seqlock<HotConfig> hot_seq;
    hot_seq.store(godo::core::snapshot_hot(live_cfg));
    const auto toml = td.path / "tracker.toml";
    const auto flag = td.path / "restart_pending";

    apply_set("smoother.deadband_mm", "12.5",
              live_cfg, mtx, hot_seq, toml, flag);

    const std::string body = read_file(toml);
    // Spot-check sections + grouping.
    CHECK(body.find("[smoother]")  != std::string::npos);
    CHECK(body.find("[network]")   != std::string::npos);
    CHECK(body.find("[amcl]")      != std::string::npos);
    CHECK(body.find("[gpio]")      != std::string::npos);
    CHECK(body.find("deadband_mm = 12.5") != std::string::npos);
}

TEST_CASE("apply_set preserves restart-pending after consecutive restart-class edits") {
    // Touching the flag twice in a row is idempotent; pending stays true.
    TempDir td("multi_restart");
    Config live_cfg = Config::make_default();
    std::mutex mtx;
    Seqlock<HotConfig> hot_seq;
    hot_seq.store(godo::core::snapshot_hot(live_cfg));
    const auto toml = td.path / "tracker.toml";
    const auto flag = td.path / "restart_pending";

    apply_set("network.ue_port", "7777",
              live_cfg, mtx, hot_seq, toml, flag);
    CHECK(is_pending(flag));
    apply_set("rt.priority", "60",
              live_cfg, mtx, hot_seq, toml, flag);
    CHECK(is_pending(flag));
    CHECK(live_cfg.ue_port == 7777);
    CHECK(live_cfg.rt_priority == 60);
}

TEST_CASE("apply_set serial.lidar_udev_serial round-trips through render_toml") {
    // issue#10.1 — string-class row, install.sh sole consumer. The
    // C++ validator only enforces non-empty + ASCII printable + ≤256
    // chars; install.sh enforces strict 32-hex format. A 32-hex value
    // must round-trip cleanly.
    TempDir td("udev_serial_rt");
    Config live_cfg = Config::make_default();
    std::mutex mtx;
    Seqlock<HotConfig> hot_seq;
    hot_seq.store(godo::core::snapshot_hot(live_cfg));
    const auto toml = td.path / "tracker.toml";
    const auto flag = td.path / "restart_pending";

    const std::string new_serial = "abcdef0123456789abcdef0123456789";
    const auto r = apply_set("serial.lidar_udev_serial", new_serial,
                             live_cfg, mtx, hot_seq, toml, flag);
    CHECK(r.ok);
    CHECK(r.reload_class == ReloadClass::Restart);
    CHECK(live_cfg.lidar_udev_serial == new_serial);
    CHECK(is_pending(flag));
    const auto body = read_file(toml);
    CHECK(body.find("[serial]") != std::string::npos);
    CHECK(body.find("lidar_udev_serial = \"" + new_serial + "\"") != std::string::npos);

    // apply_get_all reflects the post-edit value.
    const std::string snap = apply_get_all(live_cfg, mtx);
    CHECK(snap.find("\"serial.lidar_udev_serial\":\"" + new_serial + "\"") != std::string::npos);
}

TEST_CASE("apply_set serial.lidar_udev_serial empty value rejected with bad_value") {
    // String validator rejects empty (validate.cpp non-empty rule).
    // live_cfg + TOML must stay untouched on rejection.
    TempDir td("udev_serial_empty");
    Config live_cfg = Config::make_default();
    std::mutex mtx;
    Seqlock<HotConfig> hot_seq;
    hot_seq.store(godo::core::snapshot_hot(live_cfg));
    const auto toml = td.path / "tracker.toml";
    const auto flag = td.path / "restart_pending";

    const auto pre = live_cfg.lidar_udev_serial;
    const auto r = apply_set("serial.lidar_udev_serial", "",
                             live_cfg, mtx, hot_seq, toml, flag);
    CHECK_FALSE(r.ok);
    CHECK(r.err == "bad_value");
    CHECK(live_cfg.lidar_udev_serial == pre);
    CHECK_FALSE(fs::exists(toml));
    CHECK_FALSE(is_pending(flag));
}

TEST_CASE("apply_set then apply_get_all reflects post-edit value") {
    TempDir td("get_after_set");
    Config live_cfg = Config::make_default();
    std::mutex mtx;
    Seqlock<HotConfig> hot_seq;
    hot_seq.store(godo::core::snapshot_hot(live_cfg));
    const auto toml = td.path / "tracker.toml";
    const auto flag = td.path / "restart_pending";

    apply_set("smoother.deadband_mm", "33.5",
              live_cfg, mtx, hot_seq, toml, flag);
    const std::string snap = apply_get_all(live_cfg, mtx);
    CHECK(snap.find("\"smoother.deadband_mm\":33.5") != std::string::npos);
}

// issue#27 — strict {-1, +1} validator at the apply.cpp boundary.
// Schema validator only enforces the relaxed [-1, +1] Int range; the
// per-key rejecting-zero check lives at the consumer boundary
// (feedback_relaxed_validator_strict_installer.md pattern).
TEST_CASE("apply_set output_transform.x_sign accepts +1 and -1") {
    TempDir td("xform_sign_ok");
    Config live_cfg = Config::make_default();
    std::mutex mtx;
    Seqlock<HotConfig> hot_seq;
    hot_seq.store(godo::core::snapshot_hot(live_cfg));
    const auto toml = td.path / "tracker.toml";
    const auto flag = td.path / "restart_pending";

    auto r1 = apply_set("output_transform.x_sign", "1",
                        live_cfg, mtx, hot_seq, toml, flag);
    CHECK(r1.ok);
    CHECK(live_cfg.output_transform_x_sign == 1);
    auto r2 = apply_set("output_transform.x_sign", "-1",
                        live_cfg, mtx, hot_seq, toml, flag);
    CHECK(r2.ok);
    CHECK(live_cfg.output_transform_x_sign == -1);
}

TEST_CASE("apply_set output_transform.x_sign rejects 0 with bad_value") {
    TempDir td("xform_sign_zero");
    Config live_cfg = Config::make_default();
    std::mutex mtx;
    Seqlock<HotConfig> hot_seq;
    hot_seq.store(godo::core::snapshot_hot(live_cfg));
    const auto toml = td.path / "tracker.toml";
    const auto flag = td.path / "restart_pending";

    const int pre = live_cfg.output_transform_x_sign;
    auto r = apply_set("output_transform.x_sign", "0",
                       live_cfg, mtx, hot_seq, toml, flag);
    CHECK_FALSE(r.ok);
    CHECK(r.err == "bad_value");
    CHECK(r.err_detail.find("sign must be -1 or +1") != std::string::npos);
    // live_cfg + TOML untouched.
    CHECK(live_cfg.output_transform_x_sign == pre);
    CHECK_FALSE(fs::exists(toml));
}

TEST_CASE("apply_set output_transform.*_sign — value 2 rejected by schema range") {
    // Defence-in-depth: schema validator rejects |sign| > 1 BEFORE the
    // strict {-1, +1} gate fires. So 2 surfaces as bad_value with the
    // schema range message.
    TempDir td("xform_sign_oor");
    Config live_cfg = Config::make_default();
    std::mutex mtx;
    Seqlock<HotConfig> hot_seq;
    hot_seq.store(godo::core::snapshot_hot(live_cfg));
    const auto toml = td.path / "tracker.toml";
    const auto flag = td.path / "restart_pending";

    auto r = apply_set("output_transform.pan_sign", "2",
                       live_cfg, mtx, hot_seq, toml, flag);
    CHECK_FALSE(r.ok);
    CHECK(r.err == "bad_value");
}

TEST_CASE("apply_set output_transform.x_offset_m round-trips through render_toml") {
    TempDir td("xform_x_offset");
    Config live_cfg = Config::make_default();
    std::mutex mtx;
    Seqlock<HotConfig> hot_seq;
    hot_seq.store(godo::core::snapshot_hot(live_cfg));
    const auto toml = td.path / "tracker.toml";
    const auto flag = td.path / "restart_pending";

    auto r = apply_set("output_transform.x_offset_m", "0.5",
                       live_cfg, mtx, hot_seq, toml, flag);
    CHECK(r.ok);
    CHECK(live_cfg.output_transform_x_offset_m == doctest::Approx(0.5));
    // Restart class — touched the pending flag.
    CHECK(is_pending(flag));
    // TOML round-trips.
    const std::string body = read_file(toml);
    CHECK(body.find("[output_transform]") != std::string::npos);
    CHECK(body.find("x_offset_m = 0.5") != std::string::npos);
}

TEST_CASE("apply_set origin_step.x_m round-trips and survives default-defaults") {
    // origin_step.* is a frontend-only consumer (the SPA reads it via
    // /api/config). Tracker stores verbatim; no tracker logic path
    // consumes the value.
    TempDir td("origin_step_x");
    Config live_cfg = Config::make_default();
    std::mutex mtx;
    Seqlock<HotConfig> hot_seq;
    hot_seq.store(godo::core::snapshot_hot(live_cfg));
    const auto toml = td.path / "tracker.toml";
    const auto flag = td.path / "restart_pending";

    auto r = apply_set("origin_step.x_m", "0.05",
                       live_cfg, mtx, hot_seq, toml, flag);
    CHECK(r.ok);
    CHECK(live_cfg.origin_step_x_m == doctest::Approx(0.05));
    const std::string body = read_file(toml);
    CHECK(body.find("[origin_step]") != std::string::npos);
    CHECK(body.find("x_m = 0.05") != std::string::npos);
}
