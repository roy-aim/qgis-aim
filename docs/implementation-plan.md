# Rencana Implementasi — AIM Editor (QGIS Plugin)

Dokumen ini merinci rencana implementasi teknis berdasarkan aturan bisnis pada [business-rules.md](business-rules.md). Rencana disusun bertahap agar dapat diverifikasi secara inkremental sebelum lanjut ke tahap berikutnya.

**Catatan skema penting** (lihat business-rules.md Bagian 1 untuk detail lengkap): parent = tabel `adhp` (PK `gfid`, `VARCHAR(38)`), child rilis awal = tabel `ADHPSurfaceArea` (PK `GFID`, FK `ADHP_ID` ke `adhp.gfid`, dibedakan lewat kolom `SUBTYPE_CODE`; hanya `SUBTYPE_CODE` 6=Taxiway dan 8=Apron yang masuk cakupan plugin). Ini **bukan** skema sederhana `airport`/`apron`/`taxiway` sebagai tabel terpisah seperti asumsi dokumen versi awal — dokumen ini sudah direvisi menyesuaikan skema nyata hasil riset terhadap repo backend.

## 1. Struktur Proyek

```
qgis-aim/
├── CLAUDE.md
├── docs/
│   ├── business-rules.md
│   └── implementation-plan.md
└── aim_editor/                   # root plugin QGIS
    ├── __init__.py                # classFactory() — entry point QGIS
    ├── metadata.txt               # metadata plugin standar QGIS
    ├── main_plugin.py             # orkestrator utama, lifecycle plugin
    ├── api_client.py              # client REST API (login, /me, /db-credentials)
    ├── auth_manager.py            # wrapper QgsAuthManager
    ├── layer_manager.py           # load layer ADHPSurfaceArea, setSubsetString per subtype, default value
    ├── login_dialog.py            # dialog login PyQt5
    ├── adhp_search_dialog.py      # dialog pencarian parent adhp (bandara)
    ├── settings.py                 # baca/tulis QSettings (base_url API, dsb.)
    ├── resources.py / icons/      # ikon toolbar plugin
    └── i18n/ (opsional)           # jika UI perlu multi-bahasa nanti
```

Status saat ini: `__init__.py`, `metadata.txt`, `api_client.py`, `auth_manager.py`, `login_dialog.py` sudah berupa skeleton awal dan sudah disesuaikan (Tahap 2) dengan skema backend nyata. `layer_manager.py` dan dialog pencarian **belum ditulis** — nama filenya berubah dari rencana awal `airport_search_dialog.py` menjadi `adhp_search_dialog.py` mengikuti nama tabel sebenarnya (`adhp`, bukan `airport`).

## 2. Tahapan Implementasi

### Tahap 0 — Dokumentasi (selesai di iterasi ini)
- [x] `business-rules.md`
- [x] `implementation-plan.md` (dokumen ini)
- [x] `CLAUDE.md` dengan ringkasan keputusan arsitektur

### Tahap 1 — Skeleton Plugin & Boilerplate QGIS — **SELESAI (diverifikasi manual 2026-09-08)**
- [x] Struktur folder dan `metadata.txt` sesuai konvensi plugin QGIS.
- [x] `__init__.py` dengan `classFactory()`.
- [x] `main_plugin.py` minimal: registrasi ke toolbar/menu QGIS (`initGui`, `unload`), satu tombol placeholder ("Buka AIM Editor") yang menampilkan pesan info di message bar QGIS — belum ada logic bisnis (belum connect ke `login_dialog`/`api_client`).
- [x] Symlink dibuat dari `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\aim_editor` ke folder `aim_editor/` di repo ini, untuk pengujian lokal di QGIS Desktop.
- [x] **Diverifikasi user langsung di QGIS Desktop:** plugin aktif tanpa error, tombol toolbar berfungsi dan menampilkan pesan info yang sesuai.
- **Kriteria selesai:** plugin bisa di-install ke QGIS (via symlink ke folder plugins) dan muncul di menu Plugins tanpa error, tombol toolbar ada tapi belum berfungsi penuh. **Tercapai.**

### Tahap 2 — Autentikasi REST API & Kredensial DB — **SELESAI & TERVERIFIKASI (2026-09-09)**
- [x] `api_client.py`: `login()`, `get_me()`, `get_db_credentials()`, disesuaikan dengan skema backend nyata:
  - `login()`: `POST /auth/login`, request body `{"login_id": ..., "password": ...}`, response `{"token": "v2.local...", "user": {...}}`.
  - `get_me()`: `GET /me` — **response TIDAK dibungkus envelope**, field (`permissions`, `roles`, dst) langsung di top-level.
  - `get_db_credentials()`: `GET /db-credentials` — **response DIBUNGKUS envelope `{"data": {...}}`**, beda dari `/me`. Field `schema` disertakan (lihat catatan Tahap 3-4 di bawah).
