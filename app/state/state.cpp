#include <memory>

#include "rclcpp/rclcpp.hpp"
#include "px4_msgs/msg/vehicle_local_position.hpp"
#include "constants/topics.hpp"

class StateNode final : public rclcpp::Node
{
public:
    StateNode()
        : rclcpp::Node("state")
    {
        auto qos = rclcpp::QoS(rclcpp::KeepLast(1));
        qos.best_effort();
        qos.transient_local();

        position_sub_ = create_subscription<px4_msgs::msg::VehicleLocalPosition>(
          topics::PX4_LOCAL_POSITION,
          qos,
          [this](px4_msgs::msg::VehicleLocalPosition::SharedPtr msg){
            position_callback(msg);
          }
        );
        RCLCPP_INFO(get_logger(), "state started");
    }
private:
    rclcpp::Subscription<px4_msgs::msg::VehicleLocalPosition>::SharedPtr position_sub_;
    void position_callback(const px4_msgs::msg::VehicleLocalPosition::SharedPtr msg){
      if (!msg->xy_valid || !msg->z_valid)
        {
            return;
        }
        RCLCPP_INFO(
            get_logger(),

            "x: %.2f | y: %.2f | altitude: %.2f",

            msg->x,
            msg->y,
            -msg->z
        );
    }
};

int main(int argc, char * argv[])
{
    rclcpp::init(argc, argv);
    rclcpp::spin(std::make_shared<StateNode>());
    rclcpp::shutdown();
    return 0;
}
