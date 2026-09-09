"""
Dialog login kustom buat plugin AIM Editor. Ini BUKAN dialog koneksi database
bawaan QGIS — user login pake akun aplikasi (REST API backend-aim), bukan
kredensial PostgreSQL langsung. Habis login sukses, dialog ini juga otomatis
ambil hak akses (permissions) dan kredensial role PostgreSQL yang udah
dipetakan sesuai permission user tsb, biar caller (main_plugin.py) tinggal
pakai hasilnya langsung tanpa perlu tau detail API-nya.
"""

from qgis.PyQt.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QLineEdit,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
)
from qgis.PyQt.QtCore import Qt

from .api_client import ApiClient, ApiError, DbCredentials
from . import settings as aim_settings


class LoginDialog(QDialog):
    """Kalo user klik OK dan login berhasil (accept), hasil yang bisa
    diambil caller lewat properti instance ini:
      - self.token: token PASETO (string opaque)
      - self.me: dict lengkap dari response GET /me (roles, permissions, dst)
      - self.db_credentials: DbCredentials, kredensial role Postgres

    Field "Server URL" di dialog ini nyimpen base URL REST API lewat
    settings.py (QSettings) -- bukan hardcode, biar gampang beda antara
    environment dev/staging/prod tanpa perlu edit kode plugin. Field ini
    di-prefill dari nilai tersimpan terakhir (atau default kalo first run).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AIM Editor - Login")
        self.setMinimumWidth(340)

        self.api_client: ApiClient = None
        self.token = None
        self.db_credentials: DbCredentials = None
        self.me: dict = {}

        self.server_url_edit = QLineEdit(self)
        self.server_url_edit.setText(aim_settings.get_base_url())

        # login_id bisa diisi username ATAU email, samain aja sama backend
        self.login_id_edit = QLineEdit(self)
        self.password_edit = QLineEdit(self)
        self.password_edit.setEchoMode(QLineEdit.Password)

        form = QFormLayout()
        form.addRow("Server URL:", self.server_url_edit)
        form.addRow("Username/Email:", self.login_id_edit)
        form.addRow("Password:", self.password_edit)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self._on_login_clicked)
        buttons.rejected.connect(self.reject)
        self.buttons = buttons

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(self.status_label)
        layout.addWidget(buttons)
        self.setLayout(layout)

        self.password_edit.returnPressed.connect(self._on_login_clicked)

    def showEvent(self, event):
        """Override showEvent (BUKAN cuma setFocus() di __init__) -- Qt
        suka reset fokus widget pas dialog beneran ditampilkan lewat
        exec_()/show(), jadi setFocus() di __init__ doang kadang ke-
        override lagi. showEvent() dipanggil TIAP KALI dialog ini muncul,
        jadi paling reliable buat mastiin fokus awal selalu jatuh ke
        Username/Email (diminta user 2026-09-09) -- server URL jarang
        perlu diganti tiap login (udah keisi otomatis dari settings
        tersimpan), jadi username/email yang paling sering perlu diketik
        duluan pas dialog ini kebuka."""
        super().showEvent(event)
        self.login_id_edit.setFocus()

    def _on_login_clicked(self):
        server_url = self.server_url_edit.text().strip()
        login_id = self.login_id_edit.text().strip()
        password = self.password_edit.text()

        if not server_url:
            self.status_label.setText("Server URL wajib diisi.")
            return
        if not login_id or not password:
            self.status_label.setText("Username/email dan password wajib diisi.")
            return

        self.buttons.setEnabled(False)
        self.status_label.setText("Sedang login...")
        # CATATAN: buat UX yang lebih mulus, proses login+fetch ini idealnya
        # jalan di QThread/QgsTask biar UI ga freeze. Sengaja dibikin sinkron
        # dulu di skeleton ini biar alurnya jelas kebaca.
        try:
            self.api_client = ApiClient(server_url)
            self.token = self.api_client.login(login_id, password)
            self.me = self.api_client.get_me()
            self.db_credentials = self.api_client.get_db_credentials()
        except ApiError as exc:
            self.status_label.setText("")
            QMessageBox.critical(self, "Login gagal", str(exc))
            # setEnabled(True) SENGAJA dipindah ke SETELAH QMessageBox.critical()
            # selesai (bukan sebelum) -- diminta user (2026-09-09) abis lapor
            # bug nyata: dialog error muncul 2x identik begitu klik OK pertama.
            # Root cause: kalo tombol di-enable SEBELUM critical() ditutup, ada
            # jendela waktu kecil di mana mouse-release event dari klik OK di
            # message box bisa "nge-leak"/ke-propagate ke tombol OK dialog
            # login yang udah aktif lagi di belakangnya (message box modal
            # nutup duluan, baru event mouse selesai diproses Qt event loop) --
            # nge-trigger _on_login_clicked() lagi dengan kredensial yang sama,
            # makanya errornya identik persis. Nutup tombol tetep disabled
            # sampe message box beneran selesai ditutup ngilangin jendela
            # race ini.
            self.buttons.setEnabled(True)
            return

        # Login sukses -- simpen server URL ini biar next time udah keisi
        # otomatis (bukan cuma pas login berhasil doang biar user ga
        # ke-save URL yang salah/typo kalo login gagal).
        aim_settings.set_base_url(server_url)

        self.accept()