- [x] `login_dialog.py`: field "Server URL" (default dari `settings.py`, disimpan lagi setelah login sukses) + login_id/password, memanggil `api_client`.
- [x] `settings.py` (baru): wrapper `QSettings` — `get_base_url()`/`set_base_url()`.
- [x] `auth_manager.py`: `store_credentials()`, `update_credentials()`, `remove_credentials()`.
- [x] `main_plugin.py`: tombol toolbar terhubung penuh ke `LoginDialog` → simpan kredensial via `auth_manager`. Login ulang dalam sesi QGIS yang sama memakai `update_credentials()` (bukan `store_credentials()` lagi) untuk menghindari config auth duplikat menumpuk di `qgis-auth.db`.
- **Bug ditemukan & diperbaiki lewat testing manual nyata di QGIS Desktop**: `get_db_credentials()` sempat mengakses field response langsung di top-level (`data["host"]`, dst), padahal response endpoint ini dibungkus envelope `{"data": {...}}` — beda dari `/me` yang tidak dibungkus. Menyebabkan `ApiError` generik ("Response db-credentials ga lengkap field-nya") yang membingungkan karena tidak menyebut field spesifik. Diperbaiki: baca lewat `body["data"]`, dan pesan error sekarang menyertakan detail exception asli.
- **Kriteria selesai:** dari dialog login, plugin berhasil dapat token PASETO, memanggil `/db-credentials`, dan menyimpan kredensial ke `qgis-auth.db`. **Tercapai** — diverifikasi langsung: login `ad_editor`/`ad_editor` di QGIS Desktop sukses, pesan sukses muncul di message bar, config `aim_editor_pg_session` terbentuk di Settings > Options > Authentication.

### Tahap 3 — Pencarian Parent (adhp / bandara) — **SELESAI & TERVERIFIKASI (2026-09-09)**
- **Keputusan struktur menu (2026-09-09):** plugin ini akan menangani beberapa jenis data di iterasi mendatang, dan sebagian entitas masa depan **belum tentu terikat konteks bandara** — jadi "Login" dan "cari/edit per jenis data" adalah dua action terpisah, bukan satu alur linear:
  - Action **"Buka AIM Editor"** — cuma login + simpan sesi via `auth_manager`. Selalu aktif sejak awal.
  - Action **"Apron/Taxiway"** — baru **di-enable** setelah login sukses (disabled sebelum itu). Membuka `AdhpSearchDialog` karena entitas ini memang terikat bandara (lihat business-rules.md Bagian 1). Entitas mendatang yang tidak terikat bandara akan mendapat action serupa yang **tidak** melalui `AdhpSearchDialog`.
  - Kedua action didaftarkan ke **toolbar dan menu Plugins sekaligus** (lewat `add_action()`, bukan salah satu) — pola ini dipertahankan untuk action entitas berikutnya.
- **Catatan penting soal schema:** tabel `adhp`/`ADHPSurfaceArea` **tidak berada di schema `public`** — dikonfirmasi lewat percobaan langsung saat setup role PostgreSQL di sisi backend (lihat `backend-aim/docs/aim-pages/qgis-support/qgis-be-implementation-plan.md` Tahap 3). Nama schema **bukan** dikonfigurasi manual lewat `QSettings` di plugin — endpoint `GET /db-credentials` sekarang mengembalikan field `schema` eksplisit (lihat Tahap 2 di atas, dan `qgis-be-business-rules.md`), dan itulah yang menjadi sumber kebenaran satu-satunya. `QgsDataSourceUri` yang dipakai untuk memuat layer `adhp` maupun `ADHPSurfaceArea` **wajib** diset eksplisit lewat `setSchema(<nilai dari field schema>)` — bukan mengandalkan default `public`, bukan pula nilai yang di-hardcode di kode plugin.
- [x] `adhp_search_dialog.py`: form pencarian dengan input ICAO/IATA/nama, hasil ditampilkan di `QTableWidget`, query terparameterisasi ke tabel `adhp` (kolom `icao_txt`, `iata_txt`, `name_txt`) via layer yang sudah dimuat dengan `authcfg`, memakai `QgsFeatureRequest` dengan `QgsExpression` (`ILIKE` gabungan tiga kolom) yang nilainya di-bind lewat `QgsExpressionContext`. Tidak menambah dependency terpisah (mis. psycopg2) — cukup lewat API `QgsVectorLayer`/`QgsFeatureRequest` yang sudah dipakai untuk memuat layer.
- [x] `layer_manager.py` (baru, sebagian — fungsi load `adhp` "dipinjam maju" dari Tahap 4 karena jadi prasyarat Tahap 3): `load_adhp_layer()`, helper `_build_postgres_uri()` yang dipakai bersama untuk Tahap 4 nanti.
- [x] Hasil pilihan yang diteruskan ke `main_plugin.py` adalah `gfid` (string, **bukan** integer/uuid) beserta kolom identitas lain (`icao_txt`, `iata_txt`, `name_txt`) dan `geometry` (titik lokasi) untuk keperluan zoom kanvas.
- **Bug ditemukan & diperbaiki lewat testing manual nyata di QGIS Desktop**: `QgsExpressionContext` **tidak punya** method `setVariable()` langsung (API PyQGIS) — variabel ekspresi (`@keyword`) harus ditambahkan lewat `QgsExpressionContextScope` yang di-`appendScope()`-kan ke context. Diperbaiki: `scope = QgsExpressionContextScope(); scope.setVariable(...); context.appendScope(scope)`.
- **Struktur menu diimplementasikan**: action "Buka AIM Editor" (login) dan "Apron/Taxiway" (search+nanti load layer) dipisah di `main_plugin.py`, action kedua di-`setEnabled(True)` setelah login sukses.
- **Kriteria selesai:** pengguna dapat mencari bandara dan memilih satu baris hasil, hasil pilihan (`gfid`, icao, iata, nama, titik lokasi) diteruskan ke `main_plugin.py`. **Tercapai** — diverifikasi langsung di QGIS Desktop: pencarian ICAO/IATA/nama mengembalikan hasil yang benar, pemilihan baris berhasil, kanvas zoom ke lokasi bandara terpilih.

