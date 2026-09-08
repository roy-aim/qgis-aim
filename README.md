# AIM Editor — QGIS Plugin

Plugin QGIS (Python) untuk mengedit geometri data infrastruktur kebandarudaraan (Apron dan Taxiway) di basis data PostGIS internal, dengan alur kerja yang terkendali dan otorisasi terpusat — bukan lewat Browser Panel/Layer Panel bawaan QGIS.

> **Status: dalam pengembangan aktif (belum siap pakai).** Skeleton awal sudah ada, sebagian besar logika inti (pemuatan layer, pencarian bandara, filter geometri) belum diimplementasikan. Lihat [docs/implementation-plan.md](docs/implementation-plan.md) untuk status tahapan.

## Gambaran Umum

Plugin ini memungkinkan pengguna internal untuk:
1. Login menggunakan akun aplikasi (bukan kredensial database) lewat dialog kustom.
2. Mencari bandara (parent) berdasarkan kode ICAO, IATA, atau nama.
3. Mengedit geometri **Apron** dan **Taxiway** milik bandara tersebut menggunakan perkakas *digitizing* native QGIS (snapping, undo/redo, form atribut standar) — bukan lewat form web terpisah.

Otorisasi dijembatani lewat REST API internal organisasi (autentikasi berbasis token PASETO), yang memetakan hak akses pengguna ke kredensial PostgreSQL yang di-*scope* secara sempit. Kredensial disimpan terenkripsi lewat QGIS Authentication Manager, tidak pernah dalam bentuk teks polos. Pengeditan geometri dilakukan langsung native ke PostGIS — proteksi data yang sesungguhnya berada di level basis data (Row-Level Security dan hak akses per peran), bukan hanya di plugin.

Detail lengkap arsitektur dan alasan di balik setiap keputusan desain ada di dokumen pada bagian [Dokumentasi](#dokumentasi) di bawah.

## Cakupan Rilis Saat Ini

Cakupan rilis awal **sengaja dibatasi**:
- Entitas induk (*parent*): tabel `adhp` (data bandara/aerodrome).
- Entitas anak (*child*): tabel `ADHPSurfaceArea`, dibatasi hanya subtipe **Taxiway** dan **Apron**.

Entitas atau subtipe lain akan ditambahkan secara bertahap satu per satu pada iterasi mendatang — plugin ini tidak dirancang untuk mendukung seluruh skema data AIS/ICAO sekaligus sejak awal.

## Instalasi

Plugin ini didistribusikan melalui **QGIS Plugin Repository kustom** milik organisasi, bukan repositori resmi QGIS.org. Instruksi instalasi bagi pengguna internal akan tersedia setelah rilis pertama dipublikasikan (lihat [docs/implementation-plan.md](docs/implementation-plan.md) Tahap 8).

Plugin ini bergantung pada REST API internal organisasi untuk otorisasi — tanpa akun aplikasi yang valid pada REST API tersebut, plugin tidak dapat digunakan meskipun berhasil terinstal.

## Dokumentasi

- [docs/business-rules.md](docs/business-rules.md) — Aturan bisnis lengkap: alur otorisasi, penyimpanan kredensial, aturan akses data, mitigasi keamanan, dan batasan yang diketahui.
- [docs/implementation-plan.md](docs/implementation-plan.md) — Rencana implementasi teknis bertahap beserta status pengerjaan tiap tahap.
- [docs/dev-log.md](docs/dev-log.md) — Riwayat ringkas pekerjaan pengembangan.
- [CLAUDE.md](CLAUDE.md) — Ringkasan konvensi dan keputusan arsitektur kunci proyek.

Pekerjaan sisi backend (endpoint otorisasi baru, peran basis data, Row-Level Security) didokumentasikan terpisah di repositori backend (privat), tidak termasuk dalam repositori ini.

## Kontribusi

Proyek ini bersifat internal organisasi. Lisensi dan panduan kontribusi eksternal belum ditentukan.
