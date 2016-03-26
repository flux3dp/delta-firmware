
import shutil
import os
_join = os.path.join


class _Fixtures(object):
    def __init__(self, filename=None):
        self.root = os.path.dirname(__file__)
        base = os.path.join(self.root, "data")
        if filename:
            self.node = _join(base, filename)
        else:
            self.node = base

    def apply_skel(self, root, label):
        d = _join(self.root, "skel", label)
        shutil.copytree(d, root)

    def path(self, filename):
        return _join(self.node, filename)

    def open(self, filename, mode):
        return open(_join(self.node, filename), mode)

    def exists(self, filename):
        return os.path.exists(self.node, _join(filename))

    def __getattr__(self, filename):
        node = _join(self.node, filename)
        if os.path.isfile(node):
            with open(node, "rb") as f:
                return f.read()
        elif os.path.isdir(node):
            return _Fixtures(node)

        elif os.path.exists(node):
            raise RuntimeError("Unknow Type: %s" % node)

        else:
            raise RuntimeError("Not found: %s" % node)

    def __repr__(self):
        return "<Fixtures: %s>" % self.node

Fixtures = _Fixtures()
