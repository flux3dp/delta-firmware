
import platform

if platform.system().lower().startswith("linux"):
    from ._scan_linux import *
    from ._config_linux import *

elif platform.system().lower().startswith("darwin"):
    from ._scan_darwin import *
    from ._config_darwin import *
    
else:
    raise "Can not import any module under nl80211 because we not implement platform: %s" % platform.system()
