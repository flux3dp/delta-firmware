
#include<math.h>
#include<Python.h>

#define BLOCK_HEAD_MESSAGE 4
#define HEAD_MESSAGE 2
#define MAIN_MESSAGE 1

typedef void (*command_cb_t)(const char* command, int target, void* data);

struct DeviceFSM {
  double traveled;
  float x, y, z;
  float e[3];
  unsigned short f, t, absolute_pos;
};


class DeviceController { 
public: 
    DeviceController();
    DeviceController(float _x, float _y, float _z, float _e1, float _e2,
                     float _e3, int _f=6000, int _t=0);

    int feed(int fd, command_cb_t callback, void *data);
    struct DeviceFSM fsm;

private:
    int G1(command_cb_t callback, void* data, unsigned short f=0, 
           float x=NAN, float y=NAN, float z=NAN, float e=NAN);
    char _proc_buf[256];
};
