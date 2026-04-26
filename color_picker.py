"""Standalone eyedropper: takes a screenshot, shows a fullscreen tkinter overlay,
prints the picked hex color to stdout, or exits with code 1 on cancel/error."""
import sys
import tkinter as tk
from PIL import Image, ImageTk, ImageGrab

def main():
    screenshot = ImageGrab.grab()
    sw, sh = screenshot.size

    result = [None]

    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes('-topmost', True)
    root.geometry(f'{sw}x{sh}+0+0')

    canvas = tk.Canvas(root, width=sw, height=sh, highlightthickness=0,
                       cursor='none', bg='black')
    canvas.pack()

    photo = ImageTk.PhotoImage(screenshot)
    canvas.create_image(0, 0, anchor='nw', image=photo)

    MAG_PIXELS = 15
    MAG_ZOOM   = 8
    MAG_SIZE   = MAG_PIXELS * MAG_ZOOM
    OFFSET     = 24
    state      = {'items': [], 'mag_photo': None}

    def _update(event):
        x, y = event.x, event.y
        px, py = max(0, min(x, sw - 1)), max(0, min(y, sh - 1))
        r, g, b = screenshot.getpixel((px, py))[:3]
        hex_color = f'#{r:02x}{g:02x}{b:02x}'

        half = MAG_PIXELS // 2
        x1 = max(0, px - half); y1 = max(0, py - half)
        x2 = min(sw, x1 + MAG_PIXELS); y2 = min(sh, y1 + MAG_PIXELS)
        region = screenshot.crop((x1, y1, x2, y2)).resize(
            (MAG_SIZE, MAG_SIZE), Image.NEAREST)

        mx = x + OFFSET
        my = y + OFFSET
        if mx + MAG_SIZE + 4 > sw:
            mx = x - MAG_SIZE - OFFSET
        if my + MAG_SIZE + 26 > sh:
            my = y - MAG_SIZE - OFFSET - 22

        for item in state['items']:
            canvas.delete(item)
        items = []

        mag_photo = ImageTk.PhotoImage(region)
        state['mag_photo'] = mag_photo

        items.append(canvas.create_rectangle(
            mx - 2, my - 2, mx + MAG_SIZE + 2, my + MAG_SIZE + 2,
            fill='black', outline='white', width=2))
        items.append(canvas.create_image(mx, my, anchor='nw', image=mag_photo))

        cx = mx + MAG_SIZE // 2
        cy = my + MAG_SIZE // 2
        items.append(canvas.create_line(cx, my, cx, my + MAG_SIZE, fill='white', width=1))
        items.append(canvas.create_line(mx, cy, mx + MAG_SIZE, cy, fill='white', width=1))

        lx = mx + MAG_SIZE // 2
        ly = my + MAG_SIZE + 4
        items.append(canvas.create_rectangle(
            mx - 2, ly - 2, mx + MAG_SIZE + 2, ly + 20,
            fill='black', outline=''))
        items.append(canvas.create_text(
            lx, ly + 8, text=hex_color,
            fill='white', font=('monospace', 12, 'bold')))

        CH = 10
        items.append(canvas.create_line(x - CH, y, x - 2, y, fill='white', width=1))
        items.append(canvas.create_line(x + 2, y, x + CH, y, fill='white', width=1))
        items.append(canvas.create_line(x, y - CH, x, y - 2, fill='white', width=1))
        items.append(canvas.create_line(x, y + 2, x, y + CH, fill='white', width=1))

        state['items'] = items

    def _on_click(event):
        px, py = max(0, min(event.x, sw - 1)), max(0, min(event.y, sh - 1))
        r, g, b = screenshot.getpixel((px, py))[:3]
        result[0] = f'#{r:02x}{g:02x}{b:02x}'
        root.quit()

    canvas.bind('<Motion>', _update)
    canvas.bind('<Button-1>', _on_click)
    root.bind('<Escape>', lambda _e: root.quit())
    root.focus_force()
    root.mainloop()
    root.destroy()

    if result[0]:
        print(result[0])
        sys.exit(0)
    sys.exit(1)

if __name__ == '__main__':
    main()
