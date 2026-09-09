"""
Orkestrator utama plugin AIM Editor. Ini entry point yang di-load QGIS lewat
classFactory() di __init__.py -- QGIS bakal instantiate class AimEditorPlugin
ini dan manggil initGui()/unload() di titik yang tepat sesuai lifecycle plugin
standar (initGui pas plugin diaktifkan, unload pas plugin dinonaktifkan/QGIS
ditutup).

STRUKTUR MENU (per diskusi 2026-09-09): plugin ini nantinya bakal nanganin
BEBERAPA jenis data, dan sebagian entitas masa depan BISA JADI nggak terikat
ke konteks bandara (adhp) -- jadi "Login" dan "cari data per jenis" dipisah
jadi dua action beda, BUKAN digabung jadi satu alur linear kayak awalnya:

  - "Buka AIM Editor" -- cuma login + simpen sesi. SELALU ada, aktif dari awal.
  - "Apron/Taxiway"   -- baru MUNCUL AKTIF setelah login sukses (disabled
                         sebelum login). Buka AdhpSearchDialog karena entitas
                         ini emang terikat bandara. Entitas lain nanti yang
                         nggak butuh konteks bandara tinggal nambah action
                         baru serupa, TANPA lewat AdhpSearchDialog.

Kedua action didaftarkan ke toolbar DAN menu Plugins sekaligus (lewat
add_action(), parameter add_to_toolbar/add_to_menu default True) -- bukan
pilihan salah satu, sesuai permintaan user.
"""

from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import QgsApplication

from qgis.core import QgsProject, QgsRectangle, QgsCoordinateTransform, QgsGeometry

from .login_dialog import LoginDialog
from .auth_manager import AuthConfigManager
from .adhp_search_dialog import AdhpSearchDialog
from . import layer_manager


def _combined_surface_area_extent(surface_area_layers):
    """Gabungin bounding box semua fitur di layer Apron & Taxiway (yang
    udah difilter ke bandara aktif lewat setSubsetString()) jadi SATU
    extent. Balikin None kalo `surface_area_layers` kosong/None ATAU kedua
    layer nggak punya fitur sama sekali (berarti bandara ini belum ada
    geometri Apron/Taxiway -- caller bakal fallback ke titik ARP, lihat
    _open_apron_taxiway())."""
    if not surface_area_layers:
        return None

    combined = None
    for layer in surface_area_layers.values():
        if layer.featureCount() == 0:
            continue
        layer_extent = layer.extent()
        if layer_extent.isEmpty():
            continue
        if combined is None:
            combined = QgsRectangle(layer_extent)
        else:
            combined.combineExtentWith(layer_extent)
    return combined


def _confirm_end_editing(surface_area_layers, parent_widget) -> bool:
    """Cek apakah ada layer Apron/Taxiway yang lagi mode editing DAN punya
    perubahan belum di-commit (isModified()) -- kalo ada, tanya user dulu
    lewat QMessageBox (Simpan/Buang/Batal) SEBELUM lanjut pindah bandara
    atau login ulang.

    Ditambahkan (2026-09-09) abis user lapor bug nyata: pindah bandara pas
    masih di tengah sesi editing bikin zoom/filter "ngaco" -- root cause-nya
    setSubsetString() dipanggil ulang di layer yang SAMA sementara ada
    perubahan uncommitted, bikin state layer/kanvas ga konsisten (QGIS ga
    didesain buat ganti subset filter di tengah sesi edit aktif). Guard ini
    MENCEGAH kejadian itu terulang -- BUKAN cuma workaround visual.

    Balikin True kalo AMAN buat lanjut (ga ada perubahan uncommitted, ATAU
    user udah pilih Simpan/Buang & itu berhasil dieksekusi). Balikin False
    kalo user pilih Batal, ATAU commitChanges()/rollBack() gagal (biar
    caller BATALIN aksi yang lagi mau jalan -- ganti bandara/login ulang --
    daripada lanjut dengan state yang berantakan).
    """
    if not surface_area_layers:
        return True

    modified_layers = [
        layer for layer in surface_area_layers.values()
        if layer.isEditable() and layer.isModified()
    ]
    if not modified_layers:
        return True

    names = ", ".join(layer.name() for layer in modified_layers)
    choice = QMessageBox.question(
        parent_widget,
        "AIM Editor",
        QCoreApplication.translate(
            "AimEditorPlugin",
            f"Ada perubahan yang belum disimpan di layer: {names}.\n\n"
            "Simpan perubahan dulu sebelum lanjut?"
        ),
        QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
        QMessageBox.Cancel,
    )

    if choice == QMessageBox.Cancel:
        return False

    ok = True
    for layer in modified_layers:
        if choice == QMessageBox.Save:
            if not layer.commitChanges():
                ok = False
        else:  # QMessageBox.Discard
            if not layer.rollBack():
                ok = False

    if not ok:
        QMessageBox.critical(
            parent_widget,
            "AIM Editor",
            QCoreApplication.translate(
                "AimEditorPlugin",
                "Gagal menyimpan/membuang perubahan. Aksi dibatalkan -- "
                "cek layer secara manual dulu sebelum coba lagi."
            ),
        )
    return ok


