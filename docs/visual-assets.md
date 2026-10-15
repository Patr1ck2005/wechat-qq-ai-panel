# Visual assets

The original blue/indigo conversation cards and aqua sparkle are the project's
application identity. The same artwork is used by the Windows shortcut, window,
tray and panel header. It does not use upstream WeChat or QQ logo assets.

## Rebuild icons

Run with the installed panel environment (Pillow is already locked):

```powershell
./.venv/Scripts/python.exe -I ./scripts/build-brand.py
```

This writes `wq_panel/assets/app.svg`, `app.png` and `app.ico`. The SVG remains
editable and font-free. The ICO includes 16, 20, 24, 32, 40, 48, 64, 128 and 256 px
frames for desktop, title bar and display scaling. No account, model or network
access is involved.

## Update an existing desktop shortcut

```powershell
./scripts/update-shortcut.ps1
```

This changes the launcher and icon without reinstalling dependencies or opening
the app. Existing access configuration selection is preserved. A complete quit
and reopen loads new window, tray and panel-header artwork. Windows can retain
an older icon in its shell cache briefly; no system cache is deleted by this
project.

## README illustrations

Each repository owns its product overview and interface preview under
`docs/assets/`. The editable, self-contained SVGs use invented account names,
conversations and message text. They are explicitly marked as synthetic demos;
they are neither captured private chats nor evidence of live model acceptance.
No screenshot of an operator's desktop is used.

All new artwork and generation code use this repository's MIT license. Public
source selection includes the explicit artwork names and checks local README
image references. Runtime data and private deployment state remain excluded.
