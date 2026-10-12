# Chapter 2: Two Pointers & Sliding Window

## 1. Concept

**Two pointers** means using two index variables to scan a structure, instead of one — usually moving toward each other (from both ends) or moving together in the same direction with different speeds.

**Sliding window** is a special case of two pointers where you maintain a "window" (a contiguous range `[left, right]`) over an array or string, growing and shrinking it as you scan, instead of recomputing from scratch for every possible window.

```
Two pointers (converging):
 [2, 7, 11, 15, 18]      target = 24
  L                 R
  L->                R moves toward L
      L          R
         L    R
            LR / cross -> done

Sliding window (expanding/shrinking):
 s = "a b c a b c b b"
      [a b c]                window too small? expand right
      [a b c a]               duplicate 'a' found -> shrink left
        [b c a]               valid again
          [b c a b]           ...continue
```

## 2. When to Use This Pattern

- Array is **sorted** and you need a pair/triplet matching some sum condition → two pointers from both ends.
- "Longest/shortest substring or subarray satisfying some condition" → sliding window.
- Need to compare characters from both ends (palindrome check) → two pointers converging.
- Removing duplicates in-place from a sorted array → two pointers, one reading, one writing.
- Fixed-size window ("every subarray of size k") → simple sliding window with a running sum/count.

## 3. Template / Skeleton Code

```python
def two_pointer_converging_template(arr: list[int], target: int) -> list[int]:
    left, right = 0, len(arr) - 1
    while left < right:
        current = arr[left] + arr[right]
        if current == target:
            return [left, right]
        elif current < target:
            left += 1
        else:
            right -= 1
    return []


def sliding_window_template(s: str) -> int:
    left = 0
    best = 0
    window_state = {}  # e.g., character counts inside the window
    for right in range(len(s)):
        char = s[right]
        window_state[char] = window_state.get(char, 0) + 1

        # Shrink the window from the left while it's "invalid"
        while window_is_invalid(window_state):
            left_char = s[left]
            window_state[left_char] -= 1
            if window_state[left_char] == 0:
                del window_state[left_char]
            left += 1

        best = max(best, right - left + 1)
    return best


def window_is_invalid(window_state: dict) -> bool:
    # Placeholder for an actual condition, e.g. too many distinct chars
    return False
```

---

## 4. Problems (Basic → Advanced)

### Problem 1: Valid Palindrome
**Statement:** Given a string, return `True` if it's a palindrome after removing all non-alphanumeric characters and lowercasing everything.

**Example:**
```
Input: s = "A man, a plan, a canal: Panama"
Output: True
```

**Approach:** Use two pointers starting at both ends. Skip non-alphanumeric characters as you go. Compare the lowercased characters; if they ever differ, it's not a palindrome. If pointers meet without mismatch, it is.

```python
def is_palindrome(s: str) -> bool:
    left, right = 0, len(s) - 1
    while left < right:
        while left < right and not s[left].isalnum():
            left += 1
        while left < right and not s[right].isalnum():
            right -= 1
        if s[left].lower() != s[right].lower():
            return False
        left += 1
        right -= 1
    return True


if __name__ == "__main__":
    print(is_palindrome("A man, a plan, a canal: Panama"))  # True
    print(is_palindrome("race a car"))                       # False
    print(is_palindrome(" "))                                 # True
```

**Complexity:** Time O(n), Space O(1).

---

### Problem 2: Two Sum II (Sorted Array)
**Statement:** Given a 1-indexed array sorted in ascending order, find two numbers that add up to `target`. Return their 1-indexed positions.

**Example:**
```
Input: numbers = [2, 7, 11, 15], target = 9
Output: [1, 2]
```

**Approach:** Because the array is sorted, we can use two pointers from both ends. If the sum is too big, move the right pointer left (decrease sum). If too small, move the left pointer right (increase sum). This avoids the hash map approach entirely and uses O(1) extra space.

