# ROS 2 PX4 Drone Playground

Small C++17 ROS 2 + PX4 project for learning autonomous-drone software without exposing simulator plumbing in everyday commands.

The current application intentionally does only two things:

1. execute `Drone::takeoff()` from `mission.cpp`,
2. show the simulated front camera in OpenCV.

## Toolchain

- Ubuntu 24.04 / WSL2 + WSLg
- ROS 2 Jazzy
- PX4 v1.17.0
- `px4_msgs` release/1.17
- Gazebo Harmonic / Sim 8
- Micro XRCE-DDS Agent v2.4.3
- QGroundControl v5.0.8
- OpenCV + `cv_bridge`

All managed dependencies and runtime state live under `.workspace/`.

## Three entry points

The repository has only three user-facing tools:

```text
./dev      write, build and test C++/ROS code
./mission  run and diagnose the complete drone simulation
./ros      inspect the live ROS graph
```

PX4, QGroundControl, Gazebo, DDS and camera-bridge helpers are internal implementation details.

## First setup

Run once, and again whenever the pinned toolchain changes:

```bash
./dev setup
```

It detects the machine, installs/repairs the pinned ROS/PX4 stack, builds required dependencies, verifies QGroundControl and prepares VS Code IntelliSense.

## Fly the mission

The root `mission.cpp` is the user-facing flight program:

```cpp
#include "flight/api/drone.hpp"
#include "runtime/mission.hpp"

void run_mission(Drone &drone)
{
    drone.takeoff(3.0f);
}
```

Start the complete system:

```bash
./mission start
```

The command builds the C++ application and then manages QGroundControl, Gazebo, PX4 SITL, Micro XRCE-DDS, the camera bridge and `drone_app` in the correct order. It waits for the GCS link before the mission application starts.

Useful runtime commands:

```bash
./mission status
./mission why
./mission logs
./mission stop
```

`./mission why` is a one-shot diagnosis. It reports current PX4/GCS/preflight/local-position/takeoff state instead of continuously streaming logs.

### Scenarios

```bash
./mission scenario
./mission scenario urban_block
./mission scenario reset
./mission start industrial_yard
```

The default scenario is `training_field`.

## Developer workflow

The developer surface is intentionally small:

```bash
./dev build
./dev test
./dev nodes
./dev new perception
./dev run perception
./dev clean
```

### Create and test a node

```bash
./dev new telemetry
```

creates:

```text
app/telemetry.cpp
app/telemetry.hpp
```

and registers `make_telemetry_node()` in `app/runtime/node_registry.hpp` automatically. CMake discovers the new source recursively, so no CMake edit is required.

Inspect registration:

```bash
./dev nodes
```

Run only that node:

```bash
./dev run telemetry
```

`DRONE_ONLY_NODE` is handled internally by `app/main.cpp`; the normal application still runs all registered nodes. This keeps one executable and one explicit registry while making isolated node development simple.

Before committing a change, run:

```bash
./dev test
```

It validates the project contract, checks Python/shell syntax, runs the repository unit tests and performs a full C++ build.

## ROS inspection

The ROS wrapper is read-only/inspection focused:

```bash
./ros topics
./ros nodes
./ros node flight
./ros echo /fmu/out/vehicle_status_v1
./ros once /fmu/out/vehicle_local_position_v1
./ros rate /camera/image_raw
./ros info /camera/image_raw
```

For uncommon advanced ROS operations, use the normal `ros2` CLI directly.

## Application architecture

```text
mission.cpp
    |
    v
Drone API
    |
    v
FlightState <-> OffboardController <-> FlightPublisher / FlightSubscription
    |
    v
PX4

app/main.cpp
    |
    +-- CameraNode -> /camera/image_raw -> cv_bridge -> OpenCV
    `-- FlightNode -> Drone API + PX4 Offboard control
```

`app/main.cpp` is the only process entry point. `app/runtime/node_registry.hpp` is the explicit list of nodes that run. `./dev new` keeps that registry synchronized, while `./dev run NAME` selects one registered node for local development.

## Takeoff flow

```text
Drone::takeoff(altitude)
        |
        v
wait for PX4 status + local position
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
command target altitude
        |
        v
ASCENDING -> HOVER
```

The application never force-arms the vehicle. PX4 remains responsible for low-level position, velocity, attitude, rate and motor control.

## Source layout

```text
mission.cpp
app/
  main.cpp
  camera/
  constants/
  flight/
  runtime/
tools/          # internal automation modules
simulation/
tests/
```

The public CLI stays small even though the internal runtime is defensive: it tracks process ownership, isolates Gazebo partitions, validates worlds, verifies pinned binaries and cleans partial startup failures automatically.
