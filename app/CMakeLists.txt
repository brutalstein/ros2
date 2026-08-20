cmake_minimum_required(VERSION 3.16)
project(drone)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

find_package(ament_cmake_auto REQUIRED)
ament_auto_find_build_dependencies()

# Every .cpp directly inside app/ is treated as one ROS 2 node.
file(GLOB NODE_SOURCES CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/*.cpp")

foreach(source IN LISTS NODE_SOURCES)
  get_filename_component(node "${source}" NAME_WE)
  ament_auto_add_executable("${node}" "${source}")
  target_include_directories("${node}" PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
  target_compile_options("${node}" PRIVATE -Wall -Wextra -Wpedantic)
endforeach()

ament_auto_package()
