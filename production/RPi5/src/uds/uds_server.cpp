#include "uds_server.hpp"

#include <cerrno>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <stdexcept>
#include <string>
#include <utility>

#include <fcntl.h>
#include <glob.h>
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

// issue#3 — hint validation bounds (Mode-A M-A schema bounds + Pydantic
// mirror in webctl). Tier-2 σ defaults live on Config (cold writer
// applies them when σ override is 0.0); these bounds are a defensive
// re-check at the wire seam so a misbehaving / non-webctl client cannot
// publish out-of-range values. The hard bounds match webctl's Pydantic
// constraints byte-exactly.
constexpr double HINT_X_Y_ABS_MAX_M    = 100.0;
constexpr double HINT_YAW_DEG_MIN      = 0.0;
constexpr double HINT_YAW_DEG_LT       = 360.0;
constexpr double HINT_SIGMA_XY_MIN_M   = 0.05;
constexpr double HINT_SIGMA_XY_MAX_M   = 5.0;
constexpr double HINT_SIGMA_YAW_MIN_DEG = 1.0;
constexpr double HINT_SIGMA_YAW_MAX_DEG = 90.0;

// Returns true if every supplied hint field is finite and in-range. The
// caller has already checked `has_seed_*` are all-true (seed triple is
// all-or-none, enforced by webctl Pydantic + checked here at the wire
// seam by `bad_seed_partial`).
bool hint_within_bounds(const Request& req) noexcept {
    if (req.has_seed_x_m) {
        if (!std::isfinite(req.seed_x_m)) return false;
        if (req.seed_x_m < -HINT_X_Y_ABS_MAX_M ||
            req.seed_x_m >  HINT_X_Y_ABS_MAX_M) return false;
    }
    if (req.has_seed_y_m) {
        if (!std::isfinite(req.seed_y_m)) return false;
        if (req.seed_y_m < -HINT_X_Y_ABS_MAX_M ||
            req.seed_y_m >  HINT_X_Y_ABS_MAX_M) return false;
    }
    if (req.has_seed_yaw_deg) {
        if (!std::isfinite(req.seed_yaw_deg)) return false;
        if (req.seed_yaw_deg <  HINT_YAW_DEG_MIN ||
            req.seed_yaw_deg >= HINT_YAW_DEG_LT) return false;
    }
    if (req.has_sigma_xy_m) {
        if (!std::isfinite(req.sigma_xy_m)) return false;
        if (req.sigma_xy_m < HINT_SIGMA_XY_MIN_M ||
            req.sigma_xy_m > HINT_SIGMA_XY_MAX_M) return false;
    }
    if (req.has_sigma_yaw_deg) {
        if (!std::isfinite(req.sigma_yaw_deg)) return false;
        if (req.sigma_yaw_deg < HINT_SIGMA_YAW_MIN_DEG ||
            req.sigma_yaw_deg > HINT_SIGMA_YAW_MAX_DEG) return false;
    }
    return true;
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
    // Atomic-rename bind: bind to a temp path, then rename(2) over the
    // target. `rename(2)` is atomic on the same filesystem, so a
    // concurrent client connecting to the target either sees the OLD
    // socket OR the NEW socket — never a torn intermediate state. This
    // eliminates the unlink-then-bind TOCTOU window where another
    // process could race the bind() between our unlink() and bind().
    //
    // Single-instance discipline (CODEBASE invariant (l)) gates this
    // path on the tracker pidfile lock — only one godo_tracker_rt is
    // EVER running, so the only TOCTOU at risk would be a manual
    // ``socat`` binding to /run/godo/ctl.sock during boot. Atomic
    // rename closes that gap regardless.

    listen_fd_ = ::socket(AF_UNIX, SOCK_STREAM, 0);
    if (listen_fd_ < 0) {
        throw std::runtime_error(
            std::string("uds_server::open: socket: ") +
            strerror_safe(errno));
    }

    sockaddr_un addr{};
    addr.sun_family = AF_UNIX;
    // Build the temp path: <socket_path_>.<pid>.tmp. Worst case adds
    // ~16 chars to the basename; we still need to fit inside sun_path.
    std::string tmp_path = socket_path_ + "." +
        std::to_string(static_cast<int>(::getpid())) + ".tmp";
    if (tmp_path.size() >= sizeof(addr.sun_path)) {
        ::close(listen_fd_);
        listen_fd_ = -1;
        throw std::runtime_error(
            "uds_server::open: socket path too long: " + tmp_path);
    }
    if (socket_path_.size() >= sizeof(addr.sun_path)) {
        ::close(listen_fd_);
        listen_fd_ = -1;
        throw std::runtime_error(
            "uds_server::open: socket path too long: " + socket_path_);
    }
    // Sweep any stale temp left over from a prior crashed boot.
    if (::unlink(tmp_path.c_str()) < 0 && errno != ENOENT) {
        std::fprintf(stderr,
            "uds_server::open: unlink('%s') stale-temp warning: %s\n",
            tmp_path.c_str(), strerror_safe(errno).c_str());
    }
    std::memcpy(addr.sun_path, tmp_path.data(), tmp_path.size());

    if (::bind(listen_fd_, reinterpret_cast<sockaddr*>(&addr),
               sizeof(addr)) < 0) {
        const int e = errno;
        ::close(listen_fd_);
        listen_fd_ = -1;
        throw std::runtime_error(
            std::string("uds_server::open: bind('") + tmp_path +
            "'): " + strerror_safe(e));
    }
    // issue#10.1 quick-fix: stale-non-socket guard. We have observed
    // /run/godo/ctl.sock occasionally lingering as a 0-byte regular file
    // (provenance unconfirmed — could be webctl ENOENT-on-connect, a
    // half-failed prior rename, or systemd-tmpfiles). POSIX rename(2)
    // atomically overwrites regardless of the target's file type, so
    // strictly speaking this guard is belt-and-braces. But:
    //   1. If rename DOES fail mid-flight (e.g., ENOSPC, EACCES, an
    //      out-of-band caller holding the path open), we want the next
    //      tracker boot to clear the stale state explicitly rather
    //      than inherit it.
    //   2. The lstat → unlink-if-non-socket sequence makes the boot
    //      log self-documenting: when stale state is found, stderr
    //      records it. Future broader UDS audit (separate issue tracked
    //      in NEXT_SESSION.md) may revisit; this is the minimal fix
    //      that surfaces the failure mode.
    //
    // Live-socket targets (S_IFSOCK) are left alone — rename overwrites
    // them atomically without affecting open connections to the inode.
    struct stat target_stat{};
    if (::lstat(socket_path_.c_str(), &target_stat) == 0 &&
        !S_ISSOCK(target_stat.st_mode)) {
        std::fprintf(stderr,
            "uds_server::open: stale non-socket at '%s' "
            "(mode=0%o, size=%lld); unlinking before atomic rename\n",
            socket_path_.c_str(),
            static_cast<unsigned>(target_stat.st_mode),
            static_cast<long long>(target_stat.st_size));
        if (::unlink(socket_path_.c_str()) < 0 && errno != ENOENT) {
            std::fprintf(stderr,
                "uds_server::open: stale unlink('%s') warning: %s\n",
                socket_path_.c_str(), strerror_safe(errno).c_str());
        }
    }

    // Rename atomically over the target. POSIX rename(2): if the
    // destination exists, it is replaced atomically; if a concurrent
    // process holds the destination open, its existing connection is
    // unaffected (rename rebinds the path, not the inode).
    if (::rename(tmp_path.c_str(), socket_path_.c_str()) < 0) {
        const int e = errno;
        // issue#18 MF2 — emit forensic lstat output for both endpoints
        // BEFORE the throw so journalctl records the on-disk state at
        // the moment of failure. `log_lstat_for_throw` is noexcept and
        // best-effort; the existing throw text below is unchanged so any
        // log greppers keying on "rename(" keep working.
        log_lstat_for_throw(tmp_path, "tmp_path");
        log_lstat_for_throw(socket_path_, "target");
        ::unlink(tmp_path.c_str());
        ::close(listen_fd_);
        listen_fd_ = -1;
        throw std::runtime_error(
            std::string("uds_server::open: rename('") + tmp_path +
            "' -> '" + socket_path_ + "'): " + strerror_safe(e));
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

        // issue#3 — pose hint validation + publish (production CODEBASE
        // invariant (p)). The seed triple is all-or-none; sigma overrides
        // are independent. Order discipline (Mode-A M3):
        //   1. validate
        //   2. seqlock store of bundle
        //   3. atomic flag store(true, release)
        //   4. set_mode_(OneShot) — wraps g_amcl_mode.store(release)
        // so the cold writer's acquire-load of g_amcl_mode happens-after
        // both the seqlock store and the flag set.
        const int n_seed = (req.has_seed_x_m ? 1 : 0) +
                           (req.has_seed_y_m ? 1 : 0) +
                           (req.has_seed_yaw_deg ? 1 : 0);
        if (n_seed != 0 && n_seed != 3) {
            // Defence-in-depth — webctl Pydantic already enforces this.
            const auto resp = format_err("bad_seed_partial");
            (void)::send(conn_fd, resp.data(), resp.size(), MSG_NOSIGNAL);
            return;
        }
        const bool has_sigma_overrides =
            req.has_sigma_xy_m || req.has_sigma_yaw_deg;
        if (n_seed == 0 && has_sigma_overrides) {
            const auto resp = format_err("bad_sigma_without_seed");
            (void)::send(conn_fd, resp.data(), resp.size(), MSG_NOSIGNAL);
            return;
        }
        if (n_seed == 3 && m != godo::rt::AmclMode::OneShot) {
            // Live-mode hint is out of scope (operator-locked plan §Scope).
            const auto resp = format_err("bad_seed_with_non_oneshot");
            (void)::send(conn_fd, resp.data(), resp.size(), MSG_NOSIGNAL);
            return;
        }
        if (!hint_within_bounds(req)) {
            const auto resp = format_err("bad_seed_value");
            (void)::send(conn_fd, resp.data(), resp.size(), MSG_NOSIGNAL);
            return;
        }
        if (n_seed == 3) {
            godo::rt::HintBundle b{};
            b.x_m            = req.seed_x_m;
            b.y_m            = req.seed_y_m;
            b.yaw_deg        = req.seed_yaw_deg;
            b.sigma_xy_m     = req.has_sigma_xy_m    ? req.sigma_xy_m    : 0.0;
            b.sigma_yaw_deg  = req.has_sigma_yaw_deg ? req.sigma_yaw_deg : 0.0;
            // Step 2: seqlock store (sole writer is this UDS handler).
            godo::rt::g_calibrate_hint_data.store(b);
            // Step 3: lift the validity flag with release ordering so a
            // subsequent acquire-load on the cold writer sees the
            // bundle's payload bytes.
            godo::rt::g_calibrate_hint_valid.store(
                true, std::memory_order_release);
        }

        // Step 4: set_mode_ wraps g_amcl_mode.store(OneShot, release).
        // The hint store happens-before the mode store as observed by
        // the cold writer's acquire-load on g_amcl_mode (M3 pin).
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

// ----------------------------------------------------------------------
// issue#18 — UDS bootstrap audit free helpers.
// ----------------------------------------------------------------------

namespace {

// Format `<TYPE_size_or_ENOENT>` discriminator for both the MF2 forensic
// log and the MF3 boot-audit line. Mi4 explicitly covers S_IFDIR.
std::string format_lstat_discriminator(const char* path) noexcept {
    struct stat st{};
    if (::lstat(path, &st) < 0) {
        if (errno == ENOENT) {
            return "ENOENT";
        }
        char buf[64];
        std::snprintf(buf, sizeof(buf), "lstat_errno=%d", errno);
        return std::string(buf);
    }
    char buf[64];
    const char* type = nullptr;
    switch (st.st_mode & S_IFMT) {
        case S_IFSOCK: type = "S_IFSOCK"; break;
        case S_IFREG:  type = "S_IFREG";  break;
        case S_IFDIR:  type = "S_IFDIR";  break;
        case S_IFLNK:  type = "S_IFLNK";  break;
        case S_IFBLK:  type = "S_IFBLK";  break;
        case S_IFCHR:  type = "S_IFCHR";  break;
        case S_IFIFO:  type = "S_IFIFO";  break;
        default:       type = "S_IFOTHER"; break;
    }
    std::snprintf(buf, sizeof(buf), "%s_size=%lld",
                  type, static_cast<long long>(st.st_size));
    return std::string(buf);
}

// RAII guard for glob_t (Mi2 — every return path MUST call globfree()).
struct GlobGuard {
    glob_t* g;
    explicit GlobGuard(glob_t* gp) noexcept : g(gp) {}
    ~GlobGuard() { if (g) ::globfree(g); }
    GlobGuard(const GlobGuard&) = delete;
    GlobGuard& operator=(const GlobGuard&) = delete;
};

}  // namespace

void log_lstat_for_throw(const std::string& path, const char* label) noexcept {
    const std::string disc = format_lstat_discriminator(path.c_str());
    std::fprintf(stderr,
        "uds_server::open: rename failure forensics — %s='%s' lstat=%s\n",
        label ? label : "?", path.c_str(), disc.c_str());
}

void audit_runtime_dir(const std::string& socket_path) noexcept {
    // Build the sibling glob pattern: `<socket_path>.*.tmp`. We want to
    // surface inherited `.tmp` siblings without recursively scanning the
    // whole runtime dir.
    const std::string glob_pattern = socket_path + ".*.tmp";
    const std::string ctl_disc = format_lstat_discriminator(socket_path.c_str());

    glob_t gl{};
    GlobGuard guard(&gl);
    const int rc = ::glob(glob_pattern.c_str(), GLOB_NOSORT, nullptr, &gl);

    std::size_t count = 0;
    if (rc == 0) {
        count = gl.gl_pathc;
    } else if (rc == GLOB_NOMATCH) {
        count = 0;
    } else {
        // GLOB_ABORTED / GLOB_NOSPACE — log but continue with count=0.
        std::fprintf(stderr,
            "godo_tracker_rt: uds bootstrap audit: glob('%s') rc=%d "
            "(treating as no siblings)\n",
            glob_pattern.c_str(), rc);
        count = 0;
    }

    // Build the truncated sibling list. Only basenames in the list keep
    // the line readable; the full glob pattern is constant and known.
    std::string list_body;
    const std::size_t cap =
        static_cast<std::size_t>(godo::constants::UDS_BOOT_AUDIT_SIBLING_LIST_CAP);
    const std::size_t shown = (count < cap) ? count : cap;
    for (std::size_t i = 0; i < shown; ++i) {
        const char* full = gl.gl_pathv[i];
        const char* slash = std::strrchr(full, '/');
        const char* base = slash ? slash + 1 : full;
        if (i > 0) list_body += ", ";
        list_body += base;
    }
    if (count > shown) {
        list_body += ", ...";
    }

    std::fprintf(stderr,
        "godo_tracker_rt: uds bootstrap audit: ctl.sock=%s siblings=%zu [%s]\n",
        ctl_disc.c_str(), count, list_body.c_str());
}

void sweep_stale_siblings(const std::string& socket_path) noexcept {
    const std::string glob_pattern = socket_path + ".*.tmp";

    glob_t gl{};
    GlobGuard guard(&gl);
    const int rc = ::glob(glob_pattern.c_str(), GLOB_NOSORT, nullptr, &gl);
    if (rc == GLOB_NOMATCH) {
        return;
    }
    if (rc != 0) {
        std::fprintf(stderr,
            "godo_tracker_rt: uds sibling sweep: glob('%s') rc=%d "
            "(skipping sweep)\n",
            glob_pattern.c_str(), rc);
        return;
    }

    timespec now_ts{};
    if (::clock_gettime(CLOCK_REALTIME, &now_ts) < 0) {
        std::fprintf(stderr,
            "godo_tracker_rt: uds sibling sweep: clock_gettime: %s "
            "(skipping sweep)\n",
            strerror_safe(errno).c_str());
        return;
    }
    const time_t threshold =
        now_ts.tv_sec - godo::constants::UDS_STALE_SIBLING_MIN_AGE_SEC;

    for (std::size_t i = 0; i < gl.gl_pathc; ++i) {
        const char* full = gl.gl_pathv[i];
        struct stat st{};
        if (::lstat(full, &st) < 0) {
            std::fprintf(stderr,
                "godo_tracker_rt: uds sibling sweep: lstat('%s'): %s "
                "(skipping)\n",
                full, strerror_safe(errno).c_str());
            continue;
        }
        const bool is_regular = S_ISREG(st.st_mode);
        const bool is_socket  = S_ISSOCK(st.st_mode);
        if (!is_regular && !is_socket) {
            // Leave directories, symlinks, etc. alone — operator-driven
            // out-of-band state we should not silently delete.
            std::fprintf(stderr,
                "godo_tracker_rt: uds sibling sweep: leaving '%s' alone "
                "(mode=0%o, not regular or socket)\n",
                full, static_cast<unsigned>(st.st_mode));
            continue;
        }
        // Regular files are always cleaned up (typical half-failed rename
        // leftover). Sockets are cleaned up only when older than the
        // threshold — defence in depth against a future code path that
        // creates a `.tmp` socket concurrently with the sweep.
        if (is_socket && st.st_mtime > threshold) {
            std::fprintf(stderr,
                "godo_tracker_rt: uds sibling sweep: keeping fresh socket "
                "'%s' (mtime=%lld, threshold=%lld)\n",
                full, static_cast<long long>(st.st_mtime),
                static_cast<long long>(threshold));
            continue;
        }
        if (::unlink(full) < 0) {
            std::fprintf(stderr,
                "godo_tracker_rt: uds sibling sweep: unlink('%s'): %s\n",
                full, strerror_safe(errno).c_str());
            continue;
        }
        std::fprintf(stderr,
            "godo_tracker_rt: uds sibling sweep: unlinked stale '%s' "
            "(mode=0%o, size=%lld)\n",
            full, static_cast<unsigned>(st.st_mode),
            static_cast<long long>(st.st_size));
    }
}

}  // namespace godo::uds
