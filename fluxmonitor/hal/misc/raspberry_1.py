
import logging

logger = logging.getLogger(__name__)


def _get_deviceinfo():
    info = {}

    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            info["rpi_cpu_temp"] = int(f.read(), 10) / 1000.0
    except Exception:
        logger.exception("Error while getting CPU temp")

    return info
