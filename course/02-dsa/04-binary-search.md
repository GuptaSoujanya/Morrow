# Chapter 4: Binary Search

## 1. Concept

Binary search finds a target in a **sorted** (or "sorted-like") search space by repeatedly cutting the space in half. Instead of checking every element (O(n)), you check the middle element, decide which half could possibly contain the answer, and discard the other half entirely.

```
Searching for 23 in a sorted array:

[2, 5, 8, 12, 16, 23, 38, 56, 72, 91]
 lo                              hi
             mid=16 -> 16 < 23, search right half

                    [23, 38, 56, 72, 91]
                     lo              hi
                     mid=56 -> 56 > 23, search left half

                    [23, 38]
                     lo   hi
                     mid=23 -> found!
```

The key mental shift: binary search isn't just "search a sorted array." It is really "**find the boundary point in a monotonic (always-true-then-always-false, or vice versa) condition**." Many advanced binary search problems don't look like searching at all — they're about guessing an answer and checking if it "works," which is called **binary search on the answer**.

## 2. When to Use This Pattern

- The array (or input) is **sorted**, or can be thought of as sorted.
- You see "find minimum/maximum value such that some condition holds" → binary search on the answer.
- Time complexity requirement is O(log n) — a strong hint that linear scanning isn't expected.
- Searching in a **rotated sorted array**.
- "Find first/last occurrence of X" or "find insertion point" problems.

## 3. Template / Skeleton Code

```python
def binary_search_template(arr: list[int], target: int) -> int:
    lo, hi = 0, len(arr) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1  # not found


def binary_search_on_answer_template(lo: int, hi: int) -> int:
    """Find the smallest value in [lo, hi] for which `condition(value)` is True,
    assuming condition is False...False, True...True (monotonic)."""
    def condition(value: int) -> bool:
        return True  # placeholder

    while lo < hi:
        mid = (lo + hi) // 2
        if condition(mid):
            hi = mid        # mid works, try to find something smaller/equal
        else:
            lo = mid + 1     # mid doesn't work, must go higher
    return lo
```

---

## 4. Problems (Basic → Advanced)

### Problem 1: Binary Search (Classic)
**Statement:** Given a sorted array of unique integers and a target, return its index, or -1 if not found.

**Example:**
```
Input: nums = [-1, 0, 3, 5, 9, 12], target = 9
Output: 4
```

**Approach:** Standard binary search. Compare the middle element to the target; narrow the search range to the half that could still contain it.

```python
def search(nums: list[int], target: int) -> int:
    lo, hi = 0, len(nums) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if nums[mid] == target:
            return mid
        elif nums[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1


if __name__ == "__main__":
    print(search([-1, 0, 3, 5, 9, 12], 9))   # 4
    print(search([-1, 0, 3, 5, 9, 12], 2))   # -1
```

**Complexity:** Time O(log n), Space O(1).

---

### Problem 2: Search Insert Position
**Statement:** Given a sorted array and a target, return the index where it is found, or where it would be inserted to keep the array sorted.

**Example:**
```
Input: nums = [1, 3, 5, 6], target = 5
Output: 2

Input: nums = [1, 3, 5, 6], target = 2
Output: 1
```

**Approach:** This is binary search looking for the first index where `nums[index] >= target`. When the loop ends, `lo` naturally lands on that index — whether or not the target exists.

```python
def search_insert(nums: list[int], target: int) -> int:
    lo, hi = 0, len(nums)
    while lo < hi:
        mid = (lo + hi) // 2
        if nums[mid] < target:
            lo = mid + 1
        else:
            hi = mid
    return lo


if __name__ == "__main__":
    print(search_insert([1, 3, 5, 6], 5))  # 2
    print(search_insert([1, 3, 5, 6], 2))  # 1
    print(search_insert([1, 3, 5, 6], 7))  # 4
    print(search_insert([1, 3, 5, 6], 0))  # 0
```

