#pragma once

namespace topics
{
    inline constexpr const char STATUS[] =
        "/drone/status";

    inline constexpr const char PX4_LOCAL_POSITION[] =
        "/fmu/out/vehicle_local_position_v1";

    inline constexpr const char PX4_VEHICLE_STATUS[] =
        "/fmu/out/vehicle_status_v1";

    inline constexpr const char PX4_IMU_SENSOR[] =
        "/fmu/out/sensor_combined";

    inline constexpr const char PX4_GNSS_SENSOR[] =
        "/fmu/out/vehicle_gps_position";

    inline constexpr const char PX4_OFFBOARD_CONTROL_MODE[] =
        "/fmu/in/offboard_control_mode";

    inline constexpr const char PX4_TRAJECTORY_SETPOINT[] =
        "/fmu/in/trajectory_setpoint";

    inline constexpr const char PX4_VEHICLE_COMMAND[] =
        "/fmu/in/vehicle_command";
}
