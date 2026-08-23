#include <chrono>

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
    control_timer_ =
        node_.create_wall_timer(
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
    if (!state_.hold_position_ready)
    {
        return;
    }

    const uint64_t timestamp = now_us();

    publisher_.publish_offboard_heartbeat(timestamp);

    publisher_.publish_hold_position(
        timestamp,
        state_.hold_x,
        state_.hold_y,
        state_.hold_z,
        state_.hold_yaw);

    if (state_.warmup_cycles < OFFBOARD_WARMUP_CYCLES)
    {
        state_.warmup_cycles++;
        return;
    }

    if (!state_.vehicle_status_received)
    {
        return;
    }

    if (state_.failsafe)
    {
        RCLCPP_WARN_THROTTLE(
            node_.get_logger(),
            *node_.get_clock(),
            2000,
            "OFFBOARD request blocked: PX4 failsafe active");

        return;
    }

    if (state_.offboard_confirmed)
    {
        return;
    }

    if (!state_.offboard_request_sent)
    {
        request_offboard_mode();
        state_.offboard_request_sent = true;
    }
}

void OffboardController::request_offboard_mode()
{
    publisher_.publish_vehicle_command(
        now_us(),
        px4_msgs::msg::VehicleCommand::VEHICLE_CMD_DO_SET_MODE,
        1.0f,
        6.0f);

    RCLCPP_INFO(
        node_.get_logger(),
        "OFFBOARD mode requested");
}
