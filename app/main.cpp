#include "rclcpp/rclcpp.hpp"
#include "rclcpp/executors/single_threaded_executor.hpp"
#include "runtime/node_registry.hpp"

int main(int argc, char *argv[]){
  rclcpp::init(argc, argv);
  rclcpp::executors::SingleThreadedExecutor executor;

  auto nodes = drone_runtime::make_nodes();

  for(const auto &node : nodes){
    executor.add_node(node);
  }
  executor.spin();
  rclcpp::shutdown();
  return 0;
}