- Convert to discord.py bot
- Refine the new async code to my liking
- Re-evaluate evaluate_deal() logic since I can picture some edge cases where it wouldn't work as intended
- Make it so the acceptable price range (range that the item price must fall within for it to be pushed to a webhook) is different than the deal evaluation range because you don't want to accidentally block really good deals but if you lower the min price too much it will shift the evaluation logic and incorrectly evaluate deals
  - so maybe something like this:
    ```json
    {"keyword": "3060", "min_price": 130, "max_price": 170, "fire_deal": "130 TO 145", "great_deal": "146 TO 160", ...etc}
    ```
    - or maybe instead of "TO" since it's a magic string, it could be more like `"fire_deal": {"start": 130, "end": 145}`
- I removed query mode because I don't like it really and it wastes API calls, but also there's the chance that the listing title wouldn't contain the keyword but the description would, so maybe I should re-add it with that in mind? Or somehow get the description in the current mode? (That would probably require calls for each listing though which would be super expensive since the endpoint for getting listing details shares a rate limit with the endpoint for searching listings, however I'm pretty sure it supports batching: `https://api.ebay.com/buy/browse/v1/item?item_ids=<id1>,<id2>,...` so it would basically just be one extra call, idk i'll consider it)
