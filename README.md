# OpenSOHO dla Home Assistanta

Dodatek dla Home Assistant OS z Supervisorem na `amd64` i `aarch64`. Panel OpenSOHO otwiera się z bocznego menu Home Assistanta. Routery OpenWrt rejestrują się, pobierają konfigurację i raportują monitoring przez osobny port LAN.

## Instalacja

1. Upewnij się, że gałąź udostępniana Supervisorowi zawiera `repository.yaml` i katalog `opensoho/`. W sklepie dodatków Home Assistanta otwórz menu repozytoriów i dodaj `https://github.com/pax0r/hass-open-soho`. Do instalacji lokalnej umieść katalog `opensoho/` w katalogu lokalnych dodatków HA OS i odśwież sklep.
2. Zainstaluj **OpenSOHO**. Supervisor buduje obraz ze wskazanych rewizji. Pierwszy build wymaga dostępu do danych obrazów Docker Hub, pakietów Debiana, GitHub, npm i publicznego proxy Go. Uruchomiony kontroler działa lokalnie. Obraz zawiera zasoby WWW i strefy czasowe.
3. W konfiguracji dodatku ustaw `shared_secret`. Możesz wygenerować 64 znaki poleceniem `openssl rand -hex 32` na zaufanym komputerze. Dodatek wymaga co najmniej 32 znaków. Zachowaj wartość do rejestracji routerów.
4. Włącz **Pokaż na pasku bocznym** na stronie dodatku. Jest to ustawienie instancji przechowywane przez Supervisor. Uruchom dodatek. Zaloguj się do HA jako administrator i otwórz **OpenSOHO** w bocznym menu. Użyj normalnego adresu HA, lokalnego lub zewnętrznego HTTPS. Zachowaj istniejącą konfigurację VPS, reverse proxy i WireGuarda.
5. Ustaw stały adres LAN hosta HA. Domyślny port agentów to `8090/tcp`. Jeżeli zmienisz port w ustawieniach sieciowych dodatku, zaktualizuj URL na routerach.

| Ścieżka | Przeznaczenie |
| --- | --- |
| Zewnętrzny lub lokalny adres HA | Panel i API administracyjne przez Ingress na wewnętrznym porcie dodatku 8091 |
| `http://<IP-HA-w-LAN>:8090` | Rejestracja, raporty stanu i metadanych, sumy kontrolne, archiwa konfiguracji i monitoring OpenWISP |
| `/data/opensoho/pb_data` | SQLite, pliki PocketBase i konfiguracja kontrolera |

Ogranicz dostęp do 8090 do zaufanych routerów lub sieci zarządzającej. HTTP na tym porcie nie szyfruje sekretu rejestracji, kluczy urządzeń ani konfiguracji. Port 8091 obsługuje Supervisor wewnątrz sieci HA i nie wymaga publikowania na hoście.

## Routery OpenWrt 25.12

1. Na Cudy WR3000H i TP-Link Archer C6 v2 sprawdź, czy działają `openwisp-config` i `openwisp-monitoring`. W LuCI ustaw **Server URL** na `http://<IP-HA-w-LAN>:8090` bez końcowego ukośnika oraz **Shared secret** na wartość z ustawień dodatku. Jeżeli pakiety są już zainstalowane, nie wymieniaj ich.
2. Uruchom lub zrestartuj `/etc/init.d/openwisp-config` oraz `/etc/init.d/openwisp-monitoring`. Jeśli potrzebujesz LuCI dla OpenWISP, na 25.12 użyj `apk add luci-app-openwisp`. W konfiguracji roamingu zweryfikuj pakiety `wpad-mbedtls` i `usteer` na obu urządzeniach.
3. Sprawdź w panelu, czy obydwa urządzenia pojawiły się w **Configuration → Devices** i raportują stan. `enable_new_devices: false` pozwala najpierw zarejestrować urządzenia i przejrzeć ich ustawienia. Zmiana opcji dotyczy nowo rejestrowanych urządzeń. Włącz dostarczanie konfiguracji pojedynczo po sprawdzeniu podglądu.
4. Zachowaj kopie konfiguracji obu routerów. Sprawdź na Cudy PPPoE, LAN, DHCP, firewall i dostęp awaryjny. Na Archerze potwierdź brak drugiego serwera DHCP, prawidłowy most i zachowanie przewodowego uplinku. Porównaj proponowane zmiany z aktualnym UCI przed włączeniem dostarczania konfiguracji.

