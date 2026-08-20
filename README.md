# ros2

Minimal ROS 2 Jazzy C++ workspace for WSL drone development.

The actual drone project stays under `app/`. C++ files may be grouped however you want:

```text
app/
├── core/
│   └── core.cpp
├── constants/
│   └── topics.hpp
├── sensors/
├── control/
├── planning/
├── CMakeLists.txt
└── package.xml
```

No `src/` or `include/` convention is required in this learning project.

## One-time setup

From the repository root:

```bash
./dev setup
code .
```

## Daily use

```bash
./dev b                    # incremental build + refresh VS Code
./dev r core               # build and run core
./dev ls                   # list detected nodes
./dev n sensors/imu        # create app/sensors/imu.cpp
./dev h constants/topics   # create app/constants/topics.hpp
./dev d sensor_msgs        # add/install a ROS dependency
./dev check                # quick automation/project validation
./dev doctor               # WSL + ROS + Gazebo + GPU checks
./dev fmt                  # clang-format C/C++ files
./dev rb                   # clean rebuild
./dev clean                # remove generated build files
```

Always run `./dev ...` from the repository root (`~/ros2`).

## Automatic behavior

- C++ can live anywhere under `app/`.
- A `.cpp/.cc/.cxx` file containing `int main(...)` is automatically a ROS executable.
- Its executable name is its filename: `app/core/core.cpp` -> `core`.
- A C++ source without `main()` is treated as shared implementation code and linked to the nodes.
- Header files need no CMake edits; include from the app root, e.g. `#include "constants/topics.hpp"`.
- Node filenames must be unique across `app/`; duplicates fail early with a clear error.
- Installed ROS packages referenced by `#include` are synchronized into `package.xml` when detected.
- `rosdep` resolves declared dependencies.
- Build is incremental through CMake/colcon; unchanged files are not unnecessarily recompiled.
- `compile_commands.json` is refreshed after a successful build so VS Code C++ IntelliSense follows the real compiler configuration.

## VS Code

`Ctrl+Shift+B` runs `./dev b`.

Use **Terminal -> Run Task** for Build, Run Node, Check, Doctor, and Rebuild.
