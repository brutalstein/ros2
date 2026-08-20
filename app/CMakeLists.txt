cmake_minimum_required(VERSION 3.16)
project(drone)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

find_package(ament_cmake_auto REQUIRED)
ament_auto_find_build_dependencies()

# Every .cpp directly under src/ becomes a ROS 2 executable automatically.
file(GLOB NODE_SOURCES CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/src/*.cpp")

foreach(source IN LISTS NODE_SOURCES)
  get_filename_component(node "${source}" NAME_WE)
  ament_auto_add_executable("${node}" "${source}")
  target_include_directories("${node}" PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/include")
  target_compile_options("${node}" PRIVATE -Wall -Wextra -Wpedantic)
endforeach()

if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/include")
  install(DIRECTORY include/ DESTINATION include)
endif()

ament_auto_package()
