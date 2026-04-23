#include "args.hpp"

#include <cstdlib>
#include <sstream>
#include <string_view>

namespace godo::smoke {

namespace {

bool parse_int(const std::string& s, int& out) {
    if (s.empty()) return false;
    char* end = nullptr;
    errno = 0;
    const long v = std::strtol(s.c_str(), &end, 10);
    if (errno != 0 || end == s.c_str() || *end != '\0') return false;
    if (v < INT32_MIN || v > INT32_MAX) return false;
    out = static_cast<int>(v);
    return true;
}

ParseError err(std::string msg) { return ParseError{std::move(msg)}; }

}  // namespace

std::string help_text() {
    std::ostringstream os;
    os << "godo_smoke — RPLIDAR C1 smoke capture (Phase 3 bring-up)\n"
          "\n"
          "Options:\n"
          "  --port PATH        serial port (default /dev/ttyUSB0)\n"
          "  --baud N           baudrate (default 460800)\n"
          "  --frames N         number of 360-degree frames (default 10)\n"
          "  --tag STR          filename slug (default 'smoke')\n"
          "  --notes STR        operator notes recorded in the session log\n"
          "  --out-dir PATH     output root (default 'out')\n"
          "  --dry-run          use an internal fake source instead of "
          "hardware\n"
          "  -h, --help         show this message and exit\n"
          "\n"
          "Artifacts:\n"
          "  <out-dir>/<ts>_<tag>/data/<ts>_<tag>.csv\n"
          "  <out-dir>/<ts>_<tag>/logs/<ts>_<tag>.txt\n";
    return os.str();
}

ParseResult parse(const std::vector<std::string>& argv) {
    Args args;
    for (std::size_t i = 0; i < argv.size(); ++i) {
        const std::string& a = argv[i];
        auto need_value = [&]() -> std::optional<std::string> {
            if (i + 1 >= argv.size()) {
                return std::nullopt;
            }
            return argv[++i];
        };
        if (a == "-h" || a == "--help") {
            return ParseHelp{help_text()};
        } else if (a == "--port") {
            auto v = need_value();
            if (!v) return err("--port requires a value");
            args.port = *v;
        } else if (a == "--baud") {
            auto v = need_value();
            if (!v) return err("--baud requires a value");
            if (!parse_int(*v, args.baud) || args.baud <= 0) {
                return err("--baud must be a positive integer");
            }
        } else if (a == "--frames") {
            auto v = need_value();
            if (!v) return err("--frames requires a value");
            if (!parse_int(*v, args.frames) || args.frames < 1) {
                return err("--frames must be >= 1");
            }
        } else if (a == "--tag") {
            auto v = need_value();
            if (!v) return err("--tag requires a value");
            if (v->empty()) return err("--tag must be non-empty");
            args.tag = *v;
        } else if (a == "--notes") {
            auto v = need_value();
            if (!v) return err("--notes requires a value");
            args.notes = *v;
        } else if (a == "--out-dir") {
            auto v = need_value();
            if (!v) return err("--out-dir requires a value");
            if (v->empty()) return err("--out-dir must be non-empty");
            args.out_dir = *v;
        } else if (a == "--dry-run") {
            args.dry_run = true;
        } else {
            return err("unknown argument: " + a);
        }
    }
    return args;
}

}  // namespace godo::smoke
