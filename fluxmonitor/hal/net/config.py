# flake8: noqa

from fluxmonitor import halprofile

if halprofile.CURRENT_MODEL == halprofile.MODEL_DARWIN_DEV:
    from ._config_simulate import *
elif halprofile.CURRENT_MODEL == halprofile.MODEL_LINUX_DEV:
    from ._config_simulate import *
elif halprofile.CURRENT_MODEL == halprofile.MODEL_D1:
    from ._config_linux import *
else:
    raise RuntimeError("Unsupport hal profile")
