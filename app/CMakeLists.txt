cmake_minimum_required(VERSION 3.16)
project(drone)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

find_package(ament_cmake_auto REQUIRED)
ament_auto_find_build_dependencies()

# Foundational C++ libraries used by camera/perception/planning code.
find_package(OpenCV 4 REQUIRED)
find_package(Eigen3 REQUIRED)

# Keep the project flat and modular: C++ can live anywhere under app/.
file(GLOB_RECURSE DRONE_CPP
  CONFIGURE_DEPENDS
  LIST_DIRECTORIES false
  "${CMAKE_CURRENT_SOURCE_DIR}/*.cpp"
  "${CMAKE_CURRENT_SOURCE_DIR}/*.cc"
  "${CMAKE_CURRENT_SOURCE_DIR}/*.cxx"
)

# We inspect source contents to separate ROS executables from shared implementation.
# Reconfigure when a source changes so adding/removing main() is detected.
if(DRONE_CPP)
  set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS ${DRONE_CPP})
endif()

set(DRONE_NODE_SOURCES)
set(DRONE_LIBRARY_SOURCES)

foreach(source IN LISTS DRONE_CPP)
  file(READ "${source}" source_text)
  string(REGEX MATCH "(^|[\r\n])[ \t]*int[ \t\r\n]+main[ \t\r\n]*\\(" has_main "${source_text}")

  if(has_main)
    list(APPEND DRONE_NODE_SOURCES "${source}")
  else()
    list(APPEND DRONE_LIBRARY_SOURCES "${source}")
  endif()
endforeach()

# .cpp files without main() become one shared internal library.
if(DRONE_LIBRARY_SOURCES)
  ament_auto_add_library(drone_lib SHARED ${DRONE_LIBRARY_SOURCES})
  target_include_directories(drone_lib PUBLIC
    "${CMAKE_CURRENT_SOURCE_DIR}"
    ${OpenCV_INCLUDE_DIRS}
  )

  # ament_cmake_auto / ament_target_dependencies uses the plain
  # target_link_libraries signature. CMake forbids mixing plain and keyword
  # signatures on the same target, so keep all link calls plain here too.
  target_link_libraries(drone_lib
    ${OpenCV_LIBS}
    Eigen3::Eigen
  )
  target_compile_options(drone_lib PRIVATE -Wall -Wextra -Wpedantic)
endif()

# Every .cpp with main() becomes a ros2 run executable named after the file.
foreach(source IN LISTS DRONE_NODE_SOURCES)
  get_filename_component(node "${source}" NAME_WE)

  if(TARGET "${node}")
    message(FATAL_ERROR
      "Duplicate node executable name '${node}'. "
      "Node filenames must be unique under app/."
    )
  endif()

  ament_auto_add_executable("${node}" "${source}")
  target_include_directories("${node}" PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}"
    ${OpenCV_INCLUDE_DIRS}
  )
  target_link_libraries("${node}"
    ${OpenCV_LIBS}
    Eigen3::Eigen
  )
  target_compile_options("${node}" PRIVATE -Wall -Wextra -Wpedantic)

  if(TARGET drone_lib)
    target_link_libraries("${node}" drone_lib)
  endif()
endforeach()

ament_auto_package()
