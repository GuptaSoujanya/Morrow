# Chapter 11: Tries & Bit Manipulation

## 1. Concept

A **trie** (prefix tree) is a tree where each path from the root spells out a prefix of some string. Nodes are shared between words with common prefixes, making prefix lookups extremely fast.

```
Trie storing: "cat", "car", "dog"

            root
           /    \
          c      d
          |      |
          a      o
         / \     |
        t   r    g
        *   *    *   <- * marks "end of word"

Looking up "car": root -> c -> a -> r (marked end) -> found!
Looking up "ca":  root -> c -> a (not marked end) -> prefix exists, but "ca" isn't a full word
```

**Bit manipulation** works directly on the binary representation of integers. A few operations come up again and again in interviews:

```
AND (&):  1010 & 1100 = 1000   (keeps bits set in both)
OR  (|):  1010 | 1100 = 1110   (keeps bits set in either)
XOR (^):  1010 ^ 1100 = 0110   (keeps bits set in exactly one — "difference" bits)
NOT (~):  ~1010      = ...0101 (flips every bit)
Left shift  (n << 1): multiply by 2
Right shift (n >> 1): divide by 2 (integer division)

n & (n - 1)   -> clears the lowest set bit (useful for counting set bits)
n & 1         -> checks if n is odd (lowest bit is 1)
x ^ x = 0     -> XOR-ing a number with itself cancels it out (key trick for "find the unique number")
```

## 2. When to Use This Pattern

- "Implement autocomplete / prefix search / word dictionary" → **trie**.
- "Check if a string is a prefix of any word in a set" → **trie**.
- "Find the single number that appears once / odd number of times" → **XOR trick**.
- "Count set bits," "check power of two," "swap without a temp variable" → bit tricks.
- Problem explicitly limits input to fixed-width integers (32-bit) or mentions binary representation.

## 3. Template / Skeleton Code

```python
class TrieNode:
    def __init__(self):
        self.children: dict[str, "TrieNode"] = {}
        self.is_end_of_word = False


class Trie:
    def __init__(self):
        self.root = TrieNode()

    def insert(self, word: str) -> None:
        node = self.root
        for char in word:
            if char not in node.children:
                node.children[char] = TrieNode()
            node = node.children[char]
        node.is_end_of_word = True

    def search(self, word: str) -> bool:
        node = self._traverse(word)
        return node is not None and node.is_end_of_word

    def starts_with(self, prefix: str) -> bool:
        return self._traverse(prefix) is not None

    def _traverse(self, s: str) -> "TrieNode | None":
        node = self.root
        for char in s:
            if char not in node.children:
                return None
            node = node.children[char]
        return node


def count_set_bits_template(n: int) -> int:
    count = 0
    while n:
        n &= n - 1  # clears the lowest set bit each time
        count += 1
    return count
```

---

## 4. Problems (Basic → Advanced)

### Problem 1: Single Number
**Statement:** Given a non-empty array where every element appears twice except for one, find that single one. Do it in O(n) time without extra memory.

**Example:**
```
Input: nums = [4, 1, 2, 1, 2]
Output: 4
```

**Approach:** XOR every number together. Since `a ^ a = 0` for any `a`, every pair cancels itself out, leaving only the number that appears once. Order doesn't matter because XOR is commutative and associative.

```python
def single_number(nums: list[int]) -> int:
    result = 0
    for num in nums:
        result ^= num
    return result


if __name__ == "__main__":
    print(single_number([4, 1, 2, 1, 2]))  # 4
    print(single_number([2, 2, 1]))         # 1
    print(single_number([1]))                # 1
```

**Complexity:** Time O(n), Space O(1).

---

### Problem 2: Number of 1 Bits (Hamming Weight)
**Statement:** Given an unsigned integer, return the number of `1` bits in its binary representation.

**Example:**
```
Input: n = 11   # binary: 1011
Output: 3
```

**Approach:** Repeatedly clear the lowest set bit using `n & (n - 1)`, counting how many times this is possible before `n` becomes 0. This is faster than checking every one of the 32 bits individually when there are few set bits, and never slower.

