MONITOR CUKRU - INSTRUKCJA 
====================================================

CO TO JEST
----------
Program pokazuje na jednej stronie w przeglądarce aktualne wyniki cukru
wszystkich dzieci na obozie. Kafelek dziecka świeci na zielono (wynik OK),
pomarańczowo/czerwono (za wysoki lub za niski, wymaga uwagi) albo szaro
("brak danych" / "dane nieaktualne").

Program potrafi pobierać dane z CZTERECH różnych źródeł jednocześnie -
różne dzieci mogą używać różnych systemów, to bez znaczenia, wszystkie
kafelki pojawią się razem na jednej stronie:

  1. Dexcom (aplikacja/konto Dexcom, np. Dexcom G6/G7)
  2. LibreLinkUp (FreeStyle Libre - konto "obserwującego")
  3. Nightscout ("CGM in the Cloud" - własny serwer Nightscout)
  4. Medtronic CareLink (sensory Guaridain, Simplera Medtronic)

-------------

ŁATWE URUCHOMINIE PROGRAMU (opcja łatwiejsza dla mniej zaawansowanych uzytkowników)

1. Ściagnij poniższy plik: https://github.com/jrkf/Multi-Blood-Sugar-Monitor/releases/download/v.1.0.1/uruchm.Monitor.bat

2. Kliknij na tym pliku prawym klawiszem myszki i użyj opcji 'uruchom jako administrator'

3. Postepuj zgodnie z instrukcjami jakie się wyświetlają na ekranie, do czasu uruchomienia się przeglądarki z naszym programem
------------------------------------------------------------------------------

JEDNORAZOWE PRZYGOTOWANIE PROGRAMU (Trudniejsza instrukcja krok po kroku dla zaawansowanych, jeśli powyższa instrukcja nie zadziała)
------------------------------------------------------------------------------
1. Zainstaluj Pythona (jeśli nie ma): https://www.python.org/downloads/
   Podczas instalacji zaznacz "Add Python to PATH".

2. Otwórz terminal / wiersz poleceń w folderze z programem i wpisz:

   pip install -r requirements.txt

3. Uruchom program:

   python app.py

4. W terminalu pojawi się informacja, że program działa oraz adres:
   http://localhost:5000

5. Otwórz ten adres w przeglądarce (Chrome, Edge, Firefox).

6. Kliknij ikonę zębatki (prawy górny róg) i zaloguj się domyślnym hasłem:
   zmien_haslo
   ZMIEŃ JE JAK NAJSZYBCIEJ w sekcji "6. Zmień hasło konfiguracji"!

7. Aby inne osoby (np. lekarz na tablecie) widziały ten sam podgląd,
   muszą być w tej samej sieci Wi-Fi co komputer i wejść na adres
   pokazany w terminalu (coś w stylu http://192.168.x.x:5000).


CO POPROSIĆ RODZICÓW O PRZESŁANIE - WEDŁUG ŹRÓDŁA DANYCH
===========================================================

Zanim zaczniesz zbierać dane od rodziców, ustal z każdym z nich, z jakiego
systemu monitorowania cukru korzysta ich dziecko, i poproś dokładnie o to,
co opisano poniżej. WAŻNE: dla Dexcom i LibreLinkUp potrzebne jest HASŁO
do konta - najlepiej, żeby rodzic na czas obozu utworzył dodatkowe konto
"obserwującego" / "opiekuna", a nie podawał hasła do swojego głównego
konta rodzinnego, jeśli to możliwe.

1) DEXCOM (Dexcom G6 / G7 - aplikacja Dexcom na telefonie dziecka)
   -----------------------------------------------------------------
   Poproś rodzica o:
     - login (adres e-mail) konta Dexcom dziecka,
     - hasło do tego konta,
     - region konta: "ous" dla Polski/Europy, "us" dla USA/Kanady.

   Jak dodać w programie:
     Konfiguracja -> "1. Dodaj dziecko" -> źródło danych: Dexcom.

   Import wielu dzieci naraz (plik .txt), jedna linia = jedno dziecko:
     login,haslo,Imię i Nazwisko
     login,haslo,Imię i Nazwisko,region   (region opcjonalny, domyślnie "ous")

   Uwaga: żeby program mógł czytać dane, telefon dziecka z aplikacją
   Dexcom (nadajnik danych z sensora do chmury Dexcom) musi mieć włączone
   udostępnianie / być zalogowany i online - to zwykłe konto Dexcom, bez
   żadnej dodatkowej konfiguracji po stronie rodzica poza podaniem
   loginu i hasła.


