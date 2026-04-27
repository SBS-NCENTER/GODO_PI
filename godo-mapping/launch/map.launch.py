# godo-mapping launch file.
#
# Composes:
#   - rplidar_ros's `rplidar_composition` node, configured inline for C1
#     (publishes /scan, frame_id=laser, 460800 bps)
#   - slam_toolbox async_slam_toolbox_node (consumes /scan)
#
# Plan F1 — Option A: hand-carried mapping has no robot base. base_frame is
# 'laser' (set in config/slam_toolbox_async.yaml). NO static_transform_publisher
# is included anywhere in this launch graph; the single TF chain is odom -> laser.
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

from launch import LaunchDescription
from launch.actions import EmitEvent, RegisterEventHandler
from launch.events import matches_action
from launch_ros.actions import LifecycleNode, Node
from launch_ros.event_handlers import OnStateTransition
from launch_ros.events.lifecycle import ChangeState
from lifecycle_msgs.msg import Transition

from pathlib import Path


def generate_launch_description() -> LaunchDescription:
    # 2026-04-28: TF chain fix. slam_toolbox in async mode publishes the
    # `map -> odom` transform itself, but expects an `odom -> base_frame`
    # transform to already exist for the chain `map -> odom -> base_frame`
    # to be closed. Without odom source (we are hand-carried, no wheel
    # encoders), the chain breaks → slam_toolbox never publishes /map →
    # map_saver_cli times out with 'Failed to spin map subscription'.
    #
    # Plan F1 (Option A) sets base_frame=laser. Add a single identity
    # static publisher `odom -> laser` so the chain closes. This does
    # NOT introduce a base_link frame; the laser IS the base frame.
    static_odom_to_laser = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='odom_to_laser_identity',
        arguments=['0', '0', '0', '0', '0', '0', 'odom', 'laser'],
        output='screen',
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
        static_odom_to_laser,
        rplidar,
        slam,
        slam_configure,
        slam_activate,
    ])
