#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ROM Classic 日常自動化 — 圖形介面（第二版）
==========================================

三個分頁：
    控制台  勾選要做的任務、選視窗、開始 / 停止、看紀錄
    校正    「按抓取 → 把滑鼠移到目標上 → 3 秒後自動記錄」，不用在別的視窗拖框
    設定    快捷鍵、比對門檻、等待方式等，存進 config.json

校正的原理：先按「固定視窗」把某個遊戲視窗搬到工作位置（左上角 800×500），
然後把滑鼠移到按鈕上按抓取，程式會把滑鼠周圍一小塊畫面存成模板圖。
因為每次跑都會把視窗搬到同樣的位置和大小，所以這張圖在 12 個帳號上都通用。

點兩下 gui.pyw 就能開。這個視窗會停在螢幕右邊，不要拖到左上角去擋遊戲。
"""

import json
import os
import queue
import re
import shutil
import sys
import threading
import zipfile
import tkinter as tk
from tkinter import messagebox, ttk

__version__ = "2026.11.11e"

# 需要另外裝的套件：import 名稱 → pip 安裝名稱
_PIP_NAMES = {"cv2": "opencv-python", "pyautogui": "pyautogui", "PIL": "pillow",
              "numpy": "numpy", "win32api": "pywin32", "win32gui": "pywin32",
              "win32con": "pywin32", "win32process": "pywin32", "win32clipboard": "pywin32"}


def _missing_package(err):
    """雙擊 .pyw 用的 Python 可能跟 start.bat 的不是同一個（電腦裡有好幾個 Python），
    那個 Python 沒裝套件就會一打開就失敗，又沒有黑色視窗看不到錯誤 → 看起來「點了沒反應」。
    這裡跳視窗講清楚，並問要不要直接幫「這個 Python」裝好。"""
    import subprocess
    mod = (getattr(err, "name", "") or "").split(".")[0]
    pkgs = sorted(set(_PIP_NAMES.values()))
    exe = sys.executable
    console_py = exe[:-len("pythonw.exe")] + "python.exe" if exe.lower().endswith("pythonw.exe") else exe
    r = tk.Tk(); r.withdraw()
    ok = messagebox.askyesno(
        "ROM 日常助手：缺少套件",
        f"打開時用的 Python 沒有裝「{_PIP_NAMES.get(mod, mod)}」。\n\n"
        f"這次用的 Python：\n{exe}\n\n"
        "（電腦裡如果有好幾個 Python，雙擊和 start.bat 用的可能不是同一個。）\n\n"
        "要現在幫這個 Python 把需要的套件都裝好嗎？\n"
        "會跳出一個黑色視窗安裝，跑完再雙擊一次 gui.pyw 就可以了。")
    if ok:
        try:
            subprocess.Popen([console_py, "-m", "pip", "install"] + pkgs,
                             creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        except Exception as e:
            messagebox.showerror("安裝失敗", f"沒辦法自動安裝：{e}\n\n可以在黑色視窗輸入：\n"
                                 f"\"{console_py}\" -m pip install " + " ".join(pkgs))
    raise SystemExit(1)


def _check_files_beside():
    """gui.pyw 旁邊一定要有 rom_daily.py、rom_party.py。
    朋友常在壓縮檔裡直接雙擊 gui.pyw：Windows 只把這一個檔案拿到暫存資料夾執行，
    旁邊的檔案都不在 → 原本會跳看不懂的英文錯誤（No module named 'rom_daily'）。這裡改講白話。"""
    import tempfile
    here = os.path.dirname(os.path.abspath(__file__))
    missing = [f for f in ("rom_daily.py", "rom_party.py") if not os.path.isfile(os.path.join(here, f))]
    if not missing:
        return
    low = here.lower()
    try:
        tmp = os.path.normcase(os.path.abspath(tempfile.gettempdir()))
    except Exception:
        tmp = ""
    in_zip = ".zip" in low or (tmp and os.path.normcase(here).startswith(tmp))
    r = tk.Tk(); r.withdraw()
    if in_zip:
        messagebox.showerror(
            "ROM 日常助手：請先解壓縮",
            "你是在壓縮檔（.zip）裡面直接打開 gui.pyw 的，\n"
            "這樣 Windows 只會拿出這一個檔案，其他程式檔都不在，所以開不起來。\n\n"
            "請這樣做：\n"
            "1. 關掉這個視窗\n"
            "2. 在下載的 zip 檔上按右鍵 →「解壓縮全部」\n"
            "   （Windows 11 可能要先按「顯示其他選項」）\n"
            "3. 打開解壓縮出來的資料夾，找到 gui.pyw、rom_daily.py 那一層\n"
            "4. 在那裡雙擊 gui.pyw\n\n"
            "之後都從解壓縮出來的資料夾開，zip 檔可以刪掉。")
    else:
        messagebox.showerror(
            "ROM 日常助手：缺少程式檔",
            "gui.pyw 旁邊找不到：" + "、".join(missing) + "\n\n"
            f"目前的資料夾：\n{here}\n\n"
            "這幾個檔案要放在同一個資料夾裡：\n"
            "gui.pyw、rom_daily.py、rom_party.py、account_switch.pyw\n\n"
            "請把下載的整包重新解壓縮，或把缺的檔案放回這個資料夾。")
    raise SystemExit(1)


_check_files_beside()

try:
    import cv2
    import pyautogui
    from PIL import Image, ImageTk
    import rom_daily as rd
    import rom_party as rp
except Exception as _e:
    if isinstance(_e, ModuleNotFoundError) and (getattr(_e, "name", "") or "").split(".")[0] in _PIP_NAMES:
        _missing_package(_e)                     # 缺套件：講清楚是哪個 Python，問要不要幫忙裝
    import traceback, tkinter as _tk, tkinter.messagebox as _mb
    _t = traceback.format_exc()
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui_error.log"),
                  "a", encoding="utf-8") as _f:
            _f.write("=" * 60 + "\n" + _t + "\n")
    except Exception:
        pass
    _r = _tk.Tk(); _r.withdraw()
    _mb.showerror("ROM 日常助手 啟動失敗（載入主程式時）", "\n".join(_t.strip().splitlines()[-8:]))
    raise SystemExit(1)

# 三個檔案要一起更新。版本對不上就直接講，不要跑到一半才炸。
_versions = {"gui.pyw": __version__,
             "rom_daily.py": getattr(rd, "__version__", "（舊版，沒有版本號）"),
             "rom_party.py": getattr(rp, "__version__", "（舊版，沒有版本號）")}
if len(set(_versions.values())) > 1:
    import tkinter as _tk, tkinter.messagebox as _mb
    _r = _tk.Tk(); _r.withdraw()
    _lines = "\n".join(f"{k}：{v}" for k, v in _versions.items())
    _mb.showerror("檔案版本不一致",
                  "三個程式檔要一起更新，目前的版本：\n\n" + _lines +
                  "\n\n請從最新的 ROM_final.zip 把三個檔案一起蓋掉。")
    raise SystemExit(1)

# 每張模板：檔名、說明、預設抓取大小 (寬, 高)、類型
#   btn  = 普通按鈕，抓一張就好
#   row  = 日常清單的一列，抓完文字還要再抓一次「這列右邊的按鈕在哪」
# 校正項目依「遊戲畫面」分組。每組寫清楚怎麼切到那個畫面，
# 然後才列該畫面上要抓的東西。required=False 的是選用，缺了不亮警告。
#   ("tmpl", 檔名, 說明, (寬, 高), 類型, required)      模板圖
#   ("point", 設定鍵, 說明, required)                   一個位置
#   ("grid",)                                           寵物打工九宮格
CALIB_GROUPS = [
    {"title": "主畫面",
     "how": "把遊戲切回主畫面，不要開任何面板",
     "items": [
         ("tmpl", "main_mark.png", "主畫面標記：建議框上方的「隊伍」圖示（圖案固定不會動，暗色地圖也認得到；"
          "以前抓的 ACT 按鈕可以留著，再按一次抓取把「隊伍」加進來）", (52, 52), "btn", True),
         ("tmpl", "hotspot.png", "上方「熱點」按鈕", (52, 52), "btn", True),
         ("tmpl", "daily.png", "上方「日常」按鈕（沒快捷鍵的環境必要）", (52, 52), "btn", "nokey"),
         ("point", "daily_btn", "上方「日常」按鈕的位置（認不到圖示時改點這裡；雷電預設 492, 45，通常不用動）", False),
         ("tmpl", "disconnect.png", "斷線時跳出的視窗（例如「重新連線」按鈕；有機會就抓一張）", (120, 40), "btn", False),
         ("tmpl", "dead_btn.png", "角色死亡時的綠色「回到記錄點」按鈕（看到會先點它）", (110, 34), "btn", False),
         ("point", "wake_click", "省電模式喚醒點：寵物箱左邊一點點的空地（每個視窗開始前先點一下；雷電預設 471, 366，官方不用）", False),
     ]},
    {"title": "日常面板",
     "how": "在主畫面按 I",
     "items": [
         ("tmpl", "daily_panel.png", "左上角「日常」分頁標題", (60, 28), "btn", False),
         ("point", "weekly_tab", "「週常」分頁的位置（已內建，跑掉才需要重抓）", False),
         ("tmpl", "commission_row.png", "「【任務委託板】」那幾個字（抓完會再問按鈕位置）", (112, 24), "row", True),
         ("tmpl", "row_done.png", "清單右邊灰色的打勾（已完成）", (44, 44), "btn", True),
         ("tmpl", "claim.png", "黃色「領取」按鈕", (84, 30), "btn", True),
         ("tmpl", "claim_all.png", "黃色「一鍵領取」按鈕", (96, 30), "btn", False),
         ("tmpl", "back_btn.png", "面板左上角的返回鍵", (44, 44), "btn", True),
         ("point", "safe_click", "關彈窗時點的空白處（面板上挑一個沒東西的地方）", True),
     ]},
    {"title": "委託看板",
     "how": "日常面板 → 任務委託板那一列 → 前往",
     "items": [
         ("tmpl", "quick_complete.png", "「快速完成」按鈕", (92, 30), "btn", True),
         ("tmpl", "done_stamp.png", "紅色「已完成」印章（要有一筆做完的才看得到）", (64, 64), "btn", True),
         ("tmpl", "close_x.png", "右上角紅色 X（寵物打工、頭像面板的 X 也用這項多抓）", (38, 38), "btn", True),
         ("tmpl", "quick_confirm.png", "按快速完成偶爾跳的「是否消耗冒險丸子立即完成此任務？」那行字"
          "（選用；有跳出來時再抓，抓了下面兩個位置也要抓）", (230, 20), "btn", False),
         ("point", "quick_no_remind", "同一個視窗裡「不再提示」前面的方框", "with:quick_confirm.png"),
         ("point", "quick_confirm_ok", "同一個視窗裡綠色的「確定」按鈕", "with:quick_confirm.png"),
         ("tmpl", "abandon_btn.png", "按錯接到任務時，卡片上的紅色「放棄任務」按鈕"
          "（選用；有出現時再抓，抓了下面兩項也要抓）", (160, 40), "btn", False),
         ("tmpl", "abandon_confirm.png", "按「放棄任務」後跳的「是否要放棄懸賞任務？」那行字",
          (200, 20), "btn", "with:abandon_btn.png"),
         ("point", "abandon_ok", "同一個視窗裡綠色的「確定」按鈕", "with:abandon_btn.png"),
     ]},
    {"title": "寵物打工",
     "how": "按 F1 開寵物手冊 → 點右邊「寵物打工」分頁",
     "items": [
         ("point", "pet_slot", "快捷列上「寵物手冊」那一格（沒快捷鍵的環境必要；在主畫面抓）", "nokey"),
         ("point", "pet_tab", "手冊右邊「寵物打工」分頁按鈕（開手冊後、還沒點分頁的畫面抓）", True),
         ("tmpl", "pet_title.png", "打工畫面最上面「寵物打工」標題（不是「寵物手冊」）", (124, 30), "btn", True),
         ("grid",),
         ("tmpl", "pet_gift.png", "禮物圖示（九宮格模式不需要，只是多一層確認）", (36, 36), "btn", False),
     ]},
    {"title": "時空矩陣掃蕩券",
     "how": "快捷列 F2 放時空矩陣掃蕩券；用一張讓禮物視窗跳出來再抓（先抓好再關掉視窗）",
     "items": [
         ("tmpl", "ticket_icon.png", "快捷列 F2 上的掃蕩券圖示（只框圖示，不要框到下面的數字；沒有券的角色不會按）",
          (34, 26), "btn", "feat"),
         ("point", "ticket_slot", "快捷列 F2 那一格（程式在這裡確認是不是掃蕩券；雷電也從這裡點）", "feat"),
         ("tmpl", "sweep_gift.png", "用掃蕩券後跳出的視窗，上方紅色金邊的禮物盒", (60, 50), "btn", "feat"),
     ]},
    {"title": "副本掃蕩",
     "how": "按 U（雷電：先點上方「更多」展開選單 → 再點選單裡的「副本」）→ 左邊清單找到狂想寓言點進去 → 上方等級列拖到最左（每個帳號掃哪一級在控制台「各帳號設定」選）",
     "items": [
         ("point", "more_btn", "第一下：主畫面上方「更多」按鈕（跟組隊、兌換那兩組共用，改一處全部跟著變）", "nokey"),
         ("point", "dungeon_btn", "第二下：選單裡的「副本」（先在遊戲裡手動點開「更多」，選單展開後再抓；不是抓「更多」本身）", "nokey"),
         ("tmpl", "menu_dungeon.png", "選單裡「副本」的圖示（選用，建議抓：不同帳號「更多」選單的項目數量不同，位置會移動；有抓就改用找的。先手動點開「更多」，框住圖示和下面的字）", (60, 60), "btn", False),
         ("tmpl", "dungeon_panel.png", "副本面板左上角「所有副本」字樣（剛開面板時抓）", (76, 22), "btn", True),
         ("tmpl", "fable_row.png", "左邊清單「【狂想寓言】」那幾個字", (84, 20), "btn", True),
         ("tmpl", "cake_row.png", "左邊清單「【蛋糕保衛戰】」那幾個字（選用：只用來確認副本面板有打開）", (96, 20), "btn", False),
         ("tmpl", "dungeon_title.png", "點進去後右上「狂想寓言」標題", (76, 22), "btn", False),
         ("point", "dungeon_first_tab", "分頁列拖到最左後，第一格（Lv.20）六角形的中心", True),
         ("point", "dungeon_last_tab", "分頁列拖到最左後，最右邊那格（VII Lv.80）六角形的中心（選用：要掃 Lv.20 以外的等級建議抓，程式用它算每格間距）", False),
         ("tmpl", "lv20_tab.png", "等級列 Lv.20 那一格（選用；程式主要靠上面那個位置）", (56, 60), "btn", False),
         ("tmpl", "sweep_btn.png", "藍色「掃蕩」按鈕——只框「掃蕩」兩個字，不要整顆按鈕（旁邊開組、匹配同款會混）", (52, 24), "btn", True),
         ("tmpl", "sweep_disabled.png", "灰色「掃蕩」按鈕（不能按的狀態）", (100, 34), "btn", False),
         ("tmpl", "playtime_label.png", "「消耗玩法時長」那幾個字（不要框到數字）", (92, 18), "btn", True),
         ("tmpl", "no_time_toast.png", "掃滿後按掃蕩跳的「剩餘時長不足」提示（多一層保險）", (120, 22), "btn", False),
     ]},
    {"title": "兌換序號",
     "how": "按 ESC（雷電：先點上方「更多」展開選單 → 再點選單裡的「設置」）→ 點左邊「遊戲設置」→ 內容拉到最下面",
     "items": [
         ("point", "more_btn", "第一下：主畫面上方「更多」按鈕（跟副本、組隊那兩組共用）", "nokey"),
         ("point", "settings_btn", "第二下：選單裡的「設置」（先手動點開「更多」再抓；不是抓「更多」本身）", "nokey"),
         ("tmpl", "menu_settings.png", "選單裡「設置」的圖示（選用，建議抓：不同帳號「更多」選單的項目數量不同，位置會移動；有抓就改用找的。先手動點開「更多」，框住圖示和下面的字）", (60, 60), "btn", False),
         ("tmpl", "settings_game.png", "設置視窗左邊那張「遊戲設置」卡片的字", (64, 24), "btn", True),
         ("tmpl", "redeem_btn.png", "遊戲設置拉到最下面的「兌換」按鈕", (80, 28), "btn", True),
         ("tmpl", "settings_close.png", "遊戲設置視窗右上角的 ☒（灰色小叉）", (28, 28), "btn", False),
     ]},
    {"title": "每日福利",
     "how": "主畫面點「熱點」→ 選單裡點「每日福利」",
     "items": [
         ("tmpl", "bonus_row.png", "熱點選單裡「每日福利」那一格（在選單畫面抓）", (64, 64), "btn", True),
         ("tmpl", "bonus_done.png", "灰色「已簽到」按鈕（已簽的那天抓）", (112, 36), "btn", True),
         ("tmpl", "bonus_claim.png", "可按的「簽到」按鈕（還沒簽的那天抓）", (112, 36), "btn", True),
     ]},
    {"title": "一鍵上架",
     "how": "主畫面點快捷列第 1 格（交易所）→ 點「我要出售」；要有過期貨物，右下才會出現「一鍵上架」",
     "items": [
         ("point", "exchange_slot", "快捷列上「交易所」那一格（第 1 格黃色帳篷；在主畫面抓）", "feat"),
         ("tmpl", "exchange_sell_tab.png", "交易所上方的「我要出售」分頁（框那四個字）", (62, 22), "btn", "feat"),
         ("tmpl", "relist_btn.png", "右下角黃色「一鍵上架」按鈕（要有過期貨物才會出現）", (130, 32), "btn", "feat"),
         ("tmpl", "relist_yes.png", "按一鍵上架後，確認視窗裡綠色的「是」", (140, 34), "btn", "feat"),
     ]},
    {"title": "燃料輪替",
     "how": "依序到這些畫面抓：設置面板 → 回到登錄後的標題畫面 → 選角畫面 → 隊伍面板（點隊長）→ "
            "主畫面左下對話框（系統）→ 包包愛心分頁（點燃料）。"
            "設置裡的「遊戲設置」卡片沿用「兌換序號」那組；「離開隊伍」、10000 紅字沿用「組隊輪替」那組",
     "items": [
         ("tmpl", "back_login.png", "設置面板下方的「回到登錄」", (96, 34), "btn", "feat"),
         ("tmpl", "title_start.png", "回到登錄後，標題畫面中間的「開始遊戲」", (80, 26), "btn", "feat"),
         ("tmpl", "charsel_start.png", "選角畫面右下角的「開始遊戲」", (120, 30), "btn", "feat"),
         ("tmpl", "charsel_plus.png", "選角畫面空格子的「＋」（只有兩隻角色的帳號才有；選用）", (40, 40), "btn", False),
         ("point", "char_slot_1", "選角畫面左邊第 1 個頭像（本尊）", "feat"),
         ("point", "char_slot_2", "選角畫面左邊第 2 個頭像", "feat"),
         ("point", "char_slot_3", "選角畫面左邊第 3 個頭像", "feat"),
         ("tmpl", "leader_star.png", "隊伍面板裡，隊長卡片右上角的紅色星星", (20, 28), "btn", "feat"),
         ("tmpl", "follow_off.png", "點隊長後的腳印：還沒跟隨（沒有斜線）", (32, 32), "btn", "feat"),
         ("tmpl", "follow_on.png", "點隊長後的腳印：已跟隨（有紅色斜線）", (32, 32), "btn", "feat"),
         ("point", "chat_open", "主畫面左下角的對話框（點它會打開聊天）", "feat"),
         ("tmpl", "chat_sys_tab.png", "聊天視窗左邊的「系統」分頁", (60, 30), "btn", "feat"),
         ("tmpl", "chat_fuel.png", "聊天視窗裡的「獲得燃料」四個字（只框字，不要框到 ×4）", (56, 18), "btn", "feat"),
         ("tmpl", "chat_close.png", "聊天視窗右邊的收起箭頭「<」", (20, 46), "btn", "feat"),
         ("point", "bag_btn", "主畫面上方「包包」按鈕（雷電用；官方按 B，雷電預設 611, 45）", "feat:nokey"),
         ("point", "bag_fav_tab", "包包裡的愛心分頁", "feat"),
         ("point", "bag_scroll", "包包打開在愛心分頁時，物品格子區的正中間（選用：愛心放很多東西、燃料不在第一頁時，程式從這裡上下拖來找）", False),
         ("tmpl", "fuel_item.png", "包包愛心分頁裡的燃料圖示（只框上半部的紅色礦石，滑鼠放礦石中間偏上；"
          "右下角的數量會一直變，框到就會認不到）", (40, 28), "btn", "feat"),
         ("tmpl", "fuel_full.png", "點燃料後「每日獲取上限：2000/2000」裡的 2000/2000", (50, 16), "btn", "feat"),
     ]},
    {"title": "組隊輪替",
     "how": "各項目說明有寫在哪個畫面。好友 ❤ 最愛裡只放隊長",
     "items": [
         ("tmpl", "leave_party.png", "按 T：紅色「離開隊伍」（在隊裡時）", (100, 34), "btn", True),
         ("tmpl", "create_party.png", "按 T：綠色「創建隊伍」（不在隊裡時）", (100, 34), "btn", True),
         ("tmpl", "confirm_ok.png", "點離開隊伍後的綠色「確定」", (100, 34), "btn", True),
         ("tmpl", "count_full.png", "點頭像：紅字「10000/10000」（找一隻打滿的）", (90, 20), "btn", True),
         ("point", "party_btn", "主畫面上方「隊伍」按鈕（沒快捷鍵的環境必要）", "nokey"),
         ("point", "more_btn", "第一下：主畫面上方「更多」按鈕（跟副本、兌換那兩組共用）", "nokey"),
         ("point", "friend_btn", "第二下：選單裡的「好友」（先手動點開「更多」再抓；不是抓「更多」本身）", "nokey"),
         ("tmpl", "menu_friend.png", "選單裡「好友」的圖示（選用，建議抓：不同帳號「更多」選單的項目數量不同，位置會移動；有抓就改用找的。先手動點開「更多」，框住圖示和下面的字）", (60, 60), "btn", False),
         ("point", "party_avatar", "左上角自己的頭像", True),
         ("point", "party_fav_tab", "按 O：好友面板的 ❤ 分頁", True),
         ("point", "party_friend_first", "❤ 分頁裡第一個好友的頭像", True),
         ("point", "party_apply_flag", "點好友頭像後小視窗裡的旗子", True),
         ("tmpl", "fav_tab_on.png", "好友面板切到 ❤ 分頁時：愛心＋底下那條藍色底線（選用：程式也會直接看愛心底下有沒有藍線，通常不用抓）", (52, 44), "btn", False),
         ("tmpl", "friend_close.png", "好友面板右上角的 ✕（只框 ✕；燃料輪替一定要，組隊建議抓）", (30, 30), "btn", False),
     ]},
    {"title": "進階（通常不用動）",
     "how": "這些已經有內建預設值，跑得正常就不用碰",
     "advanced": True,
     "items": [
         ("point", "scroll_point", "拖曳日常清單的位置（只用 x）", False),
         ("point", "scroll_point_alt", "拖曳的備用位置（只用 x）", False),
         ("tmpl", "pet_row.png", "日常清單「【寵物打工】」（舊入口，已不需要）", (92, 24), "row", False),
     ]},
]

# 執行模式在選單上顯示的文字
MODE_LABELS = {rd.AUTO_MODE: "自動（混合）", "官方": "只跑官方", "雷電": "只跑雷電"}

# 這些位置在「更多」展開後的選單裡；抓到跟「更多」同一點就是抓錯了
MENU_POINTS = {"dungeon_btn": "副本", "settings_btn": "設置", "friend_btn": "好友"}

SETTINGS = [
    ("window_title",     "遊戲視窗標題（部分符合即可）", str, "ROM Classic"),
    ("hotkeys",          "遊戲吃快捷鍵（F1 / I / T / O）；關掉就改點螢幕按鈕", bool, True),
    ("use_esc",          "允許用 ESC 關面板（模擬器要關，ESC 是返回鍵會跳退出遊戲）", bool, True),
    ("work_w",           "工作視窗寬（改了要重抓全部模板！）", int, 800),
    ("work_h",           "工作視窗高（改了要重抓全部模板！）", int, 500),
    ("daily_key",        "開「日常」面板的快捷鍵",     str,   "i"),
    ("pet_key",          "開「寵物手冊」的快捷鍵",     str,   "f1"),
    ("dungeon_key",      "開「副本」面板的快捷鍵",     str,   "u"),
    ("max_sweeps",       "副本掃蕩最多點幾次",         int,   14),
    ("pet_mode",         "寵物打工方式（grid=九宮格 / detect=辨識）", str, "grid"),
    ("match_threshold",  "比對門檻（0.7~0.95）",       float, 0.80),
    ("pet_gift_min_x",   "寵物打工只認 x 大於此值的圖示", int, 255),
    ("row_safe_bottom",  "清單列可點的最低 y",         int,   405),
    ("enable_bonus",     "做每日福利簽到",             bool,  True),
    ("claim_weekly",     "領完日常也切到週常領",       bool,  True),
    ("retry_failed",     "跑完後失敗的帳號自動補跑一次", bool,  True),
    ("adaptive_wait",    "等畫面靜止（關掉=固定秒數）", bool,  True),
    ("slow",             "動作放慢倍率（1=正常；卡或網路差調 1.5~2）", float, 1.0),
    ("red_dot_skip",     "日常／週常分頁沒有紅點就跳過領取", bool, True),
    ("remember_done",    "記住今天做完的任務、換過的序號（早上 6 點重置）", bool, True),
    ("relist_max",       "一鍵上架最多按幾次", int, 20),
]


# 設定分頁裡收在「進階」的項目（通常不用動；其他的放「常用」）
ADVANCED_SETTINGS = {"window_title", "work_w", "work_h", "pet_mode", "match_threshold",
                     "pet_gift_min_x", "row_safe_bottom", "adaptive_wait"}


def load_cfg():
    """目前環境的設定（座標、模板偏移、快捷鍵、尺寸…）。"""
    return rd._read_json(rd.CONFIG_PATH)


def save_cfg(cfg):
    rd._write_json(rd.CONFIG_PATH, cfg)
    rd._load_config()


def load_shared():
    """兩個環境共用的設定（目前環境、組隊輪替）。"""
    return rd._read_json(rd.SHARED_CONFIG_PATH)


def save_shared(cfg):
    rd._write_json(rd.SHARED_CONFIG_PATH, cfg)


def next_variant(base):
    """daily.png 不存在就存 daily.png，存在就 daily_2.png、daily_3.png ..."""
    root, ext = os.path.splitext(base)
    if not os.path.exists(os.path.join(rd.TEMPLATE_DIR, base)):
        return base
    i = 2
    while os.path.exists(os.path.join(rd.TEMPLATE_DIR, f"{root}_{i}{ext}")):
        i += 1
    return f"{root}_{i}{ext}"


class QueueWriter:
    def __init__(self, q):
        self.q = q

    def write(self, s):
        if s:
            self.q.put(s)

    def flush(self):
        pass


class Tooltip:
    """滑鼠停在元件上一下，旁邊浮出說明；移開就消失。長說明放這裡，畫面就不會被撐寬。"""

    def __init__(self, widget, text, delay=400):
        self.widget, self.text, self.delay = widget, text, delay
        self.tip = None
        self.job = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _=None):
        self._cancel()
        self.job = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self.job:
            self.widget.after_cancel(self.job)
            self.job = None

    def _show(self):
        if self.tip:
            return
        x = self.widget.winfo_rootx() + 10
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.tip = tk.Toplevel(self.widget)
        self.tip.overrideredirect(True)
        self.tip.attributes("-topmost", True)
        self.tip.geometry(f"+{x}+{y}")
        tk.Label(self.tip, text=self.text, justify="left", background="#ffffe0", foreground="#333",
                 relief="solid", borderwidth=1, wraplength=420, padx=6, pady=4).pack()

    def _hide(self, _=None):
        self._cancel()
        if self.tip:
            self.tip.destroy()
            self.tip = None


class ScrollFrame(ttk.Frame):
    """可以捲動的容器（校正、設定分頁）。內容放在 .inner 裡。"""

    def __init__(self, master):
        super().__init__(master)
        canvas = tk.Canvas(self, highlightthickness=0)
        bar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.inner = ttk.Frame(canvas)
        self.inner.bind("<Configure>",
                        lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        win = canvas.create_window((0, 0), window=self.inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.canvas = canvas
        # 滾輪：滑鼠停在哪個捲動框裡就捲哪個（校正、設定都有捲動框，以前後建的會搶走滾輪）
        if not ScrollFrame._wheel_bound:
            ScrollFrame._wheel_bound = True
            canvas.bind_all("<MouseWheel>", ScrollFrame._on_wheel)

    _wheel_bound = False

    @staticmethod
    def _on_wheel(e):
        try:
            w = e.widget.winfo_containing(e.x_root, e.y_root)
        except Exception:
            return
        while w is not None:
            if isinstance(w, tk.Text):               # 紀錄框自己會捲，不要連外面一起捲
                return
            if isinstance(w, ScrollFrame):
                w.canvas.yview_scroll(-1 * (e.delta // 120), "units")
                return
            w = getattr(w, "master", None)


# ---------------------------------------------------------------------------
# 自動更新（GitHub）
# ---------------------------------------------------------------------------
# 朋友按「檢查更新」：讀 version.json → 比版本 → 下載、核對 sha256、確認程式沒壞 → 舊版備份 → 換上新版。
# 只換程式檔；校正、模板、設定、帳號備份、今日紀錄都不動。
# 作者按「發布更新」：用自己的 GitHub 鑰匙（DPAPI 加密存在本機 %LOCALAPPDATA%）把程式和 version.json 傳上去。
UPDATE_REPO = "pawn842125/rom-helper"
UPDATE_BRANCH = "main"
UPDATE_FILES = ["rom_daily.py", "rom_party.py", "gui.pyw", "account_switch.pyw"]
UPDATE_PAGE = f"https://github.com/{UPDATE_REPO}"
_RAW_BASE = f"https://raw.githubusercontent.com/{UPDATE_REPO}/"   # + 快照編號/檔名
_RAW = _RAW_BASE + f"{UPDATE_BRANCH}/"
_API = f"https://api.github.com/repos/{UPDATE_REPO}/contents/"
TOKEN_PATH = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local"),
                          "ROM_helper", "github_token.bin")
BACKUP_DIR = os.path.join(rd.BASE_DIR, "更新前的備份")

GITHUB_README = """# ROM 日常助手

