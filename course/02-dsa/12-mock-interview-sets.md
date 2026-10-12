# Chapter 12: Mock Interview Sets

## How to Use This Chapter

This chapter is different from the others. Instead of teaching a pattern, it tests whether you can *apply* everything from Chapters 1–11 under realistic interview pressure.

### Rules for each mock set
1. **Set a real timer.** Each set below tells you the total time budget (typically 45–60 minutes for 3 problems, matching a real onsite/virtual round).
2. **No looking at the solutions in this course while solving.** Treat it like a real interview — you can use blank paper, a text editor, or an online compiler, but not the answer key.
3. **Talk out loud as you work**, even alone. Say your approach before coding. This is the single best habit for real interview performance.
4. **When time is up, stop — even if unfinished.** Then compare against the solution, and review what you missed.
5. After each set, run your code with the provided sample inputs to confirm it actually works, either locally (`python3 file.py`) or in [Programiz](https://www.programiz.com/python-programming/online-compiler/) / [Replit](https://replit.com/).

Each mock set mixes **easy, medium, and hard** difficulty, which mirrors how most real interview loops are structured (rarely all-hard, rarely all-easy).

---

## Mock Set 1 — Time Budget: 45 minutes (Arrays, Hashing, Trees)

### Problem 1 (Easy, ~10 min): Majority Element
**Statement:** Given an array of size `n`, return the majority element — the element that appears more than `n / 2` times. It's guaranteed to always exist.

**Example:**
```
Input: nums = [2, 2, 1, 1, 1, 2, 2]
Output: 2
```

**Approach:** Use the **Boyer-Moore Voting Algorithm**: keep a `candidate` and a `count`. Walk through the array; if the current number matches the candidate, increment count; otherwise decrement it. If count hits 0, switch the candidate to the current number and reset count to 1. Because the majority element appears more than half the time, it always wins out by the end.

```python
def majority_element(nums: list[int]) -> int:
    candidate = None
    count = 0

    for num in nums:
        if count == 0:
            candidate = num
        count += 1 if num == candidate else -1

    return candidate


if __name__ == "__main__":
    print(majority_element([2, 2, 1, 1, 1, 2, 2]))  # 2
    print(majority_element([3, 2, 3]))                # 3
    print(majority_element([1]))                       # 1
```

**Complexity:** Time O(n), Space O(1).

---

### Problem 2 (Medium, ~15 min): Longest Substring with At Most K Distinct Characters
**Statement:** Given a string `s` and an integer `k`, find the length of the longest substring that contains at most `k` distinct characters.

**Example:**
```
Input: s = "eceba", k = 2
Output: 3   # "ece"
```

**Approach:** Sliding window with a character-count hash map. Expand the window to the right, adding characters to the map. Whenever the map has more than `k` distinct keys, shrink from the left (decrementing counts, removing keys that hit zero) until it's valid again. Track the max window size seen.

```python
def length_of_longest_substring_k_distinct(s: str, k: int) -> int:
    if k == 0 or not s:
        return 0

    char_count: dict[str, int] = {}
    left = 0
    best = 0

    for right, char in enumerate(s):
        char_count[char] = char_count.get(char, 0) + 1

        while len(char_count) > k:
            left_char = s[left]
            char_count[left_char] -= 1
            if char_count[left_char] == 0:
                del char_count[left_char]
            left += 1

        best = max(best, right - left + 1)

    return best


if __name__ == "__main__":
    print(length_of_longest_substring_k_distinct("eceba", 2))  # 3
    print(length_of_longest_substring_k_distinct("aa", 1))      # 2
    print(length_of_longest_substring_k_distinct("a", 0))       # 0
```

**Complexity:** Time O(n), Space O(k).

---

### Problem 3 (Hard, ~20 min): Serialize and Deserialize Binary Tree
**Statement:** Design an algorithm to serialize a binary tree to a string, and deserialize that string back to the original tree structure.

**Example:**
```
Input tree:    1
              / \
             2   3
                / \
               4   5
Serialized:  "1,2,null,null,3,4,null,null,5,null,null"  (format may vary)
```

**Approach:** Use preorder traversal (root, then left, then right) for serialization, writing `"null"` for missing children explicitly — this is essential, since without markers for missing children, we can't unambiguously reconstruct the tree shape. For deserialization, process the comma-split values in the exact same preorder sequence, consuming one value at a time recursively.

```python
class TreeNode:
    def __init__(self, val=0, left=None, right=None):
        self.val = val
        self.left = left
        self.right = right


class Codec:
    def serialize(self, root: TreeNode | None) -> str:
        values: list[str] = []

        def dfs(node: TreeNode | None) -> None:
            if node is None:
                values.append("null")
                return
            values.append(str(node.val))
            dfs(node.left)
            dfs(node.right)

        dfs(root)
        return ",".join(values)

    def deserialize(self, data: str) -> TreeNode | None:
        values = iter(data.split(","))

        def build() -> TreeNode | None:
            val = next(values)
            if val == "null":
                return None
            node = TreeNode(int(val))
            node.left = build()
            node.right = build()
            return node

        return build()


if __name__ == "__main__":
    codec = Codec()
    root = TreeNode(1, TreeNode(2), TreeNode(3, TreeNode(4), TreeNode(5)))

    serialized = codec.serialize(root)
    print(serialized)  # 1,2,null,null,3,4,null,null,5,null,null

    rebuilt = codec.deserialize(serialized)
    print(rebuilt.val, rebuilt.left.val, rebuilt.right.val)  # 1 2 3
    print(rebuilt.right.left.val, rebuilt.right.right.val)     # 4 5
```

**Complexity:** Time O(n) for both serialize and deserialize, Space O(n).

---

## Mock Set 2 — Time Budget: 50 minutes (Graphs, DP, Heaps)

### Problem 1 (Easy, ~10 min): Flood Fill
**Statement:** Given an image (2D grid of integers), a starting pixel `(sr, sc)`, and a `new_color`, perform a flood fill: change the starting pixel's color and every connected pixel (4-directionally) with the same original color, to `new_color`.

**Example:**
```
Input: image = [[1,1,1],[1,1,0],[1,0,1]], sr=1, sc=1, new_color=2
Output: [[2,2,2],[2,2,0],[2,0,1]]
```

**Approach:** Classic graph/grid DFS. Remember the original color at the start. DFS outward, repainting any adjacent pixel that still has the original color. Stop expanding when a pixel has a different color (boundary) or is already repainted.

```python
def flood_fill(image: list[list[int]], sr: int, sc: int, new_color: int) -> list[list[int]]:
    rows, cols = len(image), len(image[0])
    original_color = image[sr][sc]

    if original_color == new_color:
        return image

    def dfs(r: int, c: int) -> None:
        if r < 0 or r >= rows or c < 0 or c >= cols or image[r][c] != original_color:
            return
        image[r][c] = new_color
        dfs(r + 1, c)
        dfs(r - 1, c)
        dfs(r, c + 1)
        dfs(r, c - 1)

    dfs(sr, sc)
    return image


if __name__ == "__main__":
    image = [[1, 1, 1], [1, 1, 0], [1, 0, 1]]
    print(flood_fill(image, 1, 1, 2))  # [[2,2,2],[2,2,0],[2,0,1]]
```

**Complexity:** Time O(rows × cols), Space O(rows × cols) for recursion stack worst case.

---

### Problem 2 (Medium, ~18 min): Unique Paths with Obstacles
**Statement:** A robot starts at the top-left of an `m x n` grid and wants to reach the bottom-right, moving only right or down. Some cells contain obstacles (marked `1`) which the robot cannot enter. Return the number of unique paths.

**Example:**
```
Input: obstacleGrid = [[0,0,0],[0,1,0],[0,0,0]]
Output: 2
```

**Approach:** 2D DP. `dp[r][c]` = number of ways to reach cell `(r, c)`. If a cell is an obstacle, `dp[r][c] = 0` (unreachable). Otherwise, it's the sum of ways to reach it from above and from the left. Base case: the start cell has exactly 1 way to be "reached" (itself), assuming it isn't blocked.

```python
def unique_paths_with_obstacles(obstacle_grid: list[list[int]]) -> int:
    rows, cols = len(obstacle_grid), len(obstacle_grid[0])
    dp = [[0] * cols for _ in range(rows)]

    for r in range(rows):
        for c in range(cols):
            if obstacle_grid[r][c] == 1:
                dp[r][c] = 0
            elif r == 0 and c == 0:
                dp[r][c] = 1
            else:
                from_top = dp[r - 1][c] if r > 0 else 0
                from_left = dp[r][c - 1] if c > 0 else 0
                dp[r][c] = from_top + from_left

    return dp[rows - 1][cols - 1]


if __name__ == "__main__":
    print(unique_paths_with_obstacles([[0, 0, 0], [0, 1, 0], [0, 0, 0]]))  # 2
    print(unique_paths_with_obstacles([[0, 1], [0, 0]]))                     # 1
    print(unique_paths_with_obstacles([[1, 0]]))                             # 0
```

**Complexity:** Time O(rows × cols), Space O(rows × cols) (can be optimized to O(cols)).

---

### Problem 3 (Hard, ~22 min): Cheapest Flights Within K Stops
**Statement:** `n` cities connected by flights `[from, to, price]`. Given a source, destination, and a maximum number of stops `k`, find the cheapest price to travel from source to destination using at most `k` stops. Return `-1` if impossible.

**Example:**
```
Input: n = 4, flights = [[0,1,100],[1,2,100],[2,0,100],[1,3,600],[2,3,200]],
       src = 0, dst = 3, k = 1
Output: 700   # 0 -> 1 -> 3
```

**Approach:** Modified Dijkstra/BFS: a normal shortest-path algorithm doesn't track "number of stops used," so it can wrongly dismiss a more expensive-but-fewer-stops path too early. Use a min-heap keyed by `(cost, node, stops_used)`, and allow revisiting a node with a *different* stop count if it might still lead to a better answer within the stop limit. Stop expanding once stops used exceeds `k`.

```python
import heapq

def find_cheapest_price(n: int, flights: list[list[int]], src: int, dst: int, k: int) -> int:
    graph: dict[int, list[tuple[int, int]]] = {i: [] for i in range(n)}
    for u, v, price in flights:
        graph[u].append((v, price))

    # (cost, node, stops_used_so_far)
    min_heap = [(0, src, 0)]

    while min_heap:
        cost, node, stops = heapq.heappop(min_heap)

        if node == dst:
            return cost

        if stops > k:
            continue

        for neighbor, price in graph[node]:
            heapq.heappush(min_heap, (cost + price, neighbor, stops + 1))

    return -1


if __name__ == "__main__":
    flights = [[0, 1, 100], [1, 2, 100], [2, 0, 100], [1, 3, 600], [2, 3, 200]]
    print(find_cheapest_price(4, flights, 0, 3, 1))  # 700
    print(find_cheapest_price(4, flights, 0, 3, 0))  # -1  (can't make it with 0 stops)
```

**Complexity:** Time O(E · k · log(E · k)) in the worst case (heap can hold many (node, stops) states). Space O(E · k).

---

## Mock Set 3 — Time Budget: 60 minutes (Backtracking, DP, Greedy — Hardest Set)

### Problem 1 (Easy, ~10 min): Maximum Subarray (Kadane's Algorithm)
**Statement:** Given an integer array, find the contiguous subarray with the largest sum, and return that sum.

**Example:**
```
Input: nums = [-2, 1, -3, 4, -1, 2, 1, -5, 4]
Output: 6   # [4, -1, 2, 1]
```

**Approach:** Kadane's algorithm — a simple 1D DP. Track the best sum ending exactly at the current index: either extend the previous subarray (if it was positive and growing) or start fresh at the current element (if the running sum went negative, continuing with it would only hurt). Keep a separate running maximum across all positions.

```python
def max_sub_array(nums: list[int]) -> int:
    current_sum = nums[0]
    best_sum = nums[0]

    for num in nums[1:]:
        current_sum = max(num, current_sum + num)
        best_sum = max(best_sum, current_sum)

    return best_sum


if __name__ == "__main__":
    print(max_sub_array([-2, 1, -3, 4, -1, 2, 1, -5, 4]))  # 6
    print(max_sub_array([1]))                                # 1
    print(max_sub_array([5, 4, -1, 7, 8]))                    # 23
```

**Complexity:** Time O(n), Space O(1).

---

### Problem 2 (Medium, ~20 min): Letter Combinations of a Phone Number
**Statement:** Given a string of digits 2-9, return all possible letter combinations the number could represent, based on a standard phone keypad mapping.

**Example:**
```
Input: digits = "23"
Output: ["ad","ae","af","bd","be","bf","cd","ce","cf"]
```

**Approach:** Backtracking. For each digit, try every letter it maps to, append it to the current path, recurse to the next digit, then remove it (backtrack) before trying the next letter. When the path length equals the number of digits, it's a complete combination.

```python
def letter_combinations(digits: str) -> list[str]:
    if not digits:
        return []

    digit_to_letters = {
        "2": "abc", "3": "def", "4": "ghi", "5": "jkl",
        "6": "mno", "7": "pqrs", "8": "tuv", "9": "wxyz",
    }

    results: list[str] = []
    path: list[str] = []

    def backtrack(index: int) -> None:
        if index == len(digits):
            results.append("".join(path))
            return

        for letter in digit_to_letters[digits[index]]:
            path.append(letter)
            backtrack(index + 1)
            path.pop()

    backtrack(0)
    return results


if __name__ == "__main__":
    print(letter_combinations("23"))
    # ['ad','ae','af','bd','be','bf','cd','ce','cf']
    print(letter_combinations(""))   # []
    print(letter_combinations("2"))  # ['a', 'b', 'c']
```

**Complexity:** Time O(4ⁿ · n) worst case (digits like 7 and 9 map to 4 letters), Space O(n) for recursion depth.

---

### Problem 3 (Hard, ~30 min): Word Break II
**Statement:** Given a string `s` and a dictionary of words, return all possible sentences where `s` can be segmented into a space-separated sequence of dictionary words.

**Example:**
```
Input: s = "catsanddog", wordDict = ["cat","cats","and","sand","dog"]
Output: ["cats and dog", "cat sand dog"]
```

**Approach:** Backtracking **with memoization** (this combination is sometimes called "memoized backtracking" or DP-on-trees-of-choices). For each starting index, try every dictionary word that matches the string starting there; if it matches, recursively solve the rest of the string. Cache results per starting index so overlapping sub-problems (the same suffix reached via different paths) aren't recomputed — this is critical, since plain backtracking alone would be exponential and too slow for larger inputs.

```python
def word_break(s: str, word_dict: list[str]) -> list[str]:
    word_set = set(word_dict)
    memo: dict[int, list[str]] = {}

    def backtrack(start: int) -> list[str]:
        if start == len(s):
            return [""]  # one way to "complete" with an empty remainder

        if start in memo:
            return memo[start]

        sentences: list[str] = []
        for end in range(start + 1, len(s) + 1):
            word = s[start:end]
            if word in word_set:
                for rest in backtrack(end):
                    sentence = word if rest == "" else word + " " + rest
                    sentences.append(sentence)

        memo[start] = sentences
        return sentences

    return backtrack(0)


if __name__ == "__main__":
    result = word_break("catsanddog", ["cat", "cats", "and", "sand", "dog"])
    print(sorted(result))
    # ['cat sand dog', 'cats and dog']

    print(word_break("pineapplepenapple",
                      ["apple", "pen", "applepen", "pine", "pineapple"]))
    # ['pine apple pen apple', 'pine applepen apple', 'pineapple pen apple']

    print(word_break("catsandog", ["cats", "dog", "sand", "and", "cat"]))
    # []  (no valid segmentation)
```

**Complexity:** Time O(n³) in the worst case (n starting points, n substring lengths, n for string slicing/joining), Space O(n²) for the memo cache in the worst case (many overlapping suffixes with multiple sentence results each).

---

## Top 30 Most-Asked FAANG Questions — Pattern Mapping Table

Use this table as a final review checklist. If you can solve every problem in the "Where Covered" column from memory, you're in excellent shape for most FAANG-style interviews.

| # | Problem | Pattern | Where Covered |
|---|---------|---------|----------------|
| 1 | Two Sum | Hashing | 01-arrays-strings-hashing.md |
| 2 | Contains Duplicate | Hashing | 01-arrays-strings-hashing.md |
| 3 | Group Anagrams | Hashing | 01-arrays-strings-hashing.md |
| 4 | Product of Array Except Self | Prefix/Suffix Products | 01-arrays-strings-hashing.md |
| 5 | Longest Consecutive Sequence | Hashing | 01-arrays-strings-hashing.md |
| 6 | Valid Palindrome | Two Pointers | 02-two-pointers-sliding-window.md |
| 7 | 3Sum | Two Pointers | 02-two-pointers-sliding-window.md |
| 8 | Best Time to Buy and Sell Stock | Sliding Window | 02-two-pointers-sliding-window.md |
| 9 | Longest Substring Without Repeating Characters | Sliding Window | 02-two-pointers-sliding-window.md |
| 10 | Minimum Window Substring | Sliding Window | 02-two-pointers-sliding-window.md |
| 11 | Valid Parentheses | Stack | 03-stack-queue-linkedlist.md |
| 12 | Reverse Linked List | Linked List | 03-stack-queue-linkedlist.md |
| 13 | Merge Two Sorted Lists | Linked List | 03-stack-queue-linkedlist.md |
| 14 | Linked List Cycle | Fast/Slow Pointers | 03-stack-queue-linkedlist.md |
| 15 | LRU Cache | Hash Map + Doubly Linked List | 03-stack-queue-linkedlist.md |
| 16 | Binary Search | Binary Search | 04-binary-search.md |
| 17 | Search in Rotated Sorted Array | Binary Search | 04-binary-search.md |
| 18 | Maximum Depth of Binary Tree | Tree DFS | 05-trees-bst.md |
| 19 | Validate Binary Search Tree | Tree DFS + BST Property | 05-trees-bst.md |
| 20 | Binary Tree Level Order Traversal | Tree BFS | 05-trees-bst.md |
| 21 | Kth Largest Element in an Array | Heap | 06-heaps-priority-queues.md |
| 22 | Merge K Sorted Lists | Heap | 06-heaps-priority-queues.md |
| 23 | Number of Islands | Graph DFS/BFS | 07-graphs.md |
| 24 | Course Schedule | Topological Sort | 07-graphs.md |
| 25 | Clone Graph | Graph DFS | 07-graphs.md |
| 26 | Subsets | Backtracking | 08-backtracking.md |
| 27 | Word Search | Backtracking | 08-backtracking.md |
| 28 | Climbing Stairs | 1D DP | 09-dynamic-programming.md |
| 29 | Coin Change | DP (Unbounded Knapsack) | 09-dynamic-programming.md |
| 30 | Longest Common Subsequence | 2D DP | 09-dynamic-programming.md |

### How to Use This Table for Final Review
1. Cover the "Pattern" and "Where Covered" columns.
2. For each problem name, say out loud: which pattern it belongs to, and sketch the approach from memory.
3. Only then check your answer against the table and the relevant chapter.
4. If you get 25+ of these right from memory without hesitation, you are well prepared for the vast majority of FAANG-style DSA interview rounds.

---

## Final Words

You've now covered 12 chapters, 70+ fully solved problems, and 3 timed mock interview sets. The patterns in this course — hashing, two pointers, sliding window, stacks/queues, linked lists, binary search, trees, heaps, graphs, backtracking, DP, greedy, tries, and bit manipulation — cover the overwhelming majority of what real interviews at top tech companies ask.

From here, the best use of your remaining prep time is **repetition under time pressure**, not more new material:
- Redo this course's problems from memory, especially ones you struggled with.
- Pull similar problems from LeetCode by pattern (use the "Where Covered" table above as a search guide) and time yourself.
- Practice explaining your approach out loud before coding — this is often what separates a "good" interview from a "great" one.

Good luck.
