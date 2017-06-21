
import logging
import pytest
import shutil
import os

from tests.fixtures import Fixtures


def setup_logger():
    import logging.config
    logging.config.dictConfig({
        'version': 1,
        'disable_existing_loggers': True,
        'formatters': {
            'default': {
                'format': "[%(asctime)s,%(levelname)s,%(name)s] %(message)s",
                'datefmt': "%Y-%m-%d %H:%M:%S"
            }
        },
        'handlers': {
            'file': {
                'formatter': 'default',
                'class': 'logging.FileHandler',
                'filename': "./tmp/test.log"
            }
        },
        'root': {
            'handlers': ['file'],
            'level': 'DEBUG',
            'propagate': True
        }
    })


def setup_test():
    from tempfile import mkdtemp
    tempbase = mkdtemp()

    from fluxmonitor import config
    config.general_config["db"] = os.path.join(tempbase, "db")
    config.general_config["keylength"] = 512
    config.general_config["debug"] = True

    config.MAINBOARD_ENDPOINT = config.uart_config["mainboard"] = \
        os.path.join(tempbase, "mainboard-us")
    config.HEADBOARD_ENDPOINT = config.uart_config["headboard"] = \
        os.path.join(tempbase, "headboard-us")
    config.UART_ENDPOINT = config.uart_config["pc"] = \
        os.path.join(tempbase, "pc-us")
    config.HALCONTROL_ENDPOINT = config.uart_config["control"] = \
        os.path.join(tempbase, "ctrl-us")
    config.USERSPACE = os.path.join(tempbase, "userspace")
    config.NETWORK_MANAGE_ENDPOINT = os.path.join(tempbase, "network-us")

    def on_exit():
        import shutil
        shutil.rmtree(tempbase)
    import atexit
    atexit.register(on_exit)
    return os.path.join(tempbase, "db")


def reload_modules():
    import sys
    for name, module in sys.modules.items():
        if module and name.startswith("fluxmonitor"):
            if name not in ["fluxmonitor._halprofile", "fluxmonitor.config",
                            "fluxmonitor.halprofile"]:
                reload(module)


setup_logger()
dbroot = setup_test()
reload_modules()
logger = logging.getLogger(__name__)
logger.critical("== Start teset " + "=" * 64)


@pytest.fixture(autouse=True)
def clean_db():
    if os.path.exists(dbroot):
        shutil.rmtree(dbroot)


@pytest.fixture
def empty_security():
    os.makedirs(os.path.join(dbroot, "security", "private"))
    os.makedirs(os.path.join(dbroot, "security", "pub"))


@pytest.fixture
def default_db():
    if os.path.exists(dbroot):
        shutil.rmtree(dbroot)
    Fixtures.apply_skel(dbroot, label="default")
