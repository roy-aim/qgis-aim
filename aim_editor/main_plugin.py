"""
Orkestrator utama plugin AIM Editor. Ini entry point yang di-load QGIS lewat
classFactory() di __init__.py -- QGIS bakal instantiate class AimEditorPlugin
ini dan manggil initGui()/unload() di titik yang tepat sesuai lifecycle plugin
standar (initGui pas plugin diaktifkan, unload pas plugin dinonaktifkan/QGIS
ditutup).

TAHAP 2 (sekarang): tombol toolbar udah nyambung ke alur login sungguhan --
buka LoginDialog, simpen kredensial DB ke QgsAuthManager. Alur search-adhp
dan load-layer (Tahap 3-4) belum ada, masih placeholder.
"""

from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import QgsApplication

from .login_dialog import LoginDialog
from .auth_manager import AuthConfigManager


class AimEditorPlugin:
    """Class utama plugin. QGIS pegang SATU instance ini selama plugin
    aktif -- state sesi (token, kredensial, dsb) disimpan sebagai atribut
    instance di sini."""

    def __init__(self, iface):
        # `iface` ini QgisInterface, jembatan resmi buat plugin ngakses
        # QGIS (canvas, layer tree, menu, toolbar, dst). Selalu dikasih
        # QGIS pas instantiate plugin, jangan bikin sendiri.
        self.iface = iface
        self.actions = []
        self.menu = "&AIM Editor"
        self.toolbar = self.iface.addToolBar("AIM Editor")
        self.toolbar.setObjectName("AIMEditorToolbar")

        # State sesi login -- None berarti belum login. `me` isinya response
        # GET /me lengkap (roles, permissions, dst), dipake Tahap 3-4 nanti
        # buat mutusin layer mana yang boleh dimuat.
        self.auth_manager = AuthConfigManager()
        self.token = None
        self.me = None
        self.db_credentials = None

    def tr(self, message):
        """Wrapper translasi standar QGIS plugin. Dipake konsisten di
        semua string yang bakal keliatan user, biar gampang nambah
        dukungan bahasa lain belakangan (lihat i18n/ di struktur folder)."""
        return QCoreApplication.translate("AimEditorPlugin", message)

    def add_action(self, icon_path, text, callback, enabled_flag=True,
                   add_to_menu=True, add_to_toolbar=True, status_tip=None,
                   whats_this=None, parent=None):
        """Helper buat daftarin satu QAction ke toolbar/menu sekaligus.
        Pola ini standar banget di plugin QGIS (mirip yang di-generate
        Plugin Builder), jadi kalau nanti nambah action baru (mis. tombol
        Login, tombol Cari Bandara) tinggal panggil ini lagi."""
        icon = QgsApplication.getThemeIcon(icon_path) if icon_path else None
        action = QAction(icon, text, parent) if icon else QAction(text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)
        if whats_this is not None:
            action.setWhatsThis(whats_this)
        if add_to_toolbar:
            self.toolbar.addAction(action)
        if add_to_menu:
            self.iface.addPluginToMenu(self.menu, action)

        self.actions.append(action)
        return action

    def initGui(self):
        """Dipanggil QGIS sekali pas plugin diaktifkan. Pasang satu tombol
        "Buka AIM Editor" yang sekarang beneran mulai alur login."""
        # Ikon custom (icons/icon.png) belum digambar -- pakai ikon tema
        # bawaan QGIS dulu ("mActionAddLayer" cukup representatif buat
        # placeholder) biar plugin tetap kelihatan di toolbar tanpa nunggu
        # aset custom. Ganti ke icons/icon.png begitu ada.
        self.add_action(
            icon_path="mActionAddLayer.svg",
            text=self.tr("Buka AIM Editor"),
            callback=self.run,
            parent=self.iface.mainWindow(),
            status_tip=self.tr("Login dan mulai edit geometri Apron/Taxiway"),
        )

    def unload(self):
        """Dipanggil QGIS pas plugin dinonaktifkan atau QGIS ditutup.
        WAJIB bersih-bersih semua yang dipasang initGui() -- action dari
        menu/toolbar, plus toolbar-nya sendiri. WAJIB juga hapus kredensial
        DB dari QgsAuthManager (lihat docs/business-rules.md Bagian 3.3
        soal kenapa ini wajib -- kredensial ga boleh nyangkut lebih lama
        dari masa sesi)."""
        for action in self.actions:
            self.iface.removePluginMenu(self.menu, action)
            self.iface.removeToolBarIcon(action)
        del self.toolbar

        self.auth_manager.remove_credentials()

    def run(self):
        """Callback tombol toolbar/menu. Buka LoginDialog, dan kalo login
        sukses, simpen kredensial DB ke QgsAuthManager. Alur search-adhp
        dan load-layer (Tahap 3-4, lihat docs/implementation-plan.md) belum
        dipanggil dari sini -- masih placeholder pesan info doang."""
        dialog = LoginDialog(parent=self.iface.mainWindow())
        if not dialog.exec_():
            # User klik Cancel atau nutup dialog -- ga ada error, cuma
            # ga lanjut apa-apa.
            return

        self.token = dialog.token
        self.me = dialog.me
        self.db_credentials = dialog.db_credentials

        try:
            if self.auth_manager.config_id:
                # Udah pernah login di sesi QGIS ini (user klik tombol lagi
                # tanpa restart QGIS) -- UPDATE config yang sama, JANGAN
                # store_credentials() lagi. Kalo dipaksa create baru tiap
                # login ulang, config lama nggak pernah kehapus otomatis
                # dan numpuk terus di qgis-auth.db.
                self.auth_manager.update_credentials(
                    user=self.db_credentials.user,
                    password=self.db_credentials.password,
                )
            else:
                self.auth_manager.store_credentials(
                    host=self.db_credentials.host,
                    port=self.db_credentials.port,
                    dbname=self.db_credentials.dbname,
                    user=self.db_credentials.user,
                    password=self.db_credentials.password,
                )
        except RuntimeError as exc:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "AIM Editor",
                self.tr(f"Gagal nyimpen kredensial database: {exc}"),
            )
            return

        username = self.me.get("username", "?") if self.me else "?"
        self.iface.messageBar().pushSuccess(
            "AIM Editor",
            self.tr(
                f"Login berhasil sebagai {username}. "
                "Pencarian bandara & pemuatan layer belum diimplementasikan (lihat Tahap 3-4)."
            ),
        )
