
#include "libflux_hal/halprofile.h"

#ifdef FLUX_MODEL_G1

#include <Python.h>

#include <stdlib.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <sys/ioctl.h>
#include <linux/types.h>
#include <linux/spi/spidev.h>
#include "flux_identify.h"


#define SPI_PATH "/dev/spidev0.1"
#define SPI_MAX_SPEED_HZ 500000
#define SPI_BITS_PER_WORD 8
#define SPI_XFER_LENGTH 2048 + 4


int inline _min(int a, int b) {
    return (a > b) ? b : a; 
}


RSA* get_machine_rsakey() {
    int fd;
    int ret;
    unsigned char buf[4096];
    uint8_t txbuf[SPI_XFER_LENGTH];
    uint8_t rxbuf1[SPI_XFER_LENGTH];
    uint8_t rxbuf2[SPI_XFER_LENGTH];

    struct spi_ioc_transfer xfer;
    memset(&xfer, 0, sizeof(xfer));

    if((fd = open(SPI_PATH, O_RDWR, 0)) == -1) {
        PyErr_SetFromErrno(PyExc_IOError);
        return NULL;
    }

    xfer.bits_per_word = SPI_BITS_PER_WORD;
    xfer.speed_hz = SPI_MAX_SPEED_HZ;
    xfer.delay_usecs = 0;
    xfer.len = 2052;

    txbuf[0] = 3;
    txbuf[1] = 1;
    txbuf[2] = 240;
    txbuf[3] = 0;
 
    xfer.tx_buf = (unsigned long)txbuf;
    xfer.rx_buf = (unsigned long)rxbuf1;

    if((ret = ioctl(fd, SPI_IOC_MESSAGE(1), &xfer)) < 0) {
        close(fd);

        PyErr_SetFromErrno(PyExc_IOError);
        return NULL;
    }

    txbuf[2] = 248;
    xfer.rx_buf = (unsigned long)rxbuf2;
    if((ret = ioctl(fd, SPI_IOC_MESSAGE(1), &xfer)) < 0) {
        close(fd);

        PyErr_SetFromErrno(PyExc_IOError);
        return NULL;
    }

    close(fd);

    int len = rxbuf1[4] + rxbuf1[5] * 256;
    if(len == 0 || len == 65535) {
        // SPI storage error
        PyErr_SetString(PyExc_RuntimeError, "Identify chip failed (-1)");
        return NULL;
    }

    memcpy((void *)buf, (void *)(rxbuf1 + 6), _min(len, 2046));
    if(len > 2046) {
        memcpy((void *)buf + 2046, rxbuf2 + 4, len - 2046);
    }

    return import_der(buf, len, 1);
}


int get_machine_uuid(unsigned char *uuid_buf[16]) {
    RSA* rsakey = get_machine_rsakey();
    if(!rsakey) return -1;

    PyObject* pybuf = export_der(rsakey, 1);
    if(!pybuf) return -1;

    PyObject* hashlib_module = PyImport_ImportModule("hashlib");
    if(!hashlib_module) return -1;

    PyObject* sha1_chip = PyObject_GetAttrString(hashlib_module, "sha1");
    if(!sha1_chip) return -1;

    PyObject* sha1 = PyEval_CallObject(sha1_chip, Py_BuildValue("(O)", pybuf));
    if(!sha1) return -1;

    PyObject* digest = PyEval_CallMethod(sha1, "digest", "()");
    if(!digest) return -1;

    Py_buffer view;
    if(PyObject_GetBuffer(digest, &view, PyBUF_SIMPLE) != 0) {
        return -1;
    }

    memcpy(uuid_buf, view.buf, 16);
    PyBuffer_Release(&view);

    return 0;
}
#endif  // @ifdef FLUX_MODEL_G1
