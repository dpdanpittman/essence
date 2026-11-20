Invented example. Sara, Max and the class do not exist.

# Brush: the store account

Written 2027-01-20.

## What it is

- The class's account with the grocery store's ordering site. The agent uses it through `shop-order` (2027-01-20, record).

## Can reach

- Place, change and cancel orders for delivery to the school kitchen (2027-01-20, checked).
- Read past orders and receipts (2027-01-20, checked).

## Cannot

- Pay. The school office pays the monthly invoice. The account has no card on it (2027-01-20, record).
- Order more than 80 in one week. The store refuses a larger order from a school account (2027-01-21, checked).
- Order for any address but the school kitchen (2027-01-20, record).

## Where its key lives

- Max's password manager, vault "Class", item "Store account". Never the password itself.

## Granted by and when

- Max made the account on 2027-01-15 and gave the agent the item on 2027-01-20. The head of department knows (record).

## How to check it

- `shop-order whoami`. It prints the account name and the weekly limit, and orders nothing.

## How to take it away

- Max removes the item from the "Class" vault, or changes the password on the store's site.

## Used by

- Landscape: home-economics-class. Stroke: order-weekly-ingredients.
