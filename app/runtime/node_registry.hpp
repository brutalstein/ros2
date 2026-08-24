#pragma once

#include <memory>
#include <vector>

#include "camera/camera.hpp"
#include "flight/flight.hpp"
#include "rclcpp/rclcpp.hpp"

namespace drone_runtime
{
std::vector<std::shared_ptr<rclcpp::Node>> make_nodes()
{
    return {
        make_camera_node(),
        make_flight_node()
    };
}
}
