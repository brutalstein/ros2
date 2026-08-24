#include "flight/api/drone.hpp"

Drone::Drone(FlightState &state) : state_(state){}

int Drone::takeoff(float altitude_m){
  if(altitude_m <= 0.0f){
    return 0;
  }
  if(state_.takeoff_requested == false){
    return 0;
  }
  state_.takeoff_altitude_m = altitude_m;
  state_.takeoff_requested = true;
  return 1;
}