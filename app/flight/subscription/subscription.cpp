#include "flight/subscription/subscription.hpp"
#include "constants/topics.hpp"

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
    if (!msg->xy_valid || !msg->z_valid)
    {
        return;
    }

    if (state_.hold_position_ready)
    {
        return;
    }

    state_.hold_x = msg->x;
    state_.hold_y = msg->y;
    state_.hold_z = msg->z;

    if (msg->heading_good_for_control)
    {
        state_.hold_yaw = msg->heading;
    }

    state_.hold_position_ready = true;

    RCLCPP_INFO(
        node_.get_logger(),
        "hold position captured | x: %.2f y: %.2f z: %.2f",
        state_.hold_x,
        state_.hold_y,
        state_.hold_z);
}

void FlightSubscription::vehicle_status_callback(
    const px4_msgs::msg::VehicleStatus::SharedPtr msg)
{
    state_.vehicle_status_received = true;
    state_.failsafe = msg->failsafe;

    const bool is_offboard =
        msg->nav_state ==
        px4_msgs::msg::VehicleStatus::NAVIGATION_STATE_OFFBOARD;

    if (is_offboard && !state_.offboard_confirmed)
    {
        state_.offboard_confirmed = true;

        RCLCPP_INFO(
            node_.get_logger(),
            "OFFBOARD confirmed by PX4");
    }

    if (!is_offboard && state_.offboard_confirmed)
    {
        state_.offboard_confirmed = false;

        RCLCPP_WARN(
            node_.get_logger(),
            "PX4 left OFFBOARD mode");
    }
}

void FlightSubscription::command_ack_callback(
    const px4_msgs::msg::VehicleCommandAck::SharedPtr msg)
{
    if (msg->command !=
        px4_msgs::msg::VehicleCommand::VEHICLE_CMD_DO_SET_MODE)
    {
        return;
    }

    if (msg->result ==
        px4_msgs::msg::VehicleCommandAck::VEHICLE_CMD_RESULT_ACCEPTED)
    {
        RCLCPP_INFO(
            node_.get_logger(),
            "PX4 accepted OFFBOARD mode command");
    }
    else
    {
        RCLCPP_WARN(
            node_.get_logger(),
            "PX4 rejected OFFBOARD command | result: %u",
            static_cast<unsigned int>(msg->result));
    }
}
