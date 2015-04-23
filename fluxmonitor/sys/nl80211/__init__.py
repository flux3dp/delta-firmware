# flake8: noqa

from fluxmonitor import halprofile

if halprofile.CURRENT_MODEL == halprofile.MODEL_DARWIN_DEV:
    from ._config_simulate import *
elif halprofile.CURRENT_MODEL == halprofile.MODEL_LINUX_DEV:
    from ._config_simulate import *
elif halprofile.CURRENT_MODEL == halprofile.MODEL_MODEL_G1:
    from ._config_linux import *
else:
    raise RuntimeError("Unsupport hal profile")
    

if halprofile.PLATFORM == halprofile.LINUX_PLATFORM:
    from ._scan_linux import *
elif halprofile.PLATFORM == halprofile.DARWIN_PLATFORM:
    from ._scan_darwin import *
else:
    raise RuntimeError("Unsupport hal profile")
