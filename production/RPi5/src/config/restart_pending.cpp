#include "restart_pending.hpp"

#include <cerrno>
#include <cstdio>
#include <cstring>
#include <system_error>

#include <fcntl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

namespace godo::config {

void touch_pending_flag(const std::filesystem::path& flag_path) noexcept {
    // Best-effort parent creation. errors_code overload swallows throws.
    std::error_code ec;
    if (!flag_path.parent_path().empty()) {
        std::filesystem::create_directories(flag_path.parent_path(), ec);
        if (ec) {
            std::fprintf(stderr,
                "restart_pending::touch: create_directories('%s') warning: %s\n",
                flag_path.parent_path().c_str(), ec.message().c_str());
            // Continue; open() will surface a clearer error if the dir
            // is genuinely unusable.
        }
    }

    const int fd = ::open(flag_path.c_str(),
                          O_CREAT | O_WRONLY | O_TRUNC, 0644);
    if (fd < 0) {
        std::fprintf(stderr,
            "restart_pending::touch: open('%s') failed: %s\n",
            flag_path.c_str(), std::strerror(errno));
        return;
    }
    if (::fsync(fd) != 0) {
        std::fprintf(stderr,
            "restart_pending::touch: fsync('%s') warning: %s\n",
            flag_path.c_str(), std::strerror(errno));
    }
    if (::close(fd) != 0) {
        std::fprintf(stderr,
            "restart_pending::touch: close('%s') warning: %s\n",
            flag_path.c_str(), std::strerror(errno));
    }
}

void clear_pending_flag(const std::filesystem::path& flag_path) noexcept {
    if (::unlink(flag_path.c_str()) != 0) {
        if (errno == ENOENT) return;  // idempotent.
        std::fprintf(stderr,
            "restart_pending::clear: unlink('%s') warning: %s\n",
            flag_path.c_str(), std::strerror(errno));
    }
}

bool is_pending(const std::filesystem::path& flag_path) noexcept {
    return ::access(flag_path.c_str(), F_OK) == 0;
}

}  // namespace godo::config
