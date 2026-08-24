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
    if (!state_.takeoff_requested) return;
    if (!state_.position_valid) return;
    if (!state_.vehicle_status_received) return;

    if (state_.failsafe)
    {
        RCLCPP_WARN_THROTTLE(
            node_.get_logger(),
            *node_.get_clock(),
            2000,
            "takeoff blocked: PX4 failsafe active");

        return;
    }

    const uint64_t timestamp = now_us();

    switch (state_.phase)
    {
        case FlightPhase::IDLE:
        {
            state_.start_x = state_.current_x;
            state_.start_y = state_.current_y;
            state_.start_z = state_.current_z;

            state_.target_z =
                state_.start_z -
                state_.takeoff_altitude_m;

            state_.warmup_cycles = 0;

            state_.phase =
                FlightPhase::OFFBOARD_WARMUP;

            RCLCPP_INFO(
                node_.get_logger(),
                "takeoff prepared | altitude: %.2f m | target z: %.2f",
                state_.takeoff_altitude_m,
                state_.target_z);

            break;
        }

        case FlightPhase::OFFBOARD_WARMUP:
        {
            publisher_.publish_offboard_heartbeat(
                timestamp);

            publisher_.publish_hold_position(
                timestamp,
                state_.start_x,
                state_.start_y,
                state_.start_z,
                state_.yaw);

            state_.warmup_cycles++;

            if (state_.warmup_cycles >=
                OFFBOARD_WARMUP_CYCLES)
            {
                request_offboard_mode();

                state_.offboard_request_sent = true;

                state_.phase =
                    FlightPhase::WAIT_OFFBOARD;
            }
            break;
        }
        case FlightPhase::WAIT_OFFBOARD:
        {
            publisher_.publish_offboard_heartbeat(
                timestamp);

            publisher_.publish_hold_position(
                timestamp,
                state_.start_x,
                state_.start_y,
                state_.start_z,
                state_.yaw);

            if (state_.offboard_confirmed)
            {
                if (!state_.arm_request_sent)
                {
                    request_arm();

                    state_.arm_request_sent = true;
                }
                state_.phase =
                    FlightPhase::WAIT_ARM;
            }
            break;
        }
        case FlightPhase::WAIT_ARM:
        {
            publisher_.publish_offboard_heartbeat(
                timestamp);

            publisher_.publish_hold_position(
                timestamp,
                state_.start_x,
                state_.start_y,
                state_.start_z,
                state_.yaw);
            if (state_.armed)
            {
                state_.phase =
                    FlightPhase::ASCENDING;

                RCLCPP_INFO(
                    node_.get_logger(),
                    "ARM confirmed | starting ascent");
            }
            break;
        }
        case FlightPhase::ASCENDING:
        {
            publisher_.publish_offboard_heartbeat(
                timestamp);

            publisher_.publish_hold_position(
                timestamp,
                state_.start_x,
                state_.start_y,
                state_.target_z,
                state_.yaw);
            const float altitude_error =
                state_.target_z -
                state_.current_z;
            if (std::abs(altitude_error) < 0.15f)
            {
                state_.phase =
                    FlightPhase::HOVER;

                RCLCPP_INFO(
                    node_.get_logger(),
                    "takeoff complete | hovering");
            }
            break;
        }
        case FlightPhase::HOVER:
        {
            publisher_.publish_offboard_heartbeat(
                timestamp);

            publisher_.publish_hold_position(
                timestamp,
                state_.start_x,
                state_.start_y,
                state_.target_z,
                state_.yaw);
            break;
        }
    }
}
void OffboardController::request_offboard_mode()
{
    publisher_.publish_vehicle_command(
        now_us(),
        px4_msgs::msg::VehicleCommand::
            VEHICLE_CMD_DO_SET_MODE,
        1.0f,
        6.0f);
    RCLCPP_INFO(
        node_.get_logger(),
        "OFFBOARD mode requested");
}
void OffboardController::request_arm()
{
    publisher_.publish_vehicle_command(
        now_us(),
        px4_msgs::msg::VehicleCommand::
            VEHICLE_CMD_COMPONENT_ARM_DISARM,
        1.0f,
        0.0f);
    RCLCPP_INFO(
        node_.get_logger(),
        "ARM requested");
}