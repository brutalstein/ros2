#include <limits>

#include "flight/publisher/publisher.hpp"
#include "constants/topics.hpp"


FlightPublisher::FlightPublisher(rclcpp::Node &node)
{
    offboard_control_mode_pub_ =
        node.create_publisher<
            px4_msgs::msg::OffboardControlMode>(
            topics::PX4_OFFBOARD_CONTROL_MODE,
            10);

    trajectory_setpoint_pub_ =
        node.create_publisher<
            px4_msgs::msg::TrajectorySetpoint>(
            topics::PX4_TRAJECTORY_SETPOINT,
            10);

    vehicle_command_pub_ =
        node.create_publisher<
            px4_msgs::msg::VehicleCommand>(
            topics::PX4_VEHICLE_COMMAND,
            10);
}