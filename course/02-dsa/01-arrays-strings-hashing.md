# Chapter 1: Arrays, Strings & Hashing

## 1. Concept

Arrays and strings are the most basic data structures: a contiguous block of items you can index into directly. A **hash map** (dictionary in Python) lets you store key→value pairs and look them up in roughly constant time, no matter how big the collection gets.

```
Array (indexing is O(1)):
 index:  0    1    2    3    4
        [10,  22,   7,  15,   3]

Hash Map (lookup is O(1) average):
  key -> value
 "apple"  -> 3
 "banana" -> 7
 "cherry" -> 1

 Internally, Python hashes the key to find a "bucket" directly,
 instead of scanning every entry.
  hash("apple") -> bucket 4 -> ("apple", 3)
  hash("banana")-> bucket 1 -> ("banana", 7)
```

The single most important interview insight in this chapter: **whenever you find yourself writing a nested loop to check "have I seen this value before?", stop and ask if a hash map/set can replace the inner loop.** This usually takes an O(n²) solution down to O(n).

## 2. When to Use This Pattern

Look for these signals in a problem:
- "Find if a pair/duplicate exists" → use a **set**.
- "Count frequency of elements" → use a **hash map** (`dict` or `collections.Counter`).
- "Group items by some property" (anagrams, same remainder, etc.) → hash map of lists.
- "Have I seen this before while scanning left to right?" → hash map storing last-seen index.
- Problems about substrings/subarrays with a condition on *distinct* elements → hash map tracking counts.

## 3. Template / Skeleton Code

```python
from collections import defaultdict, Counter

def two_sum_template(nums: list[int], target: int) -> list[int]:
    """General shape: scan once, remember what you've seen in a hash map."""
    seen: dict[int, int] = {}  # value -> index
    for i, num in enumerate(nums):
        complement = target - num
        if complement in seen:
            return [seen[complement], i]
        seen[num] = i
    return []


def group_by_key_template(items: list[str]) -> dict[str, list[str]]:
    """General shape: compute a 'signature' for each item, group by it."""
    groups: dict[str, list[str]] = defaultdict(list)
    for item in items:
        signature = "".join(sorted(item))  # example signature
        groups[signature].append(item)
    return groups
```

---

## 4. Problems (Basic → Advanced)

### Problem 1: Contains Duplicate
**Statement:** Given an array of integers, return `True` if any value appears at least twice, `False` otherwise.
(LeetCode: "Contains Duplicate")

**Example:**
```
Input: nums = [1, 2, 3, 1]
Output: True

Input: nums = [1, 2, 3, 4]
Output: False
```

**Approach:** Walk through the array once, adding each number to a set. If a number is already in the set, we found a duplicate. A set gives O(1) average lookup, so the whole scan is O(n).

```python
def contains_duplicate(nums: list[int]) -> bool:
    seen = set()
    for num in nums:
        if num in seen:
            return True
        seen.add(num)
    return False


if __name__ == "__main__":
    print(contains_duplicate([1, 2, 3, 1]))   # True
    print(contains_duplicate([1, 2, 3, 4]))   # False
    print(contains_duplicate([]))             # False
```

**Complexity:** Time O(n), Space O(n) (for the set in the worst case).

---

### Problem 2: Valid Anagram
**Statement:** Given two strings `s` and `t`, return `True` if `t` is an anagram of `s` (same letters, same counts, different order allowed).

**Example:**
```
Input: s = "anagram", t = "nagaram"
Output: True

Input: s = "rat", t = "car"
Output: False
```

**Approach:** Two strings are anagrams if and only if they have exactly the same letter frequency. Count the letters of `s` into a hash map, then subtract the letters of `t`. If any count goes negative or doesn't reach zero, they're not anagrams.

```python
from collections import Counter

def is_anagram(s: str, t: str) -> bool:
    if len(s) != len(t):
        return False
    return Counter(s) == Counter(t)


if __name__ == "__main__":
    print(is_anagram("anagram", "nagaram"))  # True
    print(is_anagram("rat", "car"))          # False
```

