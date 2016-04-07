int attach_camera(int video_name, unsigned char*& buffer);
int release_camera(int fd, unsigned char*& buffer);
int capture_image(int fd, unsigned char* &buffer);