```python
def two_sum_sorted(numbers: list[int], target: int) -> list[int]:
    left, right = 0, len(numbers) - 1
    while left < right:
        current = numbers[left] + numbers[right]
        if current == target:
            return [left + 1, right + 1]  # 1-indexed
        elif current < target:
            left += 1
        else:
            right -= 1
    return []


if __name__ == "__main__":
    print(two_sum_sorted([2, 7, 11, 15], 9))  # [1, 2]
    print(two_sum_sorted([2, 3, 4], 6))        # [1, 3]
```

**Complexity:** Time O(n), Space O(1).

---

### Problem 3: 3Sum
**Statement:** Given an integer array, find all unique triplets `[a, b, c]` such that `a + b + c == 0`.

**Example:**
```
Input: nums = [-1, 0, 1, 2, -1, -4]
Output: [[-1, -1, 2], [-1, 0, 1]]
```

**Approach:** Sort the array first. Fix one number (`i`), then use two pointers on the remaining subarray to find pairs that sum to `-nums[i]` (this reduces each sub-problem to "Two Sum II"). Skip duplicate values at every level to avoid duplicate triplets in the output.

```python
def three_sum(nums: list[int]) -> list[list[int]]:
    nums.sort()
    result: list[list[int]] = []
    n = len(nums)

    for i in range(n):
        if i > 0 and nums[i] == nums[i - 1]:
            continue  # skip duplicate "first" elements
        if nums[i] > 0:
            break  # sorted array, no way to reach 0 anymore

        left, right = i + 1, n - 1
        while left < right:
            total = nums[i] + nums[left] + nums[right]
            if total < 0:
                left += 1
            elif total > 0:
                right -= 1
            else:
                result.append([nums[i], nums[left], nums[right]])
                left += 1
                right -= 1
                while left < right and nums[left] == nums[left - 1]:
                    left += 1
                while left < right and nums[right] == nums[right + 1]:
                    right -= 1

    return result


if __name__ == "__main__":
    print(three_sum([-1, 0, 1, 2, -1, -4]))  # [[-1, -1, 2], [-1, 0, 1]]
    print(three_sum([0, 0, 0]))               # [[0, 0, 0]]
```

**Complexity:** Time O(n²) (sort is O(n log n), dominated by the nested two-pointer scan). Space O(n) for sorting / output.

---

### Problem 4: Best Time to Buy and Sell Stock
**Statement:** Given an array `prices` where `prices[i]` is the price on day `i`, find the maximum profit from buying on one day and selling on a later day. Return 0 if no profit is possible.

**Example:**
```
Input: prices = [7, 1, 5, 3, 6, 4]
Output: 5   # Buy at 1, sell at 6
```

**Approach:** This is a sliding window where `left` tracks the cheapest buy day seen so far, and `right` scans forward looking for the best sell day. If `prices[right]` is lower than `prices[left]`, we've found a new, better buy point, so we move `left` to `right`. Otherwise, we check if selling here beats our best profit so far.

```python
def max_profit(prices: list[int]) -> int:
    if not prices:
        return 0

    left = 0  # best buy day so far
    best_profit = 0

    for right in range(1, len(prices)):
        if prices[right] < prices[left]:
            left = right  # found a cheaper buy day
        else:
            profit = prices[right] - prices[left]
            best_profit = max(best_profit, profit)

    return best_profit


if __name__ == "__main__":
    print(max_profit([7, 1, 5, 3, 6, 4]))  # 5
    print(max_profit([7, 6, 4, 3, 1]))      # 0
```

**Complexity:** Time O(n), Space O(1).

---

### Problem 5: Longest Substring Without Repeating Characters
**Statement:** Given a string, find the length of the longest substring without repeating characters.

**Example:**
```
Input: s = "abcabcbb"
Output: 3   # "abc"
```

