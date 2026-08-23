#pragma once

#include <cstdint>
#include <limits>

struct FlightState
{
    bool hold_position_ready = false;
    bool vehicle_status_received = false;

    bool offboard_request_sent = false;
    bool offboard_confirmed = false;

    bool failsafe = false;

    uint32_t warmup_cycles = 0;

    float hold_x = 0.0f;
    float hold_y = 0.0f;
    float hold_z = 0.0f;

    float hold_yaw =
        std::numeric_limits<float>::quiet_NaN();
};
