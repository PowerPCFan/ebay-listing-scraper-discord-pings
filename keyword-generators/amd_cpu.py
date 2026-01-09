import sys
import json
import argparse
import textwrap
from typing import Any


CPU_WITH_SUFFIX = "regexp::(?:\\b(?:R|Ryzen)[\\s-]*{ryzen}[\\s-]*{model}[\\s-]*{suffix}\\b(?![a-zA-Z0-9]))"
CPU_WITHOUT_SUFFIX = "regexp::(?:\\b(?:R|Ryzen)[\\s-]*{ryzen}[\\s-]*{model}\\b(?![a-zA-Z]))"


def generate_keyword_block(
    ryzen: str,
    model: str,
    suffix: str | None,
    min_price: int,
    max_price: int | None,
    target_price: int
) -> dict[str, Any]:
    if suffix:
        regex = CPU_WITH_SUFFIX.format(ryzen=ryzen, model=model, suffix=suffix)
    else:
        regex = CPU_WITHOUT_SUFFIX.format(ryzen=ryzen, model=model)

    if max_price is not None:
        print("Warning: Using --max-price is discouraged as it bypasses the dynamic max price calculation.")
    else:
        max_price = target_price + 20 if (target_price // 20) > 20 else target_price + (target_price // 20)

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
    ryzens: list | None,
    models: list | None,
    suffixes: list | None,
    min_prices: list | None,
    _max_prices: list | None,
    target_prices: list | None
):
    if ryzens and not isinstance(ryzens, list):
        ryzens = [ryzens]
    if models and not isinstance(models, list):
        models = [models]
    if suffixes and not isinstance(suffixes, list):
        suffixes = [suffixes]
    if min_prices and not isinstance(min_prices, list):
        min_prices = [min_prices]
    if _max_prices and not isinstance(_max_prices, list):
        _max_prices = [_max_prices]
    if target_prices and not isinstance(target_prices, list):
        target_prices = [target_prices]

    if ryzens is None:
        ryzen = input("Ryzen Series (e.g., 3, 5, 7, 9): ").strip()
        ryzens = [ryzen]

    if models is None:
        model = input("CPU Model (e.g., 3600, 5800, 7700, 9950): ").strip()
        models = [model]

    num_configs = len(models) if models else len(ryzens)

    if suffixes is None:
        if num_configs == 1:
            suffix_raw = input("CPU Suffix (e.g., X, X3D) (leave blank for none): ").strip()
            suffixes = [suffix_raw if suffix_raw else None]
        else:
            suffixes = [None] * num_configs

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

    ryzens = extend_list(ryzens, num_configs, "5")
    models = extend_list(models, num_configs, models[0])
    suffixes = extend_list(suffixes, num_configs, None)
    min_prices = extend_list(min_prices, num_configs, min_prices[0] if min_prices else 50)
    max_prices: list[int | None] | list[None] = extend_list(_max_prices, num_configs, None)
    target_prices = extend_list(target_prices, num_configs, target_prices[0] if target_prices else 100)

    results = []
    for i in range(num_configs):
        block = generate_keyword_block(
            ryzens[i], models[i], suffixes[i],
            min_prices[i], max_prices[i], target_prices[i]
        )
        results.append(block)

    if len(results) == 1:
        raw_output = textwrap.indent(text=json.dumps(results[0], indent=4), prefix="                ")
        output_lines = raw_output.splitlines()
        ryzen = ryzens[0]
        model = models[0]
        suffix = suffixes[0]
        target_price = target_prices[0]
        for i, line in enumerate(output_lines):
            if '"keyword":' in line:
                cpu_name = f"Ryzen {ryzen} {model}{suffix if suffix else ''}"
                output_lines[i] = line + f"  // {cpu_name} (Target Price ${target_price})"
                break

        output = "\n".join(output_lines)
        print(output)
    else:
        output = json.dumps(results, indent=4)
        lines = output.splitlines()

        result_index = 0
        for i, line in enumerate(lines):
            if '"keyword":' in line and result_index < len(models):
                ryzen = ryzens[result_index]
                model = models[result_index]
                suffix = suffixes[result_index]
                target_price = target_prices[result_index]
                cpu_name = f"R{ryzen} {model}{suffix if suffix else ''}"
                comment = f"  // {cpu_name} (Target Price ${target_price})"
                lines[i] = line + comment
                result_index += 1

        print("\n".join(lines))


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser()

        parser.add_argument("--ryzen", type=str, help="Ryzen Series - comma separated (e.g., '3,5,7,9')")
        parser.add_argument("--model", type=str, help="CPU Model(s) - comma separated (e.g., '3600,5800,7700')")
        parser.add_argument("--suffix", type=str, help="CPU Suffix - comma separated (e.g., 'none,X,X3D' or 'X3D,T,none')")  # noqa: E501
        parser.add_argument("--min-price", type=str, help="Minimum Price(s) - comma separated")
        parser.add_argument("--max-price", type=str, help="Maximum Price(s) - comma separated")
        parser.add_argument("--target-price", type=str, help="Target Price(s) - comma separated")

        args = parser.parse_args(sys.argv[1:])

        ryzens = parse_comma_separated(args.ryzen, 'str')
        models = parse_comma_separated(args.model, 'str')
        suffixes = parse_comma_separated(args.suffix, 'str_or_none')
        min_prices = parse_comma_separated(args.min_price, 'int')
        max_prices = parse_comma_separated(args.max_price, 'int')
        target_prices = parse_comma_separated(args.target_price, 'int')

        main(
            ryzens=ryzens,
            models=models,
            suffixes=suffixes,
            min_prices=min_prices,
            _max_prices=max_prices,
            target_prices=target_prices
        )
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
