# godo-mapping launch file.
#
# Composes:
#   - Upstream rplidar_c1_launch.py  (publishes /scan, frame_id=laser, 460800 bps)
#   - slam_toolbox async_slam_toolbox_node  (consumes /scan)
#
# Plan F1 — Option A: hand-carried mapping has no robot base. base_frame is
# 'laser' (set in config/slam_toolbox_async.yaml). NO static_transform_publisher
# is included anywhere in this launch graph; the single TF chain is odom -> laser.
#
# Magic-number policy (plan F3): numeric / string literals in this launch file
# are Tier-2 SLAM configuration, not §6 magic numbers — but each non-trivial
# literal carries an inline comment explaining its origin.

from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare

from pathlib import Path


def generate_launch_description() -> LaunchDescription:
    # Upstream C1 launch file ships with rplidar_ros (Jazzy). Defaults match
    # GODO's wiring: serial_port=/dev/ttyUSB0, serial_baudrate=460800,
    # scan_mode=Standard, frame_id=laser. Plan resolution Q1 — no GODO wrapper
    # needed; we include upstream verbatim.
    rplidar_launch_path = [
        FindPackageShare('rplidar_ros'),
        '/launch/rplidar_c1_launch.py',
    ]
    rplidar = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(rplidar_launch_path),
    )

    # slam_toolbox async node — params come from our YAML so the Tier-2
    # surface is one file (config/slam_toolbox_async.yaml).
    params_file = str(Path('/godo-mapping/config/slam_toolbox_async.yaml'))
    slam = Node(
        package='slam_toolbox',
        executable='async_slam_toolbox_node',
        name='slam_toolbox',
        output='screen',
        parameters=[params_file],
    )

    return LaunchDescription([rplidar, slam])