```python
def hamming_weight(n: int) -> int:
    count = 0
    while n:
        n &= n - 1  # clears the lowest set bit
        count += 1
    return count


if __name__ == "__main__":
    print(hamming_weight(11))  # 3  (1011)
    print(hamming_weight(128)) # 1  (10000000)
    print(hamming_weight(0))   # 0
```

**Complexity:** Time O(k) where k is the number of set bits (at most O(32) for a 32-bit integer). Space O(1).

---

### Problem 3: Counting Bits
**Statement:** Given an integer `n`, return an array `ans` of length `n + 1` where `ans[i]` is the number of `1` bits in the binary representation of `i`, for every `i` from 0 to `n`.

**Example:**
```
Input: n = 5
Output: [0, 1, 1, 2, 1, 2]
```

**Approach:** Instead of recomputing bit counts from scratch for every number (which would be O(n log n) total), reuse previous results: `ans[i] = ans[i >> 1] + (i & 1)`. This works because shifting `i` right by 1 removes its lowest bit, and `i & 1` tells us whether that removed bit was a 1.

```python
def count_bits(n: int) -> list[int]:
    ans = [0] * (n + 1)
    for i in range(1, n + 1):
        ans[i] = ans[i >> 1] + (i & 1)
    return ans


if __name__ == "__main__":
    print(count_bits(5))   # [0, 1, 1, 2, 1, 2]
    print(count_bits(0))   # [0]
    print(count_bits(2))   # [0, 1, 1]
```

**Complexity:** Time O(n), Space O(n).

---

### Problem 4: Implement Trie (Prefix Tree)
**Statement:** Implement a trie with `insert(word)`, `search(word)` (exact match), and `starts_with(prefix)` (prefix match).

**Example:**
```
trie = Trie()
trie.insert("apple")
trie.search("apple")       # True
trie.search("app")         # False (not inserted as a complete word)
trie.starts_with("app")    # True
```

**Approach:** Each `TrieNode` holds a dictionary mapping character → child node, plus a flag marking whether a complete word ends there. `insert` walks down the trie, creating nodes as needed. `search`/`starts_with` walk down the same way; the only difference is whether we also require the final node's `is_end_of_word` flag to be `True`.

```python
class TrieNode:
    def __init__(self):
        self.children: dict[str, "TrieNode"] = {}
        self.is_end_of_word = False


class Trie:
    def __init__(self):
        self.root = TrieNode()

    def insert(self, word: str) -> None:
        node = self.root
        for char in word:
            if char not in node.children:
                node.children[char] = TrieNode()
            node = node.children[char]
        node.is_end_of_word = True

    def search(self, word: str) -> bool:
        node = self._traverse(word)
        return node is not None and node.is_end_of_word

    def starts_with(self, prefix: str) -> bool:
        return self._traverse(prefix) is not None

    def _traverse(self, s: str) -> "TrieNode | None":
        node = self.root
        for char in s:
            if char not in node.children:
                return None
            node = node.children[char]
        return node


if __name__ == "__main__":
    trie = Trie()
    trie.insert("apple")
    print(trie.search("apple"))       # True
    print(trie.search("app"))         # False
    print(trie.starts_with("app"))    # True
    trie.insert("app")
    print(trie.search("app"))         # True
```

**Complexity:** Time O(L) per operation, where L is the word/prefix length. Space O(total characters inserted) in the worst case (no shared prefixes).

---

### Problem 5: Design Add and Search Words Data Structure (Trie + Wildcard)
**Statement:** Design a data structure supporting `add_word(word)` and `search(word)`, where `search` may contain `.` as a wildcard matching any single letter.

**Example:**
```
wd = WordDictionary()
wd.add_word("bad")
wd.add_word("dad")
wd.add_word("mad")
wd.search("pad")   # False
wd.search("bad")   # True
wd.search(".ad")   # True
wd.search("b..")   # True
```

**Approach:** Use a trie exactly like Problem 4, but make `search` a DFS: when the current character is `.`, try **every** child branch recursively (since it could match any letter), instead of following just one path. When the character is a normal letter, follow only that one path as usual.

