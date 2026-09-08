"""
Orkestrator utama plugin AIM Editor. Ini entry point yang di-load QGIS lewat
classFactory() di __init__.py -- QGIS bakal instantiate class AimEditorPlugin
ini dan manggil initGui()/unload() di titik yang tepat sesuai lifecycle plugin
standar (initGui pas plugin diaktifkan, unload pas plugin dinonaktifkan/QGIS
ditutup).

TAHAP 1 (skeleton): baru bikin tombol toolbar + entry menu doang, belum ada
logic bisnis apa pun (belum connect ke login_dialog/api_client/dst). Logic
bisnis nyusul di tahap-tahap berikutnya (lihat docs/implementation-plan.md).
"""

from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import QgsApplication


class AimEditorPlugin:
    """Class utama plugin. QGIS pegang SATU instance ini selama plugin
    aktif -- state sesi (token, kredensial, dsb nanti) bakal disimpan
    sebagai atribut instance di sini di tahap-tahap berikutnya."""

    def __init__(self, iface):
        # `iface` ini QgisInterface, jembatan resmi buat plugin ngakses
        # QGIS (canvas, layer tree, menu, toolbar, dst). Selalu dikasih
        # QGIS pas instantiate plugin, jangan bikin sendiri.
        self.iface = iface
        self.actions = []
        self.menu = "&AIM Editor"
        self.toolbar = self.iface.addToolBar("AIM Editor")
        self.toolbar.setObjectName("AIMEditorToolbar")

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
        """Dipanggil QGIS sekali pas plugin diaktifkan. TAHAP 1: cuma
        pasang satu tombol placeholder ("Buka AIM Editor") yang belum
        ngapa-ngapain -- nanti bakal buka login_dialog di tahap berikutnya."""
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
        menu/toolbar, plus toolbar-nya sendiri. Di tahap berikutnya, ini
        juga tempat manggil auth_manager.remove_credentials() (lihat
        docs/business-rules.md Bagian 3.3 soal kenapa ini wajib)."""
        for action in self.actions:
            self.iface.removePluginMenu(self.menu, action)
            self.iface.removeToolBarIcon(action)
        del self.toolbar

    def run(self):
        """Placeholder callback tombol toolbar/menu. TAHAP 1: belum
        ngapa-ngapain beneran, cuma bukti kalau tombolnya nyambung.
        Nanti bakal buka LoginDialog dulu, baru lanjut ke alur
        search-adhp -> load-layer (lihat docs/implementation-plan.md
        Tahap 2-4)."""
        self.iface.messageBar().pushInfo(
            "AIM Editor",
            self.tr("Plugin berhasil dimuat. Alur login belum diimplementasikan (lihat Tahap 2)."),
        )
