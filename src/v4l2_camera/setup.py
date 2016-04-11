import platform
from setuptools import setup, Extension
from distutils.core import setup

s = platform.platform()
if s.startswith('Linux'):
    setup(name='v4l2_camera',
          ext_modules=[Extension("v4l2_camera", sources=["v4l2_camera_module.cpp", "v4l2_camera.cpp"], language="c++")
                       ],
          language="c++"
          )
else:
    from Cython.Build import cythonize
    setup(
        name='Hello world app',
        ext_modules=cythonize(["v4l2_camera.pyx"], language="c++"),
    )


# python setup.py build_ext --inplace

# v4l2_camera_module.
