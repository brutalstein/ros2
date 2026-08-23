#pragma once

#include <memory>
#include <vector>

#include "rclcpp/rclcpp.hpp"

namespace drone_runtime
{
    std::vector<std::shared_ptr<rclcpp::Node>> make_nodes();
}
