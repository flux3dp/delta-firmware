
#include "libflux_hal/halprofile.h"

#if defined(FLUX_MODEL_LINUX_DEV) || defined(FLUX_MODEL_DARWIN_DEV)

#include <Python.h>
#include "flux_identify.h"

const char model_id[2] = {0, 0};


RSA* get_machine_rsakey() {
    return get_rescue_machine_rsakey();
}


int get_machine_uuid(unsigned char *uuid_buf[16]) {
    return get_rescue_machine_uuid(uuid_buf);
}


int get_machine_sn(unsigned char *sn_buf[10]) {
    return get_rescue_machine_sn(sn_buf);
}


int get_machine_identify(unsigned char** buffer) {
    *buffer = malloc(12);
    memcpy(*buffer, "WAWASUREMONO", 12);
    return 12;
}

const char* get_machine_model() {
    return model_id;
}

#endif