
#include "libflux_crypto/flux_crypto.h"


RSA* get_machine_rsakey(void);
int get_machine_uuid(unsigned char* [16]);
int get_machine_sn(unsigned char *[10]);
int get_machine_identify(unsigned char**);


RSA* get_rescue_machine_rsakey(void);
int get_rescue_machine_uuid(unsigned char* [16]);
int get_rescue_machine_sn(unsigned char* [10]);
