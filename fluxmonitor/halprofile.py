
MODEL_DARWIN_DEV = "darwin"
MODEL_LINUX_DEV = "linux-dev"
MODEL_MODEL_G1 = "model:1"


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


CURRENT_MODEL = get_model_id()