**Approach:** Classic sliding window. Expand `right` one character at a time, adding to a set of characters currently "in the window." If the new character is already in the set, shrink from the `left` (removing characters from the set) until the duplicate is gone. Track the max window size seen.

```python
def length_of_longest_substring(s: str) -> int:
    seen: set[str] = set()
    left = 0
    best = 0

    for right in range(len(s)):
        while s[right] in seen:
            seen.remove(s[left])
            left += 1
        seen.add(s[right])
        best = max(best, right - left + 1)

    return best


if __name__ == "__main__":
    print(length_of_longest_substring("abcabcbb"))  # 3
    print(length_of_longest_substring("bbbbb"))      # 1
    print(length_of_longest_substring("pwwkew"))     # 3
```

**Complexity:** Time O(n) — each character is added and removed from the window at most once. Space O(min(n, alphabet size)).

---

### Problem 6: Minimum Window Substring
**Statement:** Given strings `s` and `t`, find the smallest substring of `s` that contains all characters of `t` (including duplicates). Return `""` if no such substring exists.

**Example:**
```
Input: s = "ADOBECODEBANC", t = "ABC"
Output: "BANC"
```

**Approach:** Count required characters of `t` in a hash map. Expand the window (`right`) over `s`, decreasing the "still needed" count whenever we include a character `t` cares about. Once the window contains *everything* needed (tracked with a counter `have == need`), try shrinking from the `left` as much as possible while staying valid, recording the smallest valid window found.

```python
from collections import Counter

def min_window(s: str, t: str) -> str:
    if not s or not t:
        return ""

    need = Counter(t)
    missing = len(t)  # total characters still needed (with multiplicity)

    left = 0
    best_len = float("inf")
    best_left = 0

    for right, char in enumerate(s):
        if need[char] > 0:
            missing -= 1
        need[char] -= 1

        while missing == 0:
            if right - left + 1 < best_len:
                best_len = right - left + 1
                best_left = left

            left_char = s[left]
            need[left_char] += 1
            if need[left_char] > 0:
                missing += 1
            left += 1

    return "" if best_len == float("inf") else s[best_left:best_left + best_len]


if __name__ == "__main__":
    print(min_window("ADOBECODEBANC", "ABC"))  # "BANC"
    print(min_window("a", "a"))                  # "a"
    print(min_window("a", "aa"))                 # ""
```

**Complexity:** Time O(|s| + |t|), Space O(|t|) for the `need` counter.

---

## 5. Complexity Summary

| Problem | Time | Space |
|---------|------|-------|
| Valid Palindrome | O(n) | O(1) |
| Two Sum II (Sorted Array) | O(n) | O(1) |
| 3Sum | O(n²) | O(n) |
| Best Time to Buy and Sell Stock | O(n) | O(1) |
| Longest Substring Without Repeating Characters | O(n) | O(k) |
| Minimum Window Substring | O(n + m) | O(m) |

---

## 6. Interview Tips

- **Say why sorting helps, if you sort first.** For 3Sum, point out: "Sorting lets me use two pointers to find complements in O(n) per fixed element, instead of a hash set lookup, and it also makes duplicate-skipping trivial."
- **Narrate the window invariant.** For sliding window problems, clearly state what makes a window "valid" or "invalid" before coding: "The window is valid as long as it has no duplicate characters" — this forces you to think through the shrink condition correctly.
- **Draw it if you can.** Even a rough ASCII sketch of the window sliding over the string on a whiteboard/notepad helps both you and the interviewer track pointer movement.
- **Mention amortized analysis for sliding window.** Many candidates worry sliding window is O(n²) because of the nested `while` loop inside a `for` loop. Explain that each pointer only moves forward, never backward, so the total work across the whole run is still O(n), not O(n²).
- **Be careful with duplicate-skipping logic (3Sum).** This is the most common place candidates introduce subtle bugs. Walk through a small example with duplicates out loud before finalizing the code.
