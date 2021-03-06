
#include<math.h>
#include<Python.h>

#define MAIN_MESSAGE 1
#define HEAD_MESSAGE 2
#define BLOCK_HEAD_MESSAGE 4
#define PAUSE_MESSAGE 8


typedef void (*command_cb_t)(const char* command, int target, void* data);


struct DeviceFSM {
  double traveled;
  float min_z, max_z, max_r2;
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
    void set_max_exec_time(double);
    struct DeviceFSM fsm;

private:
    int G1(command_cb_t callback, void* data, unsigned short f=0, 
           float x=NAN, float y=NAN, float z=NAN, float e=NAN);
    char _proc_buf[256];
    double max_exec_time;
};
