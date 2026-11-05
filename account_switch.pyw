# -*- coding: utf-8 -*-
"""官方 ROM Classic 帳號切換（測試版）。

副檔名是 .pyw：雙擊就開，不會多一個黑色視窗（跟 gui.pyw 一樣）。出錯會跳視窗並存到錯誤紀錄檔。

遊戲把「記住的登入」存在使用者資料夾裡只有一份：
    %USERPROFILE%\\AppData\\LocalLow\\X_D_ Network Inc_\\ROM Classic\\XD\\PC\\
（access_token_v2、user_v2、agreement、latest_agreement）＋同一層的 .userdata
所以不管開哪個遊戲資料夾，都會用最後登入的那隻。

這個工具：
  記住目前的帳號 → 把上面那些檔案備份到 accounts\\名字\\
  換成選的帳號   → 把那隻的備份放回去，之後「新開」的遊戲就是那隻
                   （已經開著的不受影響；新開的出現「開始遊戲」前不要再換）

注意：備份等於帳號的通行證，只留在自己電腦，不要傳給任何人。
備份放在 %LOCALAPPDATA%\\ROM_helper\\accounts（本機、不會被 OneDrive 同步到雲端）。
以前放在程式旁邊的 accounts（可能在 OneDrive 裡），第一次打開會自動搬過去。
"""
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OLD_VAULT = os.path.join(BASE_DIR, "accounts")          # 舊位置：程式旁邊（常常在 OneDrive 裡）
VAULT = os.path.join(os.environ.get("LOCALAPPDATA")
                     or os.path.join(os.path.expanduser("~"), "AppData", "Local"),
                     "ROM_helper", "accounts")            # 新位置：本機，不同步
AUTO_BACKUP = "_換之前的自動備份"
GAME_EXE = "ro_win.exe"
EXTRA_FILES = [".userdata"]                     # 跟 XD 同一層、換帳號也會變的檔案


def game_root():
    """...\\LocalLow\\X_D_ Network Inc_\\ROM Classic（找不到回傳 None）。"""
    low = os.path.join(os.path.expanduser("~"), "AppData", "LocalLow")
    exact = os.path.join(low, "X_D_ Network Inc_", "ROM Classic")
    if os.path.isdir(os.path.join(exact, "XD", "PC")):
        return exact
    for cand in glob.glob(os.path.join(low, "*Network Inc*", "ROM Classic")):
        if os.path.isdir(os.path.join(cand, "XD", "PC")):
            return cand
    return None


def login_files(root):
    """目前這份登入資料包含哪些檔案：{相對路徑: 完整路徑}。"""
    out = {}
    pc = os.path.join(root, "XD", "PC")
    for name in os.listdir(pc):
        p = os.path.join(pc, name)
        if os.path.isfile(p):
            out[os.path.join("XD", "PC", name)] = p
    for name in EXTRA_FILES:
        p = os.path.join(root, name)
        if os.path.isfile(p):
            out[name] = p
    return out


def file_md5(path):
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def game_running():
    """官方遊戲（ro_win.exe）有沒有開著。"""
    try:
        r = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {GAME_EXE}", "/NH"],
                           capture_output=True, text=True, creationflags=0x08000000)
        return GAME_EXE.lower() in r.stdout.lower()
    except Exception:
        return False


def safe_name(name):
    name = re.sub(r'[\\/:*?"<>|]', "_", name.strip())
    return name[:60]


def retry(fn, *args, tries=5):
    """檔案偶爾被別的程式（防毒、同步）短暫鎖住：等一下再試。"""
    for i in range(tries):
        try:
            return fn(*args)
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.5)


def save_account(root, name):
    """把目前的登入資料存成 VAULT\\name\\（直接寫檔，不改資料夾名稱，OneDrive 也不會卡）。"""
    dest = os.path.join(VAULT, name)
    os.makedirs(dest, exist_ok=True)
    files = login_files(root)
    for dirpath, _, fs in os.walk(dest):          # 舊的備份裡有、現在沒有的檔案刪掉
        for f in fs:
            rel = os.path.relpath(os.path.join(dirpath, f), dest)
            if rel != "info.json" and rel not in files:
                retry(os.remove, os.path.join(dirpath, f))
    for rel, src in files.items():
        p = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        retry(shutil.copy2, src, p)
    with open(os.path.join(dest, "info.json"), "w", encoding="utf-8") as f:
        json.dump({"saved": time.strftime("%Y-%m-%d %H:%M")}, f, ensure_ascii=False)
    return len(files)


