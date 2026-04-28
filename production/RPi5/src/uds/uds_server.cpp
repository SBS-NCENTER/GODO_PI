#include "uds_server.hpp"

#include <cerrno>
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <string>
#include <utility>

#include <fcntl.h>
#include <poll.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/un.h>
#include <unistd.h>

#include "core/constants.hpp"
#include "core/rt_flags.hpp"
#include "json_mini.hpp"

namespace godo::uds {

namespace {

// errno-safe perror-style helper.
std::string strerror_safe(int e) {
    char buf[128];
    return std::string(::strerror_r(e, buf, sizeof(buf)));
}

}  // namespace

UdsServer::UdsServer(std::string        socket_path,
                     ModeGetter         get_mode,
                     ModeSetter         set_mode,
                     LastPoseGetter     get_last_pose,
                     LastScanGetter     get_last_scan,
                     JitterGetter       get_jitter,
                     AmclRateGetter     get_amcl_rate,
                     ConfigGetter       get_config,
                     ConfigSchemaGetter get_config_schema,
                     ConfigSetter       set_config)
    : socket_path_(std::move(socket_path)),
      get_mode_(std::move(get_mode)),
      set_mode_(std::move(set_mode)),
      get_last_pose_(std::move(get_last_pose)),
      get_last_scan_(std::move(get_last_scan)),
      get_jitter_(std::move(get_jitter)),
      get_amcl_rate_(std::move(get_amcl_rate)),
      get_config_(std::move(get_config)),
      get_config_schema_(std::move(get_config_schema)),
      set_config_(std::move(set_config)) {}

UdsServer::~UdsServer() {
    close();
}

void UdsServer::open() {
    // Stale socket from a prior crash — unlink defensively. ENOENT is OK.
    if (::unlink(socket_path_.c_str()) < 0 && errno != ENOENT) {
        // Surface the error but continue; bind() will fail with a clearer
        // message if the path is truly unusable.
        std::fprintf(stderr,
            "uds_server::open: unlink('%s') warning: %s\n",
            socket_path_.c_str(), strerror_safe(errno).c_str());
    }

    listen_fd_ = ::socket(AF_UNIX, SOCK_STREAM, 0);
    if (listen_fd_ < 0) {
        throw std::runtime_error(
            std::string("uds_server::open: socket: ") +
            strerror_safe(errno));
    }

    sockaddr_un addr{};
    addr.sun_family = AF_UNIX;
    if (socket_path_.size() >= sizeof(addr.sun_path)) {
        ::close(listen_fd_);
        listen_fd_ = -1;
        throw std::runtime_error(
            "uds_server::open: socket path too long: " + socket_path_);
    }
    std::memcpy(addr.sun_path, socket_path_.data(), socket_path_.size());

    if (::bind(listen_fd_, reinterpret_cast<sockaddr*>(&addr),
               sizeof(addr)) < 0) {
        const int e = errno;
        ::close(listen_fd_);
        listen_fd_ = -1;
        throw std::runtime_error(
            std::string("uds_server::open: bind('") + socket_path_ +
            "'): " + strerror_safe(e));
    }
    path_bound_ = true;

    // M3: 0660 (owner + group rw). Group ownership inherits from the
    // process; same-uid caveat is documented in doc/uds_protocol.md.
    if (::chmod(socket_path_.c_str(), 0660) < 0) {
        std::fprintf(stderr,
            "uds_server::open: chmod 0660 warning: %s\n",
            strerror_safe(errno).c_str());
    }

    if (::listen(listen_fd_, godo::constants::UDS_LISTEN_BACKLOG) < 0) {
        const int e = errno;
        close();
        throw std::runtime_error(
            std::string("uds_server::open: listen: ") + strerror_safe(e));
    }
}

void UdsServer::run() {
    if (listen_fd_ < 0) {
        std::fprintf(stderr,
            "uds_server::run: open() not called or failed; exiting.\n");
        return;
    }

    while (godo::rt::g_running.load(std::memory_order_acquire)) {
        pollfd pfd{listen_fd_, POLLIN, 0};
        const int rc = ::poll(&pfd, 1,
                              godo::constants::SHUTDOWN_POLL_TIMEOUT_MS);
        if (rc < 0) {
            if (errno == EINTR) continue;       // benign
            std::fprintf(stderr,
                "uds_server::run: poll: %s — exiting.\n",
                strerror_safe(errno).c_str());
            return;
        }
        if (rc == 0) continue;                  // timeout, re-check g_running
        if (!(pfd.revents & POLLIN)) continue;  // spurious wakeup

        int conn = ::accept(listen_fd_, nullptr, nullptr);
        if (conn < 0) {
            if (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK) {
                continue;
            }
            std::fprintf(stderr,
                "uds_server::run: accept: %s — continuing.\n",
                strerror_safe(errno).c_str());
            continue;
        }
        handle_one_request(conn);
        ::close(conn);
    }
}

void UdsServer::handle_one_request(int conn_fd) noexcept {
    // Per-connection read timeout — protects accept loop if the client
    // never sends a newline.
    timeval tv{};
    tv.tv_sec  = godo::constants::UDS_CONN_READ_TIMEOUT_SEC;
    tv.tv_usec = 0;
    if (::setsockopt(conn_fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv)) < 0) {
        std::fprintf(stderr,
            "uds_server::handle: setsockopt SO_RCVTIMEO warning: %s\n",
            strerror_safe(errno).c_str());
    }

