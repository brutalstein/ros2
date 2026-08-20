#include <memory>
#include <chrono>
#include "std_msgs/msg/string.hpp"
#include "rclcpp/rclcpp.hpp"
#include "constants/topics.hpp"
using namespace std::chrono_literals;

class CoreNode final : public rclcpp::Node
{
public:
    CoreNode()
        : rclcpp::Node("core")
    {
        status_pub_ = create_publisher<std_msgs::msg::String>(topics::STATUS, 10);
        timer_ = create_wall_timer(1s, [this](){
          publish_status();
        });
        RCLCPP_INFO(get_logger(), "core started");
    }
private:
    rclcpp::Publisher<std_msgs::msg::String>::SharedPtr status_pub_;
    rclcpp::TimerBase::SharedPtr timer_;

    void publish_status(){
      std_msgs::msg::String msg;
      msg.data = "active";
      status_pub_->publish(msg);
    }
};

int main(int argc, char * argv[])
{
    rclcpp::init(argc, argv);
    rclcpp::spin(std::make_shared<CoreNode>());
    rclcpp::shutdown();
    return 0;
}
