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

Return to the repository default:

```bash
./drone scenario reset
```

Current scenarios:

- `training_field` — open flight-test field with helipad, road, hangar, service building, water tower, vehicle and trees.
- `urban_block` — roads, central launch plaza, buildings, parked vehicles, trees and street furniture.
- `industrial_yard` — warehouses, shipping containers, storage tanks, pipe bridge, forklift, barriers and service road.

The launcher prepends `simulation/worlds` to `GZ_SIM_RESOURCE_PATH` and exports the selected world through `PX4_GZ_WORLD`. This follows PX4's supported custom-world mechanism while keeping the worlds inside this repository rather than modifying the PX4 checkout.

World files use SDFormat 1.9, the same generation used by the PX4 Gazebo worlds for the pinned stack. They preserve PX4-compatible physics timing, gravity, magnetic field, atmosphere and WGS84 spherical coordinates, while all scenario geometry and materials are repository-owned and self-contained.