    // Read until '\n' or buffer cap. UDS_REQUEST_MAX_BYTES bounds both
    // memory and the worst-case scan in parse_request.
    char buf[godo::constants::UDS_REQUEST_MAX_BYTES];
    std::size_t total = 0;
    bool got_newline = false;
    while (total < sizeof(buf)) {
        ssize_t n = ::recv(conn_fd, buf + total, sizeof(buf) - total, 0);
        if (n < 0) {
            if (errno == EINTR) continue;
            // Read timeout or other error — drop without response.
            std::fprintf(stderr,
                "uds_server::handle: recv: %s — closing connection.\n",
                strerror_safe(errno).c_str());
            return;
        }
        if (n == 0) break;          // EOF before newline
        total += static_cast<std::size_t>(n);
        // Look for '\n' in the freshly read range.
        for (std::size_t i = total - static_cast<std::size_t>(n);
             i < total; ++i) {
            if (buf[i] == '\n') {
                got_newline = true;
                total = i;          // strip newline + everything after
                break;
            }
        }
        if (got_newline) break;
    }

    if (!got_newline && total >= sizeof(buf)) {
        // Oversized request without newline — close without response.
        // The client (Phase 4-3 webctl) is expected to send well-formed
        // single-line JSON; oversized means malformed or hostile.
        std::fprintf(stderr,
            "uds_server::handle: request exceeded %d bytes without "
            "newline; closing.\n",
            godo::constants::UDS_REQUEST_MAX_BYTES);
        return;
    }
    if (!got_newline) {
        // EOF before newline. Treat as parse error so the client sees a
        // consistent error response if they were expecting one.
        const auto resp = format_err("parse_error");
        (void)::send(conn_fd, resp.data(), resp.size(), MSG_NOSIGNAL);
        return;
    }

    const Request req = parse_request(std::string_view(buf, total));
    if (req.cmd.empty()) {
        const auto resp = format_err("parse_error");
        (void)::send(conn_fd, resp.data(), resp.size(), MSG_NOSIGNAL);
        return;
    }

