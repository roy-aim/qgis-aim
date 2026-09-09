"""
Ngurusin pemuatan layer PostGIS ke QGIS lewat QgsDataSourceUri + authcfg
(BUKAN username/password manual, lihat auth_manager.py kenapa). Dua jenis
layer yang diurus modul ini:

  1. `adhp` (parent/bandara) -- dipake buat search dialog (Tahap 3).
  2. `ADHPSurfaceArea` (child, Apron/Taxiway) -- dimuat sebagai DUA entri
     layer terpisah di kanvas ("Apron" & "Taxiway") setelah bandara
     dipilih (Tahap 4).

PENTING banget, dua hal yang JANGAN dilanggar (udah kejadian beneran pas
testing, lihat docs/implementation-plan.md Tahap 3-4):
  - JANGAN pake tanda kutip di sekitar nama tabel/kolom (ADHPSurfaceArea,
    SUBTYPE_CODE, ADHP_ID, dst). Migration backend bikin tabel ini TANPA
    kutip, jadi PostgreSQL fold semua ke huruf kecil. Ngasih kutip bikin
    Postgres nyari nama persis huruf besar-kecilnya yang GA ADA, query
    gagal ("relation/column ... does not exist"). Makanya SEMUA nama
    kolom/tabel di modul ini ditulis LOWERCASE -- itu nama asli yang
    tersimpan di Postgres (dan yang bakal dikenalin QGIS provider), bukan
    disingkat/gaya penulisan doang.
  - Nama SCHEMA wajib diambil dari field `schema` hasil /db-credentials
    (lihat api_client.DbCredentials), BUKAN "public" -- dikonfirmasi
    tabel-tabel ini nempatnya di schema laen (mis. app_user).
"""

from qgis.core import (
    QgsDataSourceUri,
    QgsVectorLayer,
    QgsDefaultValue,
    QgsEditFormConfig,
    QgsEditorWidgetSetup,
    QgsAttributeEditorField,
    QgsPalLayerSettings,
    QgsVectorLayerSimpleLabeling,
    QgsAttributeTableConfig,
    QgsField,
)
from qgis.PyQt.QtCore import QVariant

# Nama tabel di database (lowercase, hasil case-folding Postgres -- lihat
# catatan module-level di atas). TABLE_ADHP_SURFACE_AREA ditulis lowercase
# juga di sini (beda dari beberapa dokumen yang nulis "ADHPSurfaceArea"
# buat keterbacaan) supaya konsisten sama apa yang bakal dikenalin QGIS.
TABLE_ADHP = "adhp"
TABLE_ADHP_SURFACE_AREA = "adhpsurfacearea"

# Nama kolom kunci di tabel adhp yang dipake buat pencarian & identitas.
COL_ADHP_GFID = "gfid"
COL_ADHP_ICAO = "icao_txt"
COL_ADHP_IATA = "iata_txt"
COL_ADHP_NAME = "name_txt"
COL_ADHP_SHAPE = "shape"

# Nama kolom kunci di tabel ADHPSurfaceArea yang relevan buat plugin ini.
COL_SA_GFID = "gfid"
COL_SA_ADHP_ID = "adhp_id"
COL_SA_SUBTYPE_CODE = "subtype_code"
COL_SA_TYPE_CODE = "type_code"
COL_SA_NAME_TXT = "name_txt"
COL_SA_SHAPE = "shape"
COL_SA_CREATED_USER = "created_user"
COL_SA_CREATED_DATE = "created_date"
COL_SA_LAST_EDITED_USER = "last_edited_user"
COL_SA_LAST_EDITED_DATE = "last_edited_date"

# Domain TYPE_CODE utk subtype Taxiway (diambil dari dokumentasi skema
# ADHPSurfaceArea.TYPE_CODE -- domain-nya beda2 per subtype, ini yang
# berlaku KHUSUS Taxiway). Dipake buat Value Map combobox, lihat
# _configure_type_code().
TAXIWAY_TYPE_CODE_OPTIONS = {
    "(OTHER) - Other": "OTHER",
    "AIRTWY - Air": "AIRTWY",
    "GNDTWY - Ground": "GNDTWY",
    "EXIT - Exit/turnoff": "EXIT",
    "FASTEXIT - Rapid Exit/turnoff": "FASTEXIT",
    "STUB - Stub": "STUB",
    "T-AROUND - Turn around": "T-AROUND",
    "PAR - Parallel": "PAR",
    "BYPASS - Bypass holding bay": "BYPASS",
    "APRON - Apron": "APRON",
    "S-TLINE - Gatestand": "S-TLINE",
    "LI-TLINE - Lead-in": "LI-TLINE",
    "LO-TLINE - Lead-out": "LO-TLINE",
}