### Tahap 4 — Pemuatan & Pemfilteran Layer — **SELESAI & TERVERIFIKASI (2026-09-09)**
- **PENTING — JANGAN pakai tanda kutip di sekitar nama tabel/kolom `ADHPSurfaceArea`/`SUBTYPE_CODE`/`ADHP_ID`/`GFID` dst. dalam ekspresi `setSubsetString()`/SQL apa pun.** Migration backend membuat tabel ini **tanpa** tanda kutip (`CREATE TABLE ADHPSurfaceArea (...)`), sehingga PostgreSQL secara otomatis melipat (fold) semua identifier itu ke huruf kecil (tersimpan sebagai `adhpsurfacearea`, `subtype_code`, dst). Menambahkan tanda kutip (mis. `"SUBTYPE_CODE"`) membuat Postgres mencari nama persis huruf besar-kecilnya yang **tidak ada**, dan query gagal (`relation/column ... does not exist`) — dikonfirmasi langsung lewat error nyata saat setup role Postgres di sisi backend (lihat `backend-aim/docs/aim-pages/qgis-support/qgis-be-implementation-plan.md` Tahap 3). Semua contoh ekspresi di dokumen ini sudah sengaja ditulis tanpa kutip — pertahankan itu saat menulis kode Python sungguhan.
- **Nama schema tabel wajib diambil dari field `schema` pada response `/db-credentials`** (ditambahkan ke API, lihat `backend-aim` Tahap 2) — **bukan** `public`. Dikonfirmasi lewat percobaan langsung bahwa `adhp`/`ADHPSurfaceArea` berada di schema yang mengikuti nama user koneksi database backend, bukan schema default. `QgsDataSourceUri` harus di-set eksplisit `setSchema(<nilai dari field schema>)` sebelum memuat layer.
- [x] `layer_manager.py`:
  - `load_surface_area_layers(permissions, auth_config_id)`: memuat layer dari tabel `ADHPSurfaceArea` (dua entri layer di panel plugin: "Apron" dan "Taxiway", keduanya bersumber dari tabel yang sama dengan `setSubsetString()` dasar `SUBTYPE_CODE = 8` dan `SUBTYPE_CODE = 6` secara berurutan), hanya dimuat kalau `permissions` user memuat `qgis-apron-taxiway:read` (mode baca) atau `qgis-apron-taxiway:update` (mode dapat diedit) — lihat business-rules.md Bagian 4.1. Memakai `QgsDataSourceUri` + `setAuthConfigId`.
  - `filter_children_by_adhp(gfid)`: menambahkan kondisi `adhp_id = '<gfid>'` (gfid di-escape manual, bukan concatenation bebas) ke `setSubsetString()` tiap layer (digabung dengan filter `subtype_code` yang sudah ada).
  - `set_feature_defaults(layer, gfid, subtype_code, username, domain_layers)`: menerapkan `QgsDefaultValue` pada kolom `gfid` (`upper(uuid())`, meniru pola generate GFID backend Go persis, read-only), `adhp_id` (nilai string `gfid`, read-only), `subtype_code` (nilai tetap sesuai layer, read-only), `type_code` (lihat `_configure_type_code()` di bawah), kolom audit (lihat Tahap 4.5), dan `designator_txt` (default `name_txt` kalau masih kosong, expression `QgsDefaultValue("name_txt", False)` — bukan dipaksa sama terus, user tetap bisa override manual).
  - `_configure_type_code(layer, subtype_code)`: domain `type_code` berbeda per subtype — Taxiway pakai combobox `ValueMap` (13 pilihan tetap, `TAXIWAY_TYPE_CODE_OPTIONS`, hardcode karena domainnya fixed per skema AIS/ICAO); Apron secara skema "Not Applicable" tapi user (2026-09-09) minta tetap tampil fixed `'APRON'`, read-only (bukan disembunyikan).
  - `load_domain_layers(db_credentials, auth_config_id)` + `_configure_domain_value_relation()`: kolom `status_code`/`abandoned_code` pakai combobox `ValueRelation` (BUKAN `ValueMap` hardcode) yang query dinamis ke tabel lookup generik backend `domains_text`/`domains_smallint` (kolom `category`/`code`/`description`, difilter `category = 'Code_Sts_Sfc'`/`'Code_Yes_No'`) — dipilih dinamis karena nilai domain ini bisa diubah admin backend kapan saja lewat endpoint CRUD-nya sendiri, tidak seperti `type_code` Taxiway yang domainnya memang fixed di skema AIS/ICAO. Butuh `GRANT SELECT` tambahan ke kedua tabel lookup ini di role Postgres plugin (ditambahkan ke `qgis-be-implementation-plan.md`/`APP_README.md` Tahap 3, dijalankan user 2026-09-09) — opsional dari sisi plugin (kalau grant belum ada, combobox fallback nonaktif tanpa dianggap error fatal, lihat `main_plugin.py`).
  - `_apply_form_field_order(layer, field_order_top)`: form atribut **hanya menampilkan** 13 field (bukan >40 kolom mentah skema) sesuai urutan yang diminta user (2026-09-09, direvisi beberapa kali lewat testing manual) — `adhp_id`, `gfid`, `subtype_code`, `type_code` (4 field pertama read-only), `name_txt`, `status_code`, `abandoned_code`, `remarks_txt`, `source_txt` (editable), lalu `created_user`, `created_date`, `last_edited_user`, `last_edited_date` (read-only, tetap ditampilkan sebagai textbox abu-abu biar user bisa lihat histori, bukan disembunyikan). Field lain di skema **sengaja tidak dimasukkan ke form sama sekali** (bukan ditaruh di bawah+disabled seperti rencana awal) — keputusan setelah user mencoba form yang menampilkan semua kolom: terlalu panjang, tidak bisa di-scroll, tombol Simpan hilang dari layar. **Bug ditemukan & diperbaiki lewat testing manual**: `QgsEditFormConfig` defaultnya `GeneratedLayout` (auto-generate dari urutan kolom skema DB apa adanya) — di mode itu `invisibleRootContainer()`/`addChildElement()` yang disusun manual **sama sekali diabaikan** oleh form renderer GUI (walau programatik lewat `editFormConfig()` sudah benar). Wajib `form_config.setLayout(QgsEditFormConfig.TabLayout)` dulu sebelum menyusun ulang field, baru form GUI benar-benar mengikuti susunan itu.
  - Nama layer dirender dinamis menampilkan bandara aktif (mis. "WIII - Apron", "WIII - Taxiway", diminta user 2026-09-09) — **subtype tetap diidentifikasi dari key dict internal ("apron"/"taxiway"), bukan dari `layer.name()`** yang sudah berubah-ubah, supaya tidak salah tebak subtype.
  - Zoom kanvas awal (diminta user 2026-09-09) dengan 2 kondisi: (1) bandara belum punya geometri Apron/Taxiway sama sekali → zoom ke titik ARP `adhp.shape` dengan buffer 0.01 derajat (~1.1 km, disesuaikan setelah user uji coba merasa buffer awal 0.05° terlalu jauh untuk bandara ukuran sedang); (2) sudah ada geometri → zoom ke extent gabungan (`combineExtentWith`) kedua layer Apron+Taxiway yang sudah difilter, bukan ke ARP. **Bug ditemukan & diperbaiki lewat testing manual**: extent dari layer/geometry PostGIS masih dalam CRS sumber (EPSG:4326/WGS84 derajat), sedangkan `mapCanvas().setExtent()` menginterpretasikan angka yang diberikan sebagai CRS project/kanvas (biasanya EPSG:3857/meter) **tanpa transform otomatis** — kalau lupa transform, kanvas "lompat" ke koordinat salah total (derajat disalahartikan sebagai meter), tampil kosong/abu-abu walau panel koordinat menunjukkan sudah "sampai" ke lokasi. Diperbaiki dengan helper `_transform_extent()` (pakai `QgsCoordinateTransform`, baca CRS kanvas secara dinamis — robust walau user ganti CRS project ke yang lain, bukan hardcode EPSG:3857).
