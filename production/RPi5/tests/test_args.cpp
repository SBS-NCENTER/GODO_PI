// Unit tests for args.{hpp,cpp}.

#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <string>
#include <variant>
#include <vector>

#include "args.hpp"

using godo::smoke::Args;
using godo::smoke::parse;
using godo::smoke::ParseError;
using godo::smoke::ParseHelp;
using godo::smoke::ParseResult;

TEST_CASE("no args returns defaults") {
    auto r = parse({});
    REQUIRE(std::holds_alternative<Args>(r));
    const Args a = std::get<Args>(r);
    CHECK(a.port == "/dev/ttyUSB0");
    CHECK(a.baud == 460'800);
    CHECK(a.frames == 10);
    CHECK(a.tag == "smoke");
    CHECK(a.notes == "");
    CHECK(a.out_dir == "out");
    CHECK(a.dry_run == false);
}

TEST_CASE("--help returns the help body") {
    auto r = parse({"--help"});
    REQUIRE(std::holds_alternative<ParseHelp>(r));
    const auto h = std::get<ParseHelp>(r);
    CHECK(h.text.find("godo_smoke") != std::string::npos);
    CHECK(h.text.find("--port") != std::string::npos);
}

TEST_CASE("valid named args override defaults") {
    auto r = parse({"--port", "/dev/ttyS0", "--baud", "115200",
                    "--frames", "42", "--tag", "bench1",
                    "--notes", "hello", "--out-dir", "/tmp/x"});
    REQUIRE(std::holds_alternative<Args>(r));
    const Args a = std::get<Args>(r);
    CHECK(a.port == "/dev/ttyS0");
    CHECK(a.baud == 115200);
    CHECK(a.frames == 42);
    CHECK(a.tag == "bench1");
    CHECK(a.notes == "hello");
    CHECK(a.out_dir == "/tmp/x");
}

TEST_CASE("--dry-run flag sets dry_run true") {
    auto r = parse({"--dry-run"});
    REQUIRE(std::holds_alternative<Args>(r));
    CHECK(std::get<Args>(r).dry_run == true);
}

TEST_CASE("unknown argument is a parse error") {
    auto r = parse({"--does-not-exist"});
    REQUIRE(std::holds_alternative<ParseError>(r));
    CHECK(std::get<ParseError>(r).message.find("unknown") != std::string::npos);
}

TEST_CASE("value-requiring flags error without a value") {
    for (const auto* flag : {"--port", "--baud", "--frames", "--tag",
                              "--notes", "--out-dir"}) {
        auto r = parse({flag});
        REQUIRE_MESSAGE(std::holds_alternative<ParseError>(r), flag);
    }
}

TEST_CASE("--frames rejects zero and negative") {
    CHECK(std::holds_alternative<ParseError>(parse({"--frames", "0"})));
    CHECK(std::holds_alternative<ParseError>(parse({"--frames", "-5"})));
}

TEST_CASE("--frames rejects non-integer") {
    CHECK(std::holds_alternative<ParseError>(parse({"--frames", "x"})));
    CHECK(std::holds_alternative<ParseError>(parse({"--frames", "1.5"})));
    CHECK(std::holds_alternative<ParseError>(parse({"--frames", ""})));
}

TEST_CASE("--baud rejects zero and negative") {
    CHECK(std::holds_alternative<ParseError>(parse({"--baud", "0"})));
    CHECK(std::holds_alternative<ParseError>(parse({"--baud", "-1"})));
}

TEST_CASE("--tag rejects empty string") {
    CHECK(std::holds_alternative<ParseError>(parse({"--tag", ""})));
}
