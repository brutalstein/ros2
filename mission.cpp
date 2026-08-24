#include "flight/api/drone.hpp"
#include "runtime/mission.hpp"

void run_mission(Drone &drone)
{
    drone.takeoff(3.0f);
}