**Complexity:** Time O(log n), Space O(1).

---

### Problem 3: Find First and Last Position of Element in Sorted Array
**Statement:** Given a sorted array that may contain duplicates, find the starting and ending index of a given target. Return `[-1, -1]` if not found.

**Example:**
```
Input: nums = [5, 7, 7, 8, 8, 10], target = 8
Output: [3, 4]
```

**Approach:** Run binary search twice with slightly different tie-breaking rules: once biased to find the **leftmost** occurrence (keep going left even after finding a match), once biased to find the **rightmost** occurrence (keep going right after finding a match).

```python
def search_range(nums: list[int], target: int) -> list[int]:
    def find_bound(find_first: bool) -> int:
        lo, hi = 0, len(nums) - 1
        result = -1
        while lo <= hi:
            mid = (lo + hi) // 2
            if nums[mid] == target:
                result = mid
                if find_first:
                    hi = mid - 1  # keep searching left for an earlier match
                else:
                    lo = mid + 1  # keep searching right for a later match
            elif nums[mid] < target:
                lo = mid + 1
            else:
                hi = mid - 1
        return result

    first = find_bound(True)
    if first == -1:
        return [-1, -1]
    last = find_bound(False)
    return [first, last]


if __name__ == "__main__":
    print(search_range([5, 7, 7, 8, 8, 10], 8))  # [3, 4]
    print(search_range([5, 7, 7, 8, 8, 10], 6))  # [-1, -1]
    print(search_range([], 0))                    # [-1, -1]
```

**Complexity:** Time O(log n) (two binary searches), Space O(1).

---

### Problem 4: Search in Rotated Sorted Array
**Statement:** A sorted array has been rotated at some unknown pivot (e.g., `[0,1,2,4,5,6,7]` becomes `[4,5,6,7,0,1,2]`). Given the rotated array and a target, find its index in O(log n), or -1 if not found.

**Example:**
```
Input: nums = [4, 5, 6, 7, 0, 1, 2], target = 0
Output: 4
```

**Approach:** At every step, at least one half of `[lo, mid]` or `[mid, hi]` is guaranteed to be normally sorted (since only one rotation point exists). Check which half is sorted by comparing `nums[lo]` to `nums[mid]`. Then check if the target falls within that sorted half's range — if yes, search there; if no, search the other half.

```python
def search_rotated(nums: list[int], target: int) -> int:
    lo, hi = 0, len(nums) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if nums[mid] == target:
            return mid

        if nums[lo] <= nums[mid]:  # left half is sorted
            if nums[lo] <= target < nums[mid]:
                hi = mid - 1
            else:
                lo = mid + 1
        else:  # right half is sorted
            if nums[mid] < target <= nums[hi]:
                lo = mid + 1
            else:
                hi = mid - 1

    return -1


if __name__ == "__main__":
    print(search_rotated([4, 5, 6, 7, 0, 1, 2], 0))  # 4
    print(search_rotated([4, 5, 6, 7, 0, 1, 2], 3))  # -1
    print(search_rotated([1], 0))                     # -1
```

**Complexity:** Time O(log n), Space O(1).

---

### Problem 5: Find Minimum in Rotated Sorted Array
**Statement:** Given a rotated sorted array of unique elements, find the minimum element in O(log n).

**Example:**
```
Input: nums = [4, 5, 6, 7, 0, 1, 2]
Output: 0
```

**Approach:** The minimum is the "pivot point" — the only place where an element is smaller than its predecessor. Compare `nums[mid]` to `nums[hi]`: if `nums[mid] > nums[hi]`, the minimum must be to the right of `mid` (the rotation point is there). Otherwise, the minimum is at `mid` or to its left.

