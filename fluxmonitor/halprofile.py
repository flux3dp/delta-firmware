
MODEL_DARWIN_DEV = "darwin-dev"
MODEL_LINUX_DEV = "linux-dev"
MODEL_MODEL_G1 = "model:1"

LINUX_PLATFORM = "linux"
DARWIN_PLATFORM = "darwin"


def get_model_id():
    import platform as P

    if P.uname()[0] == "Darwin":
        return MODEL_DARWIN_DEV
    elif P.uname()[0] == "Linux":
        if "x86" in P.uname()[4]:
            return MODEL_LINUX_DEV
        else:
            # Need some method to check if it is raspberry A
            return MODEL_MODEL_G1
    else:
        raise Exception("Can not get model id")


def is_dev_model(profile=None):
    if profile is None:
        profile = get_model_id()

    return profile == MODEL_LINUX_DEV or profile == MODEL_DARWIN_DEV

def get_platform():
    import platform as _platform
    if _platform.system().lower().startswith("linux"):
        return LINUX_PLATFORM
    elif _platform.system().lower().startswith("darwin"):
        return DARWIN_PLATFORM
    else:
        raise Exception("Can not identify platform")


CURRENT_MODEL = get_model_id()
PLATFORM = get_platform()
