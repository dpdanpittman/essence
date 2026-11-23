Invented example. Sara, Max and the class do not exist.

# Stroke: order the weekly ingredients

Written 2027-01-20.
Landscape: home-economics-class (~/.claude/essence/landscapes/home-economics-class.md, How it works). Read it first.
Brush: the store account (~/.claude/essence/brushes/store-account.md). Check it before you start.

## When

- Max says "do the shop" or "order for Thursday", or it is Wednesday morning and no order exists for the week.

## Shortcut

`shop-order <week>` on Max's laptop. It reads the week's two recipe cards, totals the ingredients for 30 students, checks the total against what is left of the term budget, and places the order with the store. `--dry` prints the list and the total and orders nothing.

## Steps

1. Run `shop-order <week> --dry`. Read the list and the total.
2. If a recipe uses a common allergen, stop. Ask Max whether the parent note has gone out.
3. If the total is more than what is left of the term budget, stop. Show Max the three most expensive lines.
4. Run `shop-order <week>`. Success is the line "Order placed, delivery Wednesday".
5. Update the landscape: the budget left this term.

## Undo

`shop-order cancel <week>`. The store takes a cancel until Tuesday 18:00.

## Traps

- The fridge holds one week. An order for two weeks at once spoils.
- The store drops eggs from the order when they are out of stock and says so only on the receipt. Check the receipt on Wednesday.
