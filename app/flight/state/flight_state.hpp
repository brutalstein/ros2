#pragma once

#include <limits>

struct FlightState
{
    // Mission request written by the public Drone API.
    bool takeoff_requested = false;
    float takeoff_altitude_m = 0.0f;

    // Latest PX4 position needed by the takeoff controller.
    bool position_valid = false;
    float current_x = 0.0f;
    float current_y = 0.0f;
    float current_z = 0.0f;
    float yaw = std::numeric_limits<float>::quiet_NaN();

    // Latest PX4 vehicle state needed to decide whether takeoff may continue.
    bool status_received = false;
    bool preflight_ready = false;
    bool offboard = false;
    bool armed = false;
    bool failsafe = false;
};
