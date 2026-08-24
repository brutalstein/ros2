#include <cstdlib>
#include <memory>

#include "flight/flight.hpp"
#include "flight/api/drone.hpp"
#include "flight/control/offboard_controller.hpp"
#include "flight/publisher/publisher.hpp"
#include "flight/state/flight_state.hpp"
#include "flight/subscription/subscription.hpp"
#include "runtime/mission.hpp"

class FlightNode final : public rclcpp::Node
{
public:
    FlightNode()
        : rclcpp::Node("flight"),
          state_{},
          publisher_(*this),
          subscription_(*this, state_),
          controller_(*this, state_, publisher_),
          drone_(state_)
    {
        RCLCPP_INFO(
            get_logger(),
            "flight started | waiting for safe offboard entry");

        const char *mission_autostart =
            std::getenv("DRONE_MISSION_AUTOSTART");

        if (mission_autostart != nullptr &&
            mission_autostart[0] == '1' &&
            mission_autostart[1] == '\0')
        {
            RCLCPP_INFO(
                get_logger(),
                "mission autostart enabled");

            run_mission(drone_);
        }
    }

private:
    FlightState state_;
    FlightPublisher publisher_;
    FlightSubscription subscription_;
    OffboardController controller_;
    Drone drone_;
};

std::shared_ptr<rclcpp::Node> make_flight_node()
{
    return std::make_shared<FlightNode>();
}