# SUBTYPE_CODE yang jadi cakupan plugin ini -- lihat business-rules.md
# Bagian 9 buat daftar lengkap 10 subtype, cuma dua ini yang boleh diedit.
SUBTYPE_TAXIWAY = 6
SUBTYPE_APRON = 8

# Nama layer yang muncul di panel/Layer Tree QGIS.
LAYER_NAME_APRON = "Apron"
LAYER_NAME_TAXIWAY = "Taxiway"

# Permission yang dicek dari hasil GET /me buat mutusin mode akses --
# lihat business-rules.md Bagian 4.1 dan qgis-be-business-rules.md.
PERMISSION_READ = "qgis-apron-taxiway:read"
PERMISSION_UPDATE = "qgis-apron-taxiway:update"

# Tabel lookup/pilihan nilai generik milik backend (BUKAN tabel spesifik
# AIS/ICAO) -- dipake combobox Value Relation, query dinamis (BUKAN
# hardcode) soalnya nilainya bisa diubah admin lewat backend kapan aja
# (ada endpoint CRUD-nya, lihat qgis-be-business-rules.md §5.1). Role
# Postgres plugin butuh GRANT SELECT tambahan ke 2 tabel ini (ditambahkan
# 2026-09-09) -- TANPA itu, load_domain_layers() bakal gagal (layer invalid).
TABLE_DOMAINS_TEXT = "domains_text"
TABLE_DOMAINS_SMALLINT = "domains_smallint"
COL_DOMAIN_ID = "id"
COL_DOMAIN_CATEGORY = "category"
COL_DOMAIN_CODE = "code"
COL_DOMAIN_DESCRIPTION = "description"

# Nama category persis di tabel domain (lihat riset 2026-09-09 ke
# cmd/seeder/app/seed_domains.go) -- dipake sebagai filter WHERE category = ...
DOMAIN_CATEGORY_STATUS = "Code_Sts_Sfc"       # -> domains_text, kolom status_code
DOMAIN_CATEGORY_ABANDONED = "Code_Yes_No"     # -> domains_smallint, kolom abandoned_code

# Urutan field yang diminta user (2026-09-09, direvisi lagi di hari yang
# sama abis testing manual), berlaku SAMA persis buat Apron maupun Taxiway.
# INI SEKARANG DAFTAR FIELD YANG TAMPIL DI FORM -- bukan cuma urutan.
# Field lain di skema (~35 kolom, mis. clientkey_id/lastmod_date/mid/
# dimension_uom dst) SENGAJA GA DITAMPILIN SAMA SEKALI di form (bukan
# ditaruh di bawah & didisabled kayak versi awal) -- keputusan user abis
# nyoba form-nya kepanjangan & tombol Simpan ilang ga kelewat scroll.
# Field yang ga ditampilin BUKAN dihapus dari skema/kolom database, cuma
# ga dimasukin ke invisibleRootContainer() form -- nilainya tetep ada di
# tabel appara adanya (biasanya NULL, emang ga relevan buat Apron/Taxiway).
SURFACE_AREA_FIELD_ORDER_TOP = [
    COL_SA_ADHP_ID,
    COL_SA_GFID,
    COL_SA_SUBTYPE_CODE,
    COL_SA_TYPE_CODE,
    COL_SA_NAME_TXT,
    # designator_txt ditaruh PERSIS di bawah name_txt (diminta user
    # 2026-09-09) -- read-only, nilainya otomatis ngikut name_txt lewat
    # QgsDefaultValue di _apply_designator_default() (KALO designator_txt
    # ga dimasukin ke list ini, field-nya ga pernah dirender form sama
    # sekali, makanya default value-nya juga ga pernah ke-trigger -- bug
    # nyata yang ketauan abis user coba isi feature baru).
    "designator_txt",
    "status_code",
    "abandoned_code",
    "remarks_txt",
    "source_txt",
    # Field audit -- tetep DITAMPILIN (diminta user 2026-09-09, biar user
    # bisa liat siapa/kapan fitur dibuat & terakhir diedit) tapi read-only
    # (textbox abu-abu, bukan bisa diketik) -- udah diset read_only=True di
    # set_feature_defaults(), sama kayak gfid/adhp_id/dst.
    COL_SA_CREATED_USER,
    COL_SA_CREATED_DATE,
    COL_SA_LAST_EDITED_USER,
    COL_SA_LAST_EDITED_DATE,
]


