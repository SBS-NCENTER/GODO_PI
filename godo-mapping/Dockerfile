# godo-mapping — SLAM toolchain container.
#
# Layer order (slow → fast change) per plan F10:
#   1. FROM ros:jazzy-ros-base
#   2. apt install slam-toolbox + rplidar-ros + nav2-map-server
#   3. WORKDIR
#   4. COPY launch/, config/  (change occasionally)
#   5. COPY entrypoint.sh     (changes most often)
#
# Rebuilds after a launch / entrypoint edit reuse the apt layer.
#
# Build:    docker build -t godo-mapping:dev .
# Run:      handled by scripts/run-mapping.sh (host-side wrapper).

FROM ros:jazzy-ros-base

LABEL org.opencontainers.image.title="godo-mapping" \
      org.opencontainers.image.description="SLAM toolchain for GODO LiDAR mapping (slam_toolbox + rplidar_ros + nav2_map_server)." \
      godo-mapping="dev"

RUN apt-get update && apt-get install -y --no-install-recommends \
        ros-jazzy-slam-toolbox \
        ros-jazzy-rplidar-ros \
        ros-jazzy-nav2-map-server \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /godo-mapping

COPY launch/  /godo-mapping/launch/
COPY config/  /godo-mapping/config/
COPY entrypoint.sh /godo-mapping/entrypoint.sh
RUN chmod +x /godo-mapping/entrypoint.sh

ENTRYPOINT ["/godo-mapping/entrypoint.sh"]
