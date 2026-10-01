"""Unpack Python's Tcl/Tk library zips into folders for PyInstaller (see build.ps1 for why).

    python tools/unpack_tcl.py build/tcl     ->  build/tcl/_tcl_data, build/tcl/_tk_data
"""
import glob
import os
import shutil
import sys
import zipfile

out = sys.argv[1]
tcl_dir = os.path.join(sys.base_prefix, "tcl")
shutil.rmtree(out, ignore_errors=True)
for pattern, inner, dest in (("libtcl*.zip", "tcl_library/", "_tcl_data"), ("libtk*.zip", "tk_library/", "_tk_data")):
    found = glob.glob(os.path.join(tcl_dir, pattern))
    if len(found) != 1:
        sys.exit(f"expected one {pattern} in {tcl_dir}, found {found}")
    with zipfile.ZipFile(found[0]) as z:
        n = 0
        for name in z.namelist():
            if name.startswith(inner) and not name.endswith("/"):
                target = os.path.join(out, dest, name[len(inner):])
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "wb") as f:
                    f.write(z.read(name))
                n += 1
    print(f"{os.path.basename(found[0])}: {n} files -> {dest}")
