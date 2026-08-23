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

void FlightPublisher::publish_offboard_heartbeat(
    uint64_t timestamp)
{
    px4_msgs::msg::OffboardControlMode msg{};

    msg.timestamp = timestamp;

    msg.position = true;
    msg.velocity = false;
    msg.acceleration = false;
    msg.attitude = false;
    msg.body_rate = false;
    msg.thrust_and_torque = false;
    msg.direct_actuator = false;

    offboard_control_mode_pub_->publish(msg);
}

void FlightPublisher::publish_hold_position(
    uint64_t timestamp,
    float x,
    float y,
    float z,
    float yaw)
{
    const float nan =
        std::numeric_limits<float>::quiet_NaN();

    px4_msgs::msg::TrajectorySetpoint msg{};

    msg.timestamp = timestamp;

    msg.position = {
        x,
        y,
        z
    };

    msg.velocity = {
        nan,
        nan,
        nan
    };

    msg.acceleration = {
        nan,
        nan,
        nan
    };

    msg.jerk = {
        nan,
        nan,
        nan
    };

    msg.yaw = yaw;
    msg.yawspeed = nan;

    trajectory_setpoint_pub_->publish(msg);
}

void FlightPublisher::publish_vehicle_command(
    uint64_t timestamp,
    uint16_t command,
    float param1,
    float param2)
{
    px4_msgs::msg::VehicleCommand msg{};

    msg.timestamp = timestamp;

    msg.param1 = param1;
    msg.param2 = param2;

    msg.command = command;

    msg.target_system = 1;
    msg.target_component = 1;

    msg.source_system = 1;
    msg.source_component = 1;

    msg.from_external = true;

    vehicle_command_pub_->publish(msg);
}
