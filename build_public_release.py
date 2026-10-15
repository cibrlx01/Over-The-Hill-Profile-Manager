"""Build the public portable EXE using a local official CPython 3.12 installation."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile

VERSION = '1.0.2'
HERE = Path(__file__).resolve().parent
BUILD = HERE / 'build' / VERSION
RUNTIME = BUILD / 'runtime'
RELEASE = BUILD / f'OverTheHill-ProfileManager-v{VERSION}-Windows-x64'
PYTHON = Path(sys.base_prefix)


def main():
    if sys.version_info[:2] != (3, 12) or sys.maxsize <= 2**32 or os.name != 'nt':
        raise SystemExit('Use 64-bit Windows Python 3.12 with Tkinter to build.')
    if BUILD.exists():
        raise SystemExit('Build output already exists. Move the build folder aside before rebuilding.')
    RUNTIME.mkdir(parents=True)
    RELEASE.mkdir()
    for name in ('python.exe', 'pythonw.exe', 'python312.dll', 'python3.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'LICENSE.txt'):
        shutil.copy2(PYTHON / name, RUNTIME / name)
    excluded = {'site-packages', '__pycache__', 'test', 'tests', 'idlelib', 'ensurepip', 'turtledemo'}
    def ignore(folder, names):
        return [name for name in names if name in excluded or name.endswith(('.pyc', '.pyo'))]
    shutil.copytree(PYTHON / 'Lib', RUNTIME / 'Lib', ignore=ignore)
    (RUNTIME / 'DLLs').mkdir()
    for path in (PYTHON / 'DLLs').iterdir():
        if path.suffix.lower() in {'.dll', '.pyd'} and 'test' not in path.name.lower():
            shutil.copy2(path, RUNTIME / 'DLLs' / path.name)
    for name in ('tcl8', 'tcl8.6', 'tk8.6'):
        shutil.copytree(PYTHON / 'tcl' / name, RUNTIME / 'tcl' / name,
                        ignore=lambda folder, names: [n for n in names if n in {'demos', '__pycache__'}])
    # No import of site, current directory, global packages, or environment Python paths.
    (RUNTIME / 'python312._pth').write_text('Lib\nDLLs\napp\n', encoding='utf-8')
    (RUNTIME / 'app').mkdir()
    for name in ('profile_core.py', 'profile_manager.py', 'vehicle_names.json'):
        shutil.copy2(HERE / name, RUNTIME / 'app' / name)
    notices = RELEASE / 'THIRD-PARTY-NOTICES'
    notices.mkdir()
    shutil.copy2(PYTHON / 'LICENSE.txt', notices / 'Python-LICENSE.txt')
    for name in ('tcl8.6', 'tk8.6'):
        original = PYTHON / 'tcl' / name / 'license.terms'
        if original.exists():
            shutil.copy2(original, notices / f'{name}-license.terms')
    manifest = BUILD / 'payload-manifest.tsv'
    files = sorted(path for path in RUNTIME.rglob('*') if path.is_file())
    lines = [hashlib.sha256(path.read_bytes()).hexdigest() + '\t' + path.relative_to(RUNTIME).as_posix() for path in files]
    manifest.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    build_id = 'v' + VERSION + '-' + hashlib.sha256(manifest.read_bytes()).hexdigest()[:20]
    payload = BUILD / 'runtime.zip'
    with zipfile.ZipFile(payload, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in files:
            archive.write(path, path.relative_to(RUNTIME).as_posix())
    launcher = BUILD / 'CompiledLauncher.cs'
    launcher.write_text((HERE / 'PublicLauncher.cs').read_text(encoding='utf-8').replace('BUILD_ID_PLACEHOLDER', build_id), encoding='utf-8')
    compiler = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    executable = RELEASE / 'OverTheHill.ProfileManager.exe'
    command = [str(compiler), '/nologo', '/target:winexe', '/platform:x64', '/optimize+',
               '/reference:System.Windows.Forms.dll', '/reference:System.IO.Compression.dll',
               '/reference:System.IO.Compression.FileSystem.dll', '/out:' + str(executable),
               '/resource:' + str(payload) + ',RuntimePayload', '/resource:' + str(manifest) + ',PayloadManifest', str(launcher)]
    subprocess.run(command, check=True)
    for name in ('README.md', 'CHANGELOG.md', 'LICENSE.txt'):
        shutil.copy2(HERE / name, RELEASE / name)
    source = RELEASE / 'source'
    source.mkdir()
    for path in HERE.iterdir():
        if path.is_file() and (path.suffix == '.py' or path.name in {'PublicLauncher.cs', 'vehicle_names.json', 'README.md', 'CHANGELOG.md', 'LICENSE.txt'}):
            shutil.copy2(path, source / path.name)
    (RELEASE / 'BUILD-INFO.txt').write_text(f'Version: {VERSION}\nBuild: {build_id}\nPython: {sys.version}\nRuntime files: {len(files)}\n', encoding='utf-8')
    (RELEASE / 'SHA256SUMS.txt').write_text(hashlib.sha256(executable.read_bytes()).hexdigest() + '  OverTheHill.ProfileManager.exe\n', encoding='utf-8')
    output = BUILD / (RELEASE.name + '.zip')
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(RELEASE.rglob('*')):
            if path.is_file():
                archive.write(path, RELEASE.name + '/' + path.relative_to(RELEASE).as_posix())
    print(json.dumps({'exe': str(executable), 'zip': str(output), 'build_id': build_id,
                      'zip_bytes': output.stat().st_size, 'runtime_files': len(files)}))


if __name__ == '__main__':
    main()
