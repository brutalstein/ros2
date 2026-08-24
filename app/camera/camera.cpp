#include <memory>

#include "camera/camera.hpp"
#include "constants/camera.hpp"
#include "cv_bridge/cv_bridge.hpp"
#include "sensor_msgs/image_encodings.hpp"
#include "sensor_msgs/msg/image.hpp"

#include <opencv2/core.hpp>
#include <opencv2/highgui.hpp>

class CameraNode final : public rclcpp::Node
{
public:
    CameraNode()
        : rclcpp::Node("camera")
    {
        const auto qos = rclcpp::SensorDataQoS();

        camera_sub_ = create_subscription<sensor_msgs::msg::Image>(
            camera::IMAGE_TOPIC,
            qos,
            [this](sensor_msgs::msg::Image::ConstSharedPtr msg)
            {
                show_frame(msg);
            });

        cv::namedWindow(WINDOW_NAME, cv::WINDOW_NORMAL);
        RCLCPP_INFO(get_logger(), "camera ready | %s", camera::IMAGE_TOPIC);
    }

    ~CameraNode() override
    {
        cv::destroyWindow(WINDOW_NAME);
    }

private:
    static constexpr const char *WINDOW_NAME = "Drone Camera";

    rclcpp::Subscription<sensor_msgs::msg::Image>::SharedPtr camera_sub_;

    void show_frame(const sensor_msgs::msg::Image::ConstSharedPtr &msg)
    {
        try
        {
            const auto image = cv_bridge::toCvShare(
                msg,
                sensor_msgs::image_encodings::BGR8);

            cv::imshow(WINDOW_NAME, image->image);
            cv::waitKey(1);
        }
        catch (const cv_bridge::Exception &error)
        {
            RCLCPP_ERROR(get_logger(), "cv_bridge: %s", error.what());
        }
    }
};

std::shared_ptr<rclcpp::Node> make_camera_node()
{
    return std::make_shared<CameraNode>();
}
