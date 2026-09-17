import sys
import time
import math
import random
import sqlite3
import requests
import json
import re
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QLabel, QTextEdit, QCheckBox, QMessageBox,
    QGroupBox, QDialog, QStackedWidget, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox, QFileDialog
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl
from PySide6.QtGui import QFont, QDesktopServices, QPainter, QLinearGradient, QColor

DONATION_URL = "https://www.donationalerts.com/r/ez1ckofc"
DB_NAME = "funpay_sales.db"


def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
                   CREATE TABLE IF NOT EXISTS products
                   (
                       id
                       INTEGER
                       PRIMARY
                       KEY
                       AUTOINCREMENT,
                       title
                       TEXT
                       NOT
                       NULL,
                       content
                       TEXT
                       NOT
                       NULL,
                       price
                       REAL
                       DEFAULT
                       0.0,
                       is_reusable
                       INTEGER
                       DEFAULT
                       0
                   )
                   """)
    cursor.execute("""
                   CREATE TABLE IF NOT EXISTS sales
                   (
                       id
                       INTEGER
                       PRIMARY
                       KEY
                       AUTOINCREMENT,
                       title
                       TEXT
                       NOT
                       NULL,
                       price
                       REAL
                       NOT
                       NULL,
                       buyer
                       TEXT
                       NOT
                       NULL,
                       date
                       TEXT
                       NOT
                       NULL
                   )
                   """)
    cursor.execute("""
                   CREATE TABLE IF NOT EXISTS settings
                   (
                       key
                       TEXT
                       PRIMARY
                       KEY,
                       value
                       TEXT
                       NOT
                       NULL
                   )
                   """)
    conn.commit()
    conn.close()


def set_setting(key, value):
    conn = sqlite3.connect(DB_NAME)
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()


def get_setting(key, default=""):
    conn = sqlite3.connect(DB_NAME)
    res = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return res[0] if res else default


def send_telegram(token, chat_id, message):
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        res = requests.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"}, timeout=5)
        return res.status_code == 200
    except:
        return False


def db_fetch_products(filter_text=""):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    if filter_text:
        cursor.execute("SELECT id, title, content, price, is_reusable FROM products WHERE title LIKE ?",
                       (f"%{filter_text}%",))
    else:
        cursor.execute("SELECT id, title, content, price, is_reusable FROM products")
    rows = cursor.fetchall()
    conn.close()
    return rows


def db_add_product(title, content, price, is_reusable):
    conn = sqlite3.connect(DB_NAME)
    conn.execute("INSERT INTO products (title, content, price, is_reusable) VALUES (?, ?, ?, ?)",
                 (title, content, price, is_reusable))
    conn.commit()
    conn.close()


def db_delete_product(prod_id):
    conn = sqlite3.connect(DB_NAME)
    conn.execute("DELETE FROM products WHERE id = ?", (prod_id,))
    conn.commit()
    conn.close()


def db_add_sale(title, price, buyer):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB_NAME)
    conn.execute("INSERT INTO sales (title, price, buyer, date) VALUES (?, ?, ?, ?)", (title, price, buyer, now_str))
    conn.commit()
    conn.close()


def db_fetch_sales():
    conn = sqlite3.connect(DB_NAME)
    rows = conn.execute("SELECT title, price, buyer, date FROM sales ORDER BY id DESC").fetchall()
    conn.close()
    return rows


def db_clear_sales():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("DELETE FROM sales")
    conn.commit()
    conn.close()


class FunPayAPI:
    def __init__(self, golden_key, proxy=None):
        self.golden_key = golden_key
        self.session = requests.Session()
        self.session.cookies.set("golden_key", golden_key, domain="funpay.com")
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        })
        if proxy:
            self.session.proxies = {"http": proxy, "https": proxy}
        self.user_id = None
        self.username = None

    def check_auth(self):
        try:
            res = self.session.get("https://funpay.com/", timeout=8)
            if res.status_code != 200:
                return False, f"HTTP код: {res.status_code}"

            if 'class="user-link-name"' in res.text:
                m_name = re.search(r'class="user-link-name">([^<]+)<', res.text)
                m_id = re.search(r'data-id="(\d+)"', res.text)
                self.username = m_name.group(1).strip() if m_name else "Юзер"
                self.user_id = m_id.group(1) if m_id else "0"
                return True, f"Успешно: {self.username}"
            return False, "Сессия не найдена (неверный ключ?)"
        except Exception as e:
            return False, str(e)

    def get_updates(self):
        try:
            payload = {
                "objects": json.dumps([{"type": "chat_bookmark", "id": self.user_id, "data": False}]),
                "request": False,
                "csrf_token": ""
            }
            res = self.session.post("https://funpay.com/runner/", data=payload, timeout=8)
            if res.status_code == 200:
                return res.json()
        except:
            pass
        return None

    def send_msg(self, node_id, text):
        try:
            payload = {
                "objects": json.dumps([{"type": "chat_node", "id": str(node_id), "data": {"node": str(node_id)}}]),
                "request": json.dumps({"action": "chat_message", "data": {"node": str(node_id), "text": text}})
            }
            res = self.session.post("https://funpay.com/runner/", data=payload, timeout=8)
            return res.status_code == 200
        except:
            return False


class BotThread(QThread):
    log_signal = Signal(str)
    sale_signal = Signal(str, float, str)

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.running = True
        self.api = FunPayAPI(cfg["token"], cfg.get("proxy"))
        self.seen_nodes = set()

    def run(self):
        self.log_signal.emit("Стартуем бота...")
        ok, err = self.api.check_auth()
        if not ok:
            self.log_signal.emit(f"Ошибка авторизации: {err}")
            return

        self.log_signal.emit(f"Авторизованы как {self.api.username}")
        if self.cfg["tg_notify"]:
            send_telegram(self.cfg["tg_token"], self.cfg["tg_chat"], f"Бот запущен! Аккаунт: {self.api.username}")

        while self.running:
            data = self.api.get_updates()
            if data and "objects" in data:
                for obj in data["objects"]:
                    if obj.get("type") == "chat_node":
                        nd = obj.get("data", {})
                        node_id = str(nd.get("node"))
                        last_msg = nd.get("last_message", "")
                        buyer = nd.get("user_username", "Клиент")

                        if node_id and node_id not in self.seen_nodes:
                            self.seen_nodes.add(node_id)
                            self.log_signal.emit(f"Сообщение от {buyer}: {last_msg}")

                            if self.cfg["auto_reply"] and self.cfg["reply_text"]:
                                self.api.send_msg(node_id, self.cfg["reply_text"])

                            if self.cfg["auto_deliver"]:
                                self.check_delivery(node_id, last_msg, buyer)
            time.sleep(6)

    def check_delivery(self, node_id, text, buyer):
        products = db_fetch_products()
        for p_id, title, content, price, reusable in products:
            if title.lower() in text.lower():
                self.log_signal.emit(f"Выдаем товар по запросу: {title}")
                msg = f"Спасибо за покупку! Вот ваш товар:\n\n{content}"
                if self.api.send_msg(node_id, msg):
                    self.log_signal.emit(f"Успешно выдано игроку {buyer}")
                    if not reusable:
                        db_delete_product(p_id)
                    self.sale_signal.emit(title, price, buyer)
                    if self.cfg["tg_notify"]:
                        send_telegram(self.cfg["tg_token"], self.cfg["tg_chat"],
                                      f"Продажа!\nЛот: {title}\nЦена: {price}\nПокупатель: {buyer}")
                break

    def stop(self):
        self.running = False


# Визуальные компоненты для крутого стиля
class CircleParticle:
    def __init__(self, w, h):
        self.x = random.uniform(0, max(w, 800))
        self.y = random.uniform(0, max(h, 600))
        self.r = random.uniform(25, 75)
        self.dx = random.uniform(-0.5, 0.5)
        self.dy = random.uniform(-0.5, 0.5)
        self.color = random.choice([
            QColor(99, 102, 241, 40), QColor(168, 85, 247, 35),
            QColor(236, 72, 153, 30), QColor(59, 130, 246, 35)
        ])

    def move(self, w, h):
        self.x += self.dx
        self.y += self.dy
        if self.x - self.r < 0 or self.x + self.r > w: self.dx *= -1
        if self.y - self.r < 0 or self.y + self.r > h: self.dy *= -1


class AnimatedBackground(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.angle = 0
        self.particles = []
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.animate)
        self.timer.start(30)

    def resizeEvent(self, event):
        if not self.particles:
            self.particles = [CircleParticle(self.width(), self.height()) for _ in range(10)]
        super().resizeEvent(event)

    def animate(self):
        self.angle = (self.angle + 1) % 360
        w, h = self.width(), self.height()
        for p in self.particles: p.move(w, h)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        rad = math.radians(self.angle)
        cx, cy = self.width() / 2, self.height() / 2
        rx, ry = math.cos(rad) * cx, math.sin(rad) * cy

        grad = QLinearGradient(cx - rx, cy - ry, cx + rx, cy + ry)
        grad.setColorAt(0.0, QColor("#0A0E1A"))
        grad.setColorAt(0.5, QColor("#141B2D"))
        grad.setColorAt(1.0, QColor("#0B0F19"))
        p.fillRect(self.rect(), grad)

        p.setPen(Qt.NoPen)
        for part in self.particles:
            p.setBrush(part.color)
            p.drawEllipse(int(part.x - part.r), int(part.y - part.r), int(part.r * 2), int(part.r * 2))


class NavButton(QPushButton):
    def __init__(self, text, amber=False):
        super().__init__(text)
        self.amber = amber
        self.active = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(44)
        self.refresh()

    def set_active(self, state):
        self.active = state
        self.refresh()

    def refresh(self, hover=False):
        if self.amber:
            bg = "#FBBF24" if hover else "#D97706"
            color = "#000000"
            border = "1px solid #FDE68A"
        elif self.active:
            bg = "#6366F1"
            color = "#FFFFFF"
            border = "1px solid #818CF8"
        else:
            bg = "rgba(51, 65, 85, 0.8)" if hover else "rgba(30, 41, 59, 0.4)"
            color = "#FFFFFF" if hover else "#94A3B8"
            border = "1px solid rgba(255, 255, 255, 0.1)"

        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg}; color: {color};
                border-radius: 8px; font-weight: bold; font-size: 13px;
                padding-left: 14px; border: {border}; text-align: left;
            }}
        """)

    def enterEvent(self, event):
        self.refresh(hover=True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.refresh(hover=False)
        super().leaveEvent(event)


class DonationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Поддержка")
        self.setFixedSize(420, 220)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setStyleSheet(
            "QDialog { background-color: #1E293B; border: 2px solid #6366F1; border-radius: 12px; color: #fff; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel("❤️ Поддержите разработчика!")
        title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        desc = QLabel("Бот работает полностью локально. Вы можете поддержать автора донатом!")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #94A3B8; font-size: 12px;")
        desc.setAlignment(Qt.AlignCenter)
        layout.addWidget(desc)

        btn_donate = QPushButton("🎁 Донат (DonationAlerts)")
        btn_donate.setCursor(Qt.PointingHandCursor)
        btn_donate.setFixedHeight(40)
        btn_donate.setStyleSheet("background: #F59E0B; color: #000; font-weight: bold; border-radius: 8px;")
        btn_donate.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(DONATION_URL)))
        layout.addWidget(btn_donate)

        self.sec = 3
        self.btn_close = QPushButton(f"Закрыть ({self.sec}с)")
        self.btn_close.setEnabled(False)
        self.btn_close.setFixedHeight(35)
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.setStyleSheet("background: #334155; color: #94A3B8; font-weight: bold; border-radius: 8px;")
        self.btn_close.clicked.connect(self.accept)
        layout.addWidget(self.btn_close)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)

    def tick(self):
        self.sec -= 1
        if self.sec > 0:
            self.btn_close.setText(f"Закрыть ({self.sec}с)")
        else:
            self.timer.stop()
            self.btn_close.setEnabled(True)
            self.btn_close.setText("✕ Закрыть")
            self.btn_close.setStyleSheet("background: #EF4444; color: #fff; font-weight: bold; border-radius: 8px;")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        init_db()
        self.worker = None
        self.setWindowTitle("FunPay Bot — Sales Edition")
        self.resize(1020, 660)

        # Красивый анимированный фон
        self.bg_widget = AnimatedBackground(self)
        self.setCentralWidget(self.bg_widget)

        self.setStyleSheet("""
            QWidget { color: #F8FAFC; font-family: 'Segoe UI', sans-serif; font-size: 13px; }
            QFrame#Sidebar, QFrame#TabContainer { background-color: rgba(15, 23, 42, 0.95); border-radius: 12px; border: 1px solid rgba(255, 255, 255, 0.1); }
            QGroupBox { border: 1px solid rgba(255, 255, 255, 0.15); border-radius: 8px; margin-top: 10px; padding-top: 15px; font-weight: bold; color: #818CF8; background-color: rgba(30, 41, 59, 0.7); }
            QLineEdit, QTextEdit, QComboBox { background-color: rgba(15, 23, 42, 0.95); border: 1px solid #334155; border-radius: 6px; padding: 8px; color: #FFFFFF; }
            QLineEdit:focus, QTextEdit:focus { border: 1px solid #6366F1; }
            QComboBox QAbstractItemView { background-color: #1E293B; color: #FFFFFF; selection-background-color: #6366F1; }
            QTableWidget { background-color: rgba(15, 23, 42, 0.95); border: 1px solid #334155; gridline-color: #334155; border-radius: 6px; color: #FFFFFF; }
            QHeaderView::section { background-color: #0F172A; color: #94A3B8; padding: 6px; border: 1px solid #334155; font-weight: bold; }
        """)

        main_layout = QHBoxLayout(self.bg_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)

        # Сайдбар с кнопками
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(12, 15, 12, 15)

        logo = QLabel("⚡ FP Sales")
        logo.setFont(QFont("Segoe UI", 16, QFont.Bold))
        logo.setStyleSheet("color: #6366F1; margin-bottom: 10px;")
        sb_layout.addWidget(logo)

        self.btn_logs = NavButton("📝 Управление и Логи")
        self.btn_settings = NavButton("🔑 Настройки")
        self.btn_products = NavButton("📦 База Товаров")
        self.btn_stats = NavButton("📊 Статистика")

        self.nav_btns = [self.btn_logs, self.btn_settings, self.btn_products, self.btn_stats]
        for idx, btn in enumerate(self.nav_btns):
            btn.clicked.connect(lambda _, i=idx: self.switch_tab(i))
            sb_layout.addWidget(btn)

        sb_layout.addStretch()

        btn_donate_menu = NavButton("❤️ Поддержать", amber=True)
        btn_donate_menu.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(DONATION_URL)))
        sb_layout.addWidget(btn_donate_menu)

        main_layout.addWidget(sidebar, stretch=1)

        # Контейнер для страниц
        tab_container = QFrame()
        tab_container.setObjectName("TabContainer")
        tc_layout = QVBoxLayout(tab_container)
        tc_layout.setContentsMargins(15, 15, 15, 15)

        self.stack = QStackedWidget()
        tc_layout.addWidget(self.stack)

        main_layout.addWidget(tab_container, stretch=3)

        self.init_page_logs()
        self.init_page_settings()
        self.init_page_products()
        self.init_page_stats()

        self.load_settings()
        self.switch_tab(0)

        QTimer.singleShot(400, self.show_donation)

    def show_donation(self):
        dlg = DonationDialog(self)
        dlg.exec()

    def switch_tab(self, index):
        for idx, btn in enumerate(self.nav_btns):
            btn.set_active(idx == index)
        self.stack.setCurrentIndex(index)

    def init_page_logs(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        row = QHBoxLayout()
        self.btn_start = QPushButton("▶ Запустить бота")
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.setStyleSheet(
            "background-color: #10B981; color: white; font-size: 14px; font-weight: bold; padding: 12px; border-radius: 8px;")
        self.btn_start.clicked.connect(self.start_bot)

        self.btn_stop = QPushButton("⏹ Остановить бота")
        self.btn_stop.setCursor(Qt.PointingHandCursor)
        self.btn_stop.setStyleSheet(
            "background-color: #EF4444; color: white; font-size: 14px; font-weight: bold; padding: 12px; border-radius: 8px;")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_bot)

        row.addWidget(self.btn_start)
        row.addWidget(self.btn_stop)
        layout.addLayout(row)

        gb = QGroupBox("📲 Telegram Уведомления")
        l = QHBoxLayout()
        self.tg_token = QLineEdit()
        self.tg_token.setPlaceholderText("Bot Token (@BotFather)")
        self.tg_chat = QLineEdit()
        self.tg_chat.setPlaceholderText("Ваш Chat ID")
        l.addWidget(self.tg_token)
        l.addWidget(self.tg_chat)
        gb.setLayout(l)
        layout.addWidget(gb)

        gb_logs = QGroupBox("📝 Живая консоль бота")
        ll = QVBoxLayout()
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        ll.addWidget(self.log_box)
        gb_logs.setLayout(ll)
        layout.addWidget(gb_logs)

        self.stack.addWidget(page)

    def init_page_settings(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        btn_save = QPushButton("💾 Сохранить настройки")
        btn_save.setCursor(Qt.PointingHandCursor)
        btn_save.setStyleSheet(
            "background-color: #10B981; color: white; font-weight: bold; padding: 10px; border-radius: 8px;")
        btn_save.clicked.connect(self.save_settings)
        layout.addWidget(btn_save)

        gb = QGroupBox("🔑 Авторизация FunPay")
        l = QVBoxLayout()
        self.inp_token = QLineEdit()
        self.inp_token.setPlaceholderText("Введите ваш golden_key")
        l.addWidget(QLabel("Golden Key:"))
        l.addWidget(self.inp_token)
        gb.setLayout(l)
        layout.addWidget(gb)

        gb2 = QGroupBox("⚙️ Автоматизация")
        l2 = QVBoxLayout()
        self.chk_reply = QCheckBox("Включить автоответчик покупателям")
        self.inp_reply_text = QLineEdit()
        self.inp_reply_text.setPlaceholderText("Текст автоответа")
        self.chk_deliver = QCheckBox("Включить автовыдачу товаров из базы")
        l2.addWidget(self.chk_reply)
        l2.addWidget(self.inp_reply_text)
        l2.addWidget(self.chk_deliver)
        gb2.setLayout(l2)
        layout.addWidget(gb2)

        gb3 = QGroupBox("🌐 Прокси Сервер")
        l3 = QVBoxLayout()
        self.inp_proxy = QLineEdit()
        self.inp_proxy.setPlaceholderText("http://user:pass@ip:port")
        l3.addWidget(self.inp_proxy)
        gb3.setLayout(l3)
        layout.addWidget(gb3)

        layout.addStretch()
        self.stack.addWidget(page)

    def init_page_products(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        gb = QGroupBox("➕ Добавить товар")
        l = QVBoxLayout()
        r = QHBoxLayout()
        self.p_title = QLineEdit()
        self.p_title.setPlaceholderText("Название лота / Ключевое слово")
        self.p_price = QLineEdit()
        self.p_price.setPlaceholderText("Цена (₽)")
        self.p_price.setFixedWidth(100)
        self.p_type = QComboBox()
        self.p_type.addItems(["Одноразовый ключ", "Многоразовый текст"])
        r.addWidget(self.p_title)
        r.addWidget(self.p_price)
        r.addWidget(self.p_type)

        self.p_content = QLineEdit()
        self.p_content.setPlaceholderText("Содержимое товара (ссылка / ключ / текст)")

        btn_add = QPushButton("💾 Добавить в базу")
        btn_add.setCursor(Qt.PointingHandCursor)
        btn_add.setStyleSheet(
            "background-color: #6366F1; color: white; font-weight: bold; padding: 8px; border-radius: 6px;")
        btn_add.clicked.connect(self.add_product)

        l.addLayout(r)
        l.addWidget(self.p_content)
        l.addWidget(btn_add)
        gb.setLayout(l)
        layout.addWidget(gb)

        gb_list = QGroupBox("📦 Список товаров")
        l_list = QVBoxLayout()

        h_tools = QHBoxLayout()
        self.p_search = QLineEdit()
        self.p_search.setPlaceholderText("🔍 Поиск по названию...")
        self.p_search.textChanged.connect(lambda t: self.load_products(t))

        btn_del = QPushButton("🗑 Удалить выбранное")
        btn_del.setCursor(Qt.PointingHandCursor)
        btn_del.setStyleSheet(
            "background-color: #EF4444; color: white; font-weight: bold; padding: 8px; border-radius: 6px;")
        btn_del.clicked.connect(self.delete_product)

        h_tools.addWidget(self.p_search)
        h_tools.addWidget(btn_del)
        l_list.addLayout(h_tools)

        self.table_p = QTableWidget(0, 5)
        self.table_p.setHorizontalHeaderLabels(["ID", "Название", "Содержимое", "Цена", "Тип"])
        self.table_p.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        l_list.addWidget(self.table_p)

        gb_list.setLayout(l_list)
        layout.addWidget(gb_list)

        self.stack.addWidget(page)
        self.load_products()

    def init_page_stats(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        cards = QHBoxLayout()
        self.lbl_stats = QLabel("Продаж: 0  |  Заработано: 0.0 ₽")
        self.lbl_stats.setFont(QFont("Segoe UI", 13, QFont.Bold))
        self.lbl_stats.setStyleSheet(
            "background: rgba(30, 41, 59, 0.8); padding: 12px; border-radius: 8px; border: 1px solid #334155;")
        cards.addWidget(self.lbl_stats)
        layout.addLayout(cards)

        gb = QGroupBox("📊 История продаж")
        sl = QVBoxLayout()

        btn_clear = QPushButton("🧹 Очистить историю")
        btn_clear.setCursor(Qt.PointingHandCursor)
        btn_clear.setStyleSheet(
            "background-color: #EF4444; color: white; font-weight: bold; padding: 6px 12px; border-radius: 6px;")
        btn_clear.clicked.connect(self.clear_sales)

        h_btns = QHBoxLayout()
        h_btns.addWidget(btn_clear)
        h_btns.addStretch()
        sl.addLayout(h_btns)

        self.table_sales = QTableWidget(0, 4)
        self.table_sales.setHorizontalHeaderLabels(["Товар", "Цена", "Покупатель", "Дата"])
        self.table_sales.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        sl.addWidget(self.table_sales)

        gb.setLayout(sl)
        layout.addWidget(gb)

        self.stack.addWidget(page)
        self.load_sales()

    def load_settings(self):
        self.inp_token.setText(get_setting("token"))
        self.inp_proxy.setText(get_setting("proxy"))
        self.inp_reply_text.setText(get_setting("reply_text", "Спасибо за покупку!"))
        self.chk_reply.setChecked(get_setting("auto_reply") == "1")
        self.chk_deliver.setChecked(get_setting("auto_deliver") == "1")
        self.tg_token.setText(get_setting("tg_token"))
        self.tg_chat.setText(get_setting("tg_chat"))

    def save_settings(self):
        set_setting("token", self.inp_token.text().strip())
        set_setting("proxy", self.inp_proxy.text().strip())
        set_setting("reply_text", self.inp_reply_text.text())
        set_setting("auto_reply", "1" if self.chk_reply.isChecked() else "0")
        set_setting("auto_deliver", "1" if self.chk_deliver.isChecked() else "0")
        set_setting("tg_token", self.tg_token.text().strip())
        set_setting("tg_chat", self.tg_chat.text().strip())
        QMessageBox.information(self, "Успех", "Настройки сохранены!")

    def add_product(self):
        title = self.p_title.text().strip()
        content = self.p_content.text().strip()
        try:
            price = float(self.p_price.text().strip().replace(",", "."))
        except:
            price = 0.0
        reusable = 1 if self.p_type.currentIndex() == 1 else 0

        if not title or not content:
            QMessageBox.warning(self, "Ошибка", "Заполните название и содержимое!")
            return

        db_add_product(title, content, price, reusable)
        self.p_title.clear()
        self.p_content.clear()
        self.p_price.clear()
        self.load_products()

    def load_products(self, filter_text=""):
        rows = db_fetch_products(filter_text)
        self.table_p.setRowCount(0)
        for r_idx, row in enumerate(rows):
            self.table_p.insertRow(r_idx)
            for c_idx, val in enumerate(row):
                item = QTableWidgetItem(str(val))
                if c_idx == 4:
                    item.setText("Многоразовый" if val == 1 else "Одноразовый")
                self.table_p.setItem(r_idx, c_idx, item)

    def delete_product(self):
        row = self.table_p.currentRow()
        if row >= 0:
            p_id = int(self.table_p.item(row, 0).text())
            db_delete_product(p_id)
            self.load_products()

    def load_sales(self):
        rows = db_fetch_sales()
        self.table_sales.setRowCount(0)
        earned = 0.0
        for r_idx, (title, price, buyer, date) in enumerate(rows):
            self.table_sales.insertRow(r_idx)
            self.table_sales.setItem(r_idx, 0, QTableWidgetItem(title))
            self.table_sales.setItem(r_idx, 1, QTableWidgetItem(f"{price} ₽"))
            self.table_sales.setItem(r_idx, 2, QTableWidgetItem(buyer))
            self.table_sales.setItem(r_idx, 3, QTableWidgetItem(date))
            earned += price
        self.lbl_stats.setText(f"Продаж: {len(rows)}  |  Заработано: {earned:.2f} ₽")

    def clear_sales(self):
        if QMessageBox.question(self, "Подтверждение", "Очистить историю продаж?") == QMessageBox.Yes:
            db_clear_sales()
            self.load_sales()

    def record_sale(self, title, price, buyer):
        db_add_sale(title, price, buyer)
        self.load_sales()

    def start_bot(self):
        token = self.inp_token.text().strip()
        if not token:
            QMessageBox.warning(self, "Ошибка", "Укажите Golden Key в настройках!")
            self.switch_tab(1)
            return

        cfg = {
            "token": token,
            "proxy": self.inp_proxy.text().strip() or None,
            "auto_reply": self.chk_reply.isChecked(),
            "reply_text": self.inp_reply_text.text(),
            "auto_deliver": self.chk_deliver.isChecked(),
            "tg_notify": bool(self.tg_token.text().strip() and self.tg_chat.text().strip()),
            "tg_token": self.tg_token.text().strip(),
            "tg_chat": self.tg_chat.text().strip()
        }

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)

        self.worker = BotThread(cfg)
        self.worker.log_signal.connect(lambda s: self.log_box.append(f"[{datetime.now().strftime('%H:%M:%S')}] {s}"))
        self.worker.sale_signal.connect(self.record_sale)
        self.worker.start()

    def stop_bot(self):
        if self.worker:
            self.worker.stop()
            self.worker.wait()
            self.worker = None
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.log_box.append(f"[{datetime.now().strftime('%H:%M:%S')}] Бот остановлен.")

    def closeEvent(self, event):
        self.stop_bot()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())