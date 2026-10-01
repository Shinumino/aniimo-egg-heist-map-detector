# Build dist\AniimoEggHeistMapDetector.exe from this folder's code (the same command GitHub runs).
#   powershell -File build.ps1
#
# Tcl/Tk (the overlay window): Python 3.14 ships Tcl 9, which keeps its library inside libtcl9*.zip /
# libtk9*.zip instead of folders, and PyInstaller 6.16 still looks for the folders. Without them the .exe
# died at start with 'Tcl data directory "..._tcl_data" not found' (2026-10-01). So they are unpacked here
# and shipped under the names PyInstaller's start-up hook expects.
# fmod_toolkit: UnityPy imports it (for game audio, which this tool never reads) and it loads fmod.dll at
# import, so the DLL has to be in the .exe too or it dies at start. The same for the rest of UnityPy's chain
# (archspec needs its CPU list, json/cpu/microarchitectures.json): every one of them is collected whole.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py = ".venv\Scripts\python.exe"
& $py tools\unpack_tcl.py build\tcl
if ($LASTEXITCODE -ne 0) { throw "unpacking Tcl/Tk failed" }
& $py -m PyInstaller --noconfirm --clean --onefile --console `
    --name AniimoEggHeistMapDetector `
    --paths src `
    --add-data "web\eggheist.html;web" `
    --add-data "build\tcl\_tcl_data;_tcl_data" `
    --add-data "build\tcl\_tk_data;_tk_data" `
    --collect-all UnityPy `
    --collect-all fmod_toolkit `
    --collect-all archspec `
    --collect-all astc_encoder `
    --collect-all texture2ddecoder `
    --collect-all etcpak `
    --hidden-import PIL.ImageTk `
    run.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
