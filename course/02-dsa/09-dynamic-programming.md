# Chapter 9: Dynamic Programming

## 1. Concept

Dynamic Programming (DP) solves a big problem by breaking it into smaller overlapping sub-problems, solving each sub-problem **once**, and reusing the stored result instead of recomputing it. The two requirements for DP to apply:

1. **Optimal substructure** — the best answer to the big problem can be built from the best answers to its sub-problems.
2. **Overlapping sub-problems** — the same sub-problem gets asked for again and again if solved naively with plain recursion.

```
Fibonacci without memoization (overlapping work, exponential):

                    fib(5)
                 /          \
            fib(4)          fib(3)
           /      \         /     \
       fib(3)   fib(2)   fib(2)  fib(1)
       /    \
   fib(2) fib(1)

   fib(3) and fib(2) are each computed multiple times — wasted work.

With memoization, each fib(n) is computed exactly once:
   fib(0), fib(1), fib(2), fib(3), fib(4), fib(5)   <- each solved once, reused after
```

Two ways to implement DP:
- **Top-down (memoization)**: write the natural recursive solution, then cache results in a dictionary/array so repeat calls return instantly.
- **Bottom-up (tabulation)**: build a table iteratively from the smallest sub-problems up to the full problem, usually using a loop instead of recursion.

## 2. When to Use This Pattern

- The problem asks for a **count**, **minimum/maximum**, or **yes/no possibility**, and a brute-force recursive solution would re-solve the same smaller inputs repeatedly.
- Problem mentions "ways to do X," "minimum cost to reach Y," or "longest/shortest Z satisfying a condition."
- You can define the problem recursively: "the answer for `n` depends on the answer for smaller values like `n-1`, `n-2`, or a split point."
- Classic giveaways: strings compared (LCS, edit distance), coins/items with a capacity constraint (knapsack), subsequences (LIS), or state transitions over time (stock trading with cooldowns).

## 3. Template / Skeleton Code

```python
# Top-down (memoization) template
from functools import lru_cache

def top_down_template(n: int) -> int:
    @lru_cache(maxsize=None)
    def solve(i: int) -> int:
        if i <= 1:  # base case
            return i
        return solve(i - 1) + solve(i - 2)  # combine smaller sub-problems
    return solve(n)


# Bottom-up (tabulation) template
def bottom_up_template(n: int) -> int:
    if n <= 1:
        return n
    dp = [0] * (n + 1)
    dp[0], dp[1] = 0, 1
    for i in range(2, n + 1):
        dp[i] = dp[i - 1] + dp[i - 2]
    return dp[n]


# 2D DP template (for grid/string problems)
def two_d_template(rows: int, cols: int) -> int:
    dp = [[0] * (cols + 1) for _ in range(rows + 1)]
    for r in range(1, rows + 1):
        for c in range(1, cols + 1):
            dp[r][c] = dp[r - 1][c] + dp[r][c - 1]  # example transition
    return dp[rows][cols]
```

---

## 4. Problems (Basic → Advanced)

### Problem 1: Climbing Stairs (1D DP)
**Statement:** You're climbing a staircase with `n` steps. Each move, you can climb 1 or 2 steps. How many distinct ways can you reach the top?

**Example:**
```
Input: n = 3
Output: 3   # (1,1,1), (1,2), (2,1)
```

**Approach:** To reach step `n`, your last move was either a 1-step from `n-1`, or a 2-step from `n-2`. So `ways(n) = ways(n-1) + ways(n-2)` — this is exactly Fibonacci. Build it bottom-up with O(1) space since we only ever need the last two values.

```python
def climb_stairs(n: int) -> int:
    if n <= 2:
        return n

    prev2, prev1 = 1, 2  # ways(1), ways(2)
    for _ in range(3, n + 1):
        prev2, prev1 = prev1, prev1 + prev2

    return prev1


if __name__ == "__main__":
    print(climb_stairs(2))  # 2
    print(climb_stairs(3))  # 3
    print(climb_stairs(5))  # 8
```

**Complexity:** Time O(n), Space O(1).

---

