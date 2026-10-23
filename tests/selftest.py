#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
위젯 화면 동작 점검 (창을 띄우지 않고, 계정·네트워크 없이)
==========================================================
Qt의 offscreen 플랫폼에서 가짜 사용량으로 위젯을 만들어 크기 조정, 최소화, 색상, 설정 복원을 확인한다.
설정 파일은 임시 폴더에 만들고 지우므로 실제 위젯 설정은 건드리지 않는다.

    python3 tests/selftest.py                          # 점검만
    python3 tests/selftest.py --shots docs/screenshot.png   # README용 스크린샷도 저장
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from datetime import timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = tempfile.mkdtemp(prefix="ai-usage-selftest-")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["XDG_CONFIG_HOME"] = CONFIG_DIR          # 실제 설정(~/.config/AIUsageWidget)과 분리
sys.path.insert(0, ROOT)

import ai_usage_widget as w                          # noqa: E402
from PyQt6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt   # noqa: E402
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPixmap, QWheelEvent   # noqa: E402
from PyQt6.QtTest import QTest                       # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget    # noqa: E402

FAIL_GPT = {"on": False}


def fake_claude() -> w.ProviderUsage:
    now = w.now_local()
    return w.ProviderUsage(w.Window(27.0, now + timedelta(hours=2, minutes=3), measured_at=now),
                           w.Window(74.0, now + timedelta(days=2, hours=7), measured_at=now),
                           w.Window(12.0, now + timedelta(days=2, hours=7), measured_at=now))


def fake_gpt() -> w.ProviderUsage:
    if FAIL_GPT["on"]:
        raise RuntimeError("로그인 갱신 필요: 터미널에서 codex 를 한 번 실행하세요")
    now = w.now_local()
    return w.ProviderUsage(w.Window(93.0, now + timedelta(hours=4, minutes=10), measured_at=now),
                           w.Window(45.0, now + timedelta(days=6, hours=1), measured_at=now))


w.fetch_claude_usage = fake_claude
w.fetch_gpt_usage = fake_gpt

failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def wait_first_snapshot(card: w.UsageCard, timeout_ms: int = 8000) -> None:
    waited = 0
    while card._busy or card._data["claude"]["usage"] is None:
        QTest.qWait(50)
        waited += 50
        if waited > timeout_ms:
            raise SystemExit("첫 조회가 끝나지 않았습니다")
    QTest.qWait(700)                                 # 미터 애니메이션이 끝날 때까지


def contrast(a: str, b: str) -> float:
    def lum(c: str) -> float:
        q = QColor(c)
        ch = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
              for v in (q.redF(), q.greenF(), q.blueF())]
        return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def corner_ok(card: w.UsageCard) -> bool:
    g = card._grip.geometry()
    return g.right() == card.width() - 1 and g.bottom() == card.height() - 1