def _field_order_for_subtype(subtype_code: int) -> list:
    """Balikin daftar field form buat subtype tertentu -- BEDA dari
    SURFACE_AREA_FIELD_ORDER_TOP based version lama, sekarang type_code
    DIKECUALIKAN dari form Apron (koreksi user 2026-09-09: type_code Apron
    WAJIB NULL, disepakati field-nya dihilangkan total dari form Apron,
    bukan ditampilin kosong+disabled -- beda dari keputusan sebelumnya yang
    minta tampil fixed 'APRON'). Taxiway TETEP nampilin type_code seperti
    biasa (combobox ValueMap, lihat _configure_type_code())."""
    if subtype_code == SUBTYPE_APRON:
        return [name for name in SURFACE_AREA_FIELD_ORDER_TOP if name != COL_SA_TYPE_CODE]
    return list(SURFACE_AREA_FIELD_ORDER_TOP)

# Nama kolom designator_txt -- diisi otomatis nyamain name_txt KALO masih
# kosong (diminta user 2026-09-09), lihat _apply_designator_default().
COL_SA_DESIGNATOR_TXT = "designator_txt"


def _build_postgres_uri(db_credentials, table_name: str, auth_config_id: str,
                         geometry_column: str, key_column: str,
                         sql_filter: str = "") -> QgsDataSourceUri:
    """Helper bareng buat rakit QgsDataSourceUri ke satu tabel PostGIS.
    Dipake baik buat load_adhp_layer() maupun (nanti) load_surface_area
    layers Tahap 4 -- pola nyambungnya sama persis, cuma beda nama
    tabel/kolom.
    """
    uri = QgsDataSourceUri()
    uri.setConnection(db_credentials.host, str(db_credentials.port), db_credentials.dbname, "", "")
    # authcfg di-set TERPISAH dari setConnection() -- QGIS bakal ambil
    # username/password dari QgsAuthManager pas connect, BUKAN dari sini.
    uri.setAuthConfigId(auth_config_id)
    uri.setSchema(db_credentials.schema)
    uri.setDataSource(db_credentials.schema, table_name, geometry_column, sql_filter, key_column)
    return uri


def load_adhp_layer(db_credentials, auth_config_id: str) -> QgsVectorLayer:
    """Muat tabel `adhp` sebagai QgsVectorLayer, dipake buat search dialog
    (Tahap 3). Layer ini SENGAJA nggak ditambahin ke QgsProject/kanvas --
    dia cuma dipake internal buat query lewat QgsFeatureRequest di
    adhp_search_dialog.py, user nggak perlu liat dia di Layer Panel.

    Lempar RuntimeError kalo layer gagal connect/invalid, biar caller bisa
    kasih pesan error yang jelas ke user (bukan silent fail).
    """
    uri = _build_postgres_uri(
        db_credentials,
        table_name=TABLE_ADHP,
        auth_config_id=auth_config_id,
        geometry_column=COL_ADHP_SHAPE,
        key_column=COL_ADHP_GFID,
    )
    layer = QgsVectorLayer(uri.uri(False), "adhp (internal)", "postgres")
    if not layer.isValid():
        raise RuntimeError(
            "Gagal konek ke tabel adhp -- cek kredensial, schema, atau koneksi jaringan ke database."
        )
    return layer


def load_domain_layers(db_credentials, auth_config_id: str) -> dict:
    """Muat tabel domains_text & domains_smallint sebagai QgsVectorLayer,
    dipake sebagai SUMBER combobox Value Relation (status_code,
    abandoned_code, dst). Kayak load_adhp_layer(), layer ini SENGAJA
    ditambahin ke QgsProject (Value Relation butuh referensi by layer ID
    yang valid di project, beda dari load_adhp_layer yang cuma dipake
    internal query doang) TAPI disembunyikan dari Layer Panel (lihat
    caller di main_plugin.py) -- user ga perlu liat/ubah tabel lookup ini
    langsung.

    Lempar RuntimeError kalo salah satu layer gagal connect -- biasanya
    berarti GRANT SELECT ke tabel ini belum dijalankan di sisi Postgres
    (lihat qgis-be-implementation-plan.md Tahap 3, ditambahkan 2026-09-09).
    """
    text_uri = _build_postgres_uri(
        db_credentials, TABLE_DOMAINS_TEXT, auth_config_id, "", COL_DOMAIN_ID
    )
    text_layer = QgsVectorLayer(text_uri.uri(False), "domains_text (internal)", "postgres")
    if not text_layer.isValid():
        raise RuntimeError(
            "Gagal konek ke tabel domains_text -- kemungkinan GRANT SELECT "
            "belum diberikan ke role Postgres plugin. Lihat "
            "backend-aim docs/aim-pages/qgis-support/qgis-be-implementation-plan.md Tahap 3."
        )

    smallint_uri = _build_postgres_uri(
        db_credentials, TABLE_DOMAINS_SMALLINT, auth_config_id, "", COL_DOMAIN_ID
    )
    smallint_layer = QgsVectorLayer(smallint_uri.uri(False), "domains_smallint (internal)", "postgres")
    if not smallint_layer.isValid():
        raise RuntimeError(
            "Gagal konek ke tabel domains_smallint -- kemungkinan GRANT SELECT "
            "belum diberikan ke role Postgres plugin. Lihat "
            "backend-aim docs/aim-pages/qgis-support/qgis-be-implementation-plan.md Tahap 3."
        )

    return {"text": text_layer, "smallint": smallint_layer}


