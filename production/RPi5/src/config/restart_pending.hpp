#pragma once

// Restart-pending flag manager. Track B-CONFIG (PR-CONFIG-α) — touched
// by the UDS handler when a `restart` or `recalibrate`-class config
// change lands; cleared by godo_tracker_rt::main() on every clean boot
// AFTER `Config::load()` succeeds (TM10 / TM11 in plan).
//
// Webctl mirrors this manager in PR-CONFIG-β (best-effort defence-in-
// depth on the response path); the tracker is authoritative.

#include <filesystem>

namespace godo::config {

// Idempotent. Creates the parent directory if missing; opens with
// O_CREAT | O_WRONLY | O_TRUNC; fsync; close. Errors are logged to
// stderr but never throw.
void touch_pending_flag(const std::filesystem::path& flag_path) noexcept;

// Idempotent. ENOENT is silent; other errno values log to stderr.
void clear_pending_flag(const std::filesystem::path& flag_path) noexcept;

// True if the flag file exists.
bool is_pending(const std::filesystem::path& flag_path) noexcept;

}  // namespace godo::config
