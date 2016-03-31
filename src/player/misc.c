
#include "Python.h"

inline PyObject* create_cmd(int lineno, const char* cmd) {
    int i, size;
    int offset = 0;
    int sumcheck = 0;
    char buf[256];
    char byte = cmd[0];

    while(offset < 256 && byte != 0) {
        buf[offset] = byte;
        sumcheck ^= byte;
        offset += 1;
        byte = cmd[offset];
    }

    size = snprintf((char *)buf + offset, 256 - offset, " N%i", lineno);
    size = offset + size;

    for(i=offset;i<size;i++) {
        sumcheck ^= buf[i];
        offset += 1;
    }

    size = snprintf((char *)buf + offset, 256 - offset, "*%i\n", sumcheck);
    return PyString_FromStringAndSize(buf, offset + size);
}
