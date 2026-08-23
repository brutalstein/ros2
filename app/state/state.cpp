#include <memory>

#include "state/state.hpp"
#include "constants/topics.hpp"
#include "px4_msgs/msg/vehicle_local_position.hpp"
#include "px4_msgs/msg/vehicle_status.hpp"

class StateNode final : public rclcpp::Node
{
public:
    StateNode()
        : rclcpp::Node("state")
    {
        auto qos = rclcpp::SensorDataQoS();

        position_sub_ = create_subscription<px4_msgs::msg::VehicleLocalPosition>(
            topics::PX4_LOCAL_POSITION,
            qos,
            [this](px4_msgs::msg::VehicleLocalPosition::SharedPtr msg)
            {
                position_callback(msg);
            });

        status_sub_ = create_subscription<px4_msgs::msg::VehicleStatus>(
            topics::PX4_VEHICLE_STATUS,
            qos,
            [this](px4_msgs::msg::VehicleStatus::SharedPtr msg)
            {
                status_callback(msg);
            });

        RCLCPP_INFO(get_logger(), "state started");
    }

private:
    rclcpp::Subscription<px4_msgs::msg::VehicleLocalPosition>::SharedPtr position_sub_;
    rclcpp::Subscription<px4_msgs::msg::VehicleStatus>::SharedPtr status_sub_;

    void position_callback(const px4_msgs::msg::VehicleLocalPosition::SharedPtr msg)
    {
        if (!msg->xy_valid || !msg->z_valid)
        {
            return;
        }

        RCLCPP_INFO_THROTTLE(
            get_logger(),
            *get_clock(),
            1000,
            "POSITION | x: %.2f | y: %.2f | altitude: %.2f",
            msg->x,
            msg->y,
            -msg->z);
    }

    void status_callback(const px4_msgs::msg::VehicleStatus::SharedPtr msg)
    {
        const bool armed =
            msg->arming_state == px4_msgs::msg::VehicleStatus::ARMING_STATE_ARMED;

        RCLCPP_INFO_THROTTLE(
            get_logger(),
            *get_clock(),
            1000,
            "STATUS | armed: %s | mode: %u | failsafe: %s | preflight: %s",
            armed ? "YES" : "NO",
            static_cast<unsigned int>(msg->nav_state),
            msg->failsafe ? "YES" : "NO",
            msg->pre_flight_checks_pass ? "OK" : "NOT READY");
    }
};

std::shared_ptr<rclcpp::Node> make_state_node()
{
    return std::make_shared<StateNode>();
}
