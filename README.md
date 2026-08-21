<div align="center">

# DRONE DEV CONSOLE

**ROS 2 Jazzy · PX4 v1.17 · Gazebo Harmonic · C++ · WSL2**

![ROS 2](https://img.shields.io/badge/ROS_2-Jazzy-22314E?logo=ros&logoColor=white)
![PX4](https://img.shields.io/badge/PX4-v1.17-111111)
![Ubuntu](https://img.shields.io/badge/Ubuntu-24.04-E95420?logo=ubuntu&logoColor=white)
![Gazebo](https://img.shields.io/badge/Gazebo-8.x-F58113)
![C++](https://img.shields.io/badge/C++-17-00599C?logo=cplusplus&logoColor=white)
![WSL](https://img.shields.io/badge/WSL2-ready-0078D4?logo=windows&logoColor=white)

**One initialization. Three focused consoles. Clean repository.**

</div>

```mermaid
flowchart LR
    INIT[./dev init workspace] --> READY[Workspace Ready]
    READY --> DEV[./dev]
    READY --> DRONE[./drone]
    READY --> ROS[./ros]
    DEV --> BUILD[Create · Build · PX4 Interfaces]
    DRONE --> SIM[DDS Agent · PX4 · Gazebo]
    ROS --> GRAPH[Run · Listen · Inspect]
```

## First use

Open the repository root:

```bash
cd ~/ros2
```

Initialize everything with one command:

```bash
./dev init workspace
```

This command is safe to run again. It checks or prepares the development toolchain, ROS dependencies, VS Code extensions, PX4 message interfaces, the first build, and compiler metadata used by IntelliSense.

Normal development:

```bash
./dev b
```

Start the simulator runtime:

```bash
./drone start
```

Then use a separate terminal for your own ROS work:

```bash
./dev r state
./ros topics
```

---

## Architecture

Each root command has one responsibility:

```text
./dev    development/build/dependencies/VS Code
./drone  PX4 + Gazebo + DDS runtime orchestration
./ros    ROS graph inspection and interaction
```

`./drone start` keeps the Micro XRCE-DDS Agent in the background and opens PX4 + Gazebo in a separate WSL/Windows terminal. Your ROS terminal remains yours.

---

## Clean workspace layout

Only project-facing files stay visible at repository root:

```text
ros2/
├── app/
├── tools/
├── .vscode/
├── dev
├── drone
├── ros
└── README.md
```

Generated, external, and runtime state is isolated in `.workspace/`:

```text
.workspace/
├── build/
├── install/
├── log/
├── vendor/
├── cache/
├── runtime/
└── compile_commands.json
```

`.workspace/runtime/` contains only runtime metadata such as process identities and the background DDS Agent log. VS Code hides `.workspace/` from Explorer/search while still using its generated compiler metadata and PX4 headers.

Older root-level `build/`, `install/`, `log/`, `vendor/`, `.cache/`, and `compile_commands.json` layouts are migrated automatically. External vendor/cache data is preserved; reproducible build artifacts are regenerated instead of being moved with stale absolute paths.

---

## `./drone` — simulation runtime console

The normal command is:

```bash
./drone start
```

It performs a guarded startup sequence:

```text
validate WSL/PX4
      ↓
find or start MicroXRCEAgent
      ↓
verify UDP 8888 is actually bound
      ↓
prevent duplicate PX4 instances
      ↓
open a new WSL terminal
      ↓
make px4_sitl gz_x500
      ↓
PX4 + Gazebo ready for ROS
```

| Command | Purpose |
|---|---|
| `./drone start` | Start/reuse DDS Agent in background and open PX4 + Gazebo in a new terminal |
| `./drone status` | Show Agent, UDP port, PX4 and Gazebo state |
| `./drone stop` | Gracefully stop processes owned by this runtime console |
| `./drone logs` | Show recent background DDS Agent logs |
| `./drone logs -f` | Follow DDS Agent logs live |
| `./drone doctor` | Validate WSL, PX4 checkout, Agent binary, port and Windows terminal launcher |

Safety behavior:

- repeated `./drone start` calls are idempotent and do not intentionally launch duplicate Agent/PX4 instances;
- an existing compatible MicroXRCEAgent is reused instead of killed;
- if UDP 8888 belongs to an unknown process, startup fails instead of taking it over;
- process state stores both PID and Linux process start identity to reduce PID-reuse mistakes;
- `./drone stop` does not kill external processes it did not start;
- if PX4 window creation fails after this invocation started the Agent, that Agent is rolled back;
- background logs live under `.workspace/runtime/logs/`.

Defaults can be overridden without changing source:

```text
PX4_AUTOPILOT_DIR     default: ~/PX4-Autopilot
PX4_SIM_TARGET        default: gz_x500
XRCE_DDS_PORT         default: 8888
MICRO_XRCE_AGENT_BIN  explicit Agent executable path
```

---

## `./dev` — development console

| Command | Purpose |
|---|---|
| `./dev init workspace` | Initialize/migrate the workspace, prepare VS Code/PX4, perform first build |
| `./dev b` | Incremental build + refresh IntelliSense |
| `./dev rb` | Clean rebuild |
| `./dev n sensors/imu` | Create `app/sensors/imu.cpp` |
| `./dev h constants/topics` | Create `app/constants/topics.hpp` |
| `./dev d sensor_msgs` | Add/install a ROS dependency |
| `./dev r core` | Build and run a node |
| `./dev ls` | List detected node executables |
| `./dev px4` | Prepare/check version-matched PX4 ROS message interfaces |
| `./dev check` | Validate project scripts, node discovery and workspace layout |
| `./dev doctor` | Check WSL, ROS, Gazebo, compiler, VS Code and GPU |
| `./dev fmt` | Format project C/C++ files |
| `./dev clean` | Remove generated build/install/log while preserving vendor/runtime state |
| `./dev shell` | Open a workspace-ready ROS shell |

### Normal coding flow

```bash
./dev n state/state
# write code in VS Code
./dev b
./dev r state
```

Headers under `app/` need no manual CMake entry. A `.cpp` containing `int main(...)` becomes a node executable automatically, and newly created files are discovered on the next `./dev b`.

---

## PX4 interface automation

`./dev init workspace`, `./dev b`, `./dev r ...` and `./dev rb` manage the ROS-side PX4 message interface automatically.

```mermaid
flowchart LR
    PX4[~/PX4-Autopilot] --> VERSION[Detect release]
    VERSION --> MSGS[.workspace/vendor/px4_msgs]
    MSGS --> COLCON[colcon]
    COLCON --> INSTALL[.workspace/install]
    INSTALL --> CC[compile_commands.json]
    CC --> VSCODE[VS Code]
```

The automation detects the local PX4 release, selects the matching `px4_msgs` release line, refuses to overwrite dirty or unexpected vendor repositories, never modifies `~/PX4-Autopilot`, and only rebuilds the interface when necessary.

After that, normal C++ includes are resolved through the same workflow:

```cpp
#include "px4_msgs/msg/vehicle_local_position.hpp"
```

`./dev` manages the ROS-side interface/build environment. `./drone` manages the simulator runtime. PX4's low-level control stack itself remains inside the PX4 checkout.

---

## `./ros` — ROS runtime console

### Topics

| Command | Purpose |
|---|---|
| `./ros topics` | List topics with message types |
| `./ros listen /drone/status` | Continuously print a topic |
| `./ros once /drone/status` | Read one message |
| `./ros rate /drone/status` | Show message frequency |
| `./ros info /drone/status` | Show publishers/subscribers/QoS |
| `./ros send TOPIC TYPE DATA` | Publish one message |

### Nodes / services / parameters

| Command | Purpose |
|---|---|
| `./ros nodes` | List running nodes |
| `./ros node core` | Inspect a node |
| `./ros run core` | Run an already-built node |
| `./ros services` | List services |
| `./ros call SERVICE TYPE DATA` | Call a service |
| `./ros params core` | List node parameters |
| `./ros get core PARAM` | Read a parameter |
| `./ros set core PARAM VALUE` | Change a parameter |
| `./ros doctor` | Check the ROS runtime environment |

Short aliases:

```text
./ros t        -> topics
./ros l TOPIC  -> listen
./ros o TOPIC  -> once
./ros hz TOPIC -> rate
./ros n        -> nodes
./ros r NODE   -> run
./ros s        -> services
```

---

## VS Code

`Ctrl + Shift + B` runs:

```bash
./dev b
```

The task palette also includes `Drone: Start Runtime`, `Drone: Status`, and `Drone: Stop Runtime`.

The C++ extension reads `.workspace/compile_commands.json`, so project, ROS, and generated PX4 include paths come from the real build configuration instead of hand-maintained guesses.