- **Kriteria selesai:** setelah memilih bandara di Tahap 3, layer "Apron" dan "Taxiway" di kanvas otomatis terfilter hanya menampilkan fitur milik bandara tsb (dan subtipe yang sesuai), kanvas zoom ke sekitar lokasi bandara (ARP kalau kosong, extent geometri kalau sudah ada), dan menambah fitur baru otomatis mengisi `adhp_id`, `subtype_code`, `gfid` yang benar. **Tercapai** — diverifikasi lewat MCP QGIS (`execute_code`, `get_layers`, `get_canvas_screenshot`) dan testing manual GUI user untuk WIII, WAQQ, WITT.
- **TODO/belum dikerjakan (di-park, dicatat 2026-09-09):** dialog form atribut masih memakai ukuran dialog terakhir (tersimpan global di `QSettings` QGIS, `Windows/AttributeDialog/geometry`, dipakai semua layer bukan cuma Apron/Taxiway) — kalau sebelumnya pernah dibesarkan untuk layer lain yang field-nya banyak, form Apron/Taxiway yang cuma 13 field ikut kebesaran juga (perlu resize manual). Solusi yang dipertimbangkan: event filter Qt global yang auto-resize `QgsAttributeDialog` tiap kali muncul berdasar jumlah field aktual — user memutuskan skip dulu, bisa dikerjakan nanti kalau masih dirasa perlu.

