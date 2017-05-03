
#include <errno.h>
#include <signal.h>
#include <stddef.h>
#include <stdio.h>
#include <unistd.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <Python.h>
#include "usb_txrx.h"

#define TX_BUFFER_LEN 510
#define RX_BUFFER_LEN 510

int discover_usb(void) {
    // Return number of available usb devices
    libusb_device **devices;
    libusb_context *ctx;
    int i, c, ret, devices_count;

    ret = libusb_init(&ctx);
    if(ret != 0) {
        fprintf(stderr, "libusb_init: %i", ret);
        return -1;
    }

    devices_count = libusb_get_device_list(ctx, &devices);
    c = 0;
    for(i=0; i<devices_count; i++) {
        struct libusb_device_descriptor desc;
        ret = libusb_get_device_descriptor(devices[i], &desc);
        if(ret != 0) {
            fprintf(stderr, "libusb_get_device_descriptor: %i", ret);
            continue;
        }
        if(desc.idVendor != 0xffff) { continue; }
        if(desc.idProduct != 0xfd00) { continue; }
        c += 1;
    }
    libusb_free_device_list(devices, 1);
    libusb_exit(ctx);
    return c;
}

int setup_usb(struct usb_data **data) {
    int i, ret, devices_count;
    int device_addr, num_configurations;
    libusb_device **devices;

    *data = calloc(1, sizeof(struct usb_data));
    ret = libusb_init(&((*data)->ctx));
    // libusb_set_debug((*data)->ctx, 4);

    if(ret != 0) {
        PyErr_Format(PyExc_SystemError, "libusb_init: %i", ret);
        close_usb(*data);
        return -1;
    }

    (*data)->device = NULL;
    devices_count = libusb_get_device_list((*data)->ctx, &devices);
    if(devices_count < 0) {
        PyErr_Format(PyExc_SystemError, "libusb_get_device_list: %i", devices_count);
        close_usb(*data);
        return -1;
    } else {
        for(i=0; i<devices_count; i++) {
            struct libusb_device_descriptor desc;
            ret = libusb_get_device_descriptor(devices[i], &desc);
            if(ret != 0) {
                fprintf(stderr, "libusb_get_device_descriptor: %i", ret);
                continue;
            }
            if(desc.idVendor != 0xffff) { continue; }
            if(desc.idProduct != 0xfd00) { continue; }

            if((*data)->device == NULL) {
                (*data)->device = devices[i];
                device_addr = libusb_get_device_address(devices[i]);
                num_configurations = desc.bNumConfigurations;
            } else {
                int swap_addr = libusb_get_device_address(devices[i]);
                if(swap_addr < device_addr) {
                    (*data)->device = devices[i];
                    device_addr = swap_addr;
                    num_configurations = desc.bNumConfigurations;
                }
            }
        }
        if((*data)->device == NULL) {
            PyErr_Format(PyExc_SystemError, "No device found");
            libusb_free_device_list(devices, 1);
            close_usb(*data);
            return -1;
        }
    }

    ret = libusb_open((*data)->device, &((*data)->handle));
    if(ret != 0) {
        PyErr_Format(PyExc_SystemError, "libusb_open: %i", ret);
        close_usb(*data);
        return -1;
    }

    libusb_free_device_list(devices, 1);

    for(int i=0;i<num_configurations;i++) {
        ret = libusb_kernel_driver_active((*data)->handle, i);
        if(ret == 1) {
            printf("detach interface %i\n", i);
            ret = libusb_detach_kernel_driver((*data)->handle, i);
        }
    }

    for(i=0;i<2;i++) {
        ret = libusb_set_configuration((*data)->handle, i);
        if(ret != 0) {
            fprintf(stderr, "libusb_set_configuration(%i): %i, reset device\n", i, ret);
            libusb_reset_device((*data)->handle);
            ret = libusb_set_configuration((*data)->handle, 0);
            if(ret != 0) {
                PyErr_Format(PyExc_SystemError, "libusb_set_configuration(%i): %i", i, ret);
                close_usb(*data);
                return -1;
            }
        }
    }

    ret = libusb_claim_interface((*data)->handle, 0);
    if(ret != 0) {
        PyErr_Format(PyExc_SystemError, "libusb_claim_interface: %i", ret);
        close_usb(*data);
        return -1;
    }

    (*data)->config_desc = malloc(sizeof(struct libusb_config_descriptor));

    ret = libusb_get_active_config_descriptor((*data)->device, &((*data)->config_desc));
    if(ret != 0) {
        PyErr_Format(PyExc_SystemError, "libusb_get_active_config_descriptor: %i", ret);
        close_usb(*data);
        return -1;
    }

    int num_endpoints = (*data)->config_desc->interface[0].altsetting[0].bNumEndpoints;
    const struct libusb_endpoint_descriptor *endpoint = (*data)->config_desc->interface[0].altsetting[0].endpoint;
    for(int i=0;i<num_endpoints;i++) {
        if(endpoint[i].bEndpointAddress == 0x02) { // WRITE
            (*data)->tx = &(endpoint[i]);
        } else if(endpoint[i].bEndpointAddress == 0x83) { // READ
            (*data)->rx = &(endpoint[i]);
        }
    }

    ret = socketpair(AF_UNIX, SOCK_STREAM, 0, (int *)(&(*data)->socket_vector));
    if(ret != 0) {
        PyErr_Format(PyExc_SystemError, "socketpair: %i", ret);
        close_usb(*data);
        return -1;
    }

    return (*data)->socket_vector[1];
}


