import sys
import json
import argparse
import textwrap
from typing import Any


NORMAL_REGEX = "regexp::(?:\\b(?:RX[\\s-]*)?{model}\\b(?![\\s-]*(?:XT|XTX)\\b))"
XT_REGEX = "regexp::(?:\\b(?:RX[\\s-]*)?{model}[\\s-]*XT\\b(?![\\s-]*XTX\\b))"
XTX_REGEX = "regexp::(?:\\b(?:RX[\\s-]*)?{model}[\\s-]*XTX\\b)"


def generate_keyword_block(
    model: str,
    xt: bool,
    xtx: bool,
    min_price: int,
    max_price: int | None,
    target_price: int
) -> dict[str, Any]:
    if xt:
        regex = XT_REGEX.format(model=model)
    elif xtx:
        regex = XTX_REGEX.format(model=model)
    else:
        regex = NORMAL_REGEX.format(model=model)

    if max_price is not None:
        print("Warning: Using --max-price is discouraged as it bypasses the dynamic max price calculation.")
    else:
        max_price = target_price + 25 if (target_price // 20) > 25 else target_price + (target_price // 20)

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
    else:
        return items


def main(
    models: list[str] | None,
    xts: list[bool] | None,
    xtxs: list[bool] | None,
    min_prices: list[int] | None,
    _max_prices: list[int | None] | None,
    target_prices: list[int] | None
):
    if models and not isinstance(models, list):
        models = [models]
    if xts and not isinstance(xts, list):
        xts = [xts]
    if xtxs and not isinstance(xtxs, list):
        xtxs = [xtxs]
    if min_prices and not isinstance(min_prices, list):
        min_prices = [min_prices]
    if _max_prices and not isinstance(_max_prices, list):
        _max_prices = [_max_prices]
    if target_prices and not isinstance(target_prices, list):
        target_prices = [target_prices]

    if models is None:
        model = input("GPU Model (e.g., 6600, 7900, 9070): ").strip()
        models = [model]

    num_configs = len(models)

    if xts is None:
        if num_configs == 1:
            xt_raw = (input("xt GPU? [y/N]: ").strip().lower() or "n")
            xts = [True if xt_raw == "y" else False]
        else:
            xts = [False] * num_configs

    if xtxs is None:
        if num_configs == 1:
            xtx_raw = (input("xtx GPU? [y/N]: ").strip().lower() or "n")
            xtxs = [True if xtx_raw == "y" else False]
        else:
            xtxs = [False] * num_configs

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
        _max_prices = [None] * num_configs  # type: ignore

    def extend_list(lst, target_length, default_value):
        if lst is None:
            return [default_value] * target_length
        while len(lst) < target_length:
            lst.append(lst[-1] if lst else default_value)
        return lst[:target_length]

    xts = extend_list(xts, num_configs, False)
    xtxs = extend_list(xtxs, num_configs, False)
    min_prices = extend_list(min_prices, num_configs, min_prices[0] if min_prices else 50)
    max_prices: list[int | None] | list[None] = extend_list(_max_prices, num_configs, None)
    target_prices = extend_list(target_prices, num_configs, target_prices[0] if target_prices else 100)

    results = []
    for i in range(num_configs):
        block = generate_keyword_block(
            models[i], xts[i], xtxs[i],
            min_prices[i], max_prices[i], target_prices[i]
        )
        results.append(block)

    if len(results) == 1:
        raw_output = textwrap.indent(text=json.dumps(results[0], indent=4), prefix="                ")
        output_lines = raw_output.splitlines()
        model = models[0]
        xt = xts[0]
        _xtx = xtxs[0]
        target_price = target_prices[0]
        for i, line in enumerate(output_lines):
            if '"keyword":' in line:
                output_lines[i] = line + f"  // {model}{' XT' if xt else ''}{' XTX' if _xtx else ''} (Target Price ${target_price})"  # noqa: E501
                break

        output = "\n".join(output_lines)
        print(output)
    else:
        output = json.dumps(results, indent=4)
        lines = output.splitlines()

        result_index = 0
        for i, line in enumerate(lines):
            if '"keyword":' in line and result_index < len(models):
                model = models[result_index]
                xt = xts[result_index]
                _xtx = xtxs[result_index]
                target_price = target_prices[result_index]
                comment = f"  // {model}{' XT' if xt else ''}{' XTX' if _xtx else ''} (Target Price ${target_price})"
                lines[i] = line + comment
                result_index += 1

        print("\n".join(lines))


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser()

        parser.add_argument("--model", type=str, help="GPU Model(s) - comma separated (e.g., '6600,7900,9070')")
        parser.add_argument("--xt", type=str, help="XT flags - comma separated (e.g., 'false,true')")
        parser.add_argument("--xtx", type=str, help="XTX flags - comma separated (e.g., 'false,true')")
        parser.add_argument("--min-price", type=str, help="Minimum Price(s) - comma separated")
        parser.add_argument("--max-price", type=str, help="Maximum Price(s) - comma separated")
        parser.add_argument("--target-price", type=str, help="Target Price(s) - comma separated")

        args = parser.parse_args(sys.argv[1:])

        models = parse_comma_separated(args.model, 'str')
        xts = parse_comma_separated(args.xt, 'bool')
        xtxs = parse_comma_separated(args.xtx, 'bool')
        min_prices = parse_comma_separated(args.min_price, 'int')
        max_prices = parse_comma_separated(args.max_price, 'int')
        target_prices = parse_comma_separated(args.target_price, 'int')

        main(
            models=models,  # type: ignore
            xts=xts,  # type: ignore
            xtxs=xtxs,  # type: ignore
            min_prices=min_prices,  # type: ignore
            _max_prices=max_prices,  # type: ignore
            target_prices=target_prices  # type: ignore
        )
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