def _load_surface_area_layer(db_credentials, auth_config_id: str,
                              layer_name: str, subtype_code: int) -> QgsVectorLayer:
    """Muat SATU entri layer dari tabel adhpsurfacearea, di-filter dasar
    berdasarkan subtype_code (6=Taxiway, 8=Apron). Dipake internal sama
    load_surface_area_layers() buat masing-masing Apron & Taxiway --
    keduanya bersumber dari tabel yang SAMA, cuma beda filter."""
    uri = _build_postgres_uri(
        db_credentials,
        table_name=TABLE_ADHP_SURFACE_AREA,
        auth_config_id=auth_config_id,
        geometry_column=COL_SA_SHAPE,
        key_column=COL_SA_GFID,
        sql_filter=f"{COL_SA_SUBTYPE_CODE} = {subtype_code}",
    )
    layer = QgsVectorLayer(uri.uri(False), layer_name, "postgres")
    if not layer.isValid():
        raise RuntimeError(
            f"Gagal konek ke layer {layer_name} -- cek kredensial, schema, atau koneksi jaringan ke database."
        )
    return layer


def load_surface_area_layers(db_credentials, auth_config_id: str, permissions: list) -> dict:
    """Muat layer Apron & Taxiway (dua entri terpisah, sama-sama dari
    tabel adhpsurfacearea) SESUAI permission user dari hasil GET /me.

    Balikin dict {"apron": QgsVectorLayer, "taxiway": QgsVectorLayer} --
    KEDUANYA dimuat bareng kalo user punya salah satu dari
    qgis-apron-taxiway:read/qgis-apron-taxiway:update (mode baca-saja vs
    bisa-edit dibedain lewat kemampuan commit yang udah dibatasi RLS di
    Postgres sendiri, bukan lewat logic Python di sini -- lihat
    business-rules.md Bagian 4.1).

    Balikin dict KOSONG kalo user ga punya permission relevan sama sekali
    -- caller (main_plugin.py) yang mutusin mau kasih pesan apa ke user.
    """
    has_access = PERMISSION_READ in permissions or PERMISSION_UPDATE in permissions
    if not has_access:
        return {}

    apron_layer = _load_surface_area_layer(
        db_credentials, auth_config_id, LAYER_NAME_APRON, SUBTYPE_APRON
    )
    taxiway_layer = _load_surface_area_layer(
        db_credentials, auth_config_id, LAYER_NAME_TAXIWAY, SUBTYPE_TAXIWAY
    )
    return {"apron": apron_layer, "taxiway": taxiway_layer}


def filter_children_by_adhp(layers: dict, gfid: str) -> None:
    """Tambahin filter adhp_id ke setSubsetString() tiap layer child, DI
    ATAS filter subtype_code yang udah dipasang pas load. gfid di-escape
    manual (ganti satu kutip jadi dua) sebelum disisipin ke ekspresi --
    QgsDataSourceUri/setSubsetString ga punya mekanisme bind parameter
    kayak QgsFeatureRequest, jadi escaping manual ini yang paling aman
    buat konteks ini (gfid SELALU dari hasil pilihan AdhpSearchDialog,
    BUKAN dari input teks bebas user, jadi risikonya rendah -- tapi tetep
    di-escape biar aman kalo suatu saat sumbernya berubah)."""
    escaped_gfid = gfid.replace("'", "''")

    subtype_by_key = {"apron": SUBTYPE_APRON, "taxiway": SUBTYPE_TAXIWAY}
    for key, layer in layers.items():
        subtype_code = subtype_by_key[key]
        layer.setSubsetString(
            f"{COL_SA_SUBTYPE_CODE} = {subtype_code} AND {COL_SA_ADHP_ID} = '{escaped_gfid}'"
        )