ROM Classic（仙境傳說 Classic）每日任務自動化，官方 PC 版和雷電模擬器都能用。

## 第一次安裝
1. 安裝 Python 3.13（https://www.python.org/downloads/windows/ ，安裝時勾「Add python.exe to PATH」）。
2. 跟作者拿「ROM_helper.zip」（裡面有校正好的模板），解壓到固定的資料夾。
3. 雙擊 `gui.pyw`。缺套件會跳視窗問你要不要自動安裝，按「是」，裝完再雙擊一次。

## 之後更新
GUI →「設定」分頁 →「檢查更新」。只會換程式檔，你自己的校正、模板、設定都不會動。
有問題可以按「退回上一版」。

## 共用模板
作者發布時會一起分享模板和校正好的位置。你的 GUI 開啟時會自動「只補你缺的」，你自己抓過的完全不動。
某張在你電腦上認不太到（校正頁「測試」分數低），自己補抓一張就好。

這裡只放程式檔，不放任何人的設定、模板或帳號資料。
"""


def _q(path):
    """網址裡的中文（例如 templates/官方/xx.png）要編碼。"""
    import urllib.parse
    return urllib.parse.quote(path, safe="/")


def _http(url, data=None, method=None, headers=None, timeout=20):
    import urllib.request
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"User-Agent": "ROM-helper", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def newer(remote, local):
    """版本號格式固定（2026.11.05、2026.11.05b），直接比字串就是新舊順序。"""
    return str(remote) > str(local)


def remote_info():
    """GitHub 上最新版的資訊（version.json）。後面加時間參數，避免拿到舊的快取。"""
    import time as _t
    return json.loads(_http(_RAW + f"version.json?t={int(_t.time())}").decode("utf-8"))


def fetch_published(path, sha256, commit=None, say=print):
    """抓 GitHub 上的一個檔案，核對 sha256。依序試：
    1. 發布時記下的快照（raw/<commit>/檔名）：指定快照的網址永遠不會被快取成舊的、也沒有次數限制
    2. 一般管道（raw/main，加時間參數）：剛發布完可能還是舊的（GitHub 快取約 5 分鐘）
    3. GitHub API（不走快取，但沒登入每小時 60 次）
    都對不上才丟錯。朋友實測：剛發布完更新 → 「下載不完整（檢查碼對不上）」（2026.11.11c）。"""
    import hashlib, time as _t
    tries = []
    if commit:
        tries.append(("快照", lambda: _http(_RAW_BASE + f"{commit}/" + _q(path))))
    tries.append(("一般管道", lambda: _http(_RAW + _q(path) + f"?t={int(_t.time())}")))
    tries.append(("GitHub API", lambda: _http(_API + _q(path) + f"?ref={UPDATE_BRANCH}",
                                              headers={"Accept": "application/vnd.github.raw+json"})))
    last, mismatch = "", False
    for k, (how, get) in enumerate(tries):
        try:
            data = get()
        except Exception as e:
            last = last if mismatch else f"{how}下載失敗：{e}"
            continue
        if hashlib.sha256(data).hexdigest() == sha256:
            if k:
                say(f"  （{path} 用{how}抓到正確的）")
            return data
        last, mismatch = "檢查碼對不上", True
        if k + 1 < len(tries):
            say(f"  {path}：{last}（GitHub 可能還沒更新完），換別的方式再抓一次…")
    raise RuntimeError(f"{path} 下載不完整（{last}），請過 10 分鐘再試")


def download_update(info, say=print):
    """下載新版的每個檔案：核對 sha256（確認下載完整）、試著編譯（確認程式沒壞）。全部沒問題才回傳。"""
    files = {}
    for name, meta in info.get("files", {}).items():
        if name not in UPDATE_FILES:                # 只收認得的檔名，不會把奇怪的東西寫進資料夾
            continue
        say(f"下載 {name} …")
        data = fetch_published(name, meta.get("sha256"), info.get("commit"), say)
        compile(data.decode("utf-8"), name, "exec")
        files[name] = data
    if "gui.pyw" not in files:
        raise RuntimeError("新版的檔案清單不完整")
    return files


def apply_update(files, old_version):
    """舊版先備份到「更新前的備份/版本號/」，再換上新版。回傳備份資料夾。"""
    bdir = os.path.join(BACKUP_DIR, old_version)
    os.makedirs(bdir, exist_ok=True)
    for name in files:
        src = os.path.join(rd.BASE_DIR, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(bdir, name))
    for name, data in files.items():
        dst = os.path.join(rd.BASE_DIR, name)
        tmp = dst + ".new"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, dst)
    return bdir


def save_token(token):
    """GitHub 鑰匙用 Windows 內建的加密（DPAPI）存在本機：只有這台電腦、這個 Windows 帳號解得開。"""
    import win32crypt
    blob = win32crypt.CryptProtectData(token.encode("utf-8"), "ROM helper GitHub", None, None, None, 0)
    os.makedirs(os.path.dirname(TOKEN_PATH), exist_ok=True)
    with open(TOKEN_PATH, "wb") as f:
        f.write(blob)


def load_token():
    if not os.path.exists(TOKEN_PATH):
        return None
    try:
        import win32crypt
        with open(TOKEN_PATH, "rb") as f:
            return win32crypt.CryptUnprotectData(f.read(), None, None, None, 0)[1].decode("utf-8")
    except Exception:
        return None


def gh_api(path, token, method="GET", body=None):
    """呼叫 GitHub 的 API（作者發布用）。GET 找不到回傳 None。"""
    import urllib.error
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    try:
        raw = _http(_API + _q(path), data, method, headers, timeout=30)
        return json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as e:
        if e.code == 404 and method == "GET":
            return None
        detail = e.read()[:200].decode("utf-8", "replace")
        if e.code in (401, 403):
            raise RuntimeError(f"GitHub 拒絕（{e.code}）：鑰匙可能過期、權限不對，或打錯了。{detail}")
        raise RuntimeError(f"GitHub 回應 {e.code}：{detail}")


def gh_put(name, data, token, message):
    """把一個檔案傳到 GitHub（已經有的會覆蓋）。"""
    import base64
    cur = gh_api(name, token)
    body = {"message": message, "content": base64.b64encode(data).decode("ascii"), "branch": UPDATE_BRANCH}
    if cur and cur.get("sha"):
        body["sha"] = cur["sha"]
    return gh_api(name, token, "PUT", body)


def gh_delete(name, sha, token, message):
    return gh_api(name, token, "DELETE", {"message": message, "sha": sha, "branch": UPDATE_BRANCH})


def git_sha(data):
    """GitHub 用來分辨檔案有沒有變的檢查碼（跟它算的一樣，才知道哪些模板要重傳）。"""
    import hashlib
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def shared_point_keys():
    """校正頁上所有「位置」項目，加上寵物九宮格和模板的點擊偏移：這些是大家可以共用的校正結果。"""
    keys = {item[1] for spec in CALIB_GROUPS for item in spec["items"] if item[0] == "point"}
    return sorted(keys | {"pet_slots", "offsets"})


def local_templates(prof):
    d = os.path.join(rd.PROFILES_DIR, prof, "templates")
    if not os.path.isdir(d):
        return {}
    out = {}
    for n in sorted(os.listdir(d)):
        if n.lower().endswith(".png") and os.path.isfile(os.path.join(d, n)):
            with open(os.path.join(d, n), "rb") as f:
                out[n] = f.read()
    return out


def sync_shared(info, say=print):
    """把 GitHub 上的共用模板、位置「只補缺的」：自己已經有的完全不動。回傳 (補了幾張模板, 補了幾個位置)。"""
    import hashlib
    added_t = added_p = 0
    for prof, files in (info.get("templates") or {}).items():
        if prof not in rd.PROFILE_NAMES:
            continue
        tdir = os.path.join(rd.PROFILES_DIR, prof, "templates")
        os.makedirs(tdir, exist_ok=True)
        for n, sha in files.items():
            if not n.lower().endswith(".png") or "/" in n or "\\" in n or n.startswith("."):
                continue                            # 只收單純的 png 檔名
            dst = os.path.join(tdir, n)
            if os.path.exists(dst):
                continue                            # 自己已經有：不動（自己抓的比較準）
            try:
                data = fetch_published(f"templates/{prof}/{n}", sha, info.get("commit"), lambda *_: None)
            except Exception as e:
                say(f"  共用模板 {prof}/{n} 下載失敗或不完整，跳過（{e}）")
                continue
            with open(dst, "wb") as f:
                f.write(data)
            added_t += 1
            say(f"  補上共用模板：{prof}／{n}")
    for prof, pts in (info.get("points") or {}).items():
        if prof not in rd.PROFILE_NAMES:
            continue
        cfg_path = os.path.join(rd.PROFILES_DIR, prof, "config.json")
        cfg = rd._read_json(cfg_path)
        changed = False
        for k, v in pts.items():
            if k == "offsets" and isinstance(v, dict):
                mine = cfg.setdefault("offsets", {})
                for name, off in v.items():
                    if name not in mine:
                        mine[name] = off
                        changed = True
                        added_p += 1
            elif k not in cfg:
                cfg[k] = v
                changed = True
                added_p += 1
                say(f"  補上共用位置：{prof}／{k}")
        if changed:
            os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
    return added_t, added_p


def personal_leaks(text):
    """發布前檢查：程式裡不能有作者的個人資料（電腦路徑、兌換序號、記住的帳號名字）。"""
    hits = []
    home = os.path.expanduser("~")
    if home and len(home) > 4 and home.lower() in text.lower():
        hits.append(f"電腦路徑 {home}")
    code = (load_shared().get("redeem_code") or "").strip()
    if len(code) >= 4 and code in text:
        hits.append(f"兌換序號 {code}")
    vault = os.path.join(os.path.dirname(TOKEN_PATH), "accounts")
    if os.path.isdir(vault):
        for name in os.listdir(vault):
            if name.startswith("_"):
                continue
            # 純數字、太短的英文（例如 007）程式裡本來就常出現，不算個人資料；中文名字兩個字以上才檢查
            has_cjk = any(ord(c) > 0x2E80 for c in name)
            if (has_cjk and len(name) >= 2) or (not has_cjk and len(name) >= 4 and not name.isdigit()):
                if name in text:
                    hits.append(f"帳號名字「{name}」")
    return hits


class App:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        # 背景執行緒要叫視窗做事（跳視窗、改按鈕）一律丟進這個信箱，由視窗自己在 pump 裡拿出來做。
        # 背景直接碰 tkinter 會在視窗剛好關掉／重開時整個當掉（pythonw.exe 記憶體不能為 read）。
        self.uiq = queue.Queue()
        self.worker = None
        self.fixed_hwnd = None
        self.fixed_orig = None
        self.preview_img = None
        self.pending_row = None       # 抓完清單列文字後，等著抓按鈕位置
        self.active_log = None        # 目前訊息要顯示在哪個紀錄區（建好介面後設定）

        root.title(f"ROM 日常助手  v{__version__}")
        root.geometry(f"880x720+{rd.WORK_X + rd.WORK_W + 40}+{rd.WORK_Y}")
        root.minsize(760, 520)

        top = ttk.Frame(root, padding=(10, 8, 10, 0))
        top.pack(fill="x")
        ttk.Label(top, text="執行：", font=("Microsoft JhengHei", 10, "bold")).pack(side="left")
        self.mode_var = tk.StringVar(value=MODE_LABELS[rd.RUN_MODE])
        mcb = ttk.Combobox(top, textvariable=self.mode_var, values=list(MODE_LABELS.values()),
                           state="readonly", width=12)
        mcb.pack(side="left")
        mcb.bind("<<ComboboxSelected>>", lambda e: self.switch_mode())
        ttk.Label(top, text="　校正／設定的是：", font=("Microsoft JhengHei", 10, "bold")).pack(side="left")
        self.profile_var = tk.StringVar(value=rd.ACTIVE_PROFILE)
        cb = ttk.Combobox(top, textvariable=self.profile_var, values=rd.PROFILE_NAMES,
                          state="readonly", width=8)
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self.switch_profile())
        self.profile_hint = ttk.Label(top, text="", foreground="#666")
        self.profile_hint.pack(side="left", padx=12)

        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=6, pady=6)

        # 分頁順序（使用者指定）：控制台、燃料輪替、組隊輪替，校正和設定放最後（一鍵上架併進控制台的勾選）
        self.tab_main = ttk.Frame(nb)
        nb.add(self.tab_main, text="  控制台  ")
        self.tab_fuel = ttk.Frame(nb)
        nb.add(self.tab_fuel, text="  燃料輪替  ")
        self.tab_party = ttk.Frame(nb)
        nb.add(self.tab_party, text="  組隊輪替  ")
        calib_holder = ScrollFrame(nb)
        nb.add(calib_holder, text="  校正  ")
        self.tab_calib = calib_holder.inner
        set_holder = ScrollFrame(nb)
        nb.add(set_holder, text="  設定  ")
        self.tab_set = set_holder.inner

        self._build_main()
        self._build_calib()
        self._build_party()
        self._build_fuel()
        self._build_settings()

        self.status = tk.StringVar(value=f"待命中（執行中按 {rd.STOP_KEY.upper()} 可立刻停止）　｜　版本 {__version__}")
        ttk.Label(root, textvariable=self.status, relief="sunken",
                  anchor="w", padding=(8, 3)).pack(fill="x", side="bottom")

        self.active_log = self.logbox
        self.update_profile_hint()
        self.log("開好所有遊戲視窗後，勾選任務、按「開始」。\n")
        self.log("第一次用請先到「校正」分頁把模板抓好。\n\n")
        self.root.after(100, self.pump)
        self.root.after(200, self.track_mouse)
        self.root.after(3000, lambda: self.check_update(silent=True))   # 開好後在背景看一下有沒有新版

    # ==================================================================
    # 環境切換
    # ==================================================================
    def update_profile_hint(self):
        if rd.WINDOW_EXES:
            find = f"找雷電程式（{'、'.join(rd.WINDOW_EXES)}）或標題含「{rd.WINDOW_TITLE}」"
        else:
            find = f"視窗標題含「{rd.WINDOW_TITLE}」"
        n = sum(1 for _ in os.listdir(rd.TEMPLATE_DIR)) if os.path.isdir(rd.TEMPLATE_DIR) else 0
        self.profile_hint.configure(
            text=f"{find}　{'走快捷鍵' if rd.HOTKEYS else '點螢幕按鈕（無快捷鍵）'}　模板 {n} 張")

    def switch_mode(self):
        """執行模式：自動（混合）／只跑官方／只跑雷電。"""
        mode = {v: k for k, v in MODE_LABELS.items()}.get(self.mode_var.get(), rd.AUTO_MODE)
        if mode == rd.RUN_MODE:
            return
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("正在執行", "等目前的工作停下來再切換。")
            self.mode_var.set(MODE_LABELS[rd.RUN_MODE])
            return
        rd.RUN_MODE = mode
        shared = load_shared()
        shared["run_mode"] = mode
        save_shared(shared)
        if mode != rd.AUTO_MODE and mode != rd.ACTIVE_PROFILE:
            self.profile_var.set(mode)               # 只跑某一種：校正／設定也跟著切過去
            self.switch_profile()
        self.update_profile_hint()
        self.log(f"執行模式：{MODE_LABELS[mode]}。"
                 + ("官方和雷電的視窗都會找，每個視窗用自己那一套設定。\n" if mode == rd.AUTO_MODE
                    else f"只找{mode}的視窗。\n"), "head")

    def switch_profile(self):
        name = self.profile_var.get()
        if name == rd.ACTIVE_PROFILE:
            return
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("正在執行", "等目前的工作停下來再切換環境。")
            self.profile_var.set(rd.ACTIVE_PROFILE)
            return
        if self.fixed_hwnd:
            self.unfix_window()
        rd.set_profile(name)
        rp._load()
        shared = load_shared()
        shared["active_profile"] = name
        if rd.RUN_MODE != rd.AUTO_MODE:              # 只跑某一種時，執行的就是正在編輯的這一套
            rd.RUN_MODE = name
            shared["run_mode"] = name
            self.mode_var.set(MODE_LABELS[name])
        save_shared(shared)
        for child in self.tab_calib.winfo_children():
            child.destroy()
        self._build_calib()
        for child in self.tab_set.winfo_children():
            child.destroy()
        self._build_settings()
        self.update_profile_hint()
        self.log(f"已切換到「{name}」環境。\n", "head")

    # ==================================================================
    # 控制台
    # ==================================================================
    def _build_main(self):
        f = self.tab_main

        top = ttk.LabelFrame(f, text="要做什麼", padding=8)
        top.pack(fill="x", padx=8, pady=(8, 4))
        self.task_vars = {}
        per_row = 4                                     # 每排 4 個，任務變多也只是多一排，不會把視窗撐寬
        tips = {"relist": "把交易所裡過期的貨物重新上架：點快捷列第 1 格（交易所）→「我要出售」→ "
                          "一直按「一鍵上架」→「是」，直到按鈕消失（最多按幾次在設定頁改）。\n"
                          "預設不勾，要上架時再勾；不會記成今天做過，一天可以跑很多次。\n"
                          "第一次用先到「校正 → 一鍵上架」把模板和位置抓好。"}
        for i, key in enumerate(rd.MAIN_TASKS):
            var = tk.BooleanVar(value=key in rd.DEFAULT_ON)
            cb = ttk.Checkbutton(top, text=rd.TASK_LABELS[key], variable=var)
            cb.grid(row=i // per_row, column=i % per_row, padx=(0, 18), pady=1, sticky="w")
            if key in tips:
                Tooltip(cb, tips[key])
            self.task_vars[key] = var
        code_row = ttk.Frame(top)
        code_row.grid(row=(len(rd.MAIN_TASKS) - 1) // per_row + 1, column=0, columnspan=per_row,
                      sticky="w", pady=(6, 0))
        ttk.Label(code_row, text="兌換序號：").pack(side="left")
        self.redeem_var = tk.StringVar(value=load_shared().get("redeem_code", ""))
        ttk.Entry(code_row, textvariable=self.redeem_var, width=24).pack(side="left")
        ttk.Label(code_row, text="（勾「兌換序號」才會做；跑的時候輸入法切英文）",
                  foreground="#666").pack(side="left", padx=8)

        win = ttk.LabelFrame(f, text="哪些視窗", padding=8)
        win.pack(fill="x", padx=8, pady=4)
        self.selected_windows = None            # None = 全部；否則是編號清單
        ttk.Button(win, text="選擇要跑的視窗…", command=self.pick_windows).pack(side="left")
        self.win_sel_lbl = ttk.Label(win, text="目前：全部", foreground="#1a5fb4")
        self.win_sel_lbl.pack(side="left", padx=12)
        ttk.Button(win, text="改回全部", command=self.select_all_windows).pack(side="left")
        acc_btn = ttk.Button(win, text="各帳號設定…", command=self.account_settings)
        acc_btn.pack(side="right")
        Tooltip(acc_btn, "每個帳號自己的設定（例如副本掃哪一級）。每個帳號一列，會記住。")

        multi = ttk.LabelFrame(f, text="多開管理", padding=8)
        multi.pack(fill="x", padx=8, pady=4)
        m1 = ttk.Frame(multi)
        m1.pack(anchor="w")
        ttk.Button(m1, text="檢查開了哪些", command=self.check_instances).pack(side="left")
        ttk.Button(m1, text="補開沒開的", command=self.open_missing).pack(side="left", padx=8)
        ttk.Button(m1, text="強制關閉…", command=self.kill_dialog).pack(side="left")
        m2 = ttk.Frame(multi)
        m2.pack(anchor="w", pady=(6, 0))
        ttk.Button(m2, text="標示視窗編號", command=self.show_numbers).pack(side="left")
        arr = ttk.Button(m2, text="自動排列視窗", command=self.arrange)
        arr.pack(side="left", padx=8)
        cols_lbl = ttk.Label(m2, text="欄數：")
        cols_lbl.pack(side="left")
        self.arrange_cols = tk.StringVar(value="0")
        cols_box = ttk.Spinbox(m2, from_=0, to=8, width=3, textvariable=self.arrange_cols)
        cols_box.pack(side="left")
        ttk.Label(m2, text="ⓘ", foreground="#1a5fb4").pack(side="left", padx=(4, 0))
        tip = ("自動排列視窗的欄數。0 = 自動挑視窗最大的排法。\n"
               "視窗會保持遊戲原本比例；排好後視窗編號 = 資料夾編號。\n"
               "跑到螢幕外面、叫不出來的視窗，按這個也會被拉回來。")
        for w in (arr, cols_lbl, cols_box, m2.winfo_children()[-1]):
            Tooltip(w, tip)

        bar = ttk.Frame(f, padding=(8, 4))
        bar.pack(fill="x")
        self.btn_run = ttk.Button(bar, text="開始", width=10, command=self.run)
        self.btn_run.pack(side="left")
        self.btn_stop = ttk.Button(bar, text="停止", width=8, command=self.stop,
                                   state="disabled")
        self.btn_stop.pack(side="left", padx=6)
        ttk.Button(bar, text="清除紀錄", command=self.clear_log).pack(side="right")
        ttk.Button(bar, text="清除今天的完成紀錄", command=self.clear_today).pack(side="right", padx=6)

        frame = ttk.Frame(f, padding=(8, 0, 8, 8))
        frame.pack(fill="both", expand=True)
        self.logbox = tk.Text(frame, wrap="word", font=("Consolas", 10),
                              bg="#1e1e1e", fg="#dcdcdc", insertbackground="#dcdcdc")
        sb = ttk.Scrollbar(frame, command=self.logbox.yview)
        self.logbox.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.logbox.pack(side="left", fill="both", expand=True)
        self.logbox.tag_config("ok", foreground="#6ac46a")
        self.logbox.tag_config("bad", foreground="#e06c6c")
        self.logbox.tag_config("head", foreground="#6cb6ff")
        self.logbox.tag_config("warn", foreground="#e0b060")

    def show_numbers(self, seconds=5):
        """在每個 ROM 視窗的左上角浮出它的編號，幾秒後自動消失。"""
        hwnds = rd.find_windows()
        if not hwnds:
            messagebox.showinfo("找不到視窗", "目前沒有 ROM Classic 視窗。")
            return
        info = rd.list_instances()
        names = {h: name for _, h, name in info["windows"]}
        tags = []
        for i, h in enumerate(hwnds, 1):
            x, y, w, _ = rd.get_rect(h)
            top = tk.Toplevel(self.root)
            top.overrideredirect(True)
            top.attributes("-topmost", True)
            top.geometry(f"+{x + 12}+{y + 40}")
            cell = tk.Frame(top, bg="#d0342c", padx=14, pady=4)
            cell.pack()
            tk.Label(cell, text=str(i), font=("Arial", 36, "bold"),
                     fg="white", bg="#d0342c").pack()
            tk.Label(cell, text=os.path.basename(str(names.get(h, ""))),
                     font=("Microsoft JhengHei", 11, "bold"),
                     fg="white", bg="#d0342c").pack()
            tags.append(top)
            self.log(f"視窗 {i:2d}：{names.get(h, '')}　位置 ({x}, {y})\n")
        self.root.after(seconds * 1000, lambda: [t.destroy() for t in tags])

    def arrange(self):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("正在執行", "等目前的工作停下來再排。")
            return
        try:
            cols = int(self.arrange_cols.get())
        except ValueError:
            cols = 0
        # 放到背景做（跟其他工作同一套），GUI 不會被遊戲視窗拖住而「沒有回應」
        def job():
            if rd.arrange_windows(cols=cols, log=print):
                print("排好了。按「標示視窗編號」確認。")
        self.start(job, "排列視窗中")

    def kill_dialog(self):
        """列出每個視窗是哪一份，勾選後強制關閉（卡在讀取畫面轉圈圈時用）。"""
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("正在執行", "等目前的工作停下來再關。")
            return
        info = rd.list_instances()
        if not info["windows"]:
            self.log("目前沒有遊戲視窗。\n", "warn")
            return
        win = tk.Toplevel(self.root)
        win.title("強制關閉視窗")
        win.transient(self.root)
        win.withdraw()
        ttk.Label(win, text="勾選要強制關閉的視窗（等同工作管理員的結束工作）。關掉後用「補開沒開的」開回來。",
                  foreground="#666", wraplength=460, justify="left").pack(anchor="w", padx=12, pady=(10, 4))
        body = ttk.Frame(win, padding=(12, 0))
        body.pack(fill="both", expand=True)
        vars_ = []
        for k, (i, h, name) in enumerate(info["windows"]):
            var = tk.BooleanVar(value=False)
            ttk.Checkbutton(body, variable=var, text=f"視窗 {i:2d}　{os.path.basename(str(name))}",
                            width=26).grid(row=k // 2, column=k % 2, sticky="w", padx=(0, 16), pady=2)
            vars_.append((var, i, h, name))

        def go():
            picked = [(i, h, name) for var, i, h, name in vars_ if var.get()]
            win.destroy()
            if not picked:
                return
            names = "、".join(f"視窗 {i}（{os.path.basename(str(n))}）" for i, _, n in picked)
            if not messagebox.askyesno("確定強制關閉？", names):
                return
            for i, h, name in picked:
                ok = rd.kill_window(h)
                self.log(f"視窗 {i}（{os.path.basename(str(name))}）：{'已關閉' if ok else '關不掉'}\n",
                         "ok" if ok else "bad")
            self.log("可以按「補開沒開的」把它開回來。\n")

        bar = ttk.Frame(win, padding=12)
        bar.pack(fill="x")
        ttk.Button(bar, text="全選", command=lambda: [v.set(True) for v, *_ in vars_]).pack(side="left")
        ttk.Button(bar, text="全不選", command=lambda: [v.set(False) for v, *_ in vars_]).pack(side="left", padx=6)
        ttk.Button(bar, text="取消", command=win.destroy).pack(side="right")
        ttk.Button(bar, text="強制關閉勾選的", command=go).pack(side="right", padx=6)

        win.update_idletasks()
        ww, wh = win.winfo_reqwidth(), win.winfo_reqheight()
        rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
        rw, rh = self.root.winfo_width(), self.root.winfo_height()
        win.geometry(f"{ww}x{wh}+{rx + max(0, (rw - ww) // 2)}+{ry + max(0, (rh - wh) // 2)}")
        win.deiconify()
        win.lift()
        win.attributes("-topmost", True)
        win.after(600, lambda: win.attributes("-topmost", False))
        win.focus_force()

    def check_instances(self):
        """列出開著的視窗各是哪一份、還有哪幾份沒開。"""
        info = rd.list_instances()
        if not info["windows"]:
            if rd.RUN_MODE == rd.AUTO_MODE:
                self.log("目前沒有遊戲視窗（自動模式：官方和雷電都找過了）。\n", "warn")
            else:
                self.log(f"目前沒有遊戲視窗（「{rd.RUN_MODE}」找的是標題含「{rd.WINDOW_TITLE}」的視窗）。\n", "warn")
            hints = rd.window_titles_hint()
            if hints:
                self.log("現在開著、標題看起來相關的視窗：" + "、".join(f"「{t}」" for t in hints) + "\n")
                self.log("如果遊戲在裡面但標題不符，到設定分頁改「遊戲視窗標題」；或是上面環境選錯了。\n")
            if info["missing"]:
                self.log(f"沒開的 {len(info['missing'])} 份：" +
                         "、".join(os.path.basename(f) for f in info["missing"]) + "\n")
                self.log("按「補開沒開的」可以全部開起來。\n")
            elif not info.get("known"):
                self.log("還不知道遊戲裝在哪：先手動開一個視窗，再按一次這顆讓程式記下來。\n")
            return
        self.log(f"—— 開著的 {len(info['windows'])} 個 ——\n", "head")
        for i, _, name in info["windows"]:
            self.log(f"  視窗 {i:2d}：{name}\n")
        for full in info.get("noexe", []):
            self.log(f"  {os.path.basename(full)}：資料夾在，但裡面沒有 {info['exe_rel']}，補開會跳過它\n", "warn")
        if info["missing"]:
            self.log(f"—— 沒開的 {len(info['missing'])} 份 ——\n", "head")
            for full in info["missing"]:
                self.log(f"  {os.path.basename(full)}\n", "warn")
            self.log("按「補開沒開的」可以一次開起來（開完要自己登入）。\n")
        elif any(n.startswith("ROM") or os.sep not in str(n) for _, _, n in info["windows"]):
            self.log("全部都開著。\n", "ok")

    def open_missing(self):
        """跳出清單：每一份是已開還是未開，未開的可以勾選要不要開。"""
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("正在執行", "等目前的工作停下來再補開。")
            return
        info = rd.list_instances()
        if not info.get("known"):
            self.log("還不知道遊戲裝在哪：先手動開一個視窗，按「檢查開了哪些」讓程式記下來。\n", "warn")
            return
        if not info["all"]:
            self.log("找不到任何遊戲資料夾。\n", "warn")
            return

        win = tk.Toplevel(self.root)
        win.title("補開沒開的")
        win.transient(self.root)
        win.withdraw()                              # 先藏起來，內容建好、算好位置再顯示
        ttk.Label(win, text="勾選要開的，已開的不能勾。", foreground="#666").pack(
            anchor="w", padx=12, pady=(10, 4))

        body = ttk.Frame(win, padding=(12, 0))
        body.pack(fill="both", expand=True)
        vars_ = []
        for k, item in enumerate(info["all"]):
            row = ttk.Frame(body)
            row.grid(row=k // 2, column=k % 2, sticky="w", padx=(0, 24), pady=2)
            var = tk.BooleanVar(value=(not item["open"]) and bool(item["exe"]))
            cb = ttk.Checkbutton(row, variable=var, width=14, text=item["name"])
            cb.pack(side="left")
            if item["open"]:
                var.set(False)
                cb.configure(state="disabled")
                ttk.Label(row, text=f"已開（視窗 {item['window']}）", foreground="#26a269").pack(side="left")
            elif not item["exe"]:
                var.set(False)
                cb.configure(state="disabled")
                ttk.Label(row, text="找不到執行檔", foreground="#a51d2d").pack(side="left")
            else:
                ttk.Label(row, text="未開", foreground="#c64600").pack(side="left")
            vars_.append((var, item))

        def set_all(v):
            for var, item in vars_:
                if not item["open"] and item["exe"]:
                    var.set(v)

        def go():
            chosen = [item["path"] for var, item in vars_ if var.get()]
            win.destroy()
            if not chosen:
                self.log("沒有勾任何一份。\n")
                return
            self.log("要開：" + "、".join(os.path.basename(p) for p in chosen) + "\n")
            self.start(lambda: rd.launch_missing(log=print, only=chosen), "補開中")

        bar = ttk.Frame(win, padding=12)
        bar.pack(fill="x")
        ttk.Button(bar, text="全選", command=lambda: set_all(True)).pack(side="left")
        ttk.Button(bar, text="全不選", command=lambda: set_all(False)).pack(side="left", padx=6)
        ttk.Button(bar, text="取消", command=win.destroy).pack(side="right")
        ttk.Button(bar, text="開啟勾選的", command=go).pack(side="right", padx=6)

        # 內容建好了，量清單自己的大小，放到主視窗正中央
        win.update_idletasks()
        ww, wh = win.winfo_reqwidth(), win.winfo_reqheight()
        rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
        rw, rh = self.root.winfo_width(), self.root.winfo_height()
        x = rx + max(0, (rw - ww) // 2)
        y = ry + max(0, (rh - wh) // 2)
        win.geometry(f"{ww}x{wh}+{x}+{y}")
        win.deiconify()
        win.lift()
        win.attributes("-topmost", True)
        win.after(600, lambda: win.attributes("-topmost", False))
        win.focus_force()

    def parse_windows(self):
        return self.selected_windows

    def select_all_windows(self):
        self.selected_windows = None
        self.win_sel_lbl.configure(text="目前：全部")

    def account_settings(self):
        """各帳號設定：每個開著的帳號一列，選副本掃哪一級。存在共用設定 dungeon_levels（用帳號名字記）。"""
        hwnds = rd.find_windows()
        if not hwnds:
            messagebox.showinfo("找不到視窗", "目前沒有遊戲視窗。先把要設定的帳號開起來。")
            return
        rows = [(h, rd.kind_of(h), rd.window_label(h), rd.account_name(h)) for h in hwnds]
        levels = [rd.dungeon_level_name(n) for n in range(1, len(rd.DUNGEON_LEVELS) + 1)]
        saved = load_shared().get("dungeon_levels", {})

        win = tk.Toplevel(self.root)
        win.withdraw()
        win.title("各帳號設定")
        win.transient(self.root)
        body = ttk.Frame(win, padding=12)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="每個帳號自己的設定，會記住。沒開的帳號不會列出來，之前設好的會保留。\n"
                             "副本掃蕩：選了 Lv.20 以外的，建議先到「校正 → 副本掃蕩」抓「最右邊那格（VII）」。",
                  foreground="#666", justify="left").grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))
        for c, text in enumerate(("種類", "名稱", "副本掃哪一級", "")):
            ttk.Label(body, text=text, font=("Microsoft JhengHei", 9, "bold")).grid(
                row=1, column=c, sticky="w", padx=6)
        vars_ = []
        for i, (h, kind, name, key) in enumerate(rows, 2):
            ttk.Label(body, text=kind).grid(row=i, column=0, sticky="w", padx=6, pady=2)
            ttk.Label(body, text=name).grid(row=i, column=1, sticky="w", padx=6)
            try:
                n = max(1, min(len(levels), int(saved.get(key, 1))))
            except (TypeError, ValueError):
                n = 1
            v = tk.StringVar(value=levels[n - 1])
            ttk.Combobox(body, textvariable=v, values=levels, state="readonly", width=14).grid(
                row=i, column=2, sticky="w", padx=6)
            vars_.append((key, v))
            ttk.Button(body, text="認一下", width=7,
                       command=lambda h=h: self.peek_window(h, win)).grid(row=i, column=3, padx=6)

        def ok():
            shared = load_shared()
            memo = dict(shared.get("dungeon_levels", {}))
            for key, v in vars_:
                memo[key] = levels.index(v.get()) + 1
            shared["dungeon_levels"] = memo
            save_shared(shared)
            self.log("各帳號設定已儲存：\n" + "".join(
                f"  {name}：副本掃 {v.get()}\n" for (h, kind, name, key), (_, v) in zip(rows, vars_)), "ok")
            win.destroy()

        bar = ttk.Frame(body)
        bar.grid(row=len(rows) + 2, column=0, columnspan=4, sticky="e", pady=(12, 0))
        ttk.Button(bar, text="儲存", command=ok).pack(side="left", padx=4)
        ttk.Button(bar, text="取消", command=win.destroy).pack(side="left", padx=4)

        win.update_idletasks()
        ww, wh = win.winfo_reqwidth(), win.winfo_reqheight()
        rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
        rw, rh = self.root.winfo_width(), self.root.winfo_height()
        win.geometry(f"{ww}x{wh}+{rx + max(0, (rw - ww) // 2)}+{ry + max(0, (rh - wh) // 2)}")
        win.deiconify()
        win.lift()
        win.focus_force()

    def pick_windows(self):
        """跳出清單：列出目前每個視窗是哪一份，勾要跑的。"""
        info = rd.list_instances()
        if not info["windows"]:
            messagebox.showinfo("沒有視窗", "目前沒有遊戲視窗。")
            return
        win = tk.Toplevel(self.root)
        win.title("選擇要跑的視窗")
        win.transient(self.root)
        win.withdraw()
        ttk.Label(win, text="勾選要跑的視窗。", foreground="#666").pack(anchor="w", padx=12, pady=(10, 4))
        body = ttk.Frame(win, padding=(12, 0))
        body.pack(fill="both", expand=True)
        vars_ = []
        chosen_now = set(self.selected_windows or [i for i, _, _ in info["windows"]])
        for k, (i, _, name) in enumerate(info["windows"]):
            var = tk.BooleanVar(value=(i in chosen_now))
            ttk.Checkbutton(body, variable=var, text=f"視窗 {i:2d}　{os.path.basename(str(name))}",
                            width=26).grid(row=k // 2, column=k % 2, sticky="w", padx=(0, 16), pady=2)
            vars_.append((var, i))

        def set_all(v):
            for var, _ in vars_:
                var.set(v)

        def ok():
            picked = sorted(i for var, i in vars_ if var.get())
            win.destroy()
            if not picked:
                return
            if len(picked) == len(vars_):
                self.select_all_windows()
            else:
                self.selected_windows = picked
                self.win_sel_lbl.configure(text="目前：" + ",".join(map(str, picked)))

        bar = ttk.Frame(win, padding=12)
        bar.pack(fill="x")
        ttk.Button(bar, text="全選", command=lambda: set_all(True)).pack(side="left")
        ttk.Button(bar, text="全不選", command=lambda: set_all(False)).pack(side="left", padx=6)
        ttk.Button(bar, text="取消", command=win.destroy).pack(side="right")
        ttk.Button(bar, text="確定", command=ok).pack(side="right", padx=6)

        win.update_idletasks()
        ww, wh = win.winfo_reqwidth(), win.winfo_reqheight()
        rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
        rw, rh = self.root.winfo_width(), self.root.winfo_height()
        win.geometry(f"{ww}x{wh}+{rx + max(0, (rw - ww) // 2)}+{ry + max(0, (rh - wh) // 2)}")
        win.deiconify()
        win.lift()
        win.attributes("-topmost", True)
        win.after(600, lambda: win.attributes("-topmost", False))
        win.focus_force()

    def run(self):
        tasks = {k for k, v in self.task_vars.items() if v.get()}
        if not tasks:
            messagebox.showinfo("沒有勾任務", "至少勾一項要做的事。")
            return
        code = self.redeem_var.get().strip()
        if "redeem" in tasks and not code:
            messagebox.showinfo("沒有序號", "勾了兌換序號，但序號欄是空的。")
            return
        rd.REDEEM_CODE = code
        shared = load_shared()
        shared["redeem_code"] = code
        save_shared(shared)
        windows = self.parse_windows()
        if self.fixed_hwnd:
            self.unfix_window()
        self.start(lambda: rd.cmd_run(tasks=tasks, windows=windows),
                   "執行中，請勿操作滑鼠鍵盤")

    def stop(self):
        rd.ABORT = True
        self.status.set("正在停止，視窗會自動還原…")

    # ==================================================================
    # 校正
    # ==================================================================
    def _build_calib(self):
        f = self.tab_calib
        cfg = load_cfg()
        self.tmpl_rows = {}
        self.point_lbls = {}
        self.slot_lbls = []
        self.groups = []

        step1 = ttk.LabelFrame(f, text="先固定一個遊戲視窗，再展開要修的那一組", padding=8)
        step1.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Label(step1, text="用第幾個視窗：").pack(side="left")
        self.calib_win = tk.StringVar(value="1")
        ttk.Spinbox(step1, from_=1, to=32, width=4,
                    textvariable=self.calib_win).pack(side="left")
        self.btn_fix = ttk.Button(step1, text="固定視窗", command=self.fix_window)
        self.btn_fix.pack(side="left", padx=(8, 4))
        self.btn_unfix = ttk.Button(step1, text="還原視窗", command=self.unfix_window,
                                    state="disabled")
        self.btn_unfix.pack(side="left")
        ttk.Button(step1, text="全部收合", command=lambda: self.expand_all(False)
                   ).pack(side="right")
        ttk.Button(step1, text="全部展開", command=lambda: self.expand_all(True)
                   ).pack(side="right", padx=4)
        self.mouse_lbl = ttk.Label(step1, text="滑鼠：—", foreground="#666")
        self.mouse_lbl.pack(side="right", padx=12)

        prev = ttk.Frame(f, padding=(10, 0))
        prev.pack(fill="x")
        ttk.Label(prev, text="剛抓到的圖：").pack(side="left")
        self.preview = ttk.Label(prev, relief="sunken", padding=4)
        self.preview.pack(side="left")
        self.capture_lbl = ttk.Label(prev, text="", foreground="#c64600")
        self.capture_lbl.pack(side="left", padx=12)

        for spec in CALIB_GROUPS:
            self._build_group(f, spec, cfg)
        self.refresh_counts()

    def _build_group(self, parent, spec, cfg):
        outer = ttk.Frame(parent, relief="groove", borderwidth=1, padding=(6, 4))
        outer.pack(fill="x", padx=8, pady=3)

        head = ttk.Frame(outer)
        head.pack(fill="x")
        status = ttk.Label(head, text="", width=4, font=("Arial", 11))
        status.pack(side="left")
        ttk.Label(head, text=spec["title"], font=("Microsoft JhengHei", 10, "bold"),
                  width=14, anchor="w").pack(side="left")
        toggle = ttk.Button(head, text="展開", width=6)
        toggle.pack(side="right")
        ttk.Button(head, text="測試這組", width=8,
                   command=lambda s=spec: self.test_group(s)).pack(side="right", padx=4)
        count = ttk.Label(head, text="", foreground="#666", anchor="w",
                          wraplength=420, justify="left")
        count.pack(side="left", fill="x", expand=True)

        body = ttk.Frame(outer, padding=(8, 4, 0, 4))
        ttk.Label(body, text="怎麼切到這個畫面：" + spec["how"],
                  foreground="#1a5fb4", wraplength=620, justify="left").pack(
            fill="x", pady=(0, 6))
        for item in spec["items"]:
            if item[0] == "tmpl":
                _, name, desc, (w, h), kind, req = item
                self._tmpl_row(body, name, desc + ("" if self.is_required(req) else
                                                   "　(用這個功能就要抓)" if self.is_feature(req) else "　(選用)"),
                               w, h, kind)
            elif item[0] == "point":
                _, key, desc, req = item
                self._point_row(body, key, desc + ("" if self.is_required(req) else
                                                   "　(用這個功能就要抓)" if self.is_feature(req) else "　(選用)"),
                                cfg.get(key) or self.point_default(key))
            elif item[0] == "grid":
                self._grid_block(body, cfg)

        g = {"spec": spec, "body": body, "status": status, "count": count,
             "toggle": toggle, "open": False}
        toggle.configure(command=lambda gg=g: self.toggle_group(gg))
        self.groups.append(g)

    def _grid_block(self, parent, cfg):
        ttk.Label(parent, text="九宮格：進到打工畫面後，滑鼠依序移到每個建築「禮物會出現的位置」。"
                               "用不到的格子在倒數時把滑鼠移出遊戲視窗就會跳過。",
                  foreground="#666", wraplength=620, justify="left").pack(fill="x", pady=(4, 4))
        grid = ttk.Frame(parent)
        grid.pack(anchor="w")
        slots = cfg.get("pet_slots") or []
        if not slots and rd.PET_SLOTS:
            slots = [list(p) for p in rd.PET_SLOTS] + [None] * (9 - len(rd.PET_SLOTS))
        for i in range(9):
            cell = ttk.Frame(grid, padding=3)
            cell.grid(row=i // 3, column=i % 3, padx=4, pady=2)
            ttk.Label(cell, text=f"第 {i + 1} 格", width=6).pack(side="left")
            val = slots[i] if i < len(slots) and slots[i] else None
            lbl = ttk.Label(cell, text=f"{val[0]},{val[1]}" if val else "未設定",
                            width=9, foreground="#26a269" if val else "#a51d2d")
            lbl.pack(side="left")
            ttk.Button(cell, text="抓取", width=5,
                       command=lambda k=i: self.capture_slot(k)).pack(side="left")
            self.slot_lbls.append(lbl)
        srow = ttk.Frame(parent)
        srow.pack(anchor="w", pady=(4, 0))
        ttk.Button(srow, text="連續抓九格（每格 3 秒）",
                   command=self.capture_all_slots).pack(side="left")
        ttk.Button(srow, text="清除九格", command=self.clear_slots).pack(side="left", padx=8)
        ttk.Button(srow, text="試點一輪", command=self.test_slots).pack(side="left")

    def point_default(self, key):
        """位置的內建預設值：日常相關在 rd，組隊相關在 rp（都已依目前環境載入）。"""
        party = {"party_avatar": "P_AVATAR", "party_fav_tab": "P_FAV_TAB",
                 "party_friend_first": "P_FRIEND_FIRST", "party_apply_flag": "P_APPLY_FLAG",
                 "party_btn": "P_PARTY_BTN", "friend_btn": "P_FRIEND_BTN",
                 "more_btn": "P_MORE_BTN", "chat_open": "P_CHAT_OPEN", "bag_btn": "P_BAG_BTN",
                 "bag_fav_tab": "P_BAG_FAV", "bag_scroll": "P_BAG_SCROLL"}
        if key in party:
            return getattr(rp, party[key], None)
        return getattr(rd, key.upper(), None)

    def toggle_group(self, g, force=None):
        want = (not g["open"]) if force is None else force
        if want and not g["open"]:
            g["body"].pack(fill="x")
        elif not want and g["open"]:
            g["body"].pack_forget()
        g["open"] = want
        g["toggle"].configure(text="收合" if want else "展開")

    def expand_all(self, want):
        for g in self.groups:
            self.toggle_group(g, want)

    @staticmethod
    def is_feature(flag):
        """"feat" 用這個功能就需要；"feat:nokey" 用這個功能、而且沒快捷鍵的環境才需要。"""
        if flag == "feat":
            return True
        return flag == "feat:nokey" and not rd.HOTKEYS

    @staticmethod
    def is_required(flag):
        """True 一律必要；"nokey" 只在沒快捷鍵的環境必要；"with:xx.png" 有抓那張模板才必要；False 選用。"""
        if isinstance(flag, str) and flag.startswith("with:"):
            return rd.has(flag[5:])
        return flag is True or (flag == "nokey" and not rd.HOTKEYS)

    def feature_health(self, spec):
        """「用這個功能就要抓」的項目：回傳 (抓了幾個, 總共幾個, 缺的名字清單)。"""
        cfg = load_cfg()
        got, total, missing = 0, 0, []
        for item in spec["items"]:
            if item[0] == "tmpl":
                _, name, desc, _, _, req = item
                ok = rd.has(name)
            elif item[0] == "point":
                _, key, desc, req = item
                ok = bool(cfg.get(key) or self.point_default(key))
            else:
                continue
            if self.is_feature(req):
                total += 1
                got += ok
                if not ok:
                    missing.append(desc.split("（")[0])
        return got, total, missing

    def group_health(self, spec):
        """回傳 (必要項目缺幾個, 必要項目總數, 缺的名字清單)。"""
        cfg = load_cfg()
        total, missing = 0, []
        for item in spec["items"]:
            if item[0] == "tmpl":
                _, name, desc, _, _, req = item
                if self.is_required(req):
                    total += 1
                    if not rd.has(name):
                        missing.append(desc.split("（")[0])
            elif item[0] == "point":
                _, key, desc, req = item
                if self.is_required(req):
                    total += 1
                    if not (cfg.get(key) or self.point_default(key)):
                        missing.append(desc.split("（")[0])
                    elif self.menu_overlap(key, cfg):
                        missing.append(f"「{MENU_POINTS[key]}」跟「更多」同一點，要重抓")
            elif item[0] == "grid":
                total += 1
                slots = [p for p in (cfg.get("pet_slots") or rd.PET_SLOTS) if p]
                if not slots:
                    missing.append("九宮格")
        return len(missing), total, missing

    def menu_overlap(self, key, cfg=None):
        """選單裡的按鈕（副本／設置／好友）是不是被抓成跟「更多」同一點。是就回傳說明文字。"""
        if key not in MENU_POINTS:
            return ""
        cfg = load_cfg() if cfg is None else cfg
        more = cfg.get("more_btn") or self.point_default("more_btn")
        val = cfg.get(key) or self.point_default(key)
        if not rd.too_close(more, val):
            return ""
        name = MENU_POINTS[key]
        return (f"「{name}」記成 {val[0]}, {val[1]}，跟「更多」{more[0]}, {more[1]} 幾乎同一點，"
                f"這樣程式會點開更多又馬上關掉。\n"
                f"請在遊戲裡先手動點「更多」讓選單展開，再按「{name}」的抓取，"
                f"滑鼠移到選單裡的「{name}」圖示上。")

    def test_group(self, spec):
        """把這一組的模板全部拿目前畫面測一遍，位置則列出數值。"""
        self._calm()
        if not self.need_fixed():
            return
        screen = rd.grab()
        cfg = load_cfg()
        self.log(f"—— 測試「{spec['title']}」（畫面應該是：{spec['how']}）——\n", "head")
        for item in spec["items"]:
            if item[0] == "tmpl":
                name = item[1]
                if not rd.has(name):
                    self.log(f"  {name:20s} 還沒抓\n", "warn" if self.is_required(item[5]) else None)
                    continue
                best = 0.0
                for v in rd.template_variants(name):
                    tp = rd.load_template(v)
                    if screen.shape[0] >= tp.shape[0] and screen.shape[1] >= tp.shape[1]:
                        best = max(best, float(cv2.matchTemplate(
                            screen, tp, cv2.TM_CCOEFF_NORMED).max()))
                found = rd.find_all(screen, name)
                self.log(f"  {name:20s} {'找到 ' + str(len(found)) + ' 個' if found else '找不到'}"
                         f"　最高分 {best:.2f}\n", "ok" if found else "bad")
            elif item[0] == "point":
                key = item[1]
                val = cfg.get(key) or self.point_default(key)
                self.log(f"  {key:20s} {val if val else '未設定'}\n", None if val else "warn")
            elif item[0] == "grid":
                slots = [p for p in (cfg.get("pet_slots") or rd.PET_SLOTS) if p]
                self.log(f"  九宮格{'':16s} 已設 {len(slots)} 格\n", "ok" if slots else "warn")

    def _tmpl_row(self, parent, name, desc, w, h, kind):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=1)
        ttk.Label(row, text=desc, width=46, anchor="w", wraplength=330,
                  justify="left").pack(side="left")
        cnt = ttk.Label(row, text="0", width=5, foreground="#a51d2d")
        cnt.pack(side="left")
        wv = tk.StringVar(value=str(w))
        hv = tk.StringVar(value=str(h))
        ttk.Entry(row, textvariable=wv, width=5).pack(side="left")
        ttk.Entry(row, textvariable=hv, width=5).pack(side="left", padx=(2, 6))
        ttk.Button(row, text="抓取", width=5,
                   command=lambda: self.capture_template(name, kind)).pack(side="left")
        ttk.Button(row, text="測試", width=5,
                   command=lambda: self.test_template(name)).pack(side="left", padx=2)
        ttk.Button(row, text="清除", width=5,
                   command=lambda: self.clear_template(name)).pack(side="left")
        self.tmpl_rows[name] = {"count": cnt, "w": wv, "h": hv}

    def _point_row(self, parent, key, desc, val):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=1)
        ttk.Label(row, text=desc, width=46, anchor="w", wraplength=330,
                  justify="left").pack(side="left")
        lbl = ttk.Label(row, text=f"{val[0]}, {val[1]}" if val else "未設定",
                        width=12, foreground="#26a269" if val else "#a51d2d")
        lbl.pack(side="left")
        ttk.Button(row, text="抓取", width=5,
                   command=lambda: self.capture_point(key)).pack(side="left")
        self.point_lbls.setdefault(key, []).append(lbl)   # 「更多」在三組都有，要一起更新

    def rel_mouse(self):
        """滑鼠相對於工作視窗左上角的座標；不在視窗內回傳 None。"""
        x, y = pyautogui.position()
        rx, ry = x - rd.AREA_X, y - rd.AREA_Y
        if 0 <= rx < rd.AREA_W and 0 <= ry < rd.AREA_H:
            return rx, ry
        return None

    def track_mouse(self):
        pos = self.rel_mouse()
        self.mouse_lbl.configure(
            text=f"滑鼠：{pos[0]}, {pos[1]}" if pos else "滑鼠：（不在工作區內）")
        self.root.after(200, self.track_mouse)

    def fix_window(self):
        self._calm()
        hwnds = rd.find_windows()
        try:
            n = int(self.calib_win.get())
        except ValueError:
            n = 1
        if not (1 <= n <= len(hwnds)):
            messagebox.showinfo("找不到視窗", f"目前只有 {len(hwnds)} 個遊戲視窗。")
            return
        kind = rd.kind_of(hwnds[n - 1])
        if kind != rd.ACTIVE_PROFILE:                # 選到另一種視窗：校正頁換成那一套（畫面會重建）
            self.profile_var.set(kind)
            self.switch_profile()
            self.calib_win.set(str(n))
            self.log(f"視窗 {n} 是{kind}（{rd.window_label(hwnds[n - 1])}），"
                     f"校正頁已切到「{kind}」那一套，抓的東西會存到{kind}。\n", "head")
        self.fixed_hwnd = hwnds[n - 1]
        self.fixed_orig = rd.remember_place(self.fixed_hwnd)
        rd.normalize_window(self.fixed_hwnd)
        self.log(f"工作區 {rd.AREA_W}x{rd.AREA_H}"
                 f"{'（遊戲畫面子視窗）' if rd.USE_RENDER_CHILD else '（整個視窗）'}\n")
        self.btn_fix.configure(state="disabled")
        self.btn_unfix.configure(state="normal")
        self.log(f"視窗 {n} 已固定在工作位置，可以開始抓取。\n", "head")

    def unfix_window(self):
        if self.fixed_hwnd and self.fixed_orig:
            try:
                rd.restore_place(self.fixed_hwnd, self.fixed_orig)
            except Exception:
                pass
        self.fixed_hwnd = None
        self.fixed_orig = None
        self.btn_fix.configure(state="normal")
        self.btn_unfix.configure(state="disabled")
        self.log("視窗已還原。\n")

    def need_fixed(self):
        if not self.fixed_hwnd:
            messagebox.showinfo("先固定視窗", "請先在校正分頁上方按「固定視窗」。")
            return False
        return True

    def countdown(self, n, then):
        if n > 0:
            self.capture_lbl.configure(text=f"{n} 秒後抓取，把滑鼠移到目標上…")
            self.root.after(1000, lambda: self.countdown(n - 1, then))
        else:
            self.capture_lbl.configure(text="")
            then()

    def capture_template(self, name, kind):
        self._calm()
        if not self.need_fixed():
            return
        try:
            w = int(self.tmpl_rows[name]["w"].get())
            h = int(self.tmpl_rows[name]["h"].get())
        except ValueError:
            messagebox.showwarning("大小有誤", "寬和高要填數字。")
            return

        def do():
            pos = self.rel_mouse()
            if not pos:
                self.log("滑鼠不在遊戲視窗內，取消。\n", "warn")
                return
            cx, cy = pos
            x0 = max(0, min(rd.AREA_W - w, cx - w // 2))
            y0 = max(0, min(rd.AREA_H - h, cy - h // 2))
            screen = rd.grab()
            crop = screen[y0:y0 + h, x0:x0 + w]
            os.makedirs(rd.TEMPLATE_DIR, exist_ok=True)
            fname = next_variant(name)
            if not rd.imwrite(os.path.join(rd.TEMPLATE_DIR, fname), crop):
                self.log(f"存檔失敗：{os.path.join(rd.TEMPLATE_DIR, fname)}\n", "bad")
                return
            rd._tmpl_cache.pop(fname, None)
            self.show_preview(crop)
            self.refresh_counts()
            self.update_profile_hint()
            self.log(f"已存 {fname}（{w}×{h}，中心 {cx},{cy}）\n", "ok")
            if kind == "row":
                self.pending_row = (fname, x0, y0)
                self.log("→ 現在把滑鼠移到這一列右邊的「前往」按鈕正中央，3 秒後記錄偏移量。\n",
                         "warn")
                self.countdown(3, self.capture_row_button)

        self.countdown(3, do)

    def capture_row_button(self):
        if not self.pending_row:
            return
        fname, x0, y0 = self.pending_row
        self.pending_row = None
        pos = self.rel_mouse()
        if not pos:
            self.log("滑鼠不在遊戲視窗內，偏移量沒記錄；請按「清除」後重抓這一列。\n", "warn")
            return
        cfg = load_cfg()
        cfg.setdefault("offsets", {})[fname] = [pos[0] - x0, pos[1] - y0]
        save_cfg(cfg)
        self.log(f"已記錄 {fname} 的按鈕偏移量 {cfg['offsets'][fname]}\n", "ok")

    def capture_point(self, key):
        self._calm()
        if not self.need_fixed():
            return

        def do():
            pos = self.rel_mouse()
            if not pos:
                self.log("滑鼠不在遊戲視窗內，取消。\n", "warn")
                return
            cfg = load_cfg()
            cfg[key] = [pos[0], pos[1]]
            save_cfg(cfg)
            rp._load()                               # 組隊那邊的位置也要跟著更新
            for lbl in self.point_lbls.get(key, []):
                lbl.configure(text=f"{pos[0]}, {pos[1]}", foreground="#26a269")
            self.refresh_counts()
            self.log(f"已記錄 {key} = {pos[0]}, {pos[1]}\n", "ok")
            bad = self.menu_overlap(key, cfg)
            if bad:
                self.log(bad + "\n", "bad")
                messagebox.showwarning("位置抓錯了", bad)

        self.countdown(3, do)

    # -- 九宮格 ----------------------------------------------------------
    def _save_slot(self, k, pos):
        cfg = load_cfg()
        slots = cfg.get("pet_slots") or []
        if not slots:                       # config 沒存過，就顯示程式內建的預設值
            slots = [list(p) for p in rd.PET_SLOTS] + [None] * (9 - len(rd.PET_SLOTS))
        slots += [None] * (9 - len(slots))
        slots[k] = [pos[0], pos[1]] if pos else None
        cfg["pet_slots"] = slots
        save_cfg(cfg)
        lbl = self.slot_lbls[k]
        lbl.configure(text=f"{pos[0]},{pos[1]}" if pos else "未設定",
                      foreground="#26a269" if pos else "#a51d2d")
        self.refresh_counts()

    def capture_slot(self, k, then=None):
        if not self.need_fixed():
            return

        def do():
            pos = self.rel_mouse()
            if not pos:
                self.log(f"第 {k + 1} 格：滑鼠不在遊戲視窗內，跳過。\n", "warn")
            else:
                self._save_slot(k, pos)
                self.log(f"第 {k + 1} 格 = {pos[0]}, {pos[1]}\n", "ok")
            if then:
                then()

        self.capture_lbl.configure(text=f"準備抓第 {k + 1} 格…")
        self.countdown(3, do)

    def capture_all_slots(self, k=0):
        """一格接一格抓，每格 3 秒。滑鼠移到視窗外就當作那格不用。"""
        if k >= 9:
            self.log("九格抓完。\n", "ok")
            return
        self.capture_slot(k, then=lambda: self.capture_all_slots(k + 1))

    def clear_slots(self):
        if not messagebox.askyesno("確定", "要清掉九宮格全部座標嗎？"):
            return
        cfg = load_cfg()
        cfg["pet_slots"] = []
        save_cfg(cfg)
        for lbl in self.slot_lbls:
            lbl.configure(text="未設定", foreground="#a51d2d")
        self.refresh_counts()
        self.log("九宮格已清除。\n")

    def test_slots(self):
        """在固定好的視窗上，照九宮格順序把滑鼠移過去（不點），確認位置對不對。"""
        if not self.need_fixed():
            return
        slots = [tuple(p) for p in (load_cfg().get("pet_slots") or []) if p]
        if not slots:
            self.log("還沒抓任何格子。\n", "warn")
            return

        def walk(i=0):
            if i >= len(slots):
                self.log("滑鼠已依序走過所有格子。位置對的話就可以正式跑了。\n", "ok")
                return
            x, y = slots[i]
            pyautogui.moveTo(rd.AREA_X + x, rd.AREA_Y + y, duration=0.4)
            self.root.after(700, lambda: walk(i + 1))

        rd.focus(self.fixed_hwnd)
        self.log("開始走位，看滑鼠有沒有停在每個禮物的位置上…\n")
        walk()

    def test_template(self, name):
        self._calm()
        if not self.need_fixed():
            return
        if not rd.has(name):
            self.log(f"{name} 還沒抓過。\n", "warn")
            return
        screen = rd.grab()
        found = rd.find_all(screen, name)
        best = 0.0
        for v in rd.template_variants(name):
            t = rd.load_template(v)
            if screen.shape[0] >= t.shape[0] and screen.shape[1] >= t.shape[1]:
                best = max(best, float(cv2.matchTemplate(
                    screen, t, cv2.TM_CCOEFF_NORMED).max()))
        if found:
            self.log(f"{name}：目前畫面找到 {len(found)} 個，最高分 {best:.2f}\n", "ok")
        else:
            self.log(f"{name}：目前畫面找不到（最高分 {best:.2f}，門檻 {rd.MATCH_THRESHOLD}）\n",
                     "bad")

    def clear_template(self, name):
        vs = rd.template_variants(name)
        if not vs:
            return
        if not messagebox.askyesno("確定刪除", f"要刪掉 {name} 的全部 {len(vs)} 張圖嗎？"):
            return
        for v in vs:
            try:
                os.remove(os.path.join(rd.TEMPLATE_DIR, v))
            except OSError:
                pass
            rd._tmpl_cache.pop(v, None)
        cfg = load_cfg()
        for v in vs:
            cfg.get("offsets", {}).pop(v, None)
        save_cfg(cfg)
        self.refresh_counts()
        self.log(f"已刪除 {name} 的 {len(vs)} 張圖。\n")

    def refresh_counts(self):
        for name, row in self.tmpl_rows.items():
            n = len(rd.template_variants(name))
            row["count"].configure(text=str(n), foreground="#26a269" if n else "#a51d2d")
        first_problem = None
        for g in self.groups:
            miss, total, names = self.group_health(g["spec"])
            if g["spec"].get("advanced"):
                g["status"].configure(text="▸", foreground="#666")
                g["count"].configure(text="")
                continue
            fgot, ftotal, fnames = self.feature_health(g["spec"])
            if ftotal and not total:
                # 整組都是「用這個功能才要抓」：顯示抓了幾個，沒開始用就灰色，不算問題
                if fgot == ftotal:
                    g["status"].configure(text="✔", foreground="#26a269")
                    g["count"].configure(text=f"{fgot}/{ftotal}", foreground="#26a269")
                elif fgot == 0:
                    g["status"].configure(text="○", foreground="#888")
                    g["count"].configure(text=f"0/{ftotal}　還沒抓（用到這個功能才需要）", foreground="#888")
                else:
                    g["status"].configure(text="⚠", foreground="#c64600")
                    g["count"].configure(text=f"{fgot}/{ftotal}　缺 " + "、".join(fnames[:4])
                                         + ("…" if len(fnames) > 4 else ""), foreground="#c64600")
                continue
            if miss:
                g["status"].configure(text="⚠", foreground="#c64600")
                g["count"].configure(text=f"{total - miss}/{total}　缺 " + "、".join(names),
                                     foreground="#c64600")
                if first_problem is None:
                    first_problem = g
            else:
                g["status"].configure(text="✔", foreground="#26a269")
                g["count"].configure(text=f"{total}/{total}", foreground="#26a269")
        if first_problem is not None and not any(g["open"] for g in self.groups):
            self.toggle_group(first_problem, True)   # 有缺的話自動展開第一個有問題的組

    def show_preview(self, bgr):
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb)
        scale = max(1, min(3, 120 // max(1, img.height)))
        img = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
        self.preview_img = ImageTk.PhotoImage(img)
        self.preview.configure(image=self.preview_img)

    # ==================================================================
    # 組隊輪替
    # ==================================================================
    def _build_fuel(self):
        f = self.tab_fuel
        ttk.Label(f, text="鐵匠打怪掉燃料，每隻角色每天 2000。先按「燃料角色設定…」選打手、每個帳號勾要吸的角色（不勾的帳號不會被碰），再按開始。"
                          "依序：第 2 隻 → 第 3 隻（小號，燃料滿 2000 離隊）→ 本尊（戰鬥次數 10000 才離隊），"
                          "都是進打手的隊伍「跟隨」吸；沒勾本尊的帳號吸完會換回本尊。\n"
                          "不輪替、但也待在同一隊掛著的帳號會佔隊伍位置：「同時最多幾隻在吸」要設成剩下的空位。\n"
                          "事前準備：要吸的角色都換好鐵匠、燃料設成包包愛心、好友 ❤ 裡只放打手。"
                          "打手要開「自動接受入隊」。第一次用先到「校正 → 燃料輪替」抓好。\n"
                          "跑的時候程式會一直切換視窗，電腦不能做別的事；按 F12 停止。",
                  foreground="#666", wraplength=660, justify="left").pack(fill="x", padx=8, pady=(8, 4))
        box = ttk.LabelFrame(f, text="設定", padding=8)
        box.pack(fill="x", padx=8, pady=4)
        shared = load_shared()
        self.fuel_vars = {}
        for i, (key, label, default) in enumerate((("fuel_max", "同時最多幾隻在吸（隊伍 6 人含打手 → 5）", 5),
                                                    ("fuel_gap", "同一個視窗至少隔幾秒再看一次", 20))):
            ttk.Label(box, text=label).grid(row=i, column=0, sticky="w", pady=2)
            var = tk.StringVar(value=str(shared.get(key, default)))
            ttk.Entry(box, textvariable=var, width=8).grid(row=i, column=1, sticky="w", padx=6)
            self.fuel_vars[key] = var
        bar = ttk.Frame(f, padding=(8, 4))
        bar.pack(fill="x")
        self.btn_fuel_set = ttk.Button(bar, text="燃料角色設定…", command=self.fuel_settings)
        self.btn_fuel_set.pack(side="left", padx=(0, 8))
        Tooltip(self.btn_fuel_set, "選打手、每個帳號勾要吸燃料的角色，按「儲存」存起來（不會開始跑）。")
        self.btn_fuel = ttk.Button(bar, text="開始燃料輪替", command=self.fuel_start)
        self.btn_fuel.pack(side="left")
        self.btn_fuel_stop = ttk.Button(bar, text="停止", width=8, command=self.stop, state="disabled")
        self.btn_fuel_stop.pack(side="left", padx=6)
        ttk.Button(bar, text="清除紀錄", command=lambda: self.fuel_log.delete("1.0", "end")).pack(side="right")
        ttk.Button(bar, text="清除今天的燃料紀錄", command=self.fuel_clear).pack(side="right", padx=6)
        frame = ttk.Frame(f, padding=(8, 0, 8, 8))
        frame.pack(fill="both", expand=True)
        self.fuel_log = tk.Text(frame, wrap="word", font=("Consolas", 10),
                                bg="#1e1e1e", fg="#dcdcdc", insertbackground="#dcdcdc")
        sb = ttk.Scrollbar(frame, command=self.fuel_log.yview)
        self.fuel_log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.fuel_log.pack(side="left", fill="both", expand=True)
        for tag, color in (("ok", "#6ac46a"), ("bad", "#e06c6c"), ("head", "#6cb6ff"), ("warn", "#e0b060")):
            self.fuel_log.tag_config(tag, foreground=color)

    def fuel_save(self):
        shared = load_shared()
        try:
            shared["fuel_max"] = max(1, min(5, int(self.fuel_vars["fuel_max"].get())))
            shared["fuel_gap"] = max(5.0, float(self.fuel_vars["fuel_gap"].get()))
        except ValueError:
            messagebox.showerror("設定有誤", "同時幾隻、隔幾秒要填數字。")
            return False
        save_shared(shared)
        rp._load()
        return True

    def fuel_settings(self):
        """「燃料角色設定…」：打開選擇視窗，按「儲存」只存起來，不會開始跑。"""
        def saved(leader, accounts, slots):
            self.log("燃料角色設定已儲存，按「開始燃料輪替」就會照這個跑。\n", "ok", target=self.fuel_log)
        self.party_pick(saved, fuel=True, ok_text="儲存")

    def fuel_saved_plan(self):
        """照存好的燃料設定，對應到現在開著的視窗。
        回傳 (打手 hwnd 或 None, [帳號 hwnd], {hwnd: 角色}, [存了但沒開的名字])；從來沒設定過回傳 None。"""
        shared = load_shared()
        memo = {k: tuple(v) for k, v in (shared.get("fuel_slots") or {}).items() if v}
        if not memo:
            return None
        by_name = {rd.window_label(h): h for h in rd.find_windows()}
        leader_name = shared.get("fuel_leader_name") or ""
        leader = by_name.get(leader_name)
        slots = {by_name[n]: sl for n, sl in memo.items() if n in by_name and n != leader_name}
        gone = [n for n in memo if n not in by_name]
        return leader, list(slots), slots, gone

    def fuel_start(self):
        if not self._idle("開始"):
            return
        if not self.fuel_save():
            return
        if self.fixed_hwnd:
            self.unfix_window()

        def go(leader, accounts, slots):
            self.start(lambda: rp.fuel_run(leader=leader, accounts=accounts, slots=slots),
                       "燃料輪替中，請勿操作滑鼠鍵盤", target=self.fuel_log)

        self.fuel_log.delete("1.0", "end")
        plan = self.fuel_saved_plan()
        if plan is None:                              # 還沒設定過：先設定，按確定就開始
            messagebox.showinfo("還沒設定", "還沒設定要吸燃料的角色，先設定一次（之後按開始就會直接照這個跑）。")
            self.party_pick(go, fuel=True)
            return
        leader, accounts, slots, gone = plan
        if not accounts:
            messagebox.showinfo("存好的帳號都沒開",
                                "燃料角色設定裡勾的帳號，這次一個都沒開：\n" + "、".join(gone)
                                + "\n\n請把遊戲開起來，或按「燃料角色設定…」重新勾。")
            return
        label = {2: "第2隻", 3: "第3隻", 1: "本尊"}
        shared = load_shared()
        leader_name = shared.get("fuel_leader_name") or ""
        self.log("照「燃料角色設定」開始：打手 " + (leader_name or "不在這台電腦")
                 + ("（⚠ 打手的視窗這次沒開）" if leader_name and not leader else "") + "\n" + "".join(
                     f"  {rd.window_label(h)}：吸 " + "、".join(label[n] for n in (2, 3, 1) if n in sl)
                     + ("（吸完換回本尊）" if 1 not in sl else "") + "\n" for h, sl in slots.items())
                 + ("  這次沒開、跳過：" + "、".join(gone) + "\n" if gone else ""),
                 "head", target=self.fuel_log)
        go(leader, accounts, slots)

    def fuel_clear(self):
        if not messagebox.askyesno("清除今天的燃料紀錄",
                                   "程式會忘記今天哪些角色的燃料已經吸滿，下次全部重新確認。要清除嗎？"):
            return
        import json as _json
        st = rd._state()
        st["done"] = {k: v for k, v in st["done"].items() if not k.startswith("fuel|")}
        rd._save_state(st)
        self.log("已清除今天的燃料紀錄。\n", "head")

    def clear_today(self):
        if messagebox.askyesno("清除今天的完成紀錄",
                               "程式會忘記今天哪些帳號、哪些任務已經做完，下次全部重新檢查。\n"
                               "（在遊戲裡手動登出換了帳號、但沒重開遊戲時用）\n\n要清除嗎？"):
            rd.clear_today()
            self.log("已清除今天的完成紀錄，下次會全部重新檢查。\n", "head")

    def _build_party(self):
        f = self.tab_party
        cfg = load_shared()
        ttk.Label(f, text="小號自己申請進隊長的隊伍，戰鬥次數打滿 10000 就自己離隊。"
                          "程式每隔幾分鐘巡一輪，全部打滿才停。\n"
                          "先到「校正 → ⑤ 組隊輪替」把模板和位置抓好，"
                          "小號要跟隊長在同一張地圖、❤ 最愛裡只放隊長。",
                  foreground="#666", wraplength=660, justify="left").pack(
            fill="x", padx=8, pady=(8, 4))

        box = ttk.LabelFrame(f, text="設定", padding=8)
        box.pack(fill="x", padx=8, pady=4)
        self.party_vars = {}
        ttk.Label(box, text="隊長和小號：按「開始輪替」時會跳出視窗讓你選，會記住上次的選擇。",
                  foreground="#1a5fb4").grid(row=99, column=0, columnspan=2, sticky="w", pady=(6, 0))
        rows = [
            ("party_size", "隊伍上限人數（含隊長）", int, cfg.get("party_size", rp.PARTY_SIZE)),
            ("party_interval_min", "每輪間隔幾分鐘", float,
             cfg.get("party_interval_min", rp.INTERVAL_MIN)),
            ("stop_key", "全域停止鍵（f1~f12、pause、insert…；改了要重開程式）", str,
             cfg.get("stop_key", rd.STOP_KEY)),
        ]
        for i, (key, label, cast, val) in enumerate(rows):
            ttk.Label(box, text=label, width=44, anchor="w").grid(row=i, column=0, sticky="w", pady=3)
            var = tk.StringVar(value=str(val))
            ttk.Entry(box, textvariable=var, width=14).grid(row=i, column=1, sticky="w")
            self.party_vars[key] = (var, cast)

        bar = ttk.Frame(f, padding=(8, 6))
        bar.pack(fill="x")
        self.btn_party = ttk.Button(bar, text="開始輪替", width=12, command=self.party_start)
        self.btn_party.pack(side="left")
        ttk.Button(bar, text="只巡一輪（測試）", command=lambda: self.party_start(once=True)
                   ).pack(side="left", padx=6)
        ttk.Button(bar, text="儲存設定", command=self.party_save).pack(side="left", padx=6)
        self.btn_party_stop = ttk.Button(bar, text="停止", width=8, command=self.stop,
                                         state="disabled")
        self.btn_party_stop.pack(side="left", padx=(18, 0))
        ttk.Button(bar, text="清除紀錄",
                   command=lambda: self.party_log.delete("1.0", "end")).pack(side="right")

        self.party_status = tk.StringVar(value="尚未開始")
        ttk.Label(f, textvariable=self.party_status, foreground="#1a5fb4",
                  font=("Microsoft JhengHei", 10, "bold")).pack(anchor="w", padx=10, pady=(0, 4))

        frame = ttk.Frame(f, padding=(8, 0, 8, 8))
        frame.pack(fill="both", expand=True)
        self.party_log = tk.Text(frame, wrap="word", font=("Consolas", 10),
                                 bg="#1e1e1e", fg="#dcdcdc", insertbackground="#dcdcdc")
        sb = ttk.Scrollbar(frame, command=self.party_log.yview)
        self.party_log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.party_log.pack(side="left", fill="both", expand=True)
        for tag, color in (("ok", "#6ac46a"), ("bad", "#e06c6c"),
                           ("head", "#6cb6ff"), ("warn", "#e0b060")):
            self.party_log.tag_config(tag, foreground=color)

    def party_save(self):
        cfg = load_shared()
        try:
            for key, (var, cast) in self.party_vars.items():
                raw = var.get().strip()
                if key == "party_alt_windows":
                    wins = set()
                    for part in raw.replace("，", ",").split(","):
                        part = part.strip()
                        if not part:
                            continue
                        if "-" in part:
                            a, b = part.split("-", 1)
                            wins.update(range(int(a), int(b) + 1))
                        else:
                            wins.add(int(part))
                    cfg[key] = sorted(wins)
                else:
                    cfg[key] = cast(raw)
        except ValueError:
            messagebox.showwarning("數值有誤", "請確認填的是數字。")
            return False
        save_shared(cfg)
        rp._load()
        self.log("組隊設定已儲存。\n", "ok")
        return True

    def party_start(self, once=False):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("正在執行", "等目前的工作停下來再開始。")
            return
        if not self.party_save():
            return
        if self.fixed_hwnd:
            self.unfix_window()
        self.party_pick(lambda leader, alts: self._party_go(once, leader, alts))

    def _party_go(self, once, leader, alts):
        self.party_log.delete("1.0", "end")
        self.start(lambda: rp.run(once=once, leader=leader, alts=alts),
                   "組隊輪替中（只巡一輪）" if once else "組隊輪替中，請勿操作滑鼠鍵盤",
                   target=self.party_log)

    def party_pick(self, then, fuel=False, ok_text="確定，開始"):
        """彈出視窗選隊長和小號。記名字（不是編號），下次自動勾好；按確定才呼叫 then(隊長 hwnd 或 None, [小號 hwnd])。

        fuel=True（燃料輪替）：每個帳號改成三個勾「第2隻、第3隻、本尊」，都不勾 = 這個帳號不輪替。
        跟組隊輪替分開記（shared 的 fuel_leader_name、fuel_slots），呼叫 then(打手, [帳號], {帳號: (角色…)})。
        """
        hwnds = rd.find_windows()
        if not hwnds:
            messagebox.showinfo("找不到視窗", "目前沒有遊戲視窗。")
            return
        rows = [(h, rd.kind_of(h), rd.window_label(h)) for h in hwnds]
        names = [r[2] for r in rows]
        shared = load_shared()
        last_leader = shared.get("party_leader_name")
        last_alts = shared.get("party_alt_names")
        if last_leader is None:                      # 舊設定是編號：換算成名字
            ln = int(shared.get("party_leader_window", 0) or 0)
            last_leader = names[ln - 1] if 1 <= ln <= len(names) else ""
        if last_alts is None:
            nums = shared.get("party_alt_windows") or []
            last_alts = ([names[n - 1] for n in nums if 1 <= n <= len(names)] if nums
                         else [x for x in names if x != last_leader])
        SLOTS = ((2, "第2隻"), (3, "第3隻"), (1, "本尊"))
        last_slots = {}
        if fuel:
            last_leader = shared.get("fuel_leader_name", last_leader) or ""
            last_slots = {k: list(v) for k, v in (shared.get("fuel_slots") or {}).items()}
            last_alts = [k for k, v in last_slots.items() if v]
        heads = (("種類", "名稱", "打手") + tuple(t for _, t in SLOTS) + ("",)) if fuel \
            else ("種類", "名稱", "隊長", "小號", "")
        ncol = len(heads)

        win = tk.Toplevel(self.root)
        win.withdraw()
        win.title("選打手和要吸燃料的角色" if fuel else "選隊長和小號")
        win.transient(self.root)
        body = ttk.Frame(win, padding=12)
        body.pack(fill="both", expand=True)
        hint = ("打手選一個；每個帳號勾要吸燃料的角色，都不勾 = 這個帳號不輪替，程式不會碰它。\n"
                "沒勾本尊的帳號，吸完會自動換回本尊。會記住這次勾的，下次自動勾好。按「認一下」那個視窗會跳到最前面。"
                if fuel else "隊長選一個、小號勾要巡的。按「認一下」那個視窗會跳到最前面。")
        ttk.Label(body, text=hint, foreground="#666", justify="left").grid(
            row=0, column=0, columnspan=ncol, sticky="w", pady=(0, 8))
        leader_var = tk.StringVar(value=last_leader if last_leader in names else "")
        ttk.Radiobutton(body, text="打手不在這台電腦" if fuel else "隊長不在這台電腦",
                        variable=leader_var, value="").grid(row=1, column=0, columnspan=ncol, sticky="w", pady=(0, 6))
        for c, text in enumerate(heads):
            ttk.Label(body, text=text, font=("Microsoft JhengHei", 9, "bold")).grid(
                row=2, column=c, sticky="w", padx=6)
        alt_vars = []                                # 組隊：每列一個勾；燃料：每列 [(角色, 勾)…]
        for i, (h, kind, name) in enumerate(rows, 3):
            ttk.Label(body, text=kind).grid(row=i, column=0, sticky="w", padx=6, pady=2)
            ttk.Label(body, text=name).grid(row=i, column=1, sticky="w", padx=6)
            ttk.Radiobutton(body, variable=leader_var, value=name).grid(row=i, column=2, padx=6)
            if fuel:
                vs = []
                for c, (slot, _) in enumerate(SLOTS, 3):
                    v = tk.BooleanVar(value=(slot in last_slots.get(name, []) and name != leader_var.get()))
                    ttk.Checkbutton(body, variable=v).grid(row=i, column=c, padx=6)
                    vs.append((slot, v))
                alt_vars.append(vs)
            else:
                v = tk.BooleanVar(value=(name in last_alts and name != leader_var.get()))
                ttk.Checkbutton(body, variable=v).grid(row=i, column=3, padx=6)
                alt_vars.append(v)
            ttk.Button(body, text="認一下", width=7,
                       command=lambda h=h: self.peek_window(h, win)).grid(row=i, column=ncol - 1, padx=6)

        def leader_changed(*_):                      # 選成隊長（打手）的那隻自動取消勾選
            for (h, kind, name), v in zip(rows, alt_vars):
                if name == leader_var.get():
                    for _, x in (v if fuel else [(0, v)]):
                        x.set(False)
        leader_var.trace_add("write", leader_changed)

        r = len(rows) + 3
        gone = [x for x in [last_leader] + list(last_alts) if x and x not in names]
        if gone:
            ttk.Label(body, text="上次選的這幾個這次沒開：" + "、".join(dict.fromkeys(gone)),
                      foreground="#c01c28").grid(row=r, column=0, columnspan=ncol, sticky="w", pady=(8, 0))
            r += 1

        def ok():
            leader_name = leader_var.get()
            shared2 = load_shared()
            leader = next((h for h, kind, name in rows if name == leader_name), None)
            if fuel:
                picked = {}
                for (h, kind, name), vs in zip(rows, alt_vars):
                    sl = tuple(slot for slot, v in vs if v.get()) if name != leader_name else ()
                    picked[name] = (h, sl)
                alts = [h for h, sl in picked.values() if sl]
                if not alts:
                    messagebox.showinfo("沒有要吸的角色", "至少勾一隻要吸燃料的角色。", parent=win)
                    return
                memo = dict(last_slots)               # 這次沒開的帳號，保留上次勾的
                memo.update({name: list(sl) for name, (h, sl) in picked.items()})
                shared2["fuel_leader_name"] = leader_name
                shared2["fuel_slots"] = memo
                save_shared(shared2)
                slots = {h: sl for h, sl in picked.values() if sl}
                label = {2: "第2隻", 3: "第3隻", 1: "本尊"}
                self.log("燃料角色設定：打手 " + (leader_name or "不在這台電腦") + "\n" + "".join(
                    f"  {rd.window_label(h)}：吸 " + "、".join(label[n] for n in (2, 3, 1) if n in sl)
                    + ("（吸完換回本尊）" if 1 not in sl else "") + "\n" for h, sl in slots.items()),
                    target=self.fuel_log)
                win.destroy()
                then(leader, alts, slots)
                return
            alts = [h for (h, kind, name), v in zip(rows, alt_vars) if v.get() and name != leader_name]
            if not alts:
                messagebox.showinfo("沒有小號", "至少勾一隻小號。", parent=win)
                return
            shared2["party_leader_name"] = leader_name
            shared2["party_alt_names"] = [name for (h, kind, name), v in zip(rows, alt_vars)
                                          if v.get() and name != leader_name]
            save_shared(shared2)
            self.log("組隊：隊長 " + (leader_name or "不在這台電腦") + "，小號 "
                     + "、".join(rd.window_label(h) for h in alts) + "\n")
            win.destroy()
            then(leader, alts)

        bar = ttk.Frame(body)
        bar.grid(row=r, column=0, columnspan=ncol, sticky="e", pady=(12, 0))
        ttk.Button(bar, text=ok_text, command=ok).pack(side="left", padx=4)
        ttk.Button(bar, text="取消", command=win.destroy).pack(side="left", padx=4)

        win.update_idletasks()
        ww, wh = win.winfo_reqwidth(), win.winfo_reqheight()
        rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
        rw, rh = self.root.winfo_width(), self.root.winfo_height()
        win.geometry(f"{ww}x{wh}+{rx + max(0, (rw - ww) // 2)}+{ry + max(0, (rh - wh) // 2)}")
        win.deiconify()
        win.lift()
        win.attributes("-topmost", True)
        win.after(600, lambda: win.attributes("-topmost", False))
        win.focus_force()

    def peek_window(self, hwnd, dialog):
        """讓那個遊戲視窗跳到最前面一下，方便認是哪隻角色；1.5 秒後選擇視窗再回到前面。"""
        try:
            rd.focus(hwnd)
        except Exception:
            pass

        def back():
            try:
                dialog.lift()
                dialog.attributes("-topmost", True)
                dialog.after(300, lambda: dialog.attributes("-topmost", False))
            except tk.TclError:
                pass                                 # 選擇視窗已經關了
        dialog.after(1500, back)

    # ==================================================================
    # 設定
    # ==================================================================
    def _build_settings(self):
        f = self.tab_set
        cfg = load_cfg()
        box = ttk.LabelFrame(f, text="常用", padding=8)
        box.pack(fill="x", padx=8, pady=8)
        adv_wrap = ttk.Frame(f)
        adv_wrap.pack(fill="x", padx=8)
        adv_btn = ttk.Button(adv_wrap, text="▶ 顯示進階設定（通常不用動）")
        adv_btn.pack(anchor="w")
        adv = ttk.LabelFrame(adv_wrap, text="進階（通常不用動，改錯可能要重抓模板）", padding=8)

        def toggle_adv():
            if adv.winfo_ismapped():
                adv.pack_forget()
                adv_btn.configure(text="▶ 顯示進階設定（通常不用動）")
            else:
                adv.pack(fill="x", pady=(4, 0))
                adv_btn.configure(text="▼ 收起進階設定")
        adv_btn.configure(command=toggle_adv)
        self.set_vars = {}
        rows = {"common": 0, "adv": 0}
        for key, label, cast, default in SETTINGS:
            which = "adv" if key in ADVANCED_SETTINGS else "common"
            parent = adv if which == "adv" else box
            i = rows[which]
            rows[which] += 1
            ttk.Label(parent, text=label, width=46, anchor="w").grid(
                row=i, column=0, sticky="w", pady=3)
            # 沒寫進 config 的，顯示目前環境實際在用的值。
            # 以前顯示的是官方的預設，在雷電按「儲存」會把快捷鍵、ESC、視窗標題全改成官方的。
            val = cfg.get(key, getattr(rd, key.upper(), default))
            if cast is bool:
                var = tk.BooleanVar(value=bool(val))
                ttk.Checkbutton(parent, variable=var).grid(row=i, column=1, sticky="w")
            else:
                var = tk.StringVar(value=str(val))
                ttk.Entry(parent, textvariable=var, width=10).grid(row=i, column=1, sticky="w")
            self.set_vars[key] = (var, cast)
        row = ttk.Frame(f)
        row.pack(anchor="w", padx=8, pady=(10, 0))
        ttk.Button(row, text="儲存設定", command=self.save_settings).pack(side="left")
        ttk.Button(row, text="打包給朋友（產生 zip）", command=self.pack_for_friend
                   ).pack(side="left", padx=12)
        upd = ttk.LabelFrame(f, text="更新", padding=8)
        upd.pack(fill="x", padx=8, pady=(12, 0))
        ttk.Label(upd, text=f"目前版本：{__version__}　　更新來源：{UPDATE_PAGE}",
                  foreground="#555").pack(anchor="w")
        urow = ttk.Frame(upd)
        urow.pack(anchor="w", pady=(6, 0))
        self.btn_update = ttk.Button(urow, text="檢查更新", command=lambda: self.check_update(False))
        self.btn_update.pack(side="left")
        ttk.Button(urow, text="退回上一版", command=self.rollback_update).pack(side="left", padx=8)
        ttk.Button(urow, text="發布更新（作者用）", command=self.publish_update).pack(side="left", padx=(24, 0))
        ttk.Label(f, text=f"設定檔：{rd.CONFIG_PATH}\n模板資料夾：{rd.TEMPLATE_DIR}\n"
                          f"失敗截圖：{rd.SHOT_DIR}",
                  foreground="#666", justify="left").pack(anchor="w", padx=8, pady=12)

    @staticmethod
    def friend_readme():
        """打包給朋友時附上的說明（給朋友看，所以用白話、不講程式內部）。"""
        stop = (rd.STOP_KEY or "f12").upper()
        return f"""ROM 日常助手 v{__version__}　給朋友的說明
