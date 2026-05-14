import pathlib
import pickle
import re
import time

import psutierlist_api_wrapper as paw
import rapidfuzz

year_regex = re.compile(r"(19|20)\d\d", flags=re.IGNORECASE)
color_regex = re.compile(
    r"(red|orange|yellow|green|blue|purple|pink|black|white|gr(a|e)y|brown)",
    flags=re.IGNORECASE,
)

wattage_regex = re.compile(r"(?!19|20)(\d{3,4})\s*w", flags=re.IGNORECASE)


def cleanup(value: str) -> str | None:
    value = str(value).strip().lower()

    value = re.sub(pattern=year_regex, repl="", string=value)
    value = re.sub(pattern=color_regex, repl="", string=value)
    value = value.replace("label", "")
    value = re.sub(pattern=r"[^\w\s-]", repl="", string=value)
    value = value.strip()

    return value or None


tierlist_dir = pathlib.Path(__file__).parent.parent / "tierlist"
tierlist_dir.mkdir(exist_ok=True)
tierlist_pickle = tierlist_dir / "tierlist.pkl"


def _save_to_pickle(tierlist: list[paw.Item]) -> None:
    with tierlist_pickle.open("wb") as f:
        pickle.dump(tierlist, f)


def _load_from_pickle() -> list[paw.Item]:
    with tierlist_pickle.open("rb") as f:
        return pickle.load(f)  # noqa: S301


def _download_and_save_to_pickle() -> list[paw.Item] | None:
    tierlist = paw.get_pages()

    if tierlist:
        _save_to_pickle(tierlist.items)
        return tierlist.items

    return None


def get_tierlist() -> list[paw.Item] | None:
    if not tierlist_pickle.exists():
        tierlist_pickle.touch(exist_ok=True)
        return _download_and_save_to_pickle()
    elif tierlist_pickle.exists() and tierlist_pickle.stat().st_size == 0:
        # file exists/was touched but is empty
        return _download_and_save_to_pickle()

    threshold_secs = 7 * 24 * 60 * 60

    if time.time() - tierlist_pickle.stat().st_mtime > threshold_secs:
        return _download_and_save_to_pickle()
    else:
        return _load_from_pickle()


TIERLIST = get_tierlist()


def find_psu_in_tierlist(listing_name: str) -> list[paw.Item] | None:  # noqa: C901
    listing_name = listing_name.strip().lower()
    possible_matches: list[paw.Item] = []

    tierlist = TIERLIST

    if not tierlist:
        return None

    listing_tokens = listing_name.split()

    threshold_map: dict[int, int] = {0: 1, 1: 3, 2: 3, 3: 3}

    for item in tierlist:
        proper_tokens = [
            x
            for x in [
                cleanup(itm)
                for itm in [
                    item.brand,
                    item.series.series,
                    item.series.sub_series_1,
                    item.series.sub_series_2,
                ]
            ]
            if x
        ]

        if all(token in listing_name for token in proper_tokens):
            possible_matches.append(item)
            continue

        # Try 2: fuzzy match
        fuzzy_matched_all = True

        for index, proper_token in enumerate(proper_tokens):
            proper_token_matched = False
            threshold = threshold_map.get(index, 3)
            token_length_threshold = 3

            if len(proper_token) <= token_length_threshold:
                # this is so short that fuzzy matching is useless, so we'll use substring matching
                if proper_token in listing_tokens:
                    proper_token_matched = True
            else:
                for listing_token in listing_tokens:
                    distance = rapidfuzz.distance.DamerauLevenshtein.distance(
                        proper_token,
                        listing_token,
                    )

                    if distance <= threshold and len(listing_token) >= len(proper_token):
                        proper_token_matched = True
                        break

            if not proper_token_matched:
                fuzzy_matched_all = False
                break

        if fuzzy_matched_all:
            possible_matches.append(item)

    # Filter list
    wattage_match = re.search(wattage_regex, listing_name)
    if wattage_match:
        listing_wattage = int(wattage_match.group(1))
        possible_matches = [
            item
            for item in possible_matches
            if item.wattage_data.min_max.min is None
            or item.wattage_data.min_max.max is None
            or item.wattage_data.min_max.min <= listing_wattage <= item.wattage_data.min_max.max
        ]

    return possible_matches or None