Interfejs agentów przepuszcza dokładne metody i ścieżki OpenSOHO. Są to `POST /controller/register/`, `POST /controller/report-status/<uuid>/`, `POST /controller/update-info/<uuid>/`, `GET /controller/checksum/<uuid>/`, `GET /controller/download-config/<uuid>/` i `POST /api/v1/monitoring/device/`. OpenSOHO nadal sprawdza sekrety i klucze OpenWISP. [Punkt wejścia OpenSOHO](https://github.com/rubenbe/opensoho/blob/6349f37abcc43bc7f5d68db581fd4c1e328aaf2f/opensoho.go)

## SSO i zachowanie sesji

Supervisor ogranicza panel przez `panel_admin`. Dodatek dodatkowo sprawdza adres połączenia TCP `172.30.32.2` z dokumentacji HA, poprawny identyfikator użytkownika oraz członkostwo w `system-admin` z nagłówka `X-Remote-User-Groups`. Sprawdzony kod Supervisora usuwa przychodzące nagłówki tożsamości i wstawia własne. Właściciel HA otrzymuje efektywne członkostwo w grupie administratorów. Obsługę nagłówka potwierdzono w kodzie wydania Supervisora 2026.11.0. Wersja bez tego nagłówka powoduje odmowę. Nie nadawaj dodatkowi roli Supervisor API `admin` tylko po to, aby czytać listę użytkowników. [Dokumentacja Ingress](https://developers.home-assistant.io/docs/apps/presentation/#ingress) · [Supervisor Ingress](https://github.com/home-assistant/supervisor/blob/c1c6f0a754c0656eb1af189f11009f1cfc4b3e28/supervisor/api/ingress.py) · [Grupy](https://github.com/home-assistant/supervisor/blob/c1c6f0a754c0656eb1af189f11009f1cfc4b3e28/supervisor/const.py)

Adapter przekazuje zaufaną tożsamość do `RequestEvent.Auth` w PocketBase. Wewnętrzny rekord superusera ma losowe hasło tworzone przy pierwszym uruchomieniu. Przeglądarka otrzymuje identyfikator i nazwę kolekcji, a każde kolejne żądanie i ponowne połączenie SSE ponownie przechodzą przez kontrolę Ingress. Token pobrania pliku chronionego powstaje wyłącznie wewnątrz procesu. PocketBase nadal sprawdza swoje reguły. Wbudowane endpointy umożliwiające wydanie tokenu administracyjnego i instalator PocketBase są niedostępne. [PocketBase Go routing](https://pocketbase.io/docs/go-routing/)

Uprawnienia zależą od ważności sesji Ingress i roli przekazywanej przez Supervisor. W sprawdzonym kodzie HA wylogowanie odwołuje sesję Core, a cookie Ingress ma osobny cykl życia w Supervisorze. Aktualny Supervisor przedłuża jego ważność o 15 minut przy kolejnych żądaniach i może trzymać role w pamięci. Już otwarty strumień SSE jest ograniczony do 1 minuty. Przy testowaniu natychmiastowego odebrania dostępu usuń cookie `ingress_session` z przeglądarki i sprawdź nową sesję. Po awaryjnym odebraniu roli odśwież dane ról Supervisora przez jego restart, a następnie sprawdź odmowę na poprzednim koncie. [Kod sesji Supervisora](https://github.com/home-assistant/supervisor/blob/c1c6f0a754c0656eb1af189f11009f1cfc4b3e28/supervisor/ingress.py)

Wyłączenie panelu przez kontrolę roli nie zatrzymuje agentów. Dodatek nie żąda API hosta, mapowania Dockera ani dodatkowych uprawnień Supervisora. Na starcie przygotowuje katalog danych i przechodzi na UID/GID 10001. Logi żądań PocketBase są wyłączone, aby ścieżki Ingress i klucze w query agentów nie trafiały do logów. Diagnostyka kontrolera pozostaje dostępna w logu dodatku.

## Backup, odtwarzanie i aktualizacja

- Utwórz backup Home Assistanta obejmujący OpenSOHO i przechowuj go jak dane dostępowe. Tryb `cold` zatrzymuje proces na czas kopii. W kopii znajdują się dane i opcje dodatku. Osadzone migracje są odtwarzane z obrazu przy starcie.
- Przy odtwarzaniu wybierz kopię z OpenSOHO w Supervisorze. Sprawdź port, ustawienia, stan routerów, a następnie pobranie konfiguracji i nowe raporty. Jeżeli zmienił się adres LAN hosta, popraw URL na routerach.
- Przed aktualizacją utwórz backup i zachowaj możliwość uruchomienia poprzedniego obrazu z jego kopią danych. Supervisor zachowuje `/data` przy wymianie obrazu. Cofnięcie obrazu po migracji może wymagać odtworzenia wcześniejszego backupu.

## Diagnostyka

- **Panel zwraca 403.** Sprawdź rolę i aktywną sesję HA, otwórz panel z bocznego menu oraz sprawdź obsługę nagłówka grup przez wersję Supervisora. Usuń wcześniejsze cookie Ingress przy przełączaniu kont. Nagłówki z klienta LAN niczego tu nie odblokują.
- **Brak zasobów lub API w panelu.** W narzędziach przeglądarki sprawdź, czy żądania do `/_/`, `/api/ha/session`, `/api/collections/` i `/api/realtime` mają ten sam prefiks `/api/hassio_ingress/<token>/`. Przy HTTPS sprawdź, czy adresy zasobów używają tego samego originu i protokołu co HA.
- **Router nie dostaje konfiguracji.** Zweryfikuj port i osiągalność z sieci routera, sekret rejestracji oraz włączenie dostarczania konfiguracji dla urządzenia. Sprawdź logi `openwisp-config` i `openwisp-monitoring`, maskując klucze, sekret i dane konfiguracji.
- **Błąd uruchomienia po restore.** Sprawdź, czy wolumen danych jest zapisywalny i Supervisor przywrócił plik opcji. Użyj obrazu właściwego dla kopii, jeśli migracja zgłasza błąd.

## Budowanie i testy

```sh
docker buildx build --check opensoho
docker buildx build --target test opensoho
docker buildx build --platform linux/amd64 --load -t hass-open-soho:local opensoho
docker buildx build --platform linux/arm64 --load -t hass-open-soho:arm64 opensoho
python3 tests/smoke.py --http-only
```

Pełny smoke test korzysta z Playwright i Chromium. Zainstaluj `playwright==1.62.0` w lokalnym środowisku Pythona oraz `playwright install chromium` albo wskaż istniejące Chromium zmienną `CHROMIUM_BIN`. Uruchom `python3 tests/smoke.py`. Test wykorzystuje izolowaną sieć Docker i tymczasowy wolumen. Opcja `--replacement-image` pozwala przetestować drugą wersję przy zachowaniu tego samego wolumenu. W kontrolowanej sieci z własnym urzędem certyfikacji dodaj do komendy build `--secret id=build_ca,src=/ścieżka/do/zaufanego/bundle.pem`.

GitHub Actions uruchamia lint workflow przez przypięty `actionlint`, kontrolę składni skryptów, formatowania Go i Dockerfile. Dwa zadania na natywnych runnerach `ubuntu-24.04` oraz `ubuntu-24.04-arm` wykonują testy Go i JavaScript, budują obraz dla własnej architektury oraz uruchamiają pełny test przeglądarkowy i wymianę obrazu. Workflow ma minimalne uprawnienia, limity czasu, cache zależny od architektury i anuluje starsze przebiegi tej samej gałęzi. Wywołuje się przy push, pull request i ręcznie.

Zaktualizuj rewizje w `opensoho/scripts/sources.sh`, utrzymując zgodność wersji UI z modułem PocketBase w `go.mod` wersji OpenSOHO. Nałóż i w razie potrzeby zaktualizuj obie łatki w `opensoho/patches/`. Przejrzyj nowe ścieżki OpenWISP i obsługę Ingress, uruchom build oraz testy i przećwicz migrację na kopii danych. Podnieś wersję w `opensoho/config.yaml` i uzupełnij changelog.

W stosunku do upstreamu dodatek dodaje adapter HA, dwa listenery, integrację z trwałym wolumenem i łatkę kodu źródłowego UI. PocketBase Go zachowuje oryginalną bibliotekę. OpenSOHO jest przypięte do `6349f37abcc43bc7f5d68db581fd4c1e328aaf2f`, PocketBase do `v0.40.5` (`6f370ea741f33adf889eef02e3c1b884a47aa522`). Message Relay posłużył do porównania przepływu sesji i nie dostarcza kodu temu repozytorium. Przejrzany checkout Message Relay nie zawierał pliku licencji. Przykład PocketBase HA App posłużył do sprawdzenia układu dodatku i opcji backupu. Licencja tego repozytorium to AGPL-3.0. [OpenSOHO](https://github.com/rubenbe/opensoho) · [Message Relay](https://github.com/nazt/wrw-msg/blob/main/pb_hooks/lib/halogin.js) · [PocketBase HA App](https://github.com/fabio-garavini/hassio-addons/tree/main/pocketbase)

Instalacja przez prawdziwy Supervisor, domena HTTPS i urządzenia fizyczne wymagają scenariusza z [HA OS E2E](tests/HA-OS-E2E.md).
