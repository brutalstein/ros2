<div align="center">

# DRONE DEV CONSOLE

**WSL2 / Ubuntu 24.04 · ROS 2 Jazzy · PX4 v1.17 · Gazebo Harmonic · C++17 · VS Code**

Clone, run one setup command, then build or simulate.

</div>

## First use

Open the repository from VS Code in WSL, then:

```bash
cd /path/to/ros2
./dev setup
```

`./dev setup` is an idempotent machine bootstrap. It detects the OS, WSL generation, architecture, CPU count, RAM, GPU visibility, repository location and available VS Code integration before changing anything. It then resolves the pinned compatibility contract in `toolchain.json`, installs only missing system packages, prepares ROS, PX4, Gazebo, ROS/Gazebo bridge support, px4_msgs and Micro XRCE-DDS, installs missing VS Code extensions, performs a PX4 SITL smoke build, and finishes with an exact compatibility verification.

The primary supported profile is **WSL2 + Ubuntu 24.04 x86_64**. Native Ubuntu 24.04 x86_64 uses the same toolchain. Paths, runtime discovery and terminal handling are portable inside those supported profiles. Unsupported distributions, WSL1, native Windows and macOS fail clearly instead of receiving untested system modifications; this repository intentionally does not claim universal operating-system support.

## Deterministic stack

The repository owns one compatibility contract:

```text
ROS 2                Jazzy
ROS/Gazebo bridge    ros_gz
PX4                   v1.17.0
px4_msgs              release/1.17
Micro XRCE-DDS Agent  v2.4.3
Gazebo Sim            major 8 / Harmonic generation
Default vehicle       gz_x500_mono_cam
```

The PX4/ROS bridge pairing follows PX4's supported Jazzy configuration. External source trees and locally built third-party tools are kept under `.workspace/`, so no absolute user path is required and no generated dependency is committed.

Existing compatible clean `~/PX4-Autopilot` or `PX4_AUTOPILOT_DIR` checkouts are reused. Otherwise a clean pinned PX4 checkout is created under `.workspace/vendor/`. Dirty or incompatible external PX4 trees are never rewritten by the automation.

## Perception and autonomy foundation

The toolchain also pre-installs a deliberately small foundation for the next autonomy layers instead of waiting for each first compile to fail. `./dev setup` guarantees the camera/image path (`sensor_msgs`, `cv_bridge`, `image_transport`, `image_geometry`), time synchronization (`message_filters`), standard detection messages (`vision_msgs`), geometry/navigation messages, TF2 transforms, OpenCV 4 development libraries and Eigen3.

These dependencies cover the expected camera → OpenCV → perception → coordinate transform → planning pipeline without choosing a heavyweight inference runtime yet. CUDA-specific ML stacks such as TensorRT or ONNX Runtime are intentionally not pinned here; they will be added only when the inference architecture is chosen so the project does not create avoidable CUDA/version conflicts.

OpenCV and Eigen are wired into the shared CMake build baseline, so new C++ nodes can use them without hand-editing CMake. ROS dependencies used by source files are still declared normally in `package.xml` and the development automation continues to discover ROS include dependencies automatically.

## Daily workflow

```bash
./dev b                 # incremental build
./dev r state           # build + run a node
./dev n flight/flight   # create a node
./dev h constants/foo   # create a header
./dev verify            # verify exact stack contract
```

Node folders are optional. Every C++ source under `app/` containing `int main(...)` becomes an executable automatically; node filenames must only be unique across the project.

## One-command simulation and camera

The default simulation is now the PX4 X500 monocular-camera vehicle:

```bash
./drone start
```

One command now:

1. verifies or repairs the pinned dependencies,
2. installs `ros_gz` automatically if it is missing,
3. starts the managed Micro XRCE-DDS Agent,
4. starts PX4 + Gazebo with `gz_x500_mono_cam`,
5. discovers the actual Gazebo camera topic dynamically instead of assuming an instance number such as `_0`,
6. starts `ros_gz_bridge` in the background,
7. converts Gazebo image and camera-info messages to ROS 2,
8. remaps the long Gazebo names to the stable application API below.

```text
/camera/image_raw    sensor_msgs/msg/Image
/camera/camera_info  sensor_msgs/msg/CameraInfo
```

No manual `gz topic` lookup, `parameter_bridge` command, world name, model instance number or topic remap is required during normal use.

Useful variants:

```bash
./drone start camera   # same as the default
./drone start plain    # normal X500, no camera bridge
./drone start down     # PX4 down-facing mono-camera X500
./drone start depth    # PX4 depth-camera X500; generic RGB bridge is not forced
```

Advanced raw PX4 target overrides still work:

```bash
PX4_SIM_TARGET=gz_x500 ./drone start
./drone start gz_x500
```

Unlike the old runtime, the selected target is explicitly carried into the WSL/new-terminal process, so a target override is not lost when PX4 opens in another terminal.

Runtime commands:

```bash
./drone status
./drone logs
./drone logs -f
./drone doctor
./drone stop
```

`./drone status` also reports the camera bridge and stable ROS camera topics. `./drone stop` shuts the camera bridge down before PX4/Gazebo and the DDS Agent.

ROS inspection stays separate:

```bash
./ros topics
./ros info /camera/image_raw
./ros listen /fmu/out/vehicle_local_position_v1
./ros once /fmu/out/vehicle_status_v1
./ros rate /fmu/out/vehicle_local_position_v1
```

## Camera data path

The raw simulation image intentionally does not travel through PX4's uXRCE-DDS path:

```text
Gazebo camera
     ↓
Gazebo Transport
     ↓
ros_gz_bridge
     ↓
/camera/image_raw
     ↓
CameraNode / perception
```

PX4 state data follows its separate flight-data path:

```text
Gazebo sensors → PX4 → uORB → uXRCE-DDS → Micro XRCE-DDS Agent → ROS 2
```

Keeping the high-bandwidth image path separate prevents the flight-control communication path from becoming a video transport layer.

## Managed workspace

Everything machine-specific lives here and is gitignored:

```text
.workspace/
├── vendor/     # pinned source checkouts
├── deps/       # local third-party installs
├── build/      # colcon/CMake/PX4 build state
├── install/    # ROS workspace install
├── cache/      # compatibility/setup state
├── log/        # build logs
└── runtime/    # PX4, DDS Agent and camera bridge pid/log state
```

The repository root stays portable. Paths are derived from the repository location at runtime rather than from a username or fixed home directory. Camera discovery also uses the live Gazebo graph, so model instance suffixes such as `_0`, `_1` or `_12` are not hard-coded.

## Hardware-aware behavior

Build parallelism is derived deterministically from CPU count and available RAM and capped to avoid aggressive overcommit. GPU hardware is detected and reported, but GPU drivers are **never installed inside WSL**; WSL uses the Windows host GPU driver. Missing GPU access does not block compilation.

## VS Code

The automation checks the recommended C++, CMake, ROS and Remote-WSL extensions. `Ctrl+Shift+B` runs the normal incremental build. IntelliSense reads the compiler database generated by the actual build at `.workspace/compile_commands.json`.

## Safety rules

The bootstrap is intentionally conservative: it refuses unsupported OS profiles, does not overwrite dirty third-party repositories, does not silently switch incompatible PX4 versions, does not install Linux NVIDIA drivers inside WSL, and does not SIGKILL runtime processes as a normal shutdown path.

CI validates the compatibility manifest, camera runtime contract, perception dependency baseline, dynamic camera-topic selection, platform resolver, portable paths, Python syntax, shell syntax and the absence of generated Python bytecode on every push/PR.
