#!/usr/bin/env python

from datetime import datetime
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


def manually_choose_egg():
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    basedir = os.path.join(project_dir, "dist")
    eggs = [fn for fn in os.listdir(basedir) if fn.endswith(".egg")]
    egg = None

    if len(eggs) == 1:
        print("Autoselect egg: %s" % eggs[0])
        egg = eggs[0]

    while not egg:
        print("\nEgg files:\n")
        for i in range(len(eggs)):
            print("  [%i] %s" % (i + 1, eggs))
            sys.stdout.write("\nPlease choose egg file: ")
            sys.stdout.flush()

            try:
                rtn = sys.stdin.readline()
                val = int(rtn.strip())
                egg = eggs[val - 1]
            except Exception as e:
                print("Error: %s" % e)

    return os.path.join(basedir, egg)


def auto_find_extra_egg():
    return []


def auto_find_extra_deb():
    return []


def post_process_options(options):
    if not options.egg:
        options.egg = manually_choose_egg()
    if not options.extra_eggs:
        options.extra_eggs = auto_find_extra_egg()
    if not options.extra_deb:
        options.extra_deb = auto_find_extra_deb()

    if not options.output:
        options.output = "fxm1-%s.fxfw" % (datetime.now().strftime("%Y%m%d"))


def place_file(src, working_dir):
    name = os.path.basename(src)
    shutil.copyfile(src, os.path.join(working_dir, name))

    with open(src, "rb") as f:
        hashobj = sha256(f.read())
        return [name,
                "sha256:%s" % hashobj.hexdigest()]


def main():
    parser = argparse.ArgumentParser(description='fluxmonitor update packer')
    parser.add_argument('-k', '--key', dest='key', type=str, required=True,
                        help='Signature Key')
    parser.add_argument('--egg', type=str, default=None,
                        help='fluxmonitor egg file')
    parser.add_argument('--extra', dest='extra_eggs', type=str, default=None,
                        nargs='*', help='Extra eggs')
    parser.add_argument('--debian', dest='extra_deb', type=str, default=None,
                        nargs='*', help='Extra debian packages')
    parser.add_argument('-o', '--out', dest='output', type=str,
                        help="Output file")

    options = parser.parse_args()
    post_process_options(options)

    package = pkg_resources.Distribution.from_filename(options.egg)
    assert package.project_name == "fluxmonitor", "Bad egg file"
    version = package.version

    workdir = mkdtemp()

    try:
        manifest = {"package": "fluxmointor", "version": version,
                    "egg": place_file(options.egg, workdir),
                    "extra_eggs": [place_file(fn, workdir) \
                                    for fn in options.extra_eggs],
                    "extra_deb": [place_file(fn, workdir) \
                                    for fn in options.extra_deb]}

        manifest_fn = os.path.join(workdir, "MANIFEST.in")
        signature_fn = os.path.join(workdir, "signature")

        with open(manifest_fn, "w") as f:
            json.dump(manifest, f, indent=2)

        proc = subprocess.Popen(["openssl", "dgst", "-sha1",
                                 "-out", signature_fn, "-sign", options.key,
                                 manifest_fn], )
        ret = proc.wait()
        assert ret == 0, "Sign failed, return %i" % ret

        with zipfile.ZipFile(options.output, "w") as zf:
            for fn in os.listdir(workdir):
                zf.write(os.path.join(workdir, fn), fn)

        print("Output at %s" % options.output)

    finally:
        shutil.rmtree(workdir)

if __name__ == "__main__":
    main()