```python
class TrieNode:
    def __init__(self):
        self.children: dict[str, "TrieNode"] = {}
        self.is_end_of_word = False


class WordDictionary:
    def __init__(self):
        self.root = TrieNode()

    def add_word(self, word: str) -> None:
        node = self.root
        for char in word:
            if char not in node.children:
                node.children[char] = TrieNode()
            node = node.children[char]
        node.is_end_of_word = True

    def search(self, word: str) -> bool:
        def dfs(node: TrieNode, index: int) -> bool:
            if index == len(word):
                return node.is_end_of_word

            char = word[index]
            if char == ".":
                for child in node.children.values():
                    if dfs(child, index + 1):
                        return True
                return False
            else:
                if char not in node.children:
                    return False
                return dfs(node.children[char], index + 1)

        return dfs(self.root, 0)


if __name__ == "__main__":
    wd = WordDictionary()
    wd.add_word("bad")
    wd.add_word("dad")
    wd.add_word("mad")
    print(wd.search("pad"))  # False
    print(wd.search("bad"))  # True
    print(wd.search(".ad"))  # True
    print(wd.search("b.."))  # True
```

**Complexity:** Time O(L) for `add_word`; `search` is O(26^d × L) worst case where d is the number of `.` wildcards (usually much faster in practice). Space O(total characters inserted).

---

### Problem 6: Sum of Two Integers (Bitwise Addition)
**Statement:** Given two integers, calculate their sum without using the `+` or `-` operators.

**Example:**
```
Input: a = 2, b = 3
Output: 5
```

**Approach:** Addition in binary is `XOR` (adds bits ignoring carry) plus a `carry` term (`AND` of the two numbers, shifted left by 1, representing where a carry was generated). Repeat: compute XOR as the "sum without carry," compute the carry, and keep adding the carry back in (via loop) until there's no carry left. Python integers are arbitrary-precision, so we mask with `0xFFFFFFFF` to simulate fixed 32-bit behavior, then convert back from unsigned to signed if needed.

```python
def get_sum(a: int, b: int) -> int:
    mask = 0xFFFFFFFF

    while b != 0:
        carry = (a & b) << 1
        a = (a ^ b) & mask
        b = carry & mask

    # Convert back to signed 32-bit if the result looks negative in two's complement
    if a > 0x7FFFFFFF:
        a = ~(a ^ mask)

    return a


if __name__ == "__main__":
    print(get_sum(2, 3))    # 5
    print(get_sum(-2, 3))   # 1
    print(get_sum(0, 0))    # 0
```

**Complexity:** Time O(1) — bounded by the fixed 32-bit width (at most 32 loop iterations). Space O(1).

---

## 5. Complexity Summary

| Problem | Time | Space |
|---------|------|-------|
| Single Number | O(n) | O(1) |
| Number of 1 Bits | O(k set bits) | O(1) |
| Counting Bits | O(n) | O(n) |
| Implement Trie | O(L) per op | O(total chars) |
| Add and Search Words (Trie + Wildcard) | O(L) add, O(26^d · L) search | O(total chars) |
| Sum of Two Integers | O(1) | O(1) |

---

## 6. Interview Tips

- **For XOR tricks, say the property you're relying on explicitly.** "XOR-ing a number with itself gives 0, and XOR is commutative/associative, so pairs cancel regardless of order" — this one sentence explains the entire Single Number solution and shows you're not just reciting a trick.
- **For tries, describe the node shape before coding.** Say: "Each node holds a map from character to child node, plus a boolean marking whether a complete word ends here" — this one sentence is the entire design, and stating it up front prevents confusion later when you check `is_end_of_word`.
- **Mention trie space tradeoffs.** Tries are time-efficient for prefix operations but can use more memory than a hash set of words, especially with little shared prefix structure. Knowing this tradeoff shows maturity beyond "just use a trie because the problem mentions prefixes."
- **For wildcard search in tries, name it as DFS with branching.** Say: "Normally I follow one child per character, but a wildcard means I need to explore every child at that position — this turns a straight-line walk into a DFS with branching."
- **For low-level bit manipulation (Sum of Two Integers), acknowledge Python's quirk.** Say: "Python integers don't overflow like fixed-width integers in other languages, so I mask with `0xFFFFFFFF` to simulate 32-bit behavior, and convert back from unsigned to signed at the end." This shows you understand *why* the masking step exists, not just that it's needed to pass test cases.
