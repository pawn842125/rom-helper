#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ROM Classic 多開日常自動化（第三版）
====================================

設計原則：每項任務有自己的入口、自己的證據，彼此不依賴。

    1. 寵物打工   入口：F1 開寵物手冊 → 點右邊「寵物打工」分頁
                              證據：九宮格每格點過 / 畫面上沒剩可領圖示
    2. 任務委託板 入口：日常清單 → 前往   證據：看板上 3 個已完成印章
    3. 領取獎勵   入口：日常清單          證據：畫面上沒剩任何「領取」按鈕
    4. 每日福利   入口：熱點 → 每日福利   證據：按鈕變成「已簽到」

順序是固定的：簽到要日常完成三項（歡迎回來 + 委託板 + 寵物打工）才能進，
所以一定排在最後。

沒有「複查」也沒有「補做」—— 每一步做完當場就有證據，不需要回頭再開日常掃一次。
每個帳號只會開關日常兩次（委託板入口一次、領取一次）。

用法：
    python rom_daily.py run            # 全部視窗
    python rom_daily.py test 3         # 只跑第 3 個視窗
    python rom_daily.py pet 3          # 只測寵物打工
    python rom_daily.py bonus 3        # 只測每日福利
    python rom_daily.py scrolltest 3   # 測捲動
    python rom_daily.py match a.png    # 測模板分數
    python rom_daily.py snap           # 每個視窗截一張圖

