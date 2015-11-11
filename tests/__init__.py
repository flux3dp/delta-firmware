
from os import environ


TEST_FLAGS = filter(lambda e: e, environ.get("TEST", "").split(" "))
