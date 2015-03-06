
class CallbackHandler(object):
    def __init__(self, file_object, callback):
        self.obj = file_object
        self.callback = callback

    def fileno(self):
        return self.obj.fileno()

    def on_read(self):
        self.callback(self)
