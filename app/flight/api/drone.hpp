#pragma once

#include "flight/state/flight_state.hpp"

class Drone
{
public:
    explicit Drone(FlightState &state);

    bool takeoff(float altitude_m);

private:
    FlightState &state_;
};
