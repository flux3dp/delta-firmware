
#include "libflux_hal/halprofile.h"

#include <Python.h>
#include "flux_identify.h"


RSA* get_rescue_machine_rsakey() {
    RSA *keyobj;
    PyObject *pyfile, *pybuf;

    // PY: from fluxmonitor import storage as storage_module
    PyObject* storage_module = PyImport_ImportModule("fluxmonitor.storage");
    if(!storage_module) return NULL;

    // PY: storage_klass = storage_module.Storage
    PyObject* storage_klass = PyObject_GetAttrString(storage_module, "Storage");
    if(!storage_klass) return NULL;

    // PY: storage = storage_klass("security", "private")
    PyObject* storage = PyEval_CallObject(
        storage_klass,
        Py_BuildValue("ss", "security", "private"));
    if(!storage) return NULL;

    // PY: py_has_file = storage.exists("key.pem")
    PyObject* py_has_file = PyEval_CallMethod(storage, "exists",
                                              "(s)", "key.pem");
    if(!py_has_file) return NULL;

    // PY: if py_has_file:
    if(py_has_file == Py_True) {
        // PY: pyfile = storage.open("key.pem", "r")
        pyfile = PyEval_CallMethod(storage, "open",
                                            "(s)", "key.pem", "r");
        if(!pyfile) return NULL;

        // PY: pybuf = pyfile.read()
        pybuf = PyEval_CallMethod(pyfile, "read", "()");
        if(!pybuf) return NULL;

        // PY: pyfile.close()
        PyEval_CallMethod(pyfile, "close", "()");

        Py_buffer view;
        if(PyObject_GetBuffer(pybuf, &view, PyBUF_SIMPLE) != 0) {
            return NULL;
        }

        keyobj = import_pem(view.buf, view.len, 1);
        PyBuffer_Release(&view);

        if(keyobj) {
            return keyobj;
        }
    }

    keyobj = create_rsa(1024);
    pybuf = export_pem(keyobj, 0);

    // PY: storage.open("key.pem", "w")
    pyfile = PyEval_CallMethod(storage, "open", "ss", "key.pem", "w");
    if(!pyfile) return NULL;

    // PY: pyfile.write(pybuf)
    PyEval_CallMethod(pyfile, "write", "(O)", pybuf);
    // PY: pyfile.close()
    PyEval_CallMethod(pyfile, "close", "()");

    return keyobj;
}


int get_rescue_machine_uuid(unsigned char *uuid_buf[16]) {
    RSA* rsakey = get_rescue_machine_rsakey();
    if(!rsakey) return -1;

    PyObject* pybuf = export_der(rsakey, 1);
    if(!pybuf) return -1;

    PyObject* hashlib_module = PyImport_ImportModule("hashlib");
    if(!hashlib_module) return -1;

    PyObject* sha1_chip = PyObject_GetAttrString(hashlib_module, "sha512");
    if(!sha1_chip) return -1;

    PyObject* sha1 = PyEval_CallObject(sha1_chip, Py_BuildValue("(O)", pybuf));
    if(!sha1) return -1;

    PyObject* digest = PyEval_CallMethod(sha1, "digest", "()");
    if(!digest) return -1;

    Py_buffer view;
    if(PyObject_GetBuffer(digest, &view, PyBUF_SIMPLE) != 0) {
        return -1;
    }

    memcpy(uuid_buf, view.buf, 16);
    PyBuffer_Release(&view);
    memset(uuid_buf, 0, 8);

    return 0;
}
