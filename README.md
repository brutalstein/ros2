# ros2

Minimal ROS 2 Jazzy workspace for WSL development. The repository intentionally keeps one ROS package and one developer command.

## First use

```bash
git clone https://github.com/brutalstein/ros2.git
cd ros2
./dev setup
code .
```

`setup` checks the ROS toolchain, installs missing helper packages when needed, initializes rosdep, installs the recommended VS Code extensions, builds the workspace, and generates IntelliSense data.

## Daily commands

```bash
./dev n status        # create app/src/status.cpp and build
./dev h topics        # create app/include/drone/topics.hpp
./dev b               # build + refresh VS Code IntelliSense
./dev r status        # build + run node
./dev d sensor_msgs   # add a ROS dependency
./dev doctor          # check ROS, Gazebo, compiler, VS Code, NVIDIA
./dev clean           # clean generated build files
```

Long command names also work: `node`, `header`, `build`, `run`, `dep`, `setup`.

## Structure

```text
ros2/
├── app/              # the single ROS package
│   ├── CMakeLists.txt
│   └── package.xml
├── tools/            # development automation
├── .vscode/          # shared WSL/IntelliSense setup
└── dev               # the only command you normally need
```

`app/src/` and `app/include/drone/` are created when you add your first node/header, so the repository stays clean and has no empty folder tree.

## What is automatic?

- Every `app/src/*.cpp` file becomes a ROS 2 executable named after the file. No `add_executable()` edits.
- Headers under `app/include/drone/` require no CMake edits.
- `./dev build` scans ROS-style `#include` paths and adds already-installed ROS package dependencies to `package.xml` when possible.
- `ament_cmake_auto` reads dependencies from `package.xml`, so dependencies are not duplicated in CMake.
- Every build refreshes the root `compile_commands.json`, which VS Code C/C++ IntelliSense uses.
- Every `./dev` command sources ROS Jazzy automatically. You do not need to type `source /opt/ros/jazzy/setup.bash` for these commands.

The actual drone architecture will be added gradually on top of this base.
