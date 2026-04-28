def get_age_group(age: int) -> str:
    if age <= 12:
        return "child"
    elif age <= 19:
        return "teenager"
    elif age <= 59:
        return "adult"
    else:
        return "senior"


def get_top_country(countries: list) -> tuple[str, float]:
    top = max(countries, key=lambda c: c["probability"])
    return top["country_id"], top["probability"]
