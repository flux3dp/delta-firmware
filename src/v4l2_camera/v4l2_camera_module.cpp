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
#include "v4l2_camera_module.h"

static int xioctl(int fd, int request, void *arg)
{
        int r;

        do r = ioctl (fd, request, arg);
        while (-1 == r && EINTR == errno);

        return r;
}

// int print_caps(int fd)
// {
//     struct v4l2_capability caps = {};
//     if (-1 == xioctl(fd, VIDIOC_QUERYCAP, &caps))
//     {
//             perror("Querying Capabilities");
//             return 1;
//     }

//     printf( "Driver Caps:\n"
//             "  Driver: \"%s\"\n"
//             "  Card: \"%s\"\n"
//             "  Bus: \"%s\"\n"
//             "  Version: %d.%d\n"
//             "  Capabilities: %08x\n",
//             caps.driver,
//             caps.card,
//             caps.bus_info,
//             (caps.version>>16)&&0xff,
//             (caps.version>>24)&&0xff,
//             caps.capabilities);


//     struct v4l2_cropcap cropcap;
//     cropcap.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
//     if (-1 == xioctl (fd, VIDIOC_CROPCAP, &cropcap))
//     {
//             perror("Querying Cropping Capabilities");
//             return 1;
//     }

//     printf( "Camera Cropping:\n"
//             "  Bounds: %dx%d+%d+%d\n"
//             "  Default: %dx%d+%d+%d\n"
//             "  Aspect: %d/%d\n",
//             cropcap.bounds.width, cropcap.bounds.height, cropcap.bounds.left, cropcap.bounds.top,
//             cropcap.defrect.width, cropcap.defrect.height, cropcap.defrect.left, cropcap.defrect.top,
//             cropcap.pixelaspect.numerator, cropcap.pixelaspect.denominator);

//     int support_grbg10 = 0;

//     struct v4l2_fmtdesc fmtdesc = {0};
//     fmtdesc.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
//     char fourcc[5] = {0};
//     char c, e;
//     printf("  FMT : CE Desc\n--------------------\n");
//     while (0 == xioctl(fd, VIDIOC_ENUM_FMT, &fmtdesc))
//     {
//             strncpy(fourcc, (char *)&fmtdesc.pixelformat, 4);
//             if (fmtdesc.pixelformat == V4L2_PIX_FMT_SGRBG10)
//                 support_grbg10 = 1;
//             c = fmtdesc.flags & 1? 'C' : ' ';
//             e = fmtdesc.flags & 2? 'E' : ' ';
//             printf("  %s: %c%c %s\n", fourcc, c, e, fmtdesc.description);
//             fmtdesc.index++;
//     }
//     /*
//     if (!support_grbg10)
//     {
//         printf("Doesn't support GRBG10.\n");
//         return 1;
//     }*/

//     struct v4l2_format fmt;
//     fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
//     fmt.fmt.pix.width = 640;
//     fmt.fmt.pix.height = 480;
//     //fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_BGR24;
//     //fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_GREY;
//     fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_MJPEG;
//     fmt.fmt.pix.field = V4L2_FIELD_NONE;

//     if (-1 == xioctl(fd, VIDIOC_S_FMT, &fmt))
//     {
//         perror("Setting Pixel Format");
//         return 1;
//     }

//     strncpy(fourcc, (char *)&fmt.fmt.pix.pixelformat, 4);
//     printf( "Selected Camera Mode:\n"
//             "  Width: %d\n"
//             "  Height: %d\n"
//             "  PixFmt~: %s\n"
//             "  Field: %d\n",
//             fmt.fmt.pix.width,
//             fmt.fmt.pix.height,
//             fourcc,
//             fmt.fmt.pix.field);
//     return 0;
// }

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

    // printf("Length: %d\nAddress: %p\n", buf.length, buffer);
    // printf("Image Length: %d\n", buf.bytesused);

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
    printf ("%d\n", buf.bytesused);

    // storing
    int jpgfile;
    if((jpgfile = open("tmp_image2.jpeg", O_WRONLY | O_CREAT, 0660)) < 0){
        perror("open");
        // exit(1);
        return 1;
    }

    write(jpgfile, buffer, buf.bytesused);
    close(jpgfile);

    return buf.bytesused;
}

int attach_camera(int video_name, unsigned char*& buffer){
    int fd;
    char a[20] = "/dev/video";
    // itoa(video_name, a[10], 10);
    snprintf(&a[10], 10, "%d", video_name);
    fd = open(a, O_RDWR);

    if (fd == -1){
        perror("Opening video device");
        return 1;
    }

    //setting
    struct v4l2_format fmt;
    fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    fmt.fmt.pix.width = 640;
    fmt.fmt.pix.height = 480;
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
    printf("%d\n", buf.length);
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
    int fd = attach_camera(0, buffer);
    printf("Address 1: %p %d\n", buffer, fd);
    // if(print_caps(fd))  // you can just use "v4l2-ctl --list-formats-ext" to checkout properties
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
    fd = attach_camera(0, buffer);
    printf("Address 2: %p %d\n", buffer, fd);
    for(i=0; i<atoi(argv[1]); i++)
    {
      capture_image(fd, buffer);
    }

    return 0;
}
