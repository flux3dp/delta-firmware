from io import BytesIO

from libc.stdlib cimport free
import cython

try:
    from fluxmonitor.misc.systime import systime as time
except:
    from time import time as time

cdef extern from "v4l2_camera_module.h":
    int attach_camera(int video_name,unsigned char* &_buf)
    int release_camera(int fd, unsigned char* &buffer)
    int capture_image(int fd, unsigned char* &buffer)

# cdef class BuffWrap:
#     cdef long siz
#     cdef char * _buf
#     cdef char[:] arr
#     def __cinit__(self,  long siz):
#         self.siz = siz
#         self._buf = fn.char_ret(siz) # storing the pointer so it can be freed
#         self.arr = <char[:siz]>self._buf
#     def __dealloc__(self):
#         free(self._buf)
#         self.arr = None
#     # here some extras:
#     def __str__(self):
#         if self.siz<11:
#             return 'BuffWrap: ' + str([ii for ii in self.arr])
#         else:
#             return ('BuffWrap: ' + str([self.arr[ii] for ii in range(5)])[0:-1] + ' ... '
#                     + str([self.arr[ii] for ii in range(self.siz-5, self.siz)])[1:])
#     def __getitem__(self, ind):
#         """ As example of magic method.  Implement rest of to get slicing
#         http://docs.cython.org/src/userguide/special_methods.html#sequences-and-mappings
#         """
#         return self.arr[ind]

cdef class V4l2_Camera:
    cdef object py_buffer

    cdef unsigned char * _buf
    cdef int buf_length
    cdef int camera_port
    cdef int fd
    cdef float ts

    # cdef unsigned char ** _buf_pointer = cython.address(self._buf);
    def __init__(self, camera_id):
        self.camera_port = camera_id
        self.fd = -1
        self.ts = time()
        self.py_buffer = None

    def live(self, ts):

        if time() - ts > 0.1:
            self.fetch(0)

        return self.ts

    def fetch(self, clear_cache=4, return_cv=False):
        # Take a new photo immediately
        if self.fd < 0:
            self.attach()

        self.buf_length = capture_image(self.fd, self._buf)
        # success_count = 0
        # for i in range(16):  # try at most 16 times
        #     if success_count >= clear_cache:  # 4 success is enough
        #         break
        #     if self.obj.grab():
        #         success_count += 1

        self.ts = time()
        if return_cv:
            pass  # todo
        self.py_buffer = None
        # return self.img_buf

    @property
    def imagefile(self):
        if self.py_buffer is None:
            self.py_buffer = BytesIO(self._buf[:self.buf_length])

        return ("image/jpeg", self.buf_length, self.py_buffer)

    cpdef attach(self):
        if self.fd > 0:
            self.release()
        self.fd = attach_camera(self.camera_port, self._buf)
        # print(self.fd)

    cpdef release(self):
        if self.fd > 0:
            release_camera(self.fd, self._buf)
            self.fd = -1