### Tahap 4.6 — Koreksi & Fitur Editing Tambahan (2026-09-09, sesi lanjutan) — **SELESAI & TERVERIFIKASI**
Kumpulan koreksi/fitur yang muncul dari testing manual GUI setelah Tahap 4 "selesai" -- dicatat sebagai
sub-tahap terpisah karena volumenya cukup banyak untuk satu sesi kerja. Detail lengkap tiap poin ada di
`dev-log.md` (entri "koreksi & fitur editing tambahan").

- [x] **Konfirmasi sebelum ganti bandara/login ulang saat sesi editing aktif** — `_confirm_end_editing()`
  baru di `main_plugin.py`, cegah state layer berantakan kalau user pindah konteks di tengah edit belum
  disimpan.
- [x] **Fix bug zoom kanvas CRS mismatch** — extent dari layer PostGIS (EPSG:4326) wajib ditransform ke
  CRS kanvas (`_transform_extent()`, `QgsCoordinateTransform`) sebelum `setExtent()`, kalau tidak kanvas
  tampil blank/lompat ke lokasi salah.
- [x] **Tombol "Kosongkan Geometri Fitur Terpilih"** dan **"Timpakan Geometri ke Baris Terpilih"** —
  dua action baru di toolbar/menu plugin buat 2 skenario yang QGIS tidak punya tool GUI bawaannya:
  mengosongkan geometri fitur existing tanpa hapus baris, dan mengisi geometri ke baris existing yang
  masih NULL (tanpa perlu re-entry atribut manual).
- [x] **Koreksi: `type_code` Apron wajib NULL** (bukan fixed `'APRON'` seperti keputusan Tahap 4 awal) —
  field dihilangkan total dari form Apron (tetap tampil di Taxiway), default value expression `NULL`.
- [x] **Fix bug `designator_txt` tidak ke-set** — field lupa didaftarkan ke list field form, jadi default
  value-nya tidak pernah ter-trigger (form sekarang filter, bukan cuma reorder).
- [x] **Fix bug dialog error login muncul 2x** — race condition Qt di `LoginDialog`, tombol OK di-enable
  terlalu cepat (sebelum `QMessageBox.critical()` benar-benar tertutup).
- [x] Fokus awal form login ke field Username/Email (`showEvent()` override).
- [x] Label kanvas fitur Apron/Taxiway dari `name_txt`.
- [x] Attribute Table disamakan kolom+urutannya dengan form (`_apply_attribute_table_config()`), ditambah
  kolom virtual `shape_status` (Ada/Kosong) di posisi terakhir buat cek cepat baris mana yang geometrinya
  belum digambar.
- **Kriteria selesai:** semua poin di atas diverifikasi lewat MCP QGIS (`execute_code`) dan/atau testing
  manual GUI user. **Tercapai.**

### Tahap 4.5 — Pengisian Kolom Audit (created_user/last_edited_user) — **SELESAI & TERVERIFIKASI (2026-09-09)**
- Tabel `ADHPSurfaceArea` sudah punya kolom `created_user`, `created_date`, `last_edited_user`, `last_edited_date`, tapi **tidak ada trigger DB** yang mengisinya (dikonfirmasi dari migration) — plugin **wajib** mengisi ini sendiri, bukan opsional.
- [x] `layer_manager.py` (lanjutan `set_feature_defaults`): `QgsDefaultValue` untuk `last_edited_date`/`created_date` memakai ekspresi `now()`; untuk `last_edited_user`/`created_user` memakai identitas pengguna aplikasi yang sedang login (username dari hasil `GET /me`, disimpan di `main_plugin.py` setelah login, disisipkan sebagai literal string ter-escape ke ekspresi — bukan `current_user` SQL karena itu akan mengembalikan nama role Postgres bersama, bukan identitas individu, lihat business-rules.md Bagian 3.2). Keempat kolom ini `applyOnUpdate=True` (re-evaluasi tiap commit, bukan cuma sekali saat fitur dibuat) dan `read_only=True` di form (textbox abu-abu, user bisa lihat tapi tidak bisa ketik manual — dua mekanisme independen: `readOnly` form cuma soal UI, `applyOnUpdate` soal expression evaluation saat commit, jadi field tetap keupdate otomatis walau read-only di form).
- **Kriteria selesai:** fitur baru maupun fitur yang diedit ulang menunjukkan `last_edited_user` terisi username aplikasi yang benar (bukan kosong/null, bukan nama role Postgres) setelah commit. **Tercapai** — diverifikasi lewat MCP QGIS (`editFormConfig()`/`defaultValueDefinition()`).