def set_feature_defaults(layer: QgsVectorLayer, gfid: str, subtype_code: int,
                          username: str, domain_layers: dict = None) -> None:
    """Set QgsDefaultValue (nama kelas PyQGIS -- bukan "QgsDefaultValueDefinition"
    yang sempat salah ditulis & bikin ImportError pas testing manual)
    buat kolom yang WAJIB keisi otomatis pas user nambah fitur baru:
    gfid (PK, di-generate sendiri -- TIDAK ADA trigger DB yang ngisi ini,
    backend Go generate-nya manual pake uuid.New(), plugin niru pola yang
    sama persis lewat upper(uuid()) di QGIS expression engine, lihat
    docs/implementation-plan.md soal riset GFID 2026-09-09), adhp_id (FK ke
    bandara aktif), subtype_code (6/8 sesuai layer), type_code (domain beda
    per subtype, lihat _configure_type_code()), dan kolom audit
    created_*/last_edited_* (WAJIB diisi plugin sendiri -- TIDAK ADA
    trigger DB, lihat business-rules.md Bagian 5 & Tahap 4.5
    implementation-plan.md).

    gfid, adhp_id, subtype_code JUGA ditandai read-only di form atribut,
    biar user ga bisa ubah manual (mencegah fitur "pindah" ke bandara/
    subtype lain, atau PK berubah, di luar kontrol plugin).

    `domain_layers` (opsional, dict {"text": layer, "smallint": layer} dari
    load_domain_layers()) -- kalo dikasih, sekalian konfigurasi combobox
    Value Relation utk status_code/abandoned_code. Opsional (bukan wajib)
    soalnya butuh GRANT SELECT tambahan yang mungkin belum di-setup di
    semua environment (lihat load_domain_layers() docstring).
    """
    fields = layer.fields()
    form_config = layer.editFormConfig()

    def _apply_default(column: str, expression: str, read_only: bool = False):
        idx = fields.indexFromName(column)
        if idx < 0:
            # Kolom ga ketemu di layer -- kemungkinan besar salah nama
            # field/provider ga expose kolom ini. Skip diem-diem daripada
            # crash, tapi ini seharusnya ga pernah kejadian kalo skema
            # backend ga berubah.
            return
        layer.setDefaultValueDefinition(idx, QgsDefaultValue(expression, True))
        if read_only:
            form_config.setReadOnly(idx, True)

    # gfid di-generate baru tiap kali expression dievaluasi (fitur baru =
    # UUID baru) -- upper(uuid()) menghasilkan format PERSIS sama kayak
    # backend Go: {XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}, 38 karakter,
    # huruf besar semua. Dikonfirmasi lewat evaluate_expression via MCP
    # QGIS: upper(uuid()) -> '{19EF2C80-5868-4A2C-8BA8-F935D169D298}'.
    _apply_default(COL_SA_GFID, "upper(uuid())", read_only=True)

    # adhp_id & subtype_code disisipin sebagai literal SQL langsung (bukan
    # placeholder/bind) karena expression QgsDefaultValue itu dievaluasi
    # QGIS expression engine, bukan dikirim ke Postgres apa adanya --
    # gfid diapit kutip tunggal & di-escape sama kayak
    # filter_children_by_adhp() di atas.
    escaped_gfid = gfid.replace("'", "''")
    _apply_default(COL_SA_ADHP_ID, f"'{escaped_gfid}'", read_only=True)
    _apply_default(COL_SA_SUBTYPE_CODE, str(subtype_code), read_only=True)

    # read_only=True di keempat kolom audit ini (diminta user 2026-09-09:
    # tetep DITAMPILIN di form biar user bisa liat siapa/kapan, tapi
    # sebagai textbox abu-abu ga bisa diketik manual, bukan disembunyikan).
    # Read-only ini CUMA ngunci INPUT USER lewat form -- QgsDefaultValue
    # yang udah di-set applyOnUpdate=True di _apply_default() TETEP jalan
    # ngisi ulang last_edited_user/last_edited_date tiap commit walau
    # field-nya keliatan disabled (dua mekanisme independen: readOnly form
    # cuma soal UI, applyOnUpdate soal expression evaluation pas commit).
    _apply_default(COL_SA_CREATED_DATE, "now()", read_only=True)
    _apply_default(COL_SA_LAST_EDITED_DATE, "now()", read_only=True)

    # Username diambil dari GET /me (identitas APLIKASI individu), BUKAN
    # current_user SQL -- current_user bakal balikin nama role Postgres
    # bersama (qgis_writer_apron_taxiway), bukan identitas orangnya (lihat
    # business-rules.md Bagian 3.2 soal kenapa ini penting). Nilainya
    # disisipin sebagai literal string di ekspresi, sama kayak gfid.
    escaped_username = username.replace("'", "''")
    _apply_default(COL_SA_CREATED_USER, f"'{escaped_username}'", read_only=True)
    _apply_default(COL_SA_LAST_EDITED_USER, f"'{escaped_username}'", read_only=True)

    layer.setEditFormConfig(form_config)
    _configure_type_code(layer, subtype_code)

    if domain_layers is not None:
        _configure_domain_value_relation(
            layer, "status_code", domain_layers["text"], DOMAIN_CATEGORY_STATUS,
        )
        _configure_domain_value_relation(
            layer, "abandoned_code", domain_layers["smallint"], DOMAIN_CATEGORY_ABANDONED,
        )

    _apply_designator_default(layer)
    field_order = _field_order_for_subtype(subtype_code)
    _apply_form_field_order(layer, field_order)
    shape_status_field = _ensure_shape_status_field(layer)
    _apply_attribute_table_config(layer, field_order, shape_status_field)
    _apply_name_label(layer)


