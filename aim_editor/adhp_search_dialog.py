"""
Dialog pencarian parent (bandara/adhp) berdasarkan ICAO, IATA, atau nama.
Ini jalur SATU-SATUNYA buat mutusin konteks bandara aktif -- user CUMA bisa
pilih lewat pencarian ini, BUKAN browsing manual tabel adhp (lihat
docs/business-rules.md Bagian 4.2).

Query ke tabel adhp dilakukan lewat QgsFeatureRequest + QgsExpression yang
di-bind pake parameter (QgsExpressionContext), BUKAN string formatting/
concatenation manual -- biar aman dari SQL injection (nilai user langsung
masuk expression evaluator QGIS, bukan disisipin mentah ke teks SQL).
"""

from qgis.PyQt.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QAbstractItemView,
    QHeaderView,
)
from qgis.core import (
    QgsFeatureRequest,
    QgsExpression,
    QgsExpressionContext,
    QgsExpressionContextScope,
)

from . import layer_manager


class AdhpSearchDialog(QDialog):
    """Kalo user pilih satu baris & klik OK (accept), hasil yang bisa
    diambil caller lewat properti instance ini:
      - self.selected_gfid: string gfid bandara terpilih
      - self.selected_icao / selected_iata / selected_name: buat ditampilin
        di UI caller (mis. judul panel/status bar), bukan buat query lagi
      - self.selected_geometry: QgsGeometry titik lokasi (buat zoom kanvas)
    """

    def __init__(self, db_credentials, auth_config_id: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AIM Editor - Cari Bandara")
        self.setMinimumSize(480, 360)

        self.db_credentials = db_credentials
        self.auth_config_id = auth_config_id
        self.adhp_layer = None  # lazy-loaded pas dialog dibuka, lihat _ensure_layer_loaded

        self.selected_gfid = None
        self.selected_icao = None
        self.selected_iata = None
        self.selected_name = None
        self.selected_geometry = None

        self.search_edit = QLineEdit(self)
        self.search_edit.setPlaceholderText("Ketik ICAO, IATA, atau sebagian nama bandara...")
        search_button = QPushButton("Cari", self)
        search_button.clicked.connect(self._on_search_clicked)

        search_row = QHBoxLayout()
        search_row.addWidget(self.search_edit)
        search_row.addWidget(search_button)

        self.results_table = QTableWidget(self)
        self.results_table.setColumnCount(3)
        self.results_table.setHorizontalHeaderLabels(["ICAO", "IATA", "Nama"])
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.results_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.results_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.results_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.results_table.itemSelectionChanged.connect(self._on_selection_changed)
        self.results_table.itemDoubleClicked.connect(lambda _: self._try_accept())

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        self.buttons.accepted.connect(self._try_accept)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)

        layout = QVBoxLayout()
        layout.addLayout(search_row)
        layout.addWidget(self.results_table)
        layout.addWidget(self.status_label)
        layout.addWidget(self.buttons)
        self.setLayout(layout)

        self.search_edit.returnPressed.connect(self._on_search_clicked)

        # Baris kosong hasil query, dipetain balik ke row tabel pas user pilih
        # (results_table cuma nampilin ICAO/IATA/Nama, tapi kita butuh gfid +
        # shape juga pas user klik OK -- disimpen di sini, bukan di tabel).
        self._current_results = []

    def _ensure_layer_loaded(self) -> bool:
        """Lazy-load layer adhp sekali aja pas pertama kali search. Kalo
        gagal (kredensial salah, jaringan mati, dst), kasih pesan jelas ke
        user lewat QMessageBox, bukan silent fail."""
        if self.adhp_layer is not None:
            return True

        try:
            self.adhp_layer = layer_manager.load_adhp_layer(self.db_credentials, self.auth_config_id)
        except RuntimeError as exc:
            QMessageBox.critical(self, "AIM Editor", str(exc))
            return False
        return True

    def _on_search_clicked(self):
        keyword = self.search_edit.text().strip()
        if not keyword:
            self.status_label.setText("Masukkan kata kunci pencarian dulu.")
            return

        if not self._ensure_layer_loaded():
            return

        # Query di-bind pake parameter lewat QgsExpressionContext (variabel
        # @keyword), BUKAN disisipin manual ke teks ekspresi -- ini yang
        # bikin aman dari SQL injection walau user ngetik karakter aneh
        # (tanda kutip, dst).
        expression = QgsExpression(
            f"{layer_manager.COL_ADHP_ICAO} ILIKE '%' || @keyword || '%' "
            f"OR {layer_manager.COL_ADHP_IATA} ILIKE '%' || @keyword || '%' "
            f"OR {layer_manager.COL_ADHP_NAME} ILIKE '%' || @keyword || '%'"
        )
        # QgsExpressionContext sendiri GA PUNYA setVariable() langsung --
        # variabel ditambahin lewat QgsExpressionContextScope yang di-append
        # ke context. (Bug nyata ketauan lewat testing manual: setVariable()
        # itu punya QgsExpressionContextScope, bukan QgsExpressionContext.)
        scope = QgsExpressionContextScope()
        scope.setVariable("keyword", keyword)
        context = QgsExpressionContext()
        context.appendScope(scope)

        request = QgsFeatureRequest(expression, context)

        self._current_results = []
        self.results_table.setRowCount(0)

        try:
            features = list(self.adhp_layer.getFeatures(request))
        except Exception as exc:  # noqa: BLE001 -- errors dari pgsql provider bisa macem-macem
            QMessageBox.critical(self, "AIM Editor", f"Pencarian gagal: {exc}")
            return

        for feature in features:
            self._current_results.append(feature)

        self.results_table.setRowCount(len(self._current_results))
        for row, feature in enumerate(self._current_results):
            icao = feature[layer_manager.COL_ADHP_ICAO] or ""
            iata = feature[layer_manager.COL_ADHP_IATA] or ""
            name = feature[layer_manager.COL_ADHP_NAME] or ""
            self.results_table.setItem(row, 0, QTableWidgetItem(str(icao)))
            self.results_table.setItem(row, 1, QTableWidgetItem(str(iata)))
            self.results_table.setItem(row, 2, QTableWidgetItem(str(name)))

        if not self._current_results:
            self.status_label.setText("Tidak ada bandara yang cocok dengan kata kunci tsb.")
        else:
            self.status_label.setText(f"Ditemukan {len(self._current_results)} bandara.")

    def _on_selection_changed(self):
        rows = self.results_table.selectionModel().selectedRows()
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(bool(rows))

    def _try_accept(self):
        rows = self.results_table.selectionModel().selectedRows()
        if not rows:
            return

        feature = self._current_results[rows[0].row()]
        self.selected_gfid = feature[layer_manager.COL_ADHP_GFID]
        self.selected_icao = feature[layer_manager.COL_ADHP_ICAO]
        self.selected_iata = feature[layer_manager.COL_ADHP_IATA]
        self.selected_name = feature[layer_manager.COL_ADHP_NAME]
        self.selected_geometry = feature.geometry()

        self.accept()
