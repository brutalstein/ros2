#include <memory>
#include <vector>

#include "rclcpp/rclcpp.hpp"

// DRONE_NODE_INCLUDES_BEGIN
#include "camera/camera.hpp"
#include "core/core.hpp"
#include "flight/flight.hpp"
#include "sensors/sensors.hpp"
#include "state/state.hpp"
// DRONE_NODE_INCLUDES_END

int main(int argc, char *argv[])
{
    rclcpp::init(argc, argv);

    rclcpp::executors::SingleThreadedExecutor executor;

    std::vector<std::shared_ptr<rclcpp::Node>> nodes;

    // DRONE_NODE_FACTORIES_BEGIN
    nodes.push_back(make_core_node());
    nodes.push_back(make_state_node());
    nodes.push_back(make_sensors_node());
    nodes.push_back(make_camera_node());
    nodes.push_back(make_flight_node());
    // DRONE_NODE_FACTORIES_END

    for (const auto &node : nodes)
    {
        executor.add_node(node);
    }

    RCLCPP_INFO(
        rclcpp::get_logger("main"),
        "drone application started | %zu modules active",
        nodes.size());

    executor.spin();

    for (const auto &node : nodes)
    {
        executor.remove_node(node);
    }

    rclcpp::shutdown();
    return 0;
}
