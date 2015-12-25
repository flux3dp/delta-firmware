
cdef extern from "correction.h":
    struct CorrectionResult:
        float X
        float Y
        float Z
        float R
        float H

    int calculator(float, float, float, float, float, float, float, float,
                   float, float, float, float, float, float, float,
                   CorrectionResult*)

def calculate(float init_x, float init_y, float init_z, float init_h,
              float input_x, float input_y, float input_z, float input_h,
              float t1x=-73.61, float t1y=-42.50,
              float t2x=73.61, float t2y=-42.50,
              float t3x=0.00, float t3y=85.00,
              float delta_radious=96.7):
    cdef CorrectionResult result
    cdef int ret
    ret = calculator(init_x, init_y, init_z, init_h, input_x, input_y, input_z,
                     input_h, delta_radious, t1x, t1y, t2x, t2y, t3x, t3y,
                     &result)
    return {"X": result.X, "Y": result.Y, "Z": result.Z, "R": result.R,
            "H": result.H}