2) LIBRELINKUP (FreeStyle Libre - Abbott)
   -----------------------------------------------------------------
   To NIE jest to samo konto, którego dziecko używa w aplikacji
   "FreeStyle LibreLink" do skanowania sensora! Do podglądu zdalnego
   potrzebne jest osobne konto "obserwującego" w aplikacji LibreLinkUp.

   Kroki, które musi wykonać rodzic PRZED wyjazdem:
     a) Rodzic zakłada konto w aplikacji LibreLinkUp (na swoim telefonie,
        osobna aplikacja od LibreLink dziecka) - podając e-mail i hasło.
     b) Dziecko w swojej aplikacji LibreLink musi zaakceptować rodzica
        jako "obserwującego" (opiekuna) - wysyła się zaproszenie z apki
        dziecka na e-mail rodzica, rodzic je akceptuje w LibreLinkUp.
     c) Dopiero po tym kroku konto LibreLinkUp rodzica "widzi" dane
        dziecka.

   Poproś rodzica o przesłanie:
     - e-mail konta LibreLinkUp (NIE dziecka, tylko konta obserwującego),
     - hasło do tego konta LibreLinkUp,
     - region konta (zwykle "eu" dla Polski/Europy; inne dostępne opcje:
       de, fr, us, ca, au, ap, jp, ae - zależy w jakim kraju zakładano
       konto Abbott),
     - (opcjonalnie) jeśli na jednym koncie LibreLinkUp rodzic obserwuje
       WIĘCEJ niż jedno dziecko - poproś też o ID pacjenta / imię dziecka
       widoczne w apce, żeby wybrać właściwe dziecko. Jeśli konto
       obserwuje tylko jedno dziecko, ten krok nie jest potrzebny.

   Jak dodać w programie:
     Konfiguracja -> "1. Dodaj dziecko" -> źródło danych: LibreLinkUp.

   Import wielu dzieci naraz (plik .txt), jedna linia = jedno dziecko:
     librelinkup,email,hasło,region,Imię i Nazwisko
     librelinkup,email,hasło,region,Imię i Nazwisko,id_dziecka   (opcjonalne)


3) NIGHTSCOUT ("CGM in the Cloud" - własny serwer)
   -----------------------------------------------------------------
   Dotyczy rodzin, które już wcześniej korzystają z Nightscout (własna
   strona z danymi z sensora, niezależnie od marki - Dexcom, Libre itd.
   skonfigurowane przez rodzica z pomocą technicznej osoby / społeczności
   diabetyków).

   Poproś rodzica o przesłanie:
     - adres URL serwera Nightscout dziecka (np.
       https://imie-dziecka.herokuapp.com lub adres na fly.dev itp.),
     - token dostępu (API_SECRET / token), JEŚLI serwer jest zabezpieczony
       hasłem/tokenem - jeśli strona jest jawna/publiczna, można zostawić
       puste (ale wtedy dane są też jawne dla każdego, kto zna adres -
       zwróć rodzicowi na to uwagę).

   Jak dodać w programie:
     Konfiguracja -> "1. Dodaj dziecko" -> źródło danych: Nightscout.

   Import wielu dzieci naraz (plik .txt), jedna linia = jedno dziecko:
     nightscout,adres_url,token(może być puste),Imię i Nazwisko

   Uwaga: jeśli Nightscout dziecka nie miał świeżego wpisu od ponad
   15 minut, program oznaczy kafelek jako "dane nieaktualne" (szary),
   zamiast pokazywać mylący kolor na podstawie starego odczytu.


4) MEDTRONIC CARELINK (pompy/sensory Medtronic, np. MiniMed 780G)
   -----------------------------------------------------------------
   To źródło jest najbardziej techniczne - wymaga wcześniejszego
   wygenerowania pliku z tokenem dostępu (logindata.json) przy pomocy
   osobnego, jednorazowego narzędzia logującego do CareLink Connect
   (nie jest to zwykły login/hasło wpisywane w tym programie).

   Co przygotować PRZED wyjazdem (najlepiej z pomocą osoby ogarniętej
   technicznie):
     a) Rodzic zakłada / posiada konto CarePartner w aplikacji
        "CareLink Connect" (Medtronic) i obserwuje tam dziecko.
     b) Za pomocą osobnego skryptu logującego (dołączanego do biblioteki
        carelink_client2, np. carelink_carepartner_api_login.py) trzeba
        JEDNORAZOWO zalogować się danymi rodzica i wygenerować plik
        tokenu (zwykle nazwany logindata.json) zawierający access_token,
        refresh_token, mag-identifier itp. Program monitorujący
        automatycznie odświeża ten token, więc wystarczy zrobić to raz.
     c) Plik ten trzeba umieścić w folderze programu (lub w innym
        znanym miejscu na komputerze) i podać do niego ŚCIEŻKĘ.

   Poproś rodzica o:
     - dane logowania do konta CareLink Connect (login/hasło) - TYLKO
       po to, żeby osoba techniczna mogła jednorazowo wygenerować plik
       tokenu opisany wyżej. Same dane logowania NIE są wpisywane
       bezpośrednio do tego programu.
     - ewentualnie rodzic powinien przejść przez poniższą instrukcje:
       https://github.com/jrkf/Carelink_get_jwt_token

   Co wpisać w programie (po wygenerowaniu pliku tokenu):
     Konfiguracja -> "1. Dodaj dziecko" -> źródło danych: CareLink
     -> podaj imię dziecka oraz ścieżkę do pliku tokenu (np.
     C:\monitor\tokens\jan_kowalski.json).

   Import wielu dzieci naraz (plik .txt), jedna linia = jedno dziecko:
     carelink,ścieżka_do_pliku_tokenu,Imię i Nazwisko

   Uwaga: to źródło wymaga najwięcej przygotowania - zaplanuj czas na
   wygenerowanie plików tokenów z wyprzedzeniem, nie w dniu wyjazdu.
   Szczegóły generowania tokenu opisane są tu: https://github.com/jrkf/Carelink_get_jwt_token


