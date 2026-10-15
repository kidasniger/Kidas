"""Menu de sélection de fichiers (terminal)."""
import os
import select
import shutil
import sys

from h2m.ui import die, human_size


def scan_html(folder):
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in (".html", ".htm")]
    return sorted(files, key=lambda p: p.name.lower())


def _read_key(fd):
    ch = os.read(fd, 1)
    if ch == b"\x1b":
        if select.select([fd], [], [], 0.05)[0]:
            seq = os.read(fd, 2)
            if seq == b"[A":
                return "up"
            if seq == b"[B":
                return "down"
        return "esc"
    if ch == b" ":
        return "space"
    if ch in (b"\r", b"\n"):
        return "enter"
    if ch == b"\x03":
        raise KeyboardInterrupt
    return ch.decode(errors="ignore")


def pick_file(files):
    """Retourne le fichier choisi (Path)."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        for i, f in enumerate(files, 1):
            print(f"  {i}. {f.name}")
        try:
            n = int(input("Numéro du fichier : ").strip())
            return files[n - 1]
        except (ValueError, IndexError):
            die("Choix invalide.")

    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    cur, mark = 0, None
    view = min(len(files), 10)
    top = 0
    block = view + 1
    first = True

    def render():
        nonlocal top
        cols = shutil.get_terminal_size((60, 20)).columns
        if cur < top:
            top = cur
        if cur >= top + view:
            top = cur - view + 1
        lines = []
        for i in range(top, top + view):
            f = files[i]
            ptr = "❯" if i == cur else " "
            box = "[x]" if i == mark else "[ ]"
            line = f"{ptr} {box} {f.name}  ({human_size(f.stat().st_size)})"
            line = line[: cols - 1]
            lines.append(f"\x1b[1;36m{line}\x1b[0m" if i == cur else line)
        more = f"  ({cur + 1}/{len(files)})" if len(files) > view else ""
        lines.append(f"\x1b[2m↑/↓ naviguer · Espace choisir · Entrée confirmer · q quitter{more}\x1b[0m")
        return lines

    print("\nFichiers HTML trouvés :\n")
    sys.stdout.write("\x1b[?25l")
    try:
        tty.setcbreak(fd)
        while True:
            if not first:
                sys.stdout.write(f"\x1b[{block}A")
            first = False
            for ln in render():
                sys.stdout.write("\x1b[2K" + ln + "\n")
            sys.stdout.flush()
            k = _read_key(fd)
            if k in ("up", "k"):
                cur = (cur - 1) % len(files)
            elif k in ("down", "j"):
                cur = (cur + 1) % len(files)
            elif k == "space":
                mark = None if mark == cur else cur
            elif k == "enter":
                choice = mark if mark is not None else cur
                return files[choice]
            elif k in ("q", "esc"):
                print("\nAnnulé.")
                sys.exit(0)
            elif k.isdigit() and k != "0" and int(k) <= len(files):
                cur = int(k) - 1
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        sys.stdout.write("\x1b[?25h")
        sys.stdout.flush()
