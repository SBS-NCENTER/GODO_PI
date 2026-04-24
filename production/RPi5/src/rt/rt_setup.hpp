#pragma once

// RT-lifecycle helpers. See SYSTEM_DESIGN.md §6.2.
// Each function returns false on a non-fatal failure after logging an
// actionable message to stderr. True on success.

namespace godo::rt::setup {

// Process-wide: lock all current and future pages. MUST be called in
// main() before any thread is spawned so every thread's stack is eligible
// for locking.
bool lock_all_memory() noexcept;

// Pin the CURRENT thread to a single CPU. `cpu` is a zero-based logical
// CPU index; use it only for the designated RT thread.
bool pin_current_thread_to_cpu(int cpu) noexcept;

// Promote the CURRENT thread to SCHED_FIFO at the given priority.
bool set_current_thread_fifo(int prio) noexcept;

// Block all signals in the current thread's mask. Intended to be called
// from main() before thread spawning so the signal-handling thread is the
// only one with any signals enabled (see SYSTEM_DESIGN.md §6.2).
bool block_all_signals_process() noexcept;

}  // namespace godo::rt::setup
