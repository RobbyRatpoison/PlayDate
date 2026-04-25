# Steam Deck Installation — Implementation Plan

Support first-class Steam Deck installation with a dedicated script and a graceful error message when deps are wiped by a SteamOS update.

## `install_steamdeck.sh`

- Check if a sudo password is set; if not, print a message telling the user to run `passwd` and exit
- `sudo steamos-readonly disable`
- `sudo pacman-key --init && sudo pacman-key --populate archlinux`
- `sudo pacman -S --noconfirm python-gobject webkit2gtk`
- Run `install.sh`
- `sudo steamos-readonly enable`
- Script doubles as repair script -- safe to re-run after a SteamOS update wipes the packages

## `main.py` Import Guard

- Wrap the pywebview import in a try/except ImportError
- Check `/etc/os-release` for `ID=steamos` to tailor the message
- SteamOS: show a tkinter messagebox telling the user to re-run `install_steamdeck.sh`
- Other Linux: show a generic "reinstall dependencies" message pointing to the README
- Use tkinter (same as uninstaller) so it works without pywebview

## README

- Add a Steam Deck subsection under Linux
- Cover: set a password first (`passwd`), run `install_steamdeck.sh`, note that packages are wiped on SteamOS updates and the script should be re-run to restore them

## Release Notes

- Brief mention of Steam Deck support, point to README for details
