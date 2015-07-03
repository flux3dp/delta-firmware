
#ifndef FLUX_UNAME
#define FLUX_UNAME

#define LINUX_PLATFORM "linux"
#define DARWIN_PLATFORM "darwin"

#define MODEL_LINUX_DEV "linux-dev"
#define MODEL_DARWIN_DEV "darwin-dev"
#define MODEL_G1 "model:1"

struct FLUX_Uname {
    int camera_id;
} FX_Uname;


#if defined(__linux__) && defined(__x86_64__)

#define FLUX_MODEL_ID MODEL_LINUX_DEV
#define FLUX_PLATFORM LINUX_PLATFORM
#define FLUX_DEV_MODEL 1


#elif defined(__APPLE__)

#define FLUX_MODEL_ID MODEL_DARWIN_DEV;
#define FLUX_PLATFORM MODEL_DARWIN_DEV
#define FLUX_DEV_MODEL 1


#elif defined(FLUX_MODEL_G1)

#define FLUX_MODEL_ID MODEL_G1;
#define FLUX_PLATFORM LINUX_PLATFORM
#define FLUX_DEV_MODEL 0

#else
#error Unknow platform, please read compile guide at: https://github.com/flux3dp/fluxmonitor/wiki/Deploy-fluxmonitor-manually

#endif

#endif
