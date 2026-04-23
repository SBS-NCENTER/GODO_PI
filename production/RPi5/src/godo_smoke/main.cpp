// godo_smoke — Phase 3 RPi 5 bring-up smoke binary.
//
// Connects to RPLIDAR C1, captures N frames, writes:
//     out/<ts>_<tag>/data/<ts>_<tag>.csv
//     out/<ts>_<tag>/logs/<ts>_<tag>.txt
// matching the prototype/Python layout byte-for-byte on the CSV.
//
// This is NOT the production tracker; see CODEBASE.md for the smoke-scope
// boundary and the invariants pinned by the tests.

#include <algorithm>
#include <clocale>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <string>
#include <variant>
#include <vector>

#include "args.hpp"
#include "csv_writer.hpp"
#include "lidar_source_rplidar.hpp"
#include "sample.hpp"
#include "session_log.hpp"
#include "timestamp.hpp"

using namespace godo::smoke;

namespace {

int run_capture(const Args& args) {
    const std::string ts = utc_timestamp_compact();
    const std::string slug = ts + "_" + args.tag;

    const std::filesystem::path run_dir =
        std::filesystem::path(args.out_dir) / slug;
    const std::filesystem::path csv_path = run_dir / "data" / (slug + ".csv");
    const std::filesystem::path log_path = run_dir / "logs" / (slug + ".txt");

    std::cout << "godo_smoke: capturing " << args.frames
              << " frame(s) from " << args.port
              << " @ " << args.baud << " bps\n";
    std::cout << "  csv : " << csv_path.string() << "\n";
    std::cout << "  log : " << log_path.string() << "\n";

    LidarSourceRplidar lidar(args.port, args.baud);
    lidar.open();

    CsvWriter writer(csv_path);
    writer.open();

    std::vector<std::uint8_t> qualities;
    const std::int64_t t0_ns = monotonic_ns();
    lidar.scan_frames(args.frames, [&](int /*idx*/, const Frame& frame) {
        writer.write_frame(frame);
        for (const auto& s : frame.samples) qualities.push_back(s.quality);
    });
    const double duration_s =
        static_cast<double>(monotonic_ns() - t0_ns) / 1e9;

    writer.close();
    lidar.close();

    RunStats stats;
    stats.frames_captured = writer.frames_written();
    stats.samples_total   = writer.samples_written();
    stats.duration_s      = duration_s;
    if (!qualities.empty()) {
        double sum = 0.0;
        for (auto q : qualities) sum += static_cast<double>(q);
        stats.mean_quality = sum / static_cast<double>(qualities.size());
        std::vector<std::uint8_t> sorted_q = qualities;
        std::sort(sorted_q.begin(), sorted_q.end());
        const std::size_t m = sorted_q.size() / 2;
        stats.median_quality = (sorted_q.size() % 2 == 1)
            ? static_cast<double>(sorted_q[m])
            : (static_cast<double>(sorted_q[m - 1]) +
               static_cast<double>(sorted_q[m])) / 2.0;
    }

    CaptureParams params;
    params.backend          = "rplidar-sdk";
    params.port             = args.port;
    params.baud             = args.baud;
    params.frames_requested = args.frames;
    params.tag              = args.tag;
    params.notes            = args.notes;

    write_session_log(log_path, params, stats, csv_path);

    std::cout << "captured " << stats.frames_captured << " frames / "
              << stats.samples_total << " samples in "
              << duration_s << " s\n";
    return 0;
}

}  // namespace

int main(int argc, char** argv) {
    // Pin numeric formatting to the C locale so CSV decimal separators are
    // always "." regardless of the operator's LANG. All worker threads
    // inherit this by design; see CODEBASE.md invariant (d).
    std::setlocale(LC_ALL, "C");

    std::vector<std::string> av;
    av.reserve(static_cast<std::size_t>(std::max(0, argc - 1)));
    for (int i = 1; i < argc; ++i) av.emplace_back(argv[i]);

    ParseResult pr = parse(av);
    if (std::holds_alternative<ParseHelp>(pr)) {
        std::cout << std::get<ParseHelp>(pr).text;
        return 0;
    }
    if (std::holds_alternative<ParseError>(pr)) {
        std::cerr << "godo_smoke: " << std::get<ParseError>(pr).message
                  << "\n\n"
                  << help_text();
        return 2;
    }
    const Args args = std::get<Args>(pr);

    if (args.dry_run) {
        std::cerr << "godo_smoke: --dry-run is exercised via the test "
                     "harness, not the CLI.\n";
        return 2;
    }

    try {
        return run_capture(args);
    } catch (const std::exception& e) {
        std::cerr << "godo_smoke: error: " << e.what() << "\n";
        return 1;
    }
}
