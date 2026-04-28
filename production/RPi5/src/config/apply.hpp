#pragma once

// Track B-CONFIG (PR-CONFIG-α) — the central `set_config` orchestrator.
// Sequence inside `apply_set`:
//   1. validate(key, value_text) — pure schema check.
//   2. take live_cfg_mtx.
//   3. clone live_cfg → staging; apply value to staging.
//   4. serialize staging to canonical TOML body.
//   5. atomic_toml_writer::write_atomic(toml_path, body).
//   6. on success: live_cfg = staging.
//   7. if reload_class == Hot: hot_seq.store(snapshot_hot(live_cfg)).
//   8. if reload_class != Hot: restart_pending::touch_pending_flag().
//   9. release lock; return ApplyResult.
//
// `apply_get_all` and `apply_get_schema` are pure read paths; they take
// the same mutex briefly to take a Config snapshot, then format JSON
// without holding the lock.
//
// All three functions are noexcept-equivalent in spirit (failures are
// signaled through ApplyResult; std::string allocations may throw, but
// the build never disables exceptions and OOM is treated as fatal
// elsewhere in this codebase).

#include <filesystem>
#include <mutex>
#include <string>
#include <string_view>

#include "core/config.hpp"
#include "core/config_schema.hpp"
#include "core/hot_config.hpp"
#include "core/seqlock.hpp"

namespace godo::config {

struct ApplyResult {
    bool                                   ok = false;
    godo::core::config_schema::ReloadClass reload_class =
        godo::core::config_schema::ReloadClass::Hot;
    std::string                            err;
    std::string                            err_detail;
};

ApplyResult apply_set(std::string_view                              key,
                      std::string_view                              value_text,
                      godo::core::Config&                           live_cfg,
                      std::mutex&                                   live_cfg_mtx,
                      godo::rt::Seqlock<godo::core::HotConfig>&     hot_seq,
                      const std::filesystem::path&                  toml_path,
                      const std::filesystem::path&                  restart_pending_flag);

// Returns a JSON object: {"key1": value1, ...} sorted alphabetically by
// key. Numeric values are JSON-typed (int / double); strings are
// quoted. 37 keys.
std::string apply_get_all(godo::core::Config& live_cfg,
                          std::mutex&         live_cfg_mtx);

// Returns a JSON array of {"name", "type", "min", "max", "default",
// "reload_class", "description"} rows. 37 entries. Stable across
// process lifetime (the schema is constexpr).
std::string apply_get_schema();

// Render the TOML body for a Config. Emitted in canonical alphabetical-
// by-key order, grouped by section. Used internally by apply_set; also
// exposed for the e2e test to assert the round-trip shape.
std::string render_toml(const godo::core::Config& cfg);

}  // namespace godo::config
