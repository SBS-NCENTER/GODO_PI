#pragma once

// Issue#27 — final-output transform stage.
//
// Sole-owner module that applies operator-tunable per-channel offset +
// sign to the FreeD packet AFTER `apply_offset_inplace` (AMCL merge)
// and BEFORE `udp.send`. Six channels are transformed:
//
//   X       — 1/64 mm  per LSB; signed24 BE at offset OFF_X
//   Y       — 1/64 mm  per LSB; signed24 BE at offset OFF_Y
//   Z       — 1/64 mm  per LSB; signed24 BE at offset OFF_Z
//   Pan     — 1/32768° per LSB; signed24 BE at offset OFF_PAN
//   Tilt    — 1/32768° per LSB; signed24 BE at offset OFF_TILT  (per FreeD D1 spec)
//   Roll    — 1/32768° per LSB; signed24 BE at offset OFF_ROLL  (see ROLL note below)
//
// Zoom (OFF_ZOOM, unsigned24 + 0x080000 offset) and Focus (OFF_FOCUS,
// same shape) are pass-through — they keep their original wire bytes
// regardless of any transform field. Operator-locked Q3.
//
// Math (operator-locked Q1, "offset first, sign second"):
//
//   final = sign * (raw + offset)            in scaled-double space
//
// Both `offset_*` (real units: m for positions, ° for angles) and
// `sign_*` (-1 or +1) are operator-set via the schema's
// `output_transform.*` rows; the Restart class means values flip on
// godo-tracker restart, never mid-run. The HotConfig SeqLock payload is
// NOT widened — these fields are captured by const ref in `thread_d_rt`
// from the boot-time Config and held for the lifetime of the binary.
//
// ROLL byte position note (per Mode-A C1 / Parent decision fold,
// 2026-05-03 21:45 KST): the FreeD D1 spec lists bytes 9-11 as
// "Reserved Data, always 0x000000". The SHOTOKU TK-53LVR / Ti-04VR
// family in production emits a non-zero constant (~-0.017°) at this
// byte position; the bypass forwarder passes the bytes through
// unchanged; PIXOTOPE-side decoders treat the bytes as a Roll channel.
// Therefore `OFF_ROLL` is retained as a meaningful label and the
// per-LSB scale is **assumed equal to Pan/Tilt's 1/32768°** by
// byte-position convention. A future operator who finds PIXOTOPE
// decodes Roll differently can correct via `output_transform.roll_*`
// without source change.
//
// Checksum: `apply_output_transform_inplace` re-computes bytes[28] over
// bytes[0..27] via `freed::compute_checksum` after rewriting any
// transformed channel — same contract as `apply_offset_inplace`.
//
// Decoder: `decode_last_output_from_packet` projects the post-transform
// FreedPacket back into 8 channels of real units (m / ° for the 6
// transformed; raw u24 cast to double for Zoom/Focus) so the SPA's
// LastPoseCard can render the actual value being sent to UE without
// re-implementing the wire decode in TS.

#include "core/rt_types.hpp"

namespace godo::udp {

struct OutputTransform {
    double x_offset_m{0.0};
    double y_offset_m{0.0};
    double z_offset_m{0.0};
    double pan_offset_deg{0.0};
    double tilt_offset_deg{0.0};
    double roll_offset_deg{0.0};
    int    x_sign{1};
    int    y_sign{1};
    int    z_sign{1};
    int    pan_sign{1};
    int    tilt_sign{1};
    int    roll_sign{1};
};

// Apply the 6-channel transform in place. Zoom + Focus bytes untouched.
// Recomputes the checksum at OFF_CHECKSUM. noexcept — no allocations.
void apply_output_transform_inplace(godo::rt::FreedPacket& p,
                                    const OutputTransform& t) noexcept;

// Decode the post-transform packet into a `LastOutputFrame` snapshot
// suitable for SeqLock publish. `published_mono_ns` + `valid` are NOT
// touched by this helper; the caller (Thread D) sets them.
//
// The 6 transformed channels are decoded back to real units (m for
// X/Y/Z, ° for Pan/Tilt/Roll). Zoom / Focus are projected as the raw
// unsigned24 value cast to double — operator-readable raw counts; the
// FreeD D1 spec's 0x080000 offset is not subtracted because the wire
// passes the bytes through unchanged and the SPA can apply its own
// interpretation.
godo::rt::LastOutputFrame decode_last_output_from_packet(
    const godo::rt::FreedPacket& p) noexcept;

}  // namespace godo::udp
