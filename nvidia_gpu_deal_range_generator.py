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

    great_end = target_price - 1
    fire_start = min_price
    max_price = target_price + 25 if (target_price // 20) > 25 else target_price + (target_price // 20)
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


def main(
    model: str | None,
    ti: bool | None,
    _super: bool | None,
    vram: int | None,
    min_price: int | None,
    target_price: int | None
):
    if model is None:
        model = input("GPU Model (e.g., 3080, 3090): ").strip()

    if ti is None:
        ti_raw = (input("Ti GPU? [y/N]: ").strip().lower() or "n")
        if ti_raw not in ("y", "n"):
            raise ValueError("Invalid input for Ti or Non-Ti.")
        ti = True if ti_raw == "y" else False

    if _super is None:
        super_raw = (input("SUPER GPU? [y/N]: ").strip().lower() or "n")
        if super_raw not in ("y", "n"):
            raise ValueError("Invalid input for Ti or Non-Ti.")
        _super = True if super_raw == "y" else False

    if min_price is None:
        min_price = int(input("Min Price: ").strip())

    if target_price is None:
        target_price = int(input("Target Price: ").strip())

    if vram is None:
        vram_input = input("VRAM in GB (e.g., 8, 10, 12) (Default: None - no VRAM requirement): ").strip()
        vram = int(vram_input) if vram_input else None

    block = generate_keyword_block(model, ti, _super, vram, min_price, target_price)
    raw_output = textwrap.indent(text=json.dumps(block, indent=4), prefix="                ")
    output_lines = raw_output.splitlines()
    output_lines[1] = output_lines[1] + f"  // {model} {'non-Ti' if not ti else 'Ti'} (Target Price ${target_price})"
    output = "\n".join(output_lines)

    print(output)


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser()

        parser.add_argument("--model", type=str, help="GPU Model")
        parser.add_argument("--ti", action="store_true", help="Flag for if the GPU is a Ti model or not")
        parser.add_argument("--super", action="store_true", help="Flag for if the GPU is a SUPER model or not")
        parser.add_argument("--vram", type=int, help="VRAM in GB")
        parser.add_argument("--min-price", type=int, help="Minimum Price")
        parser.add_argument("--target-price", type=int, help="Target Price")

        args = parser.parse_args(sys.argv[1:])

        main(
            model=args.model or None,
            ti=args.ti or False,
            _super=args.super or False,
            vram=args.vram or None,
            min_price=args.min_price or None,
            target_price=args.target_price or None
        )
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
