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
        auto qos = rclcpp::SensorDataQoS();

        camera_sub_ = create_subscription<sensor_msgs::msg::Image>(
            camera::IMAGE_TOPIC,
            qos,
            [this](sensor_msgs::msg::Image::SharedPtr msg)
            {
                camera_callback(msg);
            });

        cv::namedWindow("Drone Camera", cv::WINDOW_NORMAL);
        RCLCPP_INFO(get_logger(), "camera started | topic: %s", camera::IMAGE_TOPIC);
    }

    ~CameraNode() override
    {
        cv::destroyAllWindows();
    }

private:
    rclcpp::Subscription<sensor_msgs::msg::Image>::SharedPtr camera_sub_;

    void camera_callback(const sensor_msgs::msg::Image::SharedPtr msg)
    {
        try
        {
            cv_bridge::CvImageConstPtr cv_image = cv_bridge::toCvShare(
                msg,
                sensor_msgs::image_encodings::BGR8);

            const cv::Mat &frame = cv_image->image;
            cv::imshow("Drone Camera", frame);
            cv::waitKey(1);
        }
        catch (const cv_bridge::Exception &error)
        {
            RCLCPP_ERROR(
                get_logger(),
                "cv_bridge error: %s",
                error.what());
        }
    }
};

std::shared_ptr<rclcpp::Node> make_camera_node()
{
    return std::make_shared<CameraNode>();
}
