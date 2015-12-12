#!/usr/bin/env python

from tempfile import mkdtemp
from hashlib import sha256
import pkg_resources
import subprocess
import argparse
import zipfile
import shutil
import json
import sys
import os


def unpack_resource(zf, metadata):
    name, signature = metadata

    zf.extract(name)

    chipertype, chipertext = signature.split(":")
    if chipertype == "sha256":
        chiper = sha256()
    else:
        raise RuntimeError("chiper error: %s" % chipertype)

    with open(name, "rb") as f:
        buf = f.read(4096)
        while buf:
            chiper.update(buf)
            buf = f.read(4096)
    if chiper.hexdigest() == chipertext:
        return name
    else:
        raise RuntimeError("chipertext error")


def validate_signature(manifest_fn, signature_fn):
    if os.path.exists("/etc/flux/fxupdate.pem"):
        keyfile = "/etc/flux/fxupdate.pem"
    else:
        keyfile = pkg_resources.resource_filename("fluxmonitor",
                                                  "data/fxupdate.pem")
    proc = subprocess.Popen(["openssl", "dgst", "-sha1", "-verify",
                             keyfile,
                             "-signature", signature_fn, manifest_fn])
    ret = proc.wait()
    if ret == 0:
        return True
    return False


def main():
    parser = argparse.ArgumentParser(description='fluxmonitor updater')
    parser.add_argument('--dryrun', dest='dryrun', action='store_const',
                        const=True, default=False, help='Dry run')
    parser.add_argument('package_file', type=str,
                        help='Update package file')
    options = parser.parse_args()
    options.package_file = os.path.abspath(options.package_file)

    workdir = mkdtemp()
    try:
        with zipfile.ZipFile(options.package_file, "r") as zf:
            zf.extract("MANIFEST.in", workdir)
            zf.extract("signature", workdir)

            manifest_fn = os.path.join(workdir, "MANIFEST.in")

            signature_fn = os.path.join(workdir, "signature")

            if not validate_signature(manifest_fn, signature_fn):
                print("Can not validate signature")
                sys.exit(1)

            with open(manifest_fn, "r") as f:
                manifest = json.load(f)

            os.chdir(workdir)
            for package in manifest["extra_deb"]:
                try:
                    name = unpack_resource(zf, package)
                    proc = subprocess.Popen(["dpkg", "-i", name])
                    ret = proc.wait()
                except RuntimeError as e:
                    print(e)

            for package in manifest["extra_eggs"]:
                try:
                    name = unpack_resource(zf, package)
                    proc = subprocess.Popen(["easy_install", name])
                    ret = proc.wait()
                except RuntimeError as e:
                    print(e)

            try:
                name = unpack_resource(zf, manifest["egg"])
                proc = subprocess.Popen(["easy_install", name])
                ret = proc.wait()
            except RuntimeError as e:
                print(e)

    finally:
        shutil.rmtree(workdir)

if __name__ == "__main__":
    main()