COL_SHAPE_STATUS = "shape_status"


def _ensure_shape_status_field(layer: QgsVectorLayer) -> str:
    """Tambahin expression field VIRTUAL (bukan kolom asli di database,
    cuma dihitung di sisi QGIS) yang nunjukin ringkas apakah geometri
    (shape) fitur itu Ada/Kosong -- diminta user (2026-09-09) buat
    ditampilin di Attribute Table, soalnya kolom geometri asli (shape) BUKAN
    field/atribut biasa (dipisah provider PostGIS lewat setDataSource(),
    ga bisa ditampilin sebagai kolom teks langsung di Attribute Table).

    Idempotent: cek dulu field-nya udah ada apa belom (based on name) --
    kalo addExpressionField() dipanggil berkali-kali tanpa cek ini, field
    numpuk duplikat tiap kali ganti bandara (set_feature_defaults() jalan
    ulang). Balikin nama field ini (dipake caller buat _apply_attribute_
    table_config() taruh di kolom PALING TERAKHIR).
    """
    fields = layer.fields()
    if fields.indexFromName(COL_SHAPE_STATUS) < 0:
        field = QgsField(COL_SHAPE_STATUS, QVariant.String)
        expr = "CASE WHEN $geometry IS NULL THEN 'Kosong' ELSE 'Ada' END"
        layer.addExpressionField(expr, field)
    return COL_SHAPE_STATUS


def _apply_attribute_table_config(layer: QgsVectorLayer, field_order: list,
                                   shape_status_field: str = None) -> None:
    """Samain kolom yang tampil + urutannya di Attribute Table dengan form
    atribut (diminta user 2026-09-09) -- defaultnya Attribute Table selalu
    nampilin SEMUA kolom skema (>40 kolom) apa adanya, beda dari form yang
    udah kita filter/urutin sendiri (lihat _apply_form_field_order()).
    Kolom yang ga disebut di `field_order` disembunyikan (hidden=True) di
    sini juga -- bukan dihapus dari skema, cuma ga ditampilin.

    `shape_status_field` (opsional, dari _ensure_shape_status_field()) --
    kalo dikasih, kolom ini SENGAJA ditaruh PALING TERAKHIR (diminta user
    2026-09-09) -- ringkasan ada/kosongnya geometri, biar user gampang cek
    baris mana yang masih perlu digambar geometrinya tanpa perlu klik satu-
    satu ke kanvas.

    Dipanggil tiap kali set_feature_defaults() jalan (ganti bandara) --
    idempotent, config lama ketimpa yang baru, ga numpuk.
    """
    config = layer.attributeTableConfig()

    order_index = {name: i for i, name in enumerate(field_order)}
    columns = list(config.columns())
    # Kolom "Action" bawaan Attribute Table (type != Field, name kosong)
    # BUKAN field database -- JANGAN disortir/disembunyiin kayak field
    # biasa, biarin apa adanya (biasanya nempel di ujung, tetep visible).
    field_columns = [col for col in columns if col.type == QgsAttributeTableConfig.Field]
    other_columns = [col for col in columns if col.type != QgsAttributeTableConfig.Field]

    # shape_status_field WAJIB paling akhir -- kasih index gede banget
    # (lebih gede dari "sisanya yang ga disebut di field_order") biar selalu
    # jatuh di ujung, bukan ketuker sama kolom hidden lain.
    def _sort_key(col):
        if shape_status_field is not None and col.name == shape_status_field:
            return len(field_order) + 1
        return order_index.get(col.name, len(field_order))

    # Urutin: kolom yang ada di field_order duluan (sesuai urutannya),
    # sisanya di belakang apa adanya, shape_status_field paling akhir --
    # konsisten sama pola _apply_form_field_order() di atas.
    field_columns.sort(key=_sort_key)
    for col in field_columns:
        col.hidden = col.name not in order_index and col.name != shape_status_field

    config.setColumns(field_columns + other_columns)
    layer.setAttributeTableConfig(config)