### Tahap 5 — Perpanjangan Sesi (Session Renewal)
- Mekanisme timer/pengecekan `expires_at` kredensial (mis. `QTimer` di `main_plugin.py`), memanggil ulang `/db-credentials` sebelum kedaluwarsa dan `update_credentials()` pada `auth_manager.py`.
- **Kriteria selesai:** simulasi kredensial mendekati kedaluwarsa (mis. set `expires_at` singkat di server dev) tidak memutus sesi edit yang sedang berjalan; layer tetap bisa commit setelah refresh terjadi di background.

### Tahap 6 — Cleanup & Lifecycle
- [x] `unload()` di `main_plugin.py`: memanggil `auth_manager.remove_credentials()`, melepas layer yang dimuat plugin, membersihkan referensi — **sudah dikerjakan sejak Tahap 1**.
- [ ] Hook logout eksplisit (tombol logout di UI) yang melakukan hal serupa tanpa perlu unload plugin/QGIS — **belum dikerjakan**, sengaja ditunda (diputuskan 2026-09-09) supaya bisa lanjut ke Tahap 3-4 dulu. Untuk sementara, membersihkan sesi cukup lewat nonaktifkan plugin di Plugin Manager, atau hapus manual config "aim_editor_pg_session" di Settings > Options > Authentication.
- **Kriteria selesai:** setelah logout atau plugin di-unload, config di `qgis-auth.db` sudah tidak ada lagi (diverifikasi via Settings > Options > Authentication). **Tercapai untuk jalur unload**, belum ada jalur logout eksplisit untuk diverifikasi.

### Tahap 6.5 — Unit Test Otomatis
- Ditulis untuk logic yang tidak bergantung langsung pada runtime QGIS (atau bisa di-mock), memakai `pytest` + `unittest.mock`:
  - `api_client.py`: `login()`, `get_me()`, `get_db_credentials()` — mock response `requests`, uji penanganan error (status non-200, field response hilang/rusak).
  - `layer_manager.py`: logic pembentukan ekspresi `setSubsetString()` (kombinasi `ADHP_ID` + `SUBTYPE_CODE`) dan `QgsDefaultValue` dari `gfid` — uji nilai yang dihasilkan benar dan aman dari injeksi (mis. `gfid` yang mengandung karakter kutip tidak merusak ekspresi SQL/QGIS), serta uji bahwa `SUBTYPE_CODE` yang dihasilkan selalu 6 atau 8, tidak pernah nilai subtipe lain.
  - `adhp_search_dialog.py`: logic pembentukan ekspresi pencarian dari input ICAO/IATA/nama — uji binding parameter, bukan string concatenation mentah.
- Bagian yang butuh QGIS runtime penuh (`QgsAuthManager`, `QgsVectorLayer` yang benar-benar connect ke PostGIS) **tidak** di-unit-test di sini — itu tercakup di Tahap 7 (manual E2E). Unit test fokus ke logic murni Python yang bisa diisolasi.
- **Kriteria selesai:** `pytest` berjalan tanpa perlu instalasi QGIS penuh (mock `qgis.core` seperlunya), semua test hijau, mencakup jalur sukses dan jalur gagal/edge case pada modul-modul di atas.

### Tahap 7 — Pengujian Manual End-to-End
- Skenario uji dengan minimal 2 kombinasi hak akses berbeda (mis. permission `qgis-apron-taxiway:read` saja vs `qgis-apron-taxiway:update`) untuk memverifikasi RLS dan grant Postgres bekerja sesuai harapan dari sisi plugin.
- Skenario uji tambah fitur Apron baru, tambah fitur Taxiway baru, edit geometri existing, hapus fitur — verifikasi kolom `last_edited_user`/`last_edited_date` terisi benar, `ADHP_ID` dan `SUBTYPE_CODE` benar, dan fitur Runway/subtipe lain di `ADHPSurfaceArea` **tidak** ikut termuat/dapat diedit lewat plugin.
- Skenario uji edit bersamaan (concurrent edit) dua sesi QGIS pada fitur yang sama, verifikasi perilaku last-write-wins sesuai business-rules.md Bagian 5.1 (tidak ada crash/error tak terduga, commit belakangan yang menang).
- Skenario uji negatif: pastikan role PostgreSQL yang dipetakan plugin **tidak bisa** mengakses tabel otorisasi backend (`users`, `roles`, `permissions`, dst.) sama sekali — mis. coba `SELECT` langsung ke tabel tsb pakai kredensial yang didapat plugin, harus ditolak (lihat business-rules.md Bagian 6, poin 2).
- Dokumentasikan hasil pengujian di `docs/` terpisah jika diperlukan (di luar cakupan dokumen ini).

