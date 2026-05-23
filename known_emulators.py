"""
Built-in emulator definitions.  User config lives in emulators.json;
this file is read-only reference data bundled with the app.
"""

PLATFORM_NAMES = {
    'gamecube':   'GameCube',
    'wii':        'Wii',
    'wiiu':       'Wii U',
    'switch':     'Nintendo Switch',
    'nes':        'NES',
    'snes':       'SNES',
    'n64':        'Nintendo 64',
    'gb':         'Game Boy',
    'gbc':        'Game Boy Color',
    'gba':        'Game Boy Advance',
    'nds':        'Nintendo DS',
    '3ds':        'Nintendo 3DS',
    'virtualboy': 'Virtual Boy',
    'ps1':        'PlayStation',
    'ps2':        'PlayStation 2',
    'ps3':        'PlayStation 3',
    'psp':        'PSP',
    'psvita':     'PlayStation Vita',
    'dreamcast':  'Dreamcast',
    'saturn':     'Saturn',
    'genesis':    'Genesis / Mega Drive',
    'sms':        'Master System',
    'gg':         'Game Gear',
    'segacd':     'Sega CD / Mega CD',
    '32x':        'Sega 32X',
    'pce':        'PC Engine / TurboGrafx-16',
    'xbox':       'Xbox',
    'xbox360':    'Xbox 360',
    'arcade':     'Arcade',
    'dos':        'DOS',
    'atari2600':  'Atari 2600',
    'lynx':       'Atari Lynx',
    'c64':        'Commodore 64',
    'scummvm':    'ScummVM',
}

