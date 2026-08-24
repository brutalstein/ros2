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
    enum class Phase
    {
        IDLE,
        WARMUP,
        WAIT_OFFBOARD,
        WAIT_PREFLIGHT,
        WAIT_ARM,
        ASCENDING,
        HOVER,
        FAILED
    };

    static constexpr uint32_t WARMUP_CYCLES = 15;
    static constexpr uint32_t RETRY_CYCLES = 10;
    static constexpr uint32_t MAX_REQUEST_ATTEMPTS = 5;
    static constexpr float ALTITUDE_TOLERANCE_M = 0.15f;

    rclcpp::Node &node_;
    FlightState &state_;
    FlightPublisher &publisher_;
    rclcpp::TimerBase::SharedPtr control_timer_;

    Phase phase_ = Phase::IDLE;
    uint32_t phase_cycles_ = 0;
    uint32_t offboard_attempts_ = 0;
    uint32_t arm_attempts_ = 0;

    float hold_x_ = 0.0f;
    float hold_y_ = 0.0f;
    float hold_z_ = 0.0f;
    float hold_yaw_ = 0.0f;
    float target_z_ = 0.0f;

    uint64_t now_us() const;
    void control_loop();
    void publish_stream(uint64_t timestamp);
    void request_offboard_mode();
    void request_arm();
    void fail_takeoff(const char *reason);
};
