# ROS 2 PX4 Drone Playground

Minimal C++17 project for learning ROS 2 + PX4 Offboard control in Gazebo.
The current application intentionally does only two things:

1. run a simple `Drone::takeoff()` mission,
2. show the simulated front camera with OpenCV.

Everything that only duplicated PX4 state or printed unused IMU/GNSS data has been removed.

## Stack

- Ubuntu 24.04 / WSL2
- ROS 2 Jazzy
- PX4 v1.17.0
- `px4_msgs` release/1.17
- Gazebo Harmonic / Gazebo Sim 8
- Micro XRCE-DDS Agent v2.4.3
- OpenCV + `cv_bridge`
- C++17

## First setup

```bash
cd ~/ros2
./dev setup
```

The project keeps downloaded/build dependencies under `.workspace/`.

## Run the mission

The root `mission.cpp` is the user-facing mission file:

```cpp
#include "flight/api/drone.hpp"
#include "runtime/mission.hpp"

void run_mission(Drone &drone)
{
    drone.takeoff(3.0f);
}
```

Start everything with:

```bash
./mission start
```

This builds the C++ app, starts the selected Gazebo world and GUI, starts PX4 SITL, starts Micro XRCE-DDS, starts the camera bridge, and runs `drone_app` with mission autostart enabled.

Stop and reset the runtime with:

```bash
./mission stop
```

Useful mission commands:

```bash
./mission start
./mission status
./mission logs
./mission stop
```

## Current application architecture

```text
app/main.cpp
   |
   +-- CameraNode
   |     `-- /camera/image_raw -> cv_bridge -> OpenCV window
   |
   `-- FlightNode
         +-- Drone API
         +-- FlightState
         +-- FlightSubscription
         +-- OffboardController
         `-- FlightPublisher
```

There is one application entry point: `app/main.cpp`.
`mission.cpp` does not define another `main()`; it only provides `run_mission(Drone&)`, which `FlightNode` calls when `./mission start` enables mission autostart.

## Takeoff flow

`drone.takeoff(3.0f)` only submits the requested altitude. The controller then advances asynchronously from the ROS executor timer:

```text
wait for PX4 status + valid local position
                |
                v
capture takeoff position
                |
                v
stream Offboard heartbeat + hold setpoint
                |
                v
request OFFBOARD
                |
                v
wait for PX4 preflight readiness
                |
                v
request normal ARM
                |
                v
command target_z = start_z - altitude
                |
                v
ASCENDING -> HOVER
```

PX4 remains responsible for position, velocity, attitude, rate and motor control. The application never force-arms the vehicle.

### No QGroundControl requirement

This project intentionally runs without a GCS. PX4's x500 SITL profile normally enables a GCS-loss action through `NAV_DLL_ACT`. The launcher sets:

```text
PX4_PARAM_NAV_DLL_ACT=0
```

for this simulator profile, so the absence of QGroundControl does not by itself block arming. This does **not** disable estimator, position, sensor, failsafe or normal arming checks.

## Why did takeoff not happen?

Use the one-shot diagnostic command:

```bash
./drone why
```

It does not stream logs continuously. It samples the latest PX4 ROS state and reports a short current diagnosis, for example:

```text
PX4: RUNNING | OFFBOARD | DISARMED
Preflight: BLOCKED | Local position: OK
Takeoff: BLOCKED
Reason: PX4 preflight checks are not ready
```

It checks `VehicleStatus`, local position, failsafe flags, estimator flags and the most recent relevant PX4/mission error when available.

For full logs:

```bash
./mission logs
./drone logs
./drone gz-logs
```

## Camera

The only ROS camera stream used by the C++ application is:

```text
/camera/image_raw
```

Flow:

```text
Gazebo camera
  -> ros_gz_bridge
  -> /camera/image_raw
  -> CameraNode
  -> cv_bridge
  -> cv::imshow("Drone Camera")
```

Camera-info bridging is disabled because the current application does not use it.

## Development commands

```bash
./dev b       # build
./dev r       # build + run drone_app
./dev check   # validate project structure
./dev verify  # verify pinned environment
./dev clean   # clean application build output
```

ROS inspection helpers:

```bash
./ros topics
./ros nodes
./ros once /fmu/out/vehicle_status_v1
./ros once /fmu/out/vehicle_local_position_v1
```

## Scenarios

```bash
./drone scenarios
./drone scenario training_field
./drone scenario urban_block
./drone scenario industrial_yard
./drone scenario reset
```

The selected world is launched by the repository-owned Gazebo runtime before PX4 connects to it.

## Source layout

```text
mission.cpp
app/
  main.cpp
  camera/
  constants/
  flight/
    api/
    control/
    publisher/
    state/
    subscription/
  runtime/
tools/
simulation/
tests/
```

The former `core/`, standalone `state/` and `sensors/` nodes were removed because they duplicated information already consumed by `FlightSubscription` and were not part of takeoff or camera operation.
