
#include "libflux_hal/halprofile.h"

#if defined(FLUX_MODEL_LINUX_DEV) || defined(FLUX_MODEL_DARWIN_DEV)

#include <Python.h>
#include "flux_identify.h"


RSA* get_machine_rsakey() {
    return get_rescue_machine_rsakey();
}


int get_machine_uuid(unsigned char *uuid_buf[16]) {
    return get_rescue_machine_uuid(uuid_buf);
}

#endif