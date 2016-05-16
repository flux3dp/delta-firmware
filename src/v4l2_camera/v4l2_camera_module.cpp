
#include "v4l2_camera_module.h"

#ifdef __linux__

#include <errno.h>
#include <fcntl.h>
#include <linux/videodev2.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>
#include <stdlib.h>
#include <typeinfo>

static int xioctl(int fd, int request, void *arg)
{
        int r;

        do r = ioctl (fd, request, arg);
        while (-1 == r && EINTR == errno);

        return r;
}

int init_mmap(int fd, unsigned char* &buffer)
{
    struct v4l2_requestbuffers req = {0};
    req.count = 1;
    req.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    req.memory = V4L2_MEMORY_MMAP;

    if (-1 == xioctl(fd, VIDIOC_REQBUFS, &req))
    {
        perror("Requesting Buffer");
        return 1;
    }

    struct v4l2_buffer buf = {0};
    buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    buf.memory = V4L2_MEMORY_MMAP;
    buf.index = 0;
    if(-1 == xioctl(fd, VIDIOC_QUERYBUF, &buf))
    {
        perror("Querying Buffer");
        return 1;
    }

    buffer =  static_cast<unsigned char *>(mmap (NULL, buf.length, PROT_READ | PROT_WRITE, MAP_SHARED, fd,  buf.m.offset));

    return 0;
}

int capture_image(int fd, unsigned char* &buffer){
    struct v4l2_buffer buf = {0};
    buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    buf.memory = V4L2_MEMORY_MMAP;
    buf.index = 0;
    if(-1 == xioctl(fd, VIDIOC_QBUF, &buf))
    {
        perror("Query Buffer");
        return 1;
    }

    if(-1 == xioctl(fd, VIDIOC_STREAMON, &buf.type))
    {
        perror("Start Capture");
        return 1;
    }

    fd_set fds;
    FD_ZERO(&fds);
    FD_SET(fd, &fds);
    struct timeval tv = {0};
    tv.tv_sec = 2;
    int r = select(fd+1, &fds, NULL, NULL, &tv);
    if(-1 == r)
    {
        perror("Waiting for Frame");
        return 1;
    }

    if(-1 == xioctl(fd, VIDIOC_DQBUF, &buf))
    {
        perror("Retrieving Frame");
        return 1;
    }
    // printf ("%d\n", buf.bytesused);

    // storing
    // int jpgfile;
    // if((jpgfile = open("tmp_image2.jpeg", O_WRONLY | O_CREAT, 0660)) < 0){
    //     perror("open");
    //     // exit(1);
    //     return 1;
    // }

    // write(jpgfile, buffer, buf.bytesused);
    // close(jpgfile);

    return buf.bytesused;
}

int attach_camera(int video_name, unsigned char*& buffer, int width, int height){
    int fd;
    char a[20] = "/dev/video";
    // itoa(video_name, a[10], 10);
    snprintf(&a[10], 10, "%d", video_name);
    fd = open(a, O_RDWR);

    if (fd == -1){
        perror("Opening video device");
        return 1;
    }

    //setting: you can use "v4l2-ctl --list-formats-ext" to checkout properties
    struct v4l2_format fmt;
    fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    fmt.fmt.pix.width = width;
    fmt.fmt.pix.height = height;
    fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_MJPEG;
    fmt.fmt.pix.field = V4L2_FIELD_NONE;

    if (-1 == xioctl(fd, VIDIOC_S_FMT, &fmt))
    {
        perror("Setting Pixel Format");
        return 1;
    }

    if(init_mmap(fd, buffer))
        return -1;

    return fd;
}

int release_camera(int fd, unsigned char*& buffer){
    // int type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    // if(xioctl(fd, VIDIOC_STREAMOFF, &type) < 0){
    //     perror("VIDIOC_STREAMOFF");
    //     return 1;
    // }
    struct v4l2_buffer buf = {0};
    buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    buf.memory = V4L2_MEMORY_MMAP;
    if(-1 == xioctl(fd, VIDIOC_QUERYBUF, &buf))
    {
        perror("Querying Buffer");
        return 1;
    }
    if(-1 == munmap((void *)buffer, buf.length)){
      perror("munmap error");
    }
    close(fd);
    return 0;
}

int main(int argc, char* argv[]){
    uint8_t *buffer;
    // char a[] = "/dev/video0";
    int fd = attach_camera(0, buffer, 800, 600);
    printf("Address 1: %p %d\n", buffer, fd);
    // if(print_caps(fd))
    //     return 1;

    // for (size_t i = 0; i < 1800; i += 1){
    //     printf("%s\n", "QAQ.........");
    // }

    int i;
    for(i=0; i<atoi(argv[1]); i++)
    {
      capture_image(fd, buffer);
    }
    release_camera(fd, buffer);
    fd = attach_camera(0, buffer, 800, 600);
    printf("Address 2: %p %d\n", buffer, fd);
    for(i=0; i<atoi(argv[1]); i++)
    {
      capture_image(fd, buffer);
    }

    return 0;
}

#endif
