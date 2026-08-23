#include <memory>

#include "rclcpp/rclcpp.hpp"
#include "constants/camera.hpp"
#include "sensor_msgs/msg/image.hpp"
#include "sensor_msgs/image_encodings.hpp"
#include "cv_bridge/cv_bridge.hpp"

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
          [this](sensor_msgs::msg::Image::SharedPtr msg){
            camera_callback(msg);
          }
        );
        RCLCPP_INFO(get_logger(), "camera started");  
    }
    ~CameraNode(){
      cv::destroyAllWindows();
    }
private:
    rclcpp::Subscription<sensor_msgs::msg::Image>::SharedPtr camera_sub_;
    void camera_callback(const sensor_msgs::msg::Image::SharedPtr msg){
      try {
        cv_bridge::CvImageConstPtr cv_image = cv_bridge::toCvShare(
          msg, sensor_msgs::image_encodings::BGR8
        );
        const cv::Mat &frame = cv_image->image;
        cv::imshow("Drone Camera", frame);
        cv::waitKey(1);
      }
      catch(const cv_bridge::Exception &error){
         RCLCPP_ERROR(
                get_logger(),
                "cv_bridge error: %s",
                error.what()
            );
      }
    }
};

int main(int argc, char * argv[])
{
    rclcpp::init(argc, argv);
    rclcpp::spin(std::make_shared<CameraNode>());
    rclcpp::shutdown();
    return 0;
}