    if (req.cmd == "ping") {
        const auto resp = format_ok();
        (void)::send(conn_fd, resp.data(), resp.size(), MSG_NOSIGNAL);
        return;
    }
    if (req.cmd == "get_mode") {
        const auto mode = get_mode_ ? get_mode_() : godo::rt::AmclMode::Idle;
        const auto resp = format_ok_mode(mode);
        (void)::send(conn_fd, resp.data(), resp.size(), MSG_NOSIGNAL);
        return;
    }
    if (req.cmd == "set_mode") {
        godo::rt::AmclMode m;
        if (!parse_mode_arg(req.mode_arg, m)) {
            const auto resp = format_err("bad_mode");
            (void)::send(conn_fd, resp.data(), resp.size(), MSG_NOSIGNAL);
            return;
        }
        if (set_mode_) set_mode_(m);
        const auto resp = format_ok();
        (void)::send(conn_fd, resp.data(), resp.size(), MSG_NOSIGNAL);
        return;
    }
    if (req.cmd == "get_last_pose") {
        // Track B — see doc/uds_protocol.md §C.4. Null callback is
        // surfaced to the client as valid=0 (no pose ever published)
        // rather than an error so the harness can distinguish
        // "tracker reachable but no AMCL fix yet" from "tracker down".
        godo::rt::LastPose pose{};
        pose.iterations = -1;
        if (get_last_pose_) pose = get_last_pose_();
        const auto resp = format_ok_pose(pose);
        (void)::send(conn_fd, resp.data(), resp.size(), MSG_NOSIGNAL);
        return;
    }
    if (req.cmd == "get_last_scan") {
        // Track D — see doc/uds_protocol.md §C.5. Same null-callback
        // semantics as get_last_pose: valid=0 distinguishes "no scan
        // yet" from "tracker down".
        godo::rt::LastScan scan{};
        scan.iterations = -1;
        if (get_last_scan_) scan = get_last_scan_();
        const auto resp = format_ok_scan(scan);
        (void)::send(conn_fd, resp.data(), resp.size(), MSG_NOSIGNAL);
        return;
    }
    if (req.cmd == "get_jitter") {
        // PR-DIAG — see doc/uds_protocol.md §C.6. Same null-callback
        // semantics: valid=0 means the publisher hasn't ticked yet.
        godo::rt::JitterSnapshot snap{};
        if (get_jitter_) snap = get_jitter_();
        const auto resp = format_ok_jitter(snap);
        (void)::send(conn_fd, resp.data(), resp.size(), MSG_NOSIGNAL);
        return;
    }
    if (req.cmd == "get_amcl_rate") {
        // PR-DIAG — see doc/uds_protocol.md §C.7. Mode-A M2 fold
        // renamed scan_rate → amcl_iteration_rate; the wire command
        // matches the canonical name.
        godo::rt::AmclIterationRate rate{};
        if (get_amcl_rate_) rate = get_amcl_rate_();
        const auto resp = format_ok_amcl_rate(rate);
        (void)::send(conn_fd, resp.data(), resp.size(), MSG_NOSIGNAL);
        return;
    }
    if (req.cmd == "get_config") {
        // Track B-CONFIG (PR-CONFIG-α) — operator pull of the live
        // effective config. Null callback → config_unsupported.
        if (!get_config_) {
            const auto resp = format_err("config_unsupported");
            (void)::send(conn_fd, resp.data(), resp.size(), MSG_NOSIGNAL);
            return;
        }
        const std::string body = get_config_();
        const auto resp = format_ok_get_config(body);
        (void)::send(conn_fd, resp.data(), resp.size(), MSG_NOSIGNAL);
        return;
    }
    if (req.cmd == "get_config_schema") {
        if (!get_config_schema_) {
            const auto resp = format_err("config_unsupported");
            (void)::send(conn_fd, resp.data(), resp.size(), MSG_NOSIGNAL);
            return;
        }
        const std::string body = get_config_schema_();
        const auto resp = format_ok_get_config_schema(body);
        (void)::send(conn_fd, resp.data(), resp.size(), MSG_NOSIGNAL);
        return;
    }
    if (req.cmd == "set_config") {
        if (!set_config_) {
            const auto resp = format_err("config_unsupported");
            (void)::send(conn_fd, resp.data(), resp.size(), MSG_NOSIGNAL);
            return;
        }
        if (req.key_arg.empty()) {
            const auto resp = format_err_with_detail(
                "bad_payload", "missing 'key' field");
            (void)::send(conn_fd, resp.data(), resp.size(), MSG_NOSIGNAL);
            return;
        }
        const ConfigSetReply rep = set_config_(req.key_arg, req.value_arg);
        if (rep.ok) {
            const auto resp = format_ok_set_config(rep.reload_class);
            (void)::send(conn_fd, resp.data(), resp.size(), MSG_NOSIGNAL);
            return;
        }
        const auto resp = format_err_with_detail(rep.err, rep.err_detail);
        (void)::send(conn_fd, resp.data(), resp.size(), MSG_NOSIGNAL);
        return;
    }

    const auto resp = format_err("unknown_cmd");
    (void)::send(conn_fd, resp.data(), resp.size(), MSG_NOSIGNAL);
}

void UdsServer::close() noexcept {
    if (listen_fd_ >= 0) {
        ::close(listen_fd_);
        listen_fd_ = -1;
    }
    if (path_bound_) {
        if (::unlink(socket_path_.c_str()) < 0 && errno != ENOENT) {
            std::fprintf(stderr,
                "uds_server::close: unlink('%s') warning: %s\n",
                socket_path_.c_str(), strerror_safe(errno).c_str());
        }
        path_bound_ = false;
    }
}

}  // namespace godo::uds
