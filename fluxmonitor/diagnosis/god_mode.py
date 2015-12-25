
from hashlib import sha1
import os

DEBUG_STR = "442c3154f4fc88ec556dc69f0cbce343f0ed7626"


def allow_god_mode():
    from fluxmonitor import _halprofile
    from fluxmonitor.storage import Storage

    if _halprofile.is_dev_model:
        return True
    else:
        s = Storage("general", "meta")
        magic_str = s["debug"]
        if magic_str:
            return sha1(magic_str).hexdigest() == DEBUG_STR
        else:
            return False
