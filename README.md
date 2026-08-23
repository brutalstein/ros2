<div align="center">

# DRONE DEV CONSOLE

**WSL2 / Ubuntu 24.04 · ROS 2 Jazzy · PX4 v1.17 · Gazebo Harmonic · C++17 · VS Code**

One deterministic simulation runtime, one C++ application entry point.

</div>

## First use

Open the repository from VS Code in WSL, then:

```bash
cd /path/to/ros2
./dev setup
```

`./dev setup` is an idempotent machine bootstrap. It detects the platform and hardware, resolves the pinned compatibility contract in `toolchain.json`, installs only missing dependencies, prepares ROS, PX4, Gazebo, px4_msgs and Micro XRCE-DDS, and verifies the resulting stack.

The primary supported profile is **WSL2 + Ubuntu 24.04 x86_64**. Native Ubuntu 24.04 x86_64 uses the same toolchain.

## Deterministic stack

```text
ROS 2                Jazzy
ROS/Gazebo bridge    ros_gz
PX4                   v1.17.0
px4_msgs              release/1.17
Micro XRCE-DDS Agent  v2.4.3
Gazebo Sim            major 8 / Harmonic generation
Default vehicle       gz_x500_mono_cam
Default scenario      training_field
```

External source trees and generated dependencies live under `.workspace/`. The repository does not require user-specific absolute paths.

## Application architecture: one entry point

`app/main.cpp` is the **only C++ `main()` in the application**. Core, state, sensors, camera, flight and future autonomy components are node modules linked into one executable named `drone_app`.

```text
app/main.cpp
     │
     ├── CoreNode
     ├── StateNode
     ├── SensorsNode
     ├── CameraNode
     └── FlightNode
```

CMake rejects any extra `main()` under `app/`. Node implementation files expose a `make_<name>_node()` factory instead.

The development automation follows the same rule. Creating a module:

```bash
./dev n perception/detector
```

automatically creates:

```text
app/perception/detector.cpp
app/perception/detector.hpp
```

and registers `make_detector_node()` in `app/main.cpp`. No manual CMake edit or second process entry point is needed.

## Daily workflow

```bash
./dev b                         # incremental application build
./dev r                         # build + run the complete app/main.cpp system
./dev n perception/detector     # create + register a new node module
./dev h constants/foo           # create a generic header
./dev ls                        # show entrypoint and linked modules
./dev check                     # validate architecture + automation
./dev verify                    # verify exact stack contract
```

`./dev r` always runs the complete application, not an individual node.

## Simulation runtime

The simulation infrastructure remains deliberately separate from the C++ application process:

```text
./drone start
     │
     ├── Gazebo server + GUI
     ├── selected repository-owned scenario
     ├── PX4 SITL
     ├── Micro XRCE-DDS Agent
     └── ros_gz camera bridge
```

Gazebo worlds live under `simulation/worlds/`. The default is `training_field`.

```bash
./drone scenarios
./drone scenario urban_block
./drone scenario industrial_yard
./drone scenario reset
```

The runtime starts repository-owned worlds directly from their absolute SDF path, validates them before launch, and connects PX4 using its supported standalone Gazebo mode. Gazebo server and GUI are runtime-owned processes so `./drone stop` can shut them down reliably.

Useful runtime commands:

```bash
./drone start
./drone status
./drone logs
./drone gz-logs
./drone cleanup
./drone stop
```

## First autonomous command: takeoff

`FlightNode` is part of `app/main.cpp` and currently implements the first closed-loop flight action: **safe PX4 Offboard takeoff followed by hover**.

Default behavior:

```text
wait for PX4 status + valid local position
              ↓
wait for PX4 preflight checks
              ↓
capture local NED takeoff origin
              ↓
stream Offboard heartbeat + hold setpoint at 10 Hz for 2 s
              ↓
request OFFBOARD mode + normal arm
              ↓
command z = origin_z - 3 m
              ↓
climb to ~3 m
              ↓
hold position / hover
```

The code does **not** force-arm or bypass PX4 health checks. If PX4 is not ready or is in failsafe, takeoff is paused instead of overriding the autopilot.

Normal use is two terminals:

```bash
# Terminal 1: simulator / flight stack infrastructure
./drone start
```

```bash
# Terminal 2: the one C++ application
./dev r
```

The default takeoff altitude is 3 metres. It can be changed through the ROS parameter:

```bash
./dev r --ros-args -p takeoff_altitude_m:=5.0
```

Automatic takeoff can be disabled while still running the rest of the application:

```bash
./dev r --ros-args -p auto_takeoff:=false
```

## Camera and perception foundation

`./dev setup` guarantees the foundational image/perception dependencies: `sensor_msgs`, `cv_bridge`, `image_transport`, `image_geometry`, `message_filters`, `vision_msgs`, geometry/navigation messages, TF2, OpenCV 4 and Eigen3.

The simulation camera path is intentionally separate from PX4 flight-state transport:

```text
Gazebo camera
     ↓
Gazebo Transport
     ↓
ros_gz_bridge
     ↓
/camera/image_raw
     ↓
CameraNode
     ↓
cv_bridge
     ↓
OpenCV cv::Mat
```

PX4 flight/state data follows:

```text
Gazebo sensors → PX4 → uORB → uXRCE-DDS → Micro XRCE-DDS Agent → ROS 2
```

Stable camera API:

```text
/camera/image_raw    sensor_msgs/msg/Image
/camera/camera_info  sensor_msgs/msg/CameraInfo
```

## ROS inspection

```bash
./ros topics
./ros info /camera/image_raw
./ros listen /fmu/out/vehicle_local_position_v1
./ros once /fmu/out/vehicle_status_v1
./ros rate /fmu/out/vehicle_local_position_v1
```

## Managed workspace

```text
.workspace/
├── vendor/     # pinned source checkouts
├── deps/       # locally built dependencies
├── build/      # build state
├── install/    # ROS workspace install
├── cache/      # setup state
├── log/        # build logs
└── runtime/    # PX4 / Gazebo / bridge runtime state and logs
```

## Hardware-aware behavior

Build parallelism is derived from CPU count and available RAM and capped to avoid aggressive overcommit. GPU hardware is detected and reported, but Linux NVIDIA drivers are never installed inside WSL; WSL uses the Windows host GPU driver.

## VS Code

The automation checks the recommended C++, CMake, ROS and Remote-WSL extensions. IntelliSense uses `.workspace/compile_commands.json`, generated from the real build.

## Safety rules

The bootstrap refuses unsupported OS profiles, does not overwrite dirty third-party repositories, does not silently change pinned PX4 versions, and does not install Linux NVIDIA drivers inside WSL. Flight code does not bypass PX4 preflight or arming safety checks. Gazebo SIGKILL escalation is restricted to runtime-owned Gazebo process groups when graceful shutdown fails.

CI validates the compatibility manifest, single-entry application architecture, offboard takeoff contract, camera/perception baseline, scenario worlds, Gazebo runtime contract, portable paths, Python/shell syntax and generated-file hygiene on every push and pull request.
