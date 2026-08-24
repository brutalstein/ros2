#include "flight/subscription/subscription.hpp"

#include "constants/topics.hpp"
#include "px4_msgs/msg/vehicle_command.hpp"

namespace
{
const char *command_result_name(uint8_t result)
{
    using Ack = px4_msgs::msg::VehicleCommandAck;

    switch (result)
    {
        case Ack::VEHICLE_CMD_RESULT_ACCEPTED:
            return "accepted";
        case Ack::VEHICLE_CMD_RESULT_TEMPORARILY_REJECTED:
            return "temporarily rejected";
        case Ack::VEHICLE_CMD_RESULT_DENIED:
            return "denied";
        case Ack::VEHICLE_CMD_RESULT_UNSUPPORTED:
            return "unsupported";
        case Ack::VEHICLE_CMD_RESULT_FAILED:
            return "failed";
        case Ack::VEHICLE_CMD_RESULT_IN_PROGRESS:
            return "in progress";
        case Ack::VEHICLE_CMD_RESULT_CANCELLED:
            return "cancelled";
        default:
            return "unknown";
    }
}
}

FlightSubscription::FlightSubscription(
    rclcpp::Node &node,
    FlightState &state)
    : node_(node),
      state_(state)
{
    auto qos = rclcpp::SensorDataQoS();

    local_position_sub_ =
        node_.create_subscription<px4_msgs::msg::VehicleLocalPosition>(
            topics::PX4_LOCAL_POSITION,
            qos,
            [this](px4_msgs::msg::VehicleLocalPosition::SharedPtr msg)
            {
                local_position_callback(msg);
            });

    vehicle_status_sub_ =
        node_.create_subscription<px4_msgs::msg::VehicleStatus>(
            topics::PX4_VEHICLE_STATUS,
            qos,
            [this](px4_msgs::msg::VehicleStatus::SharedPtr msg)
            {
                vehicle_status_callback(msg);
            });

    command_ack_sub_ =
        node_.create_subscription<px4_msgs::msg::VehicleCommandAck>(
            topics::PX4_VEHICLE_COMMAND_ACK,
            qos,
            [this](px4_msgs::msg::VehicleCommandAck::SharedPtr msg)
            {
                command_ack_callback(msg);
            });
}

void FlightSubscription::local_position_callback(
    const px4_msgs::msg::VehicleLocalPosition::SharedPtr msg)
{
    state_.position_valid = msg->xy_valid && msg->z_valid;

    if (!state_.position_valid)
    {
        return;
    }

    state_.current_x = msg->x;
    state_.current_y = msg->y;
    state_.current_z = msg->z;

    if (msg->heading_good_for_control)
    {
        state_.yaw = msg->heading;
    }
}

void FlightSubscription::vehicle_status_callback(
    const px4_msgs::msg::VehicleStatus::SharedPtr msg)
{
    state_.status_received = true;
    state_.preflight_ready = msg->pre_flight_checks_pass;
    state_.failsafe = msg->failsafe;

    state_.armed =
        msg->arming_state ==
        px4_msgs::msg::VehicleStatus::ARMING_STATE_ARMED;

    state_.offboard =
        msg->nav_state ==
        px4_msgs::msg::VehicleStatus::NAVIGATION_STATE_OFFBOARD;
}

void FlightSubscription::command_ack_callback(
    const px4_msgs::msg::VehicleCommandAck::SharedPtr msg)
{
    const bool accepted =
        msg->result ==
        px4_msgs::msg::VehicleCommandAck::VEHICLE_CMD_RESULT_ACCEPTED;

    if (msg->command ==
        px4_msgs::msg::VehicleCommand::VEHICLE_CMD_DO_SET_MODE)
    {
        if (accepted)
        {
            RCLCPP_INFO(node_.get_logger(), "OFFBOARD request accepted");
        }
        else
        {
            RCLCPP_WARN(
                node_.get_logger(),
                "OFFBOARD request %s",
                command_result_name(msg->result));
        }
        return;
    }

    if (msg->command ==
        px4_msgs::msg::VehicleCommand::VEHICLE_CMD_COMPONENT_ARM_DISARM)
    {
        if (accepted)
        {
            RCLCPP_INFO(node_.get_logger(), "ARM request accepted");
        }
        else
        {
            RCLCPP_WARN(
                node_.get_logger(),
                "ARM request %s",
                command_result_name(msg->result));
        }
    }
}
