#include "serial_reader.hpp"

#include <cerrno>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <system_error>
#include <utility>

#include <fcntl.h>
#include <sys/ioctl.h>
#include <termios.h>
#include <time.h>
#include <unistd.h>

#include "core/constants.hpp"
#include "core/rt_flags.hpp"
#include "d1_parser.hpp"

namespace godo::freed {

namespace {

// Map our integer baud to termios speed_t. We only need 38400 on the hot
// path, but the indirection keeps the baud parameter meaningful if we
// later support 9600 / 115200 for bench work.
bool to_speed(int baud, speed_t& out) noexcept {
    switch (baud) {
        case 9600:   out = B9600;   return true;
        case 19200:  out = B19200;  return true;
        case 38400:  out = B38400;  return true;
        case 57600:  out = B57600;  return true;
        case 115200: out = B115200; return true;
    }
    return false;
}

}  // namespace

SerialReader::SerialReader(std::string port, int baud) noexcept
    : port_(std::move(port)), baud_(baud) {}

SerialReader::~SerialReader() noexcept {
    close_port();
}

void SerialReader::open_port() {
    fd_ = ::open(port_.c_str(), O_RDONLY | O_NOCTTY);
    if (fd_ < 0) {
        const int err = errno;
        if (err == EBUSY) {
            std::fprintf(stderr,
                "freed::SerialReader: open(%s) EBUSY — the kernel serial "
                "console may still own the UART. See SYSTEM_DESIGN.md §6.3 "
                "and production/RPi5/doc/freed_wiring.md §B "
                "(cmdline.txt: remove console=serial0,115200).\n",
                port_.c_str());
        }
        throw std::system_error(err, std::generic_category(),
                                "freed::SerialReader::open(" + port_ + ")");
    }

    if (::ioctl(fd_, TIOCEXCL) != 0) {
        std::fprintf(stderr,
            "freed::SerialReader: TIOCEXCL on %s failed (%s); continuing "
            "without exclusive access\n",
            port_.c_str(), std::strerror(errno));
    }

    termios tio{};
    if (::tcgetattr(fd_, &tio) != 0) {
        const int err = errno;
        ::close(fd_);
        fd_ = -1;
        throw std::system_error(err, std::generic_category(),
                                "freed::SerialReader: tcgetattr");
    }
    cfmakeraw(&tio);

    speed_t s;
    if (!to_speed(baud_, s)) {
        ::close(fd_);
        fd_ = -1;
        throw std::runtime_error(
            "freed::SerialReader: unsupported baud " + std::to_string(baud_));
    }
    cfsetispeed(&tio, s);
    cfsetospeed(&tio, s);

    // 8O1 — 8 data bits, odd parity, 1 stop bit, no hardware flow control.
    // Matches XR_FreeD_to_UDP/src/main.cpp L957 (SERIAL_8O1).
    tio.c_cflag |=  (PARENB | PARODD | CS8);
    tio.c_cflag &= ~CSTOPB;
    tio.c_cflag &= ~CRTSCTS;

    tio.c_cc[VMIN]  = 1;    // at least one byte per read
    tio.c_cc[VTIME] = 1;    // 0.1 s timeout so we can poll g_running

    const bool termios_ok = (::tcsetattr(fd_, TCSANOW, &tio) == 0);
    if (!termios_ok) {
        const int err = errno;
        // Pseudo-terminal slaves reject some real-hardware-only cflags
        // (PARENB/PARODD/CSTOPB) with EINVAL on Linux. The PTY is
        // transparent anyway — the master writes framed bytes verbatim —
        // so we log and continue rather than failing the test harness.
        std::fprintf(stderr,
            "freed::SerialReader: tcsetattr on %s failed (%s); continuing "
            "with default termios + O_NONBLOCK — acceptable only on PTY "
            "test harnesses\n",
            port_.c_str(), std::strerror(err));
        (void)err;

        // PTY-only fallback: force O_NONBLOCK and let the read loop nap
        // on EAGAIN so g_running is still observed promptly without the
        // VTIME=1 kernel-side timer we couldn't install.
        const int flags = ::fcntl(fd_, F_GETFL, 0);
        if (flags >= 0) {
            ::fcntl(fd_, F_SETFL, flags | O_NONBLOCK);
        }
    }
    // On real PL011 (termios_ok == true) the fd stays blocking:
    // read() wakes every ≤100 ms via VTIME=1, which is strictly cheaper
    // than a userspace nanosleep cadence and gives the kernel full
    // control over when to wake us.
}

void SerialReader::close_port() noexcept {
    if (fd_ >= 0) {
        ::close(fd_);
        fd_ = -1;
    }
}

void SerialReader::run(godo::rt::Seqlock<godo::rt::FreedPacket>& out) {
    open_port();

    // Pre-allocated framing buffer: up to 2 packet lengths so that on a
    // bad checksum we can memmove-shift by 1 byte and retry without
    // reallocating. Mirrors legacy L876-937 state machine semantics but
    // with a single-buffer re-sync rather than the two-state enum.
    constexpr int kPktLen = godo::constants::FREED_PACKET_LEN;
    std::byte buf[kPktLen];
    int       filled = 0;

    while (godo::rt::g_running.load(std::memory_order_acquire)) {
        if (filled < kPktLen) {
            const ssize_t n = ::read(
                fd_, buf + filled, static_cast<std::size_t>(kPktLen - filled));
            if (n > 0) {
                filled += static_cast<int>(n);
            } else if (n == 0) {
                // EOF on a tty is typically a transient; small sleep so
                // the CPU does not spin while the crane is disconnected.
                timespec ts{0, 10'000'000};   // 10 ms
                ::nanosleep(&ts, nullptr);
                continue;
            } else {
                if (errno == EINTR) continue;
                if (errno == EAGAIN || errno == EWOULDBLOCK) {
                    // Non-blocking: no data yet. Nap briefly so the read
                    // loop does not hot-spin on an idle serial line.
                    timespec ts{0, 10'000'000};   // 10 ms
                    ::nanosleep(&ts, nullptr);
                    continue;
                }
                std::fprintf(stderr,
                    "freed::SerialReader: read(%s) error: %s\n",
                    port_.c_str(), std::strerror(errno));
                timespec ts{0, 100'000'000};      // 100 ms
                ::nanosleep(&ts, nullptr);
                continue;
            }
        }

        if (filled < kPktLen) continue;

        const ParseResult r = parse_d1(buf, static_cast<std::size_t>(kPktLen));
        if (r.status == ParseResult::Status::ok) {
            out.store(r.packet);
            filled = 0;  // consume the full packet
        } else {
            // short_buffer can't happen (we just filled kPktLen bytes).
            // bad_header / bad_checksum / unknown_type — shift by 1 byte
            // and try again on the next read. memmove-based re-sync is
            // the exact pattern used by the legacy firmware (L922-927).
            std::memmove(buf, buf + 1, static_cast<std::size_t>(kPktLen - 1));
            filled = kPktLen - 1;
        }
    }

    close_port();
}

}  // namespace godo::freed
