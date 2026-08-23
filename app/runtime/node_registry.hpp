#pragma once

#include <memory>
#include <vector>

#include "core/core.hpp"
#include "state/state.hpp"
#include "sensors/sensors.hpp"
#include "camera/camera.hpp"
#include "rclcpp/rclcpp.hpp"

namespace drone_runtime
{
    std::vector<std::shared_ptr<rclcpp::Node>> make_nodes(){
      std::vector<std::shared_ptr<rclcpp::Node>> nodes;

      nodes.push_back(make_core_node());
      nodes.push_back(make_state_node());
      nodes.push_back(make_sensors_node());
      nodes.push_back(make_camera_node());

      return nodes;
    }
}
