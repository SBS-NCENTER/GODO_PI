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

TEST_CASE("apply_get_all returns 51 keys, alphabetical, valid JSON-ish") {
    Config live_cfg = Config::make_default();
    std::mutex mtx;
    const std::string body = apply_get_all(live_cfg, mtx);
    // Trivial structural checks.
    CHECK_FALSE(body.empty());
    CHECK(body.front() == '{');
    CHECK(body.back()  == '}');
    // Count commas as "key separators" — exactly 50 between 51 items
    // (issue#14 Maj-1 fold added 3 webctl.mapping_*_s rows on top of
    // issue#12's 48; issue#5 had added 4 Live-carry on top of 42).
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
    CHECK(commas == 50);
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
    // issue#14 Maj-1 — webctl-owned mapping-stop timing ladder rows.
    // Defaults: docker_stop_grace=20, systemd_stop_timeout=30, webctl_stop_timeout=35.
    CHECK(body.find("\"webctl.mapping_docker_stop_grace_s\":20") != std::string::npos);
    CHECK(body.find("\"webctl.mapping_systemd_stop_timeout_s\":30") != std::string::npos);
    CHECK(body.find("\"webctl.mapping_webctl_stop_timeout_s\":35") != std::string::npos);
    // Last key (alphabetical): "webctl.scan_stream_hz".
    CHECK(body.find("\"webctl.scan_stream_hz\":") != std::string::npos);
}

TEST_CASE("apply_get_schema returns 51-element JSON array") {
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
    CHECK(commas == 50);
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
    // issue#14 Maj-1 — webctl-owned mapping timing rows surface too.
    CHECK(body.find("\"name\":\"webctl.mapping_docker_stop_grace_s\"") != std::string::npos);
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
    // issue#14 Mode-B M1 fix (2026-05-02 KST): the cross-trio ordering
    // invariant `docker_stop_grace < systemd_stop_timeout < webctl_stop_timeout`
    // must be enforced at apply time. Without this check the operator can
    // save `docker=60, systemd=20` (each individually in range) via the
    // Config tab → tracker writes torn trio → next webctl boot raises
    // WebctlTomlError → crash loop, recoverable only via SSH.

    // Case A: docker >= systemd → reject.
    {
        TempDir td("ladder_a");
        Config live_cfg = Config::make_default();
        std::mutex mtx;
        Seqlock<HotConfig> hot_seq;
        hot_seq.store(godo::core::snapshot_hot(live_cfg));
        const auto toml = td.path / "tracker.toml";
        const auto flag = td.path / "restart_pending";
        // First push systemd to 20 (default 30, both in range).
        // Actually default is docker=20, systemd=30, webctl=35. Push docker
        // up so docker >= systemd.
        const auto r = apply_set("webctl.mapping_docker_stop_grace_s", "30",
                                 live_cfg, mtx, hot_seq, toml, flag);
        CHECK_FALSE(r.ok);
        CHECK(r.err == "bad_value");
        CHECK(r.err_detail.find("docker_stop_grace_s") != std::string::npos);
        CHECK(r.err_detail.find("systemd_stop_timeout_s") != std::string::npos);
        CHECK(live_cfg.webctl_mapping_docker_stop_grace_s == 20);  // unchanged
        CHECK_FALSE(fs::exists(toml));
    }

    // Case B: systemd >= webctl → reject.
    {
        TempDir td("ladder_b");
        Config live_cfg = Config::make_default();
        std::mutex mtx;
        Seqlock<HotConfig> hot_seq;
        hot_seq.store(godo::core::snapshot_hot(live_cfg));
        const auto toml = td.path / "tracker.toml";
        const auto flag = td.path / "restart_pending";
        // Default systemd=30, webctl=35. Push systemd to 35 (==).
        const auto r = apply_set("webctl.mapping_systemd_stop_timeout_s", "35",
                                 live_cfg, mtx, hot_seq, toml, flag);
        CHECK_FALSE(r.ok);
        CHECK(r.err == "bad_value");
        CHECK(r.err_detail.find("systemd_stop_timeout_s") != std::string::npos);
        CHECK(r.err_detail.find("webctl_stop_timeout_s") != std::string::npos);
        CHECK(live_cfg.webctl_mapping_systemd_stop_timeout_s == 30);  // unchanged
        CHECK_FALSE(fs::exists(toml));
    }

    // Case C: valid bump (preserves ordering) succeeds.
    {
        TempDir td("ladder_c");
        Config live_cfg = Config::make_default();
        std::mutex mtx;
        Seqlock<HotConfig> hot_seq;
        hot_seq.store(godo::core::snapshot_hot(live_cfg));
        const auto toml = td.path / "tracker.toml";
        const auto flag = td.path / "restart_pending";
        // Bump webctl 35 → 50 (preserves docker(20) < systemd(30) < 50).
        const auto r = apply_set("webctl.mapping_webctl_stop_timeout_s", "50",
                                 live_cfg, mtx, hot_seq, toml, flag);
        CHECK(r.ok);
        CHECK(live_cfg.webctl_mapping_webctl_stop_timeout_s == 50);
    }
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
