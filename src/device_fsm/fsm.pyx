
from libc.math cimport NAN, isnan, sqrt

cdef extern from "math.h":
    float INFINITY

cdef extern from "device_fsm.h":
  ctypedef void (*command_cb_t)(const char*, int, void*)

  struct DeviceFSM:
    double traveled
    float x, y, z, e[3]
    float max_x, max_y, max_z
    int f, t

  cdef cppclass DeviceController:
    DeviceController()
    DeviceFSM fsm
    int feed(int, command_cb_t, void*)
    void set_max_exec_time(double)


cdef void pycallback(const char* wow, int target, void* data):
  pyfun = <object>data
  pyfun(wow, target)


cdef class PyDeviceFSM:
  cdef DeviceController *ptr

  def __init__(self, int t=0, int f=-1, float x=NAN, float y=NAN,
               float z=NAN, float e1=NAN, float e2=NAN, float e3=NAN,
               float max_x=INFINITY, float max_y=INFINITY,
               float max_z=INFINITY):
    self.ptr.fsm.x = x
    self.ptr.fsm.y = y
    self.ptr.fsm.z = z
    self.ptr.fsm.e[0] = e1
    self.ptr.fsm.e[1] = e2
    self.ptr.fsm.e[2] = e3
    self.ptr.fsm.t = t
    self.ptr.fsm.f = f
    self.ptr.fsm.max_x = max_x
    self.ptr.fsm.max_y = max_y
    self.ptr.fsm.max_z = max_z

  def __cinit__(self):
    self.ptr = new DeviceController()

  def __dealloc__(self):
    del self.ptr

  cpdef set_max_exec_time(self, double t):
    self.ptr.set_max_exec_time(t)

  cpdef int feed(self, int fd, callback):
    return self.ptr.feed(fd, pycallback, <void*>callback)

  cpdef unsigned int get_t(self):
    return self.ptr.fsm.t

  cpdef set_t(self, unsigned int val):
    self.ptr.fsm.t = val

  cpdef unsigned int get_f(self):
    return self.ptr.fsm.f

  cpdef set_f(self, unsigned int val):
    self.ptr.fsm.f = val

  cpdef float get_x(self):
    return self.ptr.fsm.x

  cpdef set_x(self, float val):
    self.ptr.fsm.x = val

  cpdef float get_y(self):
    return self.ptr.fsm.y

  cpdef set_y(self, float val):
    self.ptr.fsm.y = val

  cpdef float get_z(self):
    return self.ptr.fsm.z

  cpdef set_z(self, float val):
    self.ptr.fsm.z = val

  cpdef float get_e(self, int index):
    if index >=0 and index <= 2:
      return self.ptr.fsm.e[index]
    return NAN

  cpdef set_e(self, int index, float val):
    if index >=0 and index <= 2:
      self.ptr.fsm.e[index] = val

  cpdef double get_traveled(self):
    return self.ptr.fsm.traveled
