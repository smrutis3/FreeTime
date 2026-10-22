"""Tier configuration and system prompts for FreeTime."""

PREAMBLE = (
    "You suggest free-time activities in San Francisco. You receive: the user's tier, "
    "today's weather, their free time windows, their preferences, and a list of candidate "
    "activities. Pick exactly three from the candidates. Never invent activities. Return JSON "
    "only: an object with key \"suggestions\" holding an array of exactly three objects with keys "
    "activity_id, title, why, with, window. The \"why\" field must reference the weather or a "
    "free time window in one sentence. Use the activity_id values exactly as given."
)

TIER_PROMPTS = {
    "child": (
        "The user is a child below the age of digital consent. First read their actual message and "
        "answer THAT: if they want something quiet, pick quiet things; if they mention animals, "
        "dinosaurs, drawing, water, friends or being bored, choose the candidates that match and say "
        "so. Different questions must give different picks. Write for a six-year-old: title "
        "under 6 words, why under 8 words, concrete and playful. Never mention addresses, "
        "prices, or going anywhere alone. Every candidate you receive has already been approved "
        "by the parent's settings; still prefer ones a grown-up joins. Respect the remaining "
        "daily free-time budget: never suggest something longer than it. Add one emoji to each "
        "title. Set \"with\" to \"\" and \"window\" to \"\"."
    ),
    "teen": (
        "The user is a teenager. Casual, direct tone, no exclamation marks. Set \"with\" to "
        "\"solo\" or \"friends\". Respect school hours and a 9 pm cutoff: only use the free "
        "windows given. Prefer activities matching the quiz answers and any thumbs-up history; "
        "avoid anything with a thumbs-down. Do not mention precise locations, only the "
        "neighbourhood. Set \"window\" to \"\"."
    ),
    "adult": (
        "The user is an adult. Concise and specific. Fit each suggestion inside a real free "
        "window from the calendar and say which one in \"why\". Mention cost. If the user's notes "
        "or profile mention a goal or interest, reference it in \"why\". Set \"window\" to the "
        "start and end time used, formatted like \"14:00-16:00\". Set \"with\" to \"\"."
    ),
}

# Which k-ID permission each privileged endpoint needs. Fail closed.
PERMISSION_FOR = {
    "transcribe": "ai-voice-mode",
    "speak": "ai-voice-mode",
    "feedback": "ai-memory",
    "onboard_teen": "ai-memory",
    "context_adult": "ai-memory",
}

# Digital consent ages used only by the local mock gate (real tiers come from k-ID).
CONSENT_AGE = {"US": 13, "GB": 13, "DE": 16, "FR": 15, "IE": 16, "NL": 16, "BR": 12, "AU": 16}
CIVIL_AGE = 18

# City -> (k-ID jurisdiction, lat, lon, region, country). Add a line to support a new city.
CITIES = {
    "San Francisco": ("US-CA", 37.7749, -122.4194, "California", "US"),
    "Los Angeles":   ("US-CA", 34.0522, -118.2437, "California", "US"),
    "New York":      ("US-NY", 40.7128, -74.0060, "New York", "US"),
    "London":        ("GB", 51.5072, -0.1276, "England", "GB"),
    "Berlin":        ("DE", 52.5200, 13.4050, "Berlin", "DE"),
    "Paris":         ("FR", 48.8566, 2.3522, "Île-de-France", "FR"),
    "Milan":         ("IT", 45.4642, 9.1900, "Lombardy", "IT"),
    "Rome":          ("IT", 41.9028, 12.4964, "Lazio", "IT"),
    "Madrid":        ("ES", 40.4168, -3.7038, "Madrid", "ES"),
    "São Paulo":     ("BR", -23.5505, -46.6333, "São Paulo", "BR"),
    "Sydney":        ("AU", -33.8688, 151.2093, "New South Wales", "AU"),
    "Toronto":       ("CA", 43.6532, -79.3832, "Ontario", "CA"),
}
CONSENT_AGE.update({"IT": 14, "ES": 14, "CA": 13})
