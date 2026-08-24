#pragma once

#include "flight/state/flight_state.hpp"

class Drone {
  public:
    explicit Drone(FlightState &state);

    int takeoff(float altitude_m);
    
  private:
    FlightState &state_;
};