==================================================

一、第一次安裝
  1. 到 python.org 下載安裝 Python。
     安裝畫面最下面一定要勾「Add python.exe to PATH」。
  2. 把這個壓縮檔解壓到一個固定的資料夾（例如 C:\\rom）。
     不要在壓縮檔裡面直接執行。
  3. 執行 install.bat，安裝需要的套件（只要做一次）。
  4. 之後每次使用：執行 start.bat → 選環境（官方 或 雷電）。

二、已經幫你準備好的
  ・官方、雷電兩個環境的按鈕位置和圖片都已經校正好，不用重新抓。
  ・沒有附上：原主人的失敗截圖、兌換序號、遊戲安裝路徑、組隊的視窗安排。

三、官方（電腦版客戶端）
  ・按鈕位置和圖片可以直接用。
  ・遊戲內的快捷鍵請保持預設：
      {rd.PET_KEY.upper()} 寵物手冊、{rd.DAILY_KEY.upper()} 日常、{rd.DUNGEON_KEY.upper()} 副本、ESC 設置
    改過的話程式會打不開面板。

四、雷電模擬器
  ・每一個模擬器都要設成：解析度 1280×720、DPI 240（平板版）。
    這個不能改，改了圖片就對不上。
  ・關掉「按鍵提示」（會蓋住遊戲按鈕）。
  ・多開建議：CPU 2 核、記憶體 2048M、幀率上限選「標準」，比較不卡。
  ・遊戲快捷列第一格要放「寵物箱」（寵物手冊），程式是點那一格開寵物打工的。
    放的位置不一樣的話：校正頁 →「寵物打工」那組 → 重抓
    「快捷列上『寵物手冊』那一格」就好，其他不用動。
  ・遊戲有開省電模式沒關係，程式開始前會先點一下把它叫醒。

