#pragma once

// Minimal command-line argument parsing for godo_smoke.
//
// No dependency on an argparse library — the surface is tiny and the test
// surface must be fully deterministic. See `parse()` for the accepted shape.

#include <cstdint>
#include <optional>
#include <string>
#include <variant>
#include <vector>

namespace godo::smoke {

struct Args {
    std::string port       = "/dev/ttyUSB0";
    int         baud       = 460'800;
    int         frames     = 10;
    std::string tag        = "smoke";
    std::string notes      = "";
    std::string out_dir    = "out";
    // --dry-run: use the fake LiDAR source (hardware-free). Smoke target
    // defaults to real hardware; dry_run is exercised from tests via the
    // library path, not through the CLI.
    bool        dry_run    = false;
};

struct ParseHelp {
    std::string text;
};

struct ParseError {
    std::string message;
};

// Result variants: Args (success) | ParseHelp (--help printed) | ParseError.
using ParseResult = std::variant<Args, ParseHelp, ParseError>;

ParseResult parse(const std::vector<std::string>& argv);

// Human-readable --help body, without the program name prefix.
std::string help_text();

}  // namespace godo::smoke