前置條件：每個帳號都要把「寵物手冊」放到同一個快捷鍵上（預設 F1），
並在 GUI 校正分頁抓好「寵物打工分頁」的位置和九宮格。
"""

import ctypes
import json
import os
import re
import sys
import time

import cv2
import numpy as np
import pyautogui
import win32api
import win32con
import win32gui
from PIL import ImageGrab

# ---------------------------------------------------------------------------
# 設定區
# ---------------------------------------------------------------------------
#
# 設定分兩層：
#   共用設定  BASE_DIR/config.json            目前用哪個環境、組隊輪替的設定
#   環境設定  BASE_DIR/profiles/<環境>/config.json + templates/ + shots/
#             視窗標題、尺寸、快捷鍵、所有座標與模板 —— 官方 PC 版和雷電模擬器各一份
#
# 程式邏輯兩個環境共用，只有資料不同。

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILES_DIR = os.path.join(BASE_DIR, "profiles")
SHARED_CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

PROFILE_NAMES = ["官方", "雷電"]
ACTIVE_PROFILE = "官方"
TEMPLATE_DIR = os.path.join(PROFILES_DIR, "官方", "templates")   # set_profile 會重設
SHOT_DIR = os.path.join(PROFILES_DIR, "官方", "shots")
CONFIG_PATH = os.path.join(PROFILES_DIR, "官方", "config.json")

# ---- 兩個環境共通的基準值（環境預設值和 config 會往上蓋）----
__version__ = "2026.11.05n"

WINDOW_TITLE = "ROM Classic"     # 遊戲視窗標題，部分符合即可
WINDOW_EXCLUDE = []              # 標題含這些字的視窗不算遊戲（例如雷電的「多開器」）
WINDOW_EXES = []                 # 也用「是哪個程式開的」來認視窗（標題被改名也認得到）
HOTKEYS = True                   # 遊戲吃不吃 F1 / I / T / O 快捷鍵；False 就改點螢幕按鈕進入
USE_ESC = True                   # 關面板的最後手段可不可以按 ESC（模擬器裡 ESC = 返回鍵，會跳退出遊戲，要關）

WORK_X, WORK_Y = 60, 60          # 工作時把視窗搬到這裡
WORK_W, WORK_H = 800, 500        # 工作區目標尺寸（改了就要重抓模板）

# 工作區要對準什麼：
#   False = 整個外層視窗（官方 PC 版：視窗裡就只有遊戲，直接用）
#   True  = 視窗裡面「畫遊戲的那個子視窗」（雷電：外面還包著分頁列和工具列，
#           它們的粗細會跟 Windows 縮放比例變，只有子視窗才是穩定的）
USE_RENDER_CHILD = False
RENDER_CHILD_TITLE = "TheRender"  # 雷電畫遊戲的子視窗標題

# 執行期間實際的工作區（normalize_window 會設定；所有截圖與點擊都以這個為準）
AREA_X, AREA_Y, AREA_W, AREA_H = WORK_X, WORK_Y, WORK_W, WORK_H

MATCH_THRESHOLD = 0.80
CLICK_OFFSET = {}                # 清單列 → 該列按鈕的偏移，由 GUI 校正寫進 config

SAFE_CLICK = None                # 關彈窗時點的空白處（None 就點視窗頂端中央）
SCROLL_POINT = (400, 313)        # 拖曳清單用的 x（只取 x）
SCROLL_POINT_ALT = (250, 327)    # 第一個 x 拖不動時換這個
LIST_TOP = 110                   # 日常清單可視範圍的上下界（相對視窗）
LIST_BOTTOM = 420                # 拖曳全程都要在這個範圖內，跑出去 Unity 會當作取消

DUNGEON_KEY = "u"                # 打開「副本」面板的快捷鍵
DUNGEON_BTN = None               # 「更多」選單裡的「副本」（沒快捷鍵時從這裡進）
DUNGEON_LIST_X = 125             # 左邊副本清單拖曳用的 x
DUNGEON_LIST_TOP = 110           # 左邊清單的上下界
DUNGEON_LIST_BOTTOM = 430
DUNGEON_TAB_Y = 113              # 上方等級分頁列六角形的中心 y（拖曳起點要壓在六角形上）
DUNGEON_FIRST_TAB = (290, 113)   # 分頁列拖到最左之後，第一格（Lv.20）六角形的中心（實測 294 上下）
STRIP_DRAG_END = 0.95            # 拖分頁列時在工作區寬度幾成的地方放開（要在分頁列外框裡面，跑出去遊戲會當作取消）
MAX_SWEEPS = 14                  # 掃蕩最多點幾次（正常 6 次，漏一天 12 次）
SETTINGS_BTN = None              # 沒快捷鍵時，「更多」選單裡的「設置」位置
REDEEM_CODE = ""                 # 要兌換的序號（由 GUI 或共用設定給）
REDEEM_INPUT_DY = -41            # 序號輸入框在「兌換」按鈕上方多少像素
DAILY_KEY = "i"                  # 打開「日常」面板的快捷鍵
WEEKLY_TAB = (258, 83)           # 日常面板上「週常」分頁的位置（照截圖量的；800x500）
CLAIM_WEEKLY = True              # 領完日常後也切到週常領
PET_KEY = "f1"                   # 打開「寵物手冊」的快捷鍵
PET_TAB = None                   # 寵物手冊右邊「寵物打工」分頁的位置
PET_SLOT = None                  # 快捷列上「寵物手冊」那一格（HOTKEYS=False 時從這裡進）
# 判斷「日常／週常清單有沒有捲動」只看這塊（比例）：每列左邊的圖示和標題。
# 右邊一直閃的「領取」按鈕、x2 標誌、剛領完飄出來的「獲得…」提示框都不在裡面。
# 實測（雷電截圖）：真的捲動最少 13.8（剛好捲一整列），捲 5 像素就 16.7；右半邊全變也只有 0.0。門檻 5。
# 官方原本用舊方法（看整個畫面中間、門檻 2.5），按鈕閃光就被當成有捲動 → 到底了還誤判「清單會跳回頂端」一直盲拉。
# None = 舊方法。
LIST_CHECK_REGION = (0.12, 0.17, 0.40, 0.92)
LIST_MOVE_TOL = 5.0              # 上面那塊平均差異超過多少才算真的捲動
RAW_MOUSE = False                # 拖曳時用「真正的滑鼠移動訊號」（模擬器要；官方用游標瞬移就夠）
QUICK_NO_REMIND = None           # 快速完成偶爾跳的確認視窗：「不再提示」前面的方框
QUICK_CONFIRM_OK = None          # 同一個視窗的綠色「確定」
ABANDON_OK = None                # 「是否要放棄懸賞任務？」視窗的綠色「確定」
TICKET_KEY = "f2"                # 副本掃蕩券放在快捷列 F2（官方按這個鍵）
TICKET_SLOT = None               # 快捷列 F2 那一格（雷電沒快捷鍵時點這裡）
EXCHANGE_SLOT = None             # 快捷列上「交易所」那一格（一鍵上架用；官方雷電都放第 1 格）
RELIST_MAX = 20                  # 一鍵上架最多按幾次（常常一次只上架一兩件，要一直按到按鈕消失）
RED_DOT_SKIP = True              # 日常／週常分頁沒有紅點就跳過領取（紅點 = 有東西可以領）
REMEMBER_DONE = True             # 記住今天做完的任務，同一天重跑直接跳過（早上 6 點重置）
DAILY_BTN = None                 # 主畫面上方「日常」按鈕的固定位置（認不到圖示時改點這裡；上方那排每個帳號位置都一樣）
REDEEM_MAX_DRAGS = 15            # 兌換序號：最多往下拉幾次（到底會自己停，這只是保險）
REDEEM_LIST_REGION = (0.32, 0.40, 0.60, 0.74)   # 設置面板裡會捲動的內容區（官方、雷電位置幾乎一樣）
REDEEM_SKIP_DRAGS = 0            # 兌換序號：（2026.11.03l 起一律拉到底才找，這個只是加大「最多拉幾次」的保險）
WAKE_CLICK = None                # 省電模式喚醒點：每個視窗開始前在主畫面先點一下（None = 不點）
PET_GIFT_MIN_X = 255             # 寵物打工畫面只認 x 大於此值的圖示（擋掉左邊羊皮紙）
PET_MODE = "grid"                # grid = 九宮格固定位置；detect = 找禮物圖示
PET_SLOTS = []                   # 九宮格的位置

ROW_SAFE_TOP = 0                 # （已不使用）
ROW_SAFE_BOTTOM = 405

ENABLE_BONUS = True              # 每日福利
RETRY_FAILED = True              # 全部跑完後，失敗的帳號補跑一次（只補失敗的那幾項）

ADAPTIVE_WAIT = True
SLOW = 1.0                       # 動作放慢倍率：所有「等畫面反應」的時間都乘上它（模擬器卡、網路差就調大）
                                 # 只影響等待，不影響拖曳本身的速度（拖曳速度是實測調出來的，不能動）
STABLE_REGION = (0.12, 0.16, 0.88, 0.95)   # 比對「畫面有沒有變」時只看中間；避開頂端的提示字
STABLE_TOL = 2.5
STABLE_SETTLE = 0.3
T_MIN = 0.3
T_CLICK_MAX = 2.2
T_PANEL_MAX = 4.0
T_AFTER_FOCUS = 0.8
T_AFTER_RESIZE = 2.5
FIND_TIMEOUT = 8.0

MAX_QUICK_CLICKS = 6
MAX_PET_GIFTS = 24
MAX_CLAIMS = 20

ABORT = False
STOP_KEY = "f12"                 # 全域停止鍵：跑到一半按它，程式立刻中斷並把視窗還原


class Aborted(Exception):
    """使用者按了停止鍵或停止按鈕。"""


_VK = {"f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
       "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
       "pause": 0x13, "scrolllock": 0x91, "insert": 0x2D, "delete": 0x2E,
       "home": 0x24, "end": 0x23}


def start_stop_hotkey(key=None):
    """開一條背景執行緒監聽停止鍵，按下就把 ABORT 設成 True。"""
    import threading
    key = (key or STOP_KEY).lower()
    vk = _VK.get(key)
    if not vk:
        print(f"停止鍵「{key}」不支援，可用：{', '.join(_VK)}")
        return None

    def loop():
        global ABORT
        while True:
            try:
                if win32api.GetAsyncKeyState(vk) & 0x8000 and not ABORT:
                    ABORT = True
                    print(f"\n收到停止鍵 {key.upper()}，正在停止…")
            except Exception:
                pass
            time.sleep(0.1)

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.03

# 會被環境切換影響的全部變數，切換時先回到基準值再套用環境值
_TUNABLES = ["WINDOW_TITLE", "WINDOW_EXCLUDE", "WINDOW_EXES", "HOTKEYS", "USE_ESC", "WORK_W", "WORK_H",
             "USE_RENDER_CHILD", "RENDER_CHILD_TITLE", "MATCH_THRESHOLD",
             "SAFE_CLICK", "SCROLL_POINT", "SCROLL_POINT_ALT", "LIST_TOP", "LIST_BOTTOM",
             "DAILY_KEY", "PET_KEY", "PET_TAB", "PET_SLOT", "WAKE_CLICK", "DAILY_BTN", "TICKET_KEY", "TICKET_SLOT", "EXCHANGE_SLOT", "RELIST_MAX", "RED_DOT_SKIP", "REMEMBER_DONE", "REDEEM_SKIP_DRAGS", "QUICK_NO_REMIND", "QUICK_CONFIRM_OK", "ABANDON_OK", "RAW_MOUSE", "LIST_CHECK_REGION", "LIST_MOVE_TOL", "PET_GIFT_MIN_X",
             "DUNGEON_KEY", "DUNGEON_BTN", "DUNGEON_LIST_X", "DUNGEON_LIST_TOP",
             "DUNGEON_LIST_BOTTOM", "DUNGEON_TAB_Y", "DUNGEON_FIRST_TAB", "STRIP_DRAG_END", "MAX_SWEEPS",
             "SETTINGS_BTN", "REDEEM_INPUT_DY", "WEEKLY_TAB", "CLAIM_WEEKLY",
             "PET_MODE", "PET_SLOTS", "ROW_SAFE_TOP", "ROW_SAFE_BOTTOM",
             "ENABLE_BONUS", "ADAPTIVE_WAIT", "RETRY_FAILED", "SLOW"]
_BASE = {k: globals()[k] for k in _TUNABLES}

# ---- 每個環境自己的預設值 ----
PROFILE_DEFAULTS = {
    "官方": {
        # 這些是在 PC 版實際校正過的值
        "WINDOW_TITLE": "ROM Classic", "HOTKEYS": True,
        "SAFE_CLICK": (559, 363), "SCROLL_POINT": (419, 313), "SCROLL_POINT_ALT": (299, 327),
        "PET_TAB": (754, 295),
        "PET_SLOTS": [(483, 139), (618, 139),
                      (348, 241), (485, 241), (620, 245),
                      (353, 346), (483, 354)],
    },
    "雷電": {
        # 模擬器沒有快捷鍵，一律點螢幕按鈕；座標全部要重新校正
        # ESC 在模擬器是返回鍵，主畫面按了會跳「退出遊戲」，所以不准按
        "WINDOW_TITLE": "雷電", "HOTKEYS": False, "USE_ESC": False,
        "WINDOW_EXCLUDE": ["多開", "LDMultiPlayer", "dnmultiplayer"],
        # 模擬器可以改名（例如改成「角色名 9.1.46」），標題不一定有「雷電」：看是不是 dnplayer.exe 開的
        "WINDOW_EXES": ["dnplayer.exe"],
        # 對準遊戲畫面子視窗，固定成 800x450（16:9，跟 1280x720 同比例，不會有黑邊）
        "USE_RENDER_CHILD": True, "WORK_W": 800, "WORK_H": 450,
        # 800x450 的日常清單大約佔 y=60~410，比 PC 版矮，範圍要跟著縮
        "ROW_SAFE_BOTTOM": 372, "LIST_TOP": 80, "LIST_BOTTOM": 400,
        "DUNGEON_LIST_TOP": 95, "DUNGEON_LIST_BOTTOM": 390, "DUNGEON_TAB_Y": 100,
        "DUNGEON_FIRST_TAB": (290, 100),
        # 雷電畫面比較窄，分頁列外框右緣大約在 0.94；拖到 0.95 會超出外框被當成取消（使用者手動確認框內放開拖得動）
        "STRIP_DRAG_END": 0.90,
        # 遊戲開了省電模式，閒置後畫面會卡住，要先點一下才有反應。
        # 使用者指定：寵物箱左邊一點點（寵物箱約 506,366，左緣約 484）
        "WAKE_CLICK": (471, 366),
        # 雷電只聽「真正的滑鼠移動訊號」：pyautogui.moveTo 是游標瞬移（SetCursorPos），
        # 雷電收不到中間的移動，拖曳全部變成「點一下」（使用者看到副本分頁列只被點、沒被拉）。
        "RAW_MOUSE": True,
        # 雷電的設置頁很長、每次捲得少：使用者要求先往下拉 8 次再開始找「兌換」
        "REDEEM_SKIP_DRAGS": 8,
        # 日常圖示的人物會眨眼、暗色地圖會被染色，常常認不到；上方那排位置固定，認不到就點這裡（實測截圖）
        "DAILY_BTN": (492, 45),
        # 快捷列第 1 格（交易所，黃色帳篷）：照截圖量的，校正頁可重抓
        "EXCHANGE_SLOT": (521, 404),
        # 雷電的輸入框在「兌換」上方約 33 像素（官方 41；41 也點得到但貼著上緣）
        "REDEEM_INPUT_DY": -33,
        "WEEKLY_TAB": (257, 45),
        # 雷電比較卡，網路延遲也大：等待一律拉長 1.5 倍（設定頁可以再調）
        "SLOW": 1.5,
    },
}

# 這些 key 放在共用設定檔，不跟環境走
SHARED_KEYS = {"active_profile", "party_key", "friend_key", "party_size",
               "party_leader_window", "party_interval_min", "party_alt_windows",
               "stop_key", "redeem_code",
               "instances_root", "instances_prefix", "instances_exe", "instances_exes"}


def _read_json(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print("=" * 60)
        print(f"設定檔格式有問題，先用預設值：{path}\n{e}")
        print("=" * 60)
        return {}


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _load_config():
    """把目前環境的 config.json 套用到全域變數。"""
    cfg = _read_json(CONFIG_PATH)
    g = globals()
    if "commission_offset" in cfg:
        CLICK_OFFSET["commission_row.png"] = tuple(cfg["commission_offset"])
    for k, v in cfg.get("offsets", {}).items():
        CLICK_OFFSET[k] = tuple(v)
    for key, name in (("safe_click", "SAFE_CLICK"), ("scroll_point", "SCROLL_POINT"),
                      ("scroll_point_alt", "SCROLL_POINT_ALT"), ("pet_tab", "PET_TAB"),
                      ("pet_slot", "PET_SLOT"), ("dungeon_btn", "DUNGEON_BTN"),
                      ("wake_click", "WAKE_CLICK"), ("daily_btn", "DAILY_BTN"),
                      ("exchange_slot", "EXCHANGE_SLOT"), ("ticket_slot", "TICKET_SLOT"),
                      ("quick_no_remind", "QUICK_NO_REMIND"), ("quick_confirm_ok", "QUICK_CONFIRM_OK"),
                      ("abandon_ok", "ABANDON_OK"),
                      ("dungeon_first_tab", "DUNGEON_FIRST_TAB"),
                      ("settings_btn", "SETTINGS_BTN"), ("weekly_tab", "WEEKLY_TAB")):
        if cfg.get(key):
            g[name] = tuple(cfg[key])
    for key, name, cast in (("pet_gift_min_x", "PET_GIFT_MIN_X", int),
                            ("adaptive_wait", "ADAPTIVE_WAIT", bool),
                            ("row_safe_top", "ROW_SAFE_TOP", int),
                            ("row_safe_bottom", "ROW_SAFE_BOTTOM", int),
                            ("list_top", "LIST_TOP", int), ("list_bottom", "LIST_BOTTOM", int),
                            ("enable_bonus", "ENABLE_BONUS", bool), ("hotkeys", "HOTKEYS", bool),
                            ("use_esc", "USE_ESC", bool),
                            ("use_render_child", "USE_RENDER_CHILD", bool),
                            ("render_child_title", "RENDER_CHILD_TITLE", str),
                            ("retry_failed", "RETRY_FAILED", bool),
                            ("pet_key", "PET_KEY", str), ("daily_key", "DAILY_KEY", str),
                            ("window_title", "WINDOW_TITLE", str),
                            ("work_w", "WORK_W", int), ("work_h", "WORK_H", int),
                            ("match_threshold", "MATCH_THRESHOLD", float),
                            ("pet_mode", "PET_MODE", str),
                            ("dungeon_key", "DUNGEON_KEY", str),
                            ("dungeon_list_x", "DUNGEON_LIST_X", int),
                            ("dungeon_list_top", "DUNGEON_LIST_TOP", int),
                            ("dungeon_list_bottom", "DUNGEON_LIST_BOTTOM", int),
                            ("dungeon_tab_y", "DUNGEON_TAB_Y", int),
                            ("max_sweeps", "MAX_SWEEPS", int),
                            ("redeem_input_dy", "REDEEM_INPUT_DY", int),
                            ("claim_weekly", "CLAIM_WEEKLY", bool),
                            ("slow", "SLOW", float),
                            ("relist_max", "RELIST_MAX", int),
                            ("red_dot_skip", "RED_DOT_SKIP", bool),
                            ("remember_done", "REMEMBER_DONE", bool)):
        if key in cfg:
            g[name] = cast(cfg[key])
    if "pet_slots" in cfg:
        g["PET_SLOTS"] = [tuple(p) for p in cfg["pet_slots"] if p]
    if "window_exclude" in cfg:
        g["WINDOW_EXCLUDE"] = [str(x) for x in cfg["window_exclude"]]


def set_profile(name):
    """切換環境：重設路徑、回到基準值、套環境預設值、再讀該環境的 config。"""
    global ACTIVE_PROFILE, TEMPLATE_DIR, SHOT_DIR, CONFIG_PATH
    if name not in PROFILE_NAMES:
        name = PROFILE_NAMES[0]
    ACTIVE_PROFILE = name
    pdir = os.path.join(PROFILES_DIR, name)
    TEMPLATE_DIR = os.path.join(pdir, "templates")
    SHOT_DIR = os.path.join(pdir, "shots")
    CONFIG_PATH = os.path.join(pdir, "config.json")
    os.makedirs(TEMPLATE_DIR, exist_ok=True)

    globals().update(_BASE)
    globals().update(PROFILE_DEFAULTS.get(name, {}))
    CLICK_OFFSET.clear()
    _tmpl_cache.clear()
    _mask_cache.clear()
    _load_config()

    g = globals()
    g["PRIMARY_DRAG_OK"] = False
    g["_size_noted"] = False
    g["AREA_X"], g["AREA_Y"], g["AREA_W"], g["AREA_H"] = WORK_X, WORK_Y, WORK_W, WORK_H


def _migrate_old_layout():
    """第一次升級：把舊的 templates/、config.json 搬進 profiles/官方/。"""
    old_tmpl = os.path.join(BASE_DIR, "templates")
    new_dir = os.path.join(PROFILES_DIR, "官方")
    if os.path.exists(new_dir) or not os.path.exists(old_tmpl):
        return
    import shutil
    os.makedirs(new_dir, exist_ok=True)
    shutil.move(old_tmpl, os.path.join(new_dir, "templates"))
    old_shots = os.path.join(BASE_DIR, "shots")
    if os.path.exists(old_shots):
        shutil.move(old_shots, os.path.join(new_dir, "shots"))
    old = _read_json(SHARED_CONFIG_PATH)
    shared = {k: v for k, v in old.items() if k in SHARED_KEYS}
    profile = {k: v for k, v in old.items() if k not in SHARED_KEYS}
    shared["active_profile"] = "官方"
    _write_json(SHARED_CONFIG_PATH, shared)
    _write_json(os.path.join(new_dir, "config.json"), profile)
    print("已把舊的模板與設定搬進 profiles/官方/")


_tmpl_cache = {}
_mask_cache = {}
_migrate_old_layout()
STOP_KEY = str(_read_json(SHARED_CONFIG_PATH).get("stop_key", STOP_KEY))
REDEEM_CODE = str(_read_json(SHARED_CONFIG_PATH).get("redeem_code", ""))
set_profile(_read_json(SHARED_CONFIG_PATH).get("active_profile", "官方"))

# 執行模式：「自動」= 官方和雷電的視窗一起找，每個視窗用自己那一套設定（混跑）；
# 「官方」「雷電」= 跟以前一樣只找那一種。ACTIVE_PROFILE 則是「目前載入哪一套設定」
# （校正、設定頁編輯的就是它；自動模式跑的時候會隨視窗切換，跑完切回來）。
AUTO_MODE = "自動"
RUN_MODES = [AUTO_MODE] + list(PROFILE_NAMES)
RUN_MODE = str(_read_json(SHARED_CONFIG_PATH).get("run_mode", AUTO_MODE))
if RUN_MODE not in RUN_MODES:
    RUN_MODE = AUTO_MODE
if RUN_MODE != AUTO_MODE and ACTIVE_PROFILE != RUN_MODE:
    set_profile(RUN_MODE)                          # 只跑某一種：載入的就是那一套


# ---------------------------------------------------------------------------
# 視窗處理
# ---------------------------------------------------------------------------

def enable_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _profile_value(kind, cfg_key, glob_key):
    """不切換環境，直接讀某一套的設定值（config 有寫用 config，沒寫用那一套的預設）。"""
    cfg = _read_json(os.path.join(PROFILES_DIR, kind, "config.json"))
    if cfg_key in cfg:
        return cfg[cfg_key]
    d = dict(_BASE)
    d.update(PROFILE_DEFAULTS.get(kind, {}))
    return d.get(glob_key)


_kind_cache = {}


def window_kind(hwnd):
    """這個視窗是官方還是雷電。看的是 Windows 給的視窗身分（程式名稱、標題），不看遊戲畫面，不會判斷錯。"""
    if hwnd in _kind_cache:
        return _kind_cache[hwnd]
    try:
        title = win32gui.GetWindowText(hwnd)
    except Exception:
        title = ""
    exe = os.path.basename(window_exe(hwnd) or "").lower()
    kind = "雷電" if ("dnplayer" in exe or "ldplayer" in exe or "雷電" in title) else "官方"
    _kind_cache[hwnd] = kind
    return kind


def window_label(hwnd):
    """給人看的名字：官方用遊戲資料夾名（ROM Classic3），雷電用模擬器名（雷電模擬器-2）。都固定不變。"""
    try:
        title = win32gui.GetWindowText(hwnd)
    except Exception:
        title = ""
    if window_kind(hwnd) == "雷電":
        # 去掉結尾的版本號（「角色名 9.1.46」→「角色名」），雷電更新版本後名字才對得上（組隊記的是名字）
        return re.sub(r"\s+\d+(\.\d+)+\s*$", "", title) or title or "雷電"
    exe = window_exe(hwnd)
    info = instance_folder(exe) if exe else None
    return os.path.basename(info[0]) if info else (title or "官方")


def use_profile(kind):
    """切到這個視窗種類的那一套設定（已經是就不動）。"""
    if kind and kind != ACTIVE_PROFILE:
        set_profile(kind)


def find_windows(title=None, exclude=None, exes=None):
    """找出所有標題含有 WINDOW_TITLE 的可見視窗，排除本程式自己的視窗，依螢幕位置排序。

    自動模式（沒指定 title）：官方和雷電一起找，官方排前面、雷電排後面，各自照螢幕位置。
    """
    import win32process
    if title is None and RUN_MODE == AUTO_MODE:
        found, seen = [], set()
        for kind in PROFILE_NAMES:
            t = _profile_value(kind, "window_title", "WINDOW_TITLE")
            ex = _profile_value(kind, "window_exclude", "WINDOW_EXCLUDE") or []
            xs = _profile_value(kind, "window_exes", "WINDOW_EXES") or []
            if not t and not xs:
                continue
            for h in find_windows(t or "\x00", ex, xs):
                if h not in seen:
                    seen.add(h)
                    found.append(h)
        order = {k: i for i, k in enumerate(PROFILE_NAMES)}
        found.sort(key=lambda h: (order.get(window_kind(h), 9),
                                  win32gui.GetWindowRect(h)[0], win32gui.GetWindowRect(h)[1]))
        return found
    title = (title or WINDOW_TITLE).lower()
    exclude = WINDOW_EXCLUDE if exclude is None else exclude
    exes = [x.lower() for x in (WINDOW_EXES if exes is None else exes)]
    me = os.getpid()
    hwnds = []

    def by_program(hwnd):
        """標題對不上時，看是不是指定的程式開的（例如改了名的雷電）。

        不看大小（朋友把 5 個雷電縮到 325×220 排在螢幕下面，2026.11.03e 用 400×250 擋掉了），
        改看裡面有沒有雷電畫遊戲用的子視窗（標題 TheRender 或類別名含 Render）：
        只有真正的遊戲視窗有，模擬器自己跳的通知、設定小視窗都沒有。縮到工作列的也認得到。
        """
        if not exes:
            return False
        try:
            if os.path.basename(window_exe(hwnd) or "").lower() not in exes:
                return False
            return has_game_child(hwnd)
        except Exception:
            return False

    def cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        text = win32gui.GetWindowText(hwnd)
        if title not in text.lower() and not by_program(hwnd):
            return
        if any(x.lower() in text.lower() for x in exclude):
            return                                 # 多開器之類的，不是遊戲
        try:                                       # 跳過自己（GUI 標題也含 ROM Classic）
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid == me:
                return
        except Exception:
            pass
        if win32gui.GetParent(hwnd):               # 只要最上層視窗
            return
        hwnds.append(hwnd)

    win32gui.EnumWindows(cb, None)
    hwnds.sort(key=lambda h: (win32gui.GetWindowRect(h)[0],
                              win32gui.GetWindowRect(h)[1]))
    return hwnds


_K32 = None
_DWM = None


def _kernel32():
    """kernel32，先講清楚每個函式的參數和回傳型別。

    64 位元電腦上「程式代號」（handle）是 64 位元；沒講清楚的話 ctypes 預設當成 32 位元，會被截斷，
    下一個呼叫拿到錯的值就可能讓整個程式當掉（pythonw.exe「記憶體不能為 read」）。
    開雷電 6 開時視窗一下多一下少、每次找視窗都會對每個視窗問一次，機率就變高。
    用自己的 WinDLL，不改到別的套件共用的 ctypes.windll.kernel32。
    """
    global _K32
    if _K32 is None:
        import ctypes
        from ctypes import wintypes as wt
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
        k.OpenProcess.restype = wt.HANDLE
        k.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
        k.QueryFullProcessImageNameW.restype = wt.BOOL
        k.TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]
        k.TerminateProcess.restype = wt.BOOL
        k.CloseHandle.argtypes = [wt.HANDLE]
        k.CloseHandle.restype = wt.BOOL
        _K32 = k
    return _K32


def window_exe(hwnd):
    """這個視窗是哪個 exe 開的。用 Windows API 問，不需要額外套件。"""
    import ctypes
    from ctypes import wintypes as wt
    import win32process
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if not pid:
            return None
        k32 = _kernel32()
        h = k32.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return None
        try:
            buf = ctypes.create_unicode_buffer(2048)
            size = wt.DWORD(2048)
            ok = k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
            return buf.value if ok else None
        finally:
            k32.CloseHandle(h)
    except Exception:
        return None


def instance_folder(exe_path):
    """從 exe 路徑找出「這是第幾份遊戲」的那層資料夾。

    多開通常是把整個遊戲資料夾複製成 ROM Classic1、ROM Classic2……
    所以往上找一層「名字是文字+數字、而且旁邊有很多兄弟資料夾同樣命名」的目錄。
    回傳 (那層資料夾路徑, 共同的上層, 命名前綴)；找不到就回傳 None。
    """
    import re
    d = os.path.dirname(exe_path or "")
    for _ in range(5):
        if not d or os.path.dirname(d) == d:
            break
        name = os.path.basename(d)
        m = re.fullmatch(r"(.*?)(\d+)", name)
        if m and m.group(1).strip():
            parent = os.path.dirname(d)
            prefix = m.group(1)
            try:
                sibs = [x for x in os.listdir(parent)
                        if re.fullmatch(re.escape(prefix) + r"\d+", x)
                        and os.path.isdir(os.path.join(parent, x))]
            except OSError:
                sibs = []
            if len(sibs) >= 2:
                return d, parent, prefix
        d = os.path.dirname(d)
    return None


def find_exe_in(folder, rel, max_depth=3):
    """在某一份資料夾裡找執行檔。先試同樣的相對路徑，沒有就往下搜同名的 exe。

    多開的資料夾常常是不同時間複製的，有的多包一層、有的少一層，
    所以不能只認一種路徑。
    """
    exact = os.path.join(folder, rel)
    if os.path.exists(exact):
        return exact
    target = os.path.basename(rel).lower()
    base_depth = folder.rstrip(os.sep).count(os.sep)
    for root_dir, dirs, files in os.walk(folder):
        if root_dir.count(os.sep) - base_depth >= max_depth:
            dirs[:] = []
        for f in files:
            if f.lower() == target:
                return os.path.join(root_dir, f)
    return None


def list_instances():
    """列出目前開著的遊戲視窗對應哪一份安裝，以及還有哪幾份沒開。

    從開著的視窗推出「遊戲資料夾在哪、要執行哪個 exe」，並記到共用設定裡；
    這樣就算一個視窗都沒開，也能靠上次記下來的位置去補開。

    回傳 dict：
      windows  [(視窗編號, hwnd, 資料夾名 或 exe 路徑)]
      missing  [沒開的資料夾完整路徑]（照數字排序）
      launch   {資料夾完整路徑: 該份要執行的 exe}
    """
    import re
    hwnds = find_windows()
    windows, root, prefix, rel = [], None, None, None
    open_folders = set()
    for i, h in enumerate(hwnds, 1):
        exe = window_exe(h)
        # 雷電的安裝資料夾（LDPlayer4、LDPlayer9…）也可能長得像「文字+數字」，不能當成官方的多開資料夾
        info = instance_folder(exe) if exe and window_kind(h) != "雷電" else None
        if info:
            folder, root, prefix = info
            open_folders.add(os.path.normcase(folder))
            if rel is None:
                rel = os.path.relpath(exe, folder)
            windows.append((i, h, os.path.basename(folder)))
        elif window_kind(h) == "雷電":
            windows.append((i, h, win32gui.GetWindowText(h) or "雷電"))
        else:
            windows.append((i, h, exe or "（不明）"))

    shared = _read_json(SHARED_CONFIG_PATH)
    if root and prefix and rel:
        if (shared.get("instances_root"), shared.get("instances_prefix"),
                shared.get("instances_exe")) != (root, prefix, rel):
            shared.update({"instances_root": root, "instances_prefix": prefix,
                           "instances_exe": rel})
            _write_json(SHARED_CONFIG_PATH, shared)      # 記住，下次沒視窗也能用
    else:
        root = shared.get("instances_root")
        prefix = shared.get("instances_prefix")
        rel = shared.get("instances_exe")

    missing, launch, noexe, everyone = [], {}, [], []
    win_of = {}                                    # 資料夾 → 視窗編號
    for i, h, name in windows:
        win_of[str(name)] = i
    if root and prefix and rel and os.path.isdir(root):
        def num(x):
            m = re.search(r"(\d+)$", x)
            return int(m.group(1)) if m else 0
        for name in sorted(os.listdir(root), key=num):
            full = os.path.join(root, name)
            if not (re.fullmatch(re.escape(prefix) + r"\d+", name) and os.path.isdir(full)):
                continue
            is_open = os.path.normcase(full) in open_folders
            cache = shared.setdefault("instances_exes", {})
            exe = cache.get(name)
            if not exe or not os.path.exists(exe):
                exe = find_exe_in(full, rel)       # 整份搜一次很慢，找到就記住
                if exe:
                    cache[name] = exe
                    _write_json(SHARED_CONFIG_PATH, shared)
            everyone.append({"name": name, "path": full, "exe": exe,
                             "open": is_open, "window": win_of.get(name)})
            if is_open:
                continue
            if exe:
                missing.append(full)
                launch[full] = exe
            else:
                noexe.append(full)                 # 資料夾在，但整份裡都找不到那個 exe
    return {"windows": windows, "missing": missing, "launch": launch, "noexe": noexe,
            "all": everyone, "exe_rel": rel, "known": bool(root and prefix and rel)}


def launch_missing(gap=6.0, wait=90.0, log=print, only=None):
    """把沒開的那幾份一個一個開起來，然後等視窗出現，回報哪幾份沒出來。

    only：只開這些資料夾（完整路徑清單）；None = 全部沒開的。
    """
    import subprocess
    info = list_instances()
    for full in info.get("noexe", []):
        log(f"跳過 {os.path.basename(full)}：裡面找不到 {info['exe_rel']}（結構跟其他份不一樣？）")
    if only is not None:
        chosen = set(os.path.normcase(x) for x in only)
        info["missing"] = [f for f in info["missing"] if os.path.normcase(f) in chosen]
    if not info["missing"]:
        if not info["known"]:
            log("還不知道遊戲裝在哪：先手動開一個視窗，按一次「檢查開了哪些」讓程式記下來。")
        else:
            log("沒有需要補開的。")
        return 0

    before = len(find_windows())
    started = []
    for full in info["missing"]:
        exe = info["launch"][full]
        log(f"開啟 {os.path.basename(full)} … ({exe})")
        try:
            subprocess.Popen([exe], cwd=os.path.dirname(exe))
            started.append(full)
        except Exception as e:
            log(f"  開啟失敗：{e}")
            continue
        time.sleep(gap)

    # 等視窗真的出現
    log(f"已送出 {len(started)} 個開啟指令，等視窗出現（最多 {wait:.0f} 秒）…")
    deadline = time.time() + wait
    while time.time() < deadline:
        if len(find_windows()) >= before + len(started):
            break
        time.sleep(3)
    after = list_instances()
    still = [os.path.basename(f) for f in after["missing"] if f in started]
    log(f"現在開著 {len(after['windows'])} 個視窗。")
    if still:
        log("這幾份有下指令但視窗沒出現（可能閃退、登入中、或被擋）：" + "、".join(still))
    return len(started)


def work_area():
    """主螢幕扣掉工作列之後的可用範圍 (左, 上, 右, 下)。"""
    import ctypes
    try:
        import ctypes.wintypes as wt
        rect = wt.RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)
        return rect.left, rect.top, rect.right, rect.bottom
    except Exception:
        return 0, 0, win32api.GetSystemMetrics(0), win32api.GetSystemMetrics(1)


def invisible_border(hwnd):
    """Windows 10/11 每個視窗外圍有一圈看不到的邊框（左右下約 7~8 像素，拿來拖曳改大小）。
    回傳 (左, 上, 右, 下) 各多少；排列時要扣掉，不然視窗之間會看起來有空隙。"""
    try:
        import ctypes
        import ctypes.wintypes as wt
        global _DWM
        if _DWM is None:
            d = ctypes.WinDLL("dwmapi")
            d.DwmGetWindowAttribute.argtypes = [wt.HWND, wt.DWORD, ctypes.POINTER(wt.RECT), wt.DWORD]
            d.DwmGetWindowAttribute.restype = ctypes.c_long        # HRESULT
            _DWM = d
        if not win32gui.IsWindow(hwnd):
            return 0, 0, 0, 0
        vis = wt.RECT()
        if _DWM.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(vis), ctypes.sizeof(vis)) != 0:   # DWMWA_EXTENDED_FRAME_BOUNDS
            return 0, 0, 0, 0
        l, t, r, b = win32gui.GetWindowRect(hwnd)
        return (max(0, vis.left - l), max(0, vis.top - t), max(0, r - vis.right), max(0, b - vis.bottom))
    except Exception:
        return 0, 0, 0, 0


def game_frame(hwnd):
    """視窗「看得到的外框」比遊戲畫面多出來的寬、高（標題列、邊框、雷電右邊的工具列），以及遊戲畫面的長寬比。"""
    l, t, r, b = win32gui.GetWindowRect(hwnd)
    il, it, ir, ib = invisible_border(hwnd)
    ow, oh = (r - l) - il - ir, (b - t) - it - ib
    if window_kind(hwnd) == "雷電":
        ratio = 16 / 9
        child = find_render_child(hwnd)
        if child:
            cl, ct, cr, cb = win32gui.GetWindowRect(child)
            return max(0, ow - (cr - cl)), max(0, oh - (cb - ct)), ratio
        return 0, 0, ratio
    ratio = 1.6
    try:
        _, _, cw, ch = win32gui.GetClientRect(hwnd)
        return max(0, ow - cw), max(0, oh - ch), ratio
    except Exception:
        return 0, 0, ratio


def arrange_windows(cols=0, log=print):
    """把所有遊戲視窗排成格子，照安裝資料夾的編號（ROM Classic1、2、3…）依序填。

    排完之後「視窗編號 = 資料夾編號」，以後標示視窗、選視窗都不會亂。
    cols = 0 表示自動挑「每個視窗最大」的欄數。
    每個視窗都保持遊戲畫面原本的比例（官方 16:10、雷電 16:9），不會被拉成細長形；
    全部一樣大、一個挨一個排：以「看得到的邊」對齊，看不到的邊框互相疊在一起，所以中間沒有空隙。
    （以前是把每格塞滿，6 欄時會變得又細又長）
    """
    import math, re
    info = list_instances()
    wins = info["windows"]
    if not wins:
        log("沒有遊戲視窗可以排。")
        return 0

    def order(item):
        _, _, name = item
        m = re.search(r"(\d+)$", str(name))
        return (0, int(m.group(1))) if m else (1, str(name))
    wins = sorted(wins, key=order)
    frames = {}
    for _, hwnd, _ in wins:
        try:
            frames[hwnd] = game_frame(hwnd)
        except Exception:
            frames[hwnd] = (16, 39, 1.6)

    n = len(wins)
    left, top, right, bottom = work_area()
    sw, sh = right - left, bottom - top

    def game_width(c):
        """排成 c 欄時，每個視窗的遊戲畫面最寬可以多寬（全部視窗一樣寬，取最緊的那個）。"""
        r = math.ceil(n / c)
        cell_w, cell_h = sw / c, sh / r
        return min(min(cell_w - ew, (cell_h - eh) * ratio) for ew, eh, ratio in frames.values())

    if not cols:
        cols = max(range(1, n + 1), key=game_width)    # 挑讓視窗最大的欄數
    cols = max(1, min(int(cols), n))
    rows = math.ceil(n / cols)
    gw = int(game_width(cols))
    if gw < 160:
        log(f"⚠ 排成 {cols} 欄的話每個視窗太小（遊戲畫面只有 {gw} 寬），改用自動欄數")
        cols = max(range(1, n + 1), key=game_width)
        rows = math.ceil(n / cols)
        gw = int(game_width(cols))
    log(f"螢幕可用 {sw}x{sh}，{n} 個視窗排成 {cols} 欄 x {rows} 列，遊戲畫面每個 {gw} 寬（保持原本比例）")

    y = top
    for r in range(rows):
        row = wins[r * cols:(r + 1) * cols]
        x, row_h = left, 0
        for k, (_, hwnd, name) in enumerate(row):
            i = r * cols + k
            ew, eh, ratio = frames[hwnd]
            w, h = gw + ew, int(round(gw / ratio)) + eh          # 看得到的大小
            row_h = max(row_h, h)
            try:
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                il, it, ir, ib = invisible_border(hwnd)
                # 實際設定時把看不到的邊框加回去，讓「看得到的邊」剛好落在 (x, y)
                win32gui.SetWindowPos(hwnd, 0, x - il, y - it, w + il + ir, h + it + ib,
                                      0x0004 | 0x0040)   # NOZORDER | SHOWWINDOW
                time.sleep(0.2)
                nx, ny, nw, nh = get_rect(hwnd)
                ok = abs(nx + il - x) < 20 and abs(ny + it - y) < 20
                log(f"  {i + 1:2d}. {name} → ({x}, {y}) {w}x{h}"
                    + ("" if ok else f"　⚠ 實際在 ({nx}, {ny}) {nw}x{nh}，視窗不接受這個位置/大小"))
            except Exception as e:
                log(f"  {name} 排不動：{e}")
            x += w                                 # 下一個緊接在右邊
        y += row_h                                 # 下一列接在這列下面
    return n


def window_titles_hint(limit=8):
    """找不到遊戲視窗時用：列出目前所有頂層視窗裡，標題看起來像遊戲或模擬器的。"""
    found = []

    def cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd) or win32gui.GetParent(hwnd):
            return
        t = win32gui.GetWindowText(hwnd)
        if t and any(k in t.lower() for k in ("rom", "ragnarok", "雷電", "ld", "仙境")):
            found.append(t)

    try:
        win32gui.EnumWindows(cb, None)
    except Exception:
        pass
    return sorted(set(found))[:limit]


def kill_window(hwnd):
    """強制結束這個視窗所屬的程式（等同工作管理員的「結束工作」）。回傳成功與否。"""
    import win32process
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if not pid:
            return False
        k32 = _kernel32()
        h = k32.OpenProcess(0x0001, False, pid)          # PROCESS_TERMINATE
        if not h:
            return False
        try:
            return bool(k32.TerminateProcess(h, 1))
        finally:
            k32.CloseHandle(h)
    except Exception:
        return False


def get_rect(hwnd):
    l, t, r, b = win32gui.GetWindowRect(hwnd)
    return l, t, r - l, b - t


def step(msg):
    """紀錄裡的一個步驟。任務標題縮兩格「【副本掃蕩】」，步驟縮四格「・…」，結果「→ …」。"""
    print("    ・" + msg, flush=True)


def nap(sec):
    """固定等待，會乘上放慢倍率。"""
    time.sleep(sec * max(0.5, SLOW))


def too_close(a, b, dist=25):
    """兩個位置是不是幾乎同一點。用來抓「選單裡的按鈕被誤抓成『更多』本身」。"""
    if not a or not b:
        return False
    return abs(a[0] - b[0]) <= dist and abs(a[1] - b[1]) <= dist


def focus(hwnd):
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
        win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
    nap(T_AFTER_FOCUS)


def move_window(hwnd, x, y, w, h):
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    win32gui.SetWindowPos(hwnd, win32con.HWND_TOP, x, y, w, h,
                          win32con.SWP_SHOWWINDOW)
    nap(0.4)


_size_noted = False


def has_game_child(hwnd):
    """雷電的外層視窗裡有沒有「畫遊戲畫面」的子視窗（不拿面積最大的來湊）。"""
    hit = []

    def cb(child, _):
        try:
            if (win32gui.GetWindowText(child) == RENDER_CHILD_TITLE
                    or "render" in win32gui.GetClassName(child).lower()):
                hit.append(child)
        except Exception:
            pass

    try:
        win32gui.EnumChildWindows(hwnd, cb, None)
    except Exception:
        return False
    return bool(hit)


def find_render_child(hwnd):
    """在雷電的外層視窗裡找出「畫遊戲畫面」的子視窗。

    先找標題是 RENDER_CHILD_TITLE 的，找不到就拿類別名含 Render 的，
    再找不到就拿面積最大的子視窗。
    """
    found = []

    def cb(child, _):
        try:
            l, t, r, b = win32gui.GetWindowRect(child)
            found.append((child, win32gui.GetWindowText(child),
                          win32gui.GetClassName(child), (r - l) * (b - t)))
        except Exception:
            pass

    try:
        win32gui.EnumChildWindows(hwnd, cb, None)
    except Exception:
        return None
    if not found:
        return None
    for h, title, cls, _ in found:
        if title == RENDER_CHILD_TITLE:
            return h
    for h, title, cls, _ in found:
        if "render" in cls.lower():
            return h
    return max(found, key=lambda f: f[3])[0]


def normalize_window(hwnd):
    """把視窗搬到工作位置、拉到前面，並決定這次的工作區 AREA_*。

    官方：工作區 = 外層視窗（模擬器不會自己改尺寸，設多少就多少）。
    雷電：工作區 = 遊戲畫面子視窗。先量出外層比子視窗多出多少（分頁列、工具列），
          再把外層設成「目標 + 多出的部分」，子視窗就會剛好是目標尺寸。
          這樣不管哪台電腦、什麼縮放比例，遊戲畫面都是同樣大小，模板才能共用。
    """
    global AREA_X, AREA_Y, AREA_W, AREA_H, _size_noted
    move_window(hwnd, WORK_X, WORK_Y, WORK_W, WORK_H)
    focus(hwnd)

    if USE_RENDER_CHILD:
        child = find_render_child(hwnd)
        if child:
            for _ in range(2):                     # 量一次、修正一次、再量一次
                ox, oy, ow, oh = get_rect(hwnd)
                cx, cy, cw, ch = get_rect(child)
                dw, dh = ow - cw, oh - ch
                if (cw, ch) == (WORK_W, WORK_H):
                    break
                move_window(hwnd, WORK_X, WORK_Y, WORK_W + dw, WORK_H + dh)
            cx, cy, cw, ch = get_rect(child)
            AREA_X, AREA_Y, AREA_W, AREA_H = cx, cy, cw, ch
            if (cw, ch) != (WORK_W, WORK_H) and not _size_noted:
                print(f"注意：遊戲畫面實際是 {cw}x{ch}（目標 {WORK_W}x{WORK_H}），以實際為準。")
                _size_noted = True
            nap(T_AFTER_RESIZE)
            return
        if not _size_noted:
            print("注意：找不到遊戲畫面子視窗，改用整個視窗當工作區")
            _size_noted = True

    x, y, w, h = get_rect(hwnd)
    if (w, h) != (WORK_W, WORK_H) and w > 200 and h > 200:
        if not _size_noted:
            print(f"注意：視窗實際尺寸是 {w}x{h}（設定是 {WORK_W}x{WORK_H}），以實際尺寸為準。")
            _size_noted = True
    if (x, y) != (WORK_X, WORK_Y):
        move_window(hwnd, WORK_X, WORK_Y, w, h)
        x, y, w, h = get_rect(hwnd)
    AREA_X, AREA_Y, AREA_W, AREA_H = x, y, w, h
    nap(T_AFTER_RESIZE)


def grab(x=None, y=None, w=None, h=None):
    if ABORT:
        raise Aborted()
    x = AREA_X if x is None else x
    y = AREA_Y if y is None else y
    w = AREA_W if w is None else w
    h = AREA_H if h is None else h
    last = None
    for _ in range(3):                         # 偶爾會 screen grab failed，重試幾次
        try:
            img = ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True)
            return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        except Exception as e:
            last = e
            time.sleep(0.4)
    raise last


def imread(path):
    """讀圖。cv2.imread 不吃中文路徑（例如 profiles\\官方\\），所以先用 numpy 讀進來再解碼。"""
    try:
        data = np.fromfile(path, dtype=np.uint8)
    except (OSError, IOError):
        return None
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def imwrite(path, img):
    """存圖。同樣避開 cv2.imwrite 的中文路徑問題。回傳有沒有成功。"""
    ext = os.path.splitext(path)[1] or ".png"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        return False
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    buf.tofile(path)
    return os.path.exists(path)


# ---------------------------------------------------------------------------
# 等待與比對
# ---------------------------------------------------------------------------

def _core(img):
    h, w = img.shape[:2]
    x1, y1, x2, y2 = STABLE_REGION
    return img[int(h * y1):int(h * y2), int(w * x1):int(w * x2)]


def changed(a, b, factor=1.0):
    """兩張畫面差很多嗎。factor 越大越嚴格（用在要排除小面積閃動的場合）。"""
    if a is None or b is None:
        return False
    return float(np.mean(cv2.absdiff(_core(a), _core(b)))) >= STABLE_TOL * factor


MANUAL = "manual"                # 任務回傳這個 = 不是程式失敗，是要使用者自己處理的狀況
                                 # （總結標黃色 ⚠、不算失敗、不補跑）。例：這週 Lv.20 還沒手動打，掃蕩是灰的

LIST_SCROLLED = False            # 這次打開日常面板後，清單有沒有成功捲動過（open_daily 歸零）


LIST_SETTLE_TOL = 2.0            # 清單「停下來了」：連續兩次截圖、清單那塊差異都低於這個
                                 # 實測：只動 1 像素就 7.7；完全沒動只有雜訊 0.7


def list_diff(a, b, region=None):
    """清單那塊兩張畫面差多少（預設看日常清單左邊的圖示和標題）。不能比就回傳 None。"""
    r = region or LIST_CHECK_REGION
    if r is None or a is None or b is None:
        return None
    x0, y0, x1, y1 = int(AREA_W * r[0]), int(AREA_H * r[1]), int(AREA_W * r[2]), int(AREA_H * r[3])
    ra, rb = a[y0:y1, x0:x1], b[y0:y1, x0:x1]
    if ra.size == 0 or ra.shape != rb.shape:
        return None
    diff = cv2.absdiff(cv2.cvtColor(ra, cv2.COLOR_BGR2GRAY), cv2.cvtColor(rb, cv2.COLOR_BGR2GRAY))
    return float(np.mean(diff))


def list_changed(a, b):
    """清單有沒有真的捲動：只看清單左邊（圖示和標題），右邊閃光的按鈕、提示框都不算。"""
    if LIST_CHECK_REGION is None:
        return changed(a, b)
    if a is None or b is None:
        return False
    d = list_diff(a, b)
    return changed(a, b) if d is None else d >= LIST_MOVE_TOL


def list_settle(timeout=2.5, region=None):
    """等清單真的停下來，回傳停下來的畫面。

    遊戲清單放開後會慣性滑一段、碰到頂或底還會彈一下，最後那段爬得很慢；
    看整個畫面的「等靜止」被一直閃的按鈕干擾，常在清單還在爬的時候就截圖，
    結果下一次比對時把「上次沒爬完的」當成「這次有動」（到頂、到底了還說有動）。
    這裡只看清單那塊，每 0.15 秒看一次，連續兩次幾乎沒變才算停。
    """
    if (region or LIST_CHECK_REGION) is None:
        return grab()
    prev = grab()
    quiet = 0
    end = time.time() + timeout * max(0.5, SLOW)
    while time.time() < end and quiet < 2:
        time.sleep(0.15)
        cur = grab()
        d = list_diff(prev, cur, region)
        quiet = quiet + 1 if (d is not None and d < LIST_SETTLE_TOL) else 0
        prev = cur
    return prev


def region_changed(a, b, x0, y0, x1, y1, tol=1.0):
    """只比某個矩形範圍有沒有變。給分頁列這種「面積小、對比低」的東西用。"""
    if a is None or b is None:
        return False
    ra, rb = a[y0:y1, x0:x1], b[y0:y1, x0:x1]
    if ra.size == 0 or rb.size == 0 or ra.shape != rb.shape:
        return False
    return float(np.mean(cv2.absdiff(ra, rb))) >= tol


def strip_changed(a, b):
    """等級分頁列那一條有沒有「真的移動」。

    實測：真的捲動時差異 7 以上；滑鼠停在六角形上的亮光、拉過頭彈回來，差異只有 1~2。
    門檻設 3，只認真的移動。
    """
    y = DUNGEON_TAB_Y
    return region_changed(a, b, int(AREA_W * 0.30), max(0, y - 40),
                          int(AREA_W * 0.95), min(AREA_H, y + 45), tol=3.0)


def wait_stable(timeout=T_CLICK_MAX, settle=STABLE_SETTLE):
    """等畫面不再變動，回傳最後一張畫面。

    放慢倍率會拉長三樣：點完先等多久才開始看、要安靜多久才算停、最多等多久。
    卡的時候「點下去 → 畫面要過一下才開始動」，不先多等一下會以為已經停了。
    """
    k = max(0.5, SLOW)
    timeout, settle = timeout * k, settle * k
    if not ADAPTIVE_WAIT:
        time.sleep(timeout)
        return grab()
    time.sleep(T_MIN * k)
    prev = grab()
    t0 = time.time()
    quiet_since = None
    while time.time() - t0 < timeout:
        time.sleep(0.1)
        cur = grab()
        moving = changed(cur, prev)
        prev = cur
        if not moving:
            if quiet_since is None:
                quiet_since = time.time()
            elif time.time() - quiet_since >= settle:
                return cur
        else:
            quiet_since = None
    return prev



def load_template(name):
    if name not in _tmpl_cache:
        img = imread(os.path.join(TEMPLATE_DIR, name))
        if img is None:
            raise FileNotFoundError(f"找不到模板圖：{TEMPLATE_DIR}/{name}")
        _tmpl_cache[name] = img
    return _tmpl_cache[name]


# 主畫面上方那排圖示（熱點、日常…）是半透明的，背景會透出來，換地圖分數就掉。
# 實測熱點：草地 0.81、城鎮石板路 0.54~0.59（門檻 0.80）。
# 只比圖示裡「白色、不透明」的圖案和字之後：主畫面 0.89~0.97，不是主畫面的只有 0.36~0.39。
# 一般比對的分數照樣算，兩種取高的，所以原本認得出來的不會變差。
# main_mark（主畫面標記）也算：建議抓上方「隊伍」圖示。暗色地圖會把圖示染成淡紫、變暗，
# 「日常」圖示的人物還會眨眼（某個帳號在暗色地圖被判成不在主畫面：日常只有 0.38）；
# 「隊伍」灰階遮罩在暗色地圖 0.93、一般主畫面 0.95~0.99、非主畫面最高 0.48。
SEE_THROUGH = ("hotspot", "daily", "main_mark")

# 日常清單的列標題，活動期間會變色（例：委託雙倍時「【任務委託板】」從藍字變橙字）。
# 實測橙字對藍字模板：彩色 0.41、灰階 0.967；其他列灰階最高 0.63。
# 灰階分數只採計 GRAY_MIN 以上，其他列絕對不會被當成目標（連找半截用的 0.66 都碰不到）。
COLOR_FREE = ("commission_row", "pet_row")
GRAY_MIN = 0.75


def _tmpl_base(name):
    """daily_2.png → daily"""
    return re.sub(r"_\d+$", "", os.path.splitext(name)[0])


def template_mask(name):
    """半透明圖示的遮罩：只留白色的圖案和字（右上角的紅點、透出來的背景都不算）。其他模板回傳 None。"""
    base = _tmpl_base(name)
    if base not in SEE_THROUGH:
        return None
    if name not in _mask_cache:
        hsv = cv2.cvtColor(load_template(name), cv2.COLOR_BGR2HSV)
        m = ((hsv[:, :, 2] > 200) & (hsv[:, :, 1] < 60)).astype(np.uint8) * 255
        _mask_cache[name] = m if (m > 0).mean() >= 0.04 else None   # 白色太少就不用遮罩
    return _mask_cache[name]


def match(screen, name):
    """模板比對的分數圖。半透明圖示會另外用遮罩比一次、會變色的列標題另外用灰階比一次，取高的。"""
    tmpl = load_template(name)
    res = cv2.matchTemplate(screen, tmpl, cv2.TM_CCOEFF_NORMED)
    if _tmpl_base(name) in COLOR_FREE:
        gray = cv2.matchTemplate(cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY),
                                 cv2.cvtColor(tmpl, cv2.COLOR_BGR2GRAY), cv2.TM_CCOEFF_NORMED)
        res = np.maximum(res, np.where(gray >= GRAY_MIN, gray, -1.0).astype(res.dtype))
    mask = template_mask(name)
    if mask is not None:
        try:
            masked = cv2.matchTemplate(screen, tmpl, cv2.TM_CCOEFF_NORMED, mask=mask)
            masked = np.nan_to_num(masked, nan=-1.0, posinf=-1.0, neginf=-1.0)
            res = np.maximum(res, masked)
            # 再用灰階比一次：只看形狀，不管被地圖光線染成什麼顏色
            gmask = cv2.matchTemplate(cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY),
                                      cv2.cvtColor(tmpl, cv2.COLOR_BGR2GRAY), cv2.TM_CCOEFF_NORMED, mask=mask)
            gmask = np.nan_to_num(gmask, nan=-1.0, posinf=-1.0, neginf=-1.0)
            res = np.maximum(res, gmask.astype(res.dtype))
        except cv2.error:
            pass                                   # 太舊的 OpenCV 不支援遮罩：照舊
    return res


def template_variants(name):
    """daily.png、daily_2.png、daily_3.png ... 全部算同一顆按鈕。"""
    base, ext = os.path.splitext(name)
    out = []
    if os.path.exists(os.path.join(TEMPLATE_DIR, name)):
        out.append(name)
    i = 2
    while os.path.exists(os.path.join(TEMPLATE_DIR, f"{base}_{i}{ext}")):
        out.append(f"{base}_{i}{ext}")
        i += 1
    return out


def has(name):
    return bool(template_variants(name))


def find_all(screen, name, threshold=None):
    """回傳 [(x, y, w, h, 分數, 模板檔名), ...]。"""
    threshold = MATCH_THRESHOLD if threshold is None else threshold
    boxes = []
    for v in template_variants(name):
        tmpl = load_template(v)
        th, tw = tmpl.shape[:2]
        if screen.shape[0] < th or screen.shape[1] < tw:
            continue
        res = match(screen, v)
        ys, xs = np.where(res >= threshold)
        boxes += [(int(x), int(y), tw, th, float(res[y, x]), v)
                  for x, y in zip(xs, ys)]
    boxes.sort(key=lambda b: -b[4])
    kept = []
    for b in boxes:
        if all(abs(b[0] - k[0]) > b[2] * 0.5 or abs(b[1] - k[1]) > b[3] * 0.5
               for k in kept):
            kept.append(b)
    return kept


def find_one(screen, name, threshold=None):
    r = find_all(screen, name, threshold)
    return r[0] if r else None


def wait_for(name, timeout=FIND_TIMEOUT):
    deadline = time.time() + timeout * max(0.5, SLOW)
    while True:
        box = find_one(grab(), name)
        if box or time.time() >= deadline:
            return box
        time.sleep(0.4)


def wait_until(pred, timeout):
    """反覆截圖直到 pred(screen) 為真。"""
    deadline = time.time() + timeout * max(0.5, SLOW)
    while True:
        screen = grab()
        if pred(screen):
            return True
        if time.time() >= deadline:
            return False
        time.sleep(0.4)


CUR_HWND = None                  # 正在處理的視窗（do_account 設定）


def window_state(hwnd=None):
    """檢查遊戲視窗是不是還好好待在工作位置。沒問題回傳空字串，有問題回傳說明。

    雷電曾經跑到一半整個視窗不見（截圖拍到桌面），補跑時又正常，所以每項任務前都檢查。
    """
    hwnd = hwnd or CUR_HWND
    if not hwnd:
        return ""
    probs = []
    try:
        if not win32gui.IsWindow(hwnd):
            return "視窗已經不存在（模擬器關掉了？）"
        if win32gui.IsIconic(hwnd):
            probs.append("被縮小到工作列")
        else:
            target = find_render_child(hwnd) if USE_RENDER_CHILD else None
            x, y, w, h = get_rect(target or hwnd)
            if abs(x - AREA_X) > 4 or abs(y - AREA_Y) > 4 or abs(w - AREA_W) > 4 or abs(h - AREA_H) > 4:
                probs.append(f"位置跑掉了（現在 {x},{y} {w}x{h}，應該在 {AREA_X},{AREA_Y} {AREA_W}x{AREA_H}）")
        fg = win32gui.GetForegroundWindow()
        if fg and fg != hwnd:
            title = win32gui.GetWindowText(fg) or "沒有標題的視窗"
            if fg in find_windows():               # 同樣叫 ROM Classic 的話，說清楚是哪一個
                probs.append(f"最上面是另一個遊戲視窗「{window_label(fg)}」")
            else:
                probs.append(f"最上面是「{title}」")
    except Exception as e:
        probs.append(f"檢查視窗時出錯：{e}")
    return "、".join(probs)


def ensure_window():
    """視窗被縮小、移走或被蓋住就拉回來。回傳發生了什麼（沒事回傳空字串）。"""
    state = window_state()
    if state:
        step(f"視窗狀態不對（{state}），拉回原位")
        normalize_window(CUR_HWND)
    return state


def dump_fail(tag):
    os.makedirs(SHOT_DIR, exist_ok=True)
    path = os.path.join(SHOT_DIR, f"fail_{tag}.png")
    imwrite(path, grab())
    state = window_state()                     # 順便記下當下視窗狀態，事後才知道是誰動了它
    return f"{path}；當下視窗{state}" if state else path


# ---------------------------------------------------------------------------
# 基本動作
# ---------------------------------------------------------------------------

def click_at(cx, cy, wait=T_CLICK_MAX):
    pyautogui.moveTo(AREA_X + cx, AREA_Y + cy, duration=0.1)
    pyautogui.click()
    return wait_stable(wait)


def click_box(box, name=None, wait=T_CLICK_MAX):
    """點比對到的框。有偏移就用偏移（清單列 → 右邊按鈕），否則點正中央。"""
    x, y, w, h = box[0], box[1], box[2], box[3]
    off = CLICK_OFFSET.get(box[5]) or (CLICK_OFFSET.get(name) if name else None)
    cx, cy = (x + off[0], y + off[1]) if off else (x + w // 2, y + h // 2)
    return click_at(cx, cy, wait)


def safe_click(times=1):
    pt = SAFE_CLICK or (AREA_W // 2, 40)
    for _ in range(times):
        click_at(pt[0], pt[1], wait=1.6)


def mouse_move(x, y):
    """拖曳途中移動滑鼠（螢幕座標）。

    官方：pyautogui.moveTo（游標瞬移）就拖得動，維持原樣。
    雷電：要用 mouse_event 送「真正的移動訊號」，按住時模擬器才看得到手指在滑。
    """
    if not RAW_MOUSE:
        pyautogui.moveTo(x, y)
        return
    u = ctypes.windll.user32
    vx, vy = u.GetSystemMetrics(76), u.GetSystemMetrics(77)     # 虛擬桌面（多螢幕）左上角
    vw, vh = u.GetSystemMetrics(78), u.GetSystemMetrics(79)     # 虛擬桌面寬高
    nx = int(round((x - vx) * 65535 / max(1, vw - 1)))
    ny = int(round((y - vy) * 65535 / max(1, vh - 1)))
    # MOVE | ABSOLUTE | VIRTUALDESK
    win32api.mouse_event(0x0001 | 0x8000 | 0x4000, nx, ny, 0, 0)


def drag(start, dy, steps=24, hold=0.035):
    """在清單範圍內慢慢拖曳，放開前停一下讓慣性歸零。

    只用 start 的 x；起點和終點的 y 都夾在 LIST_TOP ~ LIST_BOTTOM 之間，
    確保滑鼠整段路都在清單上。之前終點跑到視窗外面，Unity 會把拖曳當成取消，
    清單就彈回原位，看起來像「滑下去又彈到最上面」。
    """
    x = AREA_X + start[0]
    if dy < 0:                                  # 往下捲：從清單底部往上拉
        y_start = LIST_BOTTOM - 15
        y_end = max(LIST_TOP + 10, y_start + dy)
    else:                                       # 往上捲（scroll_to_top 用）
        y_start = LIST_TOP + 15
        y_end = min(LIST_BOTTOM - 10, y_start + dy)
    y0, y1 = AREA_Y + y_start, AREA_Y + y_end

    pyautogui.moveTo(x, y0, duration=0.1)
    mouse_move(x, y0)
    pyautogui.mouseDown()
    time.sleep(0.15)
    for i in range(1, steps + 1):
        mouse_move(x, y0 + int((y1 - y0) * i / steps))
        time.sleep(hold)
    time.sleep(0.3)
    pyautogui.mouseUp()
    time.sleep(0.15)
    quick = grab()                 # 放開後立刻拍一張，用來判斷「有動但彈回去」
    time.sleep(0.4)
    wait_stable(2.0)
    return quick


PRIMARY_DRAG_OK = False          # 主拖曳起點有沒有成功捲動過
LIST_BOUNCES = False             # 這個帳號的清單捲完會自己跳回頂端（清單在即時刷新）


def park_mouse():
    """把滑鼠移到面板上方的空白處，關掉可能因為停在圖示上而跳出的提示框。"""
    pyautogui.moveTo(AREA_X + AREA_W // 2, AREA_Y + 60, duration=0.1)
    nap(0.5)


def scroll_down(thorough=False):
    """清單往下捲一段。回傳畫面有沒有變（沒變 = 已經到底）。

    thorough=True 用在「這個面板的第一次捲動」：清單有 6~8 項，第一次一定捲得動，
    捲不動就是被什麼東西擋到（例如提示框），值得換幾種方法再試。
    之後的捲動失敗就單純是到底了，不浪費時間重試。
    只用拖曳不用滾輪當主力：ROM 的滾輪方向是反的，只留作最後手段。
    """
    global PRIMARY_DRAG_OK, LIST_BOUNCES, LIST_SCROLLED
    before = list_settle()
    quick = drag(SCROLL_POINT, -300)
    if list_changed(before, list_settle()):
        PRIMARY_DRAG_OK = True
        LIST_SCROLLED = True
        step("清單往下捲：有動")
        return True
    if LIST_CHECK_REGION is not None and LIST_SCROLLED:
        # 已經成功捲過了：這次放開瞬間有動、等一下又回原樣，是「到底了拉過頭彈回來」，
        # 不是「清單會跳回頂端」。（雷電之前會被誤判，切到拖完立刻找模式一直拉）
        step("清單往下捲：沒動（到底了）")
        return False
    bounced = (list_changed(before, quick) if LIST_CHECK_REGION is not None
               else changed(before, quick, factor=4))
    if bounced:
        # 放開的瞬間「整個清單」有動、等一下又回到原樣 = 清單自己跳回去了。
        # 門檻拉高四倍，避免小面積的東西（提示字、游標效果）閃一下就被當成有捲動。
        if not LIST_BOUNCES:
            step("注意：這個帳號的日常清單捲完會自己跳回頂端，改用「拖完立刻找」模式")
        LIST_BOUNCES = True
        PRIMARY_DRAG_OK = True
        return False
    if not thorough:
        step("清單往下捲：沒動（到底了）")
        return False

    step("清單第一次捲就沒動，換方法再試（移開滑鼠、換起點、滾輪）")
    park_mouse()                                   # 先把提示框弄掉再試一次
    before = list_settle()
    drag(SCROLL_POINT, -300)
    if list_changed(before, list_settle()):
        PRIMARY_DRAG_OK = True
        LIST_SCROLLED = True
        step("清單往下捲：移開滑鼠後有動")
        return True

    before = list_settle()                         # 換另一個起點
    drag(SCROLL_POINT_ALT, -300)
    if list_changed(before, list_settle()):
        LIST_SCROLLED = True
        step("清單往下捲：換起點後有動")
        return True

    before = list_settle()                         # 最後手段：滾輪（方向反的，所以是正值）
    pyautogui.moveTo(AREA_X + SCROLL_POINT[0], AREA_Y + (LIST_TOP + LIST_BOTTOM) // 2, duration=0.1)
    pyautogui.scroll(400)
    wait_stable(1.5)
    after = list_settle()
    if list_changed(before, after):
        LIST_SCROLLED = True
        step("清單往下捲：用滾輪才動")
        return True
    step("清單往下捲：四種方法都沒動（到底了，或被什麼擋住）")
    # 四種方法都沒動：存下前後兩張，事後才看得出是「沒動」還是「動了又彈回來」
    imwrite(os.path.join(SHOT_DIR, "scrolldebug_before.png"), before)
    imwrite(os.path.join(SHOT_DIR, "scrolldebug_after.png"), after)
    return False


def scroll_to_top(max_drags=4):
    """清單一路捲回最上面。回傳有沒有真的往上捲過（本來就在最上面 = False）。"""
    moved = False
    for n in range(max_drags):
        before = list_settle()
        drag(SCROLL_POINT, 300)
        if not list_changed(before, list_settle()):
            step(f"清單往上捲第 {n + 1} 次：沒動（到頂了）")
            break
        step(f"清單往上捲第 {n + 1} 次：有動")
        moved = True
    return moved


# ---------------------------------------------------------------------------
# 畫面判斷與面板開關
# ---------------------------------------------------------------------------

def disconnected(screen=None):
    """看得到斷線／重新連線的視窗嗎（需要 disconnect.png，沒抓就一律 False）。"""
    if not has("disconnect.png"):
        return False
    screen = grab() if screen is None else screen
    return find_one(screen, "disconnect.png") is not None


def on_main(screen=None):
    """在主畫面嗎。看得到「日常」按鈕，或看得到 main_mark.png（主畫面固定標記）都算。

    日常按鈕是半透明的、人物還會眨眼，換地圖就可能認不出來；main_mark 建議抓上方的「隊伍」圖示
    （圖案固定、暗色地圖也認得到），兩者互為備援。
    """
    screen = grab() if screen is None else screen
    if find_one(screen, "daily.png"):
        return True
    return has("main_mark.png") and find_one(screen, "main_mark.png") is not None


def daily_panel_open(timeout=4.0):
    """日常面板開了嗎。有 daily_panel.png 就等它出現；沒有就以「離開主畫面」為準。"""
    if has("daily_panel.png"):
        return wait_for("daily_panel.png", timeout=timeout) is not None
    return wait_until(lambda sc: not on_main(sc), timeout)


def back_to_main(tries=12):
    """一層一層關，直到主畫面的『日常』按鈕露出來。

    優先順序：紅色 X > 返回鍵 > 點空白處 > ESC。
    ESC 排最後，因為在主畫面按 ESC 會叫出「設置」。
    """
    for i in range(tries):
        screen = grab()
        if on_main(screen):
            return True
        dead = has("dead_btn.png") and find_one(screen, "dead_btn.png")
        if dead:
            click_box(dead, wait=T_PANEL_MAX)         # 角色死了：回到記錄點，等復活載圖
            nap(3.0)
            wait_stable(5.0)
            continue
        box = find_one(screen, "close_x.png") or find_one(screen, "back_btn.png")
        if box:
            click_box(box)
            continue
        if i % 2 == 0 or not USE_ESC:
            safe_click(1)
        else:
            pyautogui.press("esc")
            wait_stable(1.5)
    return False


def open_daily():
    """回主畫面並打開日常面板。剛打開時清單一定在最上面。

    優先用快捷鍵（不受地圖背景影響），快捷鍵沒反應才退回去點日常按鈕。
    """
    global LIST_SCROLLED
    LIST_SCROLLED = False                          # 新打開的面板，還沒捲過
    if not on_main() and not back_to_main():
        return False
    park_mouse()
    if HOTKEYS:
        pyautogui.press(DAILY_KEY)
        nap(0.6)
        wait_stable(T_PANEL_MAX)
        if daily_panel_open():
            return True
    # 沒快捷鍵（或沒反應）就點按鈕。日常圖示的人物會眨眼，多看幾次等睜眼的那一格
    box = wait_for("daily.png", timeout=2.0)
    if box:
        click_box(box, wait=T_PANEL_MAX)
        return daily_panel_open()
    if DAILY_BTN and on_main():
        # 還是認不到（暗色地圖染色＋眨眼）：上方那排位置每個帳號都一樣，直接點固定位置
        step("認不到「日常」圖示（人物眨眼或地圖太暗），改點固定位置")
        click_at(DAILY_BTN[0], DAILY_BTN[1], wait=T_PANEL_MAX)
        return daily_panel_open()
    return False


def row_visible(box):
    """這一列右邊的按鈕點得到嗎。只怕被清單下緣切到；靠上緣的列文字看得到就點得到。"""
    return box[1] <= ROW_SAFE_BOTTOM


def row_is_done(screen, row):
    """那一列右邊有「已完成／已領取」標記嗎。"""
    if not has("row_done.png"):
        return False
    rx, ry, rw, rh = row[0], row[1], row[2], row[3]
    cy = ry + rh // 2
    return any(abs((b[1] + b[3] // 2) - cy) <= 30 and b[0] > rx + rw // 2
               for b in find_all(screen, "row_done.png"))


def drag_and_find(name, want_visible=True, timeout=1.3):
    """拖一段，放開後不等畫面靜止，立刻反覆找目標；找到就馬上回傳讓呼叫端點下去。

    專門對付「清單會自己跳回頂端」的帳號：從放開到跳回去大概有一秒左右的空檔，
    要在那之內完成「找到 → 點」。
    """
    x = AREA_X + SCROLL_POINT[0]
    y0, y1 = AREA_Y + LIST_BOTTOM - 15, AREA_Y + LIST_TOP + 10
    pyautogui.moveTo(x, y0, duration=0.08)
    mouse_move(x, y0)
    pyautogui.mouseDown()
    time.sleep(0.12)
    for i in range(1, 19):
        mouse_move(x, y0 + int((y1 - y0) * i / 18))
        time.sleep(0.025)
    time.sleep(0.25)
    pyautogui.mouseUp()
    deadline = time.time() + timeout
    while time.time() < deadline:
        box = find_one(grab(), name)
        if box and (not want_visible or row_visible(box)):
            return box
        time.sleep(0.05)
    return None


def find_row(name, rounds=2):
    """在日常清單找某一列。先看目前畫面，找不到或只露半截才往下捲。

    被面板邊緣切到的列比對分數會偏低，所以在正常門檻找不到時，
    再用低一點的門檻看一次；看到了就知道「在下面，捲下去就有」。
    """
    partial = None
    if not wait_until(lambda sc: panel_loaded(DAILY_LIST_REGION, sc), 6.0):
        step("日常清單等了很久還是空白（網路慢？），照樣往下找")
    if LIST_BOUNCES:                               # 已知會彈回：直接用快速模式
        box = find_one(grab(), name)
        if box and row_visible(box):
            return box
        for _ in range(3):
            box = drag_and_find(name)
            if box:
                return box
        return None

    def search_down(first_pass):
        """從目前位置一路往下找。回傳 (找到的列, 只露半截的列)。"""
        part = None
        for i in range(rounds + 1):
            screen = grab()
            box = find_one(screen, name) or find_one(screen, name, threshold=0.66)
            if box:
                if row_visible(box) and box[4] >= MATCH_THRESHOLD:
                    return box, part
                part = box
            if i >= rounds:
                break
            if not scroll_down(thorough=(first_pass and i == 0)):
                break
        return None, part

    box, partial = search_down(True)
    if box:
        return box
    if partial:
        return partial
    # 往下都沒有：可能清單一打開還在載入，第一眼沒看到就捲過頭了。捲回最上面再找一輪。
    if scroll_to_top():
        step("往下沒找到，捲回最上面重找一次")
        box, partial = search_down(False)
        if box or partial:
            return box or partial
    # 一般模式沒找到：不管有沒有偵測到彈回，都用「拖完立刻找」再試兩次。
    # 彈回的偵測偶爾會漏（放開瞬間那張剛好沒拍到移動），這樣可以補上。
    for _ in range(2):
        box = drag_and_find(name)
        if box:
            return box
    return None


def still_on_list(screen=None):
    """日常清單還開著嗎。有面板標題模板就看標題（最準）；沒有才看列文字。"""
    screen = grab() if screen is None else screen
    if has("daily_panel.png"):
        return find_one(screen, "daily_panel.png") is not None
    return bool(find_one(screen, "commission_row.png")
                or find_one(screen, "pet_row.png"))


ROW_BUTTON_X_RATIO = 0.87        # 清單右邊那欄按鈕的 x 大約在工作區寬度的 87%


def click_row_button(row, tmpl):
    """點某一列右邊的按鈕：先用校正的偏移量，沒進去就改點按鈕欄的固定位置。"""
    step("點那一列右邊的「前往」")
    click_box(row, tmpl, wait=T_PANEL_MAX)
    if not still_on_list():
        return True
    step("還在清單上，改點按鈕欄的固定位置再試一次")
    cy = row[1] + row[3] // 2
    click_at(int(AREA_W * ROW_BUTTON_X_RATIO), cy, wait=T_PANEL_MAX)
    return not still_on_list()


def open_row(tmpl):
    """找到清單某一列並點進去，確認清單真的消失了。點歪會重試。"""
    for _ in range(3):
        row = find_row(tmpl)
        if row and click_row_button(row, tmpl):
            return True
        if not scroll_down():
            # 到底了還進不去，最後再直接試一次
            row = find_one(grab(), tmpl)
            if row:
                return click_row_button(row, tmpl)
            return False
    return False


# ---------------------------------------------------------------------------
# 任務一：寵物打工（F1 寵物手冊 → 寵物打工分頁）
# ---------------------------------------------------------------------------

PET_TITLE_TRUST = False          # 這次進打工畫面時標題有沒有認出來（沒有就不靠它做判斷）


def on_pet_screen(screen=None):
    """在打工畫面上嗎。沒有 pet_title.png 就回傳 None（無從判斷）。"""
    if not has("pet_title.png"):
        return None
    screen = grab() if screen is None else screen
    return find_one(screen, "pet_title.png", threshold=0.72) is not None


def open_pet_screen():
    """快捷鍵開寵物手冊 → 點右邊「寵物打工」分頁。回傳有沒有進到打工畫面。

    判斷順序：
      1. 認得出「寵物打工」標題 → 確定進去了，之後也用標題做檢查
      2. 認不出標題，但已經不在主畫面 → 當作進去了，之後不靠標題判斷
      3. 還在主畫面 → 沒打開
    手冊有時載入慢，分頁點早了會沒反應，所以最多點兩次。
    """
    global PET_TITLE_TRUST
    PET_TITLE_TRUST = False
    if HOTKEYS:
        step(f"按 {PET_KEY.upper()} 開寵物手冊")
        pyautogui.press(PET_KEY)
        nap(0.8)
        wait_stable(T_PANEL_MAX)
    if on_main() and PET_SLOT:                     # 沒快捷鍵（或沒反應）→ 點快捷列格子
        step("點快捷列的寵物箱開寵物手冊")
        click_at(PET_SLOT[0], PET_SLOT[1], wait=T_PANEL_MAX)
    for k in range(2):
        if PET_TAB:
            step(f"點右邊「寵物打工」分頁（第 {k + 1} 次）")
            click_at(PET_TAB[0], PET_TAB[1], wait=T_PANEL_MAX)
        if wait_until(lambda sc: on_pet_screen(sc) is True, 5.0):
            PET_TITLE_TRUST = True
            step("進入寵物打工畫面（認出標題）")
            return True
        if not on_main():
            step("進入寵物打工畫面（標題沒認出來，但已經不在主畫面）")
            return True                        # 進去了，只是標題沒認出來
    step("還在主畫面，寵物手冊沒打開")
    return False


def ensure_pet_screen():
    """確認還在打工畫面；不小心點進別的東西就關掉，關不掉就整個重進。

    只有在進來時標題有認出來，才用標題判斷；否則一律當作沒事。
    """
    if not PET_TITLE_TRUST or on_pet_screen():
        return True
    screen = grab()
    box = find_one(screen, "close_x.png") or find_one(screen, "back_btn.png")
    if box:
        click_box(box)
    elif USE_ESC:
        pyautogui.press("esc")
        wait_stable(1.5)
    else:
        safe_click(1)
    if on_pet_screen():
        return True
    back_to_main()
    return open_pet_screen()


def count_gifts(screen=None, exclude=()):
    """數畫面上還有幾個可領的圖示（只算建築物那區，排除點過的位置）。"""
    if not has("pet_gift.png"):
        return []
    screen = grab() if screen is None else screen
    gifts = [g for g in find_all(screen, "pet_gift.png") if g[0] >= PET_GIFT_MIN_X]
    return [g for g in gifts
            if all(abs(g[0] - c[0]) > 15 or abs(g[1] - c[1]) > 15 for c in exclude)]


def collect_by_grid():
    """九宮格模式：每一格都點兩下（第二下關獎勵視窗），不管有沒有東西。"""
    clicks = 0
    for x, y in PET_SLOTS:
        click_at(x, y)
        click_at(x, y)
        clicks += 1
        step(f"九宮格第 {clicks} 格（{x},{y}）：點兩下（第二下關獎勵視窗）")
        if not ensure_pet_screen():
            step("點完這格跑出打工畫面了")
            return clicks, False
    return clicks, True


def collect_by_detect():
    """辨識模式：在畫面上找禮物圖示，一個一個點。"""
    got = 0
    clicked = []
    empty = 0
    for _ in range(MAX_PET_GIFTS):
        gifts = count_gifts(exclude=clicked)
        if not gifts:
            empty += 1
            if empty >= 3:
                break
            safe_click(1)
            nap(1.0)
            continue
        empty = 0
        gifts.sort(key=lambda b: (b[1], b[0]))
        g = gifts[0]
        click_box(g)
        click_box(g)
        clicked.append((g[0], g[1]))
        got += 1
        step(f"收第 {got} 份禮物（{g[0]},{g[1]}）")
    return got


def do_pet_work(idx):
    """開寵物打工畫面，把禮物和樂園幣全收掉。回傳 (收乾淨了嗎, 訊息)。"""
    use_grid = (PET_MODE == "grid" and PET_SLOTS)
    if not use_grid and not has("pet_gift.png"):
        return True, "（沒有九宮格座標也沒有 pet_gift.png，跳過寵物打工）"

    if not on_main():
        back_to_main()

    if not open_pet_screen():
        shot = dump_fail(f"win{idx:02d}_pet_open")   # 先截圖，再回主畫面
        back_to_main()
        return False, (f"打不開寵物打工，請確認 {PET_KEY.upper()} 快捷鍵和「寵物打工分頁」位置"
                       f"（{shot}）")

    if use_grid:
        clicks, intact = collect_by_grid()
        msg = f"寵物打工九宮格點了 {clicks} 格"
        if not PET_TITLE_TRUST:
            # 沒認出寵物打工的標題，只是「不在主畫面」就當作進去了：可能根本開錯面板
            # （使用者忘了把寵物手冊放 F1，點了 7 格卻被記成今天做完，重跑就跳過）→ 不記
            global UNSURE
            UNSURE = True
            if has("pet_title.png"):
                msg += "（標題沒認出來，請到校正分頁重抓 pet_title 並按測試）"
        if not intact:
            shot = dump_fail(f'win{idx:02d}_pet_lost')   # 先截圖，再回主畫面
            back_to_main()
            return False, msg + f"，中途跑出打工畫面（{shot}）"
    else:
        got = collect_by_detect()
        msg = f"寵物打工收了 {got} 份"

    # 有禮物模板就順便確認一下有沒有剩，沒有就相信九宮格
    ok = True
    if has("pet_gift.png"):
        left = len(count_gifts())
        step(f"檢查畫面上還有沒有禮物：{f'還有 {left} 個' if left else '沒有了'}")
        if left:
            dump_fail(f"win{idx:02d}_pet_left")
            msg += f"，畫面上還看得到 {left} 個"
            ok = False
    back_to_main()
    return ok, msg


# ---------------------------------------------------------------------------
# 任務二：任務委託板
# ---------------------------------------------------------------------------

def handle_quick_confirm():
    """按「快速完成」後偶爾會跳「是否消耗冒險丸子立即完成此任務？」（不是每次）。

    有跳：勾「不再提示」、按「確定」，回傳 True。沒跳：False。
    跳了但兩個位置還沒校正（按不了）：None。沒抓這張模板就當作不會跳，照舊。
    視窗一定在畫面正中央，所以方框和確定按鈕用固定位置就好。
    """
    if not has("quick_confirm.png"):
        return False
    if not wait_until(lambda sc: find_one(sc, "quick_confirm.png") is not None, 1.0):
        return False
    if not (QUICK_NO_REMIND and QUICK_CONFIRM_OK):
        step("跳出「是否消耗冒險丸子立即完成此任務？」，但「不再提示／確定」的位置還沒校正，按不了")
        return None
    step("跳出「是否消耗冒險丸子立即完成此任務？」→ 勾「不再提示」、按「確定」")
    click_at(QUICK_NO_REMIND[0], QUICK_NO_REMIND[1], wait=0.8)
    click_at(QUICK_CONFIRM_OK[0], QUICK_CONFIRM_OK[1], wait=T_PANEL_MAX)
    return True


_abandon_stuck = False           # 這隻帳號有被接取的委託、但放棄的校正沒抓（do_commission 歸零）


def handle_abandon():
    """委託被按錯「接取任務」了：卡片上會變成紅色「放棄任務」，那張就不能快速完成。

    按「放棄任務」→ 等「是否要放棄懸賞任務？」→ 按「確定」，卡片恢復成可以快速完成。
    沒抓 abandon_btn.png 就不處理；確認畫面或確定位置沒抓，也不去按放棄（免得卡在半路）。
    一隻帳號最多處理 3 張。回傳處理了幾張。
    """
    if not has("abandon_btn.png"):
        return 0
    n = 0
    for _ in range(3):
        btn = find_one(grab(), "abandon_btn.png")
        if not btn:
            break
        if not (has("abandon_confirm.png") and ABANDON_OK):
            global _abandon_stuck
            if not _abandon_stuck:
                step("有一張委託被接取了（出現「放棄任務」），但放棄用的確認字樣或確定位置還沒校正，先不動它")
            _abandon_stuck = True
            break
        step("有一張委託被接取了（按錯了？）→ 按「放棄任務」")
        click_box(btn, wait=T_PANEL_MAX)
        if not wait_until(lambda sc: find_one(sc, "abandon_confirm.png") is not None, 3.0):
            step("沒看到「是否要放棄懸賞任務？」，不按確定")
            break
        click_at(ABANDON_OK[0], ABANDON_OK[1], wait=T_PANEL_MAX)
        n += 1
        step("按「確定」放棄了，這張恢復成可以快速完成")
    return n


KEEP_DAILY = False               # 這隻等一下要領取：委託做完回到日常面板就好，不用回主畫面
DAILY_OPEN_NOW = False           # 日常面板現在開著（委託留給領取用）


def leave_for_claim():
    """委託做完：等一下要領取的話，關掉委託看板、留在日常面板；不行就照舊回主畫面。"""
    global DAILY_OPEN_NOW
    DAILY_OPEN_NOW = False
    if KEEP_DAILY and has("daily_panel.png"):
        if not find_one(grab(), "daily_panel.png"):    # 還在委託看板：按 X 回日常清單
            x = find_one(grab(), "close_x.png")
            if x:
                click_box(x, wait=T_PANEL_MAX)
        if wait_for("daily_panel.png", timeout=3.0):
            DAILY_OPEN_NOW = True
            step("回到日常面板，等一下直接領取")
            return
    back_to_main()


def do_commission(idx):
    """日常 → 委託板 → 快速完成 ×3。回傳 (3/3 了嗎, 訊息)。"""
    step("打開日常面板")
    if not open_daily():
        return False, f"打不開日常（{dump_fail(f'win{idx:02d}_daily')}）"

    step("在清單上找「任務委託板」")
    row = find_row("commission_row.png")
    if not row:
        shot = dump_fail(f'win{idx:02d}_comm_row')   # 先截圖，再回主畫面
        back_to_main()
        return False, f"清單上找不到委託板（{shot}）"
    step("找到「任務委託板」那一列")
    if row_is_done(grab(), row):
        step("那一列有完成標記：今天已經做完")
        leave_for_claim()
        return True, "委託板今天已完成"

    if not open_row("commission_row.png"):
        shot = dump_fail(f'win{idx:02d}_comm_open')   # 先截圖，再回主畫面
        back_to_main()
        return False, f"進不去委託看板（{shot}）"

    step("進入委託看板")
    global _abandon_stuck
    _abandon_stuck = False
    done = 0
    handle_abandon()                           # 一進來就有被接取的（三張都接了就看不到快速完成）
    wait_for("quick_complete.png", timeout=FIND_TIMEOUT)
    for _ in range(MAX_QUICK_CLICKS):
        handle_abandon()                       # 上一下按錯變成「接取任務」的話，先放棄掉
        btns = find_all(grab(), "quick_complete.png")
        if not btns:
            break
        btns.sort(key=lambda b: b[0])
        click_box(btns[0])
        if handle_quick_confirm() is None:     # 跳了確認視窗卻按不了：停下來，不要亂點
            shot = dump_fail(f"win{idx:02d}_comm_confirm")
            back_to_main()
            return False, ("快速完成跳出「是否消耗冒險丸子」確認視窗，但「不再提示／確定」位置還沒校正"
                           f"（{shot}）")
        safe_click(3)                      # 金幣視窗 + 獎勵視窗
        done += 1
        step(f"按第 {done} 個「快速完成」，點空白處關掉獎勵視窗")

    stamps = 0
    for _ in range(4):                     # 印章有時晚一拍才蓋上去
        stamps = len(find_all(grab(), "done_stamp.png"))
        if stamps >= 3:
            break
        wait_stable(1.2)
    step(f"檢查完成章：{stamps}/3")

    if stamps < 3:
        dump_fail(f"win{idx:02d}_comm_stamp")
        back_to_main()
    else:
        leave_for_claim()

    if stamps >= 3:
        return True, f"委託點了 {done} 次、3/3 完成"
    if _abandon_stuck:
        return False, (f"委託點了 {done} 次但只有 {stamps} 個已完成：有一張被接取了（紅色「放棄任務」），"
                       "要到校正頁「委託看板」抓放棄用的字樣和確定位置，程式才能幫你放棄")
    return False, f"委託點了 {done} 次但只有 {stamps} 個已完成"


# ---------------------------------------------------------------------------
# 任務：副本掃蕩（狂想寓言 Lv.20）
# ---------------------------------------------------------------------------

def drag_line(x0, y0, x1, y1, steps=20, hold=0.03):
    """從 (x0,y0) 慢慢拖到 (x1,y1)，座標相對工作區。放開前停一下避免慣性。"""
    pyautogui.moveTo(AREA_X + x0, AREA_Y + y0, duration=0.1)
    mouse_move(AREA_X + x0, AREA_Y + y0)
    pyautogui.mouseDown()
    time.sleep(0.15)
    for i in range(1, steps + 1):
        mouse_move(AREA_X + x0 + (x1 - x0) * i // steps,
                   AREA_Y + y0 + (y1 - y0) * i // steps)
        time.sleep(hold)
    time.sleep(0.3)
    pyautogui.mouseUp()
    wait_stable(1.8)


def flick(x0, y0, x1, y1, steps=5):
    """快速一甩（手機的 fling）。有些清單只認這種，慢拖放開時速度是零它不理。"""
    pyautogui.moveTo(AREA_X + x0, AREA_Y + y0, duration=0.05)
    mouse_move(AREA_X + x0, AREA_Y + y0)
    pyautogui.mouseDown()
    for i in range(1, steps + 1):
        mouse_move(AREA_X + x0 + (x1 - x0) * i // steps,
                   AREA_Y + y0 + (y1 - y0) * i // steps)
        time.sleep(0.012)
    pyautogui.mouseUp()
    wait_stable(1.8)


def strip_hex_x():
    """回傳一個「不管分頁列停在哪裡，都壓得到某顆六角形本體」的 x。

    六角形寬約 50、間距 70。分頁列停在最左時第一顆在 281，被捲過的狀態下
    第一顆會偏到 296 左右，差 15 像素。取 358 這個位置，兩種情況都落在六角形裡。
    用比例寫，雷電（800 寬）算出來一樣。
    """
    return int(AREA_W * 0.4475)


def strip_scroll_left(y):
    """把等級分頁列往左端拖一段。回傳分頁列有沒有真的移動。

    使用者實測：要「按在六角形本體上、慢慢拖」才會動。
    拖完先把滑鼠移開再截圖，不然滑鼠停在六角形上的亮光會被當成畫面變了。
    """
    x0, x1 = strip_hex_x(), int(AREA_W * STRIP_DRAG_END)
    park_mouse()
    before = grab()
    drag_line(x0, y, x1, y, steps=26, hold=0.04)     # 慢拖，約 1 秒
    park_mouse()
    wait_stable(1.2)
    return strip_changed(before, grab())


def open_dungeon():
    """按 U（或 更多 → 副本）開副本面板。回傳 (有沒有開起來, 失敗原因)。"""
    if not on_main() and not back_to_main():
        return False, "不在主畫面"
    park_mouse()
    if HOTKEYS:
        pyautogui.press(DUNGEON_KEY)
        nap(0.6)
        wait_stable(T_PANEL_MAX)
    if on_main():
        if not HOTKEYS and not DUNGEON_BTN:
            return False, "這個環境沒有快捷鍵，但「更多裡的副本」位置還沒校正"
        if DUNGEON_BTN:
            more = _more_btn_point()
            if not more:
                return False, "「更多」按鈕位置還沒校正（在副本掃蕩那組的第一下）"
            if too_close(more, DUNGEON_BTN):
                return False, (f"「副本」位置 {tuple(DUNGEON_BTN)} 跟「更多」{more} 是同一點，抓錯了："
                               "校正頁先手動點開「更多」，再抓選單裡的「副本」")
            if not open_more_menu():
                return False, "點了「更多」但選單沒展開（遊戲可能太卡）"
            pt = menu_item_point("menu_dungeon.png", DUNGEON_BTN, "副本")
            if not pt:
                back_to_main()
                return False, "「更多」選單裡找不到「副本」"
            click_at(pt[0], pt[1], wait=T_PANEL_MAX)
    if has("dungeon_panel.png"):
        if wait_for("dungeon_panel.png", timeout=5.0):
            return True, ""
        return False, "點完之後沒看到「所有副本」字樣（dungeon_panel 模板可能對不上，或點的位置不對）"
    if wait_until(lambda sc: not on_main(sc), 4.0):
        return True, ""
    return False, "點完之後還在主畫面"


MENU_REGION = (0.58, 0.19, 0.92, 0.75)   # 「更多」選單展開後蓋住的範圍（比例）


def wake_up():
    """省電模式喚醒：在主畫面點一下無關緊要的地方，等畫面恢復反應。

    只在主畫面點：停在面板上時，點這裡可能點到面板裡的東西；
    那種情況 back_to_main 本來就會點空白處或叉叉，同樣會把遊戲叫醒。
    """
    if not WAKE_CLICK:
        return
    step(f"點寵物箱左邊（{WAKE_CLICK[0]},{WAKE_CLICK[1]}）喚醒省電模式")
    click_at(WAKE_CLICK[0], WAKE_CLICK[1], wait=T_PANEL_MAX)
    nap(0.5)


def open_more_menu():
    """點「更多」，確認選單真的展開了才回傳 True。

    卡的時候點了「更多」沒反應，程式照樣點第二下，就會點到主畫面同位置的東西
    （實際發生：點「副本」的位置在主畫面上剛好是「課題」）。
    判斷：選單那塊畫面變很多（實測展開前後差約 100，平常晃動只有 1~3），而且上方那排圖示還在。
    """
    more = _more_btn_point()
    if not more:
        return False
    x0, y0 = int(AREA_W * MENU_REGION[0]), int(AREA_H * MENU_REGION[1])
    x1, y1 = int(AREA_W * MENU_REGION[2]), int(AREA_H * MENU_REGION[3])
    park_mouse()
    base = grab()

    def is_open(sc):
        return region_changed(base, sc, x0, y0, x1, y1, tol=20) and on_main(sc)

    for attempt in range(2):
        if attempt and is_open(grab()):            # 上一下其實有開，只是比較慢
            step("「更多」選單展開了（上一下比較慢）")
            return True
        click_at(more[0], more[1], wait=T_PANEL_MAX)
        if wait_until(is_open, 3.0):
            step("「更多」選單展開了")
            return True
        if not on_main():                          # 點到別的東西了：收掉再試
            back_to_main()
            base = grab()
        step("「更多」選單沒打開" + ("，再點一次" if attempt == 0 else "，放棄"))
    return False


def menu_item_point(tmpl, fallback, label):
    """「更多」選單展開後，選單裡某一項（副本、設置、好友）要點哪裡。

    不同帳號的選單項目數量不一樣（例如沒公會、功能還沒解鎖就少一格），後面的項目會往前移；
    用固定位置會點到隔壁（朋友的雷電：要點「設置」卻點到「傭兵貓」）。
    有抓 tmpl 就在選單範圍內用找的；沒抓才用校正的固定位置。抓了卻找不到就回傳 None，不亂點。
    """
    if not has(tmpl):
        return fallback
    x0, y0 = int(AREA_W * MENU_REGION[0]), int(AREA_H * MENU_REGION[1])
    x1, y1 = int(AREA_W * MENU_REGION[2]), int(AREA_H * MENU_REGION[3])
    inside = [b for b in find_all(grab(), tmpl)
              if x0 <= b[0] + b[2] // 2 <= x1 and y0 <= b[1] + b[3] // 2 <= y1]
    if not inside:
        step(f"「更多」選單裡找不到「{label}」的圖示")
        return None
    b = max(inside, key=lambda bb: bb[4])
    step(f"在「更多」選單裡找到「{label}」")
    return (b[0] + b[2] // 2, b[1] + b[3] // 2)


def _more_btn_point():
    """「更多」按鈕位置存在組隊那邊（more_btn），這裡借用。"""
    cfg = _read_json(CONFIG_PATH)
    v = cfg.get("more_btn")
    return tuple(v) if v else None


def panel_loaded(region, screen=None):
    """面板某一塊有沒有內容了（不是一片空白在轉圈）。

    實測副本左邊清單：載入中起伏（標準差）1.0，載入完成 67.6；日常清單載入完成 37。門檻 15。
    """
    screen = grab() if screen is None else screen
    x0, y0 = int(AREA_W * region[0]), int(AREA_H * region[1])
    x1, y1 = int(AREA_W * region[2]), int(AREA_H * region[3])
    part = screen[y0:y1, x0:x1]
    if part.size == 0:
        return True
    return float(cv2.cvtColor(part, cv2.COLOR_BGR2GRAY).std()) >= 15


DUNGEON_LIST_REGION = (0.04, 0.13, 0.28, 0.95)   # 副本面板左邊清單
DAILY_LIST_REGION = (0.14, 0.15, 0.95, 0.92)     # 日常面板清單


def select_fable():
    """左邊清單找到【狂想寓言】並點進去。清單順序會變（限時副本會插隊），一律靠找字。

    每次只拖半頁，卡片才不會剛好卡在頁面邊界被切成兩半。
    """
    x = DUNGEON_LIST_X
    half = (DUNGEON_LIST_BOTTOM - DUNGEON_LIST_TOP) // 2
    for i in range(8):
        screen = grab()
        row = find_one(screen, "fable_row.png") or find_one(screen, "fable_row.png", threshold=0.72)
        if row:
            step("左邊清單找到【狂想寓言】，點進去")
            click_box(row, wait=T_PANEL_MAX)
            if not has("dungeon_title.png"):
                return True
            ok = wait_for("dungeon_title.png", timeout=4.0) is not None
            step("右上出現「狂想寓言」標題" if ok else "點了但右上沒出現「狂想寓言」標題")
            return ok
        if i == 7:
            break
        before = grab()
        drag_line(x, DUNGEON_LIST_BOTTOM - 20, x, DUNGEON_LIST_BOTTOM - 20 - half)
        if not changed(before, grab()):
            step(f"左邊清單沒看到狂想寓言，往下拖第 {i + 1} 次：沒動（到底了）")
            break                                  # 捲到底還沒看到
        step(f"左邊清單沒看到狂想寓言，往下拖第 {i + 1} 次：有動")
    return False


def select_lv20():
    """選到 Lv.20。

    把分頁列往左端拖到底（一次拖不動就是到底了），最左邊那格必定是 Lv.20，
    點它，再用「藍色掃蕩按鈕有沒有出現」確認真的選到了。

    以前「看得到 lv20_tab.png 就不拖」：但每格六角形長得幾乎一樣，被選中的 Lv.40
    會被當成 Lv.20，結果完全沒拖就去點（雷電實際發生，使用者看到「只有點、沒有拉」）。
    現在一律先拖到底，模板只拿來決定點哪一格。每次拖的結果都印出來，方便事後判斷。
    """
    y = DUNGEON_TAB_Y
    for n in range(5):
        moved = strip_scroll_left(y)
        step(f"分頁列往左拖第 {n + 1} 次：{'有動' if moved else '沒動（到最左了，或拖曳沒生效）'}")
        if not moved:
            break                                  # 拖不動 = 到底了

    targets = []
    tab = find_one(grab(), "lv20_tab.png", threshold=0.9)
    if tab:
        targets.append((tab[0] + tab[2] // 2, tab[1] + tab[3] // 2))
    fx, fy = DUNGEON_FIRST_TAB
    targets += [(fx, fy), (fx, fy + 27)]
    for cx, cy in targets:
        click_at(cx, cy, wait=T_PANEL_MAX)
        if find_sweep_button():
            step(f"點第一格 Lv.20（{cx},{cy}）：藍色「掃蕩」按鈕出現了")
            return True
        step(f"點第一格 Lv.20（{cx},{cy}）：沒看到藍色「掃蕩」按鈕")
    return find_sweep_button() is not None


_last_red_count = -1


def playtime_is_red():
    """「消耗玩法時長：30」的 30 是不是紅的（紅 = 剩餘時長不夠，不能再掃）。

    找到「消耗玩法時長」那幾個字，從字的左邊一路看到右邊 100 像素，數紅色像素。
    範圍故意涵蓋模板本身，這樣不管抓模板時有沒有把「: 30」框進去都算得到。
    回傳 True / False，找不到那幾個字回傳 None。
    """
    global _last_red_count
    screen = grab()
    lbl = find_one(screen, "playtime_label.png")
    if not lbl:
        _last_red_count = -1
        return None
    x, y, w, h = lbl[0], lbl[1], lbl[2], lbl[3]
    y0, y1 = max(0, y - 4), min(screen.shape[0], y + h + 4)
    x0, x1 = max(0, x - 4), min(screen.shape[1], x + w + 100)
    region = screen[y0:y1, x0:x1]
    if region.size == 0:
        _last_red_count = -1
        return None
    b = region[:, :, 0].astype(int)
    g = region[:, :, 1].astype(int)
    r = region[:, :, 2].astype(int)
    red = int(((r > 140) & (g < 120) & (b < 120) & (r - g > 60)).sum())
    _last_red_count = red
    return red >= 15


def find_sweep_button(screen=None):
    """找「掃蕩」按鈕。

    底下四顆按鈕（掃蕩、開組、匹配、挑戰）三顆是同款藍色，光靠圖片比對會混。
    掃蕩固定在最左邊那格，所以只認 x 在工作區左邊 45% 以內的候選，門檻也拉高。
    """
    screen = grab() if screen is None else screen
    cands = find_all(screen, "sweep_btn.png")
    cands = [c for c in cands if c[0] + c[2] / 2 < AREA_W * 0.45]
    return cands[0] if cands else None


def do_dungeon(idx):
    """U → 狂想寓言 → Lv.20 → 掃蕩到紅字。回傳 (掃滿了嗎, 訊息)。"""
    step("打開副本面板" + (f"（按 {DUNGEON_KEY.upper()}）" if HOTKEYS else "（點「更多」→「副本」）"))
    opened, why = open_dungeon()
    if not opened:
        shot = dump_fail(f"win{idx:02d}_dg_open")
        back_to_main()
        return False, f"打不開副本面板：{why}（{shot}）"

    step("副本面板打開了，等左邊清單載入")
    if not wait_until(lambda sc: panel_loaded(DUNGEON_LIST_REGION, sc), 10.0):
        step("副本清單等了很久還是空白（網路慢？），照樣往下試")
    if not select_fable():
        shot = dump_fail(f"win{idx:02d}_dg_fable")
        back_to_main()
        return False, f"左邊清單找不到狂想寓言（{shot}）"

    if not select_lv20():
        shot = dump_fail(f"win{idx:02d}_dg_lv20")
        gray = has("sweep_disabled.png") and find_one(grab(), "sweep_disabled.png")
        back_to_main()
        if gray:
            step("看到灰色的「掃蕩」按鈕：這週 Lv.20 還沒手動打過")
            return MANUAL, f"Lv.20 掃蕩是灰的：這週還沒手動打過，先打一次才能掃（或沒選到 Lv.20）（{shot}）"
        return False, f"選不到能掃的 Lv.20（{shot}）"

    state = playtime_is_red()
    step("「消耗玩法時長」：" + {True: "已經是紅字（今天掃滿了）", False: "還沒紅，開始掃蕩",
                              None: "找不到這幾個字"}[state])
    if state is True:
        back_to_main()
        return True, "副本掃蕩今天已滿"
    if state is False and has("no_time_toast.png") and find_one(grab(), "no_time_toast.png"):
        back_to_main()
        return True, "副本掃蕩今天已滿"
    if state is None:
        shot = dump_fail(f"win{idx:02d}_dg_label")
        back_to_main()
        return False, f"看不到「消耗玩法時長」字樣（{shot}）"

    def dismiss_reward():
        """關掃蕩後的獎勵視窗。

        不能用一般的「安全空白處」——那個點是照日常面板選的，在副本面板上
        剛好壓到「開組」按鈕。改點副本面板最上面的標題列，那裡什麼都沒有。
        """
        click_at(int(AREA_W * 0.5), int(AREA_H * 0.12), wait=1.2)
        if not find_sweep_button() and not out_of_time():
            click_at(AREA_W // 2, AREA_H // 2, wait=1.2)   # 還沒關就點視窗本體

    def out_of_time():
        """掃滿了嗎：30 變紅，或跳出「剩餘時長不足」的提示。"""
        if playtime_is_red():
            return True
        return has("no_time_toast.png") and find_one(grab(), "no_time_toast.png") is not None

    done = 0
    why = ""
    gray_seen = False
    for _ in range(MAX_SWEEPS):
        btn = find_sweep_button()
        if not btn:
            wait_stable(1.5)
            btn = find_sweep_button()
        if not btn:
            if has("sweep_disabled.png") and find_one(grab(), "sweep_disabled.png"):
                why = "掃蕩按鈕是灰的（Lv.20 沒選到，或這隻沒通關 Lv.20）"
                gray_seen = True
            else:
                why = "找不到藍色的掃蕩按鈕（模板可能對不上）"
            step(why)
            break
        click_box(btn, wait=T_PANEL_MAX)
        done += 1
        if out_of_time():                          # 這一下沒掃成（時長不夠）
            step(f"掃蕩第 {done} 次：按下去時長就紅了／跳出時長不足，停止")
            break
        dismiss_reward()
        red_now = out_of_time()
        step(f"掃蕩第 {done} 次：完成、關掉獎勵視窗；時長"
             f"{'變紅了，停止' if red_now else '還沒紅'}（紅色像素 {_last_red_count}）")
        if red_now:
            break
        if done == 7:
            dump_fail(f"win{idx:02d}_dg_mid")   # 正常 6 次就該紅了，還沒紅先留一張圖

    red = out_of_time()
    shot = None if red else dump_fail(f"win{idx:02d}_dg_end")
    back_to_main()
    if red:
        return True, f"副本掃蕩 {done} 次、時長已用完"
    if why:
        if gray_seen and done == 0:
            return MANUAL, f"Lv.20 掃蕩是灰的：這週還沒手動打過，先打一次才能掃（或沒選到 Lv.20）（{shot}）"
        return False, f"副本掃蕩 {done} 次後停下：{why}（{shot}）"
    return False, f"副本掃蕩 {done} 次但時長還沒紅（紅色像素 {_last_red_count}）（{shot}）"


# ---------------------------------------------------------------------------
# 任務：兌換序號（ESC → 遊戲設置 → 拉到最下面 → 輸入序號 → 兌換）
# ---------------------------------------------------------------------------

def type_text(text):
    """把文字打進目前有焦點的輸入框。先試貼上（不受輸入法影響），再退回逐字打。"""
    ok = False
    try:
        import win32clipboard
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
        win32clipboard.CloseClipboard()
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.1)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.3)
        ok = True
    except Exception:
        ok = False
    if not ok:
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.1)
        pyautogui.typewrite(text, interval=0.04)
        time.sleep(0.3)


def open_settings():
    """開「設置 → 遊戲設置」。官方按 ESC；沒快捷鍵就 更多 → 設置。"""
    if not on_main() and not back_to_main():
        return False
    park_mouse()
    if HOTKEYS:
        pyautogui.press("esc")
        nap(0.6)
        wait_stable(T_PANEL_MAX)
    if on_main() and SETTINGS_BTN:
        more = _more_btn_point()
        if too_close(more, SETTINGS_BTN):
            step("「設置」位置跟「更多」是同一點，抓錯了：校正頁先手動點開「更多」再抓「設置」")
            return False
        if more and not open_more_menu():
            step("點了「更多」但選單沒展開（遊戲可能太卡）")
            return False
        pt = menu_item_point("menu_settings.png", SETTINGS_BTN, "設置")
        if not pt:
            back_to_main()
            return False
        click_at(pt[0], pt[1], wait=T_PANEL_MAX)
    card = wait_for("settings_game.png", timeout=5.0)
    if not card:
        return False
    click_box(card, wait=T_PANEL_MAX)
    return True




def input_bar_visible(screen=None):
    """雷電點了輸入框後，畫面最下面會跳出一條白色輸入列（右邊有「確定」）。

    這時第一下按「兌換」只會把輸入列收起來，不會真的兌換。
    實測最下面那條：有輸入列時 98~100% 是白的，收起來後只有 5%。
    """
    screen = grab() if screen is None else screen
    band = screen[int(AREA_H * 0.88):int(AREA_H * 0.99), int(AREA_W * 0.02):int(AREA_W * 0.90)]
    if band.size == 0:
        return False
    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    return float((gray > 235).mean()) >= 0.9


# ---------------------------------------------------------------------------
# 副本掃蕩券（快捷列 F2，每天用一次）
# ---------------------------------------------------------------------------
# 同一天按第二次會「真的再用掉一張」，所以寧可漏按也不要多按：
#   按之前先記「tried」→ 看到禮物視窗再記「used」。下次看到 tried 沒有 used 就不按，請使用者自己確認。
#   紀錄用「種類｜名字」（不含遊戲程式編號），遊戲重開也記得；也不受「記住今天做完的任務」設定影響。

def ticket_key(hwnd):
    return f"ticket|{window_kind(hwnd)}|{window_label(hwnd)}"


def do_ticket(idx):
    key = ticket_key(CUR_HWND)
    done = done_today(key)
    if "used" in done:
        return True, "副本掃蕩券今天已經用過了（紀錄），跳過"
    if "tried" in done:
        return MANUAL, ("今天按過掃蕩券但沒確認到禮物視窗，為了不多用一張，今天不會再按；"
                        "請自己看一下，確定沒用到的話按控制台「清除今天的完成紀錄」再跑")
    if not (has("sweep_gift.png") and has("ticket_icon.png") and TICKET_SLOT):
        return MANUAL, "副本掃蕩券還沒校正完（校正頁「副本掃蕩券」：禮物盒、F2 上的掃蕩券圖示、F2 那一格的位置）"
    if not on_main() and not back_to_main():
        return False, f"不在主畫面，沒按掃蕩券（{dump_fail(f'win{idx:02d}_ticket_start')}）"
    # 不是每隻角色都有掃蕩券：沒有的 F2 可能是空的，也可能放了別的東西（按下去會用掉那個東西！）
    # 所以先確認 F2 那一格真的是掃蕩券才按
    sx, sy = TICKET_SLOT
    here = [b for b in find_all(grab(), "ticket_icon.png")
            if abs(b[0] + b[2] // 2 - sx) < 40 and abs(b[1] + b[3] // 2 - sy) < 40]
    if not here:
        return True, "這隻角色沒有副本掃蕩券（F2 不是掃蕩券），跳過"

    mark_done("tried", key)                        # 先記：就算按完程式剛好停掉，下次也不會再按
    if HOTKEYS:
        step(f"F2 是掃蕩券，按 {TICKET_KEY.upper()} 使用")
        pyautogui.press(TICKET_KEY)
    else:
        step(f"F2 是掃蕩券，點那一格（{sx},{sy}）使用")
        click_at(sx, sy)
    gift = wait_for("sweep_gift.png", timeout=6.0)
    if not gift:
        shot = dump_fail(f"win{idx:02d}_ticket")
        back_to_main()
        return MANUAL, ("按了掃蕩券但沒看到禮物視窗（可能券用完了），為了不多用一張今天不會再按；"
                        f"請自己看一下（{shot}）")
    mark_done("used", key)
    step("看到禮物視窗：掃蕩券用掉了，點一下關掉")
    safe_click(1)
    if not wait_until(lambda sc: find_one(sc, "sweep_gift.png") is None, 3.0):
        safe_click(1)
    back_to_main()
    return True, "副本掃蕩券已使用"


def lowest_redeem_btn():
    """畫面上最下面那個像「兌換」的按鈕（「查看」長得一樣，但在它上面）。"""
    btns = find_all(grab(), "redeem_btn.png")
    return max(btns, key=lambda b: b[1]) if btns else None


def do_redeem(idx):
    """輸入序號並按兌換。不管有沒有跳「領取成功」，按到就算做完。"""
    code = (REDEEM_CODE or "").strip()
    if not code:
        return True, "（沒有填序號，跳過兌換）"
    if REMEMBER_DONE and code in redeemed():
        return True, f"序號 {code} 這隻已經換過了（紀錄），跳過"

    step("打開「設置 → 遊戲設置」")
    if not open_settings():
        shot = dump_fail(f"win{idx:02d}_rd_open")
        back_to_main()
        return False, f"打不開遊戲設置（{shot}）"

    # 設置內容要拉到最下面才看得到「兌換獎勵」。
    # 拖曳要在內容區裡面、而且要靠左邊的文字欄：
    #   下面那排「回到登錄／保存設置」不能碰，中間的音量滑桿更不能碰（會改音量）。
    # 以前最多拉 6 次、而且第 6 次拉完沒再找就放棄：雷電畫面比較扁、每次捲得少，拉不到最下面。
    # 現在一直拉到「拖和滾輪都不動」才算到底，每次停下前都再找一次。
    btn = None
    bottom = False
    x = int(AREA_W * 0.40)
    y_from, y_to = int(AREA_H * 0.72), int(AREA_H * 0.47)
    # 一律先拉到最底再找：設置頁裡「冒險碼」的「查看」跟「兌換」是同一種淺藍小按鈕，
    # 邊拉邊找會在「兌換」還沒出現時，把「查看」當成「兌換」（筆電官方實際發生）。
    # 「兌換」在最底下、在「查看」下面，所以到底後有好幾個像的就選最下面那個。
    step("先把設置頁拉到最下面（「兌換」在最底下）")
    moved_once = False
    # 「有沒有動」只看設置面板的內容區：面板外面的遊戲畫面（人物、特效、鏡頭）一直在動，
    # 看整個畫面的話到底了也永遠是「有動」（筆電官方拉了 12 次停不下來）。
    # 實測：內容捲 5 像素差 10 以上；面板外整片都變了，內容區差 0.0。也等內容停下來才比（有慣性和回彈）。
    R = REDEEM_LIST_REGION

    def moved(a, b):
        d = list_diff(a, b, R)
        return changed(a, b) if d is None else d >= LIST_MOVE_TOL

    # 第二個起點：比較高的位置。拉到後面時「兌換獎勵」的輸入框會移到原本的起點，
    # 按在輸入框上拖不動（輸入框會吃掉拖曳），程式就以為到底了，其實「兌換」還被切在下面（筆電官方截圖）。
    alt_from, alt_to = int(AREA_H * 0.58), int(AREA_H * 0.42)
    for i in range(REDEEM_SKIP_DRAGS + REDEEM_MAX_DRAGS):
        before = list_settle(region=R)
        drag_line(x, y_from, x, y_to)
        label = f"往下拉第 {i + 1} 次"
        if moved(before, list_settle(region=R)):
            moved_once = True
            step(f"{label}：有動")
            continue
        before = list_settle(region=R)
        drag_line(x, alt_from, x, alt_to)
        if moved(before, list_settle(region=R)):
            moved_once = True
            step(f"{label}：原本的位置拉不動（可能壓到輸入框），換高一點的位置拉：有動")
            continue
        if moved_once:
            # 前面拉得動、這次拉不動 = 到底了（只會拉過頭彈一下）。
            # 不要再用滾輪：雷電的滾輪方向跟官方相反，會把清單往上捲，害程式以為還沒到底又一直拉。
            bottom = True
            step(f"{label}：沒動，已經到最下面了")
            break
        step(f"{label}：沒動，改用滾輪（第一下就拖不動，試試看滾輪）")
        # 拖不動就試滾輪（ROM 的滾輪方向是反的，正值才是往下）
        pyautogui.moveTo(AREA_X + x, AREA_Y + (y_from + y_to) // 2, duration=0.1)
        pyautogui.scroll(600)
        wait_stable(1.5)
        if not moved(before, list_settle(region=R)):
            bottom = True
            step("滾輪也沒動：已經拉到最下面了")
            break
    btns = find_all(grab(), "redeem_btn.png")
    btn = max(btns, key=lambda bb: bb[1]) if btns else None
    if btn:
        if len(btns) > 1:
            step(f"畫面上有 {len(btns)} 個長得像的按鈕（例如「查看」），選最下面那個")
        step("找到「兌換」按鈕")
    else:
        shot = dump_fail(f"win{idx:02d}_rd_btn")
        back_to_main()
        why = ("已經拉到最下面了還是找不到（模板可能對不上）" if bottom
               else f"拉了 {REDEEM_SKIP_DRAGS + REDEEM_MAX_DRAGS} 次還沒到底")
        return False, f"設置裡找不到「兌換」按鈕：{why}（{shot}）"

    bx, by = btn[0] + btn[2] // 2, btn[1] + btn[3] // 2
    step(f"點輸入框，輸入序號 {code}")
    click_at(bx, by + REDEEM_INPUT_DY, wait=1.2)   # 輸入框在按鈕正上方
    type_text(code)
    step("按「兌換」")
    btn2 = lowest_redeem_btn() or btn
    bar = input_bar_visible()
    click_box(btn2, wait=2.5)                      # 按兌換，會閃一個小視窗，不理它
    if bar:
        # 雷電：第一下只把下面的輸入列收起來（使用者實測），要再按一次才真的兌換
        step("第一下只把下方的輸入列收起來，再按一次「兌換」")
        nap(0.5)
        btn3 = lowest_redeem_btn() or btn2
        click_box(btn3, wait=2.5)
    nap(1.0)

    closed = False
    c = find_one(grab(), "settings_close.png")
    if c:
        click_box(c)
        closed = on_main() or back_to_main()
    if not closed:
        closed = back_to_main()
    if not closed:
        shot = dump_fail(f"win{idx:02d}_rd_close")
        return False, f"序號 {code} 已按兌換，但關不掉設置（{shot}）"
    mark_redeemed(code)
    return True, f"序號 {code} 已按兌換"


# ---------------------------------------------------------------------------
# 任務三：領取日常獎勵
# ---------------------------------------------------------------------------

def tab_dot_gone(tag):
    """這個分頁（daily／weekly）的紅點不見了嗎＝這頁沒東西可領了。看不出來就當作還在（照舊找）。"""
    d, w = tab_red_dots()
    return (d if tag == "daily" else w) is False


def claim_visible_list(tag):
    """把目前這個清單（日常或週常）裡所有黃色「領取」點掉，會往下捲找漏網的。回傳領了幾項。

    每領完一個、每次要往下捲之前，都看一下這個分頁的紅點：紅點消失＝都領完了，直接收工，
    不用再一路捲到底（使用者提的省時間做法）。
    """
    total = 0
    name = "日常" if tag == "daily" else "週常"

    def finished():
        if tab_dot_gone(tag):
            step(f"「{name}」分頁的紅點消失了：這頁都領完了，不用再往下找")
            return True
        return False

    for page in range(3):
        for _ in range(MAX_CLAIMS):
            screen = grab()
            btns = find_all(screen, "claim.png") + find_all(screen, "claim_all.png")
            if not btns:
                break
            btns.sort(key=lambda b: b[1])
            click_box(btns[0])
            safe_click(2)
            total += 1
            step(f"點第 {total} 個「領取」（{btns[0][0]},{btns[0][1]}），點空白處關獎勵視窗")
            if finished():
                return total
        if finished():
            return total
        if not scroll_down(thorough=(page == 0)):
            break
    if LIST_BOUNCES and not finished():
        # 第二頁的領取按鈕只能「拖完立刻點」，一次點一顆，點完清單會跳回去再來一次
        for _ in range(8):
            btn = drag_and_find("claim.png", want_visible=False) \
                or drag_and_find("claim_all.png", want_visible=False)
            if not btn:
                break
            click_box(btn)
            safe_click(2)
            total += 1
            step(f"拖完立刻點第 {total} 個「領取」")
    return total


def weekly_tab_point(screen=None):
    """「週常」分頁的中心：有模板用找的，沒有用校正的位置。"""
    screen = grab() if screen is None else screen
    if has("weekly_tab.png"):
        t = find_one(screen, "weekly_tab.png")
        if t:
            return t[0] + t[2] // 2, t[1] + t[3] // 2
    return WEEKLY_TAB


def tab_red_dots(screen=None):
    """日常、週常分頁右上角有沒有紅點 → (日常有, 週常有)。看不出來就 (None, None)。

    紅點在分頁文字右上方約 (+34, -16) 像素（工作區寬 800 時，官方雷電一樣）。
    實測：有紅點約 70 個紅色像素，沒有就是 0。
    """
    if not RED_DOT_SKIP:
        return None, None
    screen = grab() if screen is None else screen
    pt = weekly_tab_point(screen)
    if not pt:
        return None, None
    k = AREA_W / 800.0
    wx, wy = pt
    hsv = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
    h, s_, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    red = (((h <= 10) | (h >= 170)) & (s_ > 120) & (v > 140))

    def count(x0, x1):
        y0, y1 = max(0, int(wy - 40 * k)), max(0, int(wy + 2 * k))
        return int(red[y0:y1, max(0, int(wx + x0 * k)):max(0, int(wx + x1 * k))].sum())

    return count(-85, -30) >= 15, count(10, 60) >= 15


def do_claim(idx):
    """日常清單的「領取」全點掉；有抓「週常」分頁模板的話，切過去也領一遍。
    分頁沒有紅點就跳過那一頁（紅點 = 有東西可以領）。"""
    global LIST_SCROLLED, DAILY_OPEN_NOW
    if DAILY_OPEN_NOW and has("daily_panel.png") and find_one(grab(), "daily_panel.png"):
        step("日常面板還開著（剛做完委託），直接領取")
        LIST_SCROLLED = False
        scroll_to_top()                            # 剛剛找委託時清單被捲過了
    else:
        step("打開日常面板")
        if not open_daily():
            DAILY_OPEN_NOW = False
            return 0, f"領取時打不開日常（{dump_fail(f'win{idx:02d}_claim_open')}）"
    DAILY_OPEN_NOW = False

    dot_daily, dot_weekly = tab_red_dots()
    if dot_daily is False:
        step("日常分頁沒有紅點，沒東西可領，跳過")
        daily = 0
    else:
        daily = claim_visible_list("daily")
        step(f"日常分頁：領了 {daily} 項")
    weekly = None
    if CLAIM_WEEKLY and dot_weekly is False:
        step("週常分頁沒有紅點，沒東西可領，不用切過去")
        weekly = 0
    elif CLAIM_WEEKLY:
        step("切到「週常」分頁")
        tab = find_one(grab(), "weekly_tab.png") if has("weekly_tab.png") else None
        if tab:
            click_box(tab, wait=T_PANEL_MAX)       # 有模板就用模板
        else:
            click_at(WEEKLY_TAB[0], WEEKLY_TAB[1], wait=T_PANEL_MAX)   # 沒有就點固定位置
        # 切過去的週常清單不一定在最上面（會停在上次看的位置），不先捲回去會漏掉上面幾列（例：達納托斯之塔）
        LIST_SCROLLED = False                      # 換了一份清單，重新算
        step("週常清單先捲回最上面")
        scroll_to_top()
        weekly = claim_visible_list("weekly")
        step(f"週常分頁：領了 {weekly} 項")
    back_to_main()

    if weekly is None:
        return daily, f"領取 {daily} 項"
    return daily + weekly, f"領取 日常 {daily} 項、週常 {weekly} 項"


# ---------------------------------------------------------------------------
# 任務四：每日福利（簽到）
# ---------------------------------------------------------------------------

def bonus_state(timeout=8.0):
    """'claim' 可簽 / 'done' 已簽 / 'main' 根本沒打開 / None 不明。"""
    deadline = time.time() + timeout * max(0.5, SLOW)
    while time.time() < deadline:
        screen = grab()
        if find_one(screen, "bonus_claim.png"):
            return "claim"
        if find_one(screen, "bonus_done.png"):
            return "done"
        time.sleep(0.5)
    return "main" if on_main() else None


def do_bonus(idx):
    """熱點 → 每日福利 → 簽到。回傳 (簽到了嗎, 訊息)。"""
    if not has("hotspot.png"):
        return True, "（沒有 hotspot.png，跳過每日福利）"

    step("找主畫面上方的「熱點」")
    box = wait_for("hotspot.png", timeout=4.0)
    if not box:
        step("沒看到熱點，回主畫面再找一次")
        back_to_main()
        box = wait_for("hotspot.png", timeout=6.0)
    if not box:
        return False, f"找不到熱點（{dump_fail(f'win{idx:02d}_hotspot')}）"
    step(f"點熱點（分數 {box[4]:.2f}），找「每日福利」")
    click_box(box, wait=T_PANEL_MAX)

    entry = wait_for("bonus_row.png", timeout=5.0)
    if not entry:
        shot = dump_fail(f'win{idx:02d}_bonus_menu')   # 先截圖，再回主畫面
        back_to_main()
        return False, f"熱點選單裡找不到每日福利（{shot}）"
    step("點「每日福利」")
    click_box(entry, "bonus_row.png", wait=T_PANEL_MAX)

    state = bonus_state()
    step("福利畫面：" + {"claim": "可以簽到", "done": "今天已經簽過了",
                         "main": "又回到主畫面（沒進去）"}.get(state, "看不出狀態"))
    if state == "done":
        back_to_main()
        return True, "每日福利今天已簽到"
    if state == "main":
        return False, "每日福利進不去（日常可能未滿 3 項）"
    if state is None:
        shot = dump_fail(f'win{idx:02d}_bonus')   # 先截圖，再回主畫面
        back_to_main()
        return False, f"每日福利畫面不明（{shot}）"

    used = None
    ok = False
    for attempt in range(3):
        btn = find_one(grab(), "bonus_claim.png")
        if not btn:
            break
        used = btn[5]
        step(f"按「簽到」第 {attempt + 1} 次，同位置再點一下關獎勵視窗")
        click_box(btn)
        click_box(btn)                         # 同位置再點一下關獎勵視窗
        safe_click(1)
        if bonus_state(timeout=6.0) == "done":
            step("狀態變成已簽到")
            ok = True
            break
    if not ok:
        dump_fail(f"win{idx:02d}_bonus_after")
    back_to_main()
    if ok:
        return True, "每日福利簽到完成"
    return False, f"按了簽到 {attempt + 1} 次但狀態沒變（認到的按鈕：{used}）"


# ---------------------------------------------------------------------------
# 單一帳號
# ---------------------------------------------------------------------------

class _Disconnected(Exception):
    """帳號斷線，中止這隻剩下的任務。"""


# ---------------------------------------------------------------------------
# 一鍵上架（交易所：過期貨物重新上架）
# ---------------------------------------------------------------------------

def relist_button(timeout=3.0):
    """「一鍵上架」按鈕還在嗎（只有有過期貨物時才會出現）。上架中按鈕會變淡，多等一下才算數。"""
    return wait_for("relist_btn.png", timeout=timeout)


def do_relist(idx):
    """快捷列第 1 格開交易所 →「我要出售」→ 一直按「一鍵上架」→「是」，直到按鈕消失。

    遊戲說會全部上架，但常常一次只上架一兩件就停，所以要重複按。最多 RELIST_MAX 次。
    """
    for name in ("exchange_sell_tab.png", "relist_btn.png", "relist_yes.png"):
        if not has(name):
            return False, f"一鍵上架的模板還沒抓齊（缺 {name}），請到校正分頁「一鍵上架」那組"
    if not EXCHANGE_SLOT:
        return False, "快捷列上「交易所」那一格的位置還沒校正"

    step(f"點快捷列的交易所（{EXCHANGE_SLOT[0]},{EXCHANGE_SLOT[1]}）")
    click_at(EXCHANGE_SLOT[0], EXCHANGE_SLOT[1], wait=T_PANEL_MAX)
    tab = wait_for("exchange_sell_tab.png", timeout=8.0)
    if not tab:
        shot = dump_fail(f"win{idx:02d}_relist_open")
        back_to_main()
        return False, f"打不開交易所，或找不到「我要出售」（{shot}）"
    step("點「我要出售」")
    click_box(tab, wait=T_PANEL_MAX)

    rounds = 0
    while True:
        btn = relist_button(timeout=4.0)
        if not btn:
            nap(1.5)                               # 再確認一次，免得剛好在轉圈圈
            btn = relist_button(timeout=2.0)
        if not btn:
            break
        if rounds >= RELIST_MAX:
            shot = dump_fail(f"win{idx:02d}_relist_left")
            back_to_main()
            return MANUAL, (f"一鍵上架按了 {RELIST_MAX} 次還有過期貨物沒上架完"
                            f"（可能資金不足，請自己看一下）（{shot}）")
        rounds += 1
        step(f"按「一鍵上架」第 {rounds} 次")
        click_box(btn, wait=T_PANEL_MAX)
        yes = wait_for("relist_yes.png", timeout=5.0)
        if yes:
            step("確認視窗按「是」")
            click_box(yes, wait=T_PANEL_MAX)
        else:
            step("沒看到確認視窗（可能直接開始上架了）")
        step("等上架跑完")
        wait_stable(4.0)
        nap(1.0)

    step("「一鍵上架」按鈕不見了：過期的都上架完了" if rounds else "沒有「一鍵上架」按鈕：沒有過期貨物")
    back_to_main()
    if not rounds:
        return True, "沒有過期貨物要上架"
    return True, f"一鍵上架按了 {rounds} 次，全部上架完成"


ALL_TASKS = ("pet", "comm", "claim", "bonus", "dungeon", "ticket", "redeem", "relist")
MAIN_TASKS = ("pet", "comm", "claim", "bonus", "dungeon", "ticket", "redeem")   # 控制台勾選的（一鍵上架在自己的分頁）

# ---------------------------------------------------------------------------
# 今天做完的紀錄（早上 6 點換日）
# ---------------------------------------------------------------------------
# 認帳號用「這一次開著的遊戲」：種類｜名字｜程式編號（pid）。遊戲重開 pid 就變，當成新的重新檢查，
# 不會因為官方用帳號切換工具換了一隻、還沿用上一隻的紀錄而漏做。
# 唯一例外：在遊戲裡手動登出換帳號但沒重開遊戲 → 分頁上按「清除今天的紀錄」。
STATE_PATH = os.path.join(BASE_DIR, "daily_state.json")
RESET_HOUR = 6
RECORDABLE = ("pet", "comm", "bonus", "dungeon")   # 領取不記（之後還會冒出新的）；一鍵上架不記（貨物會再過期）
CUR_ACCOUNT = ""
UNSURE = False                   # 任務說「完成」但其實不確定有沒有做對（例：寵物打工標題沒認出來）→ 不記成今天做完


def day_key():
    """遊戲的「今天」：早上 6 點才換日。"""
    return time.strftime("%Y-%m-%d", time.localtime(time.time() - RESET_HOUR * 3600))


def account_key(hwnd):
    try:
        import win32process
        pid = win32process.GetWindowThreadProcessId(hwnd)[1]
    except Exception:
        pid = 0
    return f"{window_kind(hwnd)}|{window_label(hwnd)}|{pid}"


def _state():
    st = _read_json(STATE_PATH)
    if st.get("day") != day_key():                 # 過了早上 6 點：今天的紀錄清掉（兌換紀錄留著）
        st = {"day": day_key(), "done": {}, "redeem": st.get("redeem", {})}
    st.setdefault("done", {})
    st.setdefault("redeem", {})
    return st


def _save_state(st):
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=1)
    except Exception as e:
        print(f"  （存今天的紀錄失敗：{e}）")


def done_today(key=None):
    return set(_state()["done"].get(key or CUR_ACCOUNT, []))


def mark_done(task, key=None):
    st = _state()
    lst = st["done"].setdefault(key or CUR_ACCOUNT, [])
    if task not in lst:
        lst.append(task)
        _save_state(st)


def redeemed(key=None):
    return set(_state()["redeem"].get(key or CUR_ACCOUNT, []))


def mark_redeemed(code, key=None):
    st = _state()
    lst = st["redeem"].setdefault(key or CUR_ACCOUNT, [])
    if code not in lst:
        lst.append(code)
        if len(st["redeem"]) > 300:                # 舊的遊戲程式編號留太多就丟掉前面的
            for k in list(st["redeem"])[:-300]:
                del st["redeem"][k]
        _save_state(st)


def clear_today():
    """清掉今天「做完了」的紀錄（兌換序號的紀錄不清）。"""
    st = _state()
    st["done"] = {}
    _save_state(st)
TASK_LABELS = {"pet": "寵物打工", "comm": "任務委託板", "dungeon": "副本掃蕩", "ticket": "副本掃蕩券",
               "claim": "領取獎勵", "bonus": "每日福利", "redeem": "兌換序號", "relist": "一鍵上架"}
DEFAULT_ON = {"pet", "comm", "dungeon", "claim", "bonus", "ticket"}     # 兌換序號預設不勾


LAST_NOTES = ({}, [])           # 最近一次 do_account：(每項任務的結果, 其他附註)


def _remember_notes(by_task, notes):
    global LAST_NOTES
    task_notes = set(by_task.values())
    LAST_NOTES = (dict(by_task), [x for x in notes if x not in task_notes])


def merge_retry(first, second):
    """把補跑的結果合進第一次的總結。

    原本失敗、補跑成功 → 只留綠色 ✓，後面註明（補跑後成功）；補跑也失敗 → ✗（補跑也失敗）。
    原本就成功、只是跟著重跑的（例如補完寵物順便再領一次）→ 留原本的；領取有多領到才註明。
    """
    import re as _re
    (t1, x1), (t2, x2) = first, second
    merged = dict(t1)
    for k, note2 in t2.items():
        note1 = t1.get(k, "")
        if not note1:
            merged[k] = note2
        elif note1.startswith("✗"):
            merged[k] = note2 + ("（補跑後成功）" if note2.startswith("✓")
                                 else "（補跑也失敗）" if note2.startswith("✗") else "")
        elif k == "claim":
            more = sum(int(v) for v in _re.findall(r"(\d+) 項", note2))
            if more:
                merged[k] = note1 + f"（補跑又領了 {more} 項）"
    extras = x1 + [x for x in x2 if x not in x1]
    return "；".join([merged[k] for k in ALL_TASKS if k in merged] + extras), (merged, extras)


def do_account(idx, hwnd, tasks=None):
    """tasks：要做哪幾項，例如 {"pet", "comm"}。None = 全部。"""
    global LIST_BOUNCES, CUR_HWND, CUR_ACCOUNT, KEEP_DAILY, DAILY_OPEN_NOW
    LIST_BOUNCES = False                           # 每隻帳號重新判斷清單會不會彈回
    CUR_HWND = hwnd
    CUR_ACCOUNT = account_key(hwnd)
    DAILY_OPEN_NOW = False
    _remember_notes({}, [])                        # 先清掉，免得一開始就失敗時沿用上一個帳號的結果
    tasks = set(DEFAULT_ON) if tasks is None else set(tasks)
    KEEP_DAILY = "claim" in tasks                  # 委託做完直接接著領取，不用關掉日常面板再開
    if not ENABLE_BONUS:
        tasks.discard("bonus")
    orig = get_rect(hwnd)
    notes = []
    by_task = {}                                   # 每項任務自己的結果（補跑時拿來合併總結）
    flags = {}
    try:
        normalize_window(hwnd)
        if on_main():
            wake_up()                              # 省電模式：先點一下叫醒

        if not on_main() and not back_to_main():
            shot = dump_fail(f"win{idx:02d}_start")
            if disconnected():
                return False, f"可能斷線了，這隻跳過（{shot}）", {}
            return False, f"卡在不明畫面、回不到主畫面，可能斷線（{shot}）", {}

        def run(key, fn):
            """跑一項任務。出錯只記這一項，不影響後面的。"""
            print(f"  【{TASK_LABELS[key]}】", flush=True)
            if REMEMBER_DONE and key in RECORDABLE and key in done_today():
                msg = f"{TASK_LABELS[key]}今天已經做完了（紀錄），跳過"
                print(f"    → 完成：{msg}", flush=True)
                flags[key] = True
                notes.append("✓" + msg)
                by_task[key] = "✓" + msg
                return
            global UNSURE
            UNSURE = False
            try:
                moved = ensure_window()            # 先確認視窗還在原位、在最上面
                if moved:
                    notes.append(f"（{TASK_LABELS[key]}開始前視窗{moved}，已拉回）")
                    if not on_main():
                        back_to_main()
                ok, msg = fn(idx)
            except (pyautogui.FailSafeException, Aborted):
                raise
            except Exception as e:
                ok, msg = False, f"{TASK_LABELS[key]}發生錯誤：{e}"
                try:
                    back_to_main()             # 盡量把畫面收乾淨，讓下一項能接著做
                except Exception:
                    pass
            manual = (ok == MANUAL)
            if ok is True and key in RECORDABLE:
                if UNSURE:
                    step("這次不確定有沒有做對，不記成今天做完，下次重跑會再做一次")
                else:
                    mark_done(key)                 # 今天做完了，同一天重跑就跳過
            print(f"    → {'要手動處理' if manual else '完成' if ok else '失敗'}：{msg}", flush=True)
            if key != "claim":                 # 領取不影響成敗判定
                flags[key] = bool(ok)          # 要手動處理的不算失敗，也不補跑
            # 總結裡每一項前面標 ✓／✗／⚠，GUI 照這個分別上色（綠／紅／黃）
            notes.append(("⚠" if manual else "✓" if ok else "✗") + msg)
            by_task[key] = notes[-1]
            if not ok and disconnected():
                notes.append("偵測到斷線畫面，這隻剩下的不做了")
                raise _Disconnected()

        if "pet" in tasks:
            run("pet", do_pet_work)
        if "comm" in tasks:
            run("comm", do_commission)
        if "claim" in tasks:
            run("claim", lambda i: (True, do_claim(i)[1]))
        if "bonus" in tasks:
            run("bonus", do_bonus)
        if "dungeon" in tasks:                     # 副本放最後：跟日常獎勵、簽到都無關
            run("dungeon", do_dungeon)
        if "ticket" in tasks:
            run("ticket", do_ticket)
        if "redeem" in tasks:
            run("redeem", do_redeem)
        if "relist" in tasks:
            run("relist", do_relist)

        _remember_notes(by_task, notes)
        return all(flags.values()) if flags else True, "；".join(notes), flags

    except (pyautogui.FailSafeException, Aborted):
        raise
    except _Disconnected:
        _remember_notes(by_task, notes)
        return False, "；".join(notes), flags
    except Exception as e:
        return False, "；".join(notes + [f"發生錯誤：{e}"]), flags
    finally:
        CUR_HWND = None
        try:
            move_window(hwnd, *orig)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 指令
# ---------------------------------------------------------------------------

ALL_TEMPLATES = [
    "daily.png", "commission_row.png", "quick_complete.png", "close_x.png",
    "done_stamp.png", "claim.png", "claim_all.png", "back_btn.png",
    "pet_row.png", "pet_gift.png", "pet_title.png", "row_done.png",
    "hotspot.png", "bonus_row.png", "bonus_claim.png", "bonus_done.png",
    "main_mark.png", "daily_panel.png", "disconnect.png",
    "dungeon_panel.png", "fable_row.png", "dungeon_title.png", "lv20_tab.png",
    "sweep_btn.png", "sweep_disabled.png", "playtime_label.png",
    "settings_game.png", "redeem_btn.png", "settings_close.png", "no_time_toast.png",
    "dead_btn.png", "weekly_tab.png",
]


def _with_window(n, fn):
    """把第 n 個視窗搬到工作位置，跑 fn，再還原。"""
    hwnds = find_windows()
    if not (1 <= n <= len(hwnds)):
        print(f"目前只有 {len(hwnds)} 個視窗")
        return
    hwnd = hwnds[n - 1]
    orig = get_rect(hwnd)
    try:
        normalize_window(hwnd)
        print(f"=== 視窗 {n} ===")
        fn(n)
    except Aborted:
        print("已中止")
    finally:
        move_window(hwnd, *orig)


def cmd_pet(n=1):
    _with_window(n, lambda i: print("  " + do_pet_work(i)[1]))


def cmd_bonus(n=1):
    _with_window(n, lambda i: print("  " + do_bonus(i)[1]))


def cmd_snap():
    os.makedirs(SHOT_DIR, exist_ok=True)
    hwnds = find_windows()
    print(f"找到 {len(hwnds)} 個 {WINDOW_TITLE} 視窗")
    for i, hwnd in enumerate(hwnds, 1):
        orig = get_rect(hwnd)
        normalize_window(hwnd)
        path = os.path.join(SHOT_DIR, f"win{i:02d}.png")
        imwrite(path, grab())
        print(f"  已存 {path}")
        move_window(hwnd, *orig)


def cmd_dgtest(n=1):
    """副本分頁列診斷：各種捲動方法各試一次，每次存圖並印有沒有動。"""
    def run(i):
        os.makedirs(SHOT_DIR, exist_ok=True)
        opened, why = open_dungeon()
        if not opened:
            print(f"  打不開副本面板：{why}"); return
        if not select_fable():
            print("  找不到狂想寓言"); return
        y = DUNGEON_TAB_Y
        x0, x1 = strip_hex_x(), int(AREA_W * STRIP_DRAG_END)
        imwrite(os.path.join(SHOT_DIR, "strip_0.png"), grab())
        print(f"  已存 strip_0.png（初始）；拖曳起點 ({x0}, {y})，應該壓在某顆六角形正中央")

        def wheel(v):
            pyautogui.moveTo(AREA_X + (x0 + x1) // 2, AREA_Y + y)
            pyautogui.scroll(v)
            wait_stable(1.5)

        def keys(k, times):
            for _ in range(times):
                pyautogui.press(k)
                time.sleep(0.4)
            wait_stable(1.5)

        tests = [
            ("慢拖（按在六角形上）", lambda: drag_line(x0, y, x1, y, steps=26, hold=0.04)),
            ("快甩（六角形列）", lambda: flick(x0, y, x1, y)),
            ("快甩（Lv 字那列）", lambda: flick(x0, y + 30, x1, y + 30)),
            ("快甩（六角形上方空白）", lambda: flick(x0, y - 22, x1, y - 22)),
            ("慢拖（Lv 字那列）", lambda: drag_line(x0, y + 30, x1, y + 30)),
            ("慢拖（六角形上方空白）", lambda: drag_line(x0, y - 22, x1, y - 22)),
            ("滾輪-", lambda: wheel(-480)),
            ("滾輪+", lambda: wheel(480)),
            ("鍵盤 ← ×3", lambda: keys("left", 3)),
            ("鍵盤 A ×3", lambda: keys("a", 3)),
        ]
        for k, (name, fn) in enumerate(tests, 1):
            before = grab()
            fn()
            after = grab()
            imwrite(os.path.join(SHOT_DIR, f"strip_{k}.png"), after)
            yy = DUNGEON_TAB_Y
            band_a = before[max(0, yy - 40):yy + 45, int(AREA_W * 0.30):int(AREA_W * 0.95)]
            band_b = after[max(0, yy - 40):yy + 45, int(AREA_W * 0.30):int(AREA_W * 0.95)]
            diff = float(np.mean(cv2.absdiff(band_a, band_b))) if band_a.shape == band_b.shape else -1
            print(f"  {name}：{'有動' if strip_changed(before, after) else '沒動'}"
                  f"（分頁列差異 {diff:.2f}）　→ strip_{k}.png")
        back_to_main()
    _with_window(n, run)


def cmd_scrolltest(n=1):
    def run(i):
        os.makedirs(SHOT_DIR, exist_ok=True)
        if not open_daily():
            print("  打不開日常")
            return
        for k in range(3):
            path = os.path.join(SHOT_DIR, f"scroll_{k}.png")
            imwrite(path, grab())
            moved = scroll_down()
            print(f"  已存 {path}   往下拖 → {'有動' if moved else '沒動（到底了）'}")
        back_to_main()
    _with_window(n, run)


def cmd_match(fname=None):
    imgs = [fname] if fname else sorted(
        f for f in os.listdir(SHOT_DIR) if f.startswith("scroll_"))
    if not imgs:
        print("沒有可測的圖片")
        return
    print(f"門檻 {MATCH_THRESHOLD}\n")
    for im in imgs:
        screen = imread(os.path.join(SHOT_DIR, im))
        if screen is None:
            print(f"讀不到 {im}")
            continue
        print(f"--- {im} ---")
        hits = {}
        for n in ALL_TEMPLATES:
            vs = template_variants(n)
            if not vs:
                print(f"     {n:20s} 還沒裁")
                continue
            best, bestv = 0.0, None
            for v in vs:
                t = load_template(v)
                if screen.shape[0] < t.shape[0] or screen.shape[1] < t.shape[1]:
                    continue
                m = float(cv2.matchTemplate(screen, t, cv2.TM_CCOEFF_NORMED).max())
                if m > best:
                    best, bestv = m, v
            found = find_all(screen, n)
            if found:
                hits[n] = found
            print(f"  {'OK' if found else '  '} {n:20s} 最高分 {best:.2f}"
                  f"（{bestv}）  找到 {len(found)} 個")
        names = list(hits)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                if any(abs(x[0] - y[0]) < max(x[2], y[2]) * 0.6 and
                       abs(x[1] - y[1]) < max(x[3], y[3]) * 0.6
                       for x in hits[a] for y in hits[b]):
                    print(f"\n  ** 警告：{a} 和 {b} 指到同一個位置，其中一張裁錯了 **")
        print()


def _check_templates(tasks, who=""):
    """目前載入的那一套模板夠不夠跑這些任務。不夠就印出缺什麼、回傳 False。"""
    tag = f"【{who}】" if who else ""
    need = []
    if not has("daily.png") and not has("main_mark.png"):
        print(f"{tag}缺少模板：daily.png 或 main_mark.png 至少要有一張，程式才知道什麼是主畫面")
        return False
    if "comm" in tasks:
        need += ["commission_row.png", "quick_complete.png", "close_x.png", "done_stamp.png"]
    if "pet" in tasks:
        need += ["pet_gift.png"]
    if "dungeon" in tasks:
        need += ["dungeon_panel.png", "fable_row.png", "sweep_btn.png", "playtime_label.png"]
    if "redeem" in tasks:
        need += ["settings_game.png", "redeem_btn.png"]
    if "claim" in tasks:
        need += ["claim.png"]
    if "bonus" in tasks and ENABLE_BONUS:
        need += ["hotspot.png", "bonus_row.png", "bonus_done.png"]
    missing = [f for f in need if not has(f)]
    if missing:
        print(f"{tag}缺少模板：" + "、".join(missing))
        print(f"尋找的資料夾：{TEMPLATE_DIR}")
        return False
    for f in ["pet_gift.png", "claim.png", "hotspot.png",
              "bonus_row.png", "bonus_claim.png", "bonus_done.png"]:
        if not has(f):
            print(f"{tag}提醒：沒有 {f}，相關步驟會跳過或用備援方式")
    if "pet" in tasks and not has("pet_title.png"):
        print(f"{tag}提醒：沒有 pet_title.png，無法確認有沒有真的進到打工畫面，"
              "建議到校正分頁抓一張（打工畫面最上面的「寵物打工」標題）")
    if SLOW != 1.0:
        print(f"{tag}（動作放慢 ×{SLOW:g}，等待時間都拉長）")
    return True


def kind_of(hwnd):
    """跑的時候這個視窗要用哪一套設定。自動模式看視窗身分；固定模式就是目前那一套。"""
    return window_kind(hwnd) if RUN_MODE == AUTO_MODE else ACTIVE_PROFILE


def win_title(n, hwnd, pad=False):
    """紀錄、總結裡的視窗名稱。自動模式多標「官方／雷電 + 名字」。pad：總結用，編號補成兩格對齊。"""
    base = f"視窗 {n:2d}" if pad else f"視窗 {n}"
    if RUN_MODE != AUTO_MODE:
        return base
    return f"{base}（{window_kind(hwnd)} {window_label(hwnd)}）"


def cmd_run(only=None, tasks=None, windows=None):
    """only：單一視窗編號；windows：多個編號的清單；tasks：要做的任務集合。"""
    tasks = set(DEFAULT_ON) if tasks is None else set(tasks)
    home = ACTIVE_PROFILE                          # 跑完切回來（校正、設定頁編輯的那一套）
    try:
        _cmd_run(only, tasks, windows)
    finally:
        use_profile(home)


def _cmd_run(only, tasks, windows):
    hwnds = find_windows()
    if not hwnds:
        if RUN_MODE == AUTO_MODE:
            print("找不到遊戲視窗（官方和雷電都沒有）")
        else:
            print(f"找不到「{WINDOW_TITLE}」視窗")
        return
    if only:
        windows = [only]
    if windows:
        bad = [n for n in windows if not (1 <= n <= len(hwnds))]
        if bad:
            print(f"視窗編號 {bad} 不存在，目前只有 {len(hwnds)} 個")
            return
        picked = [(n, hwnds[n - 1]) for n in windows]
    else:
        picked = list(enumerate(hwnds, 1))

    # 每一種要跑的視窗，各自檢查那一套模板夠不夠
    kinds = sorted({kind_of(h) for _, h in picked}, key=lambda k: PROFILE_NAMES.index(k))
    for k in kinds:
        use_profile(k)
        if not _check_templates(tasks, k if RUN_MODE == AUTO_MODE else ""):
            return

    for n, hwnd in picked:
        x, y, w, h = get_rect(hwnd)
        print(f"  {win_title(n, hwnd, pad=True)}：「{win32gui.GetWindowText(hwnd)}」 位置 ({x}, {y}) 大小 {w}x{h}")
    print(f"\n準備處理 {len(picked)} 個視窗，任務："
          + "、".join(TASK_LABELS[t] for t in ALL_TASKS if t in tasks) + "，3 秒後開始")
    print(f"（每個帳號的「寵物手冊」要放在 {PET_KEY.upper()} 快捷鍵；"
          "跑的時候不要碰滑鼠鍵盤；滑鼠甩到左上角可中止）")
    for i in (3, 2, 1):
        print(f"  {i}...")
        time.sleep(1)

    t0 = time.time()
    results = []
    try:
        for n, hwnd in picked:
            if ABORT:
                print("\n已中止")
                break
            t1 = time.time()
            use_profile(kind_of(hwnd))             # 這個視窗用它自己那一套設定
            print(f"\n=== {win_title(n, hwnd)} ===")
            ok, msg, flags = do_account(n, hwnd, tasks)
            print(f"  {msg}  [{time.time() - t1:.0f} 秒]")
            results.append([n, ok, msg, flags, hwnd, LAST_NOTES])
    except Aborted:
        print("\n已中止，視窗已還原。")
    if not results:
        return

    # --- 補跑：失敗的帳號只補失敗的那幾項，一次為限 ---
    if RETRY_FAILED and not ABORT:
        redo = [r for r in results if not r[1]]
        if redo:
            print(f"\n===== 補跑 {len(redo)} 個失敗的帳號 =====")
        for r in redo:
            if ABORT:
                break
            n, _, msg, flags, hwnd = r[:5]
            if "斷線" in msg:
                print(f"\n=== {win_title(n, hwnd)}：可能斷線，不補跑 ===")
                continue
            again = {k for k, v in flags.items() if not v} or set(tasks)
            if "comm" in again or "pet" in again:
                again |= {"claim"}                 # 補做完會多出可領的獎勵
                if "bonus" in tasks:
                    again |= {"bonus"}             # 日常補滿 3 項後簽到才進得去
            t1 = time.time()
            use_profile(kind_of(hwnd))
            print(f"\n=== {win_title(n, hwnd)}（補跑：{'、'.join(TASK_LABELS[k] for k in ALL_TASKS if k in again)}）===")
            try:
                ok2, msg2, flags2 = do_account(n, hwnd, again)
            except Aborted:
                print("\n已中止，視窗已還原。")
                break
            print(f"  {msg2}  [{time.time() - t1:.0f} 秒]")
            merged = dict(flags); merged.update(flags2)
            r[1] = all(merged.values()) if merged else True
            if r[5][0] or LAST_NOTES[0]:
                r[2], r[5] = merge_retry(r[5], LAST_NOTES)   # 總結只留最後的結果，不再出現補跑前的紅字
            else:
                r[2] = msg + "｜補跑→" + msg2              # 兩次都還沒開始做任務就失敗（例如卡在不明畫面）
            r[3] = merged

    print("\n========== 總結 ==========")
    good = sum(r[1] for r in results)
    for n, ok, msg, _, hwnd, _ in results:
        print(f"{'OK ' if ok else '!! '}{win_title(n, hwnd, pad=True)}：{msg}")
    print(f"\n{good}/{len(results)} 個帳號全部完成，共 {time.time() - t0:.0f} 秒")
    todo = sum(1 for r in results if "⚠" in r[2])
    if todo:
        print(f"另外 {todo} 個帳號有 ⚠ 要你手動處理（看上面黃色那幾項）")


if __name__ == "__main__":
    enable_dpi_awareness()
    start_stop_hotkey()
    print(f"（跑的過程中按 {STOP_KEY.upper()} 可以立刻停止）")
    args = sys.argv[1:]
    cmd = args[0] if args else "run"
    num = next((int(a) for a in args if a.isdigit()), None)
    png = next((a for a in args[1:] if a.endswith(".png")), None)

    {"snap": lambda: cmd_snap(),
     "scrolltest": lambda: cmd_scrolltest(num or 1),
     "dgtest": lambda: cmd_dgtest(num or 1),
     "match": lambda: cmd_match(png),
     "pet": lambda: cmd_pet(num or 1),
     "bonus": lambda: cmd_bonus(num or 1),
     "test": lambda: cmd_run(only=num or 1),
     "run": lambda: cmd_run(only=num),
     }.get(cmd, lambda: cmd_run(only=num))()
