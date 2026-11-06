#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ROM Classic 組隊輪替
====================

讓小號自己申請進隊長的隊伍，今日戰鬥次數打滿 10000 就自己離隊，
把位置讓給下一隻。程式每隔幾分鐘巡一輪，直到所有小號都打滿。

每隻小號每輪做的事：
    按 T 看隊伍狀態
      ├─ 看到「離開隊伍」= 在隊裡 → 點頭像看戰鬥次數
      │       ├─ 紅字 10000/10000 → 離開隊伍 → 標記完成
      │       └─ 沒滿 → 什麼都不做
      └─ 看到「創建隊伍」= 不在隊裡 → 點頭像看戰鬥次數
              ├─ 已經滿了 → 標記完成
              └─ 沒滿，而且隊伍有空位 → 按 O → ❤ 分頁 → 第一個好友 → 旗子申請

「隊伍有空位」是程式自己算的：隊伍上限 6 減掉隊長 = 5 隻小號，
目前在隊裡的隻數由每輪巡查得知。圖上的「可申請 5/5」看起來是每日申請次數上限，
所以絕對不能沒空位還一直申請。

前置條件：
    * 小號跟隊長在同一張地圖（這程式不會移動角色）
    * 每隻小號的好友「❤ 我的最愛」裡只放隊長一個人
    * 校正分頁抓好四張模板和四個位置（見 GUI「⑤ 組隊輪替」）

用法：
    python rom_party.py                 # 用 config.json 的設定持續巡邏
    python rom_party.py once            # 只巡一輪就停，用來測試
    python rom_party.py once 3          # 只看第 3 個視窗一次