def _apply_name_label(layer: QgsVectorLayer) -> None:
    """Nyalain label di kanvas buat tiap fitur, ambil dari name_txt
    (diminta user 2026-09-09) -- biar user bisa langsung liat nama
    Apron/Taxiway di peta tanpa perlu buka form/attribute table satu-satu.
    Dipanggil tiap kali set_feature_defaults() jalan (ganti bandara) --
    idempotent, aman di-set ulang (nimpa config lama, ga numpuk).
    """
    label_settings = QgsPalLayerSettings()
    label_settings.fieldName = COL_SA_NAME_TXT
    label_settings.enabled = True

    layer.setLabeling(QgsVectorLayerSimpleLabeling(label_settings))
    layer.setLabelsEnabled(True)


def _apply_designator_default(layer: QgsVectorLayer) -> None:
    """designator_txt otomatis ngikut name_txt -- diminta user (2026-09-09,
    direvisi lagi abis testing manual: awalnya editable, user putusin
    disabled aja) READ-ONLY di form, ditaruh persis di bawah name_txt
    (lihat SURFACE_AREA_FIELD_ORDER_TOP). Dipake buat Apron & Taxiway,
    dua2nya punya kolom ini.

    Pake "name_txt" ekspresi (BUKAN nilai/literal beku) supaya nilainya
    ikut nyesuain tiap kali name_txt diisi/diubah di form yang sama,
    persis kayak gimana QGIS expression-based default value kerja (re-
    evaluate tiap form dibuka/field terkait berubah) -- bukan cuma sekali
    pas fitur baru dibuat.

    PENTING: field ini WAJIB ada di SURFACE_AREA_FIELD_ORDER_TOP (dipake
    _apply_form_field_order()) supaya field-nya kerender di form sama
    sekali -- form kita sekarang FILTER (cuma nampilin field yang eksplisit
    disebut), jadi kalo lupa didaftarin, QgsDefaultValue di sini ga pernah
    ke-trigger (bug nyata yang sempet kejadian, designator_txt keliatan
    "ga keisi" padahal defaultnya udah bener secara kode).
    """
    fields = layer.fields()
    idx = fields.indexFromName(COL_SA_DESIGNATOR_TXT)
    if idx < 0:
        return
    layer.setDefaultValueDefinition(idx, QgsDefaultValue("name_txt", False))
    form_config = layer.editFormConfig()
    form_config.setReadOnly(idx, True)
    layer.setEditFormConfig(form_config)


def _configure_type_code(layer: QgsVectorLayer, subtype_code: int) -> None:
    """Atur widget & default value kolom type_code, domainnya BEDA per
    subtype (lihat dokumentasi skema ADHPSurfaceArea.TYPE_CODE):
      - Taxiway (6): combobox Value Map, 13 pilihan (TAXIWAY_TYPE_CODE_OPTIONS),
        field TETEP tampil di form.
      - Apron (8): TYPE_CODE **WAJIB NULL** (dikoreksi user 2026-09-09 --
        keputusan sebelumnya minta tampil fixed 'APRON', ternyata salah,
        field ini harus NULL). Field-nya DIHILANGKAN TOTAL dari form Apron
        (lihat _field_order_for_subtype()), TAPI QgsDefaultValue tetep
        di-set ke ekspresi "NULL" (applyOnUpdate=True) supaya kolom ini
        eksplisit ke-NULL-kan pas commit walau field-nya ga pernah dirender
        di form -- expression default value QGIS tetep dievaluasi & dikirim
        ke provider pas commitChanges() untuk fitur baru, ga bergantung ke
        apakah field itu ada di invisibleRootContainer() form atau enggak
        (beda sama Value Relation/ValueMap widget config yang emang cuma
        efeknya di rendering form doang).
    """
    fields = layer.fields()
    idx = fields.indexFromName(COL_SA_TYPE_CODE)
    if idx < 0:
        return

    form_config = layer.editFormConfig()

    if subtype_code == SUBTYPE_TAXIWAY:
        layer.setDefaultValueDefinition(idx, QgsDefaultValue("", False))
        form_config.setReadOnly(idx, False)
        widget_setup = QgsEditorWidgetSetup(
            "ValueMap", {"map": TAXIWAY_TYPE_CODE_OPTIONS}
        )
        layer.setEditorWidgetSetup(idx, widget_setup)
    elif subtype_code == SUBTYPE_APRON:
        layer.setDefaultValueDefinition(idx, QgsDefaultValue("NULL", True))
        form_config.setReadOnly(idx, True)

    layer.setEditFormConfig(form_config)


