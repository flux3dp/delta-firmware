
#ifndef LIB_HALPROFILE
#define LIB_HALPROFILE

#ifdef FLUX_MODEL_LINUX_DEV
#define FX_MODEL_ID "linux-dev"
#define FX_PLATFORM "linux"
#define FX_DEV_MODEL 1
#define FX_CAMERA0_ID -1


#elif defined(FLUX_MODEL_DARWIN_DEV)
#define FX_MODEL_ID "darwin-dev"
#define FX_PLATFORM "darwin"
#define FX_DEV_MODEL 1
#define FX_CAMERA0_ID 0


#elif defined(FLUX_MODEL_G1)
#define FX_MODEL_ID "model-1";
#define FX_PLATFORM "linux"
#define FX_DEV_MODEL 0
#define FX_CAMERA0_ID 0


#else
#error Unknow platform

#endif

#ifdef FX_MODEL_ID
const char* FLUX_MODEL_ID = FX_MODEL_ID;
const char* FLUX_PLATFORM = FX_PLATFORM;
const int FLUX_DEV_MODEL = FX_DEV_MODEL;
const int FLUX_CAMERA0_ID = FX_CAMERA0_ID;
#endif

#endif
