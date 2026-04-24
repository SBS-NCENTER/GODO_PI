#pragma once

// Real-time UDP sender for FreeD packets.
//
// Uses a connected SOCK_DGRAM so send(2) (not sendto) is available on the
// hot path — half the syscall cost and no per-send sockaddr construction.
// Non-blocking: EAGAIN/EWOULDBLOCK from an overfull kernel buffer is
// counted and periodically logged rather than blocking Thread D.

#include <cstdint>
#include <string>

#include "core/rt_types.hpp"

namespace godo::udp {

class UdpSender {
public:
    UdpSender(std::string host, int port);
    ~UdpSender() noexcept;

    UdpSender(const UdpSender&)            = delete;
    UdpSender& operator=(const UdpSender&) = delete;

    // Send the 29-byte FreeD packet. An all-zero packet is interpreted as
    // "no FreeD received yet" and is silently skipped (logged once).
    // Returns true on send success or deliberate skip, false on hard error.
    bool send(const godo::rt::FreedPacket& p) noexcept;

private:
    std::string host_;
    int         port_;
    int         fd_{-1};
    std::uint64_t eagain_miss_count_{0};
    bool          empty_frame_logged_{false};
};

// Apply the offset (dx, dy in metres; dyaw in degrees) to a FreeD D1 packet.
// Decodes the X/Y signed-24 fields and the pan signed-24 field, adds
// `off.dx * 64` / `off.dy * 64` / `off.dyaw * 32768` in the encoded
// domain, re-encodes via yaw::wrap_signed24 on each, recomputes checksum.
//
// Z/Tilt/Roll/Zoom/Focus/Status pass through untouched.
void apply_offset_inplace(godo::rt::FreedPacket& p,
                          const godo::rt::Offset& off) noexcept;

}  // namespace godo::udp