def test_resize(card: w.UsageCard) -> None:
    print("크기 조정")
    check(card.width() == w.CARD_WIDTH, f"100%일 때 폭 {w.CARD_WIDTH}")
    check(corner_ok(card), "손잡이가 오른쪽 아래 모서리에 있음")
    h100 = card.height()

    grip = card._grip
    left, none, mods = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier
    start = QPointF(grip.mapToGlobal(QPoint(7, 7)))
    QApplication.sendEvent(grip, QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(7, 7), start, left, left, mods))
    for step in range(0, 121, 10):
        g = start + QPointF(step, step * 0.6)
        QApplication.sendEvent(grip, QMouseEvent(QEvent.Type.MouseMove, grip.mapFromGlobal(g), g, none, left, mods))
    QApplication.sendEvent(grip, QMouseEvent(QEvent.Type.MouseButtonRelease, grip.mapFromGlobal(g), g, left, none, mods))
    QTest.qWait(100)
    check(card._scale_pct > 100 and card._scale_pct % w.UI_SCALE_STEP == 0,
          f"모서리를 끌면 커지고 {w.UI_SCALE_STEP}% 단위 ({card._scale_pct}%)")
    check(abs(card.width() - w.sp(w.CARD_WIDTH)) <= 1, "폭이 배율을 따라감")
    check(abs(card.height() / h100 - card._scale_pct / 100) < 0.08, "높이도 같은 비율로 커짐")
    check(corner_ok(card), "커진 뒤에도 손잡이가 모서리에 있음")

    screen = card.screen().availableGeometry()
    card.move(screen.right() - card.width() - 24, screen.top() + 24)
    QTest.qWait(50)
    right = card.frameGeometry().right()
    card.set_scale(150)
    check(card._scale_pct == 150 and card._scale_menu.title() == "크기 (150%)", "메뉴로 150%")
    check(card.frameGeometry().right() == right, "화면 오른쪽에 있으면 오른쪽 모서리가 제자리")

    center = QPointF(card.width() / 2, 40)
    wheel = QWheelEvent(center, QPointF(card.mapToGlobal(center.toPoint())), QPoint(0, 0), QPoint(0, -120),
                        none, Qt.KeyboardModifier.ControlModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(card, wheel)              # 합성한 휠 이벤트는 자식에서 부모로 전파되지 않아 직접 보낸다
    check(card._scale_pct == 145, "Ctrl + 휠로 5% 줄임")
    check(not any(a.isChecked() for a in card._scale_group.actions()), "프리셋에 없는 배율이면 체크 없음")

    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    before = len(card.findChildren(QWidget))
    for pct in (110, 120, 75, 200, 90, 100):
        card.set_scale(pct)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    check(len(card.findChildren(QWidget)) == before, "크기를 여러 번 바꿔도 위젯이 쌓이지 않음")
    check(card.claude._meter.value > 26, "새로 만든 카드에도 값이 바로 채워짐")


def test_minimize(card: w.UsageCard) -> None:
    print("최소화")
    screen = card.screen().availableGeometry()
    card.move(screen.right() - card.width() - 24, screen.top() + 24)
    QTest.qWait(50)
    before = card.frameGeometry()
    full_w, full_h = card.width(), card.height()
    card._min_btn.click()
    check(card._mini and card._mini_bar.isVisible() and not card._full.isVisible(), "− 버튼으로 막대가 됨")
    check(card.width() < full_w * 0.85 and card.height() < full_h * 0.35, f"막대가 작음 ({card.width()}×{card.height()})")
    check(card.frameGeometry().right() == before.right() and card.frameGeometry().top() == before.top(),
          "오른쪽 위 모서리가 제자리")
    check(not card._grip.isVisible() and card._act_mini.isChecked(), "손잡이 숨김, 메뉴 체크")

    FAIL_GPT["on"] = True
    card.request_refresh()
    QTest.qWait(1500)
    tip = card._mini_items["gpt"].toolTip()
    check("로그인 갱신 필요" in tip and "93%" in tip, "조회 실패 시 마지막 값 유지 + 툴팁에 이유")
    FAIL_GPT["on"] = False

    card.set_provider_visible("gpt", False)
    check(not card._mini_items["gpt"].isVisible(), "GPT를 숨기면 막대에서도 빠짐")
    card.set_provider_visible("gpt", True)
    QTest.qWait(1500)

    card._expand_btn.click()
    check(not card._mini and card._full.isVisible() and card._grip.isVisible(), "□ 버튼으로 다시 펼침")
    check(card.frameGeometry().right() == before.right(), "펼칠 때도 오른쪽 모서리가 제자리")


def test_colors(card: w.UsageCard) -> None:
    print("색상")
    original = (w.C_BASE, w.C_EDGE, w.C_TRACK, w.C_TEXT, w.C_MUTED, w.C_OK, w.C_WARN, w.C_CRIT)
    swatches = card._palette._swatches
    for name, color in w.THEME_PRESETS[1:]:
        swatches[QColor(color).name()].click()
        if QColor(w.C_BASE) != QColor(color):
            check(False, f"{name} 견본을 누르면 바탕색이 바뀜")
    check(True, f"견본 {len(w.THEME_PRESETS) - 1}개를 눌러 모두 적용됨")
    check(sum(s._selected for s in swatches.values()) == 1, "고른 견본 하나에만 고리")
    check(card._weekly_on and card._data["claude"]["usage"] is not None, "색을 바꿔도 값과 펼침 상태 유지")
    check(w.C_MUTED.lower() in card._status.styleSheet().lower(), "상태 줄도 새 색을 따라감")

    worst = 99.0
    for _name, color in w.THEME_PRESETS:
        w.set_theme(color)
        for token in (w.C_TEXT, w.C_MUTED, w.C_OK, w.C_WARN, w.C_CRIT):
            worst = min(worst, contrast(token, w.C_BASE))
    check(worst >= 4.5, f"모든 견본에서 글자·상태색 대비 4.5 이상 (최저 {worst:.1f})")

    card.set_theme_color("not-a-color")
    check((w.C_BASE, w.C_EDGE, w.C_TRACK, w.C_TEXT, w.C_MUTED, w.C_OK, w.C_WARN, w.C_CRIT) == original,
          "잘못된 색 값이면 기본 색")
    card.set_theme_color("#FFE680")
    check(w.is_light(w.C_BASE) and contrast(w.C_TEXT, w.C_BASE) > 10, "직접 고른 밝은 색이면 어두운 글자")
    card.set_theme_color(w.THEME_DEFAULT)
    check((w.C_BASE, w.C_EDGE, w.C_TRACK, w.C_TEXT, w.C_MUTED, w.C_OK, w.C_WARN, w.C_CRIT) == original,
          "기본 색으로 되돌리면 원래 색 그대로")


def test_restore() -> None:
    print("설정 복원")
    card = w.UsageCard()
    card.show()
    wait_first_snapshot(card)
    card.set_scale(115)
    card.set_theme_color("#E5EFFA")
    card.set_minimized(True)
    pos = card.pos()
    card.close()
    QTest.qWait(100)
    w.set_theme(w.THEME_DEFAULT)                     # 새로 실행한 것처럼 기본 색에서 시작
    again = w.UsageCard()
    again.show()
    QTest.qWait(200)
    check(again._scale_pct == 115 and again._mini and w.C_BASE == "#e5effa" and again.pos() == pos,
          "다시 띄우면 크기·최소화·색·위치가 복원됨")
    again.close()
    w.set_theme(w.THEME_DEFAULT)


def save_screenshot(path: str) -> None:
    """README용: 기본 카드(주간 펼침), 밝은 카드, 최소화 막대 두 개를 한 장에."""
    shots = []
    for color, mini in ((w.THEME_DEFAULT, False), ("#E5EFFA", False), (w.THEME_DEFAULT, True), ("#E5EFFA", True)):
        card = w.UsageCard()
        card.set_scale(100)
        card.set_theme_color(color)
        card.set_weekly_visible(True)
        card.set_minimized(mini)
        card.show()
        wait_first_snapshot(card)
        shots.append(card.grab())
        card.close()
        QTest.qWait(50)
    w.set_theme(w.THEME_DEFAULT)

    pad, gap = 28, 24
    dark, light, mini_dark, mini_light = shots
    right_w = max(mini_dark.width(), mini_light.width())
    width = pad * 2 + dark.width() + light.width() + right_w + gap * 2
    height = pad * 2 + max(dark.height(), light.height())
    sheet = QPixmap(width, height)
    sheet.fill(QColor("#454B59"))
    p = QPainter(sheet)
    p.drawPixmap(pad, pad, dark)
    p.drawPixmap(pad + dark.width() + gap, pad, light)
    x = pad + dark.width() + light.width() + gap * 2
    p.drawPixmap(x, pad, mini_dark)
    p.drawPixmap(x, pad + mini_dark.height() + 14, mini_light)
    p.end()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    sheet.save(path)
    print(f"스크린샷 저장: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--shots", metavar="PNG", help="README용 스크린샷을 이 경로에 저장")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setFont(w.make_font(12))
    app.setStyleSheet(w.app_qss())
    try:
        card = w.UsageCard()
        card.show()
        wait_first_snapshot(card)
        card.set_weekly_visible(True)
        test_resize(card)
        test_minimize(card)
        test_colors(card)
        card.close()
        QTest.qWait(100)
        test_restore()
        if args.shots:
            shutil.rmtree(CONFIG_DIR, ignore_errors=True)    # 스크린샷은 빈 설정에서 찍는다
            save_screenshot(args.shots)
    finally:
        shutil.rmtree(CONFIG_DIR, ignore_errors=True)

    print(f"\n결과: {'실패 ' + str(len(failures)) + '개' if failures else '모두 통과'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
