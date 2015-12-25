
from __future__ import absolute_import

from mimetypes import add_type, guess_type

MIMETYPE_GCODE = "text/gcode"
MIMETYPE_FCODE = "application/fcode"
MIMETYPE_FLUX_FIRMWARE = "binary/flux-firmware"

add_type(MIMETYPE_GCODE, ".gcode")
add_type(MIMETYPE_FCODE, ".fc")
add_type(MIMETYPE_FLUX_FIRMWARE, ".fxfw")



def validate_ext(filename, match_mimetype):
    real_mimetype, _ = guess_type(filename)
    return real_mimetype == match_mimetype
