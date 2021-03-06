
#include <cmath>
#include "device_fsm.h"

#define POSITION_ERROR -1
#define IO_ERROR -2
#define MULTI_E_ERROR -3

#define MACRO_READ(fd, ptr, size) \
  if(read(fd, ptr, size) != size) { \
    return IO_ERROR; \
  } else { \
    l += size; \
  } \


DeviceController::DeviceController() {
  fsm.traveled = 0;
  fsm.x = fsm.y = fsm.z = NAN;
  fsm.e[0] = fsm.e[1] = fsm.e[2] = 0;
  fsm.f = 3000;
  fsm.t = 0;
  fsm.absolute_pos = 1;
}

DeviceController::DeviceController(float _x, float _y, float _z, float e1, float e2, float e3, int _f, int _t) {
  fsm.traveled = 0;
  fsm.x = _x; fsm.y = _y; fsm.z = _z;
  fsm.e[0] = e1; fsm.e[1] = e2; fsm.e[2] = e3;
  fsm.f = _f; fsm.t = _t;
  max_exec_time = 1;
}

void DeviceController::set_max_exec_time(double t) {
  max_exec_time = t;
}

int DeviceController::feed(int fd, command_cb_t callback, void* data) {
  char cmd;
  ssize_t l = read(fd, &cmd, 1);

  if(l==0) {
    return 0;
  }

  if(cmd & 128) {
    // G1
    float f = 0,
          r = 0,
          x = NAN,
          y = NAN,
          z = NAN,
          e[3] = {NAN, NAN, NAN};

    int e_counter = 0;
    int t;
    int illegal = 0;

    if(cmd & 64) { MACRO_READ(fd, &f, 4) }  // Find F
    if(cmd & 32) { // Find X
      MACRO_READ(fd, &x, 4)
      r = x * x;
    } else {
      r = fsm.x * fsm.x;
    }
    if(cmd & 16) { // Find Y
      MACRO_READ(fd, &y, 4)
      r = y * y;
    } else {
      r = fsm.y * fsm.y;
    }
    if(r > fsm.max_r2) { illegal = 1;}

    if(cmd & 8)  {  // Find Z
      MACRO_READ(fd, &z, 4)
      if(!fsm.absolute_pos) z += fsm.z;

      if(z > fsm.max_z || z < fsm.min_z) illegal = 1;
    }

    // Find E
    if(cmd & 4) {
      MACRO_READ(fd, &(e[0]), 4)
      if(!fsm.absolute_pos) e[0] += fsm.e[0];
      t = 0;
      e_counter++;
    }
    if(cmd & 2) {
      MACRO_READ(fd, &(e[1]), 4)
      if(!fsm.absolute_pos) e[1] += fsm.e[1];
      t = 1;
      e_counter++;
    }
    if(cmd & 1) {
      MACRO_READ(fd, &(e[2]), 4)
      if(!fsm.absolute_pos) e[2] += fsm.e[2];
      t = 2;
      e_counter++;
    }

    if(illegal > 0) return POSITION_ERROR;  // ERROR: Move to out of range
    if(e_counter > 1) return MULTI_E_ERROR;  // ERRROR: Can not handle multi e
    if(e_counter == 1 && fsm.t != t) {
      fsm.t = t;
      snprintf(_proc_buf, 8, "T%i", fsm.t);
      callback(_proc_buf, MAIN_MESSAGE, data);
      snprintf(_proc_buf, 32, "G92 E%.6f", fsm.e[fsm.t]);
      callback(_proc_buf, MAIN_MESSAGE, data);
      G1(callback, data, f, x, y, z, e[fsm.t]);
    } else {
      G1(callback, data, f, x, y, z, e[fsm.t]);
    }
    return l;
  } else if(cmd & 64) {
    return 1;
  } else if((cmd & 48) == 48) {
    // Fan Control
    float val;
    MACRO_READ(fd, &val, 4)
    snprintf(_proc_buf, 32, "F%i%.4f", 0, val);
    callback(_proc_buf, HEAD_MESSAGE, data);
    return l;

  } else if(cmd & 32) {
    // Laser Control
    float val;
    MACRO_READ(fd, &val, 4)
    snprintf(_proc_buf, 32, "X2O%i", (int)(val * 255));
    callback(_proc_buf, MAIN_MESSAGE, data);
    return l;
  } else if(cmd & 16) {
    // Heater Control
    float val;
    MACRO_READ(fd, &val, 4)
    snprintf(_proc_buf, 32, "H%i%.1f", cmd & 7, val);

    int block = cmd & 8;
    callback(_proc_buf, (block ? BLOCK_HEAD_MESSAGE : HEAD_MESSAGE), data);
    return l;
  } else if(cmd == 7) {
    // Pause with height
    float val;
    MACRO_READ(fd, &val, 4)
    snprintf(_proc_buf, 32, "Z%.4f", val);
    callback(_proc_buf, PAUSE_MESSAGE, data);
    return 1;
  } else if(cmd == 6) {
    // Pause with height
    callback("Z0", PAUSE_MESSAGE, data);
    return 1;
  } else if(cmd == 5) {
    callback("Z25", PAUSE_MESSAGE, data);
    return 1;
  } else if(cmd & 4) {
    // Sleep (G4)
    float val;
    MACRO_READ(fd, &val, 4)
    snprintf(_proc_buf, 32, "G4 P%i", (int)val);
    callback(_proc_buf, MAIN_MESSAGE, data);
    return l;
  } else if(cmd == 3) {
    // Relative Positioning (G91)
    fsm.absolute_pos = 0;
  } else if(cmd == 2) {
    // Absolute Positioning (G90)
    fsm.absolute_pos = 1;
  } else if(cmd == 1) {
    // Home (G28)
    callback("G28", MAIN_MESSAGE, data);
    return 1;
  } else {
    return 1;
  }
}