```python
def find_min(nums: list[int]) -> int:
    lo, hi = 0, len(nums) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if nums[mid] > nums[hi]:
            lo = mid + 1
        else:
            hi = mid
    return nums[lo]


if __name__ == "__main__":
    print(find_min([4, 5, 6, 7, 0, 1, 2]))  # 0
    print(find_min([3, 4, 5, 1, 2]))         # 1
    print(find_min([1, 2, 3, 4, 5]))         # 1 (not rotated)
```

**Complexity:** Time O(log n), Space O(1).

---

### Problem 6: Koko Eating Bananas (Binary Search on the Answer)
**Statement:** Koko has `piles` of bananas, and `h` hours to eat them all. Each hour, she picks one pile and eats up to `k` bananas from it (if the pile has fewer than `k`, she finishes it and the hour ends anyway). Find the minimum integer eating speed `k` such that she can eat all bananas within `h` hours.

**Example:**
```
Input: piles = [3, 6, 7, 11], h = 8
Output: 4
```

**Approach:** This is **binary search on the answer**, not on the array. The possible speeds `k` range from `1` to `max(piles)`. For a given speed, we can calculate exactly how many hours it takes (sum of `ceil(pile / k)` for each pile) — this check is monotonic: higher `k` always means fewer or equal hours needed. So we binary search for the smallest `k` where `hours_needed(k) <= h`.

```python
import math

def min_eating_speed(piles: list[int], h: int) -> int:
    def hours_needed(speed: int) -> int:
        return sum(math.ceil(pile / speed) for pile in piles)

    lo, hi = 1, max(piles)
    while lo < hi:
        mid = (lo + hi) // 2
        if hours_needed(mid) <= h:
            hi = mid        # mid works; try a smaller speed
        else:
            lo = mid + 1     # mid too slow; need a bigger speed
    return lo


if __name__ == "__main__":
    print(min_eating_speed([3, 6, 7, 11], 8))   # 4
    print(min_eating_speed([30, 11, 23, 4, 20], 5))  # 30
    print(min_eating_speed([30, 11, 23, 4, 20], 6))  # 23
```

**Complexity:** Time O(n log(max(piles))) — binary search does O(log(max(piles))) iterations, each costing O(n) to compute hours. Space O(1).

---

## 5. Complexity Summary

| Problem | Time | Space |
|---------|------|-------|
| Binary Search (Classic) | O(log n) | O(1) |
| Search Insert Position | O(log n) | O(1) |
| Find First and Last Position | O(log n) | O(1) |
| Search in Rotated Sorted Array | O(log n) | O(1) |
| Find Minimum in Rotated Sorted Array | O(log n) | O(1) |
| Koko Eating Bananas | O(n log(max value)) | O(1) |

---

## 6. Interview Tips

- **State your loop invariant before coding.** Say clearly: "`lo` and `hi` always bound a range that could contain the answer; I shrink it until it can't shrink anymore." This prevents off-by-one bugs and shows the interviewer you're thinking rigorously, not just pattern-matching.
- **Pick one template and stick to it.** There are many valid ways to write binary search (`lo <= hi` vs `lo < hi`, inclusive vs exclusive `hi`). Memorize one style per use case (exact match vs. boundary-finding) so you don't mix them mid-interview and introduce bugs.
- **Always double check the mid-point update.** A classic bug is writing `hi = mid` when it should be `hi = mid - 1` (or vice versa), causing infinite loops. Trace through a tiny 2-3 element example by hand before declaring the solution done.
- **For "binary search on the answer" problems, explicitly name the trick.** Say: "The direct search space is awkward, but the question 'can we achieve X in this budget?' is monotonic, so I can binary search over possible answers instead of over the array." This is often the single insight that separates candidates who solve Koko-style problems from those who get stuck.
- **Mention integer overflow habits (language-agnostic point).** In Python this isn't a real issue, but say "I'd normally use `lo + (hi - lo) // 2` instead of `(lo + hi) // 2` to avoid overflow in languages like Java or C++" — this is a small detail interviewers notice from experienced candidates.
