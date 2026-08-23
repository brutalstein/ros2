#include <memory>

#include "sensors/sensors.hpp"
#include "constants/topics.hpp"
#include "px4_msgs/msg/sensor_combined.hpp"
#include "px4_msgs/msg/sensor_gps.hpp"

class SensorsNode final : public rclcpp::Node
{
public:
    SensorsNode()
        : rclcpp::Node("sensors")
    {
        auto qos = rclcpp::SensorDataQoS();

        imu_sub_ = create_subscription<px4_msgs::msg::SensorCombined>(
            topics::PX4_IMU_SENSOR,
            qos,
            [this](px4_msgs::msg::SensorCombined::SharedPtr msg)
            {
                imu_callback(msg);
            });

        gnss_sub_ = create_subscription<px4_msgs::msg::SensorGps>(
            topics::PX4_GNSS_SENSOR,
            qos,
            [this](px4_msgs::msg::SensorGps::SharedPtr msg)
            {
                gnss_callback(msg);
            });

        RCLCPP_INFO(get_logger(), "sensors started");
    }

private:
    rclcpp::Subscription<px4_msgs::msg::SensorCombined>::SharedPtr imu_sub_;
    rclcpp::Subscription<px4_msgs::msg::SensorGps>::SharedPtr gnss_sub_;

    void imu_callback(const px4_msgs::msg::SensorCombined::SharedPtr msg)
    {
        const float ax = msg->accelerometer_m_s2[0];
        const float ay = msg->accelerometer_m_s2[1];
        const float az = msg->accelerometer_m_s2[2];

        const float gx = msg->gyro_rad[0];
        const float gy = msg->gyro_rad[1];
        const float gz = msg->gyro_rad[2];

        RCLCPP_INFO_THROTTLE(
            get_logger(),
            *get_clock(),
            1000,
            "IMU | accel: %.2f %.2f %.2f m/s2 | gyro: %.2f %.2f %.2f rad/s",
            ax,
            ay,
            az,
            gx,
            gy,
            gz);
    }

    void gnss_callback(const px4_msgs::msg::SensorGps::SharedPtr msg)
    {
        const double latitude = msg->latitude_deg;
        const double longitude = msg->longitude_deg;
        const double altitude = msg->altitude_msl_m;

        RCLCPP_INFO_THROTTLE(
            get_logger(),
            *get_clock(),
            1000,
            "GNSS | lat: %.7f | lon: %.7f | alt: %.2f m | fix: %u | satellites: %u | eph: %.2f m | epv: %.2f m",
            latitude,
            longitude,
            altitude,
            static_cast<unsigned int>(msg->fix_type),
            static_cast<unsigned int>(msg->satellites_used),
            msg->eph,
            msg->epv);

        if (msg->vel_ned_valid)
        {
            RCLCPP_INFO_THROTTLE(
                get_logger(),
                *get_clock(),
                1000,
                "GNSS VELOCITY | N: %.2f | E: %.2f | D: %.2f m/s",
                msg->vel_n_m_s,
                msg->vel_e_m_s,
                msg->vel_d_m_s);
        }
    }
};

std::shared_ptr<rclcpp::Node> make_sensors_node()
{
    return std::make_shared<SensorsNode>();
}