五、跑的時候
  ・不要碰滑鼠和鍵盤，也不要開別的視窗蓋住遊戲。
  ・要中途停止：按 {stop}。
  ・最上面「執行」選「自動（混合）」：官方和雷電可以同時開、一起跑，
    程式會自己分辨每個視窗是哪一種。
  ・第一次使用：控制台先只選一個視窗、只勾一項任務，確定正常再全開。
  ・失敗的話，最後的總結會寫原因，失敗當下的截圖在
    profiles\\（環境名稱）\\shots\\ 資料夾裡。

六、組隊輪替
  ・之後更新：「設定」分頁按「檢查更新」，只換程式檔，你的校正、模板、設定都不會動。
  ・按「開始輪替」會跳出視窗讓你選隊長、勾小號（官方雷電可以混著選），
    之後會記住，下次直接按確定就好。
"""

    # ---------- 更新 ----------
    def _idle(self, what):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("正在執行", f"等目前的工作停下來再{what}。")
            return False
        return True

    def check_update(self, silent=False):
        """silent：開 GUI 時在背景偷偷看一下，有新版只寫一行紀錄，不跳視窗；連不上也不吵。"""
        if not silent and not self._idle("檢查更新"):
            return

        def work():
            try:
                info = remote_info()
            except Exception as e:
                err = str(e)                         # e 離開 except 就會被清掉，先存下來
                if getattr(e, "code", None) == 404:
                    err = "GitHub 上還沒有發布任何版本（作者還沒按過「發布更新」）"
                if not silent:
                    self.ui(lambda: messagebox.showerror(
                        "連不上更新伺服器", f"檢查更新失敗：{err}\n\n可能是網路問題，等一下再試。"))
                return
            self.ui(lambda: self._update_found(info, silent))
        threading.Thread(target=work, daemon=True).start()

    def _sync_templates(self, info, silent):
        """背景補上共用模板和位置（只補缺的），做完通知視窗。
        作者自己的電腦（存了發布鑰匙）不補：模板就是從這台來的，自己刪掉的壞模板不該又被補回來。"""
        if load_token():
            if not silent:
                messagebox.showinfo("已經是最新版", f"目前的 {__version__} 就是最新版。\n"
                                    "（這台是發布用的電腦，不會從 GitHub 補模板）")
            return

        def work():
            try:
                t, p = sync_shared(info, say=lambda m: self.ui(lambda m=m: self.log(m + "\n")))
            except Exception as e:
                err = str(e)
                self.ui(lambda: self.log(f"補共用模板時出錯：{err}\n", "warn"))
                return
            self.ui(lambda: self._synced(t, p, silent))
        threading.Thread(target=work, daemon=True).start()

    def _synced(self, t, p, silent):
        if t or p:
            rd._tmpl_cache.clear()
            rd._mask_cache.clear()
            rd.set_profile(rd.ACTIVE_PROFILE)          # 重新讀一次，新補的位置馬上生效
            rp._load()
            try:
                self.refresh_counts()
            except Exception:
                pass
            self.log(f"補上了共用模板 {t} 張、位置 {p} 個（你原本就有的都沒動）。"
                     "如果某張在你電腦上認不太到，到校正頁按「測試」，分數低的那張自己補抓一張就好。\n", "ok")
        if not silent:
            messagebox.showinfo("已經是最新版", f"目前的 {__version__} 就是最新版。"
                                + (f"\n\n另外補上了共用模板 {t} 張、位置 {p} 個。" if t or p else ""))

    def _update_found(self, info, silent):
        ver = info.get("version", "")
        if not newer(ver, __version__):
            self._sync_templates(info, silent)      # 程式是最新的，也看看有沒有新的共用模板可以補
            return
        if silent:
            self.log(f"有新版 {ver} 可以更新（目前 {__version__}）：到「設定」分頁按「檢查更新」。\n", "warn")
            self.btn_update.configure(text=f"檢查更新（有新版 {ver}）")
            return
        notes = (info.get("notes") or "").strip()
        if not messagebox.askyesno("有新版本",
                                   f"有新版 {ver}（目前 {__version__}）。\n\n"
                                   + (f"這次改了：\n{notes}\n\n" if notes else "")
                                   + "要現在更新嗎？\n（只換程式檔，你的校正、模板、設定都不會動；舊版會先備份）"):
            return
        self.log(f"開始更新到 {ver}…\n", "head")

        def work():
            try:
                files = download_update(info, say=lambda t: self.ui(lambda t=t: self.log(t + "\n")))
                bdir = apply_update(files, __version__)
            except Exception as e:
                err = str(e)
                self.ui(lambda: (self.log(f"更新失敗：{err}（沒有換掉任何檔案）\n", "bad"),
                                            messagebox.showerror("更新失敗", f"{err}\n\n沒有換掉任何檔案，舊版照常可以用。")))
                return
            self.ui(lambda: self._update_done(ver, bdir))
        threading.Thread(target=work, daemon=True).start()

    def _update_done(self, ver, bdir):
        self.log(f"已更新到 {ver}。舊版備份在：{bdir}\n", "ok")
        if messagebox.askyesno("更新完成", f"已更新到 {ver}。\n\n要現在重新開啟程式嗎？"):
            self.restart()

    def restart(self):
        import subprocess
        try:
            subprocess.Popen([sys.executable, os.path.join(rd.BASE_DIR, "gui.pyw")], cwd=rd.BASE_DIR)
        finally:
            self.root.destroy()

    def rollback_update(self):
        if not self._idle("退回"):
            return
        olds = sorted(d for d in (os.listdir(BACKUP_DIR) if os.path.isdir(BACKUP_DIR) else [])
                      if os.path.isdir(os.path.join(BACKUP_DIR, d)) and d != __version__)
        if not olds:
            messagebox.showinfo("沒有可以退回的版本", "還沒有透過「檢查更新」更新過，沒有舊版備份。")
            return
        last = olds[-1]
        if not messagebox.askyesno("退回上一版", f"要退回 {last} 嗎？\n（目前 {__version__} 也會先備份起來）"):
            return
        src = os.path.join(BACKUP_DIR, last)
        files = {n: open(os.path.join(src, n), "rb").read() for n in os.listdir(src) if n in UPDATE_FILES}
        bdir = apply_update(files, __version__)
        self.log(f"已退回 {last}（剛剛的 {__version__} 備份在 {bdir}）\n", "ok")
        if messagebox.askyesno("退回完成", f"已退回 {last}。要現在重新開啟程式嗎？"):
            self.restart()

    def _ask_notes(self, ver):
        """發布時填「這次改了什麼」，朋友更新時會看到。"""
        win = tk.Toplevel(self.root)
        win.title(f"發布 {ver}")
        win.transient(self.root)
        ttk.Label(win, text="這次改了什麼？（朋友按「檢查更新」時會看到）", padding=(10, 8, 10, 4)).pack(anchor="w")
        txt = tk.Text(win, width=60, height=8, font=("Microsoft JhengHei", 10))
        txt.pack(padx=10)
        result = {}

        def ok():
            result["notes"] = txt.get("1.0", "end").strip()
            win.destroy()
        bar = ttk.Frame(win, padding=10)
        bar.pack(fill="x")
        ttk.Button(bar, text="發布", command=ok).pack(side="right")
        ttk.Button(bar, text="取消", command=win.destroy).pack(side="right", padx=6)
        win.grab_set()
        txt.focus_set()
        self.root.wait_window(win)
        return result.get("notes")

    def publish_update(self):
        """作者用：把目前資料夾裡的程式發布到 GitHub。"""
        from tkinter import simpledialog
        if not self._idle("發布"):
            return
        vers = {"gui.pyw": __version__, "rom_daily.py": getattr(rd, "__version__", "?"),
                "rom_party.py": getattr(rp, "__version__", "?")}
        if len(set(vers.values())) > 1:
            messagebox.showerror("版本不一致", "三個程式檔的版本號不一樣，不能發布：\n"
                                 + "\n".join(f"{k}：{v}" for k, v in vers.items()))
            return
        names = [n for n in UPDATE_FILES if os.path.exists(os.path.join(rd.BASE_DIR, n))]
        datas = {n: open(os.path.join(rd.BASE_DIR, n), "rb").read() for n in names}
        for n, d in datas.items():
            try:
                compile(d.decode("utf-8"), n, "exec")
            except Exception as e:
                messagebox.showerror("程式有錯", f"{n} 沒辦法執行，不能發布：\n{e}")
                return
        leaks = [f"{n}：{h}" for n, d in datas.items() for h in personal_leaks(d.decode("utf-8"))]
        if leaks:
            messagebox.showerror("裡面有個人資料", "程式裡找到這些個人資料，GitHub 是公開的，不能發布：\n\n"
                                 + "\n".join(leaks[:10]))
            return

        token = load_token()
        if not token:
            token = simpledialog.askstring(
                "第一次發布：貼上 GitHub 鑰匙",
                "請貼上 GitHub 的鑰匙（github_pat_ 開頭那一串）。\n"
                "會加密存在這台電腦，下次就不用再貼。", show="*", parent=self.root)
            if not token:
                return
            token = token.strip()
            try:
                if gh_api("README.md", token) is None:
                    raise RuntimeError("找不到 rom-helper 裡的 README，鑰匙可能沒有選對 repository")
            except Exception as e:
                messagebox.showerror("鑰匙不能用", str(e))
                return
            save_token(token)
            self.log("GitHub 鑰匙已加密存好（只存在這台電腦）。\n", "ok")

        try:
            cur = remote_info().get("version", "")
        except Exception:
            cur = ""
        if cur and not newer(__version__, cur) and not messagebox.askyesno(
                "版本沒有比較新", f"GitHub 上已經是 {cur}，目前要發布的是 {__version__}。\n"
                                f"朋友不會收到更新提示。確定還是要發布嗎？"):
            return
        tmpl = {prof: local_templates(prof) for prof in rd.PROFILE_NAMES}
        keys = shared_point_keys()
        points = {}
        for prof in rd.PROFILE_NAMES:
            cfg = rd._read_json(os.path.join(rd.PROFILES_DIR, prof, "config.json"))
            points[prof] = {k: cfg[k] for k in keys if k in cfg}
        summary = "、".join(f"{prof} {len(tmpl[prof])} 張" for prof in rd.PROFILE_NAMES)
        if not messagebox.askyesno(
                "一起分享模板和位置",
                f"這次會把你的模板（{summary}）和校正好的位置一起傳上去，朋友更新時會「只補他缺的」。\n\n"
                "GitHub 是公開的：請確認模板裡沒有截到角色名字或聊天內容。\n"
                f"（模板在 {rd.PROFILES_DIR} 底下各環境的 templates 資料夾，可以先打開看看）\n\n"
                "要一起分享嗎？（按「否」就只發布程式）"):
            tmpl, points = {}, {}
        notes = self._ask_notes(__version__)
        if notes is None:
            return

        def job():
            import hashlib, time as _t
            print(f"===== 發布 {__version__} 到 {UPDATE_PAGE} =====")
            msg = f"發布 {__version__}"
            commit = None                             # 最後一次上傳後的快照編號（包含前面傳的所有檔案）

            def put(path, data):
                nonlocal commit
                r = gh_put(path, data, token, msg)
                c = (r or {}).get("commit", {}).get("sha") if isinstance(r, dict) else None
                commit = c or commit
            for n in names:
                print(f"  上傳 {n} …", flush=True)
                put(n, datas[n])
            print("  更新說明頁（README.md）…", flush=True)
            put("README.md", GITHUB_README.encode("utf-8"))
            manifest = {}
            for prof, files in tmpl.items():
                remote = gh_api(f"templates/{prof}", token) or []
                rsha = {it["name"]: it["sha"] for it in remote if isinstance(it, dict) and it.get("type") == "file"}
                up = [n for n, d in files.items() if rsha.get(n) != git_sha(d)]
                gone = [n for n in rsha if n not in files]
                print(f"  {prof} 模板：共 {len(files)} 張，要上傳 {len(up)} 張（新的或改過的）、"
                      f"刪掉 {len(gone)} 張（你已經刪掉的）", flush=True)
                for k, n in enumerate(up, 1):
                    put(f"templates/{prof}/{n}", files[n])
                    if k % 10 == 0 or k == len(up):
                        print(f"    已上傳 {k}/{len(up)}", flush=True)
                for n in gone:
                    r = gh_delete(f"templates/{prof}/{n}", rsha[n], token, msg)
                    c = (r or {}).get("commit", {}).get("sha") if isinstance(r, dict) else None
                    commit = c or commit
                manifest[prof] = {n: hashlib.sha256(d).hexdigest() for n, d in files.items()}
            info = {"version": __version__, "notes": notes,
                    "published": _t.strftime("%Y-%m-%d %H:%M"),
                    "files": {n: {"sha256": hashlib.sha256(datas[n]).hexdigest(), "size": len(datas[n])}
                              for n in names},
                    "templates": manifest, "points": points,
                    "commit": commit}                 # 朋友下載時指定這個快照，不會拿到快取的舊檔
            if commit:
                print(f"  這次的快照編號：{commit[:10]}…", flush=True)
            print("  最後上傳版本資訊（version.json）：朋友從這一刻開始收得到更新", flush=True)
            gh_put("version.json", json.dumps(info, ensure_ascii=False, indent=1).encode("utf-8"), token, msg)
            print(f"→ 發布完成：{__version__}。朋友按「檢查更新」就會拿到。")
        self.start(job, "發布更新中")

    def pack_for_friend(self):
        """把程式檔、共用設定、兩個環境的模板與座標打成一個 zip（不含失敗截圖）。"""
        out = os.path.join(rd.BASE_DIR, "ROM_helper.zip")
        files = ["rom_daily.py", "rom_party.py", "gui.pyw",
                 "install.bat", "start.bat", "README.txt"]
        # 共用設定裡這些是「你自己的」，不給朋友：序號、你電腦上的遊戲路徑、你的組隊視窗安排
        personal = ("redeem_code", "party_leader_window", "party_alt_windows",
                    "party_leader_name", "party_alt_names")
        try:
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
                for name in files:
                    path = os.path.join(rd.BASE_DIR, name)
                    if os.path.exists(path):
                        z.write(path, name)
                shared = {k: v for k, v in rd._read_json(rd.SHARED_CONFIG_PATH).items()
                          if k not in personal and not k.startswith("instances_")}
                z.writestr("config.json", json.dumps(shared, ensure_ascii=False, indent=2))
                # 記事本才不會亂碼：UTF-8 帶 BOM、Windows 換行
                readme = self.friend_readme().replace("\n", "\r\n").encode("utf-8-sig")
                z.writestr("給朋友的說明.txt", readme)
                for root, dirs, fnames in os.walk(rd.PROFILES_DIR):
                    dirs[:] = [d for d in dirs if d != "shots"]      # 失敗截圖不帶
                    for fn in fnames:
                        full = os.path.join(root, fn)
                        z.write(full, os.path.relpath(full, rd.BASE_DIR))
            n = len(zipfile.ZipFile(out).namelist())
            self.log(f"已打包 {n} 個檔案 → {out}\n", "ok")
            self.log("（沒帶：失敗截圖、兌換序號、你電腦上的遊戲路徑、組隊的視窗安排）\n")
            self.log("已附上「給朋友的說明.txt」：安裝步驟、官方和雷電要注意的設定，朋友解壓就看得到。\n")
            self.log("傳給朋友時用 Google 雲端硬碟或 LINE，Gmail 附件會擋裡面的 .bat。\n")
        except Exception as e:
            self.log(f"打包失敗：{e}\n", "bad")

    def save_settings(self):
        cfg = load_cfg()
        try:
            for key, (var, cast) in self.set_vars.items():
                cfg[key] = cast(var.get()) if cast is not bool else bool(var.get())
        except ValueError:
            messagebox.showwarning("數值有誤", "門檻和座標要填數字。")
            return
        save_cfg(cfg)
        rp._load()
        self.update_profile_hint()
        self.refresh_counts()
        self.log("設定已儲存並套用。\n", "ok")

    # ==================================================================
    # 共用
    # ==================================================================
    @staticmethod
    def line_tag(text):
        s = text.lstrip()
        return ("ok" if s.startswith(("OK", "→ 完成")) else
                "bad" if s.startswith(("!!", "→ 失敗")) else
                "warn" if s.startswith(("→ 要手動處理", "另外")) else
                "head" if s.startswith("===") else
                "warn" if ("異常" in s or "失敗" in s) else None)

    def log(self, text, tag=None, target=None):
        box = target or self.logbox
        if tag is None and any(m in text for m in "✓✗⚠"):
            # 總結那種一行好幾項的：✓ 那段綠、✗ 那段紅、⚠（要你手動處理）黃、「｜補跑→」一般顏色；
            # 開頭的 OK／!!（這個帳號是不是全部完成）照舊
            parts = re.split(r"(?=[✓✗⚠])|(?=｜補跑→)", text)
            box.insert("end", parts[0], self.line_tag(parts[0]))
            for part in parts[1:]:
                box.insert("end", part, "ok" if part.startswith("✓") else
                                        "bad" if part.startswith("✗") else
                                        "warn" if part.startswith("⚠") else None)
        else:
            box.insert("end", text, tag if tag is not None else self.line_tag(text))
        box.see("end")
        # 組隊紀錄裡的狀態摘要順便放到上方的狀態列
        if box is getattr(self, "party_log", None) and text.lstrip().startswith("狀態："):
            self.party_status.set(text.strip())

    def clear_log(self):
        self.logbox.delete("1.0", "end")

    def ui(self, fn):
        """背景執行緒用：請視窗（主執行緒）待會做 fn。安全，不會直接碰 tkinter。"""
        self.uiq.put(fn)

    def pump(self):
        self.drain()
        while True:
            try:
                fn = self.uiq.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception as e:
                self.log(f"（介面更新時出錯：{e}）\n", "warn")
        self.root.after(100, self.pump)

    def drain(self):
        try:
            while True:
                self.log(self.q.get_nowait(), target=self.active_log)
        except queue.Empty:
            pass

    def busy(self, on, label=""):
        state = "disabled" if on else "normal"
        self.btn_run.configure(state=state)
        self.btn_party.configure(state=state)
        self.btn_stop.configure(state="normal" if on else "disabled")
        self.btn_party_stop.configure(state="normal" if on else "disabled")
        self.btn_fuel.configure(state=state)
        self.btn_fuel_set.configure(state=state)
        self.btn_fuel_stop.configure(state="normal" if on else "disabled")
        self.status.set((label + f"　｜　按 {rd.STOP_KEY.upper()} 立刻停止") if on
                        else f"待命中（執行中按 {rd.STOP_KEY.upper()} 可立刻停止）")
        if not on:
            self.drain()                       # 把佇列裡剩的訊息倒完再切回預設紀錄區
            if self.active_log is self.party_log:
                self.party_status.set(self.party_status.get() + "　（已停止）")
            self.active_log = self.logbox

    def start(self, fn, label, target=None):
        if self.worker and self.worker.is_alive():
            return
        rd.ABORT = False
        self.active_log = target or self.logbox
        self.busy(True, label)

        def job():
            old = sys.stdout
            sys.stdout = QueueWriter(self.q)
            try:
                fn()
            except Exception as e:
                print(f"\n發生錯誤：{e}")
            finally:
                sys.stdout = old
                rd.ABORT = False                 # 停止的旗子放下，不然之後校正頁一截圖就會當成「要中止」
                self.ui(lambda: self.busy(False))

        self.worker = threading.Thread(target=job, daemon=True)
        self.worker.start()

    def _calm(self):
        """校正頁的動作（測試、抓取、固定視窗）前：沒有在跑的話，把停止的旗子放下。
        （按過 F12 或停止之後旗子會一直舉著，截圖就會被當成「要中止」而出錯。）"""
        if not (self.worker and self.worker.is_alive()):
            rd.ABORT = False

    def on_close(self):
        if self.fixed_hwnd:
            self.unfix_window()
        self.root.destroy()


def _report_crash():
    """閃退時把完整錯誤寫到 gui_error.log，並盡量跳視窗顯示。"""
    import traceback
    text = traceback.format_exc()
    try:
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui_error.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("=" * 60 + "\n" + text + "\n")
    except Exception:
        log_path = "(寫不進去)"
    try:
        import tkinter.messagebox as _mb
        _r = tk.Tk(); _r.withdraw()
        _mb.showerror("ROM 日常助手 啟動失敗",
                      f"錯誤已寫到：\n{log_path}\n\n最後幾行：\n" + "\n".join(text.strip().splitlines()[-6:]))
    except Exception:
        pass


if __name__ == "__main__":
    try:
        rd.enable_dpi_awareness()
        rd.start_stop_hotkey()
        root = tk.Tk()
        try:
            style = ttk.Style()
            for theme in ("vista", "clam"):
                if theme in style.theme_names():
                    style.theme_use(theme)
                    break
        except Exception:
            pass
        app = App(root)
        root.protocol("WM_DELETE_WINDOW", app.on_close)

        def _cb_error(exc, val, tb):
            """按鈕背後出錯時，把錯誤印進紀錄區，而不是默默吞掉。"""
            import traceback
            text = "".join(traceback.format_exception(exc, val, tb))
            try:
                app.log("按鈕執行出錯：\n" + text + "\n", "bad")
            except Exception:
                pass
            try:
                with open(os.path.join(rd.BASE_DIR, "gui_error.log"), "a", encoding="utf-8") as f:
                    f.write("=" * 60 + "\n" + text + "\n")
            except Exception:
                pass
        root.report_callback_exception = _cb_error
        root.mainloop()
    except Exception:
        _report_crash()
