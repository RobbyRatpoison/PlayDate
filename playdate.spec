# playdate.spec
# PyInstaller build spec for PlayDate (Windows)
#
# Build with:   pyinstaller playdate.spec
# Output:       dist/PlayDate/PlayDate.exe  (onedir bundle)
#
# PyInstaller docs: https://pyinstaller.org/en/stable/spec-files.html

import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# ── Root of the project (same folder as this spec file) ───────────────────────
ROOT = os.path.dirname(os.path.abspath(SPEC))

# ── Data files to bundle ───────────────────────────────────────────────────────
# Format: (source_path, dest_folder_inside_bundle)
datas = [
    # HTML templates — Flask looks for these in a 'templates' folder
    (os.path.join(ROOT, 'templates'), 'templates'),

    # Static assets (CSS, JS, images, backgrounds, favicon)
    (os.path.join(ROOT, 'static'), 'static'),
]

# Pull in any data files that flask, jinja2, waitress etc need
datas += collect_data_files('flask')
datas += collect_data_files('jinja2')
datas += collect_data_files('waitress')
datas += collect_data_files('webview')

# ── Hidden imports ─────────────────────────────────────────────────────────────
# Modules that PyInstaller's static analysis misses because they're
# imported dynamically (lazy imports, string-based imports, etc.)
hiddenimports = [
    # Flask internals
    'flask',
    'flask.templating',
    'jinja2',
    'jinja2.ext',
    'werkzeug',
    'werkzeug.serving',
    'werkzeug.debug',

    # WSGI server
    'waitress',
    'waitress.runner',

    # pywebview — Windows uses the EdgeChromium (WebView2) backend
    'webview',
    'webview.platforms.winforms',
    'webview.platforms.edgechromium',
    'clr',          # pythonnet — required by pywebview on Windows
    'System',
    'System.Windows.Forms',

    # PlayDate modules
    'app',
    'config',
    'database',
    'images',
    'imports',
    'index',
    'library',
    'main',
    'scrapers',
    'utils',

    # Common stdlib / third-party used at runtime
    'sqlite3',
    'json',
    'threading',
    'logging',
    'logging.handlers',
    'email.mime.text',  # used by some waitress internals
    'PIL',
    'PIL.Image',
    'requests',
    'bs4',
    'rapidfuzz',

    # VDF parser — lazy-imported in utils.py for localconfig.vdf reading
    'vdf',

    # Selenium — lazy-imported in scrape_blaeo_games(), so PyInstaller misses it
    'selenium',
    'selenium.webdriver',
    'selenium.webdriver.chrome',
    'selenium.webdriver.chrome.options',
    'selenium.webdriver.common.by',
    'selenium.webdriver.support.ui',
    'selenium.webdriver.support.expected_conditions',
    'webdriver_manager',
    'webdriver_manager.chrome',
]

hiddenimports += collect_submodules('webview')
hiddenimports += collect_submodules('flask')
hiddenimports += collect_submodules('werkzeug')

# ── Analysis ───────────────────────────────────────────────────────────────────
a = Analysis(
    [os.path.join(ROOT, 'main.py')],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude heavy packages not needed at runtime
        'matplotlib',
        'numpy',
        'boto3',
        'botocore',
        'gi',               # Linux GTK — not needed on Windows
        'gtk',
        'test',
        'unittest',
        'tkinter',          # Not used by the app itself
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ── EXE ───────────────────────────────────────────────────────────────────────
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,   # onedir mode — binaries go in the COLLECT step
    name='PlayDate',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,                # compress binaries (requires UPX on PATH)
    upx_exclude=[],
    console=False,           # no console window — app has its own pywebview window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT, 'static', 'img', 'favicon.ico'),  # .ico for Windows
)

# ── COLLECT (onedir bundle) ────────────────────────────────────────────────────
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PlayDate',         # output folder: dist/PlayDate/
)