### Tahap 8 — Distribusi via QGIS Plugin Repository
- Menyusun berkas `plugins.xml` yang menunjuk ke rilis `.zip` plugin di GitHub Releases repositori ini (repositori publik).
- Menyiapkan proses build rilis: packaging folder `aim_editor/` menjadi `.zip` sesuai konvensi struktur plugin QGIS, versi mengikuti `metadata.txt`.
- Dokumentasi singkat untuk pengguna internal: cara menambahkan URL repository kustom di QGIS Plugin Manager (Settings > Plugins > Settings > Plugin Repositories) — sekali saja per instalasi QGIS pengguna.
- (Opsional, dipertimbangkan bukan wajib rilis awal) Endpoint `/version` atau `/health` di backend REST API yang dicek plugin saat startup, untuk mendeteksi ketidakcocokan versi plugin vs backend yang sedang aktif dikembangkan, dan menampilkan pesan yang jelas ke pengguna bila tidak kompatibel.
- **Kriteria selesai:** minimal satu rilis `.zip` ter-publish di GitHub Releases, `plugins.xml` valid dan bisa ditambahkan sebagai repository kustom di QGIS Plugin Manager pada instalasi QGIS terpisah (bukan mesin development), plugin terdeteksi sebagai "upgradeable" saat versi baru dirilis.

### Tahap 9 (Iterasi Mendatang) — Entitas/Subtipe Tambahan
- Di luar cakupan rilis awal, dicatat di sini sebagai pola untuk iterasi berikutnya: subtipe lain di `ADHPSurfaceArea` (Runway, RunwayProtection, FATO, FATOProtection, TLOF, TLOFProtection, Stopway, BlastPad) atau tabel geometri AIS/ICAO lain (`ADHPSurfacePoint`, `ADHPSurfaceLine`, `Marking`, dst.) dapat ditambahkan **satu per satu**, mengikuti pola yang sama seperti Tahap 3-4.5 di atas (permission baru di `/me`, entri layer baru di `layer_manager.py`, default value untuk `ADHP_ID`/kolom pembeda subtipe/kolom audit). **Tidak dikerjakan sebagai bagian rilis awal.**

## 3. Hal di Luar Cakupan Plugin (Tanggung Jawab Server/DB, Bukan Kode Plugin Ini)

Seluruh pekerjaan sisi backend/database untuk mendukung plugin ini (endpoint `GET /db-credentials`, permission dan role aplikasi baru, pembuatan peran PostgreSQL beserta grant-nya, kebijakan Row-Level Security, jejak audit) **didokumentasikan secara terpisah dan lengkap** di repositori backend (`backend-aim`, sudah tersedia di workspace yang sama):

- **Aturan bisnis:** `backend-aim/docs/aim-pages/qgis-support/qgis-be-business-rules.md`
- **Rencana implementasi:** `backend-aim/docs/aim-pages/qgis-support/qgis-be-implementation-plan.md`

Dokumen ini (repo `qgis-aim`) tidak lagi menduplikasi detail teknis backend tersebut — cukup mencatat poin ringkas berikut sebagai konteks:

- Plugin **tidak** memakai permission `runway:*` existing untuk otorisasi (cakupannya terlalu luas, meliputi Runway/FATO/TLOF dst. yang tidak boleh diedit lewat plugin). Backend menambahkan permission baru khusus: `qgis-apron-taxiway:read` dan `qgis-apron-taxiway:update`.
- Endpoint `GET /db-credentials` memetakan permission tsb ke peran PostgreSQL `qgis_writer_apron_taxiway` (punya `update`) atau `qgis_reader_apron_taxiway` (`read` saja) — nama peran ini yang dipakai `api_client.py`/dokumentasi plugin sebagai acuan, bukan `qgis_writer_apron_taxiway` versi asumsi lama yang sempat dipetakan dari `runway:update`.
- Kedua peran PostgreSQL tsb digrant eksplisit hanya ke `ADHPSurfaceArea` dan `SELECT` pada `adhp`, dengan RLS membatasi ke `SUBTYPE_CODE IN (6, 8)`. Sama sekali tidak ada akses ke tabel otorisasi backend (`users`/`roles`/`permissions`/dst.) walau satu database yang sama.

Item-item di atas adalah prasyarat infrastruktur yang harus tersedia agar plugin dapat berfungsi sesuai aturan bisnis. Implementasinya berada di luar kode plugin QGIS ini (repo `qgis-aim`), tapi tidak berarti di luar jangkauan sesi kerja ini — repo `backend-aim` sudah tersedia di workspace yang sama dan dapat dikerjakan atas permintaan eksplisit user.

## 4. Hal yang Masih Perlu Dikonfirmasi User Sebelum Finalisasi

