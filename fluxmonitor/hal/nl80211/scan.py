# flake8: noqa

from fluxmonitor import halprofile

if halprofile.PLATFORM == halprofile.LINUX_PLATFORM:
    from ._scan_linux import *
elif halprofile.PLATFORM == halprofile.DARWIN_PLATFORM:
    from ._scan_darwin import *
else:
    raise RuntimeError("Unsupport hal profile")
