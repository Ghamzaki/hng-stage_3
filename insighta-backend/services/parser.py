import re
from typing import Optional

COUNTRY_MAP = {
    "algeria": "DZ", "angola": "AO", "australia": "AU", "benin": "BJ",
    "botswana": "BW", "brazil": "BR", "burkina faso": "BF", "burundi": "BI",
    "cameroon": "CM", "canada": "CA", "cape verde": "CV",
    "central african republic": "CF", "chad": "TD", "china": "CN",
    "comoros": "KM", "ivory coast": "CI", "cote d'ivoire": "CI",
    "côte d'ivoire": "CI", "dr congo": "CD",
    "democratic republic of congo": "CD", "drc": "CD", "djibouti": "DJ",
    "egypt": "EG", "equatorial guinea": "GQ", "eritrea": "ER",
    "eswatini": "SZ", "swaziland": "SZ", "ethiopia": "ET", "france": "FR",
    "gabon": "GA", "gambia": "GM", "germany": "DE", "ghana": "GH",
    "guinea": "GN", "guinea-bissau": "GW", "india": "IN", "japan": "JP",
    "kenya": "KE", "lesotho": "LS", "liberia": "LR", "libya": "LY",
    "madagascar": "MG", "malawi": "MW", "mali": "ML", "mauritania": "MR",
    "mauritius": "MU", "morocco": "MA", "mozambique": "MZ", "namibia": "NA",
    "niger": "NE", "nigeria": "NG", "republic of the congo": "CG",
    "congo": "CG", "rwanda": "RW", "senegal": "SN", "seychelles": "SC",
    "sierra leone": "SL", "somalia": "SO", "south africa": "ZA",
    "south sudan": "SS", "sudan": "SD", "sao tome and principe": "ST",
    "são tomé e príncipe": "ST", "tanzania": "TZ", "togo": "TG",
    "tunisia": "TN", "uganda": "UG", "united kingdom": "GB", "uk": "GB",
    "britain": "GB", "united states": "US", "usa": "US", "america": "US",
    "western sahara": "EH", "zambia": "ZM", "zimbabwe": "ZW",
}

VALID_CODES = set(COUNTRY_MAP.values())


def parse_query(q: str) -> Optional[dict]:
    text = q.lower().strip()
    if not text:
        return None

    filters = {}

    if re.search(r'\b(males?|men|man)\b', text):
        filters["gender"] = "male"
    elif re.search(r'\b(females?|women|woman|lady|ladies)\b', text):
        filters["gender"] = "female"

    if re.search(r'\byoung\b', text):
        filters["min_age"] = 16
        filters["max_age"] = 24

    if re.search(r'\b(children|child|kids?)\b', text):
        filters["age_group"] = "child"
    elif re.search(r'\b(teenagers?|teens?|adolescents?)\b', text):
        filters["age_group"] = "teenager"
    elif re.search(r'\badults?\b', text):
        filters["age_group"] = "adult"
    elif re.search(r'\b(seniors?|elderly|old people|old)\b', text):
        filters["age_group"] = "senior"

    between = re.search(r'\bbetween\s+(\d+)\s+and\s+(\d+)\b', text)
    if between:
        filters["min_age"] = int(between.group(1))
        filters["max_age"] = int(between.group(2))
    else:
        above = re.search(r'\b(?:above|over|older\s+than)\s+(\d+)\b', text)
        if above:
            filters["min_age"] = int(above.group(1))
        below = re.search(r'\b(?:below|under|younger\s+than)\s+(\d+)\b', text)
        if below:
            filters["max_age"] = int(below.group(1))

    country_match = re.search(
        r'\b(?:from|in)\s+([a-z][a-z\s\'\-\.]+?)(?:\s+(?:who|that|with|and|above|below|over|under)\b|$)',
        text,
    )
    if country_match:
        raw = country_match.group(1).strip()
        code = COUNTRY_MAP.get(raw)
        if not code:
            for name, c in sorted(COUNTRY_MAP.items(), key=lambda x: -len(x[0])):
                if name in raw:
                    code = c
                    break
        if code:
            filters["country_id"] = code
    else:
        code_match = re.search(r'\b([A-Z]{2})\b', q)
        if code_match and code_match.group(1) in VALID_CODES:
            filters["country_id"] = code_match.group(1)

    if not filters:
        return None
    return filters
