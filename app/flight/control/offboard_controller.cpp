#include <chrono>
#include <cmath>

#include "flight/control/offboard_controller.hpp"
#include "px4_msgs/msg/vehicle_command.hpp"

using namespace std::chrono_literals;

OffboardController::OffboardController(
    rclcpp::Node &node,
    FlightState &state,
    FlightPublisher &publisher)
    : node_(node),
      state_(state),
      publisher_(publisher)
{
    control_timer_ = node_.create_wall_timer(
        100ms,
        [this]()
        {
            control_loop();
        });
}

uint64_t OffboardController::now_us() const
{
    return static_cast<uint64_t>(
        node_.get_clock()->now().nanoseconds() / 1000);
}

void OffboardController::control_loop()
{
    if (!state_.takeoff_requested)
    {
        return;
    }

    if (phase_ == Phase::IDLE)
    {
        if (!state_.position_valid)
        {
            RCLCPP_WARN_THROTTLE(
                node_.get_logger(),
                *node_.get_clock(),
                2000,
                "takeoff waiting | PX4 local position is not valid");
            return;
        }

        if (!state_.status_received)
        {
            return;
        }

        if (state_.failsafe)
        {
            RCLCPP_WARN_THROTTLE(
                node_.get_logger(),
                *node_.get_clock(),
                2000,
                "takeoff waiting | PX4 failsafe is active");
            return;
        }

        hold_x_ = state_.current_x;
        hold_y_ = state_.current_y;
        hold_z_ = state_.current_z;
        hold_yaw_ = state_.yaw;
        target_z_ = hold_z_ - state_.takeoff_altitude_m;

        phase_cycles_ = 0;
        offboard_attempts_ = 0;
        arm_attempts_ = 0;
        phase_ = Phase::WARMUP;

        RCLCPP_INFO(
            node_.get_logger(),
            "takeoff prepared | altitude: %.2f m | target z: %.2f",
            state_.takeoff_altitude_m,
            target_z_);
        return;
    }

    if (!state_.position_valid)
    {
        fail_takeoff("PX4 local position became invalid");
    }

    if (state_.failsafe)
    {
        fail_takeoff("PX4 failsafe became active");
    }

    const uint64_t timestamp = now_us();
    publish_stream(timestamp);

    switch (phase_)
    {
        case Phase::IDLE:
            break;

        case Phase::WARMUP:
        {
            phase_cycles_++;

            if (phase_cycles_ >= WARMUP_CYCLES)
            {
                request_offboard_mode();
                offboard_attempts_ = 1;
                phase_cycles_ = 0;
                phase_ = Phase::WAIT_OFFBOARD;
            }
            break;
        }

        case Phase::WAIT_OFFBOARD:
        {
            if (state_.offboard)
            {
                phase_cycles_ = 0;

                if (state_.preflight_ready)
                {
                    request_arm();
                    arm_attempts_ = 1;
                    phase_ = Phase::WAIT_ARM;
                }
                else
                {
                    phase_ = Phase::WAIT_PREFLIGHT;
                    RCLCPP_WARN(
                        node_.get_logger(),
                        "OFFBOARD ready | waiting for PX4 preflight checks");
                }
                break;
            }

            phase_cycles_++;

            if (phase_cycles_ >= RETRY_CYCLES)
            {
                phase_cycles_ = 0;

                if (offboard_attempts_ >= MAX_REQUEST_ATTEMPTS)
                {
                    fail_takeoff("PX4 did not enter OFFBOARD mode");
                    break;
                }

                offboard_attempts_++;
                request_offboard_mode();
            }
            break;
        }

        case Phase::WAIT_PREFLIGHT:
        {
            if (!state_.offboard)
            {
                phase_cycles_ = 0;
                phase_ = Phase::WAIT_OFFBOARD;
                break;
            }

            if (!state_.preflight_ready)
            {
                break;
            }

            if (arm_attempts_ >= MAX_REQUEST_ATTEMPTS)
            {
                fail_takeoff("PX4 preflight recovered after ARM retries were exhausted");
                break;
            }

            arm_attempts_++;
            phase_cycles_ = 0;
            request_arm();
            phase_ = Phase::WAIT_ARM;
            break;
        }

        case Phase::WAIT_ARM:
        {
            if (state_.armed)
            {
                phase_cycles_ = 0;
                phase_ = Phase::ASCENDING;
                RCLCPP_INFO(
                    node_.get_logger(),
                    "ARM confirmed | ascending");
                break;
            }

            if (!state_.offboard)
            {
                fail_takeoff("PX4 left OFFBOARD while waiting for ARM");
                break;
            }

            if (!state_.preflight_ready)
            {
                phase_cycles_ = 0;
                phase_ = Phase::WAIT_PREFLIGHT;
                RCLCPP_WARN(
                    node_.get_logger(),
                    "ARM paused | PX4 preflight checks are not ready");
                break;
            }

            phase_cycles_++;

            if (phase_cycles_ >= RETRY_CYCLES)
            {
                phase_cycles_ = 0;

                if (arm_attempts_ >= MAX_REQUEST_ATTEMPTS)
                {
                    fail_takeoff("PX4 did not ARM after 5 attempts");
                    break;
                }

                arm_attempts_++;
                request_arm();
            }
            break;
        }

        case Phase::ASCENDING:
        {
            if (!state_.armed || !state_.offboard)
            {
                fail_takeoff("PX4 left the armed OFFBOARD state during ascent");
                break;
            }

            const float altitude_error =
                std::abs(target_z_ - state_.current_z);

            if (altitude_error < ALTITUDE_TOLERANCE_M)
            {
                phase_ = Phase::HOVER;
                RCLCPP_INFO(
                    node_.get_logger(),
                    "takeoff complete | hovering at %.2f m",
                    state_.takeoff_altitude_m);
            }
            break;
        }

        case Phase::HOVER:
        {
            if (!state_.armed || !state_.offboard)
            {
                fail_takeoff("PX4 left the armed OFFBOARD state while hovering");
            }
            break;
        }

        case Phase::FAILED:
            break;
    }
}

