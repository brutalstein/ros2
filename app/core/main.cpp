#include <memory>

#include "rclcpp/rclcpp.hpp"

class MainNode final : public rclcpp::Node
{
public:
    MainNode()
        : rclcpp::Node("main")
    {
        RCLCPP_INFO(get_logger(), "main started");
    }
};

int main(int argc, char * argv[])
{
    rclcpp::init(argc, argv);
    rclcpp::spin(std::make_shared<MainNode>());
    rclcpp::shutdown();
    return 0;
}
