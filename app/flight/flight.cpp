#include <chrono>
#include <memory>

#include "flight/flight.hpp"
#include "constants/topics.hpp"

#include "px4_msgs/msg/offboard_control_mode.hpp"


using namespace std::chrono_literals;


class FlightNode final : public rclcpp::Node
{
public:
    FlightNode()
        : rclcpp::Node("flight")
    {
        offboard_control_mode_pub_ =
            create_publisher<px4_msgs::msg::OffboardControlMode>(
                topics::PX4_OFFBOARD_CONTROL_MODE,
                10);

        heartbeat_timer_ =
            create_wall_timer(
                100ms,
                [this]()
                {
                    publish_offboard_heartbeat();
                });

        RCLCPP_INFO(
            get_logger(),
            "flight started | safe heartbeat only");
    }


private:
    rclcpp::Publisher<
        px4_msgs::msg::OffboardControlMode>::SharedPtr
        offboard_control_mode_pub_;

    rclcpp::TimerBase::SharedPtr heartbeat_timer_;


    void publish_offboard_heartbeat()
    {
        px4_msgs::msg::OffboardControlMode msg{};

        msg.timestamp =
            static_cast<uint64_t>(
                get_clock()->now().nanoseconds() / 1000);

        msg.position = true;
        msg.velocity = false;
        msg.acceleration = false;
        msg.attitude = false;
        msg.body_rate = false;
        msg.thrust_and_torque = false;
        msg.direct_actuator = false;

        offboard_control_mode_pub_->publish(msg);
    }
};


std::shared_ptr<rclcpp::Node> make_flight_node()
{
    return std::make_shared<FlightNode>();
}