void OffboardController::publish_stream(uint64_t timestamp)
{
    float x = hold_x_;
    float y = hold_y_;
    float z = hold_z_;

    if (phase_ == Phase::ASCENDING || phase_ == Phase::HOVER)
    {
        z = target_z_;
    }
    else if (phase_ == Phase::FAILED &&
             state_.armed &&
             state_.position_valid)
    {
        x = state_.current_x;
        y = state_.current_y;
        z = state_.current_z;
    }

    publisher_.publish_offboard_heartbeat(timestamp);
    publisher_.publish_hold_position(
        timestamp,
        x,
        y,
        z,
        hold_yaw_);
}

void OffboardController::request_offboard_mode()
{
    publisher_.publish_vehicle_command(
        now_us(),
        px4_msgs::msg::VehicleCommand::VEHICLE_CMD_DO_SET_MODE,
        1.0f,
        6.0f);

    RCLCPP_INFO(node_.get_logger(), "OFFBOARD mode requested");
}

void OffboardController::request_arm()
{
    publisher_.publish_vehicle_command(
        now_us(),
        px4_msgs::msg::VehicleCommand::VEHICLE_CMD_COMPONENT_ARM_DISARM,
        1.0f,
        0.0f);

    RCLCPP_INFO(
        node_.get_logger(),
        "ARM requested | attempt %u/%u",
        arm_attempts_,
        MAX_REQUEST_ATTEMPTS);
}

void OffboardController::fail_takeoff(const char *reason)
{
    if (phase_ == Phase::FAILED)
    {
        return;
    }

    phase_ = Phase::FAILED;
    RCLCPP_ERROR(
        node_.get_logger(),
        "takeoff failed | %s | run ./drone why",
        reason);
}
