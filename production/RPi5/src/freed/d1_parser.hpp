#pragma once

// FreeD D1 packet parser — pure, no I/O.
// Wire format and checksum scheme lifted verbatim from
// XR_FreeD_to_UDP/src/main.cpp L17-31 (layout) and L185-191 (checksum).

#include <cstddef>
#include <cstdint>

#include "core/rt_types.hpp"

namespace godo::freed {

struct ParseResult {
    enum class Status {
        ok,
        short_buffer,
        bad_checksum,
        unknown_type,
        bad_header,
    };

    Status                   status;
    godo::rt::FreedPacket    packet;  // valid only when status == ok
};

// Parse one D1 packet from [bytes, bytes+len). Does not consume; caller
// manages the framing buffer. Bumps an internal atomic counter on
// unknown-type; never throws; non-blocking.
ParseResult parse_d1(const std::byte* bytes, std::size_t len) noexcept;

// Observed count of non-D1 type bytes seen by the parser. Monotonic.
std::uint64_t unknown_type_count() noexcept;

// FreeD checksum: (64 - sum_of_bytes_0..27) mod 256. `bytes` must point
// at the start of a FreeD packet; only the first 28 bytes are read.
std::uint8_t compute_checksum(const std::byte* bytes, std::size_t len) noexcept;

}  // namespace godo::freed
