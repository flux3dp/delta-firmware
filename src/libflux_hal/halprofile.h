
#ifndef LIB_HALPROFILE
#define LIB_HALPROFILE

#ifdef FLUX_MODEL_LINUX_DEV
#define FLUX_MODEL_ID "linux-dev"
#define FLUX_PLATFORM "linux"
#define FLUX_DEV_MODEL 1
#define FLUX_CAMERA0_ID -1


#elif defined(FLUX_MODEL_DARWIN_DEV)
#define FLUX_MODEL_ID "darwin-dev"
#define FLUX_PLATFORM "darwin"
#define FLUX_DEV_MODEL 1
#define FLUX_CAMERA0_ID 0


#elif defined(FLUX_MODEL_G1)
#define FLUX_MODEL_ID "model-1"
#define FLUX_PLATFORM "linux"
#define FLUX_DEV_MODEL 0
#define FLUX_CAMERA0_ID 0


#else
#error Unknow platform

#endif
#endif
