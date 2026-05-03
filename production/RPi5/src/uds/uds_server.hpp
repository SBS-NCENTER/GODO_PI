#pragma once

// UDS control-plane server.
//
// Listens on a Unix-domain SOCK_STREAM socket and translates JSON-lines
// commands into godo::rt::AmclMode transitions. The seam Phase 4-3
// `godo-webctl` will eventually drive.
//
// Wire protocol (see doc/uds_protocol.md):
//   Request  → {"cmd":"set_mode","mode":"<Idle|OneShot|Live>"}\n
//              {"cmd":"get_mode"}\n
//              {"cmd":"ping"}\n
//              {"cmd":"get_last_pose"}\n   (Track B; uds_protocol.md §C.4)
//              {"cmd":"get_last_scan"}\n   (Track D; uds_protocol.md §C.5)
//              {"cmd":"get_jitter"}\n      (PR-DIAG; uds_protocol.md §C.6)
//              {"cmd":"get_amcl_rate"}\n   (PR-DIAG; uds_protocol.md §C.7)
//   Response → {"ok":true}\n
//              {"ok":true,"mode":"<...>"}\n
//              {"ok":true,"valid":<0|1>,"x_m":...,...}\n
//              {"ok":true,"valid":<0|1>,"forced":...,"pose_valid":...,
//                "iterations":...,"published_mono_ns":...,
//                "pose_x_m":...,"pose_y_m":...,"pose_yaw_deg":...,
//                "n":...,"angles_deg":[...],"ranges_m":[...]}\n
//              {"ok":true,"valid":<0|1>,"p50_ns":...,...}\n
//              {"ok":true,"valid":<0|1>,"hz":...,...}\n
//              {"ok":false,"err":"<code>"}\n
//
// One client at a time, request/response then close. Listen socket is
// polled with a 100 ms timeout (constants::SHUTDOWN_POLL_TIMEOUT_MS) so
// `g_running.store(false)` is observed within one cycle (M1).
//
// File permissions are set to 0660 on bind. Until godo-tracker.service
// introduces SocketGroup= (Phase 4-2 follow-up), any client must run
// under the same uid as godo_tracker_rt; this matches the operator
// setup on news-pi01 where both processes run as `ncenter`.

#include <functional>
#include <string>

#include "core/rt_flags.hpp"
#include "core/rt_types.hpp"

namespace godo::uds {

// Mode-setter / mode-getter callbacks. Production wires these to
// `godo::rt::g_amcl_mode`; tests inject their own atomic to verify
// dispatch without stomping on the global.
using ModeSetter = std::function<void(godo::rt::AmclMode)>;
using ModeGetter = std::function<godo::rt::AmclMode()>;

// Track B — `get_last_pose` callback. Production wires this to a
// Seqlock<LastPose>::load(). A nullptr callback is treated as "valid=0"
// (no pose ever published) — the client receives a well-formed response
// with valid=false and the rest of the fields zeroed.
using LastPoseGetter = std::function<godo::rt::LastPose()>;

// Track D — `get_last_scan` callback. Production wires this to a
// Seqlock<LastScan>::load(). Same null-callback semantics as
// LastPoseGetter — clients distinguish "no scan yet" (valid=0) from
// "tracker down" (no UDS reply).
using LastScanGetter = std::function<godo::rt::LastScan()>;

// issue#27 — `get_last_output` callback. Production wires this to a
// Seqlock<LastOutputFrame>::load(). Same null-callback semantics:
// valid=0 distinguishes "no frame published yet" from "tracker down".
using LastOutputGetter = std::function<godo::rt::LastOutputFrame()>;

// Track B-DIAG (PR-DIAG) — `get_jitter` / `get_amcl_rate` callbacks.
// Production wires these to Seqlock<JitterSnapshot>::load() /
// Seqlock<AmclIterationRate>::load() owned by main.cpp; the diag
// publisher thread is the only writer (build-grep
// [jitter-publisher-grep]). Null callback → valid=0 sentinel reply.
using JitterGetter   = std::function<godo::rt::JitterSnapshot()>;
using AmclRateGetter = std::function<godo::rt::AmclIterationRate()>;

// Track B-CONFIG (PR-CONFIG-α) — config edit callbacks.
//
// - ConfigGetter           returns a JSON-array body for `get_config`.
// - ConfigSchemaGetter     returns a JSON-array body for
//                          `get_config_schema` (pure; no live state).
// - ConfigSetter           applies (key, value_text); returns the
//                          tuple `{ok, err, err_detail, reload_class}`
//                          serialized as a small POD.
//
// Production wires Setter to godo::config::apply_set; Getter to
// apply_get_all; SchemaGetter to apply_get_schema. Null callbacks
// surface `config_unsupported` to the wire.
struct ConfigSetReply {
    bool        ok           = false;
    std::string err;            // bad_key | bad_type | bad_value | write_failed
    std::string err_detail;     // human-readable detail; ASCII only
    std::string reload_class;   // "hot" | "restart" | "recalibrate"
};

using ConfigGetter       = std::function<std::string()>;
using ConfigSchemaGetter = std::function<std::string()>;
using ConfigSetter       = std::function<ConfigSetReply(std::string_view key,
                                                        std::string_view value)>;

class UdsServer {
public:
    UdsServer(std::string        socket_path,
              ModeGetter         get_mode,
              ModeSetter         set_mode,
              LastPoseGetter     get_last_pose      = nullptr,
              LastScanGetter     get_last_scan      = nullptr,
              JitterGetter       get_jitter         = nullptr,
              AmclRateGetter     get_amcl_rate      = nullptr,
              ConfigGetter       get_config         = nullptr,
              ConfigSchemaGetter get_config_schema  = nullptr,
              ConfigSetter       set_config         = nullptr,
              LastOutputGetter   get_last_output    = nullptr);