**Complexity:** Time O(n), Space O(1) (at most 26 lowercase letters, so the Counter size is bounded).

---

### Problem 3: Two Sum
**Statement:** Given an array of integers `nums` and an integer `target`, return the indices of the two numbers that add up to `target`. Assume exactly one valid answer exists, and you cannot use the same element twice.

**Example:**
```
Input: nums = [2, 7, 11, 15], target = 9
Output: [0, 1]   # nums[0] + nums[1] = 2 + 7 = 9
```

**Approach:** Brute force checks every pair — O(n²). Instead, scan once: for each number, compute what its "complement" (target - number) would need to be. Check a hash map to see if we've already seen that complement. If yes, we found our pair instantly. If no, store the current number's index for future lookups.

```python
def two_sum(nums: list[int], target: int) -> list[int]:
    seen: dict[int, int] = {}  # value -> index
    for i, num in enumerate(nums):
        complement = target - num
        if complement in seen:
            return [seen[complement], i]
        seen[num] = i
    return []  # no solution found


if __name__ == "__main__":
    print(two_sum([2, 7, 11, 15], 9))  # [0, 1]
    print(two_sum([3, 2, 4], 6))       # [1, 2]
    print(two_sum([3, 3], 6))          # [0, 1]
```

**Complexity:** Time O(n), Space O(n).

---

### Problem 4: Group Anagrams
**Statement:** Given an array of strings, group the anagrams together. Return the groups in any order.

**Example:**
```
Input: strs = ["eat","tea","tan","ate","nat","bat"]
Output: [["eat","tea","ate"], ["tan","nat"], ["bat"]]
```

**Approach:** Two words are anagrams if, when sorted, they produce the identical string. So we use that sorted string as a "signature" / key in a hash map, and append every word to the list under its signature.

```python
from collections import defaultdict

def group_anagrams(strs: list[str]) -> list[list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for word in strs:
        signature = "".join(sorted(word))
        groups[signature].append(word)
    return list(groups.values())


if __name__ == "__main__":
    result = group_anagrams(["eat", "tea", "tan", "ate", "nat", "bat"])
    for group in result:
        print(group)
    # ['eat', 'tea', 'ate']
    # ['tan', 'nat']
    # ['bat']
```

**Complexity:** Time O(n * k log k) where n = number of words, k = max word length (for sorting each word). Space O(n * k).

---

### Problem 5: Top K Frequent Elements
**Statement:** Given an integer array `nums` and an integer `k`, return the `k` most frequent elements.

**Example:**
```
Input: nums = [1, 1, 1, 2, 2, 3], k = 2
Output: [1, 2]
```

**Approach:** First count frequency with a hash map. A naive approach sorts all elements by frequency — O(n log n). A faster approach, **bucket sort by frequency**, places each number into a bucket indexed by its count (counts can range 1..n), then reads off the top buckets from the highest count downward. This is O(n) overall.

```python
def top_k_frequent(nums: list[int], k: int) -> list[int]:
    count: dict[int, int] = {}
    for num in nums:
        count[num] = count.get(num, 0) + 1

    # buckets[i] = list of numbers that appear exactly i times
    buckets: list[list[int]] = [[] for _ in range(len(nums) + 1)]
    for num, freq in count.items():
        buckets[freq].append(num)

    result: list[int] = []
    for freq in range(len(buckets) - 1, 0, -1):
        for num in buckets[freq]:
            result.append(num)
            if len(result) == k:
                return result
    return result


if __name__ == "__main__":
    print(top_k_frequent([1, 1, 1, 2, 2, 3], 2))  # [1, 2]
    print(top_k_frequent([1], 1))                  # [1]
```

**Complexity:** Time O(n), Space O(n).

---

### Problem 6: Product of Array Except Self
**Statement:** Given an integer array `nums`, return an array `answer` where `answer[i]` is the product of all elements of `nums` except `nums[i]`. Do this without using division, in O(n) time.

**Example:**
```
Input: nums = [1, 2, 3, 4]
Output: [24, 12, 8, 6]
```

