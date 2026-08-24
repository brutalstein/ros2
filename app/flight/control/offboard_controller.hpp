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
    static constexpr uint32_t ARM_RETRY_CYCLES = 10;
    static constexpr uint32_t ARM_MAX_ATTEMPTS = 5;


    rclcpp::Node &node_;
    FlightState &state_;
    FlightPublisher &publisher_;


    rclcpp::TimerBase::SharedPtr control_timer_;

    uint32_t arm_retry_cycles_ = 0;
    uint32_t arm_attempts_ = 0;


    uint64_t now_us() const;

    void control_loop();

    void request_offboard_mode();
    void request_arm();
};