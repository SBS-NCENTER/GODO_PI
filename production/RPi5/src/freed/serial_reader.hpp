#pragma once

// FreeD serial reader — Thread A.
//
// Opens the PL011 UART0 device read-only at 38400 8O1, reads bytes,
// frames D1 packets (re-sync via 1-byte memmove shift on mismatch so the
// behaviour is byte-identical to the legacy Arduino firmware at
// XR_FreeD_to_UDP/src/main.cpp L876-937), and writes each good packet to
// the provided Seqlock<FreedPacket>.
//
// Exits when godo::rt::g_running becomes false (polled via VTIME = 0.1 s).

#include <string>

#include "core/rt_types.hpp"
#include "core/seqlock.hpp"

namespace godo::freed {

class SerialReader {
public:
    SerialReader(std::string port, int baud) noexcept;
    ~SerialReader() noexcept;

    SerialReader(const SerialReader&)            = delete;
    SerialReader& operator=(const SerialReader&) = delete;

    // Blocks in a read loop until g_running is false. Throws std::system_error
    // on open/termios/ioctl failure; read errors are logged-and-retried.
    void run(godo::rt::Seqlock<godo::rt::FreedPacket>& out);

private:
    std::string port_;
    int         baud_;
    int         fd_{-1};

    void open_port();
    void close_port() noexcept;
};

}  // namespace godo::freed
