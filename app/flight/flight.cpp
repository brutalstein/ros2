#include <cstdlib>
#include <memory>
#include <string_view>

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
        RCLCPP_INFO(get_logger(), "flight ready | waiting for mission");

        const char *autostart = std::getenv("DRONE_MISSION_AUTOSTART");

        if (autostart != nullptr && std::string_view(autostart) == "1")
        {
            RCLCPP_INFO(get_logger(), "mission started");
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
