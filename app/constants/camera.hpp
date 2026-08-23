#pragma once

namespace camera
{
    // ROS tarafında kullanacağımız görüntü kanalı
    inline constexpr const char IMAGE_TOPIC[] =
        "/camera/image_raw";

    inline constexpr const char FRAME_ID[] =
        "camera_optical_frame";

    // Görüntü
    inline constexpr int WIDTH = 1280;
    inline constexpr int HEIGHT = 720;
    inline constexpr int FPS = 30;

    // 90 derece yatay görüş açısı
    inline constexpr double HFOV_RAD = 1.57079632679;

    // Drone gövdesine göre hedeflediğimiz kamera konumu.
    // x: ileri, y: yan, z: düşey offset.
    inline constexpr double MOUNT_X_M = 0.15;
    inline constexpr double MOUNT_Y_M = 0.0;
    inline constexpr double MOUNT_Z_M = -0.08;

    // Kamerayı yaklaşık 28 derece aşağı eğmek istiyoruz.
    inline constexpr double PITCH_DOWN_DEG = 28.0;

    // Kamera render mesafesi
    inline constexpr double NEAR_CLIP_M = 0.10;
    inline constexpr double FAR_CLIP_M = 200.0;
}