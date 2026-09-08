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

### Tahap 1 — Skeleton Plugin & Boilerplate QGIS
- Struktur folder dan `metadata.txt` sesuai konvensi plugin QGIS.
- `__init__.py` dengan `classFactory()`.
- `main_plugin.py` minimal: registrasi ke toolbar/menu QGIS (`initGui`, `unload`), tanpa logic bisnis dulu — cukup bisa di-load QGIS tanpa error.
- **Kriteria selesai:** plugin bisa di-install ke QGIS (via symlink ke folder plugins) dan muncul di menu Plugins tanpa error, tombol toolbar ada tapi belum berfungsi.

### Tahap 2 — Autentikasi REST API & Kredensial DB
- `api_client.py`: implementasi `login()`, `get_me()`, `get_db_credentials()`, disesuaikan dengan skema backend nyata (hasil riset repo `backend-aim`, Go/Gin) — **sudah dikerjakan**:
  - `login()`: `POST /auth/login`, request body `{"login_id": ..., "password": ...}`, response `{"token": "v2.local...", "user": {...}}`.
  - `get_me()`: `GET /me` (endpoint existing), response memuat `roles` (array objek) dan `permissions` (array string `resource:action`). Untuk rilis awal, plugin memeriksa keberadaan permission `qgis-apron-taxiway:read`/`qgis-apron-taxiway:update` (permission baru khusus plugin ini, lihat business-rules.md Bagian 3.2 dan dokumen backend `backend-aim/docs/aim-pages/qgis-support/qgis-be-business-rules.md`) sebagai penentu apakah layer Apron/Taxiway boleh dimuat dan mode akses (baca-saja/dapat-diedit).
  - `get_db_credentials()`: endpoint **baru** `GET /db-credentials`, masih perlu ditambahkan ke backend (lihat Bagian 3 dokumen ini dan business-rules.md Bagian 3.2).
- `login_dialog.py`: dialog PyQt5 (login_id/password) yang memanggil `api_client` — **sudah dikerjakan**.
- `auth_manager.py`: wrapper `QgsAuthManager` — `store_credentials()`, `update_credentials()`, `remove_credentials()` — **sudah dikerjakan**.
- `settings.py`: base URL REST API disimpan via `QSettings` (bukan hardcode), agar bisa beda antara environment dev/staging/prod — **belum dikerjakan**.
- **Kriteria selesai:** dari dialog login, plugin berhasil dapat token PASETO, memanggil `/db-credentials`, dan menyimpan kredensial ke `qgis-auth.db` — dapat diverifikasi lewat menu Settings > Options > Authentication di QGIS bahwa config baru muncul (tanpa password terlihat plaintext).

### Tahap 3 — Pencarian Parent (adhp / bandara)
- `adhp_search_dialog.py`: form pencarian dengan input ICAO/IATA/nama, hasil ditampilkan di tabel (`QTableWidget`/`QTableView`), query terparameterisasi ke tabel `adhp` (kolom `icao_txt`, `iata_txt`, `name_txt`) via layer yang sudah dimuat dengan `authcfg`, memakai `QgsFeatureRequest` dengan `QgsExpression` yang nilainya di-bind sebagai parameter (bukan string formatting manual pada input pengguna). Tidak menambah dependency terpisah (mis. psycopg2) untuk query ini — cukup lewat API `QgsVectorLayer`/`QgsFeatureRequest` yang sudah dipakai untuk memuat layer.
- Hasil pilihan yang diteruskan ke `main_plugin.py` adalah `gfid` (string, **bukan** integer/uuid) beserta kolom identitas lain (`icao_txt`, `iata_txt`, `name_txt`) dan `shape` (titik lokasi, `PointZ`) untuk keperluan zoom kanvas.
- **Kriteria selesai:** pengguna dapat mencari bandara dan memilih satu baris hasil, hasil pilihan (`gfid`, icao, iata, nama, titik lokasi) diteruskan ke `main_plugin.py`.

