
from __future__ import absolute_import

from mimetypes import add_type, guess_type

MIMETYPE_GCODE = "text/gcode"
MIMETYPE_FCODE = "application/fcode"

add_type(MIMETYPE_GCODE, ".gcode")
add_type(MIMETYPE_FCODE, ".fc")


def validate_ext(filename, match_mimetype):
    real_mimetype, _ = guess_type(filename)
    return real_mimetype == match_mimetype
