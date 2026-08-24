#pragma once

#include <cstdint>
#include <limits>


enum class FlightPhase
{
    IDLE,
    OFFBOARD_WARMUP,
    WAIT_OFFBOARD,
    WAIT_ARM,
    ASCENDING,
    HOVER
};


struct FlightState
{
    FlightPhase phase = FlightPhase::IDLE;

    bool takeoff_requested = false;

    bool position_valid = false;
    bool vehicle_status_received = false;

    bool offboard_request_sent = false;
    bool offboard_confirmed = false;

    bool arm_request_sent = false;
    bool armed = false;

    bool failsafe = false;

    uint32_t warmup_cycles = 0;

    float current_x = 0.0f;
    float current_y = 0.0f;
    float current_z = 0.0f;

    float start_x = 0.0f;
    float start_y = 0.0f;
    float start_z = 0.0f;

    float yaw =
        std::numeric_limits<float>::quiet_NaN();

    float takeoff_altitude_m = 0.0f;
    float target_z = 0.0f;
};