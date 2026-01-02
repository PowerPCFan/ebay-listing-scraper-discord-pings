import sys
import json
import argparse
import textwrap
from typing import Any


NORMAL_REGEX = "regexp::(?:\\b(?:RTX[\\s-]*)?{model}\\b(?![\\s-]*(?:Ti|SUPER)\\b))"
TI_REGEX = "regexp::(?:\\b(?:RTX[\\s-]*)?{model}[\\s-]*Ti\\b(?![\\s-]*SUPER\\b))"
SUPER_REGEX = "regexp::(?:\\b(?:RTX[\\s-]*)?{model}[\\s-]*SUPER\\b)"
TI_SUPER_REGEX = "regexp::(?:\\b(?:RTX[\\s-]*)?{model}[\\s-]*Ti[\\s-]*SUPER\\b)"
VRAM_SPECIFIC_REGEX = "regexp::(?:\\b(?:RTX[\\s-]*)?{model}\\b(?![\\s-]*(?:Ti|SUPER)\\b)[\\s-]+{vram_amt}\\s?GB\\b)"


def generate_keyword_block(
    model: str,
    ti: bool,
    _super: bool,
    vram: int | None,
    min_price: int,
    max_price: int | None,
    target_price: int
) -> dict[str, Any]:
    if ti and _super:
        regex = TI_SUPER_REGEX.format(model=model)
    elif ti:
        regex = TI_REGEX.format(model=model)
    elif _super:
        regex = SUPER_REGEX.format(model=model)
    elif vram is not None:
        regex = VRAM_SPECIFIC_REGEX.format(model=model, vram_amt=vram)
    elif not ti and not _super and vram is None:
        regex = NORMAL_REGEX.format(model=model)
    else:
        raise ValueError("Invalid combination of Ti, SUPER, and VRAM parameters. (Note: VRAM can only be specified for non-Ti, non-SUPER models)")  # noqa: E501

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
    """Parse comma-separated values and convert to appropriate types"""
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
    tis: list[bool] | None,
    supers: list[bool] | None,
    vrams: list[int | None] | None,
    min_prices: list[int] | None,
    max_prices: list[int | None] | None,
    target_prices: list[int] | None
):
    if models and not isinstance(models, list):
        models = [models]
    if tis and not isinstance(tis, list):
        tis = [tis]
    if supers and not isinstance(supers, list):
        supers = [supers]
    if vrams and not isinstance(vrams, list):
        vrams = [vrams]
    if min_prices and not isinstance(min_prices, list):
        min_prices = [min_prices]
    if max_prices and not isinstance(max_prices, list):
        max_prices = [max_prices]
    if target_prices and not isinstance(target_prices, list):
        target_prices = [target_prices]

    if models is None:
        model = input("GPU Model (e.g., 3080, 3090): ").strip()
        models = [model]

    num_configs = len(models)

    if tis is None:
        if num_configs == 1:
            ti_raw = (input("Ti GPU? [y/N]: ").strip().lower() or "n")
            tis = [True if ti_raw == "y" else False]
        else:
            tis = [False] * num_configs

    if supers is None:
        if num_configs == 1:
            super_raw = (input("SUPER GPU? [y/N]: ").strip().lower() or "n")
            supers = [True if super_raw == "y" else False]
        else:
            supers = [False] * num_configs

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

    if vrams is None:
        vrams = [None] * num_configs

    if max_prices is None:
        max_prices = [None] * num_configs

    def extend_list(lst, target_length, default_value):
        if lst is None:
            return [default_value] * target_length
        while len(lst) < target_length:
            lst.append(lst[-1] if lst else default_value)
        return lst[:target_length]

    tis = extend_list(tis, num_configs, False)
    supers = extend_list(supers, num_configs, False)
    vrams: list[int | None] | list[None] = extend_list(vrams, num_configs, None)
    min_prices = extend_list(min_prices, num_configs, min_prices[0] if min_prices else 50)
    max_prices: list[int | None] | list[None] = extend_list(max_prices, num_configs, None)
    target_prices = extend_list(target_prices, num_configs, target_prices[0] if target_prices else 100)

    results = []
    for i in range(num_configs):
        block = generate_keyword_block(
            models[i], tis[i], supers[i], vrams[i], 
            min_prices[i], max_prices[i], target_prices[i]
        )
        results.append(block)

    if len(results) == 1:
        raw_output = textwrap.indent(text=json.dumps(results[0], indent=4), prefix="                ")
        output_lines = raw_output.splitlines()
        model = models[0]
        ti = tis[0]
        _super = supers[0]
        vram = vrams[0]
        target_price = target_prices[0]
        for i, line in enumerate(output_lines):
            if '"keyword":' in line:
                output_lines[i] = line + f"  // {model}{' Ti' if ti else ''}{' SUPER' if _super else ''}{' ' + str(vram) + 'GB' if vram is not None else ''} (Target Price ${target_price})"
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
                ti = tis[result_index]
                _super = supers[result_index]
                vram = vrams[result_index]
                target_price = target_prices[result_index]
                comment = f"  // {model}{' Ti' if ti else ''}{' SUPER' if _super else ''}{' ' + str(vram) + 'GB' if vram is not None else ''} (Target Price ${target_price})"
                lines[i] = line + comment
                result_index += 1

        print("\n".join(lines))


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser()

        parser.add_argument("--model", type=str, help="GPU Model(s) - comma separated (e.g., '3080,3090')")
        parser.add_argument("--ti", type=str, help="Ti flags - comma separated (e.g., 'false,true')")
        parser.add_argument("--super", type=str, help="SUPER flags - comma separated (e.g., 'false,true')")
        parser.add_argument("--vram", type=str, help="VRAM in GB - comma separated (e.g., '8,12')")
        parser.add_argument("--min-price", type=str, help="Minimum Price(s) - comma separated")
        parser.add_argument("--max-price", type=str, help="Maximum Price(s) - comma separated")
        parser.add_argument("--target-price", type=str, help="Target Price(s) - comma separated")

        args = parser.parse_args(sys.argv[1:])

        models = parse_comma_separated(args.model, 'str')
        tis = parse_comma_separated(args.ti, 'bool')
        supers = parse_comma_separated(args.super, 'bool')
        vrams = parse_comma_separated(args.vram, 'int')
        min_prices = parse_comma_separated(args.min_price, 'int')
        max_prices = parse_comma_separated(args.max_price, 'int')
        target_prices = parse_comma_separated(args.target_price, 'int')

        main(
            models=models,
            tis=tis,
            supers=supers,
            vrams=vrams,
            min_prices=min_prices,
            max_prices=max_prices,
            target_prices=target_prices
        )
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
