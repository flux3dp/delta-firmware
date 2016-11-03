
#include <stdint.h>
#include <sys/socket.h>
#include <pthread.h>
#include <libusb-1.0/libusb.h>


struct usb_data {
    libusb_context *ctx;
    libusb_device *device;
    libusb_device_handle *handle;
    struct libusb_config_descriptor *config_desc;

    const struct libusb_endpoint_descriptor *tx;
    const struct libusb_endpoint_descriptor *rx;

    pthread_t thread_tx;
    pthread_t thread_rx;

    int socket_vector[2];
    int running;

    short thread_flag[2];
};


int discover_usb(void);
int setup_usb(struct usb_data **data);
int start_usb(struct usb_data *data);
int is_running(struct usb_data *data);
void close_usb(struct usb_data *data);
void free_usb(struct usb_data *data);
void *thread_tx_entry(void *arg);
void *thread_rx_entry(void *arg);
