# godo-mapping launch file.
#
# Composes:
#   - rf2o_laser_odometry_node (consumes /scan, publishes odom -> laser TF)
#   - rplidar_ros's `rplidar_node`, configured inline for C1
#     (publishes /scan, frame_id=laser, 460800 bps)
#   - slam_toolbox async_slam_toolbox_node (consumes /scan + odom -> laser TF)
#
# Plan F1 — Option A: hand-carried mapping has no robot base. base_frame is
# 'laser' (set in config/slam_toolbox_async.yaml).
#
# Magic-number policy (plan F3): numeric / string literals in this launch file
# are Tier-2 SLAM configuration, not §6 magic numbers — but each non-trivial
# literal carries an inline comment explaining its origin.
#
# 2026-04-28 update — the Jazzy `ros-jazzy-rplidar-ros` Debian package does
# NOT ship `rplidar_c1_launch.py` (only A3 / S1 / generic). Instead of
# IncludeLaunchDescription on a non-existent file, we inline the Node call
# with explicit C1 parameters. Verified by inspecting
# `/opt/ros/jazzy/share/rplidar_ros/launch/` inside `godo-mapping:dev`.
#
# 2026-04-29 update — rf2o laser odometry replaces static identity TF.
# Root cause: the previous static identity tf2_ros publisher on the
# odom -> laser edge lied to slam_toolbox about motion. Karto's
# `minimum_travel_distance: 0.5` / `minimum_travel_heading: 0.5` gate
# (slam_toolbox upstream defaults) saw zero motion forever, so only the
# very first scan was integrated and the resulting PGM showed a single-
# fan artifact (~107 occupied pixels at maps/0429_2.pgm). rf2o consumes
# /scan, performs scan-to-scan registration, and publishes a true
# motion-derived `odom -> laser` TF. SSOT for rf2o parameters lives in
# config/rf2o.yaml. See CODEBASE.md invariant (h).

from launch import LaunchDescription
from launch.actions import EmitEvent, RegisterEventHandler
from launch.events import matches_action
from launch_ros.actions import LifecycleNode, Node
from launch_ros.event_handlers import OnStateTransition
from launch_ros.events.lifecycle import ChangeState
from lifecycle_msgs.msg import Transition

from pathlib import Path


def generate_launch_description() -> LaunchDescription:
    # rf2o laser odometry — consumes /scan and publishes odom -> laser TF
    # via scan-to-scan registration. Replaces the 2026-04-28 static
    # identity publisher whose frozen zero-motion broke slam_toolbox's
    # Karto minimum_travel_distance gate.
    #
    # CRITICAL: the Node `name=` MUST be byte-equal to the top-level
    # key in config/rf2o.yaml (`rf2o_laser_odometry:`).
    # Without this, ROS 2's parameter loader silently fails to bind the
    # YAML and rf2o boots with hardcoded defaults (base_frame_id=base_link,
    # init_pose_from_topic='/base_pose_ground_truth') — rf2o would then
    # wait forever for an init pose on a non-existent topic and never
    # produce odom→laser TF. Exact symmetric failure mode to the bug
    # we're fixing.
    #
    # use_sim_time pinned False explicitly (defense-in-depth, symmetric
    # to slam_toolbox below). Hardware run, never Gazebo.
    rf2o_params = str(Path('/godo-mapping/config/rf2o.yaml'))
    rf2o = Node(
        package='rf2o_laser_odometry',
        executable='rf2o_laser_odometry_node',
        name='rf2o_laser_odometry',
        output='screen',
        parameters=[
            rf2o_params,
            {'use_sim_time': False},
        ],
    )

    # rplidar driver, parameters explicit for the RPLIDAR C1.
    # serial_baudrate=460800 is per doc/RPLIDAR/RPLIDAR_C1.md §6 (C1's UART
    # rate; A1/A2 use 115200, A3 uses 256000 — the generic
    # rplidar.launch.py defaults to 115200 which would NOT enumerate the C1).
    # The Dockerfile builds upstream Slamtec/rplidar_ros (ros2 branch) into
    # a colcon overlay so the modern `rplidar_node` binary is available.
    # The Jazzy Debian package only ships `rplidar_composition` (legacy
    # SDK path), which fails on C1 with 0x80008002.
    rplidar = Node(
        package='rplidar_ros',
        executable='rplidar_node',
        name='rplidar_node',
        output='screen',
        parameters=[{
            'channel_type': 'serial',
            'serial_port': '/dev/ttyUSB0',
            'serial_baudrate': 460800,        # C1
            'frame_id': 'laser',              # Plan F1: base_frame == laser
            'inverted': False,
            'angle_compensate': True,
            'scan_mode': 'Standard',          # C1 primary mode (~5,000 SPS)
        }],
    )

    # slam_toolbox async — params come from our YAML so the Tier-2
    # surface is one file (config/slam_toolbox_async.yaml).
    #
    # 2026-04-28: slam_toolbox is a LIFECYCLE node. Just spawning it leaves
    # it in the unconfigured state — no /map publish, /scan subscription
    # idle. The official online_async_launch.py emits CONFIGURE then
    # ACTIVATE transitions; we mirror that pattern. use_sim_time is
    # explicitly false (hardware, not Gazebo).
    params_file = str(Path('/godo-mapping/config/slam_toolbox_async.yaml'))
    slam = LifecycleNode(
        package='slam_toolbox',
        executable='async_slam_toolbox_node',
        name='slam_toolbox',
        namespace='',
        output='screen',
        parameters=[
            params_file,
            {'use_sim_time': False},
        ],
    )
    slam_configure = EmitEvent(
        event=ChangeState(
            lifecycle_node_matcher=matches_action(slam),
            transition_id=Transition.TRANSITION_CONFIGURE,
        ),
    )
    slam_activate = RegisterEventHandler(
        OnStateTransition(
            target_lifecycle_node=slam,
            start_state='configuring',
            goal_state='inactive',
            entities=[
                EmitEvent(event=ChangeState(
                    lifecycle_node_matcher=matches_action(slam),
                    transition_id=Transition.TRANSITION_ACTIVATE,
                )),
            ],
        ),
    )

    return LaunchDescription([
        rf2o,
        rplidar,
        slam,
        slam_configure,
        slam_activate,
    ])
