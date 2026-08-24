# ROS 2 PX4 Drone Playground

Minimal C++17 project for learning ROS 2 + PX4 Offboard control in Gazebo.
The current application intentionally does only two things:

1. run a simple `Drone::takeoff()` mission,
2. show the simulated front camera with OpenCV.

Everything that only duplicated PX4 state or printed unused IMU/GNSS data has been removed.

## Stack

- Ubuntu 24.04 / WSL2 + WSLg
- ROS 2 Jazzy
- PX4 v1.17.0
- `px4_msgs` release/1.17
- Gazebo Harmonic / Gazebo Sim 8
- Micro XRCE-DDS Agent v2.4.3
- QGroundControl v5.0.8
- OpenCV + `cv_bridge`
- C++17

## First setup

```bash
cd ~/ros2
./dev setup
```

`./dev setup` installs/builds the ROS/PX4 toolchain and also downloads the managed Linux QGroundControl AppImage into `.workspace/deps/`.

QGroundControl runs inside Ubuntu/WSL. On WSL2, WSLg must be enabled so the GUI can open. The current SITL workflow uses MAVLink UDP only, so the setup does not modify serial-port groups or disable ModemManager.

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

This builds the C++ app and then automatically starts:

```text
QGroundControl
      |
      | MAVLink UDP 14550
      v
PX4 SITL <-> Gazebo
      |
      | uXRCE-DDS
      v
Micro XRCE-DDS Agent <-> ROS 2
      |
      +-> FlightNode
      `-> Camera bridge -> CameraNode -> OpenCV
```

The launcher does not continue silently if the GCS is missing. After PX4 starts it waits until `VehicleStatus.gcs_connection_lost` becomes false and prints:

```text
[OK] PX4 <-> QGroundControl connected
```

Only after the simulation runtime and GCS link are ready does `./mission start` launch `drone_app` with mission autostart enabled.

Stop and reset the runtime with:

```bash
./mission stop
```

This also closes the managed QGroundControl process.

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

## QGroundControl and arming

The runtime now uses PX4's normal GCS behavior. There is no `NAV_DLL_ACT=0` bypass in the launcher.

`./drone start` and `./mission start` both launch the managed QGroundControl process before PX4 and then verify the MAVLink GCS connection. This means a missing GCS is treated as a startup problem instead of being hidden until ARM is rejected.

QGroundControl listens on the standard SITL GCS UDP port:

```text
14550/udp
```

If QGroundControl cannot open, cannot bind the port, or PX4 still reports the GCS link as lost, startup fails with a short error and cleans up the partial runtime.

## Why did takeoff not happen?

Use the one-shot diagnostic command:

```bash
./drone why
```

It does not stream logs continuously. It samples the latest PX4 ROS state and reports a short current diagnosis, for example:

```text
PX4: RUNNING | OFFBOARD | DISARMED
QGroundControl: RUNNING | PX4 link: CONNECTED
Preflight: BLOCKED | Local position: OK
Takeoff: BLOCKED
Reason: PX4 preflight checks are not ready
```

If the GCS is the problem it now says so explicitly, for example:

```text
QGroundControl: STOPPED | PX4 link: DISCONNECTED
Takeoff: BLOCKED
Reason: QGroundControl is not running
```

It checks `VehicleStatus`, local position, failsafe flags, estimator flags and the most recent relevant PX4/mission error when available.

For full logs:

```bash
./mission logs
./drone logs
./drone gz-logs
```

`./drone logs` also includes recent QGroundControl output.

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
./dev setup   # install/repair ROS, PX4, DDS Agent and QGroundControl
./dev b       # build
./dev r       # build + run drone_app
./dev check   # validate project structure
./dev verify  # verify pinned core environment
./dev clean   # clean application build output
```

Runtime helpers:

```bash
./drone start
./drone status
./drone why
./drone logs
./drone stop
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
  qgroundcontrol.py
simulation/
tests/
```

The former `core/`, standalone `state/` and `sensors/` nodes were removed because they duplicated information already consumed by `FlightSubscription` and were not part of takeoff or camera operation.
