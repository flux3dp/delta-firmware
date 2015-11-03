
cdef extern from "correction.h":
    struct CorrectionResult:
        float X
        float Y
        float Z
        float R
        float H

    int calculator(float, float, float, float, float, float, float, float,
                   float, CorrectionResult*)

def calculate(float init_x, float init_y, float init_z, float init_h,
              float input_x, float input_y, float input_z, float input_h,
              float delta_radious=96.7):
    cdef CorrectionResult result
    cdef int ret
    ret = calculator(init_x, init_y, init_z, init_h, input_x, input_y, input_z,
                     input_h, delta_radious, &result)
    return (result.X, result.Y, result.Z, result.R, result.H)
