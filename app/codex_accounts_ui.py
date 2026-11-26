"""Codex Multi-Account Management Pane, Dialog & Card Components.

Matches Bailong desktop pet design system:
- Compact hierarchy, no middle-dot separators
- Hidden scrollbars with wheel scrolling preserved
- Distinct primary, danger, and disabled hover states
- Browser authorization launch
- Non-blocking background worker threads for OAuth and quota operations
"""
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QUrl, QTimer, QPoint
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget, QLabel,
    QPushButton, QScrollArea, QMessageBox, QInputDialog, QProgressBar, QSizePolicy, QMenu, QFrame
)

from codex_account_manager import CodexAccountManager
from typography import FONT_CSS
from ui_theme import (
    SURFACE, INK, MUTED, ACCENT, TRACK, PANEL, BORDER,
    PRIMARY, PRIMARY_PRESSED, ON_PRIMARY, SELECTED, DANGER,
    DANGER_SURFACE, DISABLED, hide_scrollbars, editor_stylesheet
)
from theme_runtime import set_theme_style


class AccountWorker(QThread):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, target_fn, *args, parent=None):
        super().__init__(parent)
        self.target_fn = target_fn
        self.args = args

    def run(self):
        try:
            res = self.target_fn(*self.args)
            self.finished.emit(res)
        except Exception as error:
            self.failed.emit(str(error))


