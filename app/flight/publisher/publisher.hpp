#pragma once

#include <cstdint>

#include "rclcpp/rclcpp.hpp"

#include "px4_msgs/msg/offboard_control_mode.hpp"
#include "px4_msgs/msg/trajectory_setpoint.hpp"
#include "px4_msgs/msg/vehicle_command.hpp"


class FlightPublisher
{
public:
    explicit FlightPublisher(rclcpp::Node &node);

    void publish_offboard_heartbeat(
        uint64_t timestamp);

    void publish_hold_position(
        uint64_t timestamp,
        float x,
        float y,
        float z,
        float yaw);

    void publish_vehicle_command(
        uint64_t timestamp,
        uint16_t command,
        float param1 = 0.0f,
        float param2 = 0.0f);


private:
    rclcpp::Publisher<
        px4_msgs::msg::OffboardControlMode>::SharedPtr
        offboard_control_mode_pub_;

    rclcpp::Publisher<
        px4_msgs::msg::TrajectorySetpoint>::SharedPtr
        trajectory_setpoint_pub_;

    rclcpp::Publisher<
        px4_msgs::msg::VehicleCommand>::SharedPtr
        vehicle_command_pub_;
};