inline int DeviceController::G1(command_cb_t callback, void* data, unsigned short f, float x, float y, float z, float e) {
  double dx, dy, dz, de;
  double length;
  double tcost;
  double r;
  int section = 0;

  if(fsm.f == 0 && f == 0) {
    f = 3000;
  } else if(f == 0) {
    f = fsm.f;
  }

  strcpy(_proc_buf, "G1 ");

  if(!(isnan(fsm.x) && isnan(fsm.y) && isnan(fsm.z))) {
    dx = isnan(x) ? 0 : (x - fsm.x);
    dy = isnan(y) ? 0 : (y - fsm.y);
    dz = isnan(z) ? 0 : (z - fsm.z);
    de = isnan(e) ? 0 : (e - fsm.e[fsm.t]);

    length =  sqrt(dx*dx + dy*dy + dz*dz);
    if(isnan(length)) {
      fprintf(stderr, "length got nan (%f, %f, %f)\n", dx, dy, dz);
    } else {
      fsm.traveled += length;
    }

    tcost = length / f * 100;
    section = (int)(tcost / max_exec_time);
    if(section > 4096) {
      fprintf(stderr, "G1 split section over limit: %i, strict to 4096\n", section);
      section = 4096;
    }

    for(int i=1;i<section;i++) {
      char* buf_offset = _proc_buf + 3;
      r = 1.0 / section * i;

      if(f != fsm.f) {
        buf_offset += snprintf(buf_offset, 8, "F%i ", f);
        fsm.f = f;
      }

      if(dx != 0)
        buf_offset += snprintf(buf_offset, 16, "X%.6f ", fsm.x + dx * r);
      if(dy != 0)
        buf_offset += snprintf(buf_offset, 16, "Y%.6f ", fsm.y + dy * r);
      if(dz != 0)
        buf_offset += snprintf(buf_offset, 16, "Z%.6f ", fsm.z + dz * r);
      if(de != 0)
        buf_offset += snprintf(buf_offset, 16, "E%.6f ", fsm.e[fsm.t] + de * r);

      buf_offset[-1] = 0;
      callback(_proc_buf, MAIN_MESSAGE, data);
    }
  }

  // **Last command generate direct to prevent floating round error**
  char* buf_offset = _proc_buf + 3;
  if(f != fsm.f) {
    buf_offset += snprintf(buf_offset, 8, "F%i ", f);
    fsm.f = f;
  }

  if(!isnan(x)) {
    buf_offset += snprintf(buf_offset, 16, "X%.6f ", x);
    fsm.x = x;
  }

  if(!isnan(y)) {
    buf_offset += snprintf(buf_offset, 16, "Y%.6f ", y);
    fsm.y = y;
  }

  if(!isnan(z)) {
    buf_offset += snprintf(buf_offset, 16, "Z%.6f ", z);
    fsm.z = z;
  }

  if(!isnan(e)) {
    buf_offset += snprintf(buf_offset, 16, "E%.6f ", e);
    fsm.e[fsm.t] = e;
  }

  buf_offset[-1] = 0;
  callback(_proc_buf, MAIN_MESSAGE, data);
  return (section == 0) ? 1 : section;
}
