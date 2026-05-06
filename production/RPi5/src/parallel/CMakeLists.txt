# issue#11 P4-2-11-1 — ParallelEvalPool fork-join particle eval pool.
#
# Static library; cold-side only. The pool's mutex + condition_variable
# live in parallel_eval_pool.cpp via a pimpl; the public header
# parallel_eval_pool.hpp drags neither <mutex> nor <condition_variable>
# into translation units that include it (in particular cold_writer.cpp
# remains M1-clean — see scripts/build.sh [m1-no-mutex]).
#
# Depends on godo_core only (rt::monotonic_ns + project invariants); no
# AMCL or LiDAR coupling. Reused by issue#19 EDT 2D parallelization via
# a separate parallel_for_with_scratch<S> API (deferred — issue#11 ships
# only the index-only `parallel_for(begin, end, fn)` surface).

add_library(godo_parallel STATIC
    parallel_eval_pool.cpp
)

target_include_directories(godo_parallel PUBLIC
    "${CMAKE_CURRENT_SOURCE_DIR}/.."
)

target_link_libraries(godo_parallel PUBLIC
    godo_core
)

# pthreads for std::thread + pthread_setaffinity_np / pthread_attr_setstacksize.
find_package(Threads REQUIRED)
target_link_libraries(godo_parallel PUBLIC Threads::Threads)
