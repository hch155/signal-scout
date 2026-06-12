"""Dict-based UI translations. English source strings are the keys;
missing keys fall back to the English input unchanged."""

SUPPORTED_LANGS = ('en', 'pl')
DEFAULT_LANG = 'en'

TRANSLATIONS = {
    # base.html — nav / header / footer
    'Data': 'Dane',
    'Statistics': 'Statystyki',
    'Tips': 'Porady',
    'Use cases': 'Zastosowania',
    'Pricing': 'Cennik',
    'Sign in': 'Zaloguj się',
    'Account': 'Konto',
    'Logout': 'Wyloguj się',
    'Toggle dark theme': 'Przełącz ciemny motyw',
    'Switch language': 'Zmień język',
    'Close': 'Zamknij',
    'Privacy': 'Prywatność',
    'Contact': 'Kontakt',

    # base.html — auth modal
    'Welcome to Signal-Scout': 'Witamy w Signal-Scout',
    'Sign in to save spots, get coverage alerts, and use the API.':
        'Zaloguj się, aby zapisywać miejsca, otrzymywać alerty o zasięgu i korzystać z API.',
    'Continue with Google': 'Kontynuuj przez Google',
    'Continue with GitHub': 'Kontynuuj przez GitHub',
    'Continue with Facebook': 'Kontynuuj przez Facebooka',
    'or with email': 'lub przez e-mail',
    'Create account': 'Utwórz konto',
    'Email': 'E-mail',
    'Password': 'Hasło',
    'Your password': 'Twoje hasło',
    'Show': 'Pokaż',
    'Forgot password?': 'Nie pamiętasz hasła?',
    'Choose a strong password': 'Wybierz silne hasło',
    'Confirm password': 'Potwierdź hasło',
    'Repeat password': 'Powtórz hasło',
    '8+ characters': 'Co najmniej 8 znaków',
    'A number': 'Cyfra',
    'An uppercase letter': 'Wielka litera',
    'A lowercase letter': 'Mała litera',
    'A special character': 'Znak specjalny',
    'Passwords match': 'Hasła są zgodne',
    'By continuing you agree to the': 'Kontynuując, akceptujesz',
    'Privacy Policy': 'Politykę prywatności',

    # map.html
    'Sorry — this map only covers Poland':
        'Przepraszamy — ta mapa obejmuje tylko Polskę',
    'Consider visiting — the cellular coverage is actually pretty great:':
        'Rozważ odwiedziny — zasięg sieci komórkowej jest tu naprawdę dobry:',
    'base stations': 'stacji bazowych',
    'operators': 'operatorów',
    'to GSM': 'do GSM',
    'Click anywhere inside the country outline to try it.':
        'Kliknij w dowolnym miejscu w granicach kraju, aby wypróbować.',

    # page titles (markdown body content stays English)
    'Network Data — Frequency Bands & Technologies | Signal-Scout':
        'Dane sieci — pasma częstotliwości i technologie | Signal-Scout',
    'Network Data': 'Dane sieci',
    'Information about frequency bands and network technologies':
        'Informacje o pasmach częstotliwości i technologiach sieciowych',
    'Tips: Boost Your Cellular Signal — RSRP Optimization | Signal-Scout':
        'Porady: wzmocnij sygnał komórkowy — optymalizacja RSRP | Signal-Scout',
    'Signal Optimization Guide': 'Przewodnik po optymalizacji sygnału',
    'Practical advice for maximizing your cellular signal strength and quality':
        'Praktyczne porady, jak zmaksymalizować siłę i jakość sygnału komórkowego',
    'Polish Mobile Network Statistics — Sites per Operator | Signal-Scout':
        'Statystyki polskich sieci komórkowych — lokalizacje wg operatora | Signal-Scout',
    'Network Statistics': 'Statystyki sieci',
    'Frequency band deployment and physical site counts across Polish mobile operators':
        'Wdrożenia pasm częstotliwości i liczba fizycznych lokalizacji polskich operatorów komórkowych',

    # account.html — headings, nav, buttons
    'Your account': 'Twoje konto',
    'Profile, security, and API access.': 'Profil, bezpieczeństwo i dostęp do API.',
    'Saved spots': 'Zapisane miejsca',
    'API keys': 'Klucze API',
    'Alerts': 'Alerty',
    'On': 'Wł.',
    'Off': 'Wył.',
    'Locations': 'Lokalizacje',
    'Named keys': 'Nazwane klucze',
    'Activity': 'Aktywność',
    'Profile': 'Profil',
    'Notifications': 'Powiadomienia',
    'Danger': 'Ryzyko',
    'Saved locations': 'Zapisane lokalizacje',
    'API access': 'Dostęp do API',
    'Named API keys': 'Nazwane klucze API',
    'Recent activity': 'Ostatnia aktywność',
    'Two-factor': 'Weryfikacja dwuetapowa',
    'Danger zone': 'Strefa ryzyka',
    'Two-factor authentication (TOTP)': 'Weryfikacja dwuetapowa (TOTP)',
    'Email notifications': 'Powiadomienia e-mail',
    'Change password': 'Zmiana hasła',
    'Regenerate API key': 'Wygeneruj nowy klucz API',
    '+ Add': '+ Dodaj',
    'Save location': 'Zapisz lokalizację',
    'Cancel': 'Anuluj',
    'Create API key': 'Utwórz klucz API',
    'Regenerate': 'Wygeneruj ponownie',
    'Disable 2FA': 'Wyłącz 2FA',
    'Confirm disable': 'Potwierdź wyłączenie',
    'Generate new secret': 'Wygeneruj nowy sekret',
    'Set up 2FA': 'Skonfiguruj 2FA',
    'Verify and enable': 'Zweryfikuj i włącz',
    'Save profile': 'Zapisz profil',
    'Update password': 'Zaktualizuj hasło',
    'Delete my account': 'Usuń moje konto',
    'Use my location': 'Użyj mojej lokalizacji',
    'Copy': 'Kopiuj',
    'Send me email from Signal-Scout': 'Wysyłaj mi e-maile od Signal-Scout',

    # JS — map filters / legend / sidebar
    'Toggle Filters': 'Pokaż/ukryj filtry',
    'Service Provider:': 'Operator:',
    'Frequency:': 'Częstotliwość:',
    'Apply Filters': 'Zastosuj filtry',
    'Clear': 'Wyczyść',
    'Show Nearest BTS': 'Pokaż najbliższe BTS',
    'Show BTS Within Distance': 'Pokaż BTS w zasięgu',
    'Search': 'Szukaj',
    'Enter Base Station ID': 'Podaj ID stacji bazowej',
    'Log in to use this feature.': 'Zaloguj się, aby użyć tej funkcji.',
    'BTS count:': 'Liczba BTS:',
    'Range': 'Zasięg',
    'Signal Strength': 'Siła sygnału',
    'High Band Frequency': 'Pasmo wysokie',
    'Mid Band Frequency': 'Pasmo średnie',
    'Low Band Frequency': 'Pasmo niskie',
    'Excellent': 'Doskonały',
    'Good': 'Dobry',
    'Fair': 'Średni',
    'Poor': 'Słaby',
    'Stations': 'Stacje',
    'Avg Dist': 'Śr. odl.',
    'Nearest': 'Najbliższa',
    'Best Signal': 'Najlepszy sygnał',
    'Distance:': 'Odległość:',
    'Base Station ID:': 'ID stacji bazowej:',
    'Frequency Bands:': 'Pasma częstotliwości:',
    'City:': 'Miasto:',
    'Location:': 'Lokalizacja:',
    'Coordinates:': 'Współrzędne:',
    'View on Google Maps': 'Zobacz w Google Maps',
    'Bands:': 'Pasma:',
    'Copy coordinates': 'Skopiuj współrzędne',
    'No stations found': 'Nie znaleziono stacji',
    'Try adjusting your filters or clicking a different location on the map.':
        'Zmień filtry lub kliknij inne miejsce na mapie.',
    "Save this spot — we'll email you after our monthly UKE data refresh if coverage here changes.":
        'Zapisz to miejsce — po comiesięcznej aktualizacji danych UKE wyślemy Ci e-mail, jeśli zasięg się tu zmieni.',
    'Save': 'Zapisz',
    'Saving…': 'Zapisywanie…',
    'Sending…': 'Wysyłanie…',
    'Verification email sent.': 'Email weryfikacyjny wysłany.',
    'Could not send — try again.': 'Nie udało się wysłać — spróbuj ponownie.',
    'Resend verification email': 'Wyślij ponownie email weryfikacyjny',
    'Your email address is not verified yet — coverage alerts stay paused until you click the link we sent you.':
        'Twój adres email nie został jeszcze zweryfikowany — alerty zasięgu pozostają wstrzymane, dopóki nie klikniesz w link, który wysłaliśmy.',
    'Check per-band coverage gaps at this spot':
        'Sprawdź luki zasięgu poszczególnych pasm w tym miejscu',
    'Analyse': 'Analizuj',
    'Coverage at this spot': 'Zasięg w tym miejscu',
    'Checking coverage at this spot…': 'Sprawdzanie zasięgu w tym miejscu…',
    'Click a band to show its closest BTS on the map.':
        'Kliknij pasmo, aby pokazać jego najbliższy BTS na mapie.',
    'Your Location': 'Twoja lokalizacja',
    'Navigate to station': 'Nawiguj do stacji',
    'Navigate to Station': 'Nawiguj do stacji',

    # JS — compass
    'Rotate until arrow points up': 'Obracaj, aż strzałka wskaże górę',
    'You face:': 'Twój kierunek:',
    'Station:': 'Stacja:',
    'Station': 'Stacja',

    # JS — auth / account
    'Hold to show': 'Przytrzymaj, aby pokazać',
    'Holding': 'Widoczne',
    'Logged in': 'Zalogowano',
    'User registered': 'Zarejestrowano użytkownika',
    'Copied!': 'Skopiowano!',
    'Profile saved.': 'Zapisano profil.',
    'Password updated.': 'Zaktualizowano hasło.',
    'Location saved. Reloading…': 'Zapisano lokalizację. Odświeżanie…',
    'Locating…': 'Ustalanie lokalizacji…',
}

