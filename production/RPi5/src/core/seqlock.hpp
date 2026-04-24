#pragma once

// Single-writer, N-reader seqlock.
// See SYSTEM_DESIGN.md §6.1.1 — Offset and FreedPacket are both wider than
// any lock-free std::atomic<T> on aarch64 without LSE2, so we cannot use
// std::atomic<T> for the hot/cold exchange.

#include <atomic>
#include <cstdint>
#include <type_traits>

namespace godo::rt {

template <typename T>
class Seqlock {
    static_assert(std::is_trivially_copyable_v<T>,
                  "Seqlock<T> requires trivially copyable T");

    alignas(64) std::atomic<std::uint64_t> seq_{0};
    T payload_{};

public:
    // Single writer only.
    void store(const T& v) noexcept {
        const auto s = seq_.load(std::memory_order_relaxed);
        seq_.store(s + 1, std::memory_order_release);
        payload_ = v;
        seq_.store(s + 2, std::memory_order_release);
    }

    // Any reader.
    T load() const noexcept {
        for (;;) {
            const auto s1 = seq_.load(std::memory_order_acquire);
            if (s1 & 1) continue;                     // writer in progress
            const T copy = payload_;
            const auto s2 = seq_.load(std::memory_order_acquire);
            if (s1 == s2) return copy;
        }
    }

    // Even sequence number — also the update-counter the smoother consumes.
    std::uint64_t generation() const noexcept {
        return seq_.load(std::memory_order_acquire) & ~std::uint64_t{1};
    }
};

}  // namespace godo::rt
