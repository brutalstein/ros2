cmake_minimum_required(VERSION 3.16)
project(drone)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

find_package(ament_cmake_auto REQUIRED)
ament_auto_find_build_dependencies()
find_package(OpenCV 4 REQUIRED)

set(DRONE_ENTRYPOINT "${CMAKE_CURRENT_SOURCE_DIR}/main.cpp")
set(DRONE_MISSION_STUB "${CMAKE_CURRENT_SOURCE_DIR}/runtime/mission_stub.cpp")

if(NOT EXISTS "${DRONE_ENTRYPOINT}")
  message(FATAL_ERROR "Single application entry point is missing: app/main.cpp")
endif()

# Compile every implementation under app/. app/main.cpp is the only process
# entrypoint; everything else is linked into drone_lib.
file(GLOB_RECURSE DRONE_CPP
  CONFIGURE_DEPENDS
  LIST_DIRECTORIES false
  "${CMAKE_CURRENT_SOURCE_DIR}/*.cpp"
  "${CMAKE_CURRENT_SOURCE_DIR}/*.cc"
  "${CMAKE_CURRENT_SOURCE_DIR}/*.cxx"
)

# A root mission.cpp is optional. When present it replaces the empty mission
# stub and is linked into the same application.
file(GLOB DRONE_ROOT_MISSION
  CONFIGURE_DEPENDS
  "${CMAKE_CURRENT_SOURCE_DIR}/../mission.cpp"
)

set(DRONE_LIBRARY_SOURCES ${DRONE_CPP})
list(REMOVE_ITEM DRONE_LIBRARY_SOURCES "${DRONE_ENTRYPOINT}")

if(DRONE_ROOT_MISSION)
  list(REMOVE_ITEM DRONE_LIBRARY_SOURCES "${DRONE_MISSION_STUB}")
  list(APPEND DRONE_LIBRARY_SOURCES ${DRONE_ROOT_MISSION})
endif()

list(SORT DRONE_LIBRARY_SOURCES)

foreach(source IN LISTS DRONE_LIBRARY_SOURCES)
  file(READ "${source}" source_text)
  string(REGEX MATCH "(^|[\r\n])[ \t]*int[ \t\r\n]+main[ \t\r\n]*\\(" has_main "${source_text}")
  if(has_main)
    file(RELATIVE_PATH relative_source "${CMAKE_CURRENT_SOURCE_DIR}" "${source}")
    message(FATAL_ERROR
      "Only app/main.cpp may define main(). Remove main() from ${relative_source}."
    )
  endif()
endforeach()

ament_auto_add_library(drone_lib SHARED ${DRONE_LIBRARY_SOURCES})
target_include_directories(drone_lib PUBLIC
  "${CMAKE_CURRENT_SOURCE_DIR}"
  ${OpenCV_INCLUDE_DIRS}
)
target_link_libraries(drone_lib ${OpenCV_LIBS})
target_compile_options(drone_lib PRIVATE -Wall -Wextra -Wpedantic)

ament_auto_add_executable(drone_app "${DRONE_ENTRYPOINT}")
target_include_directories(drone_app PRIVATE
  "${CMAKE_CURRENT_SOURCE_DIR}"
  ${OpenCV_INCLUDE_DIRS}
)
target_link_libraries(drone_app drone_lib ${OpenCV_LIBS})
target_compile_options(drone_app PRIVATE -Wall -Wextra -Wpedantic)

ament_auto_package()