class AccountCard(QWidget):
    switchRequested = Signal(str)
    refreshRequested = Signal(str)
    renameRequested = Signal(str)
    deleteRequested = Signal(str)

    def __init__(self, account_data: dict, parent=None):
        super().__init__(parent)
        self.account_data = account_data
        self.acc_id = account_data['id']
        self._init_ui()

    def _init_ui(self):
        is_active = self.account_data.get('is_active', False)
        bg = SURFACE if is_active else PANEL
        border_color = PRIMARY if is_active else BORDER
        self.action_buttons = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        self.setObjectName('account_card')
        set_theme_style(
            self,
            f'QWidget#account_card{{background:{bg};border:1px solid {border_color};border-radius:8px;}}'
        )

        # Row 1: 名称 / 账户
        row1 = QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.setSpacing(6)

        # 名称: Status dot + Alias
        dot = QLabel('●' if is_active else '○')
        set_theme_style(
            dot,
            f'{FONT_CSS}font-size:11px;color:{PRIMARY if is_active else MUTED};'
        )
        row1.addWidget(dot)

        alias_text = self.account_data.get('alias') or '未命名账户'
        alias_lbl = QLabel(alias_text)
        alias_lbl.setToolTip(alias_text)
        alias_lbl.setMinimumWidth(0)
        set_theme_style(
            alias_lbl,
            f'{FONT_CSS}font-size:12px;font-weight:600;color:{INK};'
        )
        row1.addWidget(alias_lbl)

        row1.addStretch()

        # 账户: Email
        email = self.account_data.get('email') or '无关联邮箱'
        email_lbl = QLabel(email)
        email_lbl.setToolTip(email)
        email_lbl.setMinimumWidth(0)
        set_theme_style(
            email_lbl,
            f'{FONT_CSS}font-size:10px;color:{MUTED};'
        )
        row1.addWidget(email_lbl)

        layout.addLayout(row1)

        # Row 2: 等级 / 按钮列
        row2 = QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        row2.setSpacing(6)
        row2.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # 等级: Plan badge
        plan = (self.account_data.get('plan_type') or 'Free').upper()
        plan_badge = QLabel(f" {plan} ")
        set_theme_style(
            plan_badge,
            f'{FONT_CSS}font-size:9.5px;font-weight:500;background:{SELECTED};color:{PRIMARY};border-radius:3px;padding:2px 5px;'
        )
        row2.addWidget(plan_badge, 0, Qt.AlignmentFlag.AlignVCenter)

        row2.addStretch()

        # 按钮列: 切换按钮 / 详情按钮 / 操作按钮
        if is_active:
            self.switch_btn = QPushButton('当前账户')
            self.switch_btn.setFixedSize(64, 24)
            self.switch_btn.setEnabled(False)
            set_theme_style(
                self.switch_btn,
                f'QPushButton{{{FONT_CSS}font-size:11px;font-weight:600;background:{PRIMARY};color:{ON_PRIMARY};border:0;border-radius:4px;padding:0;}}'
                f'QPushButton:disabled{{{FONT_CSS}font-size:11px;font-weight:600;background:{PRIMARY};color:{ON_PRIMARY};border:0;}}'
            )
            self.switch_btn.setToolTip('当前正在生效的活跃账户')
        else:
            self.switch_btn = QPushButton('切换账户')
            self.switch_btn.setFixedSize(64, 24)
            self.switch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            set_theme_style(
                self.switch_btn,
                f'QPushButton{{{FONT_CSS}font-size:11px;font-weight:500;background:{PRIMARY};color:{ON_PRIMARY};border:0;border-radius:4px;padding:0;}}'
                f'QPushButton:hover{{background:{PRIMARY_PRESSED};}}'
                f'QPushButton:pressed{{background:#4d3c62;}}'
                f'QPushButton:disabled{{background:{TRACK};color:{MUTED};}}'
            )
            self.switch_btn.setToolTip('切换至此账户并同步重启 Codex')
            self.switch_btn.clicked.connect(lambda: self.switchRequested.emit(self.acc_id))
            self.action_buttons.append(self.switch_btn)
        row2.addWidget(self.switch_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self.details_btn = QPushButton('详情 ▴' if is_active else '详情 ▾')
        self.details_btn.setFixedSize(54, 24)
        self.details_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        set_theme_style(
            self.details_btn,
            f'QPushButton{{{FONT_CSS}font-size:11px;background:transparent;color:{PRIMARY};border:1px solid {BORDER};border-radius:4px;padding:0;}}'
            f'QPushButton:hover{{background:{SELECTED};border-color:{PRIMARY};color:{INK};}}'
            f'QPushButton:pressed{{background:{BORDER};color:{INK};}}'
        )
        self.details_btn.setToolTip('展开/折叠额度与凭据到期时间')
        self.details_btn.clicked.connect(self._toggle_details)
        row2.addWidget(self.details_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self.ops_btn = QPushButton('操作 ▾')
        self.ops_btn.setFixedSize(54, 24)
        self.ops_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        set_theme_style(
            self.ops_btn,
            f'QPushButton{{{FONT_CSS}font-size:11px;background:transparent;color:{MUTED};border:1px solid {BORDER};border-radius:4px;padding:0;}}'
            f'QPushButton:hover{{background:{SELECTED};color:{INK};border-color:{PRIMARY};}}'
            f'QPushButton:pressed{{background:{BORDER};color:{INK};}}'
            f'QPushButton:disabled{{color:{MUTED};border-color:{TRACK};}}'
        )
        self.ops_btn.setToolTip('管理此账户（刷新、改名、删除）')
        self.ops_btn.clicked.connect(self._show_actions_menu)
        row2.addWidget(self.ops_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self.action_buttons.append(self.ops_btn)

        layout.addLayout(row2)

        # Details Panel: 凭证有效期、本周周额度、五小时额度（全部带紧凑进度条）
        self.details_widget = QWidget()
        self.details_widget.setObjectName('details_panel')
        set_theme_style(
            self.details_widget,
            f'QWidget#details_panel{{background:#faf8fc;border:1px solid {BORDER};border-radius:6px;}}'
        )
        details_layout = QVBoxLayout(self.details_widget)
        details_layout.setContentsMargins(10, 8, 10, 8)
        details_layout.setSpacing(6)

        # 1. 凭证有效期（满值为 10 天）
        exp = self.account_data.get('expires_at')
        if exp:
            exp_sec = exp - time.time()
            days = int(exp_sec // 86400)
            hours = int((exp_sec % 86400) // 3600)
            mins = int((exp_sec % 3600) // 60)
            exp_time = time.strftime('%m-%d %H:%M', time.localtime(exp))
            if days > 0:
                exp_text = f"{days}天{hours}h (至 {exp_time})"
            elif hours > 0:
                exp_text = f"{hours}h{mins}m (至 {exp_time})"
            elif exp_sec > 0:
                exp_text = f"{mins}分钟 (即将到期)"
            else:
                exp_text = "已到期 (需刷新)"

            # 满值为 10 天 (10 * 86400 秒)
            max_token_sec = 10 * 86400.0
            exp_pct = max(0.0, min(100.0, (exp_sec / max_token_sec) * 100.0))
            is_danger = exp_sec <= 3600
            is_warn = 3600 < exp_sec <= 86400
        else:
            exp_text = "长期有效 / 待检测"
            exp_pct = 100.0
            is_danger = False
            is_warn = False

        details_layout.addWidget(
            self._create_progress_row('凭证有效期：', exp_text, exp_pct, is_danger=is_danger, is_warn=is_warn)
        )

        # 2. 本周周额度
        quota = self.account_data.get('quota', {})
        windows = quota.get('windows', [])
        week_win = next(
            (w for w in windows if '周' in w.get('name', '') or w.get('name') == '一周'),
            None
        )
        if not week_win and len(windows) >= 2:
            week_win = windows[1]

        if week_win:
            w_rem = week_win.get('remaining')
            week_pct = float(w_rem) if w_rem is not None else 0.0
            reset_ts = week_win.get('resetsAt')
            reset_str = ''
            if reset_ts and reset_ts > time.time():
                diff = reset_ts - time.time()
                if diff > 86400:
                    reset_str = f" ({int(diff//86400)}天重置)"
                elif diff > 3600:
                    reset_str = f" ({int(diff//3600)}h重置)"
                else:
                    reset_str = f" ({int(diff//60)}m重置)"
            week_text = f"剩余 {round(week_pct, 1)}%{reset_str}" if w_rem is not None else "未知"
            w_danger = week_pct <= 10.0
            w_warn = 10.0 < week_pct <= 30.0
        else:
            week_pct = 0.0
            week_text = "未获取"
            w_danger = False
            w_warn = False

        details_layout.addWidget(
            self._create_progress_row('本周周额度：', week_text, week_pct, is_danger=w_danger, is_warn=w_warn)
        )

        # 3. 五小时额度
        five_win = next(
            (w for w in windows if '5小时' in w.get('name', '') or '5h' in w.get('name', '').lower()),
            None
        )
        if not five_win and len(windows) >= 1:
            five_win = windows[0]

        if five_win:
            f_rem = five_win.get('remaining')
            five_pct = float(f_rem) if f_rem is not None else 0.0
            reset_ts = five_win.get('resetsAt')
            reset_str = ''
            if reset_ts and reset_ts > time.time():
                diff = reset_ts - time.time()
                if diff > 3600:
                    reset_str = f" ({int(diff//3600)}h{int((diff%3600)//60)}m重置)"
                else:
                    reset_str = f" ({int(diff//60)}m重置)"
            five_text = f"剩余 {round(five_pct, 1)}%{reset_str}" if f_rem is not None else "未知"
            f_danger = five_pct <= 10.0
            f_warn = 10.0 < five_pct <= 30.0
        else:
            five_pct = 0.0
            five_text = "未获取"
            f_danger = False
            f_warn = False

        details_layout.addWidget(
            self._create_progress_row('五小时额度：', five_text, five_pct, is_danger=f_danger, is_warn=f_warn)
        )

        self.details_widget.setVisible(is_active)
        layout.addWidget(self.details_widget)

    def _create_progress_row(self, title: str, value_text: str, percent: float, is_danger: bool = False, is_warn: bool = False):
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)

        title_lbl = QLabel(title)
        title_lbl.setFixedWidth(66)
        set_theme_style(title_lbl, f'{FONT_CSS}font-size:10.5px;color:{INK};font-weight:500;')
        row_layout.addWidget(title_lbl)

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(int(round(max(0.0, min(100.0, percent)))))
        bar.setTextVisible(False)
        bar.setFixedWidth(96)
        bar.setFixedHeight(6)

        if is_danger:
            bar_color = DANGER
            txt_color = DANGER
        elif is_warn:
            bar_color = '#b87428'
            txt_color = '#b87428'
        else:
            bar_color = PRIMARY
            txt_color = PRIMARY

        set_theme_style(
            bar,
            f'QProgressBar{{border:0;border-radius:3px;background:{TRACK};}}'
            f'QProgressBar::chunk{{border-radius:3px;background:{bar_color};}}'
        )
        row_layout.addWidget(bar)

        val_lbl = QLabel(value_text)
        val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        val_lbl.setMinimumWidth(0)
        val_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        val_lbl.setToolTip(value_text)
        set_theme_style(val_lbl, f'{FONT_CSS}font-size:10px;color:{txt_color};font-weight:500;')
        row_layout.addWidget(val_lbl)

        return row_widget

    def _toggle_details(self):
        show = self.details_widget.isHidden()
        self.details_widget.setVisible(show)
        self.details_btn.setText('详情 ▴' if show else '详情 ▾')

    def _show_actions_menu(self):
        menu = QMenu(self)
        menu.setCursor(Qt.CursorShape.PointingHandCursor)
        set_theme_style(
            menu,
            f'''
            QMenu {{
                background: {SURFACE};
                border: 1px solid {BORDER};
                border-radius: 6px;
                padding: 4px;
            }}
            QMenu::item {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                font-size: 11px;
                color: {INK};
                padding: 5px 16px 5px 12px;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background: {SELECTED};
                color: {PRIMARY};
            }}
            '''
        )
        act_refresh = menu.addAction('🔄 刷新凭据与额度')
        act_rename = menu.addAction('✏️ 修改账户别名')
        act_del = menu.addAction('🗑️ 删除此账户')

        pos = self.ops_btn.mapToGlobal(QPoint(0, self.ops_btn.height() + 2))
        selected = menu.exec(pos)
        if selected == act_refresh:
            self.refreshRequested.emit(self.acc_id)
        elif selected == act_rename:
            self.renameRequested.emit(self.acc_id)
        elif selected == act_del:
            self.deleteRequested.emit(self.acc_id)

    def set_actions_enabled(self, enabled: bool):
        is_active = self.account_data.get('is_active', False)
        if not is_active and self.switch_btn:
            self.switch_btn.setEnabled(enabled)
        self.ops_btn.setEnabled(enabled)



class CodexAccountsPane(QWidget):
    """Main account management view that can be embedded directly in the compact bubble or shown in a window."""
    accountChanged = Signal(str)

    def __init__(self, manager: CodexAccountManager = None, parent=None):
        super().__init__(parent)
        self.manager = manager or CodexAccountManager()
        self.active_worker = None
        self._init_ui()
        self.refresh_list()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(8)

        # Header description
        top_box = QVBoxLayout()
        top_box.setSpacing(2)
        desc = QLabel('凭据经系统本地物理隔离，多账户一键秒级切换与自动保活。')
        set_theme_style(desc, f'{FONT_CSS}font-size:11px;color:{MUTED};')
        top_box.addWidget(desc)
        main_layout.addLayout(top_box)

        # Action Toolbar (Single row: 新增账户 / 导入账户 / 全部刷新 / 全部续期)
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 2, 0, 2)
        toolbar.setSpacing(6)

        self.login_btn = QPushButton('新增账户')
        self.login_btn.setFixedHeight(28)
        self.login_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.login_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        set_theme_style(
            self.login_btn,
            f'QPushButton{{{FONT_CSS}font-size:11px;font-weight:600;background:{PRIMARY};color:{ON_PRIMARY};border:0;border-radius:6px;padding:3px 4px;}}'
            f'QPushButton:hover{{background:{PRIMARY_PRESSED};}}'
            f'QPushButton:pressed{{background:#4d3c62;}}'
            f'QPushButton:disabled{{background:{TRACK};color:{MUTED};}}'
        )
        self.login_btn.setToolTip('选择浏览器打开 Codex 官方登录授权页' if sys.platform == 'darwin'
                                  else '用系统默认浏览器打开 Codex 官方登录授权页')
        self.login_btn.clicked.connect(self.choose_login_browser)
        toolbar.addWidget(self.login_btn)

        self.import_btn = QPushButton('导入账户')
        self.import_btn.setFixedHeight(28)
        self.import_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        set_theme_style(
            self.import_btn,
            f'QPushButton{{{FONT_CSS}font-size:11px;font-weight:500;background:{SELECTED};color:{PRIMARY};border:1px solid {BORDER};border-radius:6px;padding:3px 4px;}}'
            f'QPushButton:hover{{background:{BORDER};color:{INK};border-color:{PRIMARY};}}'
            f'QPushButton:pressed{{background:#ded2e7;color:{INK};}}'
            f'QPushButton:disabled{{background:{PANEL};color:{MUTED};border-color:transparent;}}'
        )
        self.import_btn.setToolTip('导入当前系统已生效的 Codex 登录凭据')
        self.import_btn.clicked.connect(self.import_current)
        toolbar.addWidget(self.import_btn)

        self.refresh_all_btn = QPushButton('全部刷新')
        self.refresh_all_btn.setFixedHeight(28)
        self.refresh_all_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.refresh_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        set_theme_style(
            self.refresh_all_btn,
            f'QPushButton{{{FONT_CSS}font-size:11px;background:transparent;color:{PRIMARY};border:1px solid {BORDER};border-radius:6px;padding:3px 4px;}}'
            f'QPushButton:hover{{background:{SELECTED};color:{INK};border-color:{PRIMARY};}}'
            f'QPushButton:pressed{{background:{BORDER};color:{INK};}}'
            f'QPushButton:disabled{{color:{MUTED};border-color:{TRACK};}}'
        )
        self.refresh_all_btn.setToolTip('一键刷新所有账户的凭据有效期并测算实时额度')
        self.refresh_all_btn.clicked.connect(self.refresh_all)
        toolbar.addWidget(self.refresh_all_btn)

        self.renew_all_btn = QPushButton('全部续期')
        self.renew_all_btn.setFixedHeight(28)
        self.renew_all_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.renew_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        set_theme_style(
            self.renew_all_btn,
            f'QPushButton{{{FONT_CSS}font-size:11px;background:transparent;color:{MUTED};border:1px solid {BORDER};border-radius:6px;padding:3px 4px;}}'
            f'QPushButton:hover{{background:{SELECTED};color:{INK};border-color:{PRIMARY};}}'
            f'QPushButton:pressed{{background:{BORDER};color:{INK};}}'
            f'QPushButton:disabled{{color:{MUTED};border-color:{TRACK};}}'
        )
        self.renew_all_btn.setToolTip('一键续期所有托管账户的凭据')
        self.renew_all_btn.clicked.connect(self.renew_all)
        toolbar.addWidget(self.renew_all_btn)

        main_layout.addLayout(toolbar)

        # Status and Feedback Banner
        self.status_banner = QWidget()
        self.status_banner.setObjectName('status_banner')
        self.status_banner.setMinimumHeight(28)
        self.status_banner.hide()
        sb_layout = QHBoxLayout(self.status_banner)
        sb_layout.setContentsMargins(8, 4, 8, 4)
        sb_layout.setSpacing(6)

        self.status_icon = QLabel('')
        sb_layout.addWidget(self.status_icon)

        self.status_line = QLabel('')
        self.status_line.setWordWrap(True)
        sb_layout.addWidget(self.status_line, 1)

        main_layout.addWidget(self.status_banner)

        # Accounts List Scroll Area
        self.scroll = hide_scrollbars(QScrollArea())
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        set_theme_style(self.scroll, f'QScrollArea{{background:transparent;border:0;}}')

        self.card_container = QWidget()
        set_theme_style(self.card_container, f'QWidget{{background:transparent;}}')
        self.card_layout = QVBoxLayout(self.card_container)
        self.card_layout.setContentsMargins(0, 0, 0, 0)
        self.card_layout.setSpacing(6)
        self.card_layout.addStretch()

        self.scroll.setWidget(self.card_container)
        main_layout.addWidget(self.scroll, 1)

    def refresh_list(self):
        while self.card_layout.count() > 1:
            item = self.card_layout.takeAt(0)
            w = item.widget() if item else None
            if w:
                w.setParent(None)
                w.deleteLater()

        accounts = self.manager.list_accounts()
        if not accounts:
            empty = QLabel('当前尚未保存任何托管账户。\n点击上方“新增账户”拉起授权，或“导入账户”。')
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            set_theme_style(empty, f'{FONT_CSS}font-size:11px;color:{MUTED};padding:30px 10px;')
            self.card_layout.insertWidget(0, empty)
            return

        for i, acc in enumerate(accounts):
            if i > 0:
                sep = QFrame()
                sep.setObjectName('card_divider')
                sep.setFixedHeight(1)
                set_theme_style(
                    sep,
                    'QFrame#card_divider { background-color: rgba(117, 97, 141, 0.25); border: none; margin: 3px 4px; }'
                )
                self.card_layout.insertWidget(self.card_layout.count() - 1, sep)

            card = AccountCard(acc)
            card.switchRequested.connect(self.on_switch_requested)
            card.refreshRequested.connect(self.on_refresh_requested)
            card.renameRequested.connect(self.on_rename_requested)
            card.deleteRequested.connect(self.on_delete_requested)
            self.card_layout.insertWidget(self.card_layout.count() - 1, card)

        self._check_auto_probe_missing_quotas(accounts)

    def _check_auto_probe_missing_quotas(self, accounts):
        missing = [a['id'] for a in accounts if not a.get('quota', {}).get('windows')]
        if missing and not getattr(self, '_probing_missing', False):
            self._probing_missing = True
            def probe_job():
                for aid in missing:
                    try:
                        self.manager.query_account_quota(aid)
                    except Exception:
                        pass
                return True
            worker = AccountWorker(probe_job, parent=self)
            def on_done(_):
                self._probing_missing = False
                self.refresh_list()
            worker.finished.connect(on_done)
            worker.failed.connect(lambda _: setattr(self, '_probing_missing', False))
            worker.start()

    def set_busy(self, busy: bool, message: str = '', status_type: str = 'info'):
        self.import_btn.setEnabled(not busy)
        self.login_btn.setEnabled(not busy)
        if hasattr(self, 'refresh_all_btn'):
            self.refresh_all_btn.setEnabled(not busy)
        self.renew_all_btn.setEnabled(not busy)

        for i in range(self.card_layout.count()):
            item = self.card_layout.itemAt(i)
            if item and item.widget() and hasattr(item.widget(), 'set_actions_enabled'):
                item.widget().set_actions_enabled(not busy)

        if hasattr(self, '_status_timer') and self._status_timer:
            self._status_timer.stop()
            self._status_timer = None

        if not message:
            self.status_banner.hide()
            return

        self.status_banner.show()
        self.status_line.setText(message)
        if busy or status_type == 'loading':
            self.status_icon.setText('⏳')
            set_theme_style(self.status_banner, f'QWidget#status_banner{{background:#f2edf7;border:1px solid {BORDER};border-radius:6px;}}')
            set_theme_style(self.status_line, f'{FONT_CSS}font-size:11px;color:{PRIMARY};font-weight:500;')
        elif status_type == 'success':
            self.status_icon.setText('✓')
            set_theme_style(self.status_banner, f'QWidget#status_banner{{background:#edf7f2;border:1px solid #c2e3d3;border-radius:6px;}}')
            set_theme_style(self.status_line, f'{FONT_CSS}font-size:11px;color:#28634e;font-weight:500;')
            # Auto-hide success feedback after at most 10 seconds
            self._status_timer = QTimer(self)
            self._status_timer.setSingleShot(True)
            self._status_timer.timeout.connect(self.status_banner.hide)
            self._status_timer.start(10000)
        elif status_type == 'error':
            self.status_icon.setText('✕')
            set_theme_style(self.status_banner, f'QWidget#status_banner{{background:{DANGER_SURFACE};border:1px solid #ecc5d8;border-radius:6px;}}')
            set_theme_style(self.status_line, f'{FONT_CSS}font-size:11px;color:{DANGER};font-weight:500;')
        else:
            self.status_icon.setText('ℹ')
            set_theme_style(self.status_banner, f'QWidget#status_banner{{background:{PANEL};border:1px solid {BORDER};border-radius:6px;}}')
            set_theme_style(self.status_line, f'{FONT_CSS}font-size:11px;color:{INK};')


    def import_current(self):
        try:
            alias, ok = QInputDialog.getText(
                self, '导入当前账户', '请输入此账户别名（如“个人主力”、“工作号”）：',
                text='个人主力'
            )
            if not ok:
                return
            acc = self.manager.import_current_account(alias.strip())
            self.set_busy(False, f'已成功导入账户：{acc.get("alias")}', 'success')
            self.refresh_list()
        except Exception as error:
            self.set_busy(False, f'导入失败：{error}', 'error')
            QMessageBox.warning(self, '导入失败', str(error))

    def choose_login_browser(self):
        if sys.platform != 'darwin':
            self.login_new_direct()
            return
        from codex_browser_login import installed_macos_browsers
        menu = QMenu(self)
        choices = {menu.addAction('系统默认浏览器'): None}
        browsers = installed_macos_browsers()
        if browsers:
            menu.addSeparator()
        for name, path in browsers:
            choices[menu.addAction(name)] = path
        selected = menu.exec(self.login_btn.mapToGlobal(QPoint(0, self.login_btn.height() + 2)))
        if selected in choices:
            self.login_new_direct(choices[selected])
        menu.deleteLater()

    def login_new_direct(self, browser=None):
        self.set_busy(True, '正在拉起官方登录通道，请在浏览器中完成授权…', 'loading')

        from codex_connection import find_executable, child_environment, cli_command

        def worker_fn():
            exe = find_executable()
            env = child_environment()
            with tempfile.TemporaryDirectory(prefix='bailong_new_login_') as temp_dir:
                env['CODEX_HOME'] = temp_dir
                if browser is None:
                    flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                    subprocess.run(cli_command(exe, 'login'), env=env, creationflags=flags, timeout=240)
                else:
                    from codex_browser_login import login_with_browser
                    cmd = cli_command(exe, 'app-server', '-c', 'cli_auth_credentials_store="file"')
                    login_with_browser(cmd, env, browser)
                target = Path(temp_dir) / 'auth.json'
                if not target.is_file():
                    raise OSError('未检测到 Codex 浏览器授权凭据。')
                return json.loads(target.read_text(encoding='utf-8'))

        worker = AccountWorker(worker_fn, parent=self)
        self.active_worker = worker

        def on_done(auth_data):
            self.set_busy(False, '登录成功，正在保存档案…', 'loading')
            try:
                from codex_account_manager import extract_account_metadata
                from codex_account_vault import vault_encrypt
                meta = extract_account_metadata(auth_data)
                acc_id = meta['account_id'] or f"acc_{int(time.time())}"
                cipher = vault_encrypt(json.dumps(auth_data, ensure_ascii=False), self.manager.vault_path.parent)
                record = {
                    'id': acc_id,
                    'account_id': meta['account_id'],
                    'user_id': meta['user_id'],
                    'email': meta['email'],
                    'name': meta['name'],
                    'plan_type': meta['plan_type'],
                    'alias': meta.get('name') or (meta.get('email', '').split('@')[0] if meta.get('email') else '') or '新账户',
                    'expires_at': meta['expires_at'],
                    'has_refresh_token': meta['has_refresh_token'],
                    'created_at': time.time(),
                    'last_used_at': time.time(),
                    'last_refreshed_at': time.time(),
                    'status': 'active',
                    'quota': {},
                    'tokens_cipher': cipher
                }
                with self.manager._lock:
                    self.manager._accounts[acc_id] = record
                    self.manager._save_vault()
                self.refresh_list()
                self.set_busy(False, f'新账户 [{record["alias"]}] 已成功加入托管！', 'success')
            except (OSError, ValueError) as error:
                self.set_busy(False, f'保存账户失败：{error}', 'error')

        def on_fail(err):
            self.set_busy(False, f'登录未完成：{err}', 'error')
            QMessageBox.warning(self, '登录未完成', str(err))

        worker.finished.connect(on_done)
        worker.failed.connect(on_fail)
        worker.start()

    def on_switch_requested(self, account_id: str):
        acc = self.manager.get_account(account_id)
        alias = acc.get('alias', '') if acc else account_id
        self.set_busy(True, f'正在切换至账户 [{alias}] 并同步重启 Codex…', 'loading')

        def switch_job():
            self.manager.switch_account(account_id, restart_codex=True)
            # Gentle quota probe for newly activated account if needed
            try:
                self.manager.query_account_quota(account_id)
            except Exception:
                pass
            return True

        worker = AccountWorker(switch_job, parent=self)
        self.active_worker = worker

        def on_done(res):
            self.set_busy(False, f'已成功切换至账户 [{alias}]，Codex 已同步重启！', 'success')
            self.refresh_list()
            self.accountChanged.emit(account_id)

        def on_fail(err):
            self.set_busy(False, f'切换失败：{err}', 'error')
            QMessageBox.critical(self, '切换失败', f'切换账户出现错误：{err}')

        worker.finished.connect(on_done)
        worker.failed.connect(on_fail)
        worker.start()

    def on_refresh_requested(self, account_id: str):
        acc = self.manager.get_account(account_id)
        alias = acc.get('alias', '') if acc else account_id
        self.set_busy(True, f'正在刷新 [{alias}] 凭据有效期与实时额度…', 'loading')

        worker = AccountWorker(self.manager.refresh_and_probe_account, account_id, parent=self)
        self.active_worker = worker

        def on_done(res):
            self.set_busy(False, f'[{alias}] 凭据有效期与实时额度已更新！', 'success')
            self.refresh_list()

        def on_fail(err):
            self.set_busy(False, f'刷新失败：{err}', 'error')
            QMessageBox.warning(self, '刷新失败', f'无法刷新该账户：{err}')

        worker.finished.connect(on_done)
        worker.failed.connect(on_fail)
        worker.start()

    def refresh_all(self):
        self.set_busy(True, '正在刷新所有账户的凭据有效期并测算实时额度…', 'loading')
        worker = AccountWorker(lambda: self.manager.refresh_all_accounts(force=True), parent=self)
        self.active_worker = worker

        def on_done(results):
            self.set_busy(False, '所有账户凭据有效期与实时额度已更新！', 'success')
            self.refresh_list()

        def on_fail(err):
            self.set_busy(False, f'刷新异常：{err}', 'error')
            QMessageBox.warning(self, '刷新异常', str(err))

        worker.finished.connect(on_done)
        worker.failed.connect(on_fail)
        worker.start()


    def on_rename_requested(self, account_id: str):
        acc = self.manager.get_account(account_id)
        if not acc:
            return
        current_alias = acc.get('alias', '')
        new_alias, ok = QInputDialog.getText(
            self, '重命名账户', '修改账户显示别名：', text=current_alias
        )
        if ok and new_alias.strip():
            self.manager.update_alias(account_id, new_alias.strip())
            self.refresh_list()

    def on_delete_requested(self, account_id: str):
        acc = self.manager.get_account(account_id)
        alias = acc.get('alias', '') if acc else account_id
        msg = f'确定要删除账户 [{alias}] 的本地隔离档案吗？\n\n删除后该账户的本地凭据将被移除（不会注销官方账户）。'
        if QMessageBox.question(self, '确认删除', msg) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.manager.delete_account(account_id)
            self.refresh_list()
        except Exception as error:
            QMessageBox.warning(self, '删除失败', str(error))

    def renew_all(self):
        self.set_busy(True, '正在自动巡检并续期所有托管账户…', 'loading')
        worker = AccountWorker(self.manager.refresh_all_accounts, parent=self)
        self.active_worker = worker

        def on_done(results):
            self.set_busy(False, '所有账户续期巡检完成！', 'success')
            self.refresh_list()
            QMessageBox.information(self, '续期完成', '所有账户凭据已完成续期巡检，保持有效。')

        def on_fail(err):
            self.set_busy(False, f'续期出现异常：{err}', 'error')
            QMessageBox.warning(self, '续期出现异常', str(err))

        worker.finished.connect(on_done)
        worker.failed.connect(on_fail)
        worker.start()


class CodexAccountsDialog(QDialog):
    """Standalone window version wrapping the pane."""
    accountChanged = Signal(str)

    def __init__(self, manager: CodexAccountManager = None, parent=None):
        super().__init__(parent)
        self.manager = manager or CodexAccountManager()
        self.setWindowTitle('Codex 账户管理')
        self.resize(520, 540)
        set_theme_style(
            self,
            editor_stylesheet(FONT_CSS) +
            f'QDialog{{background:{SURFACE};}}'
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        self.pane = CodexAccountsPane(self.manager, self)
        self.pane.accountChanged.connect(self.accountChanged.emit)
        layout.addWidget(self.pane)