"""

import sys
import time

import pyautogui

import rom_daily as rd
from rom_daily import (back_to_main, click_at, click_box, find_one, grab, has,
                       wait_for, wait_stable, wait_until, dump_fail, on_main)

# ---------------------------------------------------------------------------
# 設定（config.json 有寫就蓋掉）
# ---------------------------------------------------------------------------

__version__ = "2026.11.05n"

PARTY_KEY = "t"                  # 隊伍面板
FRIEND_KEY = "o"                 # 好友面板
PARTY_SIZE = 6                   # 隊伍上限（含隊長）
LEADER_WINDOW = 0                # 隊長是第幾個視窗；0 = 隊長不在這台電腦上
ALT_WINDOWS = None               # 小號視窗編號清單；None = 除了隊長以外全部
INTERVAL_MIN = 5.0               # 每輪之間隔幾分鐘

# 以下位置都是相對工作視窗左上角，數字是依截圖粗估的，請用 GUI 校正確認
P_AVATAR = (45, 75)              # 左上角自己的頭像
P_FAV_TAB = (553, 84)            # 好友面板的 ❤ 分頁
P_FRIEND_FIRST = (511, 147)      # ❤ 分頁第一個好友的頭像
P_APPLY_FLAG = (393, 224)        # 好友小視窗裡的旗子（申請入隊）
P_PARTY_BTN = None               # 主畫面上方「隊伍」按鈕；T 沒反應時改點它（模擬器用）
P_MORE_BTN = None                # 主畫面上方「更多」按鈕；沒快捷鍵時好友藏在它底下
P_FRIEND_BTN = None              # 「更多」展開後的「好友」按鈕；沒快捷鍵時改點它

# 燃料輪替（鐵匠每天 2000 燃料，三隻角色輪流進打手的隊伍吸）
FUEL_MAX = 5                     # 同時最多幾隻在吸（隊伍 6 人含打手）
FUEL_GAP = 20.0                  # 同一個視窗至少隔幾秒才再看一次
BAG_KEY = "b"                    # 包包（官方）
P_CHAR_SLOTS = [None, None, None]  # 選角畫面左邊 3 個頭像（第 1 個是本尊）
P_CHAT_OPEN = None               # 主畫面左下角的對話框
P_BAG_BTN = None                 # 主畫面上方「包包」按鈕（沒快捷鍵時）
P_BAG_FAV = None                 # 包包裡的愛心分頁

# 模板：count_full.png 紅字 10000/10000、leave_party.png 離開隊伍、
#       create_party.png 創建隊伍、confirm_ok.png 綠色確定

STATE_WAIT, STATE_IN, STATE_DONE, STATE_ERR = "等待入隊", "隊伍中", "已打滿", "異常"


def _load():
    """組隊的設定在共用 config；四個位置在目前環境的 config。"""
    global PARTY_KEY, FRIEND_KEY, PARTY_SIZE, LEADER_WINDOW, ALT_WINDOWS, INTERVAL_MIN
    global P_AVATAR, P_FAV_TAB, P_FRIEND_FIRST, P_APPLY_FLAG, P_PARTY_BTN, P_FRIEND_BTN, P_MORE_BTN
    global FUEL_MAX, FUEL_GAP, BAG_KEY, P_CHAR_SLOTS, P_CHAT_OPEN, P_BAG_BTN, P_BAG_FAV
    shared = rd._read_json(rd.SHARED_CONFIG_PATH)
    FUEL_MAX = int(shared.get("fuel_max", 5))
    FUEL_GAP = float(shared.get("fuel_gap", 20.0))
    BAG_KEY = str(shared.get("bag_key", "b"))
    PARTY_KEY = str(shared.get("party_key", "t"))
    FRIEND_KEY = str(shared.get("friend_key", "o"))
    PARTY_SIZE = int(shared.get("party_size", 6))
    LEADER_WINDOW = int(shared.get("party_leader_window", 0))
    INTERVAL_MIN = float(shared.get("party_interval_min", 5.0))
    ALT_WINDOWS = [int(n) for n in shared["party_alt_windows"]] \
        if shared.get("party_alt_windows") else None

    prof = rd._read_json(rd.CONFIG_PATH)
    defaults = {"party_avatar": (45, 75), "party_fav_tab": (553, 84),
                "party_friend_first": (511, 147), "party_apply_flag": (393, 224),
                "party_btn": None, "friend_btn": None, "more_btn": None}
    if rd.ACTIVE_PROFILE != "官方":            # 官方以外的環境沒有可信的預設座標
        defaults = {k: None for k in defaults}
    for key, name in (("party_avatar", "P_AVATAR"), ("party_fav_tab", "P_FAV_TAB"),
                      ("party_friend_first", "P_FRIEND_FIRST"),
                      ("party_apply_flag", "P_APPLY_FLAG"),
                      ("party_btn", "P_PARTY_BTN"), ("friend_btn", "P_FRIEND_BTN"),
                      ("more_btn", "P_MORE_BTN")):
        val = prof.get(key) or defaults[key]
        globals()[name] = tuple(val) if val else None
    P_CHAR_SLOTS = [tuple(prof[k]) if prof.get(k) else None for k in ("char_slot_1", "char_slot_2", "char_slot_3")]
    P_CHAT_OPEN = tuple(prof["chat_open"]) if prof.get("chat_open") else None
    bag = prof.get("bag_btn") or ((611, 45) if rd.ACTIVE_PROFILE == "雷電" else None)   # 雷電上方「包包」照截圖量的
    P_BAG_BTN = tuple(bag) if bag else None
    P_BAG_FAV = tuple(prof["bag_fav_tab"]) if prof.get("bag_fav_tab") else None


_load()


# ---------------------------------------------------------------------------
# 三個基本動作：看隊伍狀態、看戰鬥次數、申請入隊
# ---------------------------------------------------------------------------

def party_status():
    """按 T 看隊伍狀態。回傳 'in' / 'out' / None（看不懂）。面板會留著開。"""
    if rd.HOTKEYS:
        pyautogui.press(PARTY_KEY)
        rd.nap(0.6)
        wait_stable(rd.T_PANEL_MAX)
    if on_main() and P_PARTY_BTN:                  # 沒快捷鍵（或沒反應）→ 點螢幕上的隊伍按鈕
        click_at(P_PARTY_BTN[0], P_PARTY_BTN[1], wait=rd.T_PANEL_MAX)
    deadline = time.time() + 5.0 * max(0.5, rd.SLOW)
    while time.time() < deadline:
        screen = grab()
        if find_one(screen, "leave_party.png"):
            return "in"
        if find_one(screen, "create_party.png"):
            return "out"
        time.sleep(0.4)
    return None


def count_is_full():
    """點頭像看今日戰鬥次數。回傳 True 滿了 / False 沒滿 / None 面板沒開。"""
    if not on_main():
        back_to_main()
    if not P_AVATAR:
        return None
    click_at(P_AVATAR[0], P_AVATAR[1], wait=rd.T_PANEL_MAX)
    # 面板開了嗎：看得到紅字就是滿；否則至少要離開主畫面才算面板有開
    deadline = time.time() + 4.0 * max(0.5, rd.SLOW)
    while time.time() < deadline:
        screen = grab()
        if find_one(screen, "count_full.png"):
            back_to_main()
            return True
        if not on_main(screen):
            break
        time.sleep(0.4)
    else:
        return None
    wait_stable(1.5)
    full = find_one(grab(), "count_full.png") is not None
    back_to_main()
    return full


def leave_party():
    """在隊伍面板開著的狀態下點離開隊伍 → 確定。回傳有沒有成功離開。"""
    btn = find_one(grab(), "leave_party.png")
    if not btn:
        return False
    click_box(btn)
    ok = wait_for("confirm_ok.png", timeout=4.0)
    if ok:
        click_box(ok)
    wait_stable(2.0)
    back_to_main()
    # 再按一次 T 確認真的不在隊裡了
    st = party_status()
    back_to_main()
    return st == "out"


def apply_party():
    """按 O → ❤ 分頁 → 第一個好友 → 旗子。回傳申請後有沒有真的進隊。"""
    if not on_main():
        back_to_main()
    if rd.HOTKEYS:
        pyautogui.press(FRIEND_KEY)
        rd.nap(0.6)
        wait_stable(rd.T_PANEL_MAX)
    if on_main() and P_FRIEND_BTN:                 # 沒快捷鍵（或沒反應）→ 更多 → 好友
        if rd.too_close(P_MORE_BTN, P_FRIEND_BTN):
            print("  「好友」位置跟「更多」是同一點，抓錯了：校正頁先手動點開「更多」再抓「好友」")
            back_to_main()
            return False
        if P_MORE_BTN and not rd.open_more_menu():   # 選單沒展開就不點，免得點到主畫面別的東西
            print("  點了「更多」但選單沒展開（遊戲可能太卡）")
            back_to_main()
            return False
        pt = rd.menu_item_point("menu_friend.png", P_FRIEND_BTN, "好友")
        if not pt:
            back_to_main()
            return False
        click_at(pt[0], pt[1], wait=rd.T_PANEL_MAX)
    if not (P_FAV_TAB and P_FRIEND_FIRST and P_APPLY_FLAG):
        back_to_main()
        return False
    click_at(P_FAV_TAB[0], P_FAV_TAB[1])
    click_at(P_FRIEND_FIRST[0], P_FRIEND_FIRST[1])
    click_at(P_APPLY_FLAG[0], P_APPLY_FLAG[1])
    wait_stable(2.0)
    back_to_main()
    # 自由隊伍是直接進的，馬上按 T 看有沒有成功
    st = party_status()
    back_to_main()
    return st == "in"


# ---------------------------------------------------------------------------
# 巡一隻小號
# ---------------------------------------------------------------------------

def visit(idx, hwnd, state, slots_free):
    """處理一隻小號。回傳 (新狀態, 訊息, 這次有沒有佔用一個空位)。"""
    orig = rd.get_rect(hwnd)
    try:
        rd.normalize_window(hwnd)
        if on_main():
            rd.wake_up()                        # 省電模式：先點一下叫醒
        if not on_main() and not back_to_main():
            return STATE_ERR, f"不在主畫面（{dump_fail(f'party{idx:02d}_start')}）", False

        st = party_status()
        if st is None:
            shot = dump_fail(f"party{idx:02d}_T")
            back_to_main()
            return STATE_ERR, f"按 T 後看不懂畫面（{shot}）", False
        back_to_main()

        full = count_is_full()
        if full is None:
            return STATE_ERR, f"頭像面板沒開（{dump_fail(f'party{idx:02d}_avatar')}）", False

        if st == "in":
            if not full:
                return STATE_IN, "在隊裡，還沒打滿", False
            party_status()                      # 重開隊伍面板準備離開
            if leave_party():
                return STATE_DONE, "打滿了，已離隊", False
            shot = dump_fail(f"party{idx:02d}_leave")
            back_to_main()
            return STATE_IN, f"打滿了但離隊失敗（{shot}）", False

        # 不在隊裡
        if full:
            return STATE_DONE, "已打滿（不在隊裡）", False
        if slots_free <= 0:
            return STATE_WAIT, "等空位", False
        if apply_party():
            return STATE_IN, "已申請並進隊", True
        return STATE_WAIT, "申請了但沒進隊（可能隊伍剛好滿了）", False

    except (pyautogui.FailSafeException, rd.Aborted):
        raise
    except Exception as e:
        try:
            back_to_main()
        except Exception:
            pass
        return STATE_ERR, f"發生錯誤：{e}", False
    finally:
        try:
            rd.move_window(hwnd, *orig)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 主迴圈
# ---------------------------------------------------------------------------

def pick_alts(hwnds):
    if ALT_WINDOWS:
        return [n for n in ALT_WINDOWS if 1 <= n <= len(hwnds) and n != LEADER_WINDOW]
    return [n for n in range(1, len(hwnds) + 1) if n != LEADER_WINDOW]


def _check_ready(who=""):
    """目前載入的那一套（官方或雷電）組隊用的模板、位置齊不齊。"""
    tag = f"【{who}】" if who else ""
    need = ["leave_party.png", "create_party.png", "count_full.png", "confirm_ok.png"]
    missing = [f for f in need if not has(f)]
    if missing:
        print(f"{tag}缺少模板：" + "、".join(missing) + "，請到校正分頁「組隊輪替」那組抓")
        return False
    if not (P_AVATAR and P_FAV_TAB and P_FRIEND_FIRST and P_APPLY_FLAG):
        print(f"{tag}組隊的四個位置還沒校正完（頭像、❤ 分頁、第一個好友、旗子）")
        return False
    if not rd.HOTKEYS and not (P_PARTY_BTN and P_FRIEND_BTN):
        print(f"{tag}這個環境沒有快捷鍵，請在校正分頁抓「隊伍按鈕」和「好友按鈕」的位置")
        return False
    return True


def _use(hwnd):
    """切到這個視窗那一套設定（自動模式下官方、雷電各用各的），組隊的位置也重讀。"""
    rd.use_profile(rd.kind_of(hwnd))
    _load()


def run(once=False, only=None, leader=None, alts=None):
    """leader：隊長的視窗（None = 隊長不在這台電腦）；alts：小號視窗清單。

    GUI 會從彈窗把選好的視窗直接傳進來；沒傳（命令列）就照舊用設定裡的視窗編號。
    """
    home = rd.ACTIVE_PROFILE
    try:
        _run(once, only, leader, alts)
    finally:
        rd.use_profile(home)
        _load()


def _run(once, only, leader, alts):
    if alts is None:                               # 命令列：照舊用編號
        hwnds = rd.find_windows()
        if not hwnds:
            print("找不到遊戲視窗")
            return
        nums = [only] if only else pick_alts(hwnds)
        alts = [hwnds[n - 1] for n in nums if 1 <= n <= len(hwnds)]
        if 1 <= LEADER_WINDOW <= len(hwnds):
            leader = hwnds[LEADER_WINDOW - 1]
    if not alts:
        print("沒有小號視窗可以巡")
        return

    kinds = sorted({rd.kind_of(h) for h in alts}, key=lambda k: rd.PROFILE_NAMES.index(k))
    for k in kinds:
        rd.use_profile(k)
        _load()
        if not _check_ready(k if rd.RUN_MODE == rd.AUTO_MODE else ""):
            return

    max_alts = max(1, PARTY_SIZE - (1 if leader else 0))
    states = {h: STATE_WAIT for h in alts}
    names = ([rd.window_label(h) for h in alts] if rd.RUN_MODE == rd.AUTO_MODE
             else [_num(h) for h in alts])        # 固定模式照舊印編號
    who = f"隊長 {rd.window_label(leader)}，" if leader and rd.RUN_MODE == rd.AUTO_MODE else ""
    print(f"{who}小號 {names}，隊伍上限 {PARTY_SIZE}（可容納 {max_alts} 隻小號），"
          f"每 {INTERVAL_MIN:g} 分鐘巡一輪")

    try:
        _run_loop(alts, states, max_alts, once)
    except rd.Aborted:
        print("\n已中止，視窗已還原。")


def _num(hwnd):
    """這個視窗現在是第幾號（開關視窗會變，所以每次現算）。不在了回傳 0。"""
    hwnds = rd.find_windows()
    return hwnds.index(hwnd) + 1 if hwnd in hwnds else 0


def _run_loop(alts, states, max_alts, once):
    import win32gui
    rnd = 0
    while True:
        rnd += 1
        print(f"\n===== 第 {rnd} 輪 {time.strftime('%H:%M:%S')} =====")
        in_party = sum(1 for s in states.values() if s == STATE_IN)
        for h in alts:
            if rd.ABORT:
                print("已中止")
                return
            if states[h] == STATE_DONE:
                continue
            n = _num(h)
            if not n or not win32gui.IsWindow(h):
                states[h] = STATE_ERR
                print(f"  {rd.window_label(h) if win32gui.IsWindow(h) else '某個視窗'}：不見了")
                continue
            _use(h)
            slots_free = max_alts - in_party
            new, msg, took = visit(n, h, states[h], slots_free)
            if states[h] == STATE_IN and new != STATE_IN:
                in_party -= 1
            if took:
                in_party += 1
            states[h] = new
            print(f"  {rd.win_title(n, h, pad=True)}：{new}　{msg}")

        summary = {}
        for s in states.values():
            summary[s] = summary.get(s, 0) + 1
        print("  狀態：" + "、".join(f"{k} {v}" for k, v in summary.items()))

        if all(s == STATE_DONE for s in states.values()):
            print("\n所有小號都打滿了，結束。")
            return
        if once:
            return
        # 可中斷的等待
        end = time.time() + INTERVAL_MIN * 60
        while time.time() < end:
            if rd.ABORT:
                print("已中止")
                return
            time.sleep(1)


# ===========================================================================
# 燃料輪替
# ===========================================================================
# 鐵匠打怪會掉燃料，每隻角色每天上限 2000。弱的角色進打手的隊伍「跟隨」吸燃料：
#   每個帳號依序：第 2 隻 → 第 3 隻（小號，燃料 2000 就離隊）→ 第 1 隻（本尊，戰鬥次數 10000 才離隊）
#   隊伍 6 人含打手，同時最多 FUEL_MAX 隻在吸；有空位優先給小號（小號約 10 分鐘就滿，本尊要很久）。
# 判斷：對話框「系統」頁
#   有新訊息、有「獲得燃料」→ 還在吸；有新訊息、沒有燃料 → 可能滿了 → 包包確認 2000/2000；
#   連續兩次一模一樣（沒有新訊息）→ 出狀況 → 確認還在隊裡、有在跟隨。
# 腳印是開關：有紅色斜線 = 已跟隨，這時再按會「取消跟隨」，所以一定先看是哪一種才按。

F_WAIT, F_IN, F_DONE, F_ERR = "等空位", "吸燃料中", "完成", "異常"
FUEL_TEMPLATES = ["settings_game.png", "back_login.png", "title_start.png", "charsel_start.png", "leader_star.png",
                  "follow_off.png", "follow_on.png", "chat_sys_tab.png", "chat_fuel.png", "chat_close.png",
                  "fuel_item.png", "fuel_full.png",
                  "leave_party.png", "create_party.png", "count_full.png"]


def _fuel_key(hwnd):
    return "fuel|" + rd.account_key(hwnd)


def _region(img, x0, y0, x1, y1):
    h, w = img.shape[:2]
    return img[int(h * y0):int(h * y1), int(w * x0):int(w * x1)]


def _same(a, b, tol=3.0):
    """兩張（同一塊）畫面幾乎一樣嗎。"""
    import cv2
    import numpy as np
    if a is None or b is None or a.shape != b.shape:
        return False
    d = cv2.absdiff(cv2.cvtColor(a, cv2.COLOR_BGR2GRAY), cv2.cvtColor(b, cv2.COLOR_BGR2GRAY))
    return float(np.mean(d)) < tol


def switch_character(slot):
    """設置 →「回到登錄」→ 標題「開始遊戲」→ 選第 slot 隻 →「開始遊戲」→ 等回到主畫面。
    回傳 True 成功 / "empty" 這格沒有角色（「＋」）/ False 失敗。"""
    rd.step(f"換到第 {slot} 隻角色：打開設置")
    if not rd.open_settings():
        rd.step("打不開設置")
        return False
    btn = wait_for("back_login.png", timeout=5.0)
    if not btn:
        rd.step("設置裡找不到「回到登錄」")
        return False
    click_box(btn, wait=rd.T_PANEL_MAX)
    ok = find_one(grab(), "confirm_ok.png")          # 有些版本會問要不要確定
    if ok:
        click_box(ok)
    rd.step("按了「回到登錄」，等標題畫面（通常 5～10 秒）")
    t = wait_for("title_start.png", timeout=60.0)
    if not t:
        rd.step("等不到標題畫面的「開始遊戲」")
        return False
    click_box(t, wait=rd.T_PANEL_MAX)
    if not wait_for("charsel_start.png", timeout=60.0):
        rd.step("等不到選角畫面")
        return False
    pt = P_CHAR_SLOTS[slot - 1]
    if not pt:
        rd.step(f"選角畫面第 {slot} 個頭像的位置還沒校正")
        return False
    if has("charsel_plus.png"):
        plus = find_one(grab(), "charsel_plus.png")
        if plus and abs(plus[0] + plus[2] // 2 - pt[0]) < 45 and abs(plus[1] + plus[3] // 2 - pt[1]) < 45:
            rd.step(f"第 {slot} 格是「＋」：這個帳號沒有第 {slot} 隻")
            return "empty"
    click_at(pt[0], pt[1], wait=1.5)
    st = wait_for("charsel_start.png", timeout=5.0)
    if not st:
        return False
    click_box(st)
    rd.step("按了「開始遊戲」，等進到遊戲")
    if not wait_until(lambda sc: on_main(sc), 90.0):
        back_to_main()                               # 進遊戲常會跳公告、簽到，關掉
    if not on_main():
        rd.step("進遊戲後回不到主畫面")
        return False
    rd.wake_up()
    rd.step(f"已經換成第 {slot} 隻")
    return True


def follow_leader():
    """隊伍面板 → 點隊長（紅色星星）→ 看腳印：有斜線就是已跟隨不要按；沒斜線才按。回傳有沒有在跟隨。"""
    st = party_status()
    if st != "in":
        back_to_main()
        return False
    star = wait_for("leader_star.png", timeout=3.0)
    if not star:
        rd.step("隊伍面板裡找不到隊長的紅色星星")
        back_to_main()
        return False
    click_box(star, wait=rd.T_PANEL_MAX)

    def foot():
        sc = grab()
        if find_one(sc, "follow_on.png"):
            return "on"
        b = find_one(sc, "follow_off.png")
        return b or None

    state = None
    for _ in range(int(6 * max(1.0, rd.SLOW))):
        state = foot()
        if state:
            break
        time.sleep(0.5)
    if state == "on":
        rd.step("已經在跟隨隊長了（腳印有斜線，不按）")
        back_to_main()
        return True
    if not state:
        rd.step("點了隊長，但沒看到腳印")
        back_to_main()
        return False
    click_box(state, wait=rd.T_PANEL_MAX)             # 沒斜線的腳印 → 按下去開始跟隨
    rd.step("按了腳印，確認有沒有變成「已跟隨」")
    back_to_main()
    party_status()                                    # 重新打開看一次
    star = wait_for("leader_star.png", timeout=3.0)
    ok = False
    if star:
        click_box(star, wait=rd.T_PANEL_MAX)
        ok = wait_for("follow_on.png", timeout=4.0) is not None
    back_to_main()
    rd.step("跟隨成功" if ok else "按了腳印但看不到「已跟隨」")
    return ok


def chat_page():
    """打開對話框「系統」頁，回傳 (有沒有「獲得燃料」, 那一頁的畫面)；打不開回傳 (None, None)。"""
    if not P_CHAT_OPEN:
        return None, None
    click_at(P_CHAT_OPEN[0], P_CHAT_OPEN[1], wait=rd.T_PANEL_MAX)
    # 對話框開著時上方的圖示還看得到（on_main 還是 True），所以用「系統」分頁判斷有沒有打開
    tab = wait_for("chat_sys_tab.png", timeout=4.0)
    if not tab:
        return None, None
    click_box(tab, wait=1.0)
    wait_stable(1.0)
    sc = grab()
    fuel = find_one(sc, "chat_fuel.png") is not None
    page = _region(sc, 0.0, 0.10, 0.45, 0.95).copy()
    for _ in range(3):                                # 用收起箭頭關掉，確認「系統」分頁不見了
        x = find_one(grab(), "chat_close.png")
        if not x:
            break
        click_box(x, wait=1.0)
        if not find_one(grab(), "chat_sys_tab.png"):
            break
    return fuel, page


def bag_fuel_full():
    """包包 → 愛心分頁 → 點燃料 → 有沒有「2000/2000」。回傳 True / False / None（看不到燃料）。"""
    if not on_main():
        back_to_main()
    if rd.HOTKEYS:
        pyautogui.press(BAG_KEY)
        rd.nap(0.6)
    if on_main() and P_BAG_BTN:
        click_at(P_BAG_BTN[0], P_BAG_BTN[1], wait=rd.T_PANEL_MAX)
    wait_stable(1.5)
    if P_BAG_FAV:
        click_at(P_BAG_FAV[0], P_BAG_FAV[1], wait=1.0)
    item = wait_for("fuel_item.png", timeout=4.0)
    if not item:
        rd.step("包包愛心分頁裡找不到燃料")
        back_to_main()
        return None
    click_box(item, wait=1.0)
    full = wait_for("fuel_full.png", timeout=3.0) is not None
    back_to_main()
    return full


class FuelAccount:
    """一個帳號（視窗）：依序換角色、入隊、跟隨、看燃料。"""

    def __init__(self, hwnd):
        self.hwnd = hwnd
        self.label = rd.window_label(hwnd)
        done = rd.done_today(_fuel_key(hwnd))
        self.queue = [n for n in (2, 3, 1) if f"slot{n}" not in done]   # 先兩隻小號，最後本尊
        self.state = F_DONE if not self.queue else F_WAIT
        self.slot = None              # 目前在吸的是第幾隻
        self.current = None           # 遊戲裡現在登入的是第幾隻（換過才知道）
        self.errors = 0
        self.page = None              # 上次看到的對話框
        self.stuck = 0
        self.fixes = 0
        self.last = 0.0
        self.note = "今天已經全部完成（紀錄）" if not self.queue else ""

    @property
    def next_is_main(self):
        return bool(self.queue) and self.queue[0] == 1

    def finish_slot(self, why):
        rd.mark_done(f"slot{self.slot}", _fuel_key(self.hwnd))
        rd.step(f"第 {self.slot} 隻{why}")
        self.queue.pop(0)
        self.slot, self.page, self.stuck, self.fixes = None, None, 0, 0
        self.state = F_DONE if not self.queue else F_WAIT

    def start_next(self):
        """有空位了：換到下一隻 → 確認還沒滿 → 入隊 → 跟隨。回傳有沒有佔到一個位置。"""
        while self.queue:
            slot = self.queue[0]
            self.slot = slot
            if self.current != slot:                  # 已經是這隻（上次入隊沒成功）就不用再換一次
                r = switch_character(slot)
                if r == "empty":
                    self.queue.pop(0)
                    continue
                if not r:
                    self.errors += 1
                    self.last = time.time() + 120     # 失敗了等 2 分鐘再試
                    shot = dump_fail(f"fuel_{self.label}_switch")
                    if self.errors >= 3:
                        self.state = F_DONE
                        self.note = f"⚠ 換第 {slot} 隻失敗 3 次，這個帳號先跳過（{shot}）"
                    else:
                        self.state, self.note = F_ERR, f"換不到第 {slot} 隻，2 分鐘後再試（{shot}）"
                    return False
                self.current = slot
            # 已經滿了就不用佔位置
            if slot == 1:
                if count_is_full():
                    self.finish_slot("（本尊）戰鬥次數已經 10000，不用吸")
                    continue
            elif bag_fuel_full():
                self.finish_slot("燃料已經 2000，不用吸")
                continue
            st = party_status()
            back_to_main()
            if st != "in" and not apply_party():
                self.last = time.time() + 60          # 隊伍可能剛好滿了：1 分鐘後再申請（不用再換角色）
                self.state, self.note = F_WAIT, "申請入隊沒進去（可能隊伍剛好滿了），1 分鐘後再試"
                return False
            followed = follow_leader()
            self.state, self.page, self.stuck, self.errors = F_IN, None, 0, 0
            self.note = (f"第 {slot} 隻{'（本尊）' if slot == 1 else ''}進隊吸燃料中"
                         + ("" if followed else "（跟隨還沒成功，巡邏時會再試）"))
            return True
        self.state, self.note = F_DONE, "全部完成"
        return False

    def check(self):
        """巡一次：滿了就離隊換下一隻；沒新訊息就修跟隨。回傳有沒有空出一個位置。"""
        is_main = self.slot == 1
        if is_main and count_is_full():
            party_status()
            if leave_party():
                self.finish_slot("（本尊）戰鬥次數 10000 打滿，已離隊")
                self.note = "全部完成"
                return True
            self.note = "本尊打滿了但離隊失敗"
            return False
        fuel, page = chat_page()
        if page is None:
            self.note = "對話框打不開"
            return False
        changed = not _same(page, self.page)
        self.page = page
        if changed:
            self.stuck = 0
            if fuel or is_main:
                self.note = "還在吸" + ("（本尊等戰鬥次數 10000）" if is_main else "")
                return False
            rd.step("對話框有新訊息但沒有燃料：可能滿了，打開包包確認")
            full = bag_fuel_full()
            if full:
                party_status()
                if leave_party():
                    self.finish_slot("燃料 2000 滿了，已離隊")
                    return True
                self.note = "燃料滿了但離隊失敗"
                return False
            self.note = "包包還沒 2000，繼續吸" if full is False else "包包裡看不到燃料"
            return False
        self.stuck += 1
        if self.stuck < 2:
            self.note = "對話框這次沒有新訊息，下次再看"
            return False
        # 連續兩次沒有新訊息：不在隊裡？沒跟隨？
        self.fixes += 1
        rd.step("對話框一直沒有新訊息：檢查還在不在隊裡、有沒有在跟隨")
        st = party_status()
        back_to_main()
        if st == "out":
            if apply_party():
                follow_leader()
                self.note = "掉出隊伍了，已重新入隊並跟隨"
            else:
                self.note = "掉出隊伍了，重新申請沒進去"
        elif follow_leader():
            self.note = "有在跟隨，但沒有新訊息：打手可能沒在打怪"
        else:
            self.note = "跟隨失敗"
        self.stuck = 0
        if self.fixes >= 4:
            self.note += f"（⚠ 已經修了 {self.fixes} 次還是沒動靜，請看一下）"
        return False


def fuel_run(leader=None, accounts=None):
    """GUI 從彈窗選好打手和要吸的帳號傳進來。"""
    home = rd.ACTIVE_PROFILE
    try:
        _fuel_run(leader, accounts or [])
    finally:
        rd.use_profile(home)
        _load()


def _fuel_ready(kind):
    missing = [f for f in FUEL_TEMPLATES if not has(f)]
    if missing:
        print(f"【{kind}】燃料輪替缺少模板：" + "、".join(missing) + "，請到校正分頁「燃料輪替」那組抓")
        return False
    lacks = [n for n, pt in zip((1, 2, 3), P_CHAR_SLOTS) if not pt]
    if lacks or not P_CHAT_OPEN or not P_BAG_FAV or not P_AVATAR:
        print(f"【{kind}】燃料輪替的位置還沒校正完（選角頭像、對話框、包包愛心分頁、自己的頭像）")
        return False
    if not rd.HOTKEYS and not (P_PARTY_BTN and P_FRIEND_BTN and P_BAG_BTN):
        print(f"【{kind}】沒有快捷鍵：請抓「隊伍」「好友」「包包」按鈕的位置")
        return False
    return True


def _fuel_run(leader, accounts):
    import win32gui
    if not accounts:
        print("沒有要吸燃料的帳號")
        return
    for k in sorted({rd.kind_of(h) for h in accounts}, key=lambda k: rd.PROFILE_NAMES.index(k)):
        rd.use_profile(k)
        _load()
        if not _fuel_ready(k):
            return
    accs = []
    for h in accounts:
        _use(h)
        accs.append(FuelAccount(h))
    print(f"打手：{rd.window_label(leader) if leader else '（不在這台電腦）'}，"
          f"{len(accs)} 個帳號，同時最多 {FUEL_MAX} 隻在吸，每個視窗至少隔 {FUEL_GAP:g} 秒看一次")
    for a in accs:
        if a.state == F_DONE:
            print(f"  {a.label}：{a.note}")
    t0 = time.time()

    def visit(a, what):
        orig = rd.get_rect(a.hwnd)
        try:
            _use(a.hwnd)
            rd.normalize_window(a.hwnd)
            if on_main():
                rd.wake_up()
            elif what == "check" and not back_to_main():
                a.note = f"不在主畫面（{dump_fail(f'fuel_{a.label}_start')}）"
                return False
            return a.start_next() if what == "start" else a.check()
        except (pyautogui.FailSafeException, rd.Aborted):
            raise
        except Exception as e:
            a.note = f"發生錯誤：{e}"
            try:
                back_to_main()
            except Exception:
                pass
            return False
        finally:
            a.last = max(a.last, time.time())        # 失敗時設的「等一下再試」不要被蓋掉
            try:
                rd.move_window(a.hwnd, *orig)
            except Exception:
                pass

    try:
        while True:
            if rd.ABORT:
                print("已中止")
                return
            alive = [a for a in accs if a.state != F_DONE and win32gui.IsWindow(a.hwnd)]
            if not alive:
                print(f"\n所有帳號都完成了，共 {(time.time() - t0) / 60:.0f} 分鐘。")
                return
            busy = sum(1 for a in accs if a.state == F_IN)
            did = False
            # 有空位：優先給下一隻是小號的帳號（小號快，本尊佔位置很久）
            waiting = sorted([a for a in alive if a.state in (F_WAIT, F_ERR)
                              and time.time() - a.last >= FUEL_GAP],
                             key=lambda a: a.next_is_main)
            if busy < FUEL_MAX and waiting:
                a = waiting[0]
                print(f"\n[{time.strftime('%H:%M:%S')}] {a.label}：有空位（{busy}/{FUEL_MAX}），換下一隻進隊")
                visit(a, "start")
                print(f"  → {a.note}")
                did = True
            for a in [a for a in alive if a.state == F_IN]:
                if rd.ABORT:
                    break
                if time.time() - a.last < FUEL_GAP:
                    continue
                print(f"\n[{time.strftime('%H:%M:%S')}] {a.label}（第 {a.slot} 隻）")
                freed = visit(a, "check")
                print(f"  → {a.note}")
                did = True
                if freed:
                    break                             # 空出位置了，先回去讓下一隻進隊
            if not did:
                time.sleep(1)
            line = "、".join(f"{a.label}:{a.state}{f'#{a.slot}' if a.slot else ''}" for a in accs)
            if did:
                print(f"  狀態：{line}")
    except rd.Aborted:
        print("\n已中止，視窗已還原。")


if __name__ == "__main__":
    rd.enable_dpi_awareness()
    rd.start_stop_hotkey()
    args = sys.argv[1:]
    num = next((int(a) for a in args if a.isdigit()), None)
    run(once=("once" in args), only=num)
