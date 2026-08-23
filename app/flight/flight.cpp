#include <chrono>
#include <cmath>
#include <limits>
#include <memory>

#include "flight/flight.hpp"
#include "constants/topics.hpp"
#include "px4_msgs/msg/offboard_control_mode.hpp"
#include "px4_msgs/msg/trajectory_setpoint.hpp"
#include "px4_msgs/msg/vehicle_command.hpp"
#include "px4_msgs/msg/vehicle_local_position.hpp"
#include "px4_msgs/msg/vehicle_status.hpp"

using namespace std::chrono_literals;

class FlightNode final : public rclcpp::Node
{
public:
    FlightNode()
        : rclcpp::Node("flight")
    {
        auto_takeoff_ = declare_parameter<bool>("auto_takeoff", true);
        takeoff_altitude_m_ = declare_parameter<double>("takeoff_altitude_m", 3.0);

        offboard_pub_ = create_publisher<px4_msgs::msg::OffboardControlMode>(
            topics::PX4_OFFBOARD_CONTROL_MODE,
            10);

        trajectory_pub_ = create_publisher<px4_msgs::msg::TrajectorySetpoint>(
            topics::PX4_TRAJECTORY_SETPOINT,
            10);

        command_pub_ = create_publisher<px4_msgs::msg::VehicleCommand>(
            topics::PX4_VEHICLE_COMMAND,
            10);

        auto sensor_qos = rclcpp::SensorDataQoS();

        status_sub_ = create_subscription<px4_msgs::msg::VehicleStatus>(
            topics::PX4_VEHICLE_STATUS,
            sensor_qos,
            [this](px4_msgs::msg::VehicleStatus::SharedPtr msg)
            {
                latest_status_ = *msg;
                have_status_ = true;
            });

        position_sub_ = create_subscription<px4_msgs::msg::VehicleLocalPosition>(
            topics::PX4_LOCAL_POSITION,
            sensor_qos,
            [this](px4_msgs::msg::VehicleLocalPosition::SharedPtr msg)
            {
                latest_position_ = *msg;
                have_position_ = msg->xy_valid && msg->z_valid;
            });

        timer_ = create_wall_timer(100ms, [this]() { control_loop(); });

        RCLCPP_INFO(
            get_logger(),
            "flight started | auto_takeoff=%s | target_altitude=%.1f m",
            auto_takeoff_ ? "true" : "false",
            takeoff_altitude_m_);
    }

private:
    enum class Phase
    {
        WAITING_FOR_READY,
        PRIMING_OFFBOARD,
        WAITING_FOR_ARM_AND_MODE,
        TAKEOFF,
        HOVER
    };

    rclcpp::Publisher<px4_msgs::msg::OffboardControlMode>::SharedPtr offboard_pub_;
    rclcpp::Publisher<px4_msgs::msg::TrajectorySetpoint>::SharedPtr trajectory_pub_;
    rclcpp::Publisher<px4_msgs::msg::VehicleCommand>::SharedPtr command_pub_;

    rclcpp::Subscription<px4_msgs::msg::VehicleStatus>::SharedPtr status_sub_;
    rclcpp::Subscription<px4_msgs::msg::VehicleLocalPosition>::SharedPtr position_sub_;
    rclcpp::TimerBase::SharedPtr timer_;

    px4_msgs::msg::VehicleStatus latest_status_{};
    px4_msgs::msg::VehicleLocalPosition latest_position_{};

    Phase phase_{Phase::WAITING_FOR_READY};
    bool auto_takeoff_{true};
    bool have_status_{false};
    bool have_position_{false};
    bool origin_captured_{false};

    double takeoff_altitude_m_{3.0};
    float origin_x_{0.0F};
    float origin_y_{0.0F};
    float origin_z_{0.0F};
    float origin_yaw_{0.0F};

    int prime_cycles_{0};
    int retry_cycles_{0};

    static constexpr int PRIME_CYCLES_REQUIRED = 20; // 2 seconds at 10 Hz.
    static constexpr int COMMAND_RETRY_CYCLES = 10;  // Retry once per second.

    uint64_t timestamp_us() const
    {
        return static_cast<uint64_t>(get_clock()->now().nanoseconds() / 1000);
    }

    void capture_origin()
    {
        origin_x_ = latest_position_.x;
        origin_y_ = latest_position_.y;
        origin_z_ = latest_position_.z;
        origin_yaw_ = std::isfinite(latest_position_.heading) ? latest_position_.heading : 0.0F;
        origin_captured_ = true;

        RCLCPP_INFO(
            get_logger(),
            "takeoff origin captured | x=%.2f y=%.2f z=%.2f | target=%.2f m AGL",
            origin_x_,
            origin_y_,
            origin_z_,
            takeoff_altitude_m_);
    }

    void publish_offboard_control_mode()
    {
        px4_msgs::msg::OffboardControlMode msg{};
        msg.position = true;
        msg.velocity = false;
        msg.acceleration = false;
        msg.attitude = false;
        msg.body_rate = false;
        msg.thrust_and_torque = false;
        msg.direct_actuator = false;
        msg.timestamp = timestamp_us();
        offboard_pub_->publish(msg);
    }

