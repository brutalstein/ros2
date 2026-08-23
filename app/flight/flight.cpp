#include <memory>

#include "flight/flight.hpp"
#include "flight/control/offboard_controller.hpp"
#include "flight/publisher/publisher.hpp"
#include "flight/state/flight_state.hpp"
#include "flight/subscription/subscription.hpp"

class FlightNode final : public rclcpp::Node
{
public:
    FlightNode()
        : rclcpp::Node("flight"),
          state_{},
          publisher_(*this),
          subscription_(*this, state_),
          controller_(*this, state_, publisher_)
    {
        RCLCPP_INFO(
            get_logger(),
            "flight started | waiting for safe offboard entry");
    }

private:
    FlightState state_;
    FlightPublisher publisher_;
    FlightSubscription subscription_;
    OffboardController controller_;
};

std::shared_ptr<rclcpp::Node> make_flight_node()
{
    return std::make_shared<FlightNode>();
}
