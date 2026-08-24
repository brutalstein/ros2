#pragma once

#include <memory>
#include <string_view>
#include <vector>

#include "camera/camera.hpp"
#include "flight/flight.hpp"
// DRONE_NODE_INCLUDES
#include "rclcpp/rclcpp.hpp"

namespace drone_runtime
{
  using NodeFactory = std::shared_ptr<rclcpp::Node> (*)();

  struct NodeSpec
  {
    const char *name;
    NodeFactory factory;
  };

  inline const std::vector<NodeSpec> &node_specs()
  {
    static const std::vector<NodeSpec> specs{
        {"camera", make_camera_node},
        {"flight", make_flight_node},
        // DRONE_NODE_ENTRIES
    };
    return specs;
  }

  inline std::vector<std::shared_ptr<rclcpp::Node>> make_nodes(
      std::string_view only = {})
  {
    std::vector<std::shared_ptr<rclcpp::Node>> nodes;

    for (const auto &spec : node_specs())
    {
      if (only.empty() || only == spec.name)
      {
        nodes.push_back(spec.factory());
      }
    }

    return nodes;
  }
}