void close_usb(struct usb_data *data) {
    data->running = 0;
 
    if(data->thread_tx) {
        pthread_kill(data->thread_tx, SIGUSR1);
    }
    if(data->thread_rx) {
        pthread_kill(data->thread_rx, SIGUSR1);
    }
    if(data->thread_tx) {
        pthread_join(data->thread_tx, NULL);
    }
    if(data->thread_rx) {
        pthread_join(data->thread_rx, NULL);
    }
}


void free_usb(struct usb_data *data) {
    if(data->config_desc) {
        free(data->config_desc);
    }
    if(data->handle) {
        libusb_close(data->handle);
    }
    if(data->ctx) {
        libusb_exit(data->ctx);
    }
    free(data);
}


int start_usb(struct usb_data *data) {
    close(data->socket_vector[1]);

    int ret;
    data->running = 1;
    ret = pthread_create(&(data->thread_tx), NULL, thread_tx_entry, (void *)data);
    if(ret != 0) {
        fprintf(stderr, "Fork tx thread error (ret=%i, errno=%i)\n", ret, errno);
        data->running = 0;
        close_usb(data);
        PyErr_Format(PyExc_SystemError, "socketpair: %i", ret);
        return -1;
    }
    ret = pthread_create(&(data->thread_rx), NULL, thread_rx_entry, (void *)data);
    if(ret != 0) {
        fprintf(stderr, "Fork rx thread error (ret=%i, errno=%i)\n", ret, errno);
        data->running = 0;
        close_usb(data);
        PyErr_Format(PyExc_SystemError, "socketpair: %i", ret);
        return -1;
    }
    fprintf(stderr, "USB daemon forked\n");
    return 0;
}


void sighug_handler(int sig) {
    signal(SIGUSR1, sighug_handler);
}


void libusb_callback(struct libusb_transfer *xfr)
{
}

void *thread_tx_entry(void *arg) {
    signal(SIGUSR1, sighug_handler);
    struct usb_data *data = arg;
    data->thread_flag[0] = 1;

    struct libusb_device_handle *handle = data->handle;
    const unsigned char endpoint = data->tx->bEndpointAddress;
    int ret, recvlen, sent, txtransfered = 0;
    unsigned char buffer[TX_BUFFER_LEN];
    struct libusb_transfer *xfr;

    while(data->running) {
        // recvlen = recv(data->socket_vector[0], buffer, TX_BUFFER_LEN, 0);

        // ret = libusb_fill_bulk_transfer(xfr, handle, endpoint, buffer, recvlen, libusb_callback, NULL, 500);
        recvlen = recv(data->socket_vector[0], buffer, TX_BUFFER_LEN, 0);

        if(recvlen == -1) {
            if(errno == ETIMEDOUT || errno == EAGAIN || errno == EINTR) {
                fprintf(stderr, "TX recv ret=%i errno=%i ignore\n", recvlen, errno);
                continue;
            } else {
                fprintf(stderr, "TX recv ret=%i errno=%i\n", recvlen, errno);
                data->running = 0;
            }
        } else if(recvlen == 0) {
            fprintf(stderr, "TX recv ret=0 (connection closed)\n");
            data->running = 0;
        } else {
            txtransfered = 0;
            while(txtransfered < recvlen) {
                pthread_mutex_lock(&(data->usb_mutex));
                ret = libusb_bulk_transfer(handle, endpoint, buffer + txtransfered, recvlen - txtransfered, &sent, 3000);
                pthread_mutex_unlock(&(data->usb_mutex));

                if(ret == 0) {
                    txtransfered += sent;
                    continue;
                } else if(ret == LIBUSB_ERROR_TIMEOUT) {
                    if(sent) {
                        txtransfered += sent;
                        continue;
                    } else {
                        printf("TX usb ret=TIMEOUT, recvlen=%i\n", recvlen);
                        break;
                    }
                } else {
                    fprintf(stderr, "TX usb ret=%i, recvlen=%i\n", ret, recvlen);
                    data->running = 0;
                    break;
                }
            }
        }
    }

    printf("Usb TX terminated.\n");
    data->thread_flag[0] = 0;
    return 0;
}


void *thread_rx_entry(void *arg) {
    signal(SIGUSR1, sighug_handler);
    struct usb_data *data = arg;
    data->thread_flag[1] = 1;

    struct libusb_device_handle *handle = data->handle;
    const unsigned char endpoint = data->rx->bEndpointAddress;
    int ret, recvlen;
    unsigned char buffer[RX_BUFFER_LEN];

    while(data->running) {
        pthread_mutex_lock(&(data->usb_mutex));
        ret = libusb_bulk_transfer(handle, endpoint, buffer, RX_BUFFER_LEN, &recvlen, 300);
        pthread_mutex_unlock(&(data->usb_mutex));
        if(ret == 0) {
            int transfered = 0;
            while(transfered < recvlen) {
                ret = send(data->socket_vector[0], buffer + transfered, recvlen - transfered, 0);

                if(ret > 0) {
                    transfered += ret;
                } else if(ret < 0) {
                    if(errno == ETIMEDOUT || errno == EAGAIN || errno == EINTR) {
                        continue;
                    } else {
                        fprintf(stderr, "RX send ret=%i errno=%i\n", ret, errno);
                        data->running = 0;
                        break;
                    }
                }
            }
        } else if(ret == LIBUSB_ERROR_TIMEOUT) {
            continue;
        } else {
            printf("RX usb ret=%i, transfered=%i\n", ret, recvlen);
            data->running = 0;
        }

    }

    printf("Usb RX terminated.\n");
    data->thread_flag[1] = 0;
    return 0;
}
