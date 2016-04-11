
cdef extern from "systime.h":
    float monotonic_time()


def systime():
    return monotonic_time()
