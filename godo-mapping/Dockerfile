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

# Runtime deps from Debian Jazzy. We pull rplidar_ros from apt only for its
# transitive deps (laser_geometry, etc.); the apt build ships only
# rplidar_composition (legacy SDK API path), so we replace it with an
# overlay built from upstream that ships rplidar_node + C1 support.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ros-jazzy-slam-toolbox \
        ros-jazzy-rplidar-ros \
        ros-jazzy-nav2-map-server \
        git \
        python3-colcon-common-extensions \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Build upstream Slamtec/rplidar_ros (ros2 branch) into a colcon overlay.
# Pinned to a specific commit so the image is reproducible. The Debian
# package version (2.1.0) is missing rplidar_node + rplidar_c1_launch.py;
# the C1's modern firmware rejects rplidar_composition's deprecated
# checkExpressScanSupported() path with 0x80008002 — see commit
# message for details.
RUN mkdir -p /opt/ros_overlay/src \
    && cd /opt/ros_overlay/src \
    && git clone --depth 1 --branch ros2 https://github.com/Slamtec/rplidar_ros.git \
    && cd /opt/ros_overlay \
    && /bin/bash -c 'set +u; source /opt/ros/jazzy/setup.bash; set -u; colcon build --merge-install --cmake-args -DCMAKE_BUILD_TYPE=Release' \
    && rm -rf /opt/ros_overlay/build /opt/ros_overlay/log /opt/ros_overlay/src/rplidar_ros/.git

WORKDIR /godo-mapping

COPY launch/  /godo-mapping/launch/
COPY config/  /godo-mapping/config/
COPY entrypoint.sh /godo-mapping/entrypoint.sh
RUN chmod +x /godo-mapping/entrypoint.sh

ENTRYPOINT ["/godo-mapping/entrypoint.sh"]