JS_STRING_KEYS = (
    'Toggle Filters',
    'Service Provider:',
    'Frequency:',
    'Apply Filters',
    'Clear',
    'Show Nearest BTS',
    'Show BTS Within Distance',
    'Search',
    'Enter Base Station ID',
    'Log in to use this feature.',
    'BTS count:',
    'Range',
    'Signal Strength',
    'High Band Frequency',
    'Mid Band Frequency',
    'Low Band Frequency',
    'Excellent',
    'Good',
    'Fair',
    'Poor',
    'Stations',
    'Avg Dist',
    'Nearest',
    'Best Signal',
    'Distance:',
    'Base Station ID:',
    'Frequency Bands:',
    'City:',
    'Location:',
    'Coordinates:',
    'View on Google Maps',
    'Bands:',
    'Copy coordinates',
    'No stations found',
    'Try adjusting your filters or clicking a different location on the map.',
    "Save this spot — we'll email you after our monthly UKE data refresh if coverage here changes.",
    'Save',
    'Saving…',
    'Sending…',
    'Verification email sent.',
    'Could not send — try again.',
    'Check per-band coverage gaps at this spot',
    'Analyse',
    'Coverage at this spot',
    'Checking coverage at this spot…',
    'Click a band to show its closest BTS on the map.',
    'Your Location',
    'Navigate to station',
    'Navigate to Station',
    'Rotate until arrow points up',
    'You face:',
    'Station:',
    'Station',
    'Hold to show',
    'Holding',
    'Logged in',
    'User registered',
    'Copied!',
    'Profile saved.',
    'Password updated.',
    'Location saved. Reloading…',
    'Locating…',
)


def translate(text, lang):
    if lang == 'pl':
        return TRANSLATIONS.get(text, text)
    return text


def js_translations(lang):
    if lang != 'pl':
        return {}
    return {key: TRANSLATIONS[key] for key in JS_STRING_KEYS if key in TRANSLATIONS}
