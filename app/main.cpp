#include <cstdlib>
#include <string>

#include "rclcpp/rclcpp.hpp"
#include "rclcpp/executors/single_threaded_executor.hpp"
#include "runtime/node_registry.hpp"

int main(int argc, char *argv[])
{
    rclcpp::init(argc, argv);

    std::string only_node;
    if (const char *requested = std::getenv("DRONE_ONLY_NODE"); requested != nullptr)
    {
        only_node = requested;
    }

    auto nodes = drone_runtime::make_nodes(only_node);
    if (!only_node.empty() && nodes.empty())
    {
        RCLCPP_ERROR(
            rclcpp::get_logger("drone_app"),
            "unknown registered node: %s",
            only_node.c_str());
        rclcpp::shutdown();
        return 2;
    }

    rclcpp::executors::SingleThreadedExecutor executor;
    for (const auto &node : nodes)
    {
        executor.add_node(node);
    }

    executor.spin();
    rclcpp::shutdown();
    return 0;
}
