# Third-party software notices

MCSync's original application code is licensed under MIT. No PolyMC/Prism source
code is included. The program uses these independently licensed components:

| Component | License / upstream |
|---|---|
| Python | PSF License; https://www.python.org/psf/license/ |
| PySide6 / Shiboken6 | LGPL-3.0 / GPL-3.0 / commercial alternatives; https://doc.qt.io/qtforpython-6/licenses.html |
| Qt Core / Gui / Widgets and plugins | Qt's applicable LGPL-3.0 / GPL terms and third-party notices; https://www.qt.io/licensing/open-source-lgpl-obligations |
| requests | Apache-2.0; https://github.com/psf/requests |
| minecraft-launcher-lib | BSD-2-Clause; https://codeberg.org/JakobDev/minecraft-launcher-lib |
| urllib3 | MIT; https://github.com/urllib3/urllib3 |
| certifi / Mozilla CA bundle | MPL-2.0; https://github.com/certifi/python-certifi |
| charset-normalizer | MIT; https://github.com/jawah/charset_normalizer |
| idna | BSD-3-Clause; https://github.com/kjd/idna |
| PyInstaller bootloader | GPL-2.0-or-later with bootloader exception; https://pyinstaller.org/en/stable/license.html |

The native onedir archives retain Qt/PySide as dynamic libraries. They are not
statically linked or DRM-locked. Recipients may replace/relink the LGPL libraries
with compatible modified versions. Do not remove the dynamic libraries or license
notices when redistributing an archive. Consult the actual upstream license texts
for all obligations, including provision of the corresponding LGPL library source.

`scripts/build.py` copies installed dependency license files into `licenses/`,
includes the original MCSync source and requirements in `source/`, and includes
this notice. Unmodified dependency source distributions are available from their
upstream repositories / PyPI at the versions listed in `requirements.txt`. Qt's
matching source is available at https://download.qt.io/archive/qt/ and PySide/Shiboken
source at https://download.qt.io/official_releases/QtForPython/ . Qt also incorporates
third-party code documented in its upstream notices. No proprietary Microsoft
Client ID, Minecraft game data, Mojang Java binaries, user mods or user tokens are
included in the launcher archive.

A distributor must check the actual licenses/source-availability requirements of
the exact bundled versions; this summary is not a replacement for those licenses.
Do not redistribute third-party modpacks without their authors' permission.