**Approach:** For each index `i`, the answer is (product of everything to its left) × (product of everything to its right). Compute a "prefix product" array (product of all elements before `i`), then sweep from the right accumulating a running "suffix product," multiplying it into the answer as you go. This avoids needing a separate suffix array (keeps space O(1) extra, excluding output).

```python
def product_except_self(nums: list[int]) -> list[int]:
    n = len(nums)
    answer = [1] * n

    # Left pass: answer[i] = product of all elements to the left of i
    prefix = 1
    for i in range(n):
        answer[i] = prefix
        prefix *= nums[i]

    # Right pass: multiply in the product of all elements to the right of i
    suffix = 1
    for i in range(n - 1, -1, -1):
        answer[i] *= suffix
        suffix *= nums[i]

    return answer


if __name__ == "__main__":
    print(product_except_self([1, 2, 3, 4]))   # [24, 12, 8, 6]
    print(product_except_self([-1, 1, 0, -3, 3]))  # [0, 0, 9, 0, 0]
```

**Complexity:** Time O(n), Space O(1) extra (not counting the output array).

---

### Problem 7: Longest Consecutive Sequence
**Statement:** Given an unsorted array of integers, find the length of the longest run of consecutive integers (they don't need to be adjacent in the array). Do this in O(n) time.

**Example:**
```
Input: nums = [100, 4, 200, 1, 3, 2]
Output: 4   # The sequence is 1, 2, 3, 4
```

**Approach:** Put all numbers in a set for O(1) lookup. For each number, only start counting a sequence if it is the *start* of a sequence — meaning `num - 1` is NOT in the set. This avoids re-counting the same sequence multiple times (which would make it O(n²) if we started from every number). From a valid start, keep checking `num + 1`, `num + 2`, ... while they exist in the set.

```python
def longest_consecutive(nums: list[int]) -> int:
    num_set = set(nums)
    longest = 0

    for num in num_set:
        # Only count from the start of a sequence
        if num - 1 not in num_set:
            length = 1
            while num + length in num_set:
                length += 1
            longest = max(longest, length)

    return longest


if __name__ == "__main__":
    print(longest_consecutive([100, 4, 200, 1, 3, 2]))  # 4
    print(longest_consecutive([0, 3, 7, 2, 5, 8, 4, 6, 0, 1]))  # 9
    print(longest_consecutive([]))  # 0
```

**Complexity:** Time O(n) — every number is only ever the start of a sequence walk once, across all iterations combined. Space O(n).

---

## 5. Complexity Summary

| Problem | Time | Space |
|---------|------|-------|
| Contains Duplicate | O(n) | O(n) |
| Valid Anagram | O(n) | O(1) |
| Two Sum | O(n) | O(n) |
| Group Anagrams | O(n·k log k) | O(n·k) |
| Top K Frequent Elements | O(n) | O(n) |
| Product of Array Except Self | O(n) | O(1) extra |
| Longest Consecutive Sequence | O(n) | O(n) |

---

## 6. Interview Tips

- **Say the brute force first, out loud.** For almost every problem here, the brute force is a nested loop (O(n²)). Naming it shows you understand the problem, and it sets up your improvement: "I could check every pair, but that's O(n²) — I can do better with a hash map."
- **Narrate your hash map's purpose.** Don't just write `seen = {}`. Say what it stores and why: "I'll use this dictionary to remember, for every number I've already visited, what index it was at."
- **Watch for the "signature" idea.** Group Anagrams and similar problems hinge on finding some computed value (sorted string, character count tuple) that is identical for all items in the same group. Interviewers love seeing you identify this on your own.
- **Clarify duplicates and edge cases up front.** Ask: "Can the array be empty? Can there be duplicate values? Is there guaranteed to be exactly one answer?" This avoids wasted time and shows rigor.
- **Mention average vs. worst case for hash maps.** Python dict/set lookups are O(1) *average* case, but worst case (hash collisions) is O(n). Knowing this detail impresses interviewers without needing to over-explain it.
