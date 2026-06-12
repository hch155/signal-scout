## Jak uzyskać najlepszy sygnał

Mocny i stabilny sygnał dla anten CPE, routerów Mi-Fi i telefonów potrafi wyraźnie poprawić komfort korzystania z internetu. Poniżej kilka wskazówek, jak ustawić sprzęt i zmaksymalizować siłę sygnału.

---

## Znajdź najbliższą stację bazową

- Skorzystaj z linku do Google Maps, aby zlokalizować najbliższy sektor anteny
- Kup kartę SIM jednego z najbliższych operatorów — to zapewnia najlepszą siłę i jakość sygnału
- Ustaw swoją lokalizację względem azymutu sektora anteny najbliższej stacji bazowej

---

## Czynniki środowiskowe

- W gęstej zabudowie licz się z odbiciami sygnału od budynków — mogą one zarówno wzmacniać, jak i osłabiać jakość sygnału
- Liczba innych użytkowników w komórce, zwłaszcza w godzinach szczytu, potrafi mocno obniżyć osiągane przepływności — w gęstych obszarach czasem opłaca się zmienić operatora

---

## Unikanie zakłóceń

- Zachowaj odstęp od linii energetycznych, aby ograniczyć Block Error Rate (BLER)
- Zwracaj uwagę na fizyczne przeszkody, które mogą blokować lub odbijać sygnał

---

## Optymalne ustawienie sprzętu

- Aby wykorzystać odbicia sygnału, ustaw sprzęt tak, by korzystał z konfiguracji MIMO (Multiple Input Multiple Output)
- Wykonaj kilka testów prędkości, aby znaleźć najlepsze miejsce dla swojego sprzętu

---

## Tryby pracy urządzeń

<p><strong>NSA (Non-Standalone)</strong> — scenariusz obecny — urządzenie musi najpierw uwierzytelnić się w sieci 4G, aby dołączyć nośną częstotliwości 5G.</p>

<p><strong>SA (Standalone)</strong> — wdrożenie planowane — urządzenie łączy się z siecią 5G bezpośrednio, bez kotwicy 4G.</p>

---

## Agregacja nośnych i przepływność

Aby osiągnąć najlepszą przepływność, warto przetestować różne nośne składowe i konfiguracje agregacji (CA).

**Downlink** (stacja bazowa → urządzenie):

- Większość urządzeń obsługuje do 4 nośnych składowych w agregacji (CA) w trybie LTE
- W trybie 5G NSA urządzenia zwykle obsługują 1 nośną LTE + 2 nośne NR

**Uplink** (urządzenie → stacja bazowa):

- Większość urządzeń obsługuje 1 lub 2 nośne w uplinku

---

## Częstotliwości i szerokości pasm w Polsce

Konfiguracja sieci każdego operatora składa się z podobnych nośnych składowych:

| Pasmo | Pasmo 3GPP | Szerokość |
|-------|------------|-----------|
| LTE800 | B20 | 5 MHz |
| LTE900 | B8 | 5 MHz |
| LTE1800 | B3 | 15 MHz |
| LTE2100 | B1 | 20 MHz |
| LTE2600 | B7 | 20 MHz |
| NR2100 (DSS) | n1 | 20 MHz |
| NR3600 (C-band) | n78 | 100 MHz |

**Przykładowe osiągalne przepływności:**

- Przy 10 MHz pasma i modulacji 256QAM: ~100–150 Mb/s w optymalnych warunkach
- **Samo LTE** (4CA: LTE800 + LTE1800 + LTE2100 + LTE2600 = 60 MHz): DL ~500–600 Mb/s, UL ~80 Mb/s
- **5G NSA** (LTE2600 + NR3600 = 120 MHz): DL ~1000–1200 Mb/s (szczytowo 1500–1600 Mb/s), UL ~150 Mb/s

Większość urządzeń agreguje tyle nośnych, ile się da, aby zapewnić najlepsze doświadczenie.

---

## Odczyt informacji o komórce z urządzenia

Poniższe kody otwierają ukryte menu diagnostyczne urządzenia:

- **iOS:** `*3001#12345#*`
- **Android:** `*#*#4636#*#*`

### Tryb Field Test w iOS

Wybranie `*3001#12345#*` na urządzeniu z iOS uruchamia Field Test Mode — ukrytą funkcję dającą głębszy wgląd w łączność komórkową. Najważniejsze dostępne informacje:

- **PLMN** (Public Land Mobile Network) — identyfikuje sieć komórkową (MCC + MNC). Przykład: 26006 = Polska, operator 06
- **Band Information** — pasmo częstotliwości, z którego aktualnie korzysta urządzenie
- **Bandwidth** — szerokość pasma (MHz); szersze pasmo pozwala na wyższą przepływność
- **Cell ID** — unikalny identyfikator komórki; pozwala wyznaczyć ID komórki i ID stacji bazowej
- **Radio Access** — używana technologia dostępu (5G, LTE itd.)
- **PCI** (Physical Cell ID) — identyfikuje komórkę fizyczną, kluczowy przy handoverze i sygnalizacji warstwy fizycznej
- **TAC** (Tracking Area Code) — używany w procedurach śledzenia i przywoływania (paging) urządzeń
- **EARFCN DL** — numer kanału częstotliwości downlinku w LTE

### Kluczowe metryki sygnału

- **RSRP** (Reference Signal Received Power) — podstawowy wskaźnik siły sygnału
- **RSRQ** (Reference Signal Received Quality) — ocenia jakość sygnału z uwzględnieniem zakłóceń i szumu
- **SINR** (Signal-to-Interference-plus-Noise Ratio) — stosunek sygnału do szumu i zakłóceń; im wyższy, tym lepiej
- **ConnectionStats** — przepływności, opóźnienia, utrata pakietów i inne metryki jakości połączenia
- **RACH Attempt** — próby nawiązania połączenia z siecią przez kanał Random Access
- **Serving Cell Info** — szczegóły aktualnie obsługującej komórki, łącznie z powyższymi metrykami
