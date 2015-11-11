
import pytest
import shutil
import os

from setup_utils import setup_test
setup_test()


@pytest.fixture(autouse=True)
def clean_db(request):
    from fluxmonitor import config
    if os.path.exists(config.general_config["db"]):
        shutil.rmtree(config.general_config["db"])
