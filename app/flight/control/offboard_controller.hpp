#pragma once

#include <cstdint>

#include "rclcpp/rclcpp.hpp"

#include "flight/publisher/publisher.hpp"
#include "flight/state/flight_state.hpp"

class OffboardController
{
public:
    OffboardController(
        rclcpp::Node &node,
        FlightState &state,
        FlightPublisher &publisher);

private:
    static constexpr uint32_t OFFBOARD_WARMUP_CYCLES = 15;

    rclcpp::Node &node_;
    FlightState &state_;
    FlightPublisher &publisher_;

    rclcpp::TimerBase::SharedPtr control_timer_;

    uint64_t now_us() const;

    void control_loop();
    void request_offboard_mode();
};
