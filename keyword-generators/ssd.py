# this script is way jankier than the rest for some reason lol but it seems to work good enough

import sys
import json
import argparse
from typing import Any

exclusions = "|".join([
    f"\\b{exclusion.replace(" ", "\\s*")}\\b"
    for exclusion in [
        "Notebook", "Desktop", "PC", "DDR\\d", "RAM", "HDD", "Hard Disk",
        "Hard Drive", "External", "USB", "Portable", "\\d{4} RPM"
    ]
])

keywords = "|".join([
    keyword.replace(".", "\\.").replace(" ", "\\s*")
    for keyword in [
        "SSD", "NVMe", "SATA", "M.2", "Drive", "Solid State", "SDD", "2.5"
    ]
])

GB_TB: str = "regexp::(?!.*(?:{exclusion}))(?=.*(?:{gb}[\\s_-]*(?:GiB|GB|G)|{tb}[\\s_-]*(?:TiB|TB|T)))(?=.*(?:{keywords})).*"  # noqa: E501
GB: str = "regexp::(?!.*(?:{exclusion}))(?=.*(?:{gb}[\\s_-]*(?:GiB|GB|G)))(?=.*(?:{keywords})).*"
TB: str = "regexp::(?!.*(?:{exclusion}))(?=.*(?:{tb}[\\s_-]*(?:TiB|TB|T)))(?=.*(?:{keywords})).*"


def generate_keyword_block(
    gb: str | None,
    tb: str | None,
    min_price: int,
    max_price: int | None,
    target_price: int,
) -> dict[str, Any]:
    mode = ""

    if gb is not None and tb is not None:
        mode = "GB_TB"
        regex = GB_TB.format(exclusion=exclusions, keywords=keywords, gb=gb, tb=tb)
    elif gb is not None and tb is None:
        mode = "GB"
        regex = GB.format(exclusion=exclusions, keywords=keywords, gb=gb)
    elif gb is None and tb is not None:
        mode = "TB"
        regex = TB.format(exclusion=exclusions, keywords=keywords, tb=tb)
    else:
        raise ValueError("Either --gb or --tb must be specified.")

    if max_price is not None:
        print("Warning: Using --max-price is discouraged as it bypasses the dynamic max price calculation.")
    else:
        max_price = target_price + (target_price // 5)

        if max_price - target_price < 10:
            max_price = target_price + 10
        elif max_price - target_price > 30:
            max_price = target_price + 30

    great_end = target_price - 1
    fire_start = min_price
    ok_end = max_price
    great_start = target_price - 10
    fire_end = great_start - 1
    good_start = great_end + 1
    good_end = good_start + ((ok_end - good_start) // 2)
    ok_start = good_end + 1

    return {
        "keyword": regex,
        "min_price": min_price,
        "max_price": max_price,
        "target_price": target_price,
        "friendly_name": f"{gb if gb else tb}{mode} SSD",
        "deal_ranges": {
            "fire_deal": {"start": fire_start, "end": fire_end},
            "great_deal": {"start": great_start, "end": great_end},
            "good_deal": {"start": good_start, "end": good_end},
            "ok_deal": {"start": ok_start, "end": ok_end}
        }
    }


def parse_comma_separated(value, param_type):
    if value is None:
        return None

    items = [item.strip() for item in value.split(',')]

    if param_type == 'bool':
        return [item.lower() in ('true', 't', 'yes', 'y', '1') for item in items]
    elif param_type == 'int':
        return [int(item) if item else None for item in items]
    elif param_type == 'str':
        return items
    elif param_type == 'str_or_none':
        return [None if item.lower() == 'none' else (item if item else None) for item in items]
    else:
        return items


def main(
    gbs: list | None,
    tbs: list | None,
    min_prices: list | None,
    _max_prices: list | None,
    target_prices: list | None,
):
    if gbs and not isinstance(gbs, list):
        gbs = [gbs]
    if tbs and not isinstance(tbs, list):
        tbs = [tbs]
    if min_prices and not isinstance(min_prices, list):
        min_prices = [min_prices]
    if _max_prices and not isinstance(_max_prices, list):
        _max_prices = [_max_prices]
    if target_prices and not isinstance(target_prices, list):
        target_prices = [target_prices]

    num_configs = len(target_prices) if target_prices else 0

    if _max_prices is None:
        _max_prices = [None] * num_configs

    def extend_list(lst, target_length, default_value):
        if lst is None:
            return [default_value] * target_length
        while len(lst) < target_length:
            lst.append(lst[-1] if lst else default_value)
        return lst[:target_length]

    gbs = extend_list(gbs, num_configs, None)
    tbs = extend_list(tbs, num_configs, None)
    min_prices = extend_list(min_prices, num_configs, min_prices[0] if min_prices else 50)
    max_prices: list[int | None] | list[None] = extend_list(_max_prices, num_configs, None)
    target_prices = extend_list(target_prices, num_configs, target_prices[0] if target_prices else 100)

    results = []
    for i in range(num_configs):
        block = generate_keyword_block(
            gbs[i], tbs[i],
            min_prices[i], max_prices[i], target_prices[i]
        )
        results.append(block)

    print(json.dumps(results[0] if len(results) == 1 else results, indent=4))


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser()

        parser.add_argument("--gb", type=str, help="GB Capacity - just a number (for example, 512 = 512GB) - you can also use a regex non-capturing group like '(?:256|512)' for multiple values")  # noqa: E501
        parser.add_argument("--tb", type=str, help="TB Capacity - just a number (for example, 1 = 1TB) - you can also use a regex non-capturing group like '(?:1|2)' for multiple values")  # noqa: E501
        parser.add_argument("--min-price", type=str, help="Minimum Price(s)")
        parser.add_argument("--max-price", type=str, help="Maximum Price(s)")
        parser.add_argument("--target-price", type=str, help="Target Price(s)")

        args = parser.parse_args(sys.argv[1:])

        gbs = parse_comma_separated(args.gb, 'str')
        tbs = parse_comma_separated(args.tb, 'str')
        min_prices = parse_comma_separated(args.min_price, 'int')
        max_prices = parse_comma_separated(args.max_price, 'int')
        target_prices = parse_comma_separated(args.target_price, 'int')

        main(
            gbs=gbs,
            tbs=tbs,
            min_prices=min_prices,
            _max_prices=max_prices,
            target_prices=target_prices
        )
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