def migrate_old_vault():
    """以前的備份放在程式旁邊（可能被 OneDrive 傳到雲端）：搬到本機的新位置。回傳要給使用者看的訊息。"""
    if not os.path.isdir(OLD_VAULT) or os.path.abspath(OLD_VAULT) == os.path.abspath(VAULT):
        return ""
    moved = []
    for name in os.listdir(OLD_VAULT):
        src = os.path.join(OLD_VAULT, name)
        if not os.path.isdir(src) or name.endswith(".tmp"):
            continue
        dest = os.path.join(VAULT, name)
        if os.path.isdir(dest):
            continue                               # 新位置已經有了，不蓋掉
        shutil.copytree(src, dest)
        moved.append(name)
    try:
        shutil.rmtree(OLD_VAULT)
        left = ""
    except Exception:
        left = (f"\n\n舊的資料夾刪不掉（可能 OneDrive 正在同步），請之後手動刪除：\n{OLD_VAULT}\n"
                "（裡面是帳號通行證，不要留在會同步到雲端的地方）")
    if not moved and not left:
        return ""
    return (f"已把 {len(moved)} 個帳號備份搬到本機：\n{VAULT}" if moved else "") + left


def restore_account(root, name):
    """把 accounts\\name\\ 的登入資料放回遊戲讀取的位置。"""
    src_dir = os.path.join(VAULT, name)
    wanted = {}
    for dirpath, _, files in os.walk(src_dir):
        for f in files:
            if f == "info.json":
                continue
            p = os.path.join(dirpath, f)
            wanted[os.path.relpath(p, src_dir)] = p
    if not any(r.startswith(os.path.join("XD", "PC")) for r in wanted):
        raise RuntimeError("這份備份裡沒有登入資料，可能壞了")
    current = login_files(root)
    for rel, p in current.items():               # 備份裡沒有的就刪掉，免得混到別隻的資料
        if rel not in wanted:
            os.remove(p)
    for rel, p in wanted.items():
        dest = os.path.join(root, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(p, dest)
    return len(wanted)


def saved_accounts():
    if not os.path.isdir(VAULT):
        return []
    names = [d for d in os.listdir(VAULT)
             if os.path.isdir(os.path.join(VAULT, d)) and not d.endswith(".tmp")]
    return sorted(names, key=lambda n: (n == AUTO_BACKUP, n))


def who_is_current(root):
    """目前遊戲讀的這份登入資料是哪一隻（比對 user_v2）。"""
    cur = os.path.join(root, "XD", "PC", "user_v2")
    if not os.path.isfile(cur):
        return None
    h = file_md5(cur)
    for name in saved_accounts():
        if name == AUTO_BACKUP:
            continue
        p = os.path.join(VAULT, name, "XD", "PC", "user_v2")
        if os.path.isfile(p) and file_md5(p) == h:
            return name
    return ""


class App:
    def __init__(self, root_win):
        self.win = root_win
        root_win.title("官方帳號切換（測試）")
        root_win.geometry("560x660")
        self.root = game_root()

        top = ttk.Frame(root_win, padding=10)
        top.pack(fill="both", expand=True)
        self.status = ttk.Label(top, font=("Microsoft JhengHei", 11, "bold"))
        self.status.pack(anchor="w")
        ttk.Label(top, text="備份等於帳號的通行證，只留在自己電腦，不要傳給任何人。",
                  foreground="#c01c28").pack(anchor="w", pady=(2, 0))
        ttk.Label(top, text=f"備份位置（本機，不會同步到雲端）：{VAULT}",
                  foreground="#666", wraplength=490).pack(anchor="w", pady=(0, 8))

        ttk.Label(top, text="記住的帳號：").pack(anchor="w")
        self.lst = tk.Listbox(top, height=10, font=("Microsoft JhengHei", 10))
        self.lst.pack(fill="both", expand=True)

        bar = ttk.Frame(top)
        bar.pack(fill="x", pady=8)
        ttk.Button(bar, text="記住目前的帳號…", command=self.on_save).pack(side="left", padx=2)
        ttk.Button(bar, text="換成選的帳號", command=self.on_restore).pack(side="left", padx=2)
        ttk.Button(bar, text="刪除選的", command=self.on_delete).pack(side="left", padx=2)
        ttk.Button(bar, text="重新整理", command=lambda: self.refresh(say=True)).pack(side="right", padx=2)
        ttk.Button(bar, text="打開備份資料夾", command=self.open_vault).pack(side="right", padx=2)

        # 跟 gui.pyw 一樣的紀錄區：做到哪、成功或出錯都寫在這裡
        logbox = ttk.LabelFrame(top, text="紀錄", padding=(4, 2))
        logbox.pack(fill="both", expand=True)
        row = ttk.Frame(logbox)
        row.pack(fill="both", expand=True)
        self.logtext = tk.Text(row, height=9, wrap="word", font=("Consolas", 10),
                               bg="#1e1e1e", fg="#dcdcdc", insertbackground="#dcdcdc")
        sb = ttk.Scrollbar(row, command=self.logtext.yview)
        self.logtext.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.logtext.pack(side="left", fill="both", expand=True)
        for tag, color in (("ok", "#6ac46a"), ("bad", "#e06c6c"), ("head", "#6cb6ff"), ("warn", "#e0b060")):
            self.logtext.tag_config(tag, foreground=color)
        ttk.Button(logbox, text="清除紀錄",
                   command=lambda: self.logtext.delete("1.0", "end")).pack(anchor="e", pady=(2, 0))

        global APP
        APP = self
        self.log("打開帳號切換工具", "head")
        os.makedirs(VAULT, exist_ok=True)
        note = migrate_old_vault()
        if note:
            self.log(note.replace("\n", " "), "warn")
            messagebox.showinfo("帳號備份搬家了", note)
        self.refresh(say=True)

    def log(self, text, tag=None):
        self.logtext.insert("end", time.strftime("[%H:%M:%S] ") + text + "\n", tag)
        self.logtext.see("end")

    def open_vault(self):
        os.makedirs(VAULT, exist_ok=True)
        os.startfile(VAULT)

    def refresh(self, say=False):
        self.root = game_root()
        if not self.root:
            self.status.configure(text="找不到官方的登入資料夾（先用官方登入過一次）", foreground="#c01c28")
            if say:
                self.log("找不到官方的登入資料夾：這台電腦要先用官方登入過一次", "bad")
            return
        who = who_is_current(self.root)
        run = "　｜　官方遊戲：開著" if game_running() else "　｜　官方遊戲：關著"
        if say:
            self.log(f"目前登入的是：{who or '（還沒記住過的帳號）'}{run.replace('　｜　', '，')}"
                     f"；記住了 {len([n for n in saved_accounts() if n != AUTO_BACKUP])} 個帳號")
        if who:
            self.status.configure(text=f"目前登入的是：{who}{run}", foreground="#26a269")
        else:
            self.status.configure(text=f"目前登入的是：（還沒記住過的帳號）{run}", foreground="#1a5fb4")
        self.lst.delete(0, "end")
        for name in saved_accounts():
            try:
                with open(os.path.join(VAULT, name, "info.json"), encoding="utf-8") as f:
                    when = json.load(f).get("saved", "")
            except Exception:
                when = ""
            mark = "（目前）" if name == who else ""
            label = "換帳號前自動留的備份" if name == AUTO_BACKUP else name
            self.lst.insert("end", f"{label}{mark}　　記住於 {when}")

    def selected(self):
        sel = self.lst.curselection()
        if not sel:
            messagebox.showinfo("先選一個", "請先在清單上點一個帳號。")
            return None
        return saved_accounts()[sel[0]]

    def on_save(self):
        if not self.root:
            return
        name = simpledialog.askstring("記住目前的帳號",
                                      "目前遊戲登入的是哪一隻？取個名字（例如 帳號A）：",
                                      parent=self.win)
        if not name:
            return
        name = safe_name(name)
        if not name or name == AUTO_BACKUP:
            messagebox.showinfo("名字不行", "換一個名字。")
            return
        if name in saved_accounts() and not messagebox.askyesno(
                "已經有了", f"「{name}」已經記住過了，要用目前的登入蓋掉嗎？"):
            return
        self.log(f"記住目前的帳號 → 「{name}」", "head")
        n = save_account(self.root, name)
        self.log(f"已記住「{name}」（存了 {n} 個登入檔案）", "ok")
        self.refresh()

    def on_restore(self):
        if not self.root:
            return
        name = self.selected()
        if not name:
            return
        if game_running() and not messagebox.askyesno(
                "官方遊戲開著",
                "官方遊戲有開著。\n\n"
                "換了之後只影響「接下來新開」的遊戲，已經開著的不受影響"
                "（跟你平常開著一個、再去另一個登入別隻是一樣的）。\n\n"
                "注意：新開的遊戲出現「開始遊戲」之前，不要再換下一隻。\n\n要換嗎？"):
            return
        label = "換帳號前自動留的備份" if name == AUTO_BACKUP else name
        self.log(f"換成「{label}」", "head")
        if game_running():
            self.log("官方遊戲開著：只影響接下來新開的遊戲，已經開著的不受影響", "warn")
        who = who_is_current(self.root)
        if who == "":                             # 目前這份沒記住過：先留一份，免得弄丟
            save_account(self.root, AUTO_BACKUP)
            self.log("目前的登入還沒記住過，先自動留一份「換帳號前自動留的備份」", "warn")
        n = restore_account(self.root, name)
        self.log(f"已把「{label}」的登入資料放回去（{n} 個檔案）")
        now = who_is_current(self.root)
        if name == AUTO_BACKUP or now == name:
            self.log(f"確認：現在的登入資料是「{label}」。打開一個官方遊戲，就會直接是這隻", "ok")
            self.log("要多開的話：等這個遊戲出現「開始遊戲」之後，再換下一隻、開下一個")
        else:
            self.log(f"放回去之後檢查不是「{label}」（讀到的是：{now or '不明'}），請再按一次或重新記住這隻", "bad")
        self.refresh()

    def on_delete(self):
        name = self.selected()
        if not name:
            return
        label = "換帳號前自動留的備份" if name == AUTO_BACKUP else name
        if messagebox.askyesno("刪除", f"確定刪除「{label}」的備份？（不會影響遊戲，只是之後要重新記住）"):
            shutil.rmtree(os.path.join(VAULT, name), ignore_errors=True)
            self.log(f"已刪除「{label}」的備份", "warn")
            self.refresh()


ERROR_LOG = os.path.join(BASE_DIR, "account_switch_錯誤紀錄.txt")
APP = None                       # 視窗開好後指向 App，出錯時也寫進紀錄區


def show_error(text):
    """.pyw 沒有黑色視窗，出錯看不到：跳視窗告訴使用者，完整內容存成文字檔。"""
    try:
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("==== %Y-%m-%d %H:%M:%S ====\n") + text + "\n")
    except Exception:
        pass
    last = "\n".join(text.strip().splitlines()[-3:])
    if APP is not None:
        try:
            APP.log("出錯了：" + text.strip().splitlines()[-1], "bad")
            APP.log(f"完整內容存在：{ERROR_LOG}", "bad")
        except Exception:
            pass
    messagebox.showerror("出錯了", f"{last}\n\n完整內容存在：\n{ERROR_LOG}\n（把這個檔案的內容貼給 Claude）")


if __name__ == "__main__":
    import traceback
    w = tk.Tk()
    # 按鈕裡出的錯（例如以前 OneDrive 鎖住資料夾）也要跳出來，不然 .pyw 會默默沒反應
    w.report_callback_exception = lambda *exc: show_error("".join(traceback.format_exception(*exc)))
    try:
        App(w)
    except Exception:
        show_error(traceback.format_exc())
        raise
    w.mainloop()