    void publish_position_setpoint(float target_z)
    {
        const float nan = std::numeric_limits<float>::quiet_NaN();

        px4_msgs::msg::TrajectorySetpoint msg{};
        msg.position = {origin_x_, origin_y_, target_z};
        msg.velocity = {nan, nan, nan};
        msg.acceleration = {nan, nan, nan};
        msg.jerk = {nan, nan, nan};
        msg.yaw = origin_yaw_;
        msg.yawspeed = nan;
        msg.timestamp = timestamp_us();
        trajectory_pub_->publish(msg);
    }

    void publish_vehicle_command(uint16_t command, float param1 = 0.0F, float param2 = 0.0F)
    {
        px4_msgs::msg::VehicleCommand msg{};
        msg.param1 = param1;
        msg.param2 = param2;
        msg.command = command;
        msg.target_system = latest_status_.system_id == 0 ? 1 : latest_status_.system_id;
        msg.target_component = latest_status_.component_id == 0 ? 1 : latest_status_.component_id;
        msg.source_system = 1;
        msg.source_component = 1;
        msg.from_external = true;
        msg.timestamp = timestamp_us();
        command_pub_->publish(msg);
    }

    void request_offboard_and_arm()
    {
        publish_vehicle_command(
            px4_msgs::msg::VehicleCommand::VEHICLE_CMD_DO_SET_MODE,
            1.0F,
            6.0F);

        publish_vehicle_command(
            px4_msgs::msg::VehicleCommand::VEHICLE_CMD_COMPONENT_ARM_DISARM,
            1.0F);

        RCLCPP_INFO(get_logger(), "requested OFFBOARD mode + arm");
    }

    bool armed() const
    {
        return latest_status_.arming_state ==
               px4_msgs::msg::VehicleStatus::ARMING_STATE_ARMED;
    }

    bool offboard() const
    {
        return latest_status_.nav_state ==
               px4_msgs::msg::VehicleStatus::NAVIGATION_STATE_OFFBOARD;
    }

    void control_loop()
    {
        if (!auto_takeoff_)
        {
            return;
        }

        if (!have_status_ || !have_position_)
        {
            RCLCPP_INFO_THROTTLE(
                get_logger(),
                *get_clock(),
                2000,
                "waiting for PX4 vehicle status + valid local position");
            return;
        }

        if (latest_status_.failsafe)
        {
            RCLCPP_ERROR_THROTTLE(
                get_logger(),
                *get_clock(),
                2000,
                "PX4 is in failsafe; takeoff sequence is paused");
            return;
        }

        if (phase_ == Phase::WAITING_FOR_READY)
        {
            if (!latest_status_.pre_flight_checks_pass)
            {
                RCLCPP_INFO_THROTTLE(
                    get_logger(),
                    *get_clock(),
                    2000,
                    "waiting for PX4 preflight checks before arming");
                return;
            }

            if (!origin_captured_)
            {
                capture_origin();
            }

            prime_cycles_ = 0;
            phase_ = Phase::PRIMING_OFFBOARD;
            RCLCPP_INFO(get_logger(), "priming offboard heartbeat/setpoint stream");
        }

        const float takeoff_target_z =
            origin_z_ - static_cast<float>(takeoff_altitude_m_);

        publish_offboard_control_mode();

        if (phase_ == Phase::PRIMING_OFFBOARD)
        {
            publish_position_setpoint(origin_z_);
            ++prime_cycles_;

            if (prime_cycles_ >= PRIME_CYCLES_REQUIRED)
            {
                request_offboard_and_arm();
                retry_cycles_ = 0;
                phase_ = Phase::WAITING_FOR_ARM_AND_MODE;
            }
            return;
        }

        publish_position_setpoint(takeoff_target_z);

        if (phase_ == Phase::WAITING_FOR_ARM_AND_MODE)
        {
            if (armed() && offboard())
            {
                phase_ = Phase::TAKEOFF;
                RCLCPP_INFO(get_logger(), "armed in OFFBOARD; climbing to %.1f m", takeoff_altitude_m_);
                return;
            }

            ++retry_cycles_;
            if (retry_cycles_ >= COMMAND_RETRY_CYCLES)
            {
                request_offboard_and_arm();
                retry_cycles_ = 0;
            }
            return;
        }

        if (phase_ == Phase::TAKEOFF)
        {
            const float climbed_m = origin_z_ - latest_position_.z;

            RCLCPP_INFO_THROTTLE(
                get_logger(),
                *get_clock(),
                1000,
                "TAKEOFF | altitude: %.2f / %.2f m",
                climbed_m,
                takeoff_altitude_m_);

            if (climbed_m >= static_cast<float>(takeoff_altitude_m_ - 0.25))
            {
                phase_ = Phase::HOVER;
                RCLCPP_INFO(get_logger(), "takeoff complete; holding %.1f m", takeoff_altitude_m_);
            }
            return;
        }

        if (phase_ == Phase::HOVER)
        {
            RCLCPP_INFO_THROTTLE(
                get_logger(),
                *get_clock(),
                3000,
                "HOVER | target altitude: %.1f m",
                takeoff_altitude_m_);
        }
    }
};

std::shared_ptr<rclcpp::Node> make_flight_node()
{
    return std::make_shared<FlightNode>();
}
