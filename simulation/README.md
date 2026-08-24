# Simulation scenarios

Repository-owned Gazebo worlds live under `simulation/worlds/` and are declared in `simulation/scenarios.json`.

Normal use goes through the single runtime entry point:

```bash
./mission start
```

List/select a world:

```bash
./mission scenario
./mission scenario urban_block
./mission scenario industrial_yard
./mission scenario reset
```

Or select and start in one command:

```bash
./mission start industrial_yard
```

Current scenarios:

- `training_field` — open flight-test field and default world.
- `urban_block` — streets, buildings, parked vehicles and a central launch plaza.
- `industrial_yard` — warehouses, containers, tanks and structured obstacle corridors.

## Internal runtime design

`./mission` owns orchestration. The Gazebo helper starts the selected repository SDF in PX4-supported standalone mode, validates it with `gz sdf -k`, waits for the world service, starts the GUI, and then the internal PX4 runtime connects with `PX4_GZ_STANDALONE=1`.

Each repository clone gets its own `GZ_PARTITION`, preventing unrelated Gazebo sessions from being mistaken for this project's world. Runtime state records process IDs/process groups and only targets managed processes during shutdown.

Shutdown is simply:

```bash
./mission stop
```

For diagnostics:

```bash
./mission status
./mission why
./mission logs
```

The internal Gazebo shutdown path escalates from SIGINT to SIGTERM and uses SIGKILL only for process groups it owns. It also contains narrow recovery for stale Gazebo processes left by older repository versions.

World files use SDFormat 1.9 and preserve PX4-compatible physics timing, gravity, magnetic field, atmosphere and WGS84 spherical coordinates.
