from io import BytesIO

from libc.stdlib cimport free
import cython


from fluxmonitor.misc.systime import systime as time

cdef extern from "v4l2_camera_module.h":
    int attach_camera(int video_name,unsigned char* &_buf, int width, int height)
    int release_camera(int fd, unsigned char* &buffer)
    int capture_image(int fd, unsigned char* &buffer)


cdef class V4l2_Camera:
    cdef object py_buffer

    cdef unsigned char * _buf
    cdef int buf_length
    cdef int camera_port
    cdef int fd
    cdef float ts
    cdef width
    cdef height

    # cdef unsigned char ** _buf_pointer = cython.address(self._buf);
    def __init__(self, camera_id, width=800, height=600):
        self.camera_port = camera_id
        self.fd = -1
        self.ts = time()
        self.py_buffer = None
        self.width = width
        self.height = height

    def live(self, ts):
        if time() - ts > 0.1:
            self.fetch(0)
        else:
            self.fetch(0)
        return self.ts

    def fetch(self, clear_cache=4):
        # Take a new photo immediately
        if self.fd < 0:
            self.attach()

        self.buf_length = capture_image(self.fd, self._buf)
        # print('lengh: ', self.buf_length)
        # success_count = 0
        # for i in range(16):  # try at most 16 times
        #     if success_count >= clear_cache:  # 4 success is enough
        #         break
        #     if self.obj.grab():
        #         success_count += 1

        self.ts = time()
        self.py_buffer = None

    @property
    def imagefile(self):
        if self.py_buffer is None:
            self.py_buffer = BytesIO(self._buf[:self.buf_length])
        else:
            self.py_buffer.seek(0)

        return ("image/jpeg", self.buf_length, BytesIO(self._buf[:self.buf_length]))

    cpdef attach(self):
        print('attach')
        if self.fd > 0:
            self.release()
        self.fd = attach_camera(self.camera_port, self._buf, self.width, self.height)
        # print(self.fd)

    cpdef release(self):
        print('release')
        if self.fd > 0:
            release_camera(self.fd, self._buf)
            self.fd = -1
