
#include "libflux_hal/halprofile.h"

#ifdef FLUX_MODEL_D1

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


int spi_loaded = 0;
unsigned char uuid_cache[16];
unsigned char sn_cache[10];
unsigned char model_cache[2];


int inline _min(int a, int b) {
    return (a > b) ? b : a; 
}


int load_spi() {
    int fd;
    int ret;

    uint8_t ctrl_txbuf[1];
    uint8_t ctrl_rxbuf[1];

    struct spi_ioc_transfer xfer;
    memset(&xfer, 0, sizeof(xfer));

    if((fd = open(SPI_PATH, O_RDWR, 0)) == -1) {
        PyErr_SetFromErrno(PyExc_IOError);
        return -1;
    }

    xfer.bits_per_word = SPI_BITS_PER_WORD;
    xfer.speed_hz = SPI_MAX_SPEED_HZ;
    xfer.delay_usecs = 0;

    // Enter OPT Mode
    xfer.len = 1;
    ctrl_txbuf[0] = 0xB1;
    xfer.tx_buf = (unsigned long)ctrl_txbuf;
    xfer.rx_buf = (unsigned long)ctrl_rxbuf;

    if((ret = ioctl(fd, SPI_IOC_MESSAGE(1), &xfer)) < 0) {
        close(fd);

        PyErr_SetFromErrno(PyExc_IOError);
        return -1;
    }
    // <<<<<<<<<<<<<<<<<

    // Read OPT >>>>>>>>
    uint8_t read_txbuf[64 + 4];
    uint8_t read_rxbuf[64 + 4];

    read_txbuf[0] = 0x03;
    read_txbuf[1] = 0;
    read_txbuf[2] = 0;
    read_txbuf[3] = 0;
    xfer.len = 68;
    xfer.tx_buf = (unsigned long)read_txbuf;
    xfer.rx_buf = (unsigned long)read_rxbuf;

    if((ret = ioctl(fd, SPI_IOC_MESSAGE(1), &xfer)) < 0) {
        close(fd);

        PyErr_SetFromErrno(PyExc_IOError);
        return -1;
    }
    // <<<<<<<<<<<<<<<<<

    // Exit OPT Mode >>>
    xfer.len = 1;
    ctrl_txbuf[0] = 0xC1;
    xfer.tx_buf = (unsigned long)ctrl_txbuf;
    xfer.rx_buf = (unsigned long)ctrl_rxbuf;

    if((ret = ioctl(fd, SPI_IOC_MESSAGE(1), &xfer)) < 0) {
        close(fd);

        PyErr_SetFromErrno(PyExc_IOError);
        return -1;
    }
    // <<<<<<<<<<<<<<<<<

    close(fd);

    memcpy(uuid_cache, read_rxbuf + 4, 16);
    memcpy(sn_cache, read_rxbuf + 20, 10);
    memcpy(model_cache, read_rxbuf + 36, 2);

    spi_loaded = 1;
    return 0;
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
    if(spi_loaded == 0) {
        if(load_spi() > 1) {
            return 1;
        }
    }

    memcpy(uuid_buf, uuid_cache, 16);
    return 0;
}

int get_machine_sn(unsigned char *sn_buf[10]) {
    if(spi_loaded == 0) {
        if(load_spi() > 1) {
            return 1;
        }
    }

    memcpy(sn_buf, sn_cache, 16);
    return 0;
}

const char* get_machine_model() {
    if(spi_loaded == 0) {
        if(load_spi() > 1) {
            return "";
        }
    }

    return model_cache;
}

int get_machine_identify(unsigned char** buffer) {
    int fd;
    int ret;

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
    txbuf[2] = 224;
    txbuf[3] = 0;
 
    xfer.tx_buf = (unsigned long)txbuf;
    xfer.rx_buf = (unsigned long)rxbuf1;

    if((ret = ioctl(fd, SPI_IOC_MESSAGE(1), &xfer)) < 0) {
        close(fd);

        PyErr_SetFromErrno(PyExc_IOError);
        return NULL;
    }

    txbuf[2] = 232;
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

    *buffer = malloc(len);
    memcpy(*buffer, (void *)(rxbuf1 + 6), _min(len, 2046));
    if(len > 2046) {
        memcpy(*buffer + 2046, rxbuf2 + 4, len - 2046);
    }

    return len;
}

#endif  // @ifdef FLUX_MODEL_D1