CO ROBIĆ, JEŚLI KAFELEK POKAZUJE "--" LUB BŁĄD
------------------------------------------------
- "Brak aktualnych danych" - sensor dziecka mógł stracić połączenie
  z telefonem/nadajnikiem, albo dziecko jest poza zasięgiem Bluetooth
  od dłuższego czasu. To NIE znaczy, że coś jest nie tak z cukrem -
  oznacza tylko brak świeżego pomiaru. Sprawdź dziecko osobiście.
- "Dane nieaktualne" (Nightscout, kafelek szary) - ostatni odczyt jest
  starszy niż 15 minut - podobnie jak wyżej, sprawdź dziecko osobiście.
- "Błąd połączenia" (Dexcom / LibreLinkUp / Nightscout / CareLink) -
  zwykle chwilowy problem z internetem albo błędny login/hasło/token.
  Program spróbuje ponownie automatycznie za chwilę, nic nie trzeba
  robić - jeśli błąd nie znika, sprawdź poprawność danych w konfiguracji.
- "Oczekiwanie na sensor / Kalibracja" (CareLink) - pompa/sensor
  Medtronic chwilowo nie ma jeszcze odczytu (np. świeżo założony sensor).


WAŻNE - BEZPIECZEŃSTWO
-----------------------
- Ten program NIE zastępuje osobistej kontroli dziecka. To dodatkowe
  narzędzie ułatwiające szybki podgląd wielu dzieci naraz.
- Traktuj sam wynik z dystansem czasowym: dane z każdego z systemów
  (Dexcom, LibreLinkUp, Nightscout, CareLink) mają zwykle do kilku
  minut opóźnienia.
- W pliku konfiguracyjnym (config.json) zapisywane są loginy i hasła do
  kont dzieci/rodziców w formie zwykłego tekstu - komputer z uruchomionym
  programem powinien być pod opieką pielęgniarki/lekarza, żeby nikt
  niepowołany nie miał do niego dostępu ani nie zmieniał ustawień.
- Po zakończeniu obozu warto usunąć dane dzieci z programu (sekcja
  "3. Lista dzieci" -> "Usuń") oraz poprosić rodziców, żeby - jeśli
  zakładali dodatkowe konto "obserwującego" tylko na czas obozu - mogli
  je bezpiecznie usunąć/zmienić hasło.


USTAWIENIA WYGLĄDU
-------------------
W konfiguracji, w sekcji "4. Wygląd i odświeżanie" możesz zmienić:
- liczbę kolumn siatki (ile kafelków w rzędzie),
- szerokość/wysokość kafelka,
- co ile sekund program pyta źródła danych o nowe wyniki (zalecane:
  60-120 sek, żeby nie przeciążać kont/serwerów).


ALARMY DŹWIĘKOWE (NISKI / WYSOKI CUKIER)
------------------------------------------
W konfiguracji, w sekcji "5. Alarmy dźwiękowe" możesz ustawić:
- próg niskiego cukru i próg wysokiego cukru (poniżej/powyżej których
  kafelek robi się czerwony i włącza się dźwięk),
- co ile sekund powtarzać dźwięk, dopóki alarm trwa,
- własne pliki dźwiękowe osobno dla niskiego i wysokiego cukru
  (.wav, .mp3 lub .ogg) - można je wgrać i w każdej chwili odsłuchać
  lub przywrócić domyślne.

Na stronie głównej, obok zegarka, jest przycisk 🔊/🔇 do wyciszania
alarmów na danym urządzeniu/przeglądarce - przydatne np. w nocy, o ile
alarm jest i tak widoczny na innym ekranie. Ustawienie wyciszenia
zapamiętuje się tylko w tej przeglądarce.

UWAGA: przeglądarki czasem blokują automatyczne odtwarzanie dźwięku,
dopóki ktoś raz nie kliknie czegokolwiek na stronie (to zabezpieczenie
przeglądarki, nie błąd programu) - wystarczy raz kliknąć gdziekolwiek
na stronie podglądu zaraz po jej otwarciu.


ZAMYKANIE PROGRAMU
-------------------
Wróć do okna terminala, w którym program działa, i naciśnij Ctrl+C.