    UdsServer(const UdsServer&)            = delete;
    UdsServer& operator=(const UdsServer&) = delete;

    ~UdsServer();

    // Bind, listen, chmod 0660. Throws std::runtime_error on any failure.
    void open();

    // Accept loop. Returns when godo::rt::g_running is false. Each
    // accepted connection handles exactly one request line then closes.
    void run();

    // Close the listen socket and unlink the socket path. Idempotent.
    void close() noexcept;

private:
    void handle_one_request(int conn_fd) noexcept;

    std::string        socket_path_;
    ModeGetter         get_mode_;
    ModeSetter         set_mode_;
    LastPoseGetter     get_last_pose_;
    LastScanGetter     get_last_scan_;
    JitterGetter       get_jitter_;
    AmclRateGetter     get_amcl_rate_;
    ConfigGetter       get_config_;
    ConfigSchemaGetter get_config_schema_;
    ConfigSetter       set_config_;
    LastOutputGetter   get_last_output_;
    int                listen_fd_  = -1;
    bool               path_bound_ = false;
};

// issue#18 — UDS bootstrap audit free functions. All three are pure
// noexcept boot-time helpers; SOLE caller in production is `main()` for
// `audit_runtime_dir` + `sweep_stale_siblings`, and the rename-failure
// throw site inside `UdsServer::open()` for `log_lstat_for_throw`. The
// last one is exposed (rather than file-private) so the unit test can
// exercise its stderr output without forcing rename(2) failure (Mi3).

// MF3 — emit a single stderr line summarising the inherited
// /run/godo/<basename> + sibling state. Best-effort; never aborts boot.
void audit_runtime_dir(const std::string& socket_path) noexcept;

// SF3 — unlink stale `<socket_path>.*.tmp` siblings older than
// constants::UDS_STALE_SIBLING_MIN_AGE_SEC seconds. Best-effort; failures
// are logged to stderr but never aborts boot. Caller MUST hold the
// tracker pidfile lock before invoking this (CODEBASE invariant (l)).
void sweep_stale_siblings(const std::string& socket_path) noexcept;

// MF2 — lstat the given path and emit one stderr line with TYPE+size or
// errno discriminator. Used pre-throw on the rename-failure path so
// journalctl records both endpoints' filesystem state. `label` is a
// short tag like "tmp_path" or "target" embedded in the log line.
void log_lstat_for_throw(const std::string& path, const char* label) noexcept;

}  // namespace godo::uds
