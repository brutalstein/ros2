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
        node_.create_subscription<
            px4_msgs::msg::VehicleLocalPosition>(
            topics::PX4_LOCAL_POSITION,
            qos,
            [this](
                px4_msgs::msg::VehicleLocalPosition::SharedPtr msg)
            {
                local_position_callback(msg);
            });
    vehicle_status_sub_ =
        node_.create_subscription<
            px4_msgs::msg::VehicleStatus>(
            topics::PX4_VEHICLE_STATUS,
            qos,
            [this](
                px4_msgs::msg::VehicleStatus::SharedPtr msg)
            {
                vehicle_status_callback(msg);
            });
    command_ack_sub_ =
        node_.create_subscription<
            px4_msgs::msg::VehicleCommandAck>(
            topics::PX4_VEHICLE_COMMAND_ACK,
            qos,
            [this](
                px4_msgs::msg::VehicleCommandAck::SharedPtr msg)
            {
                command_ack_callback(msg);
            });
}
void FlightSubscription::local_position_callback(
    const px4_msgs::msg::VehicleLocalPosition::SharedPtr msg)
{
    if (!msg->xy_valid || !msg->z_valid)
    {
        state_.position_valid = false;
        return;
    }

    state_.position_valid = true;

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
    state_.vehicle_status_received = true;
    state_.failsafe =
        msg->failsafe;
    state_.armed =
        msg->arming_state ==
        px4_msgs::msg::VehicleStatus::
            ARMING_STATE_ARMED;
    state_.offboard_confirmed =
        msg->nav_state ==
        px4_msgs::msg::VehicleStatus::
            NAVIGATION_STATE_OFFBOARD;
}
void FlightSubscription::command_ack_callback(
    const px4_msgs::msg::VehicleCommandAck::SharedPtr msg)
{
    if (msg->command ==
        px4_msgs::msg::VehicleCommand::
            VEHICLE_CMD_DO_SET_MODE)
    {
        if (msg->result ==
            px4_msgs::msg::VehicleCommandAck::
                VEHICLE_CMD_RESULT_ACCEPTED)
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

        return;
    }
    if (msg->command ==
        px4_msgs::msg::VehicleCommand::
            VEHICLE_CMD_COMPONENT_ARM_DISARM)
    {
        if (msg->result ==
            px4_msgs::msg::VehicleCommandAck::
                VEHICLE_CMD_RESULT_ACCEPTED)
        {
            RCLCPP_INFO(
                node_.get_logger(),
                "PX4 accepted ARM command");
        }
        else
        {
            RCLCPP_WARN(
                node_.get_logger(),
                "PX4 rejected ARM command | result: %u",
                static_cast<unsigned int>(msg->result));
        }
        return;
    }
}