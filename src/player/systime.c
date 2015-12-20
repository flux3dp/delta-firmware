
#include <time.h>
#include <sys/time.h>

#ifdef __MACH__
#include <mach/clock.h>
#include <mach/mach.h>
extern mach_port_t clock_port;
#endif


float inline monotonic_time() {
    #ifdef __MACH__
        clock_serv_t cclock;
        mach_timespec_t mts;
        if(clock_get_time(clock_port, &mts) != 0) {
            return 0;
        }
        return mts.tv_sec + mts.tv_nsec / ((float)1.0e9);
    #else
        struct timespec ts;
        if(clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
            return 0;
        }
        return ts.tv_sec + ts.tv_nsec / ((float)1.0e9);
    #endif
}