### Problem 2: House Robber (1D DP)
**Statement:** Given an array of non-negative integers representing money in each house, find the maximum amount you can rob without robbing two adjacent houses.

**Example:**
```
Input: nums = [2, 7, 9, 3, 1]
Output: 12   # rob house 0 (2), house 2 (9), house 4 (1) = 12
```

**Approach:** At each house `i`, you choose: skip it (carry forward the best result up to `i-1`), or rob it (its value plus the best result up to `i-2`, since you can't rob the immediate neighbor). Take the max of these two choices.

```python
def rob(nums: list[int]) -> int:
    prev2, prev1 = 0, 0  # best up to house i-2, best up to house i-1

    for num in nums:
        current = max(prev1, prev2 + num)
        prev2, prev1 = prev1, current

    return prev1


if __name__ == "__main__":
    print(rob([2, 7, 9, 3, 1]))  # 12
    print(rob([1, 2, 3, 1]))      # 4
    print(rob([]))                 # 0
```

**Complexity:** Time O(n), Space O(1).

---

### Problem 3: Coin Change (Unbounded Knapsack)
**Statement:** Given coin denominations and a target amount, return the fewest number of coins needed to make that amount, or `-1` if impossible. Unlimited coins of each denomination are available.

**Example:**
```
Input: coins = [1, 2, 5], amount = 11
Output: 3   # 5 + 5 + 1
```

**Approach:** Build `dp[a]` = minimum coins to make amount `a`, for every amount from 0 to target. `dp[0] = 0` (base case). For each amount, try every coin: if using that coin is possible (`a - coin >= 0`), `dp[a] = min(dp[a], dp[a - coin] + 1)`.

```python
def coin_change(coins: list[int], amount: int) -> int:
    dp = [float("inf")] * (amount + 1)
    dp[0] = 0

    for a in range(1, amount + 1):
        for coin in coins:
            if coin <= a:
                dp[a] = min(dp[a], dp[a - coin] + 1)

    return dp[amount] if dp[amount] != float("inf") else -1


if __name__ == "__main__":
    print(coin_change([1, 2, 5], 11))  # 3
    print(coin_change([2], 3))          # -1
    print(coin_change([1], 0))          # 0
```

**Complexity:** Time O(amount × number of coins), Space O(amount).

---

### Problem 4: Longest Increasing Subsequence (LIS)
**Statement:** Given an integer array, return the length of the longest strictly increasing subsequence (elements don't need to be contiguous).

**Example:**
```
Input: nums = [10, 9, 2, 5, 3, 7, 101, 18]
Output: 4   # [2, 3, 7, 101]
```

**Approach (O(n²) DP):** `dp[i]` = length of the longest increasing subsequence ending exactly at index `i`. For each `i`, check every earlier index `j`: if `nums[j] < nums[i]`, this element could extend that subsequence, so `dp[i] = max(dp[i], dp[j] + 1)`. The answer is the max over all `dp[i]`.

```python
def length_of_lis(nums: list[int]) -> int:
    if not nums:
        return 0

    dp = [1] * len(nums)  # every element is a subsequence of length 1 by itself

    for i in range(len(nums)):
        for j in range(i):
            if nums[j] < nums[i]:
                dp[i] = max(dp[i], dp[j] + 1)

    return max(dp)


if __name__ == "__main__":
    print(length_of_lis([10, 9, 2, 5, 3, 7, 101, 18]))  # 4
    print(length_of_lis([0, 1, 0, 3, 2, 3]))              # 4
    print(length_of_lis([7, 7, 7, 7]))                     # 1
```

**Complexity:** Time O(n²), Space O(n). (A faster O(n log n) version exists using binary search on a "tails" array, worth mentioning as a follow-up.)

---

### Problem 5: Longest Common Subsequence (LCS) — 2D DP
**Statement:** Given two strings, return the length of their longest common subsequence (characters in the same relative order, not necessarily contiguous).

**Example:**
```
Input: text1 = "abcde", text2 = "ace"
Output: 3   # "ace"
```

**Approach:** Build a 2D table `dp[i][j]` = LCS length of `text1[:i]` and `text2[:j]`. If the last characters match (`text1[i-1] == text2[j-1]`), extend the LCS found without those characters: `dp[i][j] = dp[i-1][j-1] + 1`. Otherwise, take the best of dropping a character from either string: `dp[i][j] = max(dp[i-1][j], dp[i][j-1])`.

```python
def longest_common_subsequence(text1: str, text2: str) -> int:
    m, n = len(text1), len(text2)
    dp = [[0] * (n + 1) for _ in range(m + 1)]

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if text1[i - 1] == text2[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])

    return dp[m][n]


if __name__ == "__main__":
    print(longest_common_subsequence("abcde", "ace"))  # 3
    print(longest_common_subsequence("abc", "abc"))      # 3
    print(longest_common_subsequence("abc", "def"))      # 0
```

**Complexity:** Time O(m × n), Space O(m × n).

---

### Problem 6: 0/1 Knapsack
**Statement:** Given `n` items with weights and values, and a knapsack with capacity `W`, find the maximum total value you can carry without exceeding the capacity. Each item can be used at most once (0 or 1 copy).

**Example:**
```
Input: weights = [1, 3, 4, 5], values = [1, 4, 5, 7], capacity = 7
Output: 9   # take items with weight 3 (value 4) and weight 4 (value 5) = 9
```

**Approach:** `dp[c]` = max value achievable with capacity `c`. For each item, decide (for every capacity from high to low, to avoid reusing the same item twice): skip the item (`dp[c]` stays the same), or take it (`dp[c] = max(dp[c], dp[c - weight] + value)`). Iterating capacity in reverse order per item is what keeps this "0/1" (each item used at most once) instead of "unbounded."

```python
def knapsack(weights: list[int], values: list[int], capacity: int) -> int:
    dp = [0] * (capacity + 1)

    for weight, value in zip(weights, values):
        for c in range(capacity, weight - 1, -1):  # reverse order: 0/1 knapsack
            dp[c] = max(dp[c], dp[c - weight] + value)

    return dp[capacity]


if __name__ == "__main__":
    print(knapsack([1, 3, 4, 5], [1, 4, 5, 7], 7))  # 9
    print(knapsack([2, 3, 4], [3, 4, 5], 5))          # 7
```

**Complexity:** Time O(n × capacity), Space O(capacity).

---

### Problem 7: Edit Distance (2D DP)
**Statement:** Given two strings `word1` and `word2`, return the minimum number of operations (insert, delete, replace a character) to convert `word1` into `word2`.

**Example:**
```
Input: word1 = "horse", word2 = "ros"
Output: 3   # horse -> rorse (replace h->r) -> rose (remove r) -> ros (remove e)
```

**Approach:** `dp[i][j]` = edit distance between `word1[:i]` and `word2[:j]`. Base cases: converting an empty string to a string of length `j` takes `j` insertions (and vice versa). If characters match, no operation needed at this position: `dp[i][j] = dp[i-1][j-1]`. Otherwise, try all three operations and take the cheapest: insert (`dp[i][j-1] + 1`), delete (`dp[i-1][j] + 1`), or replace (`dp[i-1][j-1] + 1`).

```python
def min_distance(word1: str, word2: str) -> int:
    m, n = len(word1), len(word2)
    dp = [[0] * (n + 1) for _ in range(m + 1)]

    for i in range(m + 1):
        dp[i][0] = i  # delete all i characters of word1
    for j in range(n + 1):
        dp[0][j] = j  # insert all j characters of word2

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if word1[i - 1] == word2[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(
                    dp[i - 1][j],      # delete from word1
                    dp[i][j - 1],      # insert into word1
                    dp[i - 1][j - 1],  # replace
                )

    return dp[m][n]


if __name__ == "__main__":
    print(min_distance("horse", "ros"))      # 3
    print(min_distance("intention", "execution"))  # 5
    print(min_distance("", "abc"))             # 3
```

**Complexity:** Time O(m × n), Space O(m × n).

---

### Problem 8: Best Time to Buy and Sell Stock with Cooldown (State Machine DP)
**Statement:** Given stock prices for `n` days, find the maximum profit from any number of buy/sell transactions, with the rule that after selling, you must wait at least one day (cooldown) before buying again.

**Example:**
```
Input: prices = [1, 2, 3, 0, 2]
Output: 3   # buy day0 (1), sell day2 (3) -> profit 2; cooldown day3; buy day3 (0), sell day4 (2) -> profit 2. Best total: buy day0 sell day2 (profit2), cooldown day3, buy day3 sell day4(profit2) = 4? Let's verify with code below.
```

**Approach:** This is **state machine DP** — model each day as being in one of three states: `held` (currently holding a stock), `sold` (just sold today, must cool down tomorrow), or `rest` (not holding, free to buy). Transition rules:
- `held[i] = max(held[i-1], rest[i-1] - price)` — keep holding, or buy today from a resting state.
- `sold[i] = held[i-1] + price` — sell what we were holding.
- `rest[i] = max(rest[i-1], sold[i-1])` — stay resting, or just finished our cooldown day after selling.

The answer is the best of `sold` or `rest` on the last day (we'd never end while still holding unsold stock for max profit).

```python
def max_profit_cooldown(prices: list[int]) -> int:
    if not prices:
        return 0

    held = float("-inf")  # holding a stock, net profit so far
    sold = 0                # just sold today
    rest = 0                # resting (not holding, no cooldown active)

    for price in prices:
        prev_sold = sold
        sold = held + price
        held = max(held, rest - price)
        rest = max(rest, prev_sold)

    return max(sold, rest)


if __name__ == "__main__":
    print(max_profit_cooldown([1, 2, 3, 0, 2]))  # 3
    print(max_profit_cooldown([1]))                # 0
    print(max_profit_cooldown([1, 2, 4]))           # 3
```

**Complexity:** Time O(n), Space O(1).

---

## 5. Complexity Summary

| Problem | Time | Space |
|---------|------|-------|
| Climbing Stairs | O(n) | O(1) |
| House Robber | O(n) | O(1) |
| Coin Change | O(amount × coins) | O(amount) |
| Longest Increasing Subsequence | O(n²) | O(n) |
| Longest Common Subsequence | O(m × n) | O(m × n) |
| 0/1 Knapsack | O(n × capacity) | O(capacity) |
| Edit Distance | O(m × n) | O(m × n) |
| Stock with Cooldown (state machine) | O(n) | O(1) |

---

## 6. Interview Tips

- **Always state the recurrence relation in plain English before coding.** Say: "`dp[i]` represents X; it depends on `dp[i-1]` and `dp[i-2]` like this..." Interviewers care more about this sentence than the code itself — it proves you understand *why* the solution works, not just *that* it works.
- **Start with brute-force recursion, then add memoization, then explain tabulation.** Narrating this progression ("naive recursion re-solves the same sub-problems, so I'll cache results — that's memoization; I can also rewrite this as a bottom-up loop to avoid recursion overhead") shows a complete mental model, not a memorized final answer.
- **Name the DP category you recognize.** Saying "this is a 0/1 knapsack because each item is used at most once" or "this is LCS because we're comparing two sequences for a common pattern" immediately tells the interviewer you've seen the pattern family before.
- **For space optimization, mention rolling variables.** Many 1D DP problems (Climbing Stairs, House Robber) only need the last 1-2 values, not a full array. Pointing this out and reducing space from O(n) to O(1) is a strong signal of depth.
- **For 2D DP, explicitly describe your table's meaning and base cases before filling it in.** State clearly: "`dp[i][j]` means the answer using the first `i` characters of string A and the first `j` characters of string B; `dp[0][j]` and `dp[i][0]` are my base cases representing an empty string." This avoids off-by-one errors and keeps you oriented in a 2-page grid of numbers.
- **For state machine DP (like stock problems), draw the state transition diagram.** A small diagram showing `held -> sold -> rest -> held...` with the costs of each transition turns an intimidating problem into a clear, almost mechanical one — both for you and the interviewer watching you think.
