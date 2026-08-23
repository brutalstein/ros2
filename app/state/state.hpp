#pragma once

#include <memory>

#include "rclcpp/rclcpp.hpp"

std::shared_ptr<rclcpp::Node> make_state_node();