### Tahap 4 — Pemuatan & Pemfilteran Layer
- `layer_manager.py`:
  - `load_surface_area_layers(permissions, auth_config_id)`: memuat layer dari tabel `ADHPSurfaceArea` (dua entri layer di panel plugin: "Apron" dan "Taxiway", keduanya bersumber dari tabel yang sama dengan `setSubsetString()` dasar `SUBTYPE_CODE = 8` dan `SUBTYPE_CODE = 6` secara berurutan), hanya dimuat kalau `permissions` user memuat `qgis-apron-taxiway:read` (mode baca) atau `qgis-apron-taxiway:update` (mode dapat diedit) — lihat business-rules.md Bagian 4.1. Memakai `QgsDataSourceUri` + `setAuthConfigId`.
  - `filter_children_by_adhp(gfid)`: menambahkan kondisi `ADHP_ID = '<gfid>'` (di-bind sebagai parameter string, bukan concatenation) ke `setSubsetString()` tiap layer (digabung dengan filter `SUBTYPE_CODE` yang sudah ada), lalu zoom kanvas ke sekitar titik `adhp.shape` milik bandara terpilih (dengan buffer memadai, bukan extent fitur anak yang mungkin kosong).
  - `set_feature_defaults(layer, gfid, subtype_code)`: menerapkan `QgsDefaultValueDefinition` pada kolom `ADHP_ID` (nilai string `gfid`), `SUBTYPE_CODE` (nilai tetap sesuai layer: 6 atau 8), dan `last_edited_user`/`last_edited_date`/`created_user`/`created_date` (lihat Tahap 4.5), serta menandai `ADHP_ID`/`SUBTYPE_CODE` read-only di form konfigurasi layer (`QgsEditFormConfig`).
- **Kriteria selesai:** setelah memilih bandara di Tahap 3, layer "Apron" dan "Taxiway" di kanvas otomatis terfilter hanya menampilkan fitur milik bandara tsb (dan subtipe yang sesuai), kanvas zoom ke sekitar lokasi bandara, dan menambah fitur baru otomatis mengisi `ADHP_ID` serta `SUBTYPE_CODE` yang benar.

### Tahap 4.5 — Pengisian Kolom Audit (created_user/last_edited_user)
- Tabel `ADHPSurfaceArea` sudah punya kolom `created_user`, `created_date`, `last_edited_user`, `last_edited_date`, tapi **tidak ada trigger DB** yang mengisinya (dikonfirmasi dari migration) — plugin **wajib** mengisi ini sendiri, bukan opsional.
- `layer_manager.py` (lanjutan `set_feature_defaults`): `QgsDefaultValueDefinition` untuk `last_edited_date`/`created_date` memakai ekspresi `now()`; untuk `last_edited_user`/`created_user` memakai identitas pengguna aplikasi yang sedang login (username dari hasil `GET /me`, disimpan di `main_plugin.py` setelah login, diakses lewat variabel/expression function kustom QGIS — bukan `current_user` SQL karena itu akan mengembalikan nama role Postgres bersama, bukan identitas individu, lihat business-rules.md Bagian 3.2).
- **Kriteria selesai:** fitur baru maupun fitur yang diedit ulang menunjukkan `last_edited_user` terisi username aplikasi yang benar (bukan kosong/null, bukan nama role Postgres) setelah commit.

### Tahap 5 — Perpanjangan Sesi (Session Renewal)
- Mekanisme timer/pengecekan `expires_at` kredensial (mis. `QTimer` di `main_plugin.py`), memanggil ulang `/db-credentials` sebelum kedaluwarsa dan `update_credentials()` pada `auth_manager.py`.
- **Kriteria selesai:** simulasi kredensial mendekati kedaluwarsa (mis. set `expires_at` singkat di server dev) tidak memutus sesi edit yang sedang berjalan; layer tetap bisa commit setelah refresh terjadi di background.

### Tahap 6 — Cleanup & Lifecycle
- `unload()` di `main_plugin.py`: memanggil `auth_manager.remove_credentials()`, melepas layer yang dimuat plugin, membersihkan referensi.
- Hook logout eksplisit (tombol logout di UI) yang melakukan hal serupa tanpa perlu unload plugin/QGIS.
- **Kriteria selesai:** setelah logout atau plugin di-unload, config di `qgis-auth.db` sudah tidak ada lagi (diverifikasi via Settings > Options > Authentication).

### Tahap 6.5 — Unit Test Otomatis
- Ditulis untuk logic yang tidak bergantung langsung pada runtime QGIS (atau bisa di-mock), memakai `pytest` + `unittest.mock`:
  - `api_client.py`: `login()`, `get_me()`, `get_db_credentials()` — mock response `requests`, uji penanganan error (status non-200, field response hilang/rusak).
  - `layer_manager.py`: logic pembentukan ekspresi `setSubsetString()` (kombinasi `ADHP_ID` + `SUBTYPE_CODE`) dan `QgsDefaultValueDefinition` dari `gfid` — uji nilai yang dihasilkan benar dan aman dari injeksi (mis. `gfid` yang mengandung karakter kutip tidak merusak ekspresi SQL/QGIS), serta uji bahwa `SUBTYPE_CODE` yang dihasilkan selalu 6 atau 8, tidak pernah nilai subtipe lain.
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
