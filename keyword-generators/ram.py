import sys
import json
import argparse
from typing import Any


WITH_MHZ = "regexp::(?=.*(?:{capacity})[\\s_-]*(?:gigabytes|gigabyte|gib|gb|g\\b))(?=.*{ddr})(?=.*(?:{mhz})).*"  # noqa: E501


def generate_keyword_block(
    capacity: str,
    ddr_type: str,
    speed: str,
    min_price: int,
    max_price: int | None,
    target_price: int,
) -> dict[str, Any]:
    regex = WITH_MHZ.format(capacity=capacity, ddr=ddr_type, mhz=speed)

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
        "friendly_name": f"{capacity}GB {ddr_type}" + (f"-{speed}" if speed else ""),
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
    capacities: list | None,
    ddr_types: list | None,
    speeds: list | None,
    min_prices: list | None,
    _max_prices: list | None,
    target_prices: list | None,
):
    if capacities and not isinstance(capacities, list):
        capacities = [capacities]
    if ddr_types and not isinstance(ddr_types, list):
        ddr_types = [ddr_types]
    if speeds and not isinstance(speeds, list):
        speeds = [speeds]
    if min_prices and not isinstance(min_prices, list):
        min_prices = [min_prices]
    if _max_prices and not isinstance(_max_prices, list):
        _max_prices = [_max_prices]
    if target_prices and not isinstance(target_prices, list):
        target_prices = [target_prices]

    if capacities is None:
        capacity = input("Capacity (e.g., 8, 16): ").strip()
        capacities = [capacity]

    if ddr_types is None:
        ddr_type = input("DDR Type (e.g., DDR4, DDR5): ").strip()
        ddr_types = [ddr_type]

    num_configs = len(ddr_types) if ddr_types else len(capacities)

    if speeds is None:
        if num_configs == 1:
            speed_raw = input("Speed (e.g., 3200, 3600) (leave blank for none): ").strip()
            speeds = [speed_raw if speed_raw else None]
        else:
            speeds = [None] * num_configs

    if min_prices is None:
        if num_configs == 1:
            min_price = int(input("Min Price: ").strip())
            min_prices = [min_price]
        else:
            raise ValueError("min_prices is required for batch processing")

    if target_prices is None:
        if num_configs == 1:
            target_price = int(input("Target Price: ").strip())
            target_prices = [target_price]
        else:
            raise ValueError("target_prices is required for batch processing")

    if _max_prices is None:
        _max_prices = [None] * num_configs

    def extend_list(lst, target_length, default_value):
        if lst is None:
            return [default_value] * target_length
        while len(lst) < target_length:
            lst.append(lst[-1] if lst else default_value)
        return lst[:target_length]

    capacities = extend_list(capacities, num_configs, None)
    ddr_types = extend_list(ddr_types, num_configs, None)
    speeds = extend_list(speeds, num_configs, None)
    min_prices = extend_list(min_prices, num_configs, min_prices[0] if min_prices else 50)
    max_prices: list[int | None] | list[None] = extend_list(_max_prices, num_configs, None)
    target_prices = extend_list(target_prices, num_configs, target_prices[0] if target_prices else 100)

    results = []
    for i in range(num_configs):
        block = generate_keyword_block(
            capacities[i], ddr_types[i], speeds[i],
            min_prices[i], max_prices[i], target_prices[i]
        )
        results.append(block)

    print(json.dumps(results[0] if len(results) == 1 else results, indent=4))


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser()

        parser.add_argument("--capacity", type=str, help="RAM Capacity - just a number (for example, 16 = 16GB)")
        parser.add_argument("--ddr", type=str, help="DDR Type - like 'DDR4' or 'DDR5'")
        parser.add_argument("--speed", type=str, help="RAM Speed - like '3200', '3600', etc.")
        parser.add_argument("--min-price", type=str, help="Minimum Price(s)")
        parser.add_argument("--max-price", type=str, help="Maximum Price(s)")
        parser.add_argument("--target-price", type=str, help="Target Price(s)")

        args = parser.parse_args(sys.argv[1:])

        capacities = parse_comma_separated(args.capacity, 'str')
        ddr_types = parse_comma_separated(args.ddr, 'str')
        speeds = parse_comma_separated(args.speed, 'str')
        min_prices = parse_comma_separated(args.min_price, 'int')
        max_prices = parse_comma_separated(args.max_price, 'int')
        target_prices = parse_comma_separated(args.target_price, 'int')

        main(
            capacities=capacities,
            ddr_types=ddr_types,
            speeds=speeds,
            min_prices=min_prices,
            _max_prices=max_prices,
            target_prices=target_prices
        )
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