def _configure_domain_value_relation(layer: QgsVectorLayer, column: str,
                                      domain_layer: QgsVectorLayer, category: str) -> None:
    """Set widget "ValueRelation" (combobox yang query dinamis ke layer
    lain) buat satu kolom, difilter ke satu `category` tabel domain.
    Query dinamis (BUKAN hardcode kayak TAXIWAY_TYPE_CODE_OPTIONS) SENGAJA
    dipilih di sini soalnya nilai domain ini emang dirancang backend buat
    bisa diubah admin kapan aja tanpa deploy ulang -- lihat diskusi
    2026-09-09 & qgis-be-business-rules.md §5.1.

    `domain_layer` WAJIB udah ada di QgsProject (Value Relation nyimpen
    referensi ke layer by ID, bukan by object Python) -- lihat
    load_domain_layers() & caller di main_plugin.py.
    """
    fields = layer.fields()
    idx = fields.indexFromName(column)
    if idx < 0:
        return

    # Key = kolom yang disimpen ke ADHPSurfaceArea (code), Value = yang
    # ditampilin di combobox (description). FilterExpression dibatasi ke
    # satu category doang -- satu tabel domain nampung banyak "kategori"
    # sekaligus (dibedain kolom category), jadi WAJIB difilter di sini,
    # kalo enggak combobox bakal nampilin SEMUA kategori campur aduk.
    escaped_category = category.replace("'", "''")
    widget_setup = QgsEditorWidgetSetup("ValueRelation", {
        "Layer": domain_layer.id(),
        "Key": COL_DOMAIN_CODE,
        "Value": COL_DOMAIN_DESCRIPTION,
        "FilterExpression": f"{COL_DOMAIN_CATEGORY} = '{escaped_category}'",
        "AllowMulti": False,
        "AllowNull": True,
        "OrderByValue": True,
        "NofColumns": 1,
    })
    layer.setEditorWidgetSetup(idx, widget_setup)


def _apply_form_field_order(layer: QgsVectorLayer, field_order_top: list) -> None:
    """Susun form atribut biar CUMA nampilin field yang disebut di
    `field_order_top`, sesuai urutan list itu -- field lain di skema
    (~35 kolom, mis. clientkey_id/lastmod_date/mid/dimension_uom dst)
    SENGAJA GA DITAMPILIN SAMA SEKALI (bukan ditaruh di bawah &
    didisabled) -- keputusan user (2026-09-09) abis nyoba form yang
    nampilin semua field kepanjangan & ga bisa discroll, tombol Simpan
    ilang dari layar. Field yang ga ditampilin BUKAN dihapus dari skema
    DB, cuma ga dimasukin ke form container ini -- nilainya tetep ada di
    tabel apa adanya.

    Dipanggil ULANG tiap kali set_feature_defaults() jalan (tiap ganti
    bandara) -- idempotent, aman dipanggil berkali-kali (invisibleRootContainer
    di-clear() dulu sebelum disusun ulang, ga numpuk elemen duplikat).

    PENTING: layout form WAJIB di-set ke QgsEditFormConfig.TabLayout dulu.
    Defaultnya QGIS pake GeneratedLayout (auto-generate form dari urutan
    kolom skema DB apa adanya) -- di mode itu, invisibleRootContainer()/
    addChildElement() yang kita susun manual di bawah ini SAMA SEKALI
    DIABAIKAN sama form renderer (ketauan nyata pas testing manual
    2026-09-09: field order & readOnly udah bener kalo dicek programatik
    lewat editFormConfig(), tapi form GUI tetep nampilin urutan lama --
    root cause-nya form masih GeneratedLayout, bukan bug di logic ordering
    ini).
    """
    fields = layer.fields()
    form_config = layer.editFormConfig()
    form_config.setLayout(QgsEditFormConfig.TabLayout)
    root = form_config.invisibleRootContainer()
    root.clear()

    for name in field_order_top:
        idx = fields.indexFromName(name)
        if idx < 0:
            continue
        field_element = QgsAttributeEditorField(name, idx, root)
        root.addChildElement(field_element)

    layer.setEditFormConfig(form_config)