1. Daftar kolom `ADHPSurfaceArea` yang perlu ditonjolkan di Attribute Form untuk Apron/Taxiway (tabel ini punya >40 kolom, sebagian besar tidak relevan untuk kedua subtipe ini) — lihat business-rules.md Bagian 5. Perlu masukan dari pihak yang memahami kebutuhan operasional data AIS/ICAO organisasi, bukan keputusan teknis semata.
2. Apakah mode **baca-saja** (read-only, permission `qgis-apron-taxiway:read` tanpa `update`) benar-benar perlu dilayani plugin di rilis awal, atau cukup mensyaratkan `qgis-apron-taxiway:update` untuk bisa memakai plugin sama sekali. Peran PostgreSQL `qgis_reader_apron_taxiway` untuk skenario ini sudah didesain di sisi backend (lihat `qgis-be-business-rules.md` Bagian 3.2), tapi apakah plugin perlu mengimplementasikan UI mode baca-saja di rilis awal masih terbuka.
3. Apakah dibutuhkan dukungan multi-bahasa UI (Indonesia/Inggris) untuk dialog-dialog plugin, atau cukup satu bahasa saja untuk end-user.
4. Prioritas subtipe/entitas berikutnya setelah Apron+Taxiway stabil (lihat Tahap 9) — belum perlu diputuskan sekarang, dicatat sebagai pertanyaan terbuka untuk iterasi mendatang.

Sudah diputuskan (tidak lagi terbuka untuk diskusi, dicatat untuk riwayat keputusan):
- **Skema data GIS nyata:** parent = `adhp` (PK `gfid` VARCHAR(38)), child rilis awal = `ADHPSurfaceArea` (PK `GFID`, FK `ADHP_ID`, dibedakan `SUBTYPE_CODE`). **Bukan** tabel `airport`/`apron`/`taxiway` terpisah seperti asumsi dokumen versi awal. Model data AIS/ICAO ini sudah dipakai lewat tabel existing, **tidak ada migrasi skema baru** yang dikerjakan untuk kebutuhan plugin ini.
- **Cakupan rilis awal dibatasi ke `SUBTYPE_CODE` 6 (Taxiway) dan 8 (Apron) saja** dari 10 subtipe yang ada di `ADHPSurfaceArea`. Subtipe lain, dan tabel geometri AIS/ICAO lain di luar `ADHPSurfaceArea`, ditambahkan satu per satu di iterasi mendatang (lihat Tahap 9) — plugin **tidak** dirancang untuk mendukung seluruh skema AIS/ICAO sekaligus.
- **Concurrent edit:** last-write-wins, tanpa locking eksplisit (lihat business-rules.md Bagian 5.1).
- **Distribusi/update plugin:** QGIS Plugin Repository kustom (`plugins.xml` + GitHub Releases), bukan self-update kustom (lihat business-rules.md Bagian 8).
- **Granularitas role PostgreSQL:** 1 role per kelompok hak akses, bukan per user individu, bukan role pemilik skema database (lihat business-rules.md Bagian 3.2). Role plugin wajib digrant eksplisit hanya ke tabel GIS, tidak ke tabel otorisasi backend walau di database yang sama.
- **Skema rights/roles/permissions backend:** dikonfirmasi via riset langsung ke repo `backend-aim`. Autentikasi PASETO v2 local via `POST /auth/login` (request `{login_id, password}`, response `{token, user}`); hak akses lewat `GET /me` existing (`permissions`: array string `resource:action`, `roles`: array objek). `ADHPSurfaceArea` secara historis berada di bawah payung permission `runway:*` di backend, namun plugin ini memakai permission baru khusus (`qgis-apron-taxiway:read`/`qgis-apron-taxiway:update`) yang scope-nya lebih sempit — lihat `backend-aim/docs/aim-pages/qgis-support/qgis-be-business-rules.md`.
- **Scope RLS rilis awal:** per `SUBTYPE_CODE`, bukan per bandara/wilayah — karena sistem permission backend tidak punya konsep scope tersebut (lihat business-rules.md Bagian 3.2 dan Bagian 6).
- **Tidak ada RLS maupun trigger audit existing di database ini** — dikonfirmasi lewat riset migration, keduanya pekerjaan baru penuh.
- **Otorisasi plugin memakai role & permission aplikasi baru yang khusus**, bukan menumpang pada role `admin_aerodrome`/`editor_aerodrome` atau permission `runway:*` existing yang scope-nya lebih luas. Permission baru: `qgis-apron-taxiway:read`, `qgis-apron-taxiway:update`. Role baru: `qgis_editor_apron_taxiway`, `qgis_viewer_apron_taxiway`. Detail lengkap dan rencana implementasinya ada di `backend-aim/docs/aim-pages/qgis-support/qgis-be-business-rules.md` dan `qgis-be-implementation-plan.md`.

Rencana ini akan direvisi begitu poin-poin yang masih terbuka di atas terjawab.
