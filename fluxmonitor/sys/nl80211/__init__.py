# flake8: noqa

from fluxmonitor.config import develope_env, platform

if develope_env:
    from ._config_simulate import *
else:
    from ._config_linux import *
    

if platform == "linux":
    from ._scan_linux import *
elif platform == "darwin":
    from ._scan_darwin import *
else:
    raise "Can not import any module under nl80211 because we not implement platform: %s" % os