KNOWN_EMULATORS = [
    # ── GameCube / Wii ───────────────────────────────────────────────────────
    {
        'id':           'dolphin',
        'name':         'Dolphin',
        'binary_names': ['dolphin-emu', 'dolphin-emu-qt2', 'org.DolphinEmu.dolphin-emu'],
        'appimage_names': ['dolphin'],
        'platforms':    ['gamecube', 'wii'],
        'extensions': {
            'gamecube': ['.iso', '.gcm', '.gcz', '.rvz', '.wia'],
            'wii':      ['.iso', '.wbfs', '.gcz', '.rvz', '.wia'],
        },
        'args': ['{rom}'],
    },
    # ── Wii U ────────────────────────────────────────────────────────────────
    {
        'id':           'cemu',
        'name':         'Cemu',
        'binary_names': ['Cemu', 'cemu', 'info.cemu.Cemu'],
        'appimage_names': ['cemu'],
        'platforms':    ['wiiu'],
        'extensions': {
            'wiiu': ['.rpx', '.wud', '.wux', '.iso'],
        },
        'args': ['-g', '{rom}'],
    },
    # ── Nintendo Switch ──────────────────────────────────────────────────────
    {
        'id':           'ryujinx',
        'name':         'Ryujinx',
        'binary_names': ['Ryujinx', 'ryujinx', 'Ryujinx.sh', 'org.ryujinx.Ryujinx'],
        'appimage_names': ['ryujinx'],
        'platforms':    ['switch'],
        'extensions': {
            'switch': ['.nsp', '.pfs0', '.xci', '.nca', '.nro', '.nso'],
        },
        'args': ['{rom}'],
    },
    {
        'id':           'sudachi',
        'name':         'Sudachi',
        'binary_names': ['sudachi', 'sudachi-cmd'],
        'appimage_names': ['sudachi'],
        'platforms':    ['switch'],
        'extensions': {
            'switch': ['.nsp', '.pfs0', '.xci', '.nca', '.nro', '.nso'],
        },
        'args': ['{rom}'],
    },
    {
        'id':           'citron',
        'name':         'Citron',
        'binary_names': ['citron', 'citron-cmd', 'io.github.citron_emu.Citron'],
        'appimage_names': ['citron'],
        'platforms':    ['switch'],
        'extensions': {
            'switch': ['.nsp', '.pfs0', '.xci', '.nca', '.nro', '.nso'],
        },
        'args': ['{rom}'],
    },
    # ── NES ──────────────────────────────────────────────────────────────────
    {
        'id':           'fceux',
        'name':         'FCEUX',
        'binary_names': ['fceux', 'FCEUX'],
        'platforms':    ['nes'],
        'extensions': {
            'nes': ['.nes', '.fds', '.nsf', '.unf', '.unif'],
        },
        'args': ['{rom}'],
    },
    {
        'id':           'nestopia',
        'name':         'Nestopia UE',
        'binary_names': ['nestopia', 'ca._0ldsk00l.Nestopia'],
        'platforms':    ['nes'],
        'extensions': {
            'nes': ['.nes', '.fds', '.nsf', '.unf', '.unif'],
        },
        'args': ['{rom}'],
    },
    {
        'id':           'punes',
        'name':         'puNES',
        'binary_names': ['punes'],
        'platforms':    ['nes'],
        'extensions': {
            'nes': ['.nes', '.fds', '.nsf'],
        },
        'args': ['{rom}'],
    },
    {
        'id':           'mesen',
        'name':         'Mesen',
        'binary_names': ['mesen', 'Mesen'],
        'appimage_names': ['mesen'],
        'platforms':    ['nes', 'snes', 'gb', 'gbc', 'sms', 'gg', 'pce'],
        'extensions': {
            'nes':  ['.nes', '.fds', '.nsf', '.unf', '.unif'],
            'snes': ['.smc', '.sfc', '.fig', '.bsx', '.swc'],
            'gb':   ['.gb'],
            'gbc':  ['.gbc'],
            'sms':  ['.sms', '.sg'],
            'gg':   ['.gg'],
            'pce':  ['.pce'],
        },
        'args': ['{rom}'],
    },
    # ── SNES ─────────────────────────────────────────────────────────────────
    {
        'id':           'snes9x',
        'name':         'Snes9x',
        'binary_names': ['snes9x', 'snes9x-gtk', 'Snes9x', 'com.snes9x.Snes9x'],
        'platforms':    ['snes'],
        'extensions': {
            'snes': ['.smc', '.sfc', '.fig', '.gd3', '.gd7', '.dx2', '.bsx', '.swc'],
        },
        'args': ['{rom}'],
    },
    {
        'id':           'bsnes',
        'name':         'bsnes',
        'binary_names': ['bsnes', 'bsnes-hd', 'dev.bsnes.bsnes'],
        'platforms':    ['snes'],
        'extensions': {
            'snes': ['.smc', '.sfc', '.fig', '.bsx', '.swc'],
        },
        'args': ['{rom}'],
    },
    # ── Nintendo 64 ──────────────────────────────────────────────────────────
    {
        'id':           'mupen64plus',
        'name':         'mupen64plus',
        'binary_names': ['mupen64plus', 'rmg', 'RMG', 'com.github.Rosalie241.RMG'],
        'appimage_names': ['rmg'],
        'platforms':    ['n64'],
        'extensions': {
            'n64': ['.n64', '.z64', '.v64', '.rom', '.ndd'],
        },
        'args': ['{rom}'],
    },
    {
        'id':           'simple64',
        'name':         'simple64',
        'binary_names': ['simple64', 'simple64-gui'],
        'appimage_names': ['simple64'],
        'platforms':    ['n64'],
        'extensions': {
            'n64': ['.n64', '.z64', '.v64', '.rom', '.ndd'],
        },
        'args': ['{rom}'],
    },
    {
        'id':           'gopher64',
        'name':         'gopher64',
        'binary_names': ['gopher64', 'io.github.gopher64.gopher64'],
        'appimage_names': ['gopher64'],
        'platforms':    ['n64'],
        'extensions': {
            'n64': ['.n64', '.z64', '.v64', '.rom'],
        },
        'args': ['{rom}'],
    },
    {
        'id':           'm64p',
        'name':         'm64p',
        'binary_names': ['m64p', 'io.github.m64p.m64p'],
        'platforms':    ['n64'],
        'extensions': {
            'n64': ['.n64', '.z64', '.v64', '.rom', '.ndd'],
        },
        'args': ['{rom}'],
    },
    {
        'id':           'project64',
        'name':         'Project64',
        'binary_names': ['Project64', 'project64', 'Project64.exe'],
        'platforms':    ['n64'],
        'extensions': {
            'n64': ['.n64', '.z64', '.v64', '.rom', '.ndd'],
        },
        'args': ['{rom}'],
    },
    # ── Game Boy / GBC / GBA ─────────────────────────────────────────────────
    {
        'id':           'mgba',
        'name':         'mGBA',
        'binary_names': ['mgba', 'mgba-qt', 'io.mgba.mGBA'],
        'platforms':    ['gba', 'gbc', 'gb'],
        'extensions': {
            'gba': ['.gba', '.agb'],
            'gbc': ['.gbc'],
            'gb':  ['.gb'],
        },
        'args': ['{rom}'],
    },
    {
        'id':           'vbam',
        'name':         'VisualBoyAdvance-M',
        'binary_names': ['visualboyadvance-m', 'vbam', 'VisualBoyAdvance-M'],
        'platforms':    ['gba', 'gbc', 'gb'],
        'extensions': {
            'gba': ['.gba', '.agb'],
            'gbc': ['.gbc'],
            'gb':  ['.gb'],
        },
        'args': ['{rom}'],
    },
    {
        'id':           'sameboy',
        'name':         'SameBoy',
        'binary_names': ['sameboy', 'SameBoy', 'io.github.sameboy.SameBoy'],
        'platforms':    ['gb', 'gbc'],
        'extensions': {
            'gb':  ['.gb'],
            'gbc': ['.gbc'],
        },
        'args': ['{rom}'],
    },
    # ── Nintendo DS ──────────────────────────────────────────────────────────
    {
        'id':           'melonds',
        'name':         'melonDS',
        'binary_names': ['melonds', 'melonDS', 'net.kuribo64.melonDS'],
        'platforms':    ['nds'],
        'extensions': {
            'nds': ['.nds', '.dsi', '.ids'],
        },
        'args': ['{rom}'],
    },
    {
        'id':           'desmume',
        'name':         'DeSmuME',
        'binary_names': ['desmume', 'desmume-gtk', 'DeSmuME', 'org.desmume.DeSmuME'],
        'platforms':    ['nds'],
        'extensions': {
            'nds': ['.nds', '.dsi'],
        },
        'args': ['{rom}'],
    },
    # ── Nintendo 3DS ─────────────────────────────────────────────────────────
    {
        'id':           'citra',
        'name':         'Citra / Lime3DS',
        'binary_names': ['citra', 'citra-qt', 'lime3ds', 'lime3ds-gui', 'io.github.lime3ds.Lime3DS'],
        'platforms':    ['3ds'],
        'extensions': {
            '3ds': ['.3ds', '.3dsx', '.cci', '.cxi', '.cia'],
        },
        'args': ['{rom}'],
    },
    {
        'id':           'azahar',
        'name':         'Azahar',
        'binary_names': ['azahar', 'azahar-qt', 'org.azahar_emu.Azahar'],
        'platforms':    ['3ds'],
        'extensions': {
            '3ds': ['.3ds', '.3dsx', '.cci', '.cxi', '.cia'],
        },
        'args': ['{rom}'],
    },
    # ── Virtual Boy ──────────────────────────────────────────────────────────
    {
        'id':           'mednafen_vb',
        'name':         'Mednafen (Virtual Boy)',
        'binary_names': ['mednafen'],
        'platforms':    ['virtualboy'],
        'extensions': {
            'virtualboy': ['.vb', '.vboy'],
        },
        'args': ['{rom}'],
    },
    # ── PlayStation ──────────────────────────────────────────────────────────
    {
        'id':           'duckstation',
        'name':         'DuckStation',
        'binary_names': ['duckstation-qt', 'duckstation-nogui', 'duckstation', 'org.duckstation.DuckStation'],
        'appimage_names': ['duckstation'],
        'platforms':    ['ps1'],
        'extensions': {
            'ps1': ['.iso', '.bin', '.cue', '.chd', '.ecm', '.mds', '.pbp', '.exe', '.psx'],
        },
        'args': ['{rom}'],
    },
    # ── PlayStation 2 ────────────────────────────────────────────────────────
    {
        'id':           'pcsx2',
        'name':         'PCSX2',
        'binary_names': ['pcsx2', 'pcsx2-qt', 'pcsx2-avx2', 'PCSX2', 'net.pcsx2.PCSX2'],
        'appimage_names': ['pcsx2'],
        'platforms':    ['ps2'],
        'extensions': {
            'ps2': ['.iso', '.bin', '.mdf', '.gz', '.chd', '.cso', '.zso'],
        },
        'args': ['{rom}'],
    },
    {
        'id':           'epsxe',
        'name':         'ePSXe',
        'binary_names': ['epsxe', 'ePSXe', 'ePSXe.exe'],
        'platforms':    ['ps1'],
        'extensions': {
            'ps1': ['.iso', '.bin', '.cue', '.img', '.pbp', '.ecm'],
        },
        'args': ['{rom}'],
    },
    # ── PlayStation 2 (alternate) ────────────────────────────────────────────
    {
        'id':           'play',
        'name':         'Play!',
        'binary_names': ['Play', 'play', 'io.github.jpd002.Play'],
        'platforms':    ['ps2'],
        'extensions': {
            'ps2': ['.iso', '.bin', '.chd', '.cso'],
        },
        'args': ['{rom}'],
    },
    # ── PlayStation 3 ────────────────────────────────────────────────────────
    {
        'id':           'rpcs3',
        'name':         'RPCS3',
        'binary_names': ['rpcs3', 'net.rpcs3.RPCS3'],
        'appimage_names': ['rpcs3'],
        'platforms':    ['ps3'],
        'extensions': {
            'ps3': ['.pkg', '.iso'],
        },
        'args': ['--no-gui', '{rom}'],
        'scan_mode': 'ps3_folder',
    },
    # ── PSP ──────────────────────────────────────────────────────────────────
    {
        'id':           'ppsspp',
        'name':         'PPSSPP',
        'binary_names': ['ppsspp', 'ppsspp-qt', 'PPSSPPQt', 'PPSSPPHeadless', 'org.ppsspp.PPSSPP'],
        'platforms':    ['psp'],
        'extensions': {
            'psp': ['.iso', '.cso', '.pbp', '.elf', '.prx'],
        },
        'args': ['{rom}'],
    },
    # ── PlayStation Vita ─────────────────────────────────────────────────────
    {
        'id':           'vita3k',
        'name':         'Vita3K',
        'binary_names': ['Vita3K', 'vita3k', 'org.vita3k.Vita3K'],
        'appimage_names': ['vita3k-x86_64', 'vita3k'],
        'platforms':    ['psvita'],
        'extensions': {
            'psvita': ['.vpk', '.pkg'],
        },
        'args': ['-r', '{rom}'],
        'scan_mode': 'vita3k_app',
    },
    # ── Dreamcast ────────────────────────────────────────────────────────────
    {
        'id':           'flycast',
        'name':         'Flycast',
        'binary_names': ['flycast', 'flycast-dojo', 'org.flycast.Flycast'],
        'platforms':    ['dreamcast'],
        'extensions': {
            'dreamcast': ['.cdi', '.gdi', '.chd', '.cue', '.iso', '.bin'],
        },
        'args': ['{rom}'],
    },
    {
        'id':           'redream',
        'name':         'Redream',
        'binary_names': ['redream'],
        'appimage_names': ['redream'],
        'platforms':    ['dreamcast'],
        'extensions': {
            'dreamcast': ['.cdi', '.gdi', '.chd', '.cue', '.iso'],
        },
        'args': ['{rom}'],
    },
    # ── Saturn ───────────────────────────────────────────────────────────────
    {
        'id':           'yabause',
        'name':         'Yabause',
        'binary_names': ['yabause', 'yabause-qt', 'org.yabause.Yabause'],
        'platforms':    ['saturn'],
        'extensions': {
            'saturn': ['.iso', '.bin', '.cue', '.chd'],
        },
        'args': ['{rom}'],
    },
    {
        'id':           'kronos',
        'name':         'Kronos',
        'binary_names': ['kronos', 'kronos-qt', 'io.github.FCare.Kronos'],
        'platforms':    ['saturn'],
        'extensions': {
            'saturn': ['.iso', '.bin', '.cue', '.chd', '.mds'],
        },
        'args': ['{rom}'],
    },
    {
        'id':           'mednafen',
        'name':         'Mednafen',
        'binary_names': ['mednafen'],
        'platforms':    ['saturn', 'ps1', 'genesis', 'sms', 'gg', 'segacd', 'pce', 'lynx'],
        'extensions': {
            'saturn':  ['.iso', '.bin', '.cue', '.toc', '.m3u'],
            'ps1':     ['.iso', '.bin', '.cue', '.chd', '.ecm', '.mds', '.pbp'],
            'genesis': ['.md', '.gen', '.smd', '.bin'],
            'sms':     ['.sms', '.sg'],
            'gg':      ['.gg'],
            'segacd':  ['.iso', '.bin', '.cue', '.chd'],
            'pce':     ['.pce', '.cue', '.ccd', '.img'],
            'lynx':    ['.lnx', '.lyx'],
        },
        'args': ['{rom}'],
    },
    # ── Genesis / Mega Drive ─────────────────────────────────────────────────
    {
        'id':           'blastem',
        'name':         'BlastEm',
        'binary_names': ['blastem', 'com.retrodev.blastem'],
        'platforms':    ['genesis', 'sms'],
        'extensions': {
            'genesis': ['.md', '.gen', '.smd', '.bin', '.68k'],
            'sms':     ['.sms', '.sg'],
        },
        'args': ['{rom}'],
    },
    # ── Xbox (original) ──────────────────────────────────────────────────────
    {
        'id':           'xemu',
        'name':         'xemu',
        'binary_names': ['xemu', 'app.xemu.xemu'],
        'platforms':    ['xbox'],
        'extensions': {
            'xbox': ['.iso', '.xbe'],
        },
        'args': ['-dvd_path', '{rom}'],
    },
    {
        'id':           'cxbx_reloaded',
        'name':         'CXBX-Reloaded',
        'binary_names': ['cxbx-reloaded', 'CxbxReloaded', 'Cxbx-Reloaded.exe'],
        'platforms':    ['xbox'],
        'extensions': {
            'xbox': ['.iso', '.xbe'],
        },
        'args': ['{rom}'],
    },
    # ── Xbox 360 ─────────────────────────────────────────────────────────────
    {
        'id':           'xenia',
        'name':         'Xenia',
        'binary_names': ['xenia', 'xenia_canary', 'xenia-canary', 'Xenia.exe', 'xenia_canary.exe'],
        'platforms':    ['xbox360'],
        'extensions': {
            'xbox360': ['.iso', '.xex', '.zar'],
        },
        'args': ['{rom}'],
    },
    # ── PC Engine / TurboGrafx-16 ────────────────────────────────────────────
    # (also covered by Mednafen and RetroArch above/below)
    # ── Atari 2600 ───────────────────────────────────────────────────────────
    {
        'id':           'gopher2600',
        'name':         'Gopher2600',
        'binary_names': ['gopher2600'],
        'platforms':    ['atari2600'],
        'extensions': {
            'atari2600': ['.a26', '.bin', '.rom'],
        },
        'args': ['{rom}'],
    },
    {
        'id':           'stella',
        'name':         'Stella',
        'binary_names': ['stella', 'Stella', 'io.github.stella_emu.Stella'],
        'platforms':    ['atari2600'],
        'extensions': {
            'atari2600': ['.a26', '.bin', '.rom', '.gz'],
        },
        'args': ['{rom}'],
    },
    # ── Atari Lynx ───────────────────────────────────────────────────────────
    # (covered by Mednafen and RetroArch)
    # ── DOS ──────────────────────────────────────────────────────────────────
    {
        'id':           'dosbox_x',
        'name':         'DOSBox-X',
        'binary_names': ['dosbox-x', 'com.dosbox_x.DOSBox-X'],
        'platforms':    ['dos'],
        'extensions': {
            'dos': ['.conf', '.exe', '.bat', '.com'],
        },
        'args': ['{rom}'],
    },
    {
        'id':           'dosbox_staging',
        'name':         'DOSBox Staging',
        'binary_names': ['dosbox', 'dosbox-staging', 'io.github.dosbox-staging'],
        'platforms':    ['dos'],
        'extensions': {
            'dos': ['.conf', '.exe', '.bat', '.com'],
        },
        'args': ['{rom}'],
    },
    # ── Commodore 64 ─────────────────────────────────────────────────────────
    {
        'id':           'vice',
        'name':         'VICE',
        'binary_names': ['x64sc', 'x64', 'vice', 'x128'],
        'platforms':    ['c64'],
        'extensions': {
            'c64': ['.d64', '.t64', '.prg', '.d81', '.g64', '.tap', '.crt'],
        },
        'args': ['{rom}'],
    },
    # ── Arcade ───────────────────────────────────────────────────────────────
    {
        'id':           'mame',
        'name':         'MAME',
        'binary_names': ['mame', 'mame64', 'org.mamedev.MAME'],
        'platforms':    ['arcade'],
        'extensions': {
            'arcade': ['.zip', '.7z', '.chd'],
        },
        'args': ['-rompath', '{rom_dir}', '{rom_name}'],
    },
    {
        'id':           'fbneo',
        'name':         'FinalBurn Neo',
        'binary_names': ['fbneo', 'fbneo-sdl', 'FinalBurn Neo'],
        'platforms':    ['arcade'],
        'extensions': {
            'arcade': ['.zip', '.7z'],
        },
        'args': ['{rom}'],
    },
    # ── ares (multi-system) ───────────────────────────────────────────────────
    {
        'id':           'ares',
        'name':         'ares',
        'binary_names': ['ares'],
        'platforms':    ['nes', 'snes', 'n64', 'gb', 'gbc', 'gba',
                         'genesis', 'sms', 'gg', 'segacd', '32x', 'pce', 'saturn'],
        'extensions': {
            'nes':     ['.nes', '.fds'],
            'snes':    ['.smc', '.sfc', '.fig', '.bsx', '.swc'],
            'n64':     ['.n64', '.z64', '.v64', '.rom'],
            'gb':      ['.gb'],
            'gbc':     ['.gbc'],
            'gba':     ['.gba', '.agb'],
            'genesis': ['.md', '.gen', '.smd', '.bin'],
            'sms':     ['.sms', '.sg'],
            'gg':      ['.gg'],
            'segacd':  ['.iso', '.bin', '.cue', '.chd'],
            '32x':     ['.32x'],
            'pce':     ['.pce', '.cue', '.ccd'],
            'saturn':  ['.iso', '.bin', '.cue', '.toc'],
        },
        'args': ['{rom}'],
    },
    # ── ScummVM ──────────────────────────────────────────────────────────────
    {
        'id':           'scummvm',
        'name':         'ScummVM',
        'binary_names': ['scummvm', 'org.scummvm.ScummVM'],
        'platforms':    ['scummvm'],
        'extensions': {
            'scummvm': ['.scummvm'],
        },
        'args': ['{rom}'],
    },
    {
        'id':           'retroarch',
        'name':         'RetroArch',
        'binary_names': ['retroarch', 'org.libretro.RetroArch'],
        'platforms':    ['nes', 'snes', 'n64', 'gb', 'gbc', 'gba', 'nds',
                         'ps1', 'ps2', 'psp',
                         'genesis', 'sms', 'gg', 'segacd', '32x',
                         'saturn', 'dreamcast', 'pce',
                         'arcade', 'gamecube', 'wii',
                         'virtualboy', 'lynx', 'atari2600', 'dos', 'c64'],
        'extensions': {
            'nes':       ['.nes', '.fds', '.nsf', '.unf', '.unif'],
            'snes':      ['.smc', '.sfc', '.fig', '.gd3', '.gd7', '.dx2', '.bsx', '.swc'],
            'n64':       ['.n64', '.z64', '.v64', '.rom', '.ndd'],
            'gb':        ['.gb'],
            'gbc':       ['.gbc'],
            'gba':       ['.gba', '.agb'],
            'nds':       ['.nds', '.dsi'],
            'ps1':       ['.iso', '.bin', '.cue', '.chd', '.ecm', '.mds', '.pbp', '.exe', '.psx'],
            'ps2':       ['.iso', '.bin', '.mdf', '.gz', '.chd'],
            'psp':       ['.iso', '.cso', '.pbp'],
            'genesis':   ['.md', '.gen', '.smd', '.bin'],
            'sms':       ['.sms', '.sg'],
            'gg':        ['.gg'],
            'segacd':    ['.iso', '.bin', '.cue', '.chd'],
            '32x':       ['.32x'],
            'saturn':    ['.iso', '.bin', '.cue', '.toc', '.m3u'],
            'dreamcast': ['.cdi', '.gdi', '.chd', '.cue', '.iso', '.bin'],
            'pce':       ['.pce', '.cue', '.ccd'],
            'arcade':    ['.zip', '.7z', '.chd'],
            'gamecube':  ['.iso', '.gcm', '.gcz', '.rvz', '.wia'],
            'wii':       ['.iso', '.wbfs', '.gcz', '.rvz', '.wia'],
            'virtualboy':['.vb', '.vboy'],
            'lynx':      ['.lnx', '.lyx'],
            'atari2600': ['.a26'],
            'dos':       ['.conf'],
            'c64':       ['.d64', '.t64', '.prg'],
        },
        'args': ['-L', '{core}', '{rom}'],
        'cores_search': {
            'nes':       ['nestopia_libretro', 'fceumm_libretro', 'mesen_libretro'],
            'snes':      ['snes9x_libretro', 'bsnes_libretro', 'bsnes_mercury_balanced_libretro'],
            'n64':       ['mupen64plus_next_libretro', 'parallel_n64_libretro'],
            'gb':        ['gambatte_libretro', 'sameboy_libretro', 'mgba_libretro'],
            'gbc':       ['gambatte_libretro', 'sameboy_libretro', 'mgba_libretro'],
            'gba':       ['mgba_libretro', 'vba_next_libretro', 'gpsp_libretro'],
            'nds':       ['melonds_libretro', 'desmume_libretro', 'desmume2015_libretro'],
            'ps1':       ['beetle_psx_hw_libretro', 'beetle_psx_libretro', 'swanstation_libretro', 'pcsx_rearmed_libretro'],
            'ps2':       ['pcsx2_libretro'],
            'psp':       ['ppsspp_libretro'],
            'genesis':   ['genesis_plus_gx_libretro', 'picodrive_libretro', 'blastem_libretro'],
            'sms':       ['genesis_plus_gx_libretro', 'picodrive_libretro', 'smsplus_libretro'],
            'gg':        ['genesis_plus_gx_libretro', 'picodrive_libretro'],
            'segacd':    ['genesis_plus_gx_libretro', 'picodrive_libretro'],
            '32x':       ['picodrive_libretro'],
            'saturn':    ['beetle_saturn_libretro', 'yabasanshiro_libretro', 'kronos_libretro'],
            'dreamcast': ['flycast_libretro'],
            'pce':       ['beetle_pce_fast_libretro', 'beetle_pce_libretro'],
            'arcade':    ['mame_libretro', 'mame2003_plus_libretro', 'mame2010_libretro', 'fbneo_libretro'],
            'gamecube':  ['dolphin_libretro'],
            'wii':       ['dolphin_libretro'],
            'virtualboy':['beetle_vb_libretro'],
            'lynx':      ['handy_libretro', 'beetle_lynx_libretro'],
            'atari2600': ['stella2014_libretro', 'stella_libretro'],
            'dos':       ['dosbox_pure_libretro'],
            'c64':       ['vice_x64sc_libretro', 'vice_x64_libretro'],
        },
    },
]

# Flat extension → platform map for root-folder scanning
EXTENSION_PLATFORM_MAP: dict[str, str] = {}
for _emu in KNOWN_EMULATORS:
    for _plat, _exts in _emu['extensions'].items():
        for _ext in _exts:
            # Only record unambiguous extensions (first writer wins)
            if _ext not in EXTENSION_PLATFORM_MAP:
                EXTENSION_PLATFORM_MAP[_ext] = _plat