def _transform_extent(extent, source_crs, dest_crs):
    """Transform QgsRectangle dari CRS sumber (biasanya EPSG:4326, CRS asli
    tabel adhp/ADHPSurfaceArea di PostGIS) ke CRS tujuan (CRS project/
    kanvas, biasanya EPSG:3857). WAJIB dipanggil sebelum mapCanvas().
    setExtent() -- setExtent() nerima angka apa adanya sebagai koordinat
    di CRS kanvas, TANPA transform otomatis, jadi kalo extent-nya masih
    dalam CRS beda (mis. derajat) hasilnya kanvas "lompat" ke lokasi yang
    salah total (lihat catatan panjang di _open_apron_taxiway()).

    Kalo source_crs == dest_crs (atau salah satu invalid), balikin extent
    apa adanya -- transform emang ga perlu/ga bisa dilakuin."""
    if not source_crs.isValid() or not dest_crs.isValid() or source_crs == dest_crs:
        return extent
    transform = QgsCoordinateTransform(source_crs, dest_crs, QgsProject.instance())
    return transform.transformBoundingBox(extent)


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

        # Action "Apron/Taxiway" disimpen terpisah (bukan cuma di self.actions)
        # soalnya perlu di-enable/disable manual berdasarkan status login.
        self.apron_taxiway_action = None

        # State sesi login -- None berarti belum login. `me` isinya response
        # GET /me lengkap (roles, permissions, dst), dipake Tahap 4 nanti
        # buat mutusin layer mana yang boleh dimuat.
        self.auth_manager = AuthConfigManager()
        self.token = None
        self.me = None
        self.db_credentials = None

        # Konteks bandara aktif (hasil AdhpSearchDialog) -- None berarti
        # belum ada bandara terpilih.
        self.selected_gfid = None

        # Layer Apron/Taxiway yang udah dimuat -- {"apron": layer, "taxiway":
        # layer} atau None kalo belum pernah dimuat. Disimpen biar pas GANTI
        # bandara, kita cuma update setSubsetString() layer yang SAMA
        # (lihat filter_children_by_adhp()), BUKAN muat ulang dari nol.
        self.surface_area_layers = None

        # Layer sumber combobox Value Relation (domains_text/domains_smallint)
        # -- {"text": layer, "smallint": layer} atau None kalo belum
        # dimuat/gagal dimuat. OPSIONAL, bukan wajib -- kalo GRANT SELECT
        # ke tabel domain belum di-setup di sisi Postgres (lihat
        # layer_manager.load_domain_layers() docstring), plugin tetep bisa
        # jalan tanpa combobox status_code/abandoned_code (fallback ke
        # widget teks bebas biasa), bukan dianggap error fatal.
        self.domain_layers = None

    def tr(self, message):
        """Wrapper translasi standar QGIS plugin. Dipake konsisten di
        semua string yang bakal keliatan user, biar gampang nambah
        dukungan bahasa lain belakangan (lihat i18n/ di struktur folder)."""
        return QCoreApplication.translate("AimEditorPlugin", message)

    def add_action(self, icon_path, text, callback, enabled_flag=True,
                   add_to_menu=True, add_to_toolbar=True, status_tip=None,
                   whats_this=None, parent=None):
        """Helper buat daftarin satu QAction ke toolbar DAN menu Plugins
        sekaligus (bukan salah satu -- keduanya default True). Pola ini
        standar banget di plugin QGIS (mirip yang di-generate Plugin
        Builder), jadi kalau nanti nambah action baru buat entitas lain
        tinggal panggil ini lagi."""
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
        """Dipanggil QGIS sekali pas plugin diaktifkan. Pasang action
        "Buka AIM Editor" (login, selalu aktif) dan "Apron/Taxiway" (baru
        aktif setelah login sukses)."""
        # Ikon custom (icons/icon.png) belum digambar -- pakai ikon tema
        # bawaan QGIS dulu biar plugin tetap kelihatan di toolbar tanpa
        # nunggu aset custom. Ganti ke icons/icon.png begitu ada.
        self.add_action(
            icon_path="mIconConnect.svg",
            text=self.tr("Buka AIM Editor"),
            callback=self.run,
            parent=self.iface.mainWindow(),
            status_tip=self.tr("Login ke AIM Editor"),
        )

        self.apron_taxiway_action = self.add_action(
            icon_path="mActionAddLayer.svg",
            text=self.tr("Apron/Taxiway"),
            callback=self._open_apron_taxiway,
            enabled_flag=False,  # aktif cuma abis login sukses, lihat run()
            parent=self.iface.mainWindow(),
            status_tip=self.tr("Cari bandara & edit geometri Apron/Taxiway"),
        )

        # Action baru (diminta user 2026-09-09) -- kosongin geometri fitur
        # yang lagi diselect di kanvas, TANPA hapus baris/atributnya.
        # Ditambahkan abis ketauan ga ada cara gampang buat ini lewat GUI
        # standar QGIS (tombol Delete keyboard HAPUS SELURUH FITUR, bukan
        # cuma geometrinya -- dikonfirmasi lewat percobaan manual user).
        # Sebelumnya cuma bisa lewat Python Console manual
        # (layer.changeGeometry(feat.id(), QgsGeometry())) -- sekarang
        # dibungkus jadi tombol biar gampang dipakai berulang, ga perlu
        # buka Python Console tiap kali ada kasus data salah (mis. geometri
        # digambar di lokasi bandara yang salah).
        self.clear_geometry_action = self.add_action(
            icon_path="mActionDeleteSelected.svg",
            text=self.tr("Kosongkan Geometri Fitur Terpilih"),
            callback=self._clear_selected_geometries,
            enabled_flag=False,  # aktif cuma abis login sukses, sama kayak apron_taxiway_action
            parent=self.iface.mainWindow(),
            status_tip=self.tr(
                "Kosongkan geometri fitur Apron/Taxiway yang lagi diselect "
                "(baris & atribut TETAP ada, cuma geometrinya jadi NULL)"
            ),
        )

        # Action baru (diminta user 2026-09-09) -- kebalikan dari
        # clear_geometry_action: isi geometri ke baris existing yang
        # geometrinya masih NULL. QGIS ga punya tool digitasi bawaan buat
        # "gambar geometri lalu tempelkan ke fitur existing yang dipilih"
        # (dikonfirmasi lewat riset API -- alur digitasi standar SELALU
        # bikin fitur baru dari nol). Alur pakainya: user digitasi geometri
        # baru dulu (jadi fitur sementara di layer yang sama), SELECT DUA
        # fitur (baris lama yg geometrinya NULL + fitur baru sementara tadi),
        # klik tombol ini -- plugin pindahin geometri ke baris lama & hapus
        # fitur sementara, atribut baris lama (name_txt/status_code/dst)
        # OTOMATIS kepertahankan, ga perlu copy manual.
        self.assign_geometry_action = self.add_action(
            icon_path="mActionAddPolygon.svg",
            text=self.tr("Timpakan Geometri ke Baris Terpilih"),
            callback=self._assign_geometry_to_selected,
            enabled_flag=False,
            parent=self.iface.mainWindow(),
            status_tip=self.tr(
                "Pindahkan geometri fitur yang baru digambar ke baris lama "
                "yang geometrinya masih kosong (pilih KEDUA fitur dulu)"
            ),
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

        if self.surface_area_layers:
            QgsProject.instance().removeMapLayers(
                [layer.id() for layer in self.surface_area_layers.values()]
            )
            self.surface_area_layers = None

        if self.domain_layers:
            QgsProject.instance().removeMapLayers(
                [layer.id() for layer in self.domain_layers.values()]
            )
            self.domain_layers = None

        self.auth_manager.remove_credentials()

    def run(self):
        """Callback action "Buka AIM Editor". Buka LoginDialog, simpen
        kredensial DB ke QgsAuthManager. SETELAH ini action "Apron/Taxiway"
        (dan entitas lain nanti) baru di-enable -- bukan langsung lanjut
        search bandara di sini (lihat catatan struktur menu di atas).

        WAJIB cek dulu ada sesi editing aktif belum di-commit di layer
        Apron/Taxiway (diminta user 2026-09-09) -- login ulang bisa ganti
        kredensial DB (`update_credentials()`) sementara ada perubahan
        uncommitted, berisiko bikin state layer berantakan."""
        if not _confirm_end_editing(self.surface_area_layers, self.iface.mainWindow()):
            return

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

        self.apron_taxiway_action.setEnabled(True)
        self.clear_geometry_action.setEnabled(True)
        self.assign_geometry_action.setEnabled(True)

        username = self.me.get("username", "?") if self.me else "?"
        self.iface.messageBar().pushSuccess(
            "AIM Editor",
            self.tr(f"Login berhasil sebagai {username}."),
        )

    def _open_apron_taxiway(self):
        """Callback action "Apron/Taxiway". Buka AdhpSearchDialog buat
        milih konteks bandara -- entitas ini EMANG terikat bandara (lihat
        docs/business-rules.md Bagian 1). Abis bandara dipilih, muat (kalo
        belum) & filter layer Apron/Taxiway sesuai bandara tsb, plus zoom
        kanvas ke lokasinya.

        WAJIB cek dulu ada sesi editing aktif belum di-commit SEBELUM buka
        dialog pencarian (diminta user 2026-09-09, bug nyata: pindah
        bandara di tengah sesi editing bikin zoom/filter "ngaco" --
        setSubsetString() ganti filter di layer yang sama sementara ada
        perubahan uncommitted bikin state layer/kanvas ga konsisten).
        Dicek DI SINI (sebelum dialog search, bukan sesudah user pilih
        bandara) supaya user ga buang waktu cari bandara baru kalo
        ujung-ujungnya batal gara-gara ada perubahan belum disimpan."""
        if not _confirm_end_editing(self.surface_area_layers, self.iface.mainWindow()):
            return

        search_dialog = AdhpSearchDialog(
            db_credentials=self.db_credentials,
            auth_config_id=self.auth_manager.config_id,
            parent=self.iface.mainWindow(),
        )
        if not search_dialog.exec_():
            return

        self.selected_gfid = search_dialog.selected_gfid

        permissions = self.me.get("permissions", []) if self.me else []

        if self.surface_area_layers is None:
            # Baru pertama kali (belum ada layer sebelumnya di sesi ini) --
            # muat dari nol sesuai permission user, lalu tambahin ke kanvas.
            try:
                self.surface_area_layers = layer_manager.load_surface_area_layers(
                    self.db_credentials, self.auth_manager.config_id, permissions
                )
            except RuntimeError as exc:
                QMessageBox.critical(self.iface.mainWindow(), "AIM Editor", str(exc))
                return

            if not self.surface_area_layers:
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "AIM Editor",
                    self.tr(
                        "Akun Anda tidak memiliki hak akses untuk mengedit geometri Apron/Taxiway."
                    ),
                )
                self.surface_area_layers = None
                return

            for layer in self.surface_area_layers.values():
                QgsProject.instance().addMapLayer(layer)

        if self.domain_layers is None:
            # Coba muat sekali aja -- OPSIONAL, kalo gagal (biasanya karena
            # GRANT SELECT ke domains_text/domains_smallint belum di-setup)
            # plugin tetep lanjut TANPA combobox status_code/abandoned_code,
            # bukan dianggap error fatal (lihat catatan di __init__).
            try:
                self.domain_layers = layer_manager.load_domain_layers(
                    self.db_credentials, self.auth_manager.config_id
                )
                for layer in self.domain_layers.values():
                    # addMapLayer(layer, False) -- ditambahin ke project TAPI
                    # nggak ditambahin ke Layer Tree/Layer Panel (parameter
                    # kedua False = jangan auto-add ke root layer tree node).
                    # User ga perlu liat tabel lookup internal ini.
                    QgsProject.instance().addMapLayer(layer, False)
            except RuntimeError as exc:
                self.domain_layers = None
                from qgis.core import QgsMessageLog, Qgis
                QgsMessageLog.logMessage(
                    f"Combobox domain (status_code/abandoned_code) nonaktif: {exc}",
                    "AIM Editor", Qgis.Warning,
                )

        # Update filter adhp_id + default value ke bandara yang baru dipilih
        # -- berlaku baik buat pemuatan pertama kali maupun ganti bandara
        # berikutnya (layer yang SAMA di-reuse, bukan dimuat ulang dari nol).
        layer_manager.filter_children_by_adhp(self.surface_area_layers, self.selected_gfid)
        username = self.me.get("username", "?") if self.me else "?"
        icao = search_dialog.selected_icao or "?"

        # PENTING: subtype ditentukan dari KEY dict ("apron"/"taxiway"),
        # BUKAN dari layer.name() -- nama layer sengaja di-rename di bawah
        # buat nampilin bandara aktif (mis. "WIII - Apron"), jadi nggak
        # boleh dipakai buat identifikasi subtype lagi (lihat diskusi
        # 2026-09-09: request user biar bandara aktif keliatan dari nama
        # layer di Layer Panel).
        subtype_by_key = {
            "apron": layer_manager.SUBTYPE_APRON,
            "taxiway": layer_manager.SUBTYPE_TAXIWAY,
        }
        layer_label_by_key = {
            "apron": layer_manager.LAYER_NAME_APRON,
            "taxiway": layer_manager.LAYER_NAME_TAXIWAY,
        }
        for key, layer in self.surface_area_layers.items():
            layer_manager.set_feature_defaults(
                layer, self.selected_gfid, subtype_by_key[key], username,
                domain_layers=self.domain_layers,
            )
            layer.setName(f"{icao} - {layer_label_by_key[key]}")
            layer.triggerRepaint()

        # Zoom awal kanvas -- 2 kondisi (diminta user 2026-09-09):
        #   1. Bandara ini BELUM ada geometri Apron/Taxiway sama sekali --
        #      center view dari titik ARP bandara (selected_geometry, dari
        #      tabel adhp), dikasih buffer biar ga zoom rapet ke satu titik.
        #   2. SUDAH ada geometri Apron/Taxiway -- zoom ke extent gabungan
        #      kedua layer (union bounding box Apron + Taxiway), BUKAN ke
        #      ARP -- lebih relevan langsung liat geometri yang udah ada.
        #
        # PENTING: extent dari layer/geometry itu masih dalam CRS SUMBER
        # layer (EPSG:4326/WGS84 derajat -- gitu adhp & ADHPSurfaceArea
        # tersimpan di PostGIS), sedangkan mapCanvas().setExtent() itu
        # NERIMA & interpretasi angkanya sebagai CRS PROJECT/kanvas
        # (biasanya EPSG:3857/meter, World_Imagery misalnya). Kalo LUPA
        # transform dulu, angka derajat (mis. 117.44) keinterpretasi
        # sebagai METER di 3857 -- kanvas "lompat" ke tengah laut deket
        # (0,0), abu-abu kosong (ketauan nyata pas testing manual
        # 2026-09-09: panel koordinat nunjukin udah "sampe" tapi kanvas
        # blank -- root cause CRS mismatch ini, bukan bug UI/render).
        canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()

        combined_extent = _combined_surface_area_extent(self.surface_area_layers)
        if combined_extent is not None and not combined_extent.isEmpty():
            source_crs = next(iter(self.surface_area_layers.values())).crs()
            combined_extent.grow(combined_extent.width() * 0.1 or 0.001)
            combined_extent = _transform_extent(combined_extent, source_crs, canvas_crs)
            self.iface.mapCanvas().setExtent(combined_extent)
            self.iface.mapCanvas().refresh()
        elif search_dialog.selected_geometry is not None and not search_dialog.selected_geometry.isEmpty():
            # Buffer sederhana biar ga zoom terlalu rapet ke satu titik
            # doang (extent titik = 0 lebar/tinggi, QGIS bisa protes/zoom
            # aneh kalo dikasih extent kosong persis). Awalnya 0.05 derajat
            # (~5.5 km) tapi user (2026-09-09) bilang masih kejauhan buat
            # bandara ukuran sedang -- diperkecil ke 0.01 derajat (~1.1 km
            # di lintang 0 derajat) biar konteks awal lebih dekat ke ARP.
            extent = search_dialog.selected_geometry.boundingBox()
            extent.grow(0.01)
            adhp_crs = search_dialog.adhp_layer.crs()
            extent = _transform_extent(extent, adhp_crs, canvas_crs)
            self.iface.mapCanvas().setExtent(extent)
            self.iface.mapCanvas().refresh()

        self.iface.messageBar().pushSuccess(
            "AIM Editor",
            self.tr(
                f"Bandara terpilih: {search_dialog.selected_icao} - {search_dialog.selected_name}. "
                "Layer Apron/Taxiway sudah dimuat dan difilter."
            ),
        )

    def _clear_selected_geometries(self):
        """Callback action "Kosongkan Geometri Fitur Terpilih" (diminta
        user 2026-09-09). Kosongin geometri (changeGeometry ke QgsGeometry()
        kosong) SEMUA fitur yang lagi diselect di layer AKTIF (iface.
        activeLayer()) -- BARIS & ATRIBUTNYA TETAP ADA, cuma geometrinya
        jadi NULL. Beda dari tombol Delete keyboard standar QGIS yang
        MENGHAPUS SELURUH FITUR (baris+atribut+geometri sekaligus) --
        dikonfirmasi lewat percobaan manual user, ga ada cara gampang lewat
        GUI standar buat cuma ngosongin geometri doang tanpa hapus baris.

        SENGAJA cuma manggil changeGeometry(), BUKAN auto-commitChanges() --
        biar konsisten sama alur editing QGIS standar (user tetep pegang
        kendali kapan nge-save lewat tombol Save Edits / Toggle Editing,
        bisa di-rollback juga kalo salah pencet, bukan langsung permanen).
        """
        layer = self.iface.activeLayer()

        if layer is None or self.surface_area_layers is None or layer not in self.surface_area_layers.values():
            QMessageBox.warning(
                self.iface.mainWindow(),
                "AIM Editor",
                self.tr(
                    "Pilih dulu layer Apron/Taxiway (klik layer-nya di Layer "
                    "Panel) sebelum pakai tombol ini."
                ),
            )
            return

        if not layer.isEditable():
            QMessageBox.warning(
                self.iface.mainWindow(),
                "AIM Editor",
                self.tr(
                    "Aktifkan mode editing dulu (Toggle Editing) sebelum "
                    "kosongkan geometri."
                ),
            )
            return

        selected_ids = layer.selectedFeatureIds()
        if not selected_ids:
            QMessageBox.information(
                self.iface.mainWindow(),
                "AIM Editor",
                self.tr("Belum ada fitur yang diselect di kanvas/attribute table."),
            )
            return

        for feature_id in selected_ids:
            layer.changeGeometry(feature_id, QgsGeometry())
        layer.triggerRepaint()

        self.iface.messageBar().pushSuccess(
            "AIM Editor",
            self.tr(
                f"Geometri {len(selected_ids)} fitur dikosongkan (belum disimpan -- "
                "klik Save Edits/Toggle Editing untuk commit permanen)."
            ),
        )

    def _assign_geometry_to_selected(self):
        """Callback action "Timpakan Geometri ke Baris Terpilih" (diminta
        user 2026-09-09) -- kebalikan dari _clear_selected_geometries().
        Butuh PERSIS 2 fitur terpilih: satu geometrinya NULL/kosong (baris
        lama/target), satu geometrinya udah keisi (fitur baru yang barusan
        digambar/sumber). Geometri sumber dipindah ke target (changeGeometry),
        fitur sumber dihapus (deleteFeature) -- atribut baris target (name_txt/
        status_code/dst) TIDAK disentuh sama sekali, cuma geometrinya yang
        berubah dari NULL jadi terisi.

        SENGAJA cuma manggil changeGeometry()+deleteFeature(), BUKAN auto-
        commitChanges() -- user tetep pegang kendali kapan nge-save, bisa
        di-rollback kalo salah pencet (sama kayak _clear_selected_geometries()).
        """
        layer = self.iface.activeLayer()

        if layer is None or self.surface_area_layers is None or layer not in self.surface_area_layers.values():
            QMessageBox.warning(
                self.iface.mainWindow(),
                "AIM Editor",
                self.tr(
                    "Pilih dulu layer Apron/Taxiway (klik layer-nya di Layer "
                    "Panel) sebelum pakai tombol ini."
                ),
            )
            return

        if not layer.isEditable():
            QMessageBox.warning(
                self.iface.mainWindow(),
                "AIM Editor",
                self.tr(
                    "Aktifkan mode editing dulu (Toggle Editing) sebelum "
                    "timpakan geometri."
                ),
            )
            return

        selected_ids = layer.selectedFeatureIds()
        if len(selected_ids) != 2:
            QMessageBox.information(
                self.iface.mainWindow(),
                "AIM Editor",
                self.tr(
                    "Pilih PERSIS 2 fitur dulu: baris lama yang geometrinya "
                    "masih kosong, dan fitur baru yang barusan digambar "
                    f"(sekarang terpilih {len(selected_ids)} fitur)."
                ),
            )
            return

        empty_feature = None
        filled_feature = None
        for feature in layer.getFeatures(list(selected_ids)):
            geom = feature.geometry()
            if geom is None or geom.isEmpty():
                empty_feature = feature
            else:
                filled_feature = feature

        if empty_feature is None or filled_feature is None:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "AIM Editor",
                self.tr(
                    "Salah satu dari 2 fitur terpilih harus geometrinya "
                    "KOSONG (baris lama), dan satu lagi harus geometrinya "
                    "SUDAH ADA (fitur baru yang barusan digambar)."
                ),
            )
            return

        layer.changeGeometry(empty_feature.id(), filled_feature.geometry())
        layer.deleteFeature(filled_feature.id())
        layer.triggerRepaint()

        self.iface.messageBar().pushSuccess(
            "AIM Editor",
            self.tr(
                "Geometri berhasil dipindahkan ke baris lama (belum disimpan -- "
                "klik Save Edits/Toggle Editing untuk commit permanen)."
            ),
        )
