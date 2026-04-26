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
//   Response → {"ok":true}\n
//              {"ok":true,"mode":"<...>"}\n
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

namespace godo::uds {

// Mode-setter / mode-getter callbacks. Production wires these to
// `godo::rt::g_amcl_mode`; tests inject their own atomic to verify
// dispatch without stomping on the global.
using ModeSetter = std::function<void(godo::rt::AmclMode)>;
using ModeGetter = std::function<godo::rt::AmclMode()>;

class UdsServer {
public:
    UdsServer(std::string socket_path,
              ModeGetter  get_mode,
              ModeSetter  set_mode);

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

    std::string socket_path_;
    ModeGetter  get_mode_;
    ModeSetter  set_mode_;
    int         listen_fd_ = -1;
    bool        path_bound_ = false;
};

}  // namespace godo::uds
