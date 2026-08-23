#pragma once

#include "rclcpp/rclcpp.hpp"

#include "flight/state/flight_state.hpp"

#include "px4_msgs/msg/vehicle_command.hpp"
#include "px4_msgs/msg/vehicle_command_ack.hpp"
#include "px4_msgs/msg/vehicle_local_position.hpp"
#include "px4_msgs/msg/vehicle_status.hpp"

class FlightSubscription
{
public:
    FlightSubscription(
        rclcpp::Node &node,
        FlightState &state);

private:
    rclcpp::Node &node_;
    FlightState &state_;

    rclcpp::Subscription<
        px4_msgs::msg::VehicleLocalPosition>::SharedPtr
        local_position_sub_;

    rclcpp::Subscription<
        px4_msgs::msg::VehicleStatus>::SharedPtr
        vehicle_status_sub_;

    rclcpp::Subscription<
        px4_msgs::msg::VehicleCommandAck>::SharedPtr
        command_ack_sub_;

    void local_position_callback(
        const px4_msgs::msg::VehicleLocalPosition::SharedPtr msg);

    void vehicle_status_callback(
        const px4_msgs::msg::VehicleStatus::SharedPtr msg);

    void command_ack_callback(
        const px4_msgs::msg::VehicleCommandAck::SharedPtr msg);
};
