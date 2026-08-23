# Simulation scenarios

Repository-owned Gazebo worlds live under `simulation/worlds/` and are selected through `simulation/scenarios.json`.

The repository default is `training_field`, so normal use is simply:

```bash
./drone start
```

List the available scenarios:

```bash
./drone scenarios
```

Select another scenario and then start the simulator:

```bash
./drone scenario urban_block
./drone start
```

You can also select and start in one command:

```bash
./drone start industrial_yard
```

Return to the repository default:

```bash
./drone scenario reset
```

Current scenarios:

- `training_field` — open flight-test field with helipad, road, hangar, service building, water tower, vehicle and trees.
- `urban_block` — roads, central launch plaza, buildings, parked vehicles, trees and street furniture.
- `industrial_yard` — warehouses, shipping containers, storage tanks, pipe bridge, forklift, barriers and service road.

## Runtime design

Repository-owned worlds are launched in PX4's supported **Gazebo standalone mode**. The root `./drone` command starts Gazebo itself using the absolute SDF path under this repository, waits until `/world/<scenario>/scene/info` is available, starts the Gazebo GUI, and only then starts PX4 with `PX4_GZ_STANDALONE=1` and the selected `PX4_GZ_WORLD`.

This separation is intentional. In normal PX4-managed mode, PX4 v1.17 constructs the world filename from its generated `PX4_GZ_WORLDS` directory. A repository-only world name would therefore be resolved inside the PX4 checkout rather than inside this repository. Standalone mode avoids that path rewrite and lets the repository own the exact world file without modifying the pinned PX4 checkout.

The Gazebo helper sources PX4's generated `gz_env.sh` so the simulator still receives the correct PX4 model paths, Gazebo system plugin path and PX4 server configuration. It then prepends `simulation/worlds` to `GZ_SIM_RESOURCE_PATH` for repository resources.

Before startup every selected world is checked with Gazebo's own SDF validator (`gz sdf -k`). The server is started before the GUI, so a failed world does not leave a disconnected black Gazebo window pretending the simulation is ready.

Each repository clone also gets an isolated `GZ_PARTITION`. PX4, Gazebo and camera discovery share that partition, preventing unrelated Gazebo sessions from being mistaken for this project's world.

## Shutdown and recovery

Normal shutdown:

```bash
./drone stop
```

The runtime owns the Gazebo server and GUI process groups directly. Shutdown tries SIGINT, then SIGTERM, and finally SIGKILL only for processes that the runtime owns. This prevents a stuck Gazebo GUI from surviving indefinitely.

For a partially failed or stale runtime:

```bash
./drone cleanup
```

The cleanup path also contains a narrow compatibility recovery for Gazebo processes leaked by the older PX4-launched implementation: it only targets Gazebo processes whose working directory is inside PX4's SITL `rootfs`, rather than killing arbitrary Gazebo sessions on the machine.

Useful diagnostics:

```bash
./drone status
./drone logs
./drone gz-logs
```

World files use SDFormat 1.9. They preserve PX4-compatible physics timing, gravity, magnetic field, atmosphere and WGS84 spherical coordinates, while all scenario geometry and materials are repository-owned and self